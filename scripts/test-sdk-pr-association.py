"""Require canonical CI runs to belong to the exact reviewed pull request."""
from pathlib import Path
import importlib.util
import unittest


ROOT = Path(__file__).parents[1]
BASE_TEST = ROOT / "scripts/test-sdk-release.py"
spec = importlib.util.spec_from_file_location("sdk_release_tests", BASE_TEST)
base_tests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base_tests)


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


if __name__ == "__main__":
    unittest.main()
