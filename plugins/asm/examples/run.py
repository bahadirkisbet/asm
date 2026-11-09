#!/usr/bin/env python3
"""Runnable local workflows: real ASM, synthetic credentials, ephemeral storage."""
import argparse
import contextlib
import http.server
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading

from mcp_client import MCPClient, assert_clean

ROOT = Path(__file__).resolve().parents[1]


@contextlib.contextmanager
def local_api(token):
    state = {"authenticated": False}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Never put request headers or token-bearing bodies in logs.

        def do_GET(self):
            if self.path == "/issue":
                code, body = 200, {"access_token": token}
            elif self.path == "/verify":
                state["authenticated"] = self.headers.get("Authorization") == "Bearer " + token
                code = 200 if state["authenticated"] else 401
                body = {"authenticated": state["authenticated"]}
            else:
                code, body = 404, {"error": "not_found"}
            encoded = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    class Server(http.server.HTTPServer):
        def handle_error(self, *_):
            state["failed"] = True

    with Server(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield "http://127.0.0.1:" + str(server.server_port), state
        finally:
            server.shutdown()
            thread.join(timeout=5)
            if thread.is_alive():
                raise RuntimeError("example_server_cleanup_failed")
            if state.get("failed"):
                raise RuntimeError("example_server_failed")


def run(name, binary, show_config=False):
    with tempfile.TemporaryDirectory(prefix="asm-example-") as temporary, contextlib.ExitStack() as stack:
        directory = Path(temporary)
        fixture_token = secrets.token_urlsafe(32)
        label = "staging" if name == "http" else "development"
        definition = {"description": "Synthetic " + name + " example token", "environment": label}
        config = {"namespace": "asm-example-" + name, "secrets": {"service-token": definition}, "operations": {}}

        if name == "file":
            source = directory / "source.json"
            with source.open("x") as file:
                source.chmod(0o600)
                json.dump({"access_token": fixture_token}, file)
            capture = {"kind": "file", "path": "source.json", "json_pointer": "/access_token"}
            delivery = {"kind": "file", "path": "delivered-token"}
        elif name == "cli":
            command = {"program": sys.executable, "cwd": str(directory), "args": [str(Path(__file__).with_name("provider.py").resolve()), "issue"]}
            capture = {"kind": "command", "command": command, "json_pointer": "/access_token"}
            delivery = {"kind": "command", "variable": "SERVICE_TOKEN", "command": {**command, "args": [command["args"][0], "verify"]}}
        else:
            url, state = stack.enter_context(local_api(fixture_token))
            config["allow_http_loopback"] = True
            capture = {"kind": "http", "request": {"url": url + "/issue"}, "json_pointer": "/access_token"}
            delivery = {"kind": "http", "request": {"url": url + "/verify"}, "placement": {"kind": "header", "name": "Authorization", "prefix": "Bearer "}}

        config["operations"] = {
            "capture-token": {"kind": "capture", "secret": "service-token", "source": capture},
            "use-token": {"kind": "deliver", "secret": "service-token", "destination": delivery},
        }
        path = directory / "operations.json"
        path.write_text(json.dumps(config))
        client = MCPClient(binary, path, os.environ.copy())
        try:
            catalog = json.loads(client.call("tools/call", {"name": "asm_catalog", "arguments": {}})["content"][0]["text"])
            assert catalog["secrets"][0]["environment"] == label
            results = [client.execute("capture-token"), client.execute("use-token")]
            assert all(item["environment"] == label for item in results)
            if name == "file":
                assert (directory / "delivered-token").read_text() == fixture_token
                assert (directory / "delivered-token").stat().st_mode & 0o777 == 0o600
            elif name == "cli":
                fixture_token = json.loads((directory / "issued.json").read_text())["access_token"]
            else:
                assert state["authenticated"], "Provider did not authenticate the delivered credential"
        finally:
            client.close()
        assert_clean(client.transcript, [fixture_token])
        # Output is prepared only after verification; never print upstream data.
        output = {"example": name, "environment": label, "steps": results, "verified": True, "secret_values_printed": False}
        if show_config:
            output["config"] = config
        return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("example", choices=["file", "cli", "http", "all"], nargs="?", default="all")
    parser.add_argument("--binary", type=Path, help="Optional ASM executable or plugin launcher")
    parser.add_argument("--show-config", action="store_true", help="Also show the value-free operation configuration used")
    args = parser.parse_args()
    binary = args.binary or (ROOT / "plugins/asm/scripts/launch.py" if (ROOT / "plugins/asm").is_dir() else ROOT / "scripts/launch.py")
    if not binary.is_file():
        raise FileNotFoundError("asm_executable_missing")
    names = ["file", "cli", "http"] if args.example == "all" else [args.example]
    outputs = [run(name, binary.resolve(), args.show_config) for name in names]
    for output in outputs:
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print('{"error":"example_failed"}', file=sys.stderr)
        sys.exit(1)
