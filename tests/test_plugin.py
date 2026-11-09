"""Plugin launcher and migration contract tests; no global configuration writes."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import install_plugin
import package_plugin

spec = importlib.util.spec_from_file_location("plugin_launcher", ROOT / "plugins/asm/scripts/launch.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "bin").mkdir()
        (self.root / "config").mkdir()
        (self.root / "config/demo.json").write_text('{"demo":true}')
        self.binary = self.root / "bin/asm-Darwin-arm64"
        self.binary.write_bytes(b"synthetic-executable")
        self.binary.chmod(0o755)
        (self.root / "bin/manifest.json").write_text(json.dumps({"Darwin-arm64":{"file":self.binary.name,"sha256":hashlib.sha256(self.binary.read_bytes()).hexdigest()}}))

    def test_binary_integrity_and_supported_platform(self):
        with patch.object(launcher.platform, "system", return_value="Darwin"), patch.object(launcher.platform, "machine", return_value="arm64"):
            self.assertEqual(launcher.binary_path(self.root), self.binary)
            self.binary.write_bytes(b"modified")
            with self.assertRaisesRegex(launcher.LaunchError, "checksum"):
                launcher.binary_path(self.root)
        with patch.object(launcher.platform, "system", return_value="Windows"):
            with self.assertRaisesRegex(launcher.LaunchError, "unsupported"):
                launcher.binary_path(self.root)

    def test_symlinked_binary_rejected(self):
        target = self.root / "other"
        self.binary.rename(target)
        self.binary.symlink_to(target)
        with patch.object(launcher.platform, "system", return_value="Darwin"), patch.object(launcher.platform, "machine", return_value="arm64"):
            with self.assertRaisesRegex(launcher.LaunchError, "missing"):
                launcher.binary_path(self.root)

    def test_config_creation_is_private_and_preserves_existing(self):
        self.root.chmod(0o750)
        config = self.root / "operations.json"
        launcher.prepare_config(config, self.root)
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o750)
        config.write_text('{"user":"keep"}')
        launcher.prepare_config(config, self.root)
        self.assertEqual(config.read_text(), '{"user":"keep"}')


class PackageTests(unittest.TestCase):
    def test_provenance_failure_precedes_writes_and_valid_package_is_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plugin = root / 'plugins/asm'
            (plugin / '.codex-plugin').mkdir(parents=True)
            (plugin / '.codex-plugin/plugin.json').write_text('{"version":"0.1.1"}')
            (root / 'examples').mkdir()
            (root / 'examples/demo.json').write_text('{"demo":true}')
            (root / 'LICENSE').write_text('fixture license')
            artifacts = root / 'artifacts'
            artifacts.mkdir()
            for target in package_plugin.TARGETS:
                binary = artifacts / ('asm-' + target)
                binary.write_bytes(b'fixture-' + target.encode())
                (artifacts / (target + '.json')).write_text(json.dumps({'file':binary.name,'sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'version':'asm 0.1.1','source_commit':'expected'}))
            with patch.object(package_plugin, 'ROOT', root):
                with self.assertRaises(ValueError): package_plugin.package(artifacts, 'wrong-source')
                self.assertFalse((plugin/'bin').exists())
                package_plugin.package(artifacts, 'expected')
            self.assertEqual(len(json.loads((plugin/'bin/manifest.json').read_text())),3)
            self.assertEqual((plugin/'config/demo.json').read_text(),'{"demo":true}')


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / ".codex").mkdir()
        self.legacy = {"command":str(self.home / ".local/share/asm/bin/asm"),"args":["--config",str(self.home / ".config/asm/operations.json"),"mcp"]}
        (self.home / ".claude.json").write_text(json.dumps({"keep":42,"mcpServers":{"asm":self.legacy}}))
        (self.home / ".codex/config.toml").write_text('model="keep"\n[mcp_servers.asm]\ncommand='+json.dumps(self.legacy["command"])+ '\nargs='+json.dumps(self.legacy["args"]))
        self.markets = {"claude":[],"codex":[]}
        self.plugins = {"claude":[],"codex":[]}
        self.calls = []
        self.fail = None

    def runner(self, args, **kwargs):
        self.calls.append(args)
        client = args[0]
        if args[1:4] == ["plugin","marketplace","list"]:
            return json.dumps(self.markets[client] if client=="claude" else {"marketplaces":self.markets[client]})
        if args[1:4] == ["plugin","marketplace","add"]:
            self.markets[client] = [{"name":"bardak", "repo":args[4], "marketplaceSource":{"source":args[4]}}]
        elif args[1:3] == ["plugin","list"]:
            return json.dumps(self.plugins[client] if client=="claude" else {"installed":self.plugins[client]})
        elif args[1:3] in [["plugin","install"],["plugin","add"]]:
            if client == self.fail:
                raise install_plugin.InstallError("fixture_install_failure")
            self.plugins[client] = [{"id":install_plugin.PLUGIN,"pluginId":install_plugin.PLUGIN,"enabled":True,"installPath":str(self.home / 'plugin'),"version":"0.1.1","scope":"user"}]
        elif args[1:3] == ["mcp","remove"]:
            self.assertTrue(self.plugins[client], "Legacy entry removed before plugin installed")
            if client=="claude":
                data=json.loads((self.home / '.claude.json').read_text()); del data['mcpServers']['asm']
                (self.home / '.claude.json').write_text(json.dumps(data))
            else:
                (self.home / '.codex/config.toml').write_text('model="keep"\n')
        return ""

    def install(self):
        install_plugin.install_plugins(["claude","codex"],"bahadirkisbet/bardak",home=self.home,environ={},runner=self.runner,which=lambda _:"/found")

    def test_migration_preserves_settings_and_is_idempotent(self):
        self.install()
        self.assertEqual(json.loads((self.home/'.claude.json').read_text())["keep"],42)
        self.assertEqual((self.home/'.codex/config.toml').read_text(),'model="keep"\n')
        self.calls.clear()
        self.install()
        self.assertFalse(any(c[2] in ["install","add","remove"] or c[2:4]==["marketplace","add"] for c in self.calls))

    def test_failed_install_keeps_legacy_entry(self):
        self.fail="claude"
        with self.assertRaises(install_plugin.InstallError): self.install()
        self.assertIn("asm",json.loads((self.home/'.claude.json').read_text())["mcpServers"])
        self.assertFalse(any(c[1:3]==["mcp","remove"] for c in self.calls))

    def test_existing_marketplace_is_refreshed_before_install(self):
        self.markets['claude']=[{"name":"bardak","repo":"bahadirkisbet/bardak"}]
        self.markets['codex']=[{"name":"bardak","marketplaceSource":{"source":"https://github.com/bahadirkisbet/bardak.git"}}]
        self.install()
        for client, refresh, install in [('claude','update','install'),('codex','upgrade','add')]:
            refresh_index=self.calls.index([client,'plugin','marketplace',refresh,'bardak'])
            install_index=next(i for i,c in enumerate(self.calls) if c[:3]==[client,'plugin',install])
            self.assertLess(refresh_index,install_index)

    def test_custom_legacy_entry_stops_all_mutations(self):
        self.legacy['args']=['custom']
        (self.home/'.claude.json').write_text(json.dumps({"mcpServers":{"asm":self.legacy}}))
        with self.assertRaises(install_plugin.InstallError): self.install()
        self.assertEqual(self.calls,[])

    def test_failed_bundle_preparation_keeps_legacy_entry(self):
        runner = self.runner
        def fail_prepare(args, **kwargs):
            if args[-1] == "--prepare":
                raise install_plugin.InstallError("bundle_invalid")
            return runner(args, **kwargs)
        with self.assertRaises(install_plugin.InstallError):
            install_plugin.install_plugins(["claude"],"bahadirkisbet/bardak",home=self.home,environ={},runner=fail_prepare,which=lambda _:"/found")
        self.assertIn("asm",json.loads((self.home/'.claude.json').read_text())["mcpServers"])

    def test_marketplace_source_conflict_stops_all_mutations(self):
        self.markets['codex']=[{"name":"bardak","marketplaceSource":{"source":"https://example.com/other.git"}}]
        with self.assertRaises(install_plugin.InstallError): self.install()
        self.assertTrue(all(c[1:4]==["plugin","marketplace","list"] for c in self.calls))

    def test_legacy_tool_restrictions_are_not_discarded(self):
        with (self.home / '.codex/config.toml').open('a') as file:
            file.write('\nenabled_tools=["asm_catalog"]\n')
        with self.assertRaises(install_plugin.InstallError): self.install()
        self.assertTrue(all(c[1:4]==["plugin","marketplace","list"] for c in self.calls))
        self.assertIn('enabled_tools', (self.home / '.codex/config.toml').read_text())

    def test_project_plugin_does_not_replace_user_installation(self):
        self.plugins['claude'] = [{"id":install_plugin.PLUGIN,"enabled":True,"scope":"project","installPath":str(self.home/'project-plugin')}]
        self.install()
        self.assertTrue(any(c[:3]==['claude','plugin','install'] and '--scope' in c and 'user' in c for c in self.calls))

    def test_legacy_permission_rule_stops_migration(self):
        (self.home/'.claude').mkdir()
        (self.home/'.claude/settings.json').write_text(json.dumps({'permissions':{'deny':['mcp__asm__asm_execute']}}))
        with self.assertRaises(install_plugin.InstallError): self.install()
        self.assertFalse(any(c[1:3]==['mcp','remove'] for c in self.calls))


if __name__ == "__main__":
    unittest.main()
