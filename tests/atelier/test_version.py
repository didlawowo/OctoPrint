"""Version metadata must preserve API 2 for fork checkouts and SD archives."""

import re
import runpy
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src/octoprint/_version.py"


class ForkVersionTests(unittest.TestCase):
    def test_fork_branches_follow_the_dev_version_line(self):
        data = runpy.run_path(str(SOURCE))
        for branch in (
            "feat/translate-fr",
            "feat/atelier-mobile-tablet",
            "origin/feat/atelier-mobile-tablet",
        ):
            versions = [
                item["tag"]
                for item in data["BRANCH_VERSIONS"]
                if any(re.match(pattern, branch) for pattern in item["patterns"])
            ]
            self.assertEqual(versions, ["2.1.0"])

    def test_source_archives_preserve_the_api_major_version(self):
        source = SOURCE.read_text()
        for refs in (
            "(HEAD -> feat/atelier-mobile-tablet)",
            "(origin/feat/atelier-mobile-tablet)",
            "(HEAD -> feat/atelier-mobile-tablet, origin/feat/atelier-mobile-tablet)",
        ):
            expanded = source.replace("$Format:%d$", refs).replace("$Format:%H$", "a" * 40)
            namespace = {"__file__": str(SOURCE), "__name__": "fork_version_test"}
            exec(compile(expanded, str(SOURCE), "exec"), namespace)
            result = namespace["_get_data_from_keywords"]()
            self.assertTrue(result["version"].startswith("2.1.0.dev"), result)
            self.assertEqual(result["revision"], "a" * 40)
