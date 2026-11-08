#!/usr/bin/env python3
"""Native client config/health checks. Does not call a model or change global config."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "target/debug/asm"
CONFIG = ROOT / "examples/demo.json"


def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, timeout=30, **kwargs)
    assert result.returncode == 0, "Native client command failed: " + args[0]
    return result.stdout


def main():
    assert shutil.which("claude") and shutil.which("codex"), "Install both native clients first"
    with tempfile.TemporaryDirectory(prefix="asm-client-compat-") as temp:
        env = dict(os.environ, CLAUDE_CONFIG_DIR=temp)
        run(["claude", "mcp", "add", "--scope", "user", "--transport", "stdio", "asm", "--", str(BINARY), "--config", str(CONFIG), "--ephemeral", "mcp"], env=env, cwd=temp)
        health = run(["claude", "mcp", "get", "asm"], env=env, cwd=temp)
        assert "Connected" in health, "Claude MCP health check did not connect"
        print("PASS Claude Code native MCP health check (isolated config)")
        config = run(["codex", "-c", "mcp_servers.asm.command=" + json.dumps(str(BINARY)), "-c", "mcp_servers.asm.args=" + json.dumps(["--config", str(CONFIG), "--ephemeral", "mcp"]), "mcp", "get", "asm", "--json"], cwd=temp)
        parsed = json.loads(config)
        assert parsed["transport"]["command"] == str(BINARY)
        assert parsed["transport"]["args"][-1] == "mcp"
        print("PASS Codex native MCP configuration parser (per-command overrides)")
        print("Scope: Claude live handshake; Codex config plus separate MCP protocol tests. No model turn executed.")


if __name__ == "__main__":
    main()
