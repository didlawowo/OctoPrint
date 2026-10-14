"""First-start configuration tests; no serial port, network or SD writes."""

import importlib.util
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/configure-local.py"
SPEC = importlib.util.spec_from_file_location("atelier_configure", SCRIPT)
configure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(configure)


class PresetTests(unittest.TestCase):
    def test_default_networks_are_loopback_only(self):
        self.assertEqual(configure.networks(""), ["127.0.0.1/32", "::1/128"])

    def test_private_network_is_explicit_and_deduplicated(self):
        result = configure.networks("192.168.42.0/24,192.168.42.0/24,fd12::/64")
        self.assertEqual(len(result), 4)
        self.assertIn("192.168.42.0/24", result)

    def test_public_wildcard_and_noncanonical_networks_are_rejected(self):
        for value in ("0.0.0.0/0", "::/0", "8.8.8.8/32", "192.168.42.2/24", "nope"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                configure.networks(value)

    def test_existing_settings_win_without_mutating_inputs(self):
        old = {"appearance": {"name": "My printer"}, "server": {"secretKey": "keep"}}
        preset = {"appearance": {"name": "Atelier", "defaultLanguage": "fr"}}
        result = configure.merge_defaults(old, preset)
        self.assertEqual(result["appearance"]["name"], "My printer")
        self.assertEqual(result["appearance"]["defaultLanguage"], "fr")
        self.assertEqual(result["server"]["secretKey"], "keep")
        self.assertNotIn("defaultLanguage", old["appearance"])

    def test_null_unanswered_setting_gets_a_preset_value(self):
        self.assertEqual(
            configure.merge_defaults({"enabled": None}, {"enabled": True}),
            {"enabled": True},
        )

    def test_only_current_wizards_are_completed_without_disabling_plugins(self):
        old = {"server": {"seenWizards": {"corewizard": 7, "third_party": 3}}}
        result = configure.plan(old, {}, "chris", configure.networks(""))
        self.assertFalse(result["server"]["firstRun"])
        self.assertEqual(result["server"]["seenWizards"]["corewizard"], 7)
        self.assertEqual(result["server"]["seenWizards"]["third_party"], 3)
        self.assertEqual(result["accessControl"]["autologinAs"], "chris")
        self.assertNotIn("plugins", result)
        self.assertNotIn("devel", result)
        self.assertNotIn("trustBasicAuthentication", result["accessControl"])

    def test_injection_is_idempotent(self):
        first = configure.plan({}, {"appearance": {"defaultLanguage": "fr"}}, "u", [])
        self.assertEqual(configure.plan(first, {}, "u", []), first)

    def test_invalid_config_structure_is_rejected(self):
        for data in ({"server": []}, {"accessControl": False}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                configure.plan(data, {}, "u", [])

    def test_private_credentials_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "credentials"
            configure.write_private(path, "private")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                configure.write_private(path, "replacement")
            self.assertEqual(path.read_text(), "private")

    def test_config_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / "original"
            original.write_text("secret: keep\n")
            alias = root / "config.yaml"
            alias.symlink_to(original)
            with self.assertRaises(ValueError):
                configure.read_mapping(alias)
            self.assertEqual(original.read_text(), "secret: keep\n")


@unittest.skipUnless(
    importlib.util.find_spec("octoprint") and importlib.util.find_spec("flask"),
    "Integration requires an installed OctoPrint environment (present in CI)",
)
class NativeProvisioningTests(unittest.TestCase):
    def run_configure(self, directory):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--basedir", str(directory)],
            text=True,
            capture_output=True,
            timeout=45,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_native_accounts_first_run_and_second_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            first = self.run_configure(directory)
            credentials = yaml.safe_load((directory / "atelier-credentials.yaml").read_text())
            users_before = (directory / "users.yaml").read_bytes()
            config = yaml.safe_load((directory / "config.yaml").read_text())
            self.assertFalse(config["server"]["firstRun"])
            self.assertEqual(config["accessControl"]["autologinAs"], "atelier")
            self.assertEqual(config["accessControl"]["localNetworks"], list(configure.LOCAL))
            self.assertFalse(config["plugins"]["tracking"]["enabled"])
            self.assertNotIn(credentials["password"], first.stdout + first.stderr)
            self.assertNotIn(credentials["password"].encode(), users_before)
            second = self.run_configure(directory)
            self.assertEqual((directory / "users.yaml").read_bytes(), users_before)
            self.assertNotIn(credentials["password"], second.stdout + second.stderr)
            self.assertEqual(len(list(directory.glob("config.yaml.before-atelier-*"))), 1)

    def test_existing_profile_and_camera_choices_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            original = {
                "appearance": {"name": "Existing machine"},
                "plugins": {"classicwebcam": {"stream": "/existing-camera"}},
                "printerProfiles": {"default": "my_existing_profile"},
            }
            (directory / "config.yaml").write_text(yaml.safe_dump(original))
            self.run_configure(directory)
            config = yaml.safe_load((directory / "config.yaml").read_text())
            self.assertEqual(config["appearance"]["name"], "Existing machine")
            self.assertEqual(config["plugins"]["classicwebcam"]["stream"], "/existing-camera")
            self.assertEqual(config["printerProfiles"]["default"], "my_existing_profile")
            self.assertTrue(list(directory.glob("config.yaml.before-atelier-*")))


if __name__ == "__main__":
    unittest.main()
