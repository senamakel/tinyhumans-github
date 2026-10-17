"""Require canonical CI runs to belong to the exact reviewed pull request."""
from pathlib import Path
import importlib.util
import io
import unittest
import zipfile


ROOT = Path(__file__).parents[1]
BASE_TEST = ROOT / "scripts/test-sdk-release.py"
spec = importlib.util.spec_from_file_location("sdk_release_tests", BASE_TEST)
base_tests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base_tests)
ACTION_DIR = ROOT / ".github/actions/sdk-reviewed-epic-preflight"
sys_path = str(ACTION_DIR)
import sys
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)
import historical_ci


class WorkflowPullAssociationTests(unittest.TestCase):
    def setUp(self):
        self.verify = base_tests.ReviewedEpicSdkReleaseTests()
        self.verify.setUp()
        self.fake = base_tests.reviewed_release_fixture(self.verify.verify)

    def run_verification(self):
        return self.verify.verify.verify_reviewed_release(
            self.fake.api,
            lambda *_: self.fake.git,
            "tinyhumansai/tinybus",
            "v0.1.7",
            "0.1.7",
            "tinybus",
            75,
        )

    def test_workflow_run_for_another_pr_on_same_head_cannot_substitute(self):
        head = self.fake.heads[72]
        actual = self.fake.workflow_runs[head][0]
        actual["conclusion"] = "failure"
        other = dict(actual, id=actual["id"] + 500, run_number=actual["run_number"] + 1)
        other["pull_requests"] = [{"number": 999}]
        other["conclusion"] = "success"
        self.fake.workflow_runs[head].append(other)
        self.fake.workflow_jobs[(other["id"], other["run_attempt"])] = [
            dict(job, run_id=other["id"])
            for job in self.fake.workflow_jobs[(actual["id"], actual["run_attempt"])]
        ]
        with self.assertRaisesRegex(self.verify.verify.VerificationError, "workflow run|successful"):
            self.run_verification()

    def test_missing_empty_or_malformed_pr_association_fails_closed(self):
        for association in (None, [], {}, [{"number": "72"}], [{"number": 999}]):
            fake = base_tests.reviewed_release_fixture(self.verify.verify)
            fake.workflow_runs[fake.heads[72]][0]["pull_requests"] = association
            self.fake = fake
            with self.subTest(association=association), self.assertRaisesRegex(
                self.verify.verify.VerificationError, "workflow run|pull request"
            ):
                self.run_verification()

    def test_run_association_must_name_exact_merged_pr(self):
        self.fake.workflow_runs[self.fake.heads[74]][0]["pull_requests"] = [{"number": 999}]
        with self.assertRaisesRegex(self.verify.verify.VerificationError, "workflow run|pull request"):
            self.run_verification()

    def test_exact_pr_number_with_wrong_base_or_head_binding_is_rejected(self):
        mutations = (
            (75, "base", {"ref": "main", "repo": {"full_name": "tinyhumansai/tinybus"}}),
            (75, "base", {"ref": "epic/8056-modules-wiring", "repo": {"full_name": "other/tinybus"}}),
            (75, "head", {"sha": "f" * 40, "ref": "feature", "repo": {"full_name": "senamakel/tinybus"}}),
            (75, "head", {"sha": base_tests.sha(15), "ref": "other-branch", "repo": {"full_name": "senamakel/tinybus"}}),
            (75, "head", {"sha": base_tests.sha(15), "ref": "feature", "repo": {"full_name": "other/tinybus"}}),
        )
        for number, field, value in mutations:
            fake = base_tests.reviewed_release_fixture(self.verify.verify)
            fake.api.pulls[number][field] = value
            self.fake = fake
            with self.subTest(field=field, value=value), self.assertRaises(
                self.verify.verify.VerificationError
            ):
                self.run_verification()

    def test_empty_run_association_requires_pinned_fmt_checkout_and_matching_merge_parents(self):
        fake = base_tests.reviewed_release_fixture(self.verify.verify)
        run = fake.workflow_runs[fake.heads[75]][0]
        run["pull_requests"] = []
        run["referenced_workflows"] = [{
            "path": (
                "tinyhumansai/.github/.github/workflows/module-ci.yml@"
                f"{historical_ci.MODULE_CI_PIN}"
            ),
            "sha": historical_ci.MODULE_CI_PIN,
        }]
        synthetic = base_tests.sha(81)
        fake.api.workflow_runs[fake.heads[75]][0] = run
        fake.api.job_logs = lambda _job_id: zip_logs(valid_checkout_log(synthetic, 75))
        actual_parents = fake.parents[fake.merges[75]]
        fake.api.commit_parents = lambda commit: (
            actual_parents if commit in {synthetic, fake.merges[75]} else ()
        )
        self.fake = fake
        self.run_verification()

    def test_historical_proof_rejects_forged_late_prelude_wrong_pr_pin_duplicates_and_parent_mismatch(self):
        synthetic = base_tests.sha(81)
        for label, log, pin, parents in (
            ("late prelude", valid_checkout_log(synthetic, 75, late_prelude=True), historical_ci.MODULE_CI_PIN, None),
            ("wrong pr", valid_checkout_log(synthetic, 74), historical_ci.MODULE_CI_PIN, None),
            ("duplicate checkout", valid_checkout_log(synthetic, 75, duplicate_checkout=True), historical_ci.MODULE_CI_PIN, None),
            ("wrong parents", valid_checkout_log(synthetic, 75), historical_ci.MODULE_CI_PIN, (base_tests.sha(1), base_tests.sha(2))),
            ("missing pin", valid_checkout_log(synthetic, 75), "f" * 40, None),
        ):
            fake = base_tests.reviewed_release_fixture(self.verify.verify)
            run = fake.workflow_runs[fake.heads[75]][0]
            run["pull_requests"] = []
            run["referenced_workflows"] = [{
                "path": f"tinyhumansai/.github/.github/workflows/module-ci.yml@{pin}",
                "sha": pin,
            }]
            fake.api.job_logs = lambda _job_id, contents=log: zip_logs(contents)
            actual_parents = fake.parents[fake.merges[75]]
            synthetic_parents = parents or actual_parents
            fake.api.commit_parents = lambda commit, sp=synthetic_parents: (
                sp if commit == synthetic else actual_parents
            )
            self.fake = fake
            with self.subTest(case=label), self.assertRaises(self.verify.verify.VerificationError):
                self.run_verification()

    def test_empty_association_with_missing_logs_and_newer_pending_attempt_fails_closed(self):
        fake = base_tests.reviewed_release_fixture(self.verify.verify)
        run = fake.workflow_runs[fake.heads[75]][0]
        run["pull_requests"] = []
        run["referenced_workflows"] = [{
            "path": f"tinyhumansai/.github/.github/workflows/module-ci.yml@{historical_ci.MODULE_CI_PIN}",
            "sha": historical_ci.MODULE_CI_PIN,
        }]
        fake.api.job_logs = lambda _job_id: b""
        self.fake = fake
        with self.assertRaisesRegex(self.verify.verify.VerificationError, "logs|archive"):
            self.run_verification()

        fake = base_tests.reviewed_release_fixture(self.verify.verify)
        head = fake.heads[75]
        pending = dict(fake.workflow_runs[head][0], run_attempt=2, status="in_progress", conclusion=None)
        fake.workflow_runs[head].append(pending)
        fake.workflow_jobs[(pending["id"], pending["run_attempt"])] = fake.workflow_jobs[
            (pending["id"], 1)
        ]
        self.fake = fake
        with self.assertRaisesRegex(self.verify.verify.VerificationError, "latest.*not successful"):
            self.run_verification()


