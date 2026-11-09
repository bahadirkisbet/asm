#!/usr/bin/env python3
"""Build ASM and register it with native clients; never print client configuration."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]


class InstallError(Exception):
    pass


def run(args, **kwargs):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=600, **kwargs)
    except (OSError, subprocess.TimeoutExpired):
        raise InstallError("A required command could not run or timed out.") from None
    if result.returncode:
        # CLI diagnostics may include configuration or credentials.
        raise InstallError("A required command failed; no captured output was printed.")
    return result.stdout


def read_config(path, client):
    if not path.exists():
        return {}
    try:
        data = path.read_bytes()
        result = tomllib.loads(data.decode()) if client == "codex" else json.loads(data)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (OSError, ValueError):
        raise InstallError(f"Cannot parse {client} settings; existing file left unchanged.") from None


def existing_entry(path, client):
    settings = read_config(path, client)
    entries = settings.get("mcp_servers" if client == "codex" else "mcpServers", {})
    if not isinstance(entries, dict):
        raise InstallError(f"Invalid {client} MCP settings; existing file left unchanged.")
    if "asm" in entries and not isinstance(entries["asm"], dict):
        raise InstallError(f"Invalid asm entry in {client}; existing file left unchanged.")
    return entries.get("asm")


def matching(entry, binary, config):
    return isinstance(entry, dict) and entry.get("command") == str(binary) and entry.get("args") == ["--config", str(config), "mcp"] and "url" not in entry and entry.get("type", "stdio") == "stdio"


def private_directory(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def backup(path, directory, client):
    if not path.exists():
        return
    private_directory(directory)
    # mkstemp supplies a private unique backup; do not overwrite previous backups.
    fd, name = tempfile.mkstemp(prefix=f"{client}-{time.time_ns()}-", dir=directory)
    with os.fdopen(fd, "wb") as output:
        output.write(path.read_bytes())
        output.flush()
        os.fsync(output.fileno())


def install(clients, config=None, *, home=None, runner=run, which=shutil.which, environ=None):
    home = Path.home() if home is None else Path(home)
    environ = os.environ if environ is None else environ
    state = home / ".local/share/asm"
    binary = state / "bin/asm"
    config = Path(config).expanduser().resolve() if config else home / ".config/asm/operations.json"
    settings_paths = {
        "codex": Path(environ.get("CODEX_HOME", home / ".codex")) / "config.toml",
        "claude": Path(environ["CLAUDE_CONFIG_DIR"]) / ".claude.json" if environ.get("CLAUDE_CONFIG_DIR") else home / ".claude.json",
    }
    for executable in ["cargo", *clients]:
        if not which(executable):
            raise InstallError(f"Required executable missing: {executable}")
    plans = []
    for client in clients:
        entry = existing_entry(settings_paths[client], client)
        if entry is not None and not matching(entry, binary, config):
            raise InstallError(f"A different asm entry exists in {client}; nothing was overwritten.")
        plans.append((client, entry is None))

    print("Building ASM (Rust required)...", flush=True)
    # JSON identifies the artifact even when CARGO_TARGET_DIR is customized.
    output = runner(["cargo", "build", "--release", "--locked", "--message-format=json"], cwd=ROOT)
    artifacts = [record.get("executable") for line in output.splitlines() if line.startswith("{")
                 for record in [json.loads(line)] if record.get("reason") == "compiler-artifact" and record.get("target", {}).get("name") == "asm" and record.get("executable")]
    if not artifacts:
        raise InstallError("Cargo did not report the ASM executable.")
    built = Path(artifacts[-1])
    if not config.exists():
        config.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Exclusive creation preserves a config another process created meanwhile.
        fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as file:
            file.write((ROOT / "examples/demo.json").read_text())
    runner([str(built), "--config", str(config), "check"])
    private_directory(binary.parent)
    fd, temporary = tempfile.mkstemp(dir=binary.parent)
    os.close(fd)
    try:
        shutil.copyfile(built, temporary)
        os.chmod(temporary, 0o700)
        os.replace(temporary, binary)
    finally:
        Path(temporary).unlink(missing_ok=True)

    for client, missing in plans:
        if missing:
            # Recheck the exact entry immediately before calling the native writer.
            if existing_entry(settings_paths[client], client) is not None:
                raise InstallError(f"{client} settings changed during installation; rerun to inspect.")
            backup(settings_paths[client], state / "backups", client)
            args = [client, "mcp", "add"]
            if client == "claude":
                args += ["--scope", "user", "--transport", "stdio"]
            runner([*args, "asm", "--", str(binary), "--config", str(config), "mcp"], cwd=home)
            if not matching(existing_entry(settings_paths[client], client), binary, config):
                raise InstallError(f"{client} registration could not be verified. Backups retained.")
        print(f"{client}: ASM configured" if missing else f"{client}: ASM already configured", flush=True)
    print(f"Installed: {binary}\nOperations: {config}\nRestart Claude Code/Codex sessions to load ASM.", flush=True)
    return binary, config


def main():
    parser = argparse.ArgumentParser(description="Install ASM into Claude Code and Codex with one command.")
    parser.add_argument("--client", choices=["both", "claude", "codex"], default="both")
    parser.add_argument("--config", type=Path, help="Use an existing operations config, or create the demo if absent")
    options = parser.parse_args()
    try:
        install(["claude", "codex"] if options.client == "both" else [options.client], options.config)
    except (InstallError, OSError, ValueError) as error:
        print(str(error) if isinstance(error, InstallError) else "Installation failed; existing client settings were not printed.", file=sys.stderr)
        print("Completed client registrations remain installed; backups are in ~/.local/share/asm/backups. Fix the failure and rerun.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
