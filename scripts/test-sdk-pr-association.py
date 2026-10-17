"""Require canonical CI runs to belong to the exact reviewed pull request."""
from pathlib import Path
import importlib.util
import io
import email.message
import unittest
from unittest.mock import patch
import urllib.error
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
                self.verify.verify.VerificationError, "workflow run|pull request|references|pin|logs"
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
            ("attacker Uses with spoofed input", attacker_prelude_log(synthetic, 75), historical_ci.MODULE_CI_PIN, None),
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

    def test_live_job_log_payload_parser_accepts_utf8_and_bounded_zip(self):
        payload = valid_checkout_log(base_tests.sha(81), 75).encode("utf-8-sig")
        self.assertEqual(historical_ci._decode_job_logs(payload), payload.decode("utf-8-sig"))
        zipped = zip_logs("fmt log")
        self.assertEqual(historical_ci._decode_job_logs(zipped), "fmt log")

    def test_job_log_redirect_drops_credentials_and_enforces_https_and_size_bounds(self):
        requests = []
        response = FakeResponse(b"safe", {"Content-Length": "4"})

        class Opener:
            def open(self, request, timeout):
                requests.append(request)
                if len(requests) == 1:
                    headers = email.message.Message()
                    headers["Location"] = "https://logs.example.invalid/private.zip?sig=secret"
                    raise urllib.error.HTTPError(request.full_url, 302, "Found", headers, None)
                return response

        with patch.object(self.verify.verify.urllib.request, "build_opener", return_value=Opener()):
            result = self.verify.verify.GitHubApi("private-token", "tinyhumansai/tinybus").job_logs(123)
        self.assertEqual(result, b"safe")
        self.assertTrue(any(name.lower() == "authorization" for name, _ in requests[0].header_items()))
        self.assertFalse(any(name.lower() == "authorization" for name, _ in requests[1].header_items()))

        for location in ("http://logs.example.invalid/logs", "https://user@logs.example.invalid/logs"):
            with self.subTest(location=location):
                class InvalidRedirectOpener:
                    def open(self, request, timeout):
                        headers = email.message.Message()
                        headers["Location"] = location
                        raise urllib.error.HTTPError(request.full_url, 302, "Found", headers, None)

                with patch.object(self.verify.verify.urllib.request, "build_opener", return_value=InvalidRedirectOpener()):
                    with self.assertRaisesRegex(self.verify.verify.VerificationError, "redirect was invalid"):
                        self.verify.verify.GitHubApi("private-token", "tinyhumansai/tinybus").job_logs(123)

        class OversizedResponse(FakeResponse):
            pass

        with patch.object(self.verify.verify.urllib.request, "build_opener", return_value=SingleResponseOpener(
            OversizedResponse(b"too big", {"Content-Length": str(8 * 1024 * 1024 + 1)})
        )):
            with self.assertRaisesRegex(self.verify.verify.VerificationError, "size bound"):
                self.verify.verify.GitHubApi("private-token", "tinyhumansai/tinybus").job_logs(123)

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
        runner_line("Uses: tinyhumansai/.github/.github/workflows/module-ci.yml@"
                    f"{historical_ci.MODULE_CI_PIN}")
        + "\n" + runner_line("##[group] Inputs") + "\n" + runner_line("##[endgroup]") + "\n"
    )
    lines = [] if late_prelude else [prelude]
    lines.extend([
        runner_line("Complete job name: module-ci / fmt"),
        runner_line(f"##[group]Run actions/checkout@{historical_ci.CHECKOUT_ACTION_PIN}"),
        runner_line(f"[command]/usr/bin/git fetch +{synthetic_sha}:refs/remotes/pull/{pull_number}/merge"),
        runner_line(f"[command]/usr/bin/git checkout refs/remotes/pull/{pull_number}/merge"),
        runner_line(f"Note: switching to 'refs/remotes/pull/{pull_number}/merge'."),
        runner_line("[command]/usr/bin/git log -1 --format=%H"),
        runner_line(synthetic_sha),
    ])
    if duplicate_checkout:
        lines.append(runner_line(f"##[group]Run actions/checkout@{historical_ci.CHECKOUT_ACTION_PIN}"))
    if late_prelude:
        lines.append(runner_line(prelude.strip()))
    lines.append(runner_line("##[group]Run dtolnay/rust-toolchain@686976e191b89faba57d3206551f0f330d8cb249"))
    return "\n".join(lines)


def runner_line(message):
    return f"module-ci / fmt\tUNKNOWN STEP\t2026-10-17T09:38:22.8052667Z {message}"


def attacker_prelude_log(synthetic_sha, pull_number):
    lines = valid_checkout_log(synthetic_sha, pull_number).splitlines()
    lines[0] = runner_line("Uses: attacker/evil/.github/workflows/spoof.yml@" + "a" * 40)
    lines.insert(3, runner_line(
        "Uses: tinyhumansai/.github/.github/workflows/module-ci.yml@" + historical_ci.MODULE_CI_PIN
    ))
    return "\n".join(lines)


def zip_logs(text):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("0_Set up job.txt", text)
    return output.getvalue()


class FakeResponse:
    def __init__(self, payload, headers):
        self.payload = payload
        self.headers = headers
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, count=-1):
        return self.payload[:count]


class SingleResponseOpener:
    def __init__(self, response):
        self.response = response

    def open(self, _request, timeout):
        return self.response


if __name__ == "__main__":
    unittest.main()