def valid_checkout_log(synthetic_sha, pull_number, *, late_prelude=False, duplicate_checkout=False):
    prelude = (
        "Uses: tinyhumansai/.github/.github/workflows/module-ci.yml@"
        f"{historical_ci.MODULE_CI_PIN}\n##[group] Inputs\n##[endgroup]\n"
    )
    lines = [] if late_prelude else [prelude]
    lines.extend([
        "Complete job name: module-ci / fmt",
        f"##[group]Run actions/checkout@{historical_ci.CHECKOUT_ACTION_PIN}",
        f"[command]/usr/bin/git fetch +{synthetic_sha}:refs/remotes/pull/{pull_number}/merge",
        f"[command]/usr/bin/git checkout refs/remotes/pull/{pull_number}/merge",
        f"Note: switching to 'refs/remotes/pull/{pull_number}/merge'.",
        "[command]/usr/bin/git log -1 --format=%H",
        synthetic_sha,
    ])
    if duplicate_checkout:
        lines.append(f"##[group]Run actions/checkout@{historical_ci.CHECKOUT_ACTION_PIN}")
    if late_prelude:
        lines.append(prelude)
    lines.append("##[group]Run dtolnay/rust-toolchain@686976e191b89faba57d3206551f0f330d8cb249")
    return "\n".join(lines)


def zip_logs(text):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("0_Set up job.txt", text)
    return output.getvalue()


if __name__ == "__main__":
    unittest.main()
