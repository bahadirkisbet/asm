"""Small stdio MCP client shared by runnable examples and contract tests."""
import base64
import json
import select
import subprocess
import time


class MCPClient:
    def __init__(self, binary, config, env, version="2025-11-25"):
        self.transcript = []
        self.sequence = 0
        self.process = subprocess.Popen(
            [str(binary), "--config", str(config), "--ephemeral", "mcp"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env,
        )
        try:
            result = self.call("initialize", {"protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "asm-example", "version": "1"}})
            assert "serverInfo" in result, "MCP initialize failed"
            self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
            self.process.stdin.flush()
        except BaseException:
            self.close()
            raise

    def call(self, method, params):
        self.sequence += 1
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.sequence, "method": method, "params": params}) + "\n")
        self.process.stdin.flush()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self.process.stdout], [], [], max(0, deadline - time.monotonic()))
            assert ready, "MCP response timed out"
            line = self.process.stdout.readline()
            assert line, "MCP exited before responding"
            self.transcript.append(line)
            response = json.loads(line)
            if response.get("id") == self.sequence:
                assert "error" not in response, "Unexpected MCP protocol error"
                return response["result"]
        raise AssertionError("MCP deadline exceeded")

    def execute(self, operation, error=None):
        result = self.call("tools/call", {"name": "asm_execute", "arguments": {"operation": operation}})
        payload = json.loads(result["content"][0]["text"])
        if error:
            assert result.get("isError") and payload.get("error") == error, "Wrong operation failure"
        else:
            assert not result.get("isError"), f"Operation failed: {operation}: {payload.get('error')}"
            assert "secret_ref" in payload
        return payload

    def close(self):
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.transcript.append(self.process.stderr.read())
        self.process.stdout.close()
        self.process.stderr.close()


def assert_clean(transcript, values):
    text = "\n".join(transcript)
    for value in values:
        for representation in [value, json.dumps(value)[1:-1], base64.b64encode(value.encode()).decode()]:
            assert representation not in text, "Secret leaked into agent-visible output"


