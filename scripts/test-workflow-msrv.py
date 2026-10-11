"""Exercise the MSRV query used by both shared CI jobs."""
import json
from pathlib import Path
import re
import subprocess
import unittest

class MsrvTests(unittest.TestCase):
    def query(self, metadata):
        workflow = (Path(__file__).parents[1] / ".github/workflows/module-ci.yml").read_text()
        queries = re.findall(r"jq -er '(.*?)'", workflow, re.S)
        self.assertEqual(len(queries), 2)
        results = [subprocess.run(["jq", "-er", query], input=json.dumps(metadata),
                                  text=True, capture_output=True) for query in queries]
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)
        return [result.stdout.strip() for result in results]

    def test_virtual_workspace_uses_highest_member_msrv(self):
        self.assertEqual(self.query({"workspace_members": ["a", "b"],
            "packages": [{"id": "a", "rust_version": "1.9"},
                         {"id": "b", "rust_version": "1.88"},
                         {"id": "external", "rust_version": "1.99"}],
            "resolve": {"root": None}}), ["1.88", "1.88"])

    def test_root_package_and_members_share_the_highest_msrv(self):
        self.assertEqual(self.query({"workspace_members": ["a", "b"],
            "packages": [{"id": "a", "rust_version": "1.85"},
                         {"id": "b", "rust_version": "1.88"}],
            "resolve": {"root": "a"}}), ["1.88", "1.88"])

if __name__ == "__main__":
    unittest.main()
