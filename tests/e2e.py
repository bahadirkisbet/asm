#!/usr/bin/env python3
"""Real CLI/MCP/HTTP/browser contract tests. Only synthetic credentials are used."""
import argparse
import contextlib
import http.server
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "target/debug/asm"


sys.path.insert(0, str(ROOT / "examples"))
from mcp_client import MCPClient, assert_clean


class Client(MCPClient):
    def __init__(self, config, env, version="2025-11-25"):
        super().__init__(BINARY, config, env, version)


@contextlib.contextmanager
def fixture_server(token):
    state = {"api_received": False, "browser_received": False, "redirect_target": False, "headers_received": False}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, data, content_type="application/json"):
            payload = data.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if self.path == "/token":
                self.reply(200, json.dumps({"access_token": token}))
            elif self.path == "/echo":
                state["headers_received"] = self.headers.get("Authorization") == "Bearer " + token
                self.reply(200 if state["headers_received"] else 403, json.dumps({"echo": token}))
            elif self.path == "/fail":
                self.reply(403, json.dumps({"error": token}))
            elif self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/redirect-target")
                self.end_headers()
            elif self.path == "/redirect-target":
                state["redirect_target"] = True
                self.reply(200, "{}")
            elif self.path == "/page":
                self.reply(200, """<!doctype html><title>ASM fixture</title>
<button id="issue" onclick="setTimeout(()=>fetch('/token').then(r=>r.json()).then(j=>document.querySelector('#token').value=j.access_token),200)">Create</button>
<input id="token" value="stale-synthetic-token"><input id="destination" oninput="document.querySelector('#saved')?.remove()">
<button id="submit" onclick="fetch('/browser-submit',{method:'POST',body:JSON.stringify({token:document.querySelector('#destination').value})}).then(r=>{if(r.ok){document.querySelector('#token').value='stale-synthetic-token';const e=document.createElement('div');e.id='saved';document.body.appendChild(e)}})">Save</button>
""", "text/html")
            else:
                self.reply(404, "{}")

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            data = json.loads(body)
            match = data.get("token") == token
            if self.path == "/browser-submit":
                state["browser_received"] = match
            elif self.path == "/api-submit":
                state["api_received"] = match
            self.reply(200 if match else 400, json.dumps({"echo": token}))

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive(), "Fixture server did not stop"


