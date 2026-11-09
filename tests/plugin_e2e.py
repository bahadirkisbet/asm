#!/usr/bin/env python3
"""Run all existing exchange scenarios from a relocated, self-contained plugin."""
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile

import e2e

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="asm-plugin-test-") as temporary:
        plugin = Path(temporary) / "installed plugin with spaces"
        shutil.copytree(ROOT / "plugins/asm", plugin)
        e2e.BINARY = plugin / "scripts/launch.py"
        launcher = runpy.run_path(str(e2e.BINARY))
        e2e.run(cli_binary=launcher["binary_path"]())
        examples = subprocess.run([sys.executable, str(plugin / "examples/run.py"), "all"], cwd=temporary, capture_output=True, text=True, timeout=60)
        assert examples.returncode == 0, "Relocated runnable examples failed"
        assert examples.stdout.count('"verified": true') == 3, "Missing example verification"
        print("PASS relocated plugin: bundled binary, checksum verification, all MCP exchange scenarios")
        print("PASS bundled file, CLI and HTTP examples without source checkout")
