"""Offline contract and negative-control tests for the reviewed module path."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml


ROOT = Path(__file__).parents[1]
BASELINE_SOURCE_COMMIT = "0cafb7aada1e706fa237948c52decd9b753b111c"
# Git blob IDs recorded from BASELINE_SOURCE_COMMIT; these remain checkable without remote refs.
UNCHANGED_PATH_BLOBS = {
    ".github/workflows/module-release.yml": "6e46ec0415347e8c1ac3a1cbf2fe9a7b806cca7d",
    ".github/workflows/sdk-release.yml": "1db85a6cbc003067983c4f2bf2a86b4935f6119a",
    ".github/workflows/sdk-reviewed-epic-release.yml": "606a5c9ae9d517ad2be556937caf1376eee7eb2c",
    ".github/actions/sdk-reviewed-epic-preflight/action.yml": "ebbbf7f3f1d0b80ee9fb36f51451cff836024ee0",
    ".github/actions/sdk-reviewed-epic-preflight/verify.py": "ac7106d353f3940332db3025852b0c7eb42545d0",
    ".github/actions/sdk-reviewed-epic-preflight/historical_ci.py": "1b61ab203a55be0f7fedb416a21d372cb25c3325",
}
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
    def test_only_four_exact_canonical_repository_package_workflow_profiles_exist(self):
        self.assertEqual(
            VERIFY.CI_WORKFLOW_IDS,
            {
                "tinyhumansai/tinyconnectors": 345777017,
                "tinyhumansai/tinybox": 334144667,
                "tinyhumansai/tinyjuice": 307270985,
                "tinyhumansai/tinywallet": 331024528,
            },
        )
        self.assertEqual(
            {repo: profile["module_ci_sha"] for repo, profile in VERIFY.MODULE_PROFILES.items()},
            {
                "tinyhumansai/tinyconnectors": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
                "tinyhumansai/tinybox": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
                "tinyhumansai/tinyjuice": "3e87ade76b622844985d0c665a3b075313e4545c",
                "tinyhumansai/tinywallet": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
            },
        )
        self.assertEqual(
            VERIFY.MODULE_PACKAGES,
            {
                "tinyhumansai/tinyconnectors": "tinyconnectors",
                "tinyhumansai/tinybox": "tinybox-module",
                "tinyhumansai/tinyjuice": "tinyjuice-module",
                "tinyhumansai/tinywallet": "tinywallet-module",
            },
        )
        self.assertEqual(VERIFY.CHECK_APP_ID, 15368)
        self.assertEqual(
            VERIFY.REQUIRED_CHECKS,
            tuple("module-ci / " + name for name in (
                "fmt", "clippy", "test", "coverage", "docs", "msrv", "supply-chain",
                "module-e2e (ubuntu-latest)", "module-e2e (macos-latest)",
                "module-e2e (windows-latest)", "feature-tests (ubuntu-latest)",
                "feature-tests (macos-latest)", "feature-tests (windows-latest)",
            )),
        )
        self.assertEqual(
            {repo: profile["manifest"] for repo, profile in VERIFY.MODULE_PROFILES.items()},
            {repo: "Cargo.toml" for repo in VERIFY.MODULE_PROFILES},
        )
        self.assertEqual(VERIFY.MODULE_PROFILES["tinyhumansai/tinywallet"]["asset"], "tinywallet-module")
        self.assertEqual(VERIFY.MODULE_PROFILES["tinyhumansai/tinywallet"]["extra_files"], [])
        self.assertEqual(
            VERIFY.MODULE_PROFILES["tinyhumansai/tinyjuice"]["extra_files"],
            ["docs/specs/tinybus-module.md"],
        )

    def test_tag_only_recheck_requires_same_canonical_profile_and_sha(self):
        class Api:
            repository = "tinyhumansai/tinyconnectors"
            tag_sha = "a" * 40

            def tag_commit(self, tag):
                self.asserted_tag = tag
                return self.tag_sha

        api = Api()
        VERIFY.verify_tag_binding(api, "v1.2.3", "a" * 40, "tinyconnectors")
        with self.assertRaisesRegex(VERIFY.VerificationError, "outside the reviewed allowlist"):
            VERIFY.verify_tag_binding(api, "v1.2.3", "a" * 40, "tinybox-module")
        api.tag_sha = "b" * 40
        with self.assertRaisesRegex(VERIFY.VerificationError, "no longer resolves"):
            VERIFY.verify_tag_binding(api, "v1.2.3", "a" * 40, "tinyconnectors")

    def test_composite_preflight_env_derives_each_package_from_the_allowlist(self):
        for repository, package in VERIFY.MODULE_PACKAGES.items():
            fake = FIXTURES.module_release_fixture(VERIFY, repository, package)
            with tempfile.TemporaryDirectory(prefix="module-release-output-") as directory:
                output_path = Path(directory) / "github-output"
                environment = {
                    "MODE": "reviewed",
                    "GH_REPO": repository,
                    "GH_TOKEN": "test-token",
                    "TAG": "v0.1.7",
                    "VERSION": "0.1.7",
                    "REVIEWED_PR": "75",
                    "GITHUB_OUTPUT": str(output_path),
                }
                with self.subTest(repository=repository):
                    with mock.patch.object(VERIFY, "GitHubApi", return_value=fake.api), \
                            mock.patch.object(VERIFY, "BareHistory", return_value=fake.git), \
                            mock.patch.dict(os.environ, environment, clear=False):
                        self.assertEqual(VERIFY.main(), 0)
                        outputs = dict(
                            line.split("=", 1) for line in output_path.read_text().splitlines()
                        )
                        self.assertEqual(outputs["module-package"], package)
                        self.assertEqual(outputs["source-sha"], fake.tag_sha)

    def test_main_rejects_explicit_package_mismatch_before_github_api_use(self):
        environment = {
            "MODE": "reviewed",
            "GH_REPO": "tinyhumansai/tinyconnectors",
            "GH_TOKEN": "test-token",
            "TAG": "v0.1.7",
            "VERSION": "0.1.7",
            "REVIEWED_PR": "75",
            "PACKAGE": "tinybox-module",
        }
        with mock.patch.object(VERIFY, "GitHubApi", side_effect=AssertionError("API must not run")), \
                mock.patch.dict(os.environ, environment, clear=False):
            with self.assertRaisesRegex(VERIFY.VerificationError, "outside the reviewed allowlist"):
                VERIFY.main()

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

        fake = FIXTURES.module_release_fixture(VERIFY, "tinyhumansai/tinyconnectors", "tinyconnectors")
        fake.api.repository = "tinyhumansai/tinybox"
        with self.assertRaisesRegex(VERIFY.VerificationError, "does not match the canonical module profile"):
            VERIFY.verify_reviewed_release(
                fake.api, lambda *_: fake.git, "tinyhumansai/tinyconnectors", "v0.1.7",
                "0.1.7", "tinyconnectors", 75,
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

        repository = "tinyhumansai/tinyjuice"
        package = VERIFY.MODULE_PACKAGES[repository]
        fake = FIXTURES.module_release_fixture(VERIFY, repository, package)
        fake.api.checks[fake.heads[75]][0]["app"]["id"] = 1
        with self.assertRaisesRegex(VERIFY.VerificationError, "trusted CI check is missing"):
            VERIFY.verify_reviewed_release(
                fake.api, lambda *_: fake.git, repository, "v0.1.7", "0.1.7", package, 75,
            )

    def test_canonical_ci_event_repository_base_and_reusable_workflow_are_bound(self):
        repository = "tinyhumansai/tinyconnectors"
        package = VERIFY.MODULE_PACKAGES[repository]
        for mutate, message in (
            (lambda association: association["base"]["repo"].update(full_name="senamakel/tinyconnectors"),
             "repository binding did not match"),
            (lambda association: association["base"].update(ref="main"),
             "base or head binding did not match"),
        ):
            fake = FIXTURES.module_release_fixture(VERIFY, repository, package)
            run = fake.api.workflow_runs[fake.heads[75]][0]
            mutate(run["pull_requests"][0])
            with self.subTest(expected=message):
                with self.assertRaisesRegex(VERIFY.VerificationError, message):
                    VERIFY.verify_reviewed_release(
                        fake.api, lambda *_: fake.git, repository, "v0.1.7", "0.1.7",
                        package, 75,
                    )

        fake = FIXTURES.module_release_fixture(VERIFY, repository, package)
        run = fake.api.workflow_runs[fake.heads[75]][0]
        run["referenced_workflows"][0]["sha"] = "0" * 40
        with self.assertRaisesRegex(VERIFY.VerificationError, "workflow pin was not trusted"):
            VERIFY.verify_reviewed_release(
                fake.api, lambda *_: fake.git, repository, "v0.1.7", "0.1.7", package, 75,
            )

    def test_each_repository_accepts_only_its_literal_module_ci_revision(self):
        pins = FIXTURES.TRUSTED_MODULE_CI_PINS
        for repository, package in VERIFY.MODULE_PACKAGES.items():
            correct_pin = pins[repository]
            other_pins = {pin for pin in pins.values() if pin != correct_pin}
            for wrong_pin in other_pins:
                fake = FIXTURES.module_release_fixture(VERIFY, repository, package)
                run = fake.api.workflow_runs[fake.heads[75]][0]
                run["referenced_workflows"][0]["sha"] = wrong_pin
                run["referenced_workflows"][0]["path"] = (
                    "tinyhumansai/.github/.github/workflows/module-ci.yml@" + wrong_pin
                )
                with self.subTest(repository=repository, wrong_pin=wrong_pin):
                    with self.assertRaisesRegex(VERIFY.VerificationError, "workflow pin was not trusted"):
                        VERIFY.verify_reviewed_release(
                            fake.api, lambda *_: fake.git, repository, "v0.1.7", "0.1.7",
                            package, 75,
                        )

        repository = "tinyhumansai/tinyjuice"
        package = VERIFY.MODULE_PACKAGES[repository]
        fake = FIXTURES.module_release_fixture(VERIFY, repository, package)
        run = fake.api.workflow_runs[fake.heads[75]][0]
        fmt_job = fake.api.workflow_jobs[(run["id"], run["run_attempt"])][0]
        fake.api.logs[fmt_job["id"]] = fake.api.logs[fmt_job["id"]].replace(
            VERIFY.MODULE_PROFILES[repository]["module_ci_sha"],
            "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
        )
        with self.assertRaisesRegex(VERIFY.VerificationError, "pinned reusable workflow"):
            VERIFY.verify_reviewed_release(
                fake.api, lambda *_: fake.git, repository, "v0.1.7", "0.1.7", package, 75,
            )

    def test_wrong_epic_base_and_false_merge_association_fail_closed(self):
        repository = "tinyhumansai/tinyconnectors"
        package = VERIFY.MODULE_PACKAGES[repository]
        fake = FIXTURES.module_release_fixture(VERIFY, repository, package)
        fake.api.pulls[75]["base"]["ref"] = "main"
        with self.assertRaisesRegex(VERIFY.VerificationError, "approved canonical epic base"):
            VERIFY.verify_reviewed_release(
                fake.api, lambda *_: fake.git, repository, "v0.1.7", "0.1.7", package, 75,
            )

        fake = FIXTURES.module_release_fixture(VERIFY, repository, package)
        first_parent, _ = fake.parents[fake.merges[75]]
        fake.parents[fake.merges[75]] = (first_parent, "e" * 40)
        with self.assertRaisesRegex(VERIFY.VerificationError, "exact merged pull request"):
            VERIFY.verify_reviewed_release(
                fake.api, lambda *_: fake.git, repository, "v0.1.7", "0.1.7", package, 75,
            )

    def test_failed_ci_and_unresolved_review_threads_fail_closed(self):
        repository = "tinyhumansai/tinybox"
        package = VERIFY.MODULE_PACKAGES[repository]
        fake = FIXTURES.module_release_fixture(VERIFY, repository, package)
        run = fake.api.workflow_runs[fake.heads[75]][0]
        fake.api.workflow_jobs[(run["id"], run["run_attempt"])][1]["conclusion"] = "failure"
        with self.assertRaisesRegex(VERIFY.VerificationError, "canonical CI job is not successful"):
            VERIFY.verify_reviewed_release(
                fake.api, lambda *_: fake.git, repository, "v0.1.7", "0.1.7", package, 75,
            )

        fake = FIXTURES.module_release_fixture(VERIFY, repository, package)
        fake.api.threads[75] = [{"isResolved": False, "isOutdated": False}]
        with self.assertRaisesRegex(VERIFY.VerificationError, "unresolved review thread"):
            VERIFY.verify_reviewed_release(
                fake.api, lambda *_: fake.git, repository, "v0.1.7", "0.1.7", package, 75,
            )

        fake = FIXTURES.module_release_fixture(VERIFY, repository, package)
        fake.api.reviews[75] = [{
            "user": {"login": "reviewer"}, "state": "CHANGES_REQUESTED",
            "commit_id": fake.heads[75], "submitted_at": "2026-10-17T12:00:00Z", "id": 750,
        }]
        with self.assertRaisesRegex(VERIFY.VerificationError, "effective changes-requested"):
            VERIFY.verify_reviewed_release(
                fake.api, lambda *_: fake.git, repository, "v0.1.7", "0.1.7", package, 75,
            )

    def test_stale_workflow_attempt_without_required_jobs_fails_closed(self):
        repository = "tinyhumansai/tinybox"
        package = VERIFY.MODULE_PACKAGES[repository]
        fake = FIXTURES.module_release_fixture(VERIFY, repository, package)
        fake.api.workflow_runs[fake.heads[75]][0]["run_attempt"] = 2
        original_jobs = fake.api.jobs_for_workflow_run

        def current_attempt_jobs(run_id, attempt):
            try:
                return original_jobs(run_id, attempt)
            except KeyError:
                return []

        fake.api.jobs_for_workflow_run = current_attempt_jobs
        with self.assertRaisesRegex(VERIFY.VerificationError, "trusted CI check is missing"):
            VERIFY.verify_reviewed_release(
                fake.api, lambda *_: fake.git, repository, "v0.1.7", "0.1.7", package, 75,
            )

    def test_synthetic_merge_tree_must_match_canonical_reviewed_merge(self):
        repository = "tinyhumansai/tinyjuice"
        package = VERIFY.MODULE_PACKAGES[repository]
        fake = FIXTURES.module_release_fixture(VERIFY, repository, package)
        merge_parents = fake.parents[fake.merges[75]]
        proof_sha = next(
            sha for sha, record in fake.api.commit_records.items()
            if record["parents"] == merge_parents and sha != fake.merges[75]
        )
        fake.api.commit_records[proof_sha]["tree_sha"] = "f" * 40
        with self.assertRaisesRegex(VERIFY.VerificationError, "merge tree"):
            VERIFY.verify_reviewed_release(
                fake.api, lambda *_: fake.git, repository, "v0.1.7", "0.1.7", package, 75,
            )

    def test_rest_pagination_exhaustion_is_a_hard_failure(self):
        api = VERIFY.GitHubApi("placeholder-token", "tinyhumansai/tinyconnectors")
        api._request = lambda _path, **_kwargs: [None] * 100
        with self.assertRaisesRegex(VERIFY.VerificationError, "pagination exceeded"):
            api.rest_pages("repos/tinyhumansai/tinyconnectors/pulls")

    def test_existing_sdk_and_module_release_sources_match_reviewed_baseline_blobs(self):
        for path, expected_blob in UNCHANGED_PATH_BLOBS.items():
            result = subprocess.run(
                ["git", "rev-parse", f"HEAD:{path}"],
                cwd=ROOT, check=False, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, f"tracked baseline path missing: {path}")
            self.assertEqual(
                result.stdout.strip(), expected_blob,
                f"{path} differs from reviewed source {BASELINE_SOURCE_COMMIT}",
            )

    def test_baseline_check_works_in_checkout_without_upstream_remote_or_ref(self):
        if os.environ.get("MODULE_REVIEWED_CLEAN_CHECKOUT_CHILD") == "1":
            return
        with tempfile.TemporaryDirectory(prefix="module-reviewed-clean-checkout-") as directory:
            checkout = Path(directory) / "checkout"
            init = subprocess.run(
                ["git", "init", str(checkout)], check=False,
                capture_output=True, text=True,
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            fetch = subprocess.run(
                ["git", "-C", str(checkout), "fetch", "--no-tags", str(ROOT),
                 "HEAD:refs/heads/portable-test"],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(fetch.returncode, 0, fetch.stderr)
            checkout_result = subprocess.run(
                ["git", "-C", str(checkout), "checkout", "--detach", "portable-test"],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(checkout_result.returncode, 0, checkout_result.stderr)
            remotes = subprocess.run(
                ["git", "-C", str(checkout), "remote"],
                check=False, capture_output=True, text=True,
            )
            self.assertNotIn("upstream", remotes.stdout.splitlines())
            upstream_ref = subprocess.run(
                ["git", "-C", str(checkout), "show-ref", "--verify",
                 "refs/remotes/upstream/epic/8056-modules-wiring"],
                check=False, capture_output=True, text=True,
            )
            self.assertNotEqual(upstream_ref.returncode, 0)
            (checkout / "scripts/test-module-reviewed-epic-release.py").write_bytes(
                (ROOT / "scripts/test-module-reviewed-epic-release.py").read_bytes()
            )
            child_environment = os.environ.copy()
            child_environment["MODULE_REVIEWED_CLEAN_CHECKOUT_CHILD"] = "1"
            result = subprocess.run(
                [sys.executable,
                 str(checkout / "scripts/test-module-reviewed-epic-release.py"),
                 "ModuleReviewedReleaseVerifierTests.test_existing_sdk_and_module_release_sources_match_reviewed_baseline_blobs"],
                cwd=checkout, env=child_environment, check=False,
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_preflight_action_pin_is_immutable_and_matches_the_complete_action_tree(self):
        import subprocess

        action = yaml.load(
            (ROOT / ".github/actions/module-reviewed-epic-preflight/action.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        self.assertEqual(action["runs"]["using"], "composite")
        action_steps = action["runs"]["steps"]
        self.assertEqual(len(action_steps), 1)
        self.assertEqual(action_steps[0]["id"], "verify")
        self.assertEqual(action_steps[0]["run"], 'python3 "$GITHUB_ACTION_PATH/verify.py"')
        self.assertNotIn("run", action_steps[0].get("env", {}))

        workflow = yaml.load(
            (ROOT / ".github/workflows/module-reviewed-epic-release.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        action_path = ".github/actions/module-reviewed-epic-preflight"
        uses = [
            step.get("uses", "")
            for job in workflow["jobs"].values()
            for step in job.get("steps", [])
            if "module-reviewed-epic-preflight@" in step.get("uses", "")
        ]
        self.assertEqual(len(uses), 2)
        self.assertTrue(all(
            item.startswith("tinyhumansai/.github/" + action_path + "@")
            for item in uses
        ))
        pins = {item.rsplit("@", 1)[1] for item in uses}
        self.assertEqual(len(pins), 1)
        pin = pins.pop()
        self.assertRegex(pin, r"^[0-9a-f]{40}$")
        pinned = subprocess.run(
            ["git", "rev-parse", f"{pin}:{action_path}"], cwd=ROOT,
            capture_output=True, text=True, check=False,
        )
        current = subprocess.run(
            ["git", "rev-parse", f"HEAD:{action_path}"], cwd=ROOT,
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(pinned.returncode, 0, "pinned action tree is missing")
        self.assertEqual(current.returncode, 0, "current action tree is missing")
        self.assertEqual(pinned.stdout.strip(), current.stdout.strip())


class ModuleReviewedReleaseWorkflowTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / ".github/workflows/module-reviewed-epic-release.yml"
        self.workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)

    def test_caller_cannot_choose_repository_profile_or_package_metadata(self):
        inputs = self.workflow["on"]["workflow_call"]["inputs"]
        self.assertEqual(set(inputs), {"tag", "version", "reviewed-pr"})

    def test_all_source_execution_jobs_require_preflight_and_use_verified_sha(self):
        jobs = self.workflow["jobs"]
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        self.assertEqual(
            jobs["preflight"]["permissions"],
            {"contents": "read", "pull-requests": "read", "checks": "read", "actions": "read"},
        )
        self.assertTrue(all(
            "actions/checkout" not in step.get("uses", "")
            for step in jobs["preflight"]["steps"]
        ))
        verifier_step = jobs["preflight"]["steps"][0]
        self.assertEqual(
            set(verifier_step["with"]),
            {"token", "tag", "version", "reviewed-pr"},
        )
        self.assertNotIn("package", verifier_step["with"])
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
                self.assertNotIn("GH_TOKEN", str(jobs[name]))

    def test_publish_is_the_only_write_job_and_rechecks_tag_after_artifacts(self):
        jobs = self.workflow["jobs"]
        write_jobs = [name for name, job in jobs.items()
                      if job.get("permissions", {}).get("contents") == "write"]
        self.assertEqual(write_jobs, ["publish"])
        self.assertEqual(
            jobs["publish"]["permissions"],
            {"contents": "write"},
        )
        self.assertEqual(
            set(jobs["publish"]["needs"]),
            {"preflight", "validate", "native", "distro", "assemble"},
        )
        self.assertNotIn("if", jobs["publish"])
        publish = str(jobs["publish"])
        self.assertIn("tag-only", publish)
        self.assertIn("needs.preflight.outputs.source-sha", publish)
        self.assertNotIn("actions/checkout", publish)
        self.assertNotIn("cargo ", publish)
        for prerequisite in ("preflight", "validate", "native", "distro"):
            self.assertIn(
                f"needs.{prerequisite}.result == 'success'",
                jobs["assemble"]["if"],
            )

    def test_fixed_native_and_distro_targets_are_required_and_registry_is_absent(self):
        workflow = (ROOT / ".github/workflows/module-reviewed-epic-release.yml").read_text()
        jobs = self.workflow["jobs"]
        self.assertEqual(len(jobs["native"]["strategy"]["matrix"]["include"]), 11)
        self.assertEqual(len(jobs["distro"]["strategy"]["matrix"]["include"]), 6)
        self.assertNotIn("publish-crates-io", workflow)
        self.assertNotIn("CARGO_REGISTRY_TOKEN", workflow)
        self.assertNotIn("include-distros", workflow)
        self.assertNotIn("extra-packaged-files", self.workflow["on"]["workflow_call"]["inputs"])
        self.assertNotIn("apt-packages", self.workflow["on"]["workflow_call"]["inputs"])
        self.assertIn("expected=17", workflow)


if __name__ == "__main__":
    unittest.main()
