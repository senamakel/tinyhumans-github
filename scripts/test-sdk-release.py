"""Pin the privilege boundary and retry behavior of the SDK release workflow."""
from pathlib import Path
import importlib.util
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
            {"contents": "read", "pull-requests": "read", "checks": "read"},
        )
        package = "\n".join(str(step) for step in jobs["package"]["steps"])
        self.assertIn("needs.preflight.outputs.source-sha", package)
        self.assertIn("git rev-parse HEAD", package)
        self.assertIn("cargo test --locked --workspace --all-features", package)
        self.assertNotIn("GH_TOKEN", package)
        self.assertEqual(
            jobs["publish"]["permissions"],
            {"contents": "write", "pull-requests": "read", "checks": "read"},
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
            '          actual_sha="$(git rev-parse HEAD)"\n'
            '          [[ "$actual_sha" == "$SOURCE_SHA" ]]\n',
            "",
        )
        legacy_run = legacy_package["run"].replace(
            "          git fetch origin main\n"
            "          git merge-base --is-ancestor HEAD origin/main\n",
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
            73,
        )
        self.assertEqual(source, fake.tag_sha)
        self.assertEqual(fake.checked_heads, [fake.heads[73], fake.heads[74], fake.heads[72]])

        fake = reviewed_release_fixture(self.verify)
        fake.parents[fake.tag_sha] = (fake.merges[74], "e" * 40)
        with self.assertRaisesRegex(self.verify.VerificationError, "head commit"):
            self.verify.verify_reviewed_release(
                fake.api, lambda *_: fake.git, "tinyhumansai/tinybus", "v0.1.7",
                "0.1.7", "tinybus", 73,
            )

        fake = reviewed_release_fixture(self.verify)
        fake.associations[fake.merges[74]] = []
        with self.assertRaisesRegex(self.verify.VerificationError, "merged pull request"):
            self.verify.verify_reviewed_release(
                fake.api, lambda *_: fake.git, "tinyhumansai/tinybus", "v0.1.7",
                "0.1.7", "tinybus", 73,
            )

        fake = reviewed_release_fixture(self.verify)
        fake.parents[fake.merges[72]] = (fake.base,)
        with self.assertRaisesRegex(self.verify.VerificationError, "two parents"):
            self.verify.verify_reviewed_release(
                fake.api, lambda *_: fake.git, "tinyhumansai/tinybus", "v0.1.7",
                "0.1.7", "tinybus", 73,
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
        with self.assertRaisesRegex(self.verify.VerificationError, "changes requested"):
            self.verify.verify_reviewed_release(
                fake.api, lambda *_: fake.git, "tinyhumansai/tinybus", "v0.1.7",
                "0.1.7", "tinybus", 73,
            )

        fake = reviewed_release_fixture(self.verify)
        fake.threads[73] = [{"isResolved": False, "isOutdated": True}]
        with self.assertRaisesRegex(self.verify.VerificationError, "unresolved review thread"):
            self.verify.verify_reviewed_release(
                fake.api, lambda *_: fake.git, "tinyhumansai/tinybus", "v0.1.7",
                "0.1.7", "tinybus", 73,
            )

    def test_required_check_names_provenance_and_success_are_all_mandatory(self):
        fake = reviewed_release_fixture(self.verify)
        fake.checks[fake.heads[72]][0]["app"] = {"id": 42}
        with self.assertRaisesRegex(self.verify.VerificationError, "trusted CI check"):
            self.verify.verify_reviewed_release(
                fake.api, lambda *_: fake.git, "tinyhumansai/tinybus", "v0.1.7",
                "0.1.7", "tinybus", 73,
            )

        fake = reviewed_release_fixture(self.verify)
        fake.checks[fake.heads[74]].pop()
        with self.assertRaisesRegex(self.verify.VerificationError, "trusted CI check"):
            self.verify.verify_reviewed_release(
                fake.api, lambda *_: fake.git, "tinyhumansai/tinybus", "v0.1.7",
                "0.1.7", "tinybus", 73,
            )

    def test_tag_binding_detects_movement_before_checkout_or_publish(self):
        fake = reviewed_release_fixture(self.verify)
        self.verify.verify_tag_binding(fake.api, "v0.1.7", fake.tag_sha)
        fake.api.tags["v0.1.7"] = "f" * 40
        with self.assertRaisesRegex(self.verify.VerificationError, "tag no longer resolves"):
            self.verify.verify_tag_binding(fake.api, "v0.1.7", fake.tag_sha)


def reviewed_release_fixture(verifier):
    class Api:
        def __init__(self):
            self.tags = {"v0.1.7": sha(4)}
            self.main = sha(1)
            self.pulls = {}
            self.associations = {}
            self.reviews = {}
            self.threads = {}
            self.checks = {}

        def tag_commit(self, tag):
            return self.tags[tag]

        def main_sha(self):
            return self.main

        def pull_request(self, number):
            return self.pulls[number]

        def pull_requests_for_commit(self, commit):
            return [{"number": number} for number in self.associations.get(commit, [])]

        def reviews_for_pull(self, number):
            return self.reviews[number]

        def review_threads_for_pull(self, number):
            return self.threads[number]

        def check_runs_for_commit(self, commit):
            return self.checks[commit]

    class Git:
        def __init__(self, parents):
            self.parents = parents
            self.tag_sha = sha(4)
            self.main_sha = sha(1)

        def parents_of(self, commit):
            return self.parents[commit]

        def is_ancestor_of(self, commit, head):
            return commit == head

    base = sha(1)
    merges = {72: sha(2), 74: sha(3), 73: sha(4)}
    heads = {72: sha(12), 74: sha(13), 73: sha(14)}
    parents = {
        merges[72]: (base, heads[72]),
        merges[74]: (merges[72], heads[74]),
        merges[73]: (merges[74], heads[73]),
    }
    api = Api()
    api.associations = {merge: [number] for number, merge in merges.items()}
    for number, merge in merges.items():
        api.pulls[number] = {
            "number": number,
            "merged": True,
            "merge_commit_sha": merge,
            "base": {
                "ref": "epic/8056-modules-wiring",
                "repo": {"full_name": "tinyhumansai/tinybus"},
            },
            "head": {"sha": heads[number]},
            "user": {"login": "author"},
        }
        api.reviews[number] = [
            {
                "user": {"login": "reviewer"},
                "state": "COMMENTED",
                "commit_id": heads[number],
                "submitted_at": "2026-10-17T12:00:00Z",
                "id": number,
            }
        ]
        api.threads[number] = [{"isResolved": True, "isOutdated": False}]
        api.checks[heads[number]] = [
            {
                "name": name,
                "app": {"id": 15368},
                "status": "completed",
                "conclusion": "success",
                "started_at": "2026-10-17T12:00:00Z",
                "id": index,
            }
            for index, name in enumerate(verifier.REQUIRED_CHECKS)
        ]
    api.reviews[74] = [
        {
            "user": {"login": "tinysweeper[bot]"},
            "state": "CHANGES_REQUESTED",
            "commit_id": sha(30),
            "submitted_at": "2026-10-17T10:00:00Z",
            "id": 740,
        },
        {
            "user": {"login": "tinysweeper[bot]"},
            "state": "APPROVED",
            "commit_id": heads[74],
            "submitted_at": "2026-10-17T11:00:00Z",
            "id": 741,
        },
        *api.reviews[74],
    ]
    api.checked_heads = []
    original_checks = api.check_runs_for_commit

    def record_checks(commit):
        api.checked_heads.append(commit)
        return original_checks(commit)

    api.check_runs_for_commit = record_checks
    fake = type("ReviewedReleaseFixture", (), {})()
    fake.api = api
    fake.git = Git(parents)
    fake.base = base
    fake.merges = merges
    fake.heads = heads
    fake.tag_sha = merges[73]
    fake.parents = parents
    fake.associations = api.associations
    fake.reviews = api.reviews
    fake.threads = api.threads
    fake.checks = api.checks
    fake.checked_heads = api.checked_heads
    return fake


def sha(value):
    return f"{value:040x}"


if __name__ == "__main__":
    unittest.main()
