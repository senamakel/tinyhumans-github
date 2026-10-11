"""Exercise the MSRV selection shared by both module CI jobs."""

import json
from pathlib import Path
import re
import subprocess
import unittest
import os
import tempfile


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

    def test_concrete_root_without_msrv_is_rejected(self):
        metadata = {
            "workspace_members": ["root", "member"],
            "packages": [
                {"id": "root", "rust_version": None},
                {"id": "member", "rust_version": "1.88"},
            ],
            "resolve": {"root": "root"},
        }
        for result in self.select(metadata):
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("workspace root package must declare rust-version", result.stderr)

    def test_malformed_concrete_root_msrv_is_rejected(self):
        metadata = {
            "workspace_members": ["root"],
            "packages": [{"id": "root", "rust_version": "stable"}],
            "resolve": {"root": "root"},
        }
        for result in self.select(metadata):
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("workspace root rust-version must be numeric X.Y or X.Y.Z", result.stderr)

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
