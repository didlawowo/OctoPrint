"""Exercise uv bootstrap failure/recovery without networking or installing packages."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

# A fake uv uses Python's no-pip EnvBuilder only to provide realistic test fixtures.
# The production bootstrap must never use Homebrew's venv/ensurepip.
FAKE_UV = r'''
import json
import os
import subprocess
import sys
from pathlib import Path

args = sys.argv[1:]
record = {
    "args": args,
    "active": os.environ.get("VIRTUAL_ENV"),
    "project": os.environ.get("UV_PROJECT_ENVIRONMENT"),
    "index": os.environ.get("UV_DEFAULT_INDEX"),
}
with open(os.environ["UV_TEST_LOG"], "a", encoding="utf-8") as stream:
    stream.write(json.dumps(record) + "\n")
if os.environ.get("UV_TEST_FAIL") == " ".join(args[:2]):
    raise SystemExit(9)
if args[:2] == ["python", "install"]:
    pass
elif args[:2] == ["python", "find"]:
    print(sys._base_executable)
elif args[0] == "venv":
    target = Path(args[-1])
    if os.environ.get("UV_TEST_BAD_RESULT"):
        target.mkdir()
    else:
        subprocess.run([sys._base_executable, "-m", "venv", "--without-pip", str(target)], check=True)
else:
    raise SystemExit("Unexpected uv command: " + repr(args))
'''


class DevEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="atelier test ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "tools").mkdir()
        self.script = self.root / "tools/dev-env.sh"
        shutil.copy2(ROOT / "tools/dev-env.sh", self.script)
        self.commands = self.root / "commands"
        self.commands.mkdir()
        self.bash = shutil.which("bash")
        self.assertIsNotNone(self.bash)
        for name in ("dirname", "date", "mv"):
            (self.commands / name).symlink_to(shutil.which(name))
        self.uv = self.commands / "uv"
        self.uv.write_text(f"#!{sys.executable}\n" + FAKE_UV, encoding="utf-8")
        self.uv.chmod(0o755)
        self.log = self.root / "uv.log"
        self.env = {
            **os.environ,
            "PATH": str(self.commands),
            "UV_TEST_LOG": str(self.log),
            "ATELIER_PYTHON": "3.11",
        }
        for key in ("UV_TEST_FAIL", "UV_TEST_BAD_RESULT"):
            self.env.pop(key, None)
        self.venv = self.root / ".venv"

    def run_bootstrap(self, **overrides):
        return subprocess.run(
            [self.bash, str(self.script)],
            cwd=self.root.parent,
            env={**self.env, **overrides},
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )

    def records(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_create_managed_environment_without_activation_or_ensurepip(self):
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.venv / "bin/activate").is_file())
        calls = [record["args"] for record in self.records()]
        self.assertEqual(calls[0], ["python", "install", "3.11"])
        self.assertEqual(
            calls[1], ["python", "find", "--managed-python", "--system", "--no-project", "3.11"]
        )
        self.assertEqual(calls[2][0], "venv")
        self.assertIn("--managed-python", calls[2])
        self.assertEqual(calls[2][-1], str(self.venv))
        self.assertNotIn("--clear", calls[2])

    def test_partial_homebrew_environment_is_preserved_and_recreated(self):
        (self.venv / "bin").mkdir(parents=True)
        (self.venv / "bin/python").symlink_to(sys.executable)
        (self.venv / "pyvenv.cfg").write_text("home = /opt/homebrew\n")
        (self.venv / "keep.txt").write_text("do not delete")
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stderr)
        backups = list(self.root.glob(".venv.broken-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "keep.txt").read_text(), "do not delete")
        self.assertTrue((self.venv / "bin/activate").exists())

    def test_reuse_healthy_environment_without_discarding_installed_state(self):
        self.assertEqual(self.run_bootstrap().returncode, 0)
        (self.venv / "keep.txt").write_text("installed state")
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.venv / "keep.txt").read_text(), "installed state")
        self.assertFalse(list(self.root.glob(".venv.broken-*")))
        self.assertEqual(sum(r["args"][0] == "venv" for r in self.records()), 1)

    def test_download_failure_does_not_move_or_delete_previous_environment(self):
        self.venv.mkdir()
        (self.venv / "keep.txt").write_text("old")
        result = self.run_bootstrap(UV_TEST_FAIL="python install")
        self.assertEqual(result.returncode, 9)
        self.assertEqual((self.venv / "keep.txt").read_text(), "old")
        self.assertFalse(list(self.root.glob(".venv.broken-*")))
        self.assertEqual(len(self.records()), 1)

    def test_wrong_new_environment_fails_closed(self):
        result = self.run_bootstrap(UV_TEST_BAD_RESULT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no packages will be installed", result.stderr)

    def test_reject_symlink_without_touching_its_target(self):
        target = self.root / "another-environment"
        target.mkdir()
        (target / "keep.txt").write_text("untouched")
        self.venv.symlink_to(target, target_is_directory=True)
        result = self.run_bootstrap()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.venv.is_symlink())
        self.assertEqual((target / "keep.txt").read_text(), "untouched")
        self.assertEqual(self.records(), [])

    def test_reject_regular_file_named_venv(self):
        self.venv.write_text("not an environment")
        result = self.run_bootstrap()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.venv.read_text(), "not an environment")
        self.assertEqual(self.records(), [])

    def test_missing_uv_fails_before_mutating_the_environment(self):
        self.uv.unlink()
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 127)
        self.assertIn("brew install uv", result.stderr)
        self.assertFalse(self.venv.exists())

    def test_active_environments_cannot_redirect_uv_but_proxies_are_preserved(self):
        result = self.run_bootstrap(
            VIRTUAL_ENV="/some/other/environment",
            UV_PROJECT_ENVIRONMENT="/another/project",
            UV_DEFAULT_INDEX="https://packages.example.test/simple",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for record in self.records():
            self.assertIsNone(record["active"])
            self.assertIsNone(record["project"])
            self.assertEqual(record["index"], "https://packages.example.test/simple")

    def test_unsupported_or_shell_like_python_version_is_rejected(self):
        for version in ("3.9", "3.15", "3.11; touch injected", "-p"):
            with self.subTest(version=version):
                result = self.run_bootstrap(ATELIER_PYTHON=version)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.records(), [])


class DevTaskContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "Taskfile.yml").read_text(encoding="utf-8")
        cls.config = yaml.load(cls.source, Loader=yaml.BaseLoader)
        cls.tasks = cls.config["tasks"]

    def test_installers_are_uv_only_and_explicitly_target_dot_venv(self):
        for name in ("install", "install-dev"):
            commands = self.tasks[name]["cmds"]
            self.assertEqual(commands[0], {"task": "venv"})
            self.assertTrue(commands[1].startswith("uv pip install --python .venv/bin/python "))
            self.assertNotIn("--system", commands[1])
        self.assertNotIn("pipx", self.source)
        self.assertNotIn("python -m pip", self.source)
        self.assertEqual(self.tasks["init-dev"]["cmds"][1], ".venv/bin/pre-commit install")

    def test_launch_runs_setup_and_translations_in_order_then_the_local_binary(self):
        commands = self.tasks["dev"]["cmds"]
        self.assertEqual(
            commands[:3],
            [{"task": "install"}, {"task": "babel-compile"}, {"task": "babel-bundle"}],
        )
        self.assertIn("exec .venv/bin/octoprint serve", commands[3])
        self.assertEqual(self.config["vars"]["HOST"], "127.0.0.1")
        self.assertEqual(self.config["vars"]["PORT"], "5000")
        self.assertNotIn("ignore_error", self.source)
        self.assertNotIn("ignore-error", self.source)
        for name in ("venv", "install", "install-dev", "init-dev", "dev"):
            self.assertNotIn("deps", self.tasks[name])

    def test_babel_never_falls_back_to_a_broken_homebrew_executable(self):
        self.assertEqual(
            self.tasks["babel-compile"]["cmds"],
            [".venv/bin/pybabel compile --directory=translations"],
        )
        self.assertIn("messages.mo", self.tasks["babel-bundle"]["preconditions"][0]["sh"])

    def test_git_ignores_environments_and_recovery_backups_but_not_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            shutil.copy2(ROOT / ".gitignore", root / ".gitignore")
            paths = [".venv/bin/activate", "venv/bin/python", ".venv.broken-123/bin/python"]
            result = subprocess.run(
                ["git", "check-ignore", "--stdin"],
                cwd=root,
                input="\n".join(paths) + "\n",
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(result.stdout.splitlines(), paths)
            result = subprocess.run(
                ["git", "check-ignore", "tools/dev-env.sh", "tests/ci/test_dev_environment.py"],
                cwd=root,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
