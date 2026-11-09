#!/usr/bin/env python3
"""Run all existing exchange scenarios from a relocated, self-contained plugin."""
from pathlib import Path
import runpy
import shutil
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
        print("PASS relocated plugin: bundled binary, checksum verification, all MCP exchange scenarios")
