#!/usr/bin/env python3
"""Register the Git marketplace and migrate only ASM's managed legacy MCP entry."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

from install import InstallError, backup, existing_entry, matching, read_config, run

MARKETPLACE = "bardak"
PLUGIN = "asm@" + MARKETPLACE


def normalized_source(source):
    source = source.rstrip("/")
    if source.startswith("git@") and ":" in source:
        host, path = source.split(":", 1)
        source = "ssh://" + host + "/" + path
    elif ":" not in source and not source.startswith(("/", ".")):
        source = "https://github.com/" + source
    return source.removesuffix(".git")


def marketplaces(client, runner):
    data = json.loads(runner([client, "plugin", "marketplace", "list", "--json"]))
    return data if client == "claude" else data["marketplaces"]


def require_source(client, entry, source):
    if client == "codex":
        current = entry.get("marketplaceSource", {}).get("source")
    else:
        current = entry.get("repo") or entry.get("url") or entry.get("path")
    if not isinstance(current, str) or normalized_source(current) != normalized_source(source):
        raise InstallError(f"{client}: marketplace name already belongs to a different source.")


def installed(client, runner):
    data = json.loads(runner([client, "plugin", "list", "--json"]))
    entries = data if client == "claude" else data["installed"]
    return next((entry for entry in entries if entry.get("id", entry.get("pluginId")) == PLUGIN and (client != "claude" or entry.get("scope") == "user")), None)


def check_claude_policies(claude_dir):
    # Plugin tool names differ from direct-MCP names. Do not strand named rules.
    paths = {claude_dir / "settings.json", claude_dir / "settings.local.json"}
    for directory in [Path.cwd(), *Path.cwd().parents]:
        paths.update([directory / ".claude/settings.json", directory / ".claude/settings.local.json"])
    for path in paths:
        settings = read_config(path, "claude")
        policies = json.dumps({key: settings.get(key) for key in ["permissions", "hooks"]})
        if "mcp__asm" in policies:
            raise InstallError("claude: legacy ASM permission/hook rules require explicit migration; settings retained.")


def install_plugins(clients, source, *, home=None, environ=None, runner=run, which=shutil.which):
    home = Path.home() if home is None else Path(home)
    environ = os.environ if environ is None else environ
    claude_dir = Path(environ.get("CLAUDE_CONFIG_DIR", home / ".claude"))
    claude_settings = claude_dir / ".claude.json" if environ.get("CLAUDE_CONFIG_DIR") else home / ".claude.json"
    paths = {"claude": claude_settings, "codex": Path(environ.get("CODEX_HOME", home / ".codex")) / "config.toml"}
    config = home / ".config/asm/operations.json"
    binary = home / ".local/share/asm/bin/asm"
    plans = []
    # Preflight both clients before any client configuration mutation.
    for client in clients:
        if not which(client):
            raise InstallError(f"Required executable missing: {client}")
        legacy = existing_entry(paths[client], client)
        if legacy is not None and (not matching(legacy, binary, config) or legacy.get("env") or set(legacy) - {"command", "args", "type", "env"}):
            raise InstallError(f"{client}: custom legacy ASM entry needs an explicit migration; left unchanged.")
        if client == "claude" and legacy is not None:
            check_claude_policies(claude_dir)
        market = next((m for m in marketplaces(client, runner) if m.get("name") == MARKETPLACE), None)
        if market:
            require_source(client, market, source)
        plans.append((client, legacy, market))
    for client, legacy, market in plans:
        backups = home / ".local/share/asm/backups"
        backup(paths[client], backups, client)
        if client == "claude":
            for path in [claude_dir / "settings.json", claude_dir / "plugins/known_marketplaces.json", claude_dir / "plugins/installed_plugins.json"]:
                backup(path, backups, "claude-plugin")
        if market is None:
            runner([client, "plugin", "marketplace", "add", source], cwd=home)
        state = installed(client, runner)
        if state is None:
            if market is not None:
                runner([client, "plugin", "marketplace", "update" if client == "claude" else "upgrade", MARKETPLACE], cwd=home)
            args = [client, "plugin", "install" if client == "claude" else "add", PLUGIN]
            if client == "claude":
                args += ["--scope", "user"]
            runner(args, cwd=home)
        state = installed(client, runner)
        if state is None or not state.get("enabled"):
            raise InstallError(f"{client}: plugin not enabled; legacy MCP entry retained.")
        if client == "claude":
            plugin_path = Path(state["installPath"])
        else:
            version = state.get("version")
            if not isinstance(version, str) or not version or any(c not in "0123456789.-abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ" for c in version):
                raise InstallError("codex: invalid installed version; legacy MCP entry retained.")
            plugin_path = paths["codex"].parent / "plugins/cache" / MARKETPLACE / "asm" / version
        # Verify the installed bundle and current config before removing a working
        # direct MCP entry. Startup performs no provider or credential operations.
        runner([sys.executable, str(plugin_path / "scripts/launch.py"), "--prepare"], cwd=home)
        if legacy is not None:
            if existing_entry(paths[client], client) != legacy:
                raise InstallError(f"{client}: legacy settings changed concurrently; entry retained.")
            # Remove only our known legacy definition, after the plugin is installed.
            args = [client, "mcp", "remove"]
            if client == "claude":
                args += ["--scope", "user"]
            runner([*args, "asm"], cwd=home)
            if existing_entry(paths[client], client) is not None:
                raise InstallError(f"{client}: legacy removal could not be verified.")
        print(f"{client}: {PLUGIN} enabled; no managed legacy duplicate", flush=True)
    print("Restart existing sessions to load the plugin's MCP tools and secrets skill.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Install ASM from its GitHub plugin marketplace")
    parser.add_argument("--client", choices=["both", "claude", "codex"], default="both")
    parser.add_argument("--source", default="bahadirkisbet/bardak", help="Git marketplace source; use your SSH alias for private repository access")
    args = parser.parse_args()
    try:
        install_plugins(["claude", "codex"] if args.client == "both" else [args.client], args.source)
    except (InstallError, OSError, ValueError, KeyError, TypeError) as error:
        print(str(error) if isinstance(error, InstallError) else "Plugin installation failed; captured client output was not printed.", file=sys.stderr)
        print("Completed installations remain; backups are in ~/.local/share/asm/backups. Fix the failure and rerun.", file=sys.stderr)
        sys.exit(1)
