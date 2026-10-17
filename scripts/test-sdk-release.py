"""Pin the privilege boundary and retry behavior of the SDK release workflow."""
from pathlib import Path
import importlib.util
import subprocess
import tempfile
import unittest

import yaml


class SdkReleaseWorkflowTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).parents[1] / ".github/workflows/sdk-release.yml"
        self.workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)

    def test_cargo_runs_without_release_write_permission(self):
        jobs = self.workflow["jobs"]
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        self.assertNotIn("permissions", jobs["package"])
        self.assertEqual(jobs["publish"]["permissions"], {"contents": "write"})
        package_steps = "\n".join(str(step) for step in jobs["package"]["steps"])
        publish_steps = "\n".join(str(step) for step in jobs["publish"]["steps"])
        self.assertIn("cargo test", package_steps)
        self.assertNotIn("GH_TOKEN", package_steps)
        self.assertNotIn("cargo ", publish_steps)
        self.assertIn("actions/upload-artifact", package_steps)
        self.assertIn("actions/download-artifact", publish_steps)

    def test_existing_release_assets_are_verified_before_retry(self):
        publish_steps = str(self.workflow["jobs"]["publish"]["steps"])
        self.assertIn("gh release view", publish_steps)
        self.assertIn("gh release download", publish_steps)
        self.assertIn("different asset set", publish_steps)
        self.assertIn("different contents", publish_steps)
        self.assertIn("gh release edit", publish_steps)
        self.assertIn("gh release create", publish_steps)


class ModuleAssetWorkflowTests(unittest.TestCase):
    def test_public_asset_name_flows_to_verification_and_uploads(self):
        path = Path(__file__).parents[1] / ".github/workflows/module-release.yml"
        text = path.read_text()
        workflow = yaml.load(text, Loader=yaml.BaseLoader)
        self.assertEqual(workflow["on"]["workflow_call"]["inputs"]["asset-name"]["default"], "")
        self.assertIn('[[ "$MODULE_ASSET" =~ ^[A-Za-z0-9_-]+$ ]]', text)
        for job in ("native", "distro"):
            uploads = [step for step in workflow["jobs"][job]["steps"]
                       if step.get("uses", "").startswith("actions/upload-artifact@")]
            self.assertTrue(uploads)
            for step in uploads:
                self.assertIn("inputs.asset-name || inputs.module-crate", step["with"]["path"])
        native = workflow["jobs"]["native"]["steps"]
        for step in native:
            if step.get("name", "").startswith("Verify"):
                self.assertIn("MODULE_ASSET", step["run"])

    def test_registry_jobs_install_native_dependencies_before_publish(self):
        path = Path(__file__).parents[1] / ".github/workflows/module-release.yml"
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        for job in ("crates_io_check", "crates_io"):
            steps = workflow["jobs"][job]["steps"]
            installs = [i for i,s in enumerate(steps) if "sudo apt-get install" in s.get("run", "")]
            publishes = [i for i,s in enumerate(steps) if "cargo publish" in s.get("run", "")]
            self.assertEqual(len(installs), 1)
            self.assertEqual(len(publishes), 1)
            self.assertLess(installs[0], publishes[0])

    def test_build_metadata_hyphens_do_not_mark_prereleases(self):
        import os
        import re
        import subprocess
        for file,var,flags in [("sdk-release.yml","VERSION","release_type"),("module-release.yml","MODULE_VERSION","release_type")]:
            path = Path(__file__).parents[1] / ".github/workflows" / file
            line = re.search(r"^ +if .*--prerelease.*fi$", path.read_text(), re.M).group().strip()
            for version,expected in [("1.2.3",0),("1.2.3+linux-x86",0),("1.2.3-beta+linux-x86",1)]:
                script = flags+"=(); "+line+"; printf '%s' "+chr(34)+"$"+"{#"+flags+"[@]}"+chr(34)
                result = subprocess.run(["bash","-c",script], env=dict(os.environ,**{var:version}),capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stdout,str(expected))


class ReviewedEpicSdkReleaseTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).parents[1]
        self.workflow = yaml.load(
            (root / ".github/workflows/sdk-reviewed-epic-release.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        self.legacy = yaml.load(
            (root / ".github/workflows/sdk-release.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        action_path = root / ".github/actions/sdk-reviewed-epic-preflight/verify.py"
        spec = importlib.util.spec_from_file_location("sdk_reviewed_epic_verify", action_path)
        if spec is None or spec.loader is None:
            raise AssertionError("reviewed SDK verifier is missing")
        self.verify = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.verify)

    def test_new_entrypoint_is_exact_tinybus_epic_and_has_narrow_token_jobs(self):
        inputs = self.workflow["on"]["workflow_call"]["inputs"]
        self.assertEqual(set(inputs), {"tag", "version", "package", "reviewed-pr"})
        jobs = self.workflow["jobs"]
        self.assertEqual(set(jobs), {"preflight", "package", "publish"})
        self.assertEqual(
            jobs["preflight"]["permissions"],
            {"contents": "read", "pull-requests": "read", "checks": "read", "actions": "read"},
        )
        package = "\n".join(str(step) for step in jobs["package"]["steps"])
        self.assertIn("needs.preflight.outputs.source-sha", package)
        self.assertIn("git rev-parse HEAD", package)
        self.assertIn("cargo test --locked --workspace --all-features", package)
        self.assertNotIn("GH_TOKEN", package)
        self.assertEqual(
            jobs["publish"]["permissions"],
            {"contents": "write"},
        )
        preflight_steps = jobs["preflight"]["steps"]
        self.assertTrue(all("actions/checkout" not in step.get("uses", "") for step in preflight_steps))
        package_checkout = next(
            step for step in jobs["package"]["steps"]
            if step.get("uses", "").startswith("actions/checkout@")
        )
        self.assertEqual(package_checkout["with"]["ref"], "${{ needs.preflight.outputs.source-sha }}")
        tag_recheck = next(
            step for step in jobs["publish"]["steps"]
            if step.get("name") == "Recheck the release tag against the verified source SHA"
        )
        self.assertEqual(tag_recheck["with"]["mode"], "tag-only")
        self.assertEqual(tag_recheck["with"]["expected-sha"], "${{ needs.preflight.outputs.source-sha }}")
        action_uses = [
            step.get("uses", "")
            for job in jobs.values()
            for step in job.get("steps", [])
            if "sdk-reviewed-epic-preflight@" in step.get("uses", "")
        ]
        self.assertGreaterEqual(len(action_uses), 2)
        for uses in action_uses:
            self.assertRegex(uses, r"^tinyhumansai/\.github/.github/actions/sdk-reviewed-epic-preflight@[0-9a-f]{40}$")
        action_sha = action_uses[0].rsplit("@", 1)[1]
        self.assertEqual(set(action_uses), {
            f"tinyhumansai/.github/.github/actions/sdk-reviewed-epic-preflight@{action_sha}"
        })
        root = Path(__file__).parents[1]
        action_tree = ".github/actions/sdk-reviewed-epic-preflight"
        action = yaml.load((root / action_tree / "action.yml").read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(action["runs"]["using"], "composite")
        self.assertTrue(action["runs"]["steps"][0]["run"].endswith("$GITHUB_ACTION_PATH/verify.py\""))
        self.assertEqual(action["inputs"]["token"]["required"], "true")
        pinned = subprocess.run(
            ["git", "rev-parse", f"{action_sha}:{action_tree}"],
            cwd=root,
            capture_output=True,
            check=False,
            text=True,
        )
        checked_in = subprocess.run(
            ["git", "rev-parse", f"HEAD:{action_tree}"],
            cwd=root,
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(pinned.returncode, 0, "pinned action tree is missing")
        self.assertEqual(checked_in.returncode, 0, "checked-in action tree is missing")
        self.assertEqual(pinned.stdout.strip(), checked_in.stdout.strip())

    def test_action_checks_match_all_required_main_ruleset_contexts(self):
        root = Path(__file__).parents[1]
        path = root / "scripts/check-module-drift.py"
        spec = importlib.util.spec_from_file_location("sdk_release_module_drift", path)
        drift = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(drift)
        self.assertEqual(len(self.verify.REQUIRED_CHECKS), 13)
        self.assertEqual(self.verify.REQUIRED_CHECKS, drift.CHECKS)
        self.assertEqual(self.verify.CHECK_APP_ID, 15368)

    def test_legacy_entrypoint_permissions_and_package_publish_logic_are_unchanged(self):
        self.assertEqual(
            set(self.legacy["on"]["workflow_call"]["inputs"]),
            {"tag", "version", "package"},
        )
        self.assertEqual(self.legacy["jobs"]["package"].get("permissions"), None)
        legacy_package = next(
            step for step in self.legacy["jobs"]["package"]["steps"]
            if step.get("name") == "Validate and package reviewed SDK source"
        )
        reviewed_package = next(
            step for step in self.workflow["jobs"]["package"]["steps"]
            if step.get("name") == "Validate and package reviewed SDK source"
        )
        reviewed_run = reviewed_package["run"].replace(
            'actual_sha="$(git rev-parse HEAD)"\n'
            '[[ "$actual_sha" == "$SOURCE_SHA" ]]\n',
            "",
        )
        legacy_run = legacy_package["run"].replace(
            "git fetch origin main\n"
            "git merge-base --is-ancestor HEAD origin/main\n",
            "",
        )
        self.assertEqual(reviewed_run, legacy_run)
        legacy_upload = next(
            step for step in self.legacy["jobs"]["package"]["steps"]
            if step.get("uses", "").startswith("actions/upload-artifact@")
        )
        reviewed_upload = next(
            step for step in self.workflow["jobs"]["package"]["steps"]
            if step.get("uses", "").startswith("actions/upload-artifact@")
        )
        self.assertEqual(reviewed_upload, legacy_upload)
        legacy_publish = next(
            step for step in self.legacy["jobs"]["publish"]["steps"]
            if step.get("name") == "Verify and publish immutable SDK release"
        )
        reviewed_publish = next(
            step for step in self.workflow["jobs"]["publish"]["steps"]
            if step.get("name") == "Verify and publish immutable SDK release"
        )
        self.assertEqual(reviewed_publish["run"], legacy_publish["run"])

    def test_reviewed_release_verifies_every_epic_merge_and_rejects_bad_history(self):
        fake = reviewed_release_fixture(self.verify)
        source = self.verify.verify_reviewed_release(
            fake.api,
            lambda *_: fake.git,
            "tinyhumansai/tinybus",
            "v0.1.7",
            "0.1.7",
            "tinybus",
            75,
        )
        self.assertEqual(source, fake.tag_sha)
        self.assertEqual(fake.checked_heads, [fake.heads[75], fake.heads[73], fake.heads[74], fake.heads[72]])

        fake = reviewed_release_fixture(self.verify)
        fake.parents[fake.tag_sha] = (fake.merges[74], "e" * 40)
        with self.assertRaisesRegex(self.verify.VerificationError, "exact merged pull request"):
            self.verify.verify_reviewed_release(
                fake.api, lambda *_: fake.git, "tinyhumansai/tinybus", "v0.1.7",
                "0.1.7", "tinybus", 75,
            )

        fake = reviewed_release_fixture(self.verify)
        fake.associations[fake.merges[74]] = []
        with self.assertRaisesRegex(self.verify.VerificationError, "merged pull request"):
            self.verify.verify_reviewed_release(
                fake.api, lambda *_: fake.git, "tinyhumansai/tinybus", "v0.1.7",
                "0.1.7", "tinybus", 75,
            )

        fake = reviewed_release_fixture(self.verify)
        fake.parents[fake.merges[72]] = (fake.base,)
        with self.assertRaisesRegex(self.verify.VerificationError, "two-parent"):
            self.verify.verify_reviewed_release(
                fake.api, lambda *_: fake.git, "tinyhumansai/tinybus", "v0.1.7",
                "0.1.7", "tinybus", 75,
            )

    def test_review_state_is_effective_across_heads_and_threads_fail_closed(self):
        fake = reviewed_release_fixture(self.verify)
        fake.reviews[74] = [review for review in fake.reviews[74] if review["state"] != "APPROVED"]
        fake.reviews[74].append({
            "user": {"login": "tinysweeper[bot]"},
            "state": "COMMENTED",
            "commit_id": "f" * 40,
            "submitted_at": "2026-10-17T12:00:00Z",
            "id": 999,
        })
        with self.assertRaisesRegex(self.verify.VerificationError, "changes-requested"):
            self.verify.verify_reviewed_release(
                fake.api, lambda *_: fake.git, "tinyhumansai/tinybus", "v0.1.7",
                "0.1.7", "tinybus", 75,
            )

        fake = reviewed_release_fixture(self.verify)
        fake.threads[75] = [{"isResolved": False, "isOutdated": True}]
        with self.assertRaisesRegex(self.verify.VerificationError, "unresolved review thread"):
            self.verify.verify_reviewed_release(
                fake.api, lambda *_: fake.git, "tinyhumansai/tinybus", "v0.1.7",
                "0.1.7", "tinybus", 75,
            )

    def test_required_check_names_provenance_and_success_are_all_mandatory(self):
        fake = reviewed_release_fixture(self.verify)
        fake.checks[fake.heads[72]][0]["app"] = {"id": 42}
        with self.assertRaisesRegex(self.verify.VerificationError, "trusted CI check"):
            self.verify.verify_reviewed_release(
                fake.api, lambda *_: fake.git, "tinyhumansai/tinybus", "v0.1.7",
                "0.1.7", "tinybus", 75,
            )

        fake = reviewed_release_fixture(self.verify)
        fake.checks[fake.heads[72]][0]["conclusion"] = "failure"
        with self.assertRaisesRegex(self.verify.VerificationError, "not successful"):
            self.verify.verify_reviewed_release(
                fake.api, lambda *_: fake.git, "tinyhumansai/tinybus", "v0.1.7",
                "0.1.7", "tinybus", 75,
            )

        fake = reviewed_release_fixture(self.verify)
        fake.checks[fake.heads[74]].pop()
        with self.assertRaisesRegex(self.verify.VerificationError, "trusted CI check"):
            self.verify.verify_reviewed_release(
                fake.api, lambda *_: fake.git, "tinyhumansai/tinybus", "v0.1.7",
                "0.1.7", "tinybus", 75,
            )

    def test_required_checks_must_share_one_canonical_pull_request_run(self):
        fake = reviewed_release_fixture(self.verify)
        fake.workflow_runs[fake.heads[72]][0]["repository"] = {
            "full_name": "someone-else/tinybus"
        }
        with self.assertRaisesRegex(self.verify.VerificationError, "workflow run|canonical CI"):
            self.verify.verify_reviewed_release(
                fake.api, lambda *_: fake.git, "tinyhumansai/tinybus", "v0.1.7",
                "0.1.7", "tinybus", 75,
            )

        for field, value in (
            ("path", ".github/workflows/attacker.yml@refs/heads/epic/8056-modules-wiring"),
            ("workflow_id", self.verify.CI_WORKFLOW_ID + 1),
            ("event", "workflow_dispatch"),
            ("head_sha", sha(99)),
            ("head_branch", "unrelated-branch"),
        ):
            fake = reviewed_release_fixture(self.verify)
            fake.workflow_runs[fake.heads[72]][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                self.verify.VerificationError, "workflow run|canonical CI"
            ):
                self.verify.verify_reviewed_release(
                    fake.api, lambda *_: fake.git, "tinyhumansai/tinybus", "v0.1.7",
                    "0.1.7", "tinybus", 75,
                )

    def test_required_checks_cannot_be_combined_across_workflow_runs(self):
        fake = reviewed_release_fixture(self.verify)
        head = fake.heads[72]
        first = fake.workflow_runs[head][0]
        second = dict(first, id=first["id"] + 100, check_suite_id=first["check_suite_id"] + 100)
        fake.workflow_runs[head].append(second)
        jobs = fake.workflow_jobs[(first["id"], first["run_attempt"])]
        split = len(jobs) // 2
        fake.workflow_jobs[(first["id"], first["run_attempt"])] = jobs[:split]
        fake.workflow_jobs[(second["id"], second["run_attempt"])] = jobs[split:]
        with self.assertRaisesRegex(self.verify.VerificationError, "trusted CI check"):
            self.verify.verify_reviewed_release(
                fake.api, lambda *_: fake.git, "tinyhumansai/tinybus", "v0.1.7",
                "0.1.7", "tinybus", 75,
            )

    def test_newer_failed_workflow_run_cannot_be_masked_by_older_green_run(self):
        fake = reviewed_release_fixture(self.verify)
        head = fake.heads[72]
        previous = fake.workflow_runs[head][0]
        latest = dict(previous, id=previous["id"] + 100, run_number=previous["run_number"] + 1,
                      check_suite_id=previous["check_suite_id"] + 100)
        fake.workflow_runs[head].append(latest)
        jobs = [dict(job, run_id=latest["id"]) for job in
                fake.workflow_jobs[(previous["id"], previous["run_attempt"])]]
        jobs[0]["conclusion"] = "failure"
        fake.workflow_jobs[(latest["id"], latest["run_attempt"])] = jobs
        with self.assertRaisesRegex(self.verify.VerificationError, "not successful"):
            self.verify.verify_reviewed_release(
                fake.api, lambda *_: fake.git, "tinyhumansai/tinybus", "v0.1.7",
                "0.1.7", "tinybus", 75,
            )

    def test_failed_latest_attempt_cannot_be_masked_by_earlier_green_attempt(self):
        fake = reviewed_release_fixture(self.verify)
        head = fake.heads[72]
        first_attempt = fake.workflow_runs[head][0]
        latest_attempt = dict(first_attempt, run_attempt=2)
        fake.workflow_runs[head].append(latest_attempt)
        jobs = [dict(job, run_attempt=2) for job in
                fake.workflow_jobs[(first_attempt["id"], first_attempt["run_attempt"])]]
        jobs[0]["conclusion"] = "failure"
        fake.workflow_jobs[(first_attempt["id"], 2)] = jobs
        with self.assertRaisesRegex(self.verify.VerificationError, "not successful"):
            self.verify.verify_reviewed_release(
                fake.api, lambda *_: fake.git, "tinyhumansai/tinybus", "v0.1.7",
                "0.1.7", "tinybus", 75,
            )

        fake = reviewed_release_fixture(self.verify)
        fake.checks[fake.heads[72]][0]["conclusion"] = "failure"
        with self.assertRaisesRegex(self.verify.VerificationError, "not successful"):
            self.verify.verify_reviewed_release(
                fake.api, lambda *_: fake.git, "tinyhumansai/tinybus", "v0.1.7",
                "0.1.7", "tinybus", 75,
            )

        fake = reviewed_release_fixture(self.verify)
        fake.checks[fake.heads[74]].pop()
        with self.assertRaisesRegex(self.verify.VerificationError, "trusted CI check"):
            self.verify.verify_reviewed_release(
                fake.api, lambda *_: fake.git, "tinyhumansai/tinybus", "v0.1.7",
                "0.1.7", "tinybus", 75,
            )

    def test_tag_binding_detects_movement_before_checkout_or_publish(self):
        fake = reviewed_release_fixture(self.verify)
        self.verify.verify_tag_binding(fake.api, "v0.1.7", fake.tag_sha)
        fake.api.tags["v0.1.7"] = "f" * 40
        with self.assertRaisesRegex(self.verify.VerificationError, "tag no longer resolves"):
            self.verify.verify_tag_binding(fake.api, "v0.1.7", fake.tag_sha)


class ReviewedReleaseApiPaginationTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).parents[1] / ".github/actions/sdk-reviewed-epic-preflight/verify.py"
        spec = importlib.util.spec_from_file_location("sdk_reviewed_epic_verify_pages", path)
        self.verify = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.verify)
        self.api = self.verify.GitHubApi("test-token", "tinyhumansai/tinybus")

    def test_rest_pagination_reads_every_page_and_enforces_shape(self):
        requested = []

        def request(path, **kwargs):
            requested.append(path)
            page = int(path.rsplit("page=", 1)[1])
            if page == 1:
                return list(range(100))
            if page == 2:
                return list(range(100, 200))
            return [200]

        self.api._request = request
        self.assertEqual(self.api.rest_pages("pulls/1/reviews"), list(range(201)))
        self.assertEqual(len(requested), 3)

        self.api._request = lambda *_args, **_kwargs: {"unexpected": []}
        with self.assertRaisesRegex(self.verify.VerificationError, "invalid page"):
            self.api.rest_pages("pulls/1/reviews")

    def test_workflow_runs_and_jobs_are_fetched_from_the_exact_head_and_attempt(self):
        requested = []

        def request(path, **kwargs):
            requested.append(path)
            if "/actions/runs?" in path:
                return {"workflow_runs": [{"id": 91}]}
            return {"jobs": [{"id": 92}]}

        self.api._request = request
        self.assertEqual(self.api.workflow_runs_for_commit(sha(7)), [{"id": 91}])
        self.assertEqual(self.api.jobs_for_workflow_run(91, 3), [{"id": 92}])
        self.assertIn(f"head_sha={sha(7)}", requested[0])
        self.assertIn("/actions/runs/91/attempts/3/jobs", requested[1])

    def test_graphql_cursor_pagination_reads_every_review_thread_page(self):
        cursors = []

        def request(path, **kwargs):
            cursor = kwargs["payload"]["variables"]["cursor"]
            cursors.append(cursor)
            if cursor is None:
                return {"data": {"repository": {"pullRequest": {
                    "reviewThreads": {
                        "nodes": [{"isResolved": True}],
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                    },
                }}}}
            return {"data": {"repository": {"pullRequest": {
                "reviewThreads": {
                    "nodes": [{"isResolved": True}, {"isResolved": False}],
                    "pageInfo": {"hasNextPage": False, "endCursor": "cursor-2"},
                },
            }}}}

        self.api._request = request
        nodes = self.api.review_threads_for_pull(12)
        self.assertEqual([node["isResolved"] for node in nodes], [True, True, False])
        self.assertEqual(cursors, [None, "cursor-1"])

    def test_graphql_pagination_rejects_missing_has_next_page(self):
        for page_info in ({}, {"hasNextPage": "false"}, {"hasNextPage": None}):
            self.api._request = lambda *_args, info=page_info, **_kwargs: {
                "data": {"repository": {"pullRequest": {
                    "reviewThreads": {"nodes": [], "pageInfo": info}
                }}}
            }
            with self.subTest(page_info=page_info), self.assertRaisesRegex(
                self.verify.VerificationError, "pageInfo|pagination"
            ):
                self.api.review_threads_for_pull(12)

    def test_main_branch_must_report_protection_enabled(self):
        for response in (
            {"protected": False, "commit": {"sha": sha(1)}},
            {"commit": {"sha": sha(1)}},
            {"protected": None, "commit": {"sha": sha(1)}},
        ):
            self.api._request = lambda *_args, payload=response, **_kwargs: payload
            with self.subTest(response=response), self.assertRaisesRegex(
                self.verify.VerificationError, "protection"
            ):
                self.api.main_sha()

    def test_bare_history_fetch_resolves_exact_tag_without_a_worktree(self):
        with tempfile.TemporaryDirectory(prefix="sdk-reviewed-git-fixture-") as temporary:
            repository = Path(temporary) / "source.git"
            repository.mkdir()

            def git(*args):
                return subprocess.run(
                    ["git", "-C", str(repository), *args],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()

            git("init", "--quiet")
            git("config", "user.name", "SDK Release Fixture")
            git("config", "user.email", "sdk-fixture@example.invalid")
            (repository / "source.txt").write_text("main\n")
            git("add", "source.txt")
            git("commit", "--quiet", "-m", "main base")
            git("branch", "-M", "main")
            main_sha = git("rev-parse", "HEAD")
            git("checkout", "--quiet", "-b", "source")
            (repository / "source.txt").write_text("epic\n")
            git("commit", "--quiet", "-am", "reviewed PR head")
            head_sha = git("rev-parse", "HEAD")
            tree = git("rev-parse", "HEAD^{tree}")
            merge_sha = git("commit-tree", tree, "-p", main_sha, "-p", head_sha, "-m", "PR merge")
            git("tag", "-a", "v0.1.7", "-m", "v0.1.7", merge_sha)

            history = self.verify.BareHistory(
                "tinyhumansai/tinybus",
                "v0.1.7",
                merge_sha,
                main_sha,
                remote_url=str(repository),
            )
            try:
                self.assertEqual(history.tag_sha, merge_sha)
                self.assertEqual(history.main_sha, main_sha)
                self.assertEqual(history.parents_of(merge_sha), (main_sha, head_sha))
                self.assertTrue(history.is_ancestor_of(main_sha, main_sha))
                self.assertFalse(history.is_ancestor_of(merge_sha, main_sha))
                self.assertEqual(
                    subprocess.run(
                        ["git", "--git-dir", str(history.git_dir), "rev-parse", "--is-bare-repository"],
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout.strip(),
                    "true",
                )
                self.assertFalse((history.git_dir / "worktrees").exists())
            finally:
                history.close()


fixture_path = Path(__file__).with_name("sdk-reviewed-release-fixtures.py")
fixture_spec = importlib.util.spec_from_file_location("sdk_reviewed_release_fixtures", fixture_path)
fixture_module = importlib.util.module_from_spec(fixture_spec)
fixture_spec.loader.exec_module(fixture_module)
reviewed_release_fixture = fixture_module.reviewed_release_fixture
sha = fixture_module.sha


if __name__ == "__main__":
    unittest.main()
