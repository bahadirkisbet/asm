#!/usr/bin/env python3
"""Verify the bundled native executable, preserve config, then hand stdio to ASM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


class LaunchError(Exception):
    pass


def binary_path(root=ROOT):
    target = platform.system() + "-" + platform.machine()
    manifest = json.loads((root / "bin/manifest.json").read_text())
    if not isinstance(manifest, dict):
        raise LaunchError("invalid_binary_manifest")
    entry = manifest.get(target)
    if not isinstance(entry, dict):
        raise LaunchError("unsupported_platform")
    expected_file = "asm-" + target
    if entry.get("file") != expected_file:
        raise LaunchError("invalid_binary_manifest")
    binary = root / "bin" / expected_file
    if binary.is_symlink() or not binary.is_file():
        raise LaunchError("bundled_binary_missing")
    if hashlib.sha256(binary.read_bytes()).hexdigest() != entry.get("sha256"):
        raise LaunchError("bundled_binary_checksum_failed")
    if not os.access(binary, os.X_OK):
        raise LaunchError("bundled_binary_not_executable")
    return binary


def prepare_config(path, root=ROOT):
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".asm-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write((root / "config/demo.json").read_bytes())
            output.flush()
            os.fsync(output.fileno())
        try:
            # Atomic exclusive publication: never overwrite an existing config.
            os.link(temporary, path)
        except FileExistsError:
            pass
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Start the bundled ASM MCP server")
    parser.add_argument("mode", nargs="?", choices=["mcp"], default="mcp")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--prepare", action="store_true", help="Validate the bundle/config without starting MCP")
    parser.add_argument("--ephemeral", action="store_true", help="Use in-memory storage for tests")
    args = parser.parse_args()
    try:
        binary = binary_path()
        configured = args.config or os.environ.get("ASM_CONFIG")
        config = Path(configured).expanduser().resolve() if configured else Path.home() / ".config/asm/operations.json"
        # An explicit missing config is an error, never silently replaced by demo.
        if configured and not config.is_file():
            raise LaunchError("configured_file_missing")
        if not configured:
            prepare_config(config)
        command = [str(binary), "--config", str(config)]
        if args.ephemeral:
            command.append("--ephemeral")
        if args.prepare:
            result = subprocess.run([*command, "check"], capture_output=True, timeout=15)
            if result.returncode:
                raise LaunchError("config_validation_failed")
            print('{"status":"ready"}')
            return 0
        os.execv(binary, [*command, "mcp"])
    except (LaunchError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        code = str(error) if isinstance(error, LaunchError) else "plugin_start_failed"
        print(json.dumps({"error": code}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
