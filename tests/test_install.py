"""Installer tests use isolated files and fake native clients; no global writes."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("installer", Path(__file__).resolve().parents[1] / "scripts/install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / ".codex").mkdir()
        (self.home / ".codex/config.toml").write_text('model = "keep-me"\n')
        (self.home / ".claude.json").write_text('{"keep": true}')
        self.binary = self.home / "built-asm"
        self.binary.write_text("test executable")
        self.calls = []

    def runner(self, args, **kwargs):
        self.calls.append(args)
        if args[0] == "cargo":
            return json.dumps({"reason": "compiler-artifact", "target": {"name": "asm"}, "executable": str(self.binary)})
        if args[0] in ["claude", "codex"]:
            binary, _, config, _ = args[args.index("--") + 1:]
            entry = {"command": binary, "args": ["--config", config, "mcp"]}
            if args[0] == "claude":
                path = self.home / ".claude.json"
                content = json.loads(path.read_text())
                content["mcpServers"] = {"asm": entry}
                path.write_text(json.dumps(content))
            else:
                with (self.home / ".codex/config.toml").open("a") as file:
                    file.write('\n[mcp_servers.asm]\ncommand = ' + json.dumps(binary) + '\nargs = ' + json.dumps(entry["args"]) + '\n')
        return ""

    def install(self, **kwargs):
        return installer.install(["claude", "codex"], home=self.home, environ={}, which=lambda _: "/found", runner=self.runner, **kwargs)

    def test_installs_backs_up_preserves_and_is_idempotent(self):
        binary, config = self.install()
        self.assertTrue(binary.exists())
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        self.assertTrue(json.loads((self.home / ".claude.json").read_text())["keep"])
        self.assertIn('model = "keep-me"', (self.home / ".codex/config.toml").read_text())
        backups = list((self.home / ".local/share/asm/backups").iterdir())
        self.assertEqual(len(backups), 2)
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in backups))
        self.calls.clear()
        self.install()
        self.assertFalse(any(c[0] in ["claude", "codex"] for c in self.calls))

    def test_conflicting_entry_fails_before_any_command(self):
        (self.home / ".codex/config.toml").write_text('[mcp_servers.asm]\ncommand = "other"\n')
        with self.assertRaises(installer.InstallError):
            self.install()
        self.assertEqual(self.calls, [])
        self.assertFalse((self.home / ".config/asm").exists())

    def test_existing_operations_are_preserved(self):
        config = self.home / "custom.json"
        config.write_text('{"custom": "preserve"}')
        self.install(config=config)
        self.assertEqual(config.read_text(), '{"custom": "preserve"}')

    def test_missing_client_fails_before_writes(self):
        with self.assertRaises(installer.InstallError):
            installer.install(["claude", "codex"], home=self.home, environ={}, which=lambda _: None, runner=self.runner)
        self.assertEqual(self.calls, [])

    def test_new_custom_config_does_not_change_parent_permissions(self):
        self.home.chmod(0o750)
        self.install(config=self.home / "custom.json")
        self.assertEqual(self.home.stat().st_mode & 0o777, 0o750)

    def test_malformed_existing_entry_is_not_overwritten(self):
        (self.home / ".claude.json").write_text('{"mcpServers":{"asm":null}}')
        with self.assertRaises(installer.InstallError):
            self.install()
        self.assertEqual(self.calls, [])

    def test_registration_failure_is_reported(self):
        def failing(args, **kwargs):
            if args[0] == "codex":
                raise installer.InstallError("fixture failure")
            return self.runner(args, **kwargs)
        with self.assertRaises(installer.InstallError):
            installer.install(["claude", "codex"], home=self.home, environ={}, which=lambda _: "/found", runner=failing)
        self.assertIsNotNone(installer.existing_entry(self.home / ".claude.json", "claude"))
        self.assertIn('model = "keep-me"', (self.home / ".codex/config.toml").read_text())


if __name__ == "__main__":
    unittest.main()
