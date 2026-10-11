"""Exercise the MSRV selection shared by both module CI jobs."""

import json
from pathlib import Path
import re
import subprocess
import unittest


WORKFLOW = Path(__file__).parents[1] / ".github/workflows/module-ci.yml"


class WorkspaceMsrvTests(unittest.TestCase):
    def queries(self):
        workflow = WORKFLOW.read_text()
        queries = re.findall(r"jq -er '(.*?)'", workflow, re.S)
        self.assertEqual(len(queries), 2)
        return queries

    def select(self, metadata):
        results = [
            subprocess.run(
                ["jq", "-er", query],
                input=json.dumps(metadata),
                text=True,
                capture_output=True,
                check=False,
            )
            for query in self.queries()
        ]
        return results

    def test_concrete_workspace_keeps_root_package_msrv(self):
        metadata = {
            "workspace_members": ["root", "member"],
            "packages": [
                {"id": "root", "rust_version": "1.85"},
                {"id": "member", "rust_version": "1.100"},
                {"id": "dependency", "rust_version": "1.120"},
            ],
            "resolve": {"root": "root"},
        }
        results = self.select(metadata)
        self.assertEqual([result.returncode for result in results], [0, 0])
        self.assertEqual([result.stdout.strip() for result in results], ["1.85", "1.85"])

    def test_virtual_workspace_uses_highest_member_msrv_numerically(self):
        metadata = {
            "workspace_members": ["older", "newer"],
            "packages": [
                {"id": "older", "rust_version": "1.99"},
                {"id": "newer", "rust_version": "1.100"},
                {"id": "dependency", "rust_version": "1.200"},
            ],
            "resolve": {"root": None},
        }
        results = self.select(metadata)
        self.assertEqual([result.returncode for result in results], [0, 0])
        self.assertEqual([result.stdout.strip() for result in results], ["1.100", "1.100"])

    def test_virtual_workspace_without_declared_member_msrv_is_rejected(self):
        metadata = {
            "workspace_members": ["one", "two"],
            "packages": [
                {"id": "one", "rust_version": None},
                {"id": "two", "rust_version": None},
                {"id": "dependency", "rust_version": "1.88"},
            ],
            "resolve": {"root": None},
        }
        for result in self.select(metadata):
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("workspace members must declare rust-version", result.stderr)

    def test_malformed_workspace_member_msrv_is_rejected(self):
        metadata = {
            "workspace_members": ["one", "two"],
            "packages": [
                {"id": "one", "rust_version": "stable"},
                {"id": "two", "rust_version": "1.88"},
            ],
            "resolve": {"root": None},
        }
        for result in self.select(metadata):
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("workspace package rust-version must be numeric X.Y or X.Y.Z", result.stderr)


if __name__ == "__main__":
    unittest.main()
