"""Offline contract and negative-control tests for the reviewed module path."""

from __future__ import annotations

import importlib.util
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
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
    def test_only_eight_exact_canonical_repository_package_workflow_profiles_exist(self):
        self.assertEqual(
            VERIFY.CI_WORKFLOW_IDS,
            {
                "tinyhumansai/tinyconnectors": 345777017,
                "tinyhumansai/tinybox": 334144667,
                "tinyhumansai/tinyjuice": 307270985,
                "tinyhumansai/tinywallet": 331024528,
                "tinyhumansai/tinymcp": 339480400,
                "tinyhumansai/tinychannels": 307289287,
                "tinyhumansai/tinydocs": 331024957,
                "tinyhumansai/tinyvoice": 333928426,
            },
        )
        self.assertEqual(
            {repo: profile["module_ci_sha"] for repo, profile in VERIFY.MODULE_PROFILES.items()},
            {
                "tinyhumansai/tinyconnectors": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
                "tinyhumansai/tinybox": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
                "tinyhumansai/tinyjuice": "3e87ade76b622844985d0c665a3b075313e4545c",
                "tinyhumansai/tinywallet": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
                "tinyhumansai/tinymcp": "62c8ae0468f3882b75947d5cba9687e609ce1fed",
                "tinyhumansai/tinychannels": "3e87ade76b622844985d0c665a3b075313e4545c",
                "tinyhumansai/tinydocs": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
                "tinyhumansai/tinyvoice": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
            },
        )
        self.assertEqual(
            VERIFY.MODULE_PACKAGES,
            {
                "tinyhumansai/tinyconnectors": "tinyconnectors",
                "tinyhumansai/tinybox": "tinybox-module",
                "tinyhumansai/tinyjuice": "tinyjuice-module",
                "tinyhumansai/tinywallet": "tinywallet-module",
                "tinyhumansai/tinymcp": "tinymcp",
                "tinyhumansai/tinychannels": "tinychannels-module",
                "tinyhumansai/tinydocs": "tinydocs-module",
                "tinyhumansai/tinyvoice": "tinyvoice-module",
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
            {
                repo: ("crates/tinyvoice-module/Cargo.toml" if repo == "tinyhumansai/tinyvoice" else "Cargo.toml")
                for repo in VERIFY.MODULE_PROFILES
            },
        )
        self.assertEqual(VERIFY.MODULE_PROFILES["tinyhumansai/tinywallet"]["asset"], "tinywallet-module")
        self.assertEqual(VERIFY.MODULE_PROFILES["tinyhumansai/tinywallet"]["extra_files"], [])
        self.assertEqual(VERIFY.MODULE_PROFILES["tinyhumansai/tinychannels"]["asset"], "tinychannels-module")
        self.assertEqual(VERIFY.MODULE_PROFILES["tinyhumansai/tinychannels"]["extra_files"], [])
        self.assertEqual(
            VERIFY.MODULE_PROFILES["tinyhumansai/tinyjuice"]["extra_files"],
            ["docs/specs/tinybus-module.md"],
        )
        self.assertEqual(
            VERIFY.MODULE_PROFILES["tinyhumansai/tinydocs"],
            {
                "package": "tinydocs-module", "asset": "tinydocs-module", "manifest": "Cargo.toml",
                "extra_files": ["docs/specs/tinybus-module.md"], "workflow_id": 331024957,
                "module_ci_sha": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
                "source_bundle": "tinydocs",
            },
        )
        self.assertEqual(
            VERIFY.MODULE_PROFILES["tinyhumansai/tinyvoice"],
            {
                "package": "tinyvoice-module", "asset": "tinyvoice-module",
                "manifest": "crates/tinyvoice-module/Cargo.toml", "extra_files": [],
                "workflow_id": 333928426,
                "module_ci_sha": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
                "apt_packages": "libasound2-dev libx11-dev libxtst-dev libxi-dev",
            },
        )
        self.assertEqual(
            VERIFY.MODULE_PROFILES["tinyhumansai/tinymcp"],
            {
                "package": "tinymcp", "asset": "tinymcp", "manifest": "Cargo.toml",
                "extra_files": [], "workflow_id": 339480400,
                "module_ci_sha": "62c8ae0468f3882b75947d5cba9687e609ce1fed",
            },
        )

    def test_tinyjuice_asset_stem_matches_the_tagged_build_and_release_assembly(self):
        fixture = json.loads(
            (Path(__file__).parent / "fixtures" / "tinyjuice-v0.10.6-release-assets.json").read_text()
        )
        profile = VERIFY.MODULE_PROFILES["tinyhumansai/tinyjuice"]
        self.assertEqual(profile["package"], fixture["crate"])
        self.assertEqual(profile["asset"], fixture["crate"])

        shell_archive = fixture["shell_archive_template"]
        for key in ("crate", "version", "host"):
            shell_archive = shell_archive.replace("${" + key + "}", fixture[key])
        powershell_archive = fixture["powershell_archive_template"]
        for key, fixture_key in (("${Crate}", "crate"), ("$Version", "version"), ("$HostKey", "windows_host")):
            powershell_archive = powershell_archive.replace(key, fixture[fixture_key])
        self.assertEqual(shell_archive, fixture["native_archive"])
        self.assertEqual(powershell_archive, fixture["windows_archive"])

        native_archive = fixture["native_archive"]
        expected_archive = (
            f"{profile['asset']}-{fixture['version']}-{fixture['host']}.tar.gz"
        )
        self.assertEqual(native_archive, expected_archive)
        workflow = (ROOT / ".github/workflows/module-reviewed-epic-release.yml").read_text()
        self.assertIn(
            'release-assets/${MODULE_ASSET}-${MODULE_VERSION}-${MODULE_HOST}.tar.gz',
            workflow,
        )
        self.assertEqual(
            fixture["windows_archive"],
            f"{profile['asset']}-{fixture['version']}-{fixture['windows_host']}.zip",
        )
        self.assertEqual(
            VERIFY.MODULE_PROFILES["tinyhumansai/tinychannels"],
            {
                "package": "tinychannels-module", "asset": "tinychannels-module", "manifest": "Cargo.toml",
                "extra_files": [], "workflow_id": 307289287,
                "module_ci_sha": "3e87ade76b622844985d0c665a3b075313e4545c",
            },
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
                        profile = VERIFY.MODULE_PROFILES[repository]
                        self.assertEqual(outputs["module-asset"], profile["asset"])
                        self.assertEqual(outputs["module-manifest"], profile["manifest"])
                        self.assertEqual(
                            outputs["module-apt-packages"], profile.get("apt_packages", ""),
                        )
                        self.assertEqual(
                            outputs["module-source-bundle"], profile.get("source_bundle", ""),
                        )

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

    def test_tinymcp_profile_accepts_only_its_canonical_package_and_ci_evidence(self):
        repository = "tinyhumansai/tinymcp"
        package = "tinymcp"
        fake = FIXTURES.module_release_fixture(VERIFY, repository, package)
        self.assertEqual(
            VERIFY.verify_reviewed_release(
                fake.api, lambda *_: fake.git, repository, "v0.1.7", "0.1.7", package, 75,
            ),
            fake.tag_sha,
        )

        for bad_repository, bad_package in (
            ("tinyhumansai/tinymcp-untrusted", package),
            (repository, "tinymcp-module"),
        ):
            with self.subTest(repository=bad_repository, package=bad_package):
                with self.assertRaises(VERIFY.VerificationError):
                    VERIFY.verify_reviewed_release(
                        fake.api, lambda *_: fake.git, bad_repository, "v0.1.7", "0.1.7",
                        bad_package, 75,
                    )

        run = fake.api.workflow_runs[fake.heads[75]][0]
        run["referenced_workflows"][0]["sha"] = "4adc1080fb495098e7af1aade82ed7e6e3c69bb7"
        run["referenced_workflows"][0]["path"] = (
            "tinyhumansai/.github/.github/workflows/module-ci.yml@"
            "4adc1080fb495098e7af1aade82ed7e6e3c69bb7"
        )
        with self.assertRaisesRegex(VERIFY.VerificationError, "workflow pin was not trusted"):
            VERIFY.verify_reviewed_release(
                fake.api, lambda *_: fake.git, repository, "v0.1.7", "0.1.7", package, 75,
            )

    def test_tinychannels_profile_accepts_only_its_canonical_package_and_ci_evidence(self):
        repository = "tinyhumansai/tinychannels"
        package = "tinychannels-module"
        fake = FIXTURES.module_release_fixture(VERIFY, repository, package)
        self.assertEqual(
            VERIFY.verify_reviewed_release(
                fake.api, lambda *_: fake.git, repository, "v0.1.7", "0.1.7", package, 75,
            ),
            fake.tag_sha,
        )
        for bad_repository, bad_package in (
            ("tinyhumansai/tinychannels-untrusted", package),
            (repository, "tinychannels"),
        ):
            with self.subTest(repository=bad_repository, package=bad_package):
                with self.assertRaises(VERIFY.VerificationError):
                    VERIFY.verify_reviewed_release(
                        fake.api, lambda *_: fake.git, bad_repository, "v0.1.7", "0.1.7",
                        bad_package, 75,
                    )
        run = fake.api.workflow_runs[fake.heads[75]][0]
        run["workflow_id"] = 339480400
        with self.assertRaisesRegex(VERIFY.VerificationError, "workflow"):
            VERIFY.verify_reviewed_release(
                fake.api, lambda *_: fake.git, repository, "v0.1.7", "0.1.7", package, 75,
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
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", pin, "HEAD"], cwd=ROOT,
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(ancestor.returncode, 0, "action pin must be a reviewed source ancestor")
        pinned_verifier = subprocess.run(
            ["git", "show", f"{pin}:.github/actions/module-reviewed-epic-preflight/verify.py"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(pinned_verifier.returncode, 0, "pinned action must contain its verifier")
        self.assertIn('"tinyhumansai/tinymcp"', pinned_verifier.stdout)
        self.assertIn('"tinyhumansai/tinychannels"', pinned_verifier.stdout)
        self.assertIn('"tinyhumansai/tinydocs"', pinned_verifier.stdout)
        self.assertIn('"tinyhumansai/tinyvoice"', pinned_verifier.stdout)


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
        source_jobs = ("validate", "native", "distro", "source_assets", "assemble")
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
        self.assertNotIn("module-manifest", self.workflow["on"]["workflow_call"]["inputs"])
        self.assertNotIn("source-artifact", self.workflow["on"]["workflow_call"]["inputs"])
        self.assertIn("expected=17", workflow)
        self.assertIn("module-source-bundle", workflow)
        self.assertIn("needs.source_assets.result == 'success'", workflow)
        self.assertIn('-name "${MODULE_ASSET}-${MODULE_VERSION}-*.tar.gz"', workflow)
        self.assertIn('-name "${MODULE_ASSET}-${MODULE_VERSION}-*.zip"', workflow)

    def test_tinydocs_sources_are_built_after_admission_and_merged_into_release_assets(self):
        jobs = self.workflow["jobs"]
        self.assertIn("source_assets", jobs)
        job = jobs["source_assets"]
        self.assertIn("preflight", job["needs"])
        self.assertIn("validate", job["needs"])
        self.assertEqual(
            job["if"],
            "needs.preflight.outputs.module-source-bundle == 'tinydocs'",
        )
        checkouts = [step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@")]
        self.assertEqual(len(checkouts), 1)
        self.assertEqual(checkouts[0]["with"]["ref"], "${{ needs.preflight.outputs.source-sha }}")
        self.assertEqual(checkouts[0]["with"].get("persist-credentials"), "false")
        self.assertIn("cargo package --locked --package tinydocs-bus", str(job))
        self.assertIn("git -C vendor/tinybus archive", str(job))
        self.assertNotIn("GH_TOKEN", str(job))

        assemble = jobs["assemble"]
        self.assertIn("source_assets", assemble["needs"])
        self.assertIn("module-*", str(assemble))
        self.assertIn("tinydocs-source-assets", str(assemble))
        self.assertIn("Merge the exact reviewed TinyDocs source bundle", str(assemble))
        self.assertIn("checksum", str(assemble))
        steps = assemble["steps"]
        checksum_index = next(i for i, step in enumerate(steps) if "checksum" in step.get("name", "").lower())
        source_download_index = next(i for i, step in enumerate(steps) if step.get("with", {}).get("name") == "tinydocs-source-assets")
        source_merge_index = next(i for i, step in enumerate(steps) if step.get("name") == "Merge the exact reviewed TinyDocs source bundle")
        upload_index = next(i for i, step in enumerate(steps) if step.get("uses", "").startswith("actions/upload-artifact@"))
        self.assertLess(source_download_index, source_merge_index)
        self.assertLess(source_merge_index, checksum_index)
        self.assertLess(source_merge_index, upload_index)
        self.assertEqual(steps[upload_index]["with"]["path"], "release-assets/*")

    def test_reviewed_tinydocs_asset_merge_rejects_untrusted_or_incomplete_bundles(self):
        assemble = self.workflow["jobs"]["assemble"]
        step = next(step for step in assemble["steps"] if step.get("name") == "Merge the exact reviewed TinyDocs source bundle")
        match = re.search(r"(?s)python3 - .*? <<'PYTHON'\n(.*?)\nPYTHON\s*$", step["run"])
        self.assertIsNotNone(match, "TinyDocs source merger must remain inline in the trusted shared workflow")
        namespace = {"__name__": "reviewed_source_merge_test"}
        exec(compile(match.group(1), "reviewed-source-merge", "exec"), namespace)
        merge = namespace["merge"]
        with tempfile.TemporaryDirectory() as root:
            source, destination = Path(root) / "source", Path(root) / "release"
            source.mkdir(); destination.mkdir()
            crate = source / "tinydocs-bus-0.2.4.crate"
            bus = source / "tinybus-source-0123456789ab.tar.gz"
            crate.write_bytes(b"crate")
            bus.write_bytes(b"bus source")
            merge("tinydocs", "0.2.4", source, destination)
            self.assertEqual(
                sorted(path.name for path in destination.iterdir()),
                ["tinybus-source-0123456789ab.tar.gz", "tinydocs-bus-0.2.4.crate"],
            )
            self.assertEqual((destination / crate.name).read_bytes(), b"crate")
            self.assertEqual((destination / bus.name).read_bytes(), b"bus source")

        with tempfile.TemporaryDirectory() as root:
            source, destination = Path(root) / "source", Path(root) / "release"
            source.mkdir(); destination.mkdir()
            (source / "tinydocs-bus-0.2.4.crate").write_bytes(b"crate")
            (source / "tinybus-source-0123456789ab.tar.gz").write_bytes(b"bus source")
            with self.assertRaisesRegex(ValueError, "unsupported reviewed source bundle"):
                merge("caller-selected", "0.2.4", source, destination)
            (source / "caller-extra.zip").write_bytes(b"extra")
            with self.assertRaisesRegex(ValueError, "exact source asset set"):
                merge("tinydocs", "0.2.4", source, destination)
            self.assertEqual(list(destination.iterdir()), [])

        with tempfile.TemporaryDirectory() as root:
            source, destination = Path(root) / "source", Path(root) / "release"
            source.mkdir(); destination.mkdir()
            crate = source / "tinydocs-bus-0.2.4.crate"
            bus = source / "tinybus-source-0123456789ab.tar.gz"
            crate.write_bytes(b"crate")
            bus.symlink_to(crate)
            with self.assertRaisesRegex(ValueError, "exact source asset set"):
                merge("tinydocs", "0.2.4", source, destination)
            bus.unlink()
            bus.write_bytes(b"bus source")
            with self.assertRaisesRegex(ValueError, "version"):
                merge("tinydocs", "../0.2.4", source, destination)
            (destination / crate.name).write_bytes(b"verified")
            with self.assertRaisesRegex(ValueError, "collides"):
                merge("tinydocs", "0.2.4", source, destination)
            self.assertEqual((destination / crate.name).read_bytes(), b"verified")
            self.assertEqual(len(list(destination.iterdir())), 1)

    def test_tinydocs_source_job_packages_only_after_verified_source_checkout(self):
        job = self.workflow["jobs"]["source_assets"]
        script = str(job)
        self.assertIn("cargo package --locked --package tinydocs-bus", script)
        self.assertNotIn("--no-verify", script)
        self.assertIn("git -C vendor/tinybus archive", script)
        self.assertIn("git -C vendor/tinybus rev-parse --verify HEAD", script)
        self.assertIn("tinydocs-bus-${MODULE_VERSION}.crate", script)
        self.assertEqual(
            next(step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact@"))["with"]["name"],
            "tinydocs-source-assets",
        )

    def test_checksum_manifest_covers_17_module_archives_and_both_tinydocs_sources(self):
        assemble = self.workflow["jobs"]["assemble"]
        step = next(step for step in assemble["steps"] if "Checksum the exact module and source asset set" in step.get("name", ""))
        with tempfile.TemporaryDirectory() as root:
            release = Path(root) / "release-assets"
            release.mkdir()
            hosts = [item["host"] for job_name in ("native", "distro")
                     for item in self.workflow["jobs"][job_name]["strategy"]["matrix"]["include"]]
            for host in hosts:
                extension = "zip" if host.startswith("windows-") else "tar.gz"
                archive = release / f"tinydocs-module-0.2.4-{host}.{extension}"
                if extension == "zip":
                    with zipfile.ZipFile(archive, "w") as bundle:
                        bundle.writestr("tinyjuice_module.dll", b"module library")
                else:
                    with tarfile.open(archive, "w:gz") as bundle:
                        library = b"module library"
                        entry = tarfile.TarInfo("libtinyjuice_module.so")
                        entry.size = len(library)
                        bundle.addfile(entry, io.BytesIO(library))
            source_archive = release / "tinybus-source-0123456789ab.tar.gz"
            with tarfile.open(source_archive, "w:gz") as bundle:
                source = b"[package]\\nname = \\\"tinybus\\\"\\n"
                entry = tarfile.TarInfo("tinybus/Cargo.toml")
                entry.size = len(source)
                bundle.addfile(entry, io.BytesIO(source))
            (release / "tinydocs-bus-0.2.4.crate").write_bytes(b"bus crate")
            fake_bin = Path(root) / "bin"
            fake_bin.mkdir()
            capture = Path(root) / "cargo-args"
            cargo = fake_bin / "cargo"
            cargo.write_text(f'''#!{sys.executable}
import hashlib
from pathlib import Path
import sys

args = sys.argv[1:]
paths = [args[index + 1] for index, value in enumerate(args[:-1]) if value == "--path"]
output = Path(args[args.index("--output") + 1])
Path({str(capture)!r}).write_text("\\n".join(args))
import tarfile
import zipfile
for path in paths:
    asset = Path(path)
    if asset.name.endswith(".tar.gz"):
        with tarfile.open(asset, "r:gz") as archive:
            members = archive.getnames()
    elif asset.name.endswith(".zip"):
        with zipfile.ZipFile(asset) as archive:
            members = archive.namelist()
    else:
        members = []
    if asset.name.endswith((".tar.gz", ".zip")) and not any(name.endswith((".so", ".dylib", ".dll")) for name in members):
        print(f"{{asset.name}}: release archive contains no platform module", file=sys.stderr)
        raise SystemExit(1)
lines = ["[sha256]"]
for path in paths:
    asset = Path(path)
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    lines.append(f'"{{asset.name}}" = "{{digest}}"')
output.write_text("\\n".join(lines) + "\\n")
''')
            cargo.chmod(0o755)
            environment = dict(os.environ, MODULE_ASSET="tinydocs-module", MODULE_VERSION="0.2.4",
                               MODULE_SOURCE_BUNDLE="tinydocs",
                               PATH=f"{fake_bin}:{os.environ['PATH']}", CAPTURE_CARGO_ARGS=str(capture))
            result = subprocess.run(["bash", "-c", step["run"]], cwd=root, env=environment,
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            args = capture.read_text().splitlines()
            self.assertEqual(args.count("--path"), 17)
            self.assertNotIn("release-assets/tinydocs-bus-0.2.4.crate", args)
            self.assertNotIn("release-assets/tinybus-source-0123456789ab.tar.gz", args)
            manifest = (release / "checksum.toml").read_text()
            self.assertIn(
                f'"tinydocs-bus-0.2.4.crate" = "{hashlib.sha256(b"bus crate").hexdigest()}"',
                manifest,
            )
            self.assertIn(
                f'"tinybus-source-0123456789ab.tar.gz" = "{hashlib.sha256(b"pinned source").hexdigest()}"',
                manifest,
            )
            self.assertEqual(manifest.count(" = "), 19)

            module_archive = next(release.glob("tinydocs-module-*.tar.gz"))
            module_archive.unlink()
            result = subprocess.run(["bash", "-c", step["run"]], cwd=root, env=environment,
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("expected 17 module archives in checksum input, found 16", result.stderr)

    def test_tinyvoice_profile_uses_exact_nested_manifest_and_all_native_dependencies(self):
        validate = self.workflow["jobs"]["validate"]
        native = self.workflow["jobs"]["native"]
        distro = self.workflow["jobs"]["distro"]
        self.assertIn("crates/tinyvoice-module/Cargo.toml", str(validate))
        self.assertIn("MODULE_APT_PACKAGES", str(native))
        self.assertEqual(
            VERIFY.MODULE_PROFILES["tinyhumansai/tinyvoice"]["apt_packages"],
            "libasound2-dev libx11-dev libxtst-dev libxi-dev",
        )
        self.assertIn("scripts/test-distro.sh", str(distro))
        apt_steps = [step for step in native["steps"] if "apt-get install" in step.get("run", "")]
        self.assertEqual(len(apt_steps), 1)
        self.assertEqual(apt_steps[0]["if"], "runner.os == 'Linux' && needs.preflight.outputs.module-apt-packages != ''")
        self.assertIn("MODULE_APT_PACKAGES", apt_steps[0]["env"])
        self.assertIn("module package and manifest are outside the compiled-in profile", str(validate))
        self.assertIn("tinyvoice-module:crates/tinyvoice-module/Cargo.toml", str(validate))
        self.assertIn("Ubuntu build dependencies are outside the compiled-in profile", str(validate))
        self.assertEqual(len(distro["strategy"]["matrix"]["include"]), 6)
        self.assertIn("MODULE_APT_PACKAGES", str(native))


if __name__ == "__main__":
    unittest.main()
