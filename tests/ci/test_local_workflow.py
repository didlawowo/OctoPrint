"""Regression checks for the public fork's local CI execution boundary."""

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RUNNER = "${{ vars.RUNNER || 'arc-runner-octoprint' }}"
SHARED_REVISION = "b4688812f0262a7cd385f2ae729dca9b2f0e1e85"


class LocalCiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / ".github/workflows/atelier.yml").read_text(encoding="utf-8")
        # BaseLoader preserves GitHub's `on` key instead of YAML 1.1 boolean coercion.
        cls.workflow = yaml.load(cls.source, Loader=yaml.BaseLoader)
        cls.jobs = cls.workflow["jobs"]
        cls.steps = [step for job in cls.jobs.values() for step in job["steps"]]

    def test_only_repository_pushes_and_manual_runs_execute_project_code(self):
        self.assertEqual(set(self.workflow["on"]), {"push", "workflow_dispatch"})
        self.assertEqual(self.workflow["on"]["push"]["branches"], ["**"])
        for job in self.jobs.values():
            self.assertEqual(job["if"], "github.repository == 'didlawowo/OctoPrint'")

    def test_all_jobs_use_the_local_runner_and_have_timeouts(self):
        for job in self.jobs.values():
            with self.subTest(job=job["name"]):
                self.assertEqual(job["runs-on"], RUNNER)
                self.assertGreater(int(job["timeout-minutes"]), 0)
                self.assertLessEqual(int(job["timeout-minutes"]), 45)
        self.assertNotIn("RUNNER", self.workflow.get("env", {}))

    def test_token_is_read_only_and_not_persisted_in_checkouts(self):
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        for job in self.jobs.values():
            self.assertNotIn("permissions", job)
        for step in self.steps:
            if step.get("uses", "").startswith("actions/checkout@"):
                self.assertEqual(step["with"]["persist-credentials"], "false")
        self.assertNotIn("secrets.", self.source)

    def test_shared_actions_are_pinned_to_one_published_release_commit(self):
        actions = [
            step["uses"]
            for step in self.steps
            if step.get("uses", "").startswith("didlawowo/workflow-ci/")
        ]
        self.assertGreaterEqual(len(actions), 4)
        self.assertEqual(
            {action.rsplit("@", 1)[1] for action in actions}, {SHARED_REVISION}
        )

    def test_core_discovery_and_required_junit_evidence_are_preserved(self):
        step = next(
            step for step in self.steps if "/run-python-tests@" in step.get("uses", "")
        )
        command = step["with"]["test-command"]
        self.assertIn("--extra develop", command)
        self.assertIn("python -m pytest", command)
        self.assertIn("--junitxml=coverage-reports/pytest-report.xml", command)
        self.assertIn("--cov-report=xml:coverage-reports/coverage.xml", command)
        self.assertNotIn("--ignore", command)
        self.assertNotIn("-o addopts", command)
        self.assertNotIn("continue-on-error", step)

    def test_no_sd_build_flash_or_hardware_command_is_executed(self):
        commands = "\n".join(step.get("run", "") for step in self.steps)
        self.assertIn("task pi:test", commands)
        self.assertNotRegex(commands, r"pi:(?:build|flash|devices|prepare)")
        self.assertNotRegex(commands, r"(?:^|\s)(?:dd|mkfs|mount|kubectl|ssh)(?:\s|$)")
        self.assertNotRegex(commands, r"/dev/(?:sd|mmcblk|ttyUSB|ttyACM)")

    def test_browser_evidence_is_retained_on_failure(self):
        steps = self.jobs["browser"]["steps"]
        archive = next(
            step
            for step in steps
            if step.get("with", {}).get("name") == "atelier-browser-results"
        )
        self.assertEqual(archive["if"], "always()")
        self.assertEqual(archive["with"]["retention-days"], "7")
        self.assertIn("tests/playwright/test-results/", archive["with"]["path"])
        recipe = next(step for step in steps if "playwright test " in step.get("run", ""))
        self.assertIn("specs/atelier.spec.js", recipe["run"])
        self.assertNotIn("continue-on-error", recipe)
        self.assertIn("--workers=1", recipe["run"])
        self.assertEqual(
            recipe["env"]["PLAYWRIGHT_JUNIT_OUTPUT_FILE"], "test-results/junit.xml"
        )

    def test_browser_uses_a_fresh_isolated_server_directory(self):
        commands = "\n".join(
            step.get("run", "") for step in self.jobs["browser"]["steps"]
        )
        self.assertIn('mktemp -d "$RUNNER_TEMP/atelier-e2e.XXXXXX"', commands)
        self.assertIn('cp -a .github/ci/e2econfig/. "$test_dir/"', commands)
        self.assertIn("OCTOPRINT_SERVER_BASE=$test_dir", commands)
        self.assertNotIn("NO_SERVER", self.source)
        self.assertNotIn("PLAYWRIGHT_BASEURL", self.source)

    def test_all_action_references_are_immutable(self):
        for step in self.steps:
            if "uses" in step:
                self.assertTrue(
                    re.fullmatch(r"[0-9a-f]{40}", step["uses"].rsplit("@", 1)[1])
                )


if __name__ == "__main__":
    unittest.main()