@contextlib.contextmanager
def browser(directory, url):
    executable = os.environ.get("ASM_CHROME") or shutil.which("google-chrome") or shutil.which("chromium") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    assert Path(executable).exists(), "Chrome missing: set ASM_CHROME or use --skip-browser"
    profile = directory / "chrome"
    proc = subprocess.Popen([executable, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check", "--disable-background-networking", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 15
        active = profile / "DevToolsActivePort"
        while not active.exists() and time.monotonic() < deadline and proc.poll() is None:
            time.sleep(0.05)
        assert active.exists(), "Chrome CDP did not start"
        port = int(active.read_text().splitlines()[0])
        # Wait for the exact fixture page, not just the debugging socket.
        import urllib.request
        while time.monotonic() < deadline:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as response:
                targets = json.load(response)
            if any(t.get("url") == url for t in targets):
                break
            time.sleep(0.05)
        else:
            raise AssertionError("Chrome fixture page did not load")
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        assert proc.poll() is not None, "Chrome did not stop"


def run(skip_browser=False, keyring=False, cli_binary=None):
    cli_binary = cli_binary or BINARY
    token = "asm-test-" + secrets.token_hex(24)
    transcript = []
    with tempfile.TemporaryDirectory(prefix="asm-e2e-") as directory, fixture_server(token) as (url, state), contextlib.ExitStack() as stack:
        directory = Path(directory)
        source = directory / "source.json"
        source.write_text(json.dumps({"token": token}))
        source.chmod(0o600)
        command = {"program": sys.executable, "cwd": str(directory), "args": ["-c", "import json; print(open('source.json').read())"]}
        operations = {}

        def capture(name, source):
            operations[name] = {"kind": "capture", "secret": name, "source": source}

        capture("file", {"kind": "file", "path": "source.json", "json_pointer": "/token"})
        capture("env", {"kind": "environment", "variable": "ASM_TEST_SOURCE"})
        capture("cli", {"kind": "command", "command": command, "json_pointer": "/token"})
        capture("api", {"kind": "http", "request": {"url": url + "/token"}, "json_pointer": "/access_token"})
        capture("failure", {"kind": "http", "request": {"url": url + "/fail"}, "json_pointer": "/access_token"})
        capture("redirect", {"kind": "http", "request": {"url": url + "/redirect"}, "json_pointer": "/access_token"})
        capture("cli-failure", {"kind": "command", "command": {**command, "args": ["-c", "import sys; s=open('source.json').read(); print(s); print(s,file=sys.stderr); sys.exit(9)"]}})
        capture("cli-timeout", {"kind": "command", "command": {**command, "timeout_seconds": 1, "args": ["-c", "import time;time.sleep(5)"]}})
        operations["generate"] = {"kind": "generate", "secret": "generated", "bytes": 32}
        operations["file-deliver"] = {"kind": "deliver", "secret": "file", "destination": {"kind": "file", "path": "delivered"}}
        operations["generated-deliver"] = {"kind": "deliver", "secret": "generated", "destination": {"kind": "file", "path": "generated"}}
        operations["env-deliver"] = {"kind": "deliver", "secret": "cli", "destination": {"kind": "command", "variable": "TOKEN", "command": {**command, "args": ["-c", "import os,json,sys; token=os.environ['TOKEN']; assert token==json.load(open('source.json'))['token']; assert 'ASM_TEST_SOURCE' not in os.environ; print(token);print(token,file=sys.stderr)"]}}}
        operations["api-deliver"] = {"kind": "deliver", "secret": "api", "destination": {"kind": "http", "request": {"url": url + "/api-submit", "method": "POST"}, "placement": {"kind": "json_field", "field": "token"}}}
        operations["header-deliver"] = {"kind": "deliver", "secret": "env", "destination": {"kind": "http", "request": {"url": url + "/echo"}, "placement": {"kind": "header", "name": "Authorization", "prefix": "Bearer "}}}
        if not skip_browser:
            endpoint = stack.enter_context(browser(directory, url + "/page"))
            page = {"endpoint": endpoint, "url": url + "/page", "timeout_seconds": 5}
            capture("browser", {"kind": "browser", "page": page, "selector": "#token", "click": "#issue"})
            operations["browser-deliver"] = {"kind": "deliver", "secret": "browser", "destination": {"kind": "browser", "page": page, "selector": "#destination", "submit": "#submit", "success_selector": "#saved"}}
        config = {"namespace": "e2e-" + secrets.token_hex(8), "allow_http_loopback": True, "secrets": {op["secret"]: {"description": "Synthetic test credential"} for op in operations.values()}, "operations": operations}
        for name, label in {"file":"development", "env":"production", "generated":"staging"}.items():
            config["secrets"][name]["environment"] = label
        path = directory / "config.json"
        path.write_text(json.dumps(config))
        env = dict(os.environ, ASM_TEST_SOURCE=token)

        for protocol in ["2024-11-05", "2025-11-25"]:
            client = Client(path, env, protocol)
            try:
                tools = client.call("tools/list", {})["tools"]
                assert {t["name"] for t in tools} == {"asm_catalog", "asm_execute"}
                schema = next(t["inputSchema"] for t in tools if t["name"] == "asm_execute")
                assert set(schema["properties"]) == {"operation"}, "Secret-bearing tool arguments exposed"
                catalog = json.loads(client.call("tools/call", {"name": "asm_catalog", "arguments": {}})["content"][0]["text"])
                expected = {"asm://" + config["namespace"] + "/" + name: definition.get("environment") for name, definition in config["secrets"].items()}
                for entry in catalog["secrets"] + catalog["operations"]:
                    assert entry["environment"] == expected[entry.get("ref", entry.get("secret_ref"))]
                for operation in ["file", "env", "cli", "api", "generate", "file-deliver", "generated-deliver", "env-deliver", "api-deliver", "header-deliver"]:
                    outcome = client.execute(operation)
                    assert outcome["environment"] == expected[outcome["secret_ref"]]
                assert (directory / "delivered").read_text() == token
                assert (directory / "delivered").stat().st_mode & 0o777 == 0o600
                generated = (directory / "generated").read_text()
                assert len(generated) == 43
                assert state["api_received"] and state["headers_received"]
                for operation, error in [("file", "secret_already_exists"), ("file-deliver", "destination_exists_or_write_failed"), ("failure", "http_status_failed"), ("redirect", "http_status_failed"), ("cli-failure", "command_failed"), ("cli-timeout", "command_timeout"), ("unknown", "unknown_operation")]:
                    client.execute(operation, error)
                assert not state["redirect_target"], "HTTP redirect followed with credential"
                if not skip_browser:
                    client.execute("browser")
                    client.execute("browser-deliver")
                    assert state["browser_received"], "Browser delivery not observed at server"
            finally:
                client.close()
                transcript.extend(client.transcript)
            assert_clean(transcript, [token, generated])
            (directory / "delivered").unlink()
            (directory / "generated").unlink()
            print(f"PASS MCP {protocol}: capture, delivery, failures, no secret in output", flush=True)

        for args, expected in [(["check"], 0), (["catalog"], 0), (["--ephemeral", "execute", "cli-failure"], 1)]:
            result = subprocess.run([str(cli_binary), "--config", str(path), *args], env=env, capture_output=True, text=True, timeout=15)
            assert result.returncode == expected, "CLI exit status incorrect"
            if args == ["catalog"]:
                catalog = json.loads(result.stdout)
                assert any(entry["environment"] == "production" for entry in catalog["secrets"])
            transcript.extend([result.stdout, result.stderr])
        if keyring:
            # Unique namespace; register cleanup before the first persistent write.
            try:
                for operation in ["file", "file-deliver"]:
                    result = subprocess.run([str(cli_binary), "--config", str(path), "execute", operation], capture_output=True, text=True, timeout=30)
                    transcript.extend([result.stdout, result.stderr])
                    assert result.returncode == 0, "OS credential store roundtrip failed"
                assert (directory / "delivered").read_text() == token
            finally:
                cleanup = subprocess.run([str(cli_binary), "--config", str(path), "delete", "file"], capture_output=True, text=True, timeout=30)
                transcript.extend([cleanup.stdout, cleanup.stderr])
                assert cleanup.returncode == 0, "OS credential cleanup failed"
            print("PASS OS credential store across CLI processes; test item removed", flush=True)
        assert_clean(transcript, [token])
        print("PASS CLI status/error contract; owned resources cleaned on exit", flush=True)
        if skip_browser:
            print("SKIPPED browser: explicitly disabled", flush=True)
        else:
            print("PASS browser create/capture/fill/submit; server verified exact value", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-browser", action="store_true")
    parser.add_argument("--keyring", action="store_true")
    options = parser.parse_args()
    run(options.skip_browser, options.keyring)
