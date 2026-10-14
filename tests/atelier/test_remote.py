"""Remote build regression tests; SSH, Docker and physical SD access are mocked."""

import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/pi"))
import remote  # noqa: E402

COMMIT = "a" * 40


class RemoteBuildTests(unittest.TestCase):
    def test_macos_and_arm_hosts_delegate_to_ssh(self):
        for system, machine in (("darwin", "arm64"), ("darwin", "x86_64"), ("linux", "aarch64")):
            with self.subTest(system=system, machine=machine), patch.object(remote.sys, "platform", system), patch.object(remote.platform, "machine", return_value=machine):
                self.assertEqual(remote.target("auto", "nvidia"), "nvidia")

    def test_linux_native_and_explicit_override(self):
        with patch.object(remote.sys, "platform", "linux"), patch.object(remote.platform, "machine", return_value="x86_64"):
            self.assertEqual(remote.target("auto", "nvidia"), "local")
            self.assertEqual(remote.target("ssh", "cluster@nvidia"), "cluster@nvidia")
        self.assertEqual(remote.target("local", "nvidia"), "local")

    def test_host_cannot_inject_ssh_options_or_shell_commands(self):
        for host in ("-oProxyCommand=evil", "host;touch /tmp/pwn", "h ost", "host\nexit", "", "$(id)"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                remote.target("ssh", host)

    def test_ssh_keeps_host_key_checking_and_disables_agent_forwarding(self):
        with patch.object(remote.subprocess, "run") as run:
            remote.ssh("nvidia", "printf '%s' 'path with spaces'", output=io.BytesIO())
        args, kwargs = run.call_args
        self.assertEqual(args[0][0], "ssh")
        self.assertIn("BatchMode=yes", args[0])
        self.assertIn("ForwardAgent=no", args[0])
        self.assertNotIn("StrictHostKeyChecking=no", args[0])
        self.assertFalse(kwargs["text"])
        self.assertTrue(kwargs["check"])

    def test_dirty_checkout_requires_explicit_committed_build(self):
        values = [COMMIT, "feat/atelier-mobile-tablet", "ok", " M tracked.py"]
        with patch.object(remote.image, "run", side_effect=values), self.assertRaises(RuntimeError):
            remote.source(False)
        with patch.object(remote.image, "run", side_effect=values):
            self.assertEqual(remote.source(True), (COMMIT, "feat/atelier-mobile-tablet"))

    def test_invalid_receipt_is_rejected_before_any_ssh(self):
        for directory in ("relative/build-x", "/home/x/../build-x", "/tmp/build-x\nexit", "/", "/tmp/anything"):
            with self.subTest(directory=directory), self.assertRaises(ValueError):
                remote.validate_receipt({"host": "nvidia", "commit": COMMIT, "directory": directory})

    def test_preflight_failure_does_not_clone_or_fetch(self):
        with patch.object(remote.shutil, "which", return_value="tool"), patch.object(remote, "source", return_value=(COMMIT, "feat/test")), patch.object(remote, "ssh", side_effect=RuntimeError("No Docker")) as ssh, self.assertRaises(RuntimeError):
            remote.remote_build("nvidia", False)
        ssh.assert_called_once_with("nvidia", remote.PREFLIGHT)

    def test_checkout_uses_exact_pushed_commit_in_new_directory(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(remote.image, "OUTPUT", Path(tmp)), patch.object(remote.shutil, "which", return_value="tool"), patch.object(remote, "source", return_value=(COMMIT, "feat/test")), patch.object(remote, "ssh", side_effect=[None, "/home/test/.cache/octoprint-atelier/build-123", None]) as ssh, patch.object(remote, "fetch") as fetch:
            remote.remote_build("nvidia", False)
            script = ssh.call_args_list[-1].args[1]
            self.assertIn("git fetch --tags origin " + COMMIT, script)
            self.assertIn("git checkout -B feat/test " + COMMIT, script)
            self.assertIn(remote.REPOSITORY, script)
            self.assertIn("python3 tools/pi/image.py build", script)
            self.assertNotIn("sudo", script)
            self.assertNotIn("rm -", script)
            self.assertNotIn("sdcard", script)
            receipt = json.loads((Path(tmp) / remote.RECEIPT).read_text())
            self.assertEqual(receipt["commit"], COMMIT)
            fetch.assert_called_once_with(receipt)

    def test_failed_build_leaves_recovery_receipt(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(remote.image, "OUTPUT", Path(tmp)), patch.object(remote.shutil, "which", return_value="tool"), patch.object(remote, "source", return_value=(COMMIT, "feat/test")), patch.object(remote, "ssh", side_effect=[None, "/tmp/build-123", subprocess.CalledProcessError(1, "ssh")]), patch.object(remote, "fetch") as fetch:
            with self.assertRaises(subprocess.CalledProcessError):
                remote.remote_build("nvidia", False)
            self.assertTrue((Path(tmp) / remote.RECEIPT).is_file())
            fetch.assert_not_called()

    def transfer(self, tmp, *, corrupt=False, wrong_commit=False):
        output = Path(tmp)
        img = output / remote.ARTIFACTS[0]
        img.write_bytes(b"old good image")
        payload = b"new known image"
        digest = hashlib.sha256(payload).hexdigest()
        contents = [
            b"corrupt" if corrupt else payload,
            (digest + "  octopi-atelier.img\n").encode(),
            json.dumps({"commit": "b" * 40 if wrong_commit else COMMIT, "image_sha256": digest}).encode(),
        ]
        def ssh(host, script, **kwargs):
            self.assertEqual(host, "nvidia")
            self.assertTrue(script.startswith("cat "))
            kwargs["output"].write(contents.pop(0))
        receipt = {"host": "nvidia", "commit": COMMIT, "directory": "/tmp/build-x"}
        with patch.object(remote.image, "OUTPUT", output), patch.object(remote.image, "IMAGE", img), patch.object(remote, "ssh", side_effect=ssh):
            remote.fetch(receipt)
        self.assertEqual(img.read_bytes(), payload)
        manifest = json.loads((output / "atelier.rpi-imager-manifest").read_text())
        self.assertEqual(manifest["os_list"][0]["url"], img.as_uri())

    def test_fetch_verifies_checksum_commit_and_local_imager_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.transfer(tmp)

    def test_failed_checksum_preserves_existing_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                self.transfer(tmp, corrupt=True)
            self.assertEqual((Path(tmp) / remote.ARTIFACTS[0]).read_bytes(), b"old good image")

    def test_wrong_commit_preserves_existing_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                self.transfer(tmp, wrong_commit=True)
            self.assertEqual((Path(tmp) / remote.ARTIFACTS[0]).read_bytes(), b"old good image")


if __name__ == "__main__":
    unittest.main()
