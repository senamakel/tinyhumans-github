"""Offline contract and negative-control tests for the reviewed module path."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).parents[1]
VERIFIER_PATH = ROOT / ".github/actions/module-reviewed-epic-preflight/verify.py"
SPEC = importlib.util.spec_from_file_location("module_reviewed_verify", VERIFIER_PATH)
if SPEC is None or SPEC.loader is None:
    raise AssertionError("module reviewed release verifier is missing")
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)

FIXTURE_PATH = Path(__file__).with_name("module-reviewed-release-fixtures.py")
FIXTURE_SPEC = importlib.util.spec_from_file_location("module_reviewed_fixtures", FIXTURE_PATH)
FIXTURES = importlib.util.module_from_spec(FIXTURE_SPEC)
FIXTURE_SPEC.loader.exec_module(FIXTURES)


class ModuleReviewedReleaseVerifierTests(unittest.TestCase):
    def test_only_three_exact_canonical_repository_package_workflow_profiles_exist(self):
        self.assertEqual(
            VERIFY.CI_WORKFLOW_IDS,
            {
                "tinyhumansai/tinyconnectors": 345777017,
                "tinyhumansai/tinybox": 334144667,
                "tinyhumansai/tinyjuice": 307270985,
            },
        )
        self.assertEqual(
            VERIFY.MODULE_PACKAGES,
            {
                "tinyhumansai/tinyconnectors": "tinyconnectors",
                "tinyhumansai/tinybox": "tinybox-module",
                "tinyhumansai/tinyjuice": "tinyjuice-module",
            },
        )
        self.assertEqual(len(VERIFY.REQUIRED_CHECKS), 13)

    def test_each_allowed_repository_accepts_the_complete_reviewed_merge_history(self):
        for repository, package in VERIFY.MODULE_PACKAGES.items():
            with self.subTest(repository=repository):
                fake = FIXTURES.module_release_fixture(VERIFY, repository, package)
                source = VERIFY.verify_reviewed_release(
                    fake.api, lambda *_: fake.git, repository, "v0.1.7", "0.1.7",
                    package, 75,
                )
                self.assertEqual(source, fake.tag_sha)
                self.assertEqual(
                    fake.checked_heads,
                    [fake.heads[75], fake.heads[73], fake.heads[74], fake.heads[72]],
                )

    def test_repository_package_and_tag_are_bound_before_history_admission(self):
        for repository, package in VERIFY.MODULE_PACKAGES.items():
            for bad_repository, bad_package, tag in (
                ("senamakel/" + repository.split("/", 1)[1], package, "v0.1.7"),
                (repository, "another-package", "v0.1.7"),
                (repository, package, "v0.1.8"),
            ):
                fake = FIXTURES.module_release_fixture(VERIFY, repository, package)
                with self.subTest(repository=repository, invalid=(bad_repository, bad_package, tag)):
                    with self.assertRaises(VERIFY.VerificationError):
                        VERIFY.verify_reviewed_release(
                            fake.api, lambda *_: fake.git, bad_repository, tag, "0.1.7",
                            bad_package, 75,
                        )

    def test_ci_workflow_identity_spoof_fails_closed(self):
        for repository, package in VERIFY.MODULE_PACKAGES.items():
            fake = FIXTURES.module_release_fixture(VERIFY, repository, package)
            fake.api.workflow_runs[fake.heads[75]][0]["workflow_id"] += 1
            with self.subTest(repository=repository):
                with self.assertRaises(VERIFY.VerificationError):
                    VERIFY.verify_reviewed_release(
                        fake.api, lambda *_: fake.git, repository, "v0.1.7", "0.1.7",
                        package, 75,
                    )

    def test_existing_sdk_and_module_release_sources_remain_byte_identical_to_upstream(self):
        import subprocess

        for path in (
            ".github/workflows/module-release.yml",
            ".github/workflows/sdk-release.yml",
            ".github/workflows/sdk-reviewed-epic-release.yml",
            ".github/actions/sdk-reviewed-epic-preflight/action.yml",
            ".github/actions/sdk-reviewed-epic-preflight/verify.py",
            ".github/actions/sdk-reviewed-epic-preflight/historical_ci.py",
        ):
            result = subprocess.run(
                ["git", "diff", "--quiet", "upstream/main", "--", path],
                cwd=ROOT, check=False,
            )
            self.assertEqual(result.returncode, 0, f"existing path changed: {path}")


class ModuleReviewedReleaseWorkflowTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / ".github/workflows/module-reviewed-epic-release.yml"
        self.workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)

    def test_all_source_execution_jobs_require_preflight_and_use_verified_sha(self):
        jobs = self.workflow["jobs"]
        source_jobs = ("validate", "native", "distro", "assemble")
        for name in source_jobs:
            with self.subTest(job=name):
                needs = jobs[name]["needs"]
                if isinstance(needs, str):
                    needs = [needs]
                self.assertIn("preflight", needs)
                checkouts = [
                    step for step in jobs[name]["steps"]
                    if step.get("uses", "").startswith("actions/checkout@")
                ]
                self.assertTrue(checkouts, f"{name} must check out source")
                for checkout in checkouts:
                    self.assertEqual(
                        checkout["with"]["ref"],
                        "${{ needs.preflight.outputs.source-sha }}",
                    )
                    self.assertEqual(checkout["with"].get("persist-credentials"), "false")

    def test_publish_is_the_only_write_job_and_rechecks_tag_after_artifacts(self):
        jobs = self.workflow["jobs"]
        write_jobs = [name for name, job in jobs.items()
                      if job.get("permissions", {}).get("contents") == "write"]
        self.assertEqual(write_jobs, ["publish"])
        publish = str(jobs["publish"])
        self.assertIn("tag-only", publish)
        self.assertIn("needs.preflight.outputs.source-sha", publish)
        self.assertNotIn("actions/checkout", publish)
        self.assertNotIn("cargo ", publish)

    def test_fixed_native_and_distro_targets_are_required_and_registry_is_absent(self):
        workflow = (ROOT / ".github/workflows/module-reviewed-epic-release.yml").read_text()
        self.assertNotIn("publish-crates-io", workflow)
        self.assertNotIn("CARGO_REGISTRY_TOKEN", workflow)
        self.assertNotIn("include-distros", workflow)
        self.assertIn("expected=17", workflow)


if __name__ == "__main__":
    unittest.main()
