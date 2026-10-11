"""Exercise the MSRV query used by both shared CI jobs."""
import json
from pathlib import Path
import re
import subprocess
import unittest
import os
import tempfile

class MsrvTests(unittest.TestCase):
    def query(self, metadata):
        """Run both workflow queries against a realistic Cargo metadata fixture."""
        workflow = (Path(__file__).parents[1] / ".github/workflows/module-ci.yml").read_text()
        queries = re.findall(r"jq -er '(.*?)'", workflow, re.S)
        self.assertEqual(len(queries), 2)
        results = [subprocess.run(["jq", "-er", query], input=json.dumps(metadata),
                                  text=True, capture_output=True) for query in queries]
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)
        return [result.stdout.strip() for result in results]

    def test_virtual_workspace_uses_highest_member_msrv(self):
        """Keep dependency MSRVs from changing the selected workspace promise."""
        self.assertEqual(self.query({"workspace_members": ["a", "b"],
            "packages": [{"id": "a", "rust_version": "1.9"},
                         {"id": "b", "rust_version": "1.88"},
                         {"id": "external", "rust_version": "1.99"}],
            "resolve": {"root": None}}), ["1.88", "1.88"])

    def test_root_package_keeps_its_own_msrv(self):
        """Keep dependency MSRVs from changing the selected workspace promise."""
        self.assertEqual(self.query({"workspace_members": ["a", "b"],
            "packages": [{"id": "a", "rust_version": "1.85"},
                         {"id": "b", "rust_version": "1.88"}],
            "resolve": {"root": "a"}}), ["1.85", "1.85"])

    def test_selected_package_features_stay_with_their_own_package(self):
        """Each public package builds at its compiler with only its qualified features."""
        workflow = (Path(__file__).parents[1] / ".github/workflows/module-ci.yml").read_text()
        block = workflow.split("      - name: Build with the declared MSRV", 1)[1]
        script = block.split("        run: |\n", 1)[1].split("\n  supply-chain:", 1)[0]
        script = "\n".join(line[10:] for line in script.splitlines())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "calls"
            metadata = {"packages": [{"name": "a", "rust_version": "1.70"},
                                     {"name": "b", "rust_version": "1.88"}]}
            cargo = root / "cargo"
            cargo.write_text("#!/usr/bin/env python3\nimport json,sys\n"
                             "if 'metadata' in sys.argv: print(" + repr(json.dumps(metadata)) + ")\n"
                             "else:\n"
                             " with open(" + repr(str(log)) + ", 'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n")
            cargo.chmod(0o755)
            rustup = root / "rustup"; rustup.write_text("#!/bin/sh\nexit 0\n"); rustup.chmod(0o755)
            env = dict(os.environ, PATH=str(root)+os.pathsep+os.environ["PATH"],
                       MSRV_BUILD_TARGETS=json.dumps([{"packages":["a","b"],"features":["a/foo","b/bar"]}]))
            result = subprocess.run(["bash","-e","-o","pipefail","-c",script], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(calls, [["+1.70","build","--package","a","--features","a/foo"],
                                     ["+1.88","build","--package","b","--features","b/bar"]])

if __name__ == "__main__":
    unittest.main()
