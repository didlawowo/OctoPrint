"""Version contracts for the fork pinned to the upstream 2.0.0rc6 source."""

import re
import runpy
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / "src/octoprint/_version.py"
BRANCH = "feat/atelier-2.0-rc6"
V2_BRANCH = "feat/atelier-v2"
MOBILE_BRANCH = "fix/atelier-v2-mobile-overflow"
COMMIT = "a" * 40


class ForkVersionTests(unittest.TestCase):
    def test_fork_rule_pins_release_and_exact_upstream_commit(self):
        data = runpy.run_path(str(SOURCE))
        for branch in (BRANCH, "origin/" + BRANCH, V2_BRANCH, "origin/" + V2_BRANCH, MOBILE_BRANCH, "origin/" + MOBILE_BRANCH):
            rules = [
                item
                for item in data["BRANCH_VERSIONS"]
                if any(re.fullmatch(p, branch) for p in item["patterns"])
            ]
            self.assertEqual(len(rules), 1)
            self.assertEqual(rules[0]["tag"], "2.0.0rc6")
            self.assertEqual(
                rules[0]["commit"], "75fef2506e6f4ce62b4b4e6eb6810ea67833622a"
            )

    def test_git_checkout_identifies_fork_without_claiming_a_final_release(self):
        data = runpy.run_path(str(SOURCE))
        fn = data["_get_data_from_git"]
        for branch in (BRANCH, V2_BRANCH, MOBILE_BRANCH):
            with self.subTest(branch=branch):
                overrides = {
                    "_get_branch": lambda branch=branch: branch,
                    "_get_long": lambda: COMMIT,
                    "_get_short": lambda: COMMIT[:8],
                    "_get_tag": lambda: "2.0.0rc6",
                    "_get_distance": lambda ref: 1,
                    "_get_dirty": lambda: False,
                }
                with patch.dict(fn.__globals__, overrides):
                    result = fn()
                self.assertEqual(result["version"], "2.0.0rc6+atelier.gaaaaaaaa")
                self.assertEqual(result["revision"], COMMIT)

    def test_archives_do_not_mistake_a_numeric_branch_for_a_tag(self):
        for refs in (
            f"(HEAD -> {BRANCH})",
            f"(origin/{BRANCH})",
            f"(HEAD -> {BRANCH}, origin/{BRANCH})",
            f"(HEAD -> {V2_BRANCH})",
            f"(origin/{V2_BRANCH})",
            f"(HEAD -> {V2_BRANCH}, origin/{V2_BRANCH})",
            f"(HEAD -> {MOBILE_BRANCH})",
            f"(origin/{MOBILE_BRANCH})",
        ):
            text = (
                SOURCE.read_text()
                .replace("$Format:%d$", refs)
                .replace("$Format:%H$", COMMIT)
            )
            data = {"__file__": str(SOURCE), "__name__": "version_test"}
            exec(compile(text, str(SOURCE), "exec"), data)
            result = data["_get_data_from_keywords"]()
            self.assertEqual(result["version"], "2.0.0rc6+atelier.gaaaaaaaa")
            self.assertEqual(result["revision"], COMMIT)

    def test_real_upstream_tag_retains_its_release_version(self):
        text = (
            SOURCE.read_text()
            .replace("$Format:%d$", "(tag: 2.0.0rc6)")
            .replace("$Format:%H$", COMMIT)
        )
        data = {"__file__": str(SOURCE), "__name__": "version_test"}
        exec(compile(text, str(SOURCE), "exec"), data)
        self.assertEqual(data["_get_data_from_keywords"]()["version"], "2.0.0rc6")


if __name__ == "__main__":
    unittest.main()
