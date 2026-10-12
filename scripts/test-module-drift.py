"""Offline regressions for the organization module workflow/ruleset guard."""
import copy
import importlib.util
import pathlib
import unittest

spec = importlib.util.spec_from_file_location("drift", pathlib.Path(__file__).with_name("check-module-drift.py"))
drift = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drift)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.ci = {"jobs": {"module-ci": {"uses": drift.PREFIX + "module-ci.yml@" + "a" * 40}}}
        self.release = {"jobs": {"module-release": {"uses": drift.PREFIX + "module-release.yml@" + "a" * 40, "with": {"include-distros": True}}}}
        self.ruleset = {
            "target": "branch", "enforcement": "active",
            "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
            "bypass_actors": [{"actor_type": "RepositoryRole", "actor_id": 5, "bypass_mode": "always"}],
            "rules": [{"type": "deletion"}, {"type": "non_fast_forward"},
                      {"type": "pull_request", "parameters": {"required_review_thread_resolution": True}},
                      {"type": "required_status_checks", "parameters": {
                          "strict_required_status_checks_policy": True,
                          "required_status_checks": [{"context": x, "integration_id": 15368} for x in drift.CHECKS]}}]}

    def validate(self):
        return drift.validate("tinyjuice", self.ci, self.release, [self.ruleset])

    def test_current_contract_passes(self):
        self.assertEqual(self.validate(), [])

    def test_unpinned_or_wrong_workflow_fails(self):
        for suffix in ("module-ci.yml@main", "other.yml@" + "a" * 40):
            self.ci["jobs"]["module-ci"]["uses"] = drift.PREFIX + suffix
            self.assertTrue(self.validate())

    def test_renamed_ci_job_fails(self):
        self.ci["jobs"]["renamed"] = self.ci["jobs"].pop("module-ci")
        self.assertTrue(self.validate())

    def test_duplicate_or_local_ci_job_fails(self):
        self.ci["jobs"]["test"] = {"runs-on": "ubuntu-latest", "steps": []}
        self.assertTrue(self.validate())

    def test_disabled_distro_builds_fail(self):
        self.release["jobs"]["module-release"]["with"]["include-distros"] = False
        self.assertTrue(self.validate())

    def test_missing_or_wrong_app_check_fails(self):
        checks = self.ruleset["rules"][-1]["parameters"]["required_status_checks"]
        checks.pop()
        self.assertTrue(self.validate())
        checks.append({"context": drift.CHECKS[-1], "integration_id": 1})
        self.assertTrue(self.validate())

    def test_non_strict_or_inactive_ruleset_fails(self):
        self.ruleset["enforcement"] = "evaluate"
        self.assertTrue(self.validate())
        self.ruleset["enforcement"] = "active"
        self.ruleset["rules"][-1]["parameters"]["strict_required_status_checks_policy"] = False
        self.assertTrue(self.validate())

    def test_main_excluded_fails(self):
        self.ruleset["conditions"]["ref_name"]["exclude"] = ["refs/heads/main"]
        self.assertTrue(self.validate())

    def test_missing_pr_or_admin_bypass_fails(self):
        self.ruleset["rules"] = [x for x in self.ruleset["rules"] if x["type"] != "pull_request"]
        self.assertTrue(self.validate())
        self.setUp()
        self.ruleset["bypass_actors"] = []
        self.assertTrue(self.validate())

    def test_public_ruleset_metadata_checks_visible_contract(self):
        del self.ruleset["bypass_actors"]
        self.assertEqual(self.validate(), [])
        self.ruleset["rules"][-1]["parameters"]["required_status_checks"].pop()
        self.assertTrue(self.validate())

    def test_documented_supplemental_jobs_pass(self):
        self.ci["jobs"]["wallet-dependency-boundaries"] = {"steps": []}
        self.assertEqual(drift.validate("tinywallet", self.ci, self.release, [self.ruleset]), [])
        self.assertTrue(self.validate())
        self.setUp()
        for repo, job in (("tinydocs", "source-packages"), ("tinycomputer", "verify-published")):
            release = copy.deepcopy(self.release)
            release["jobs"][job] = {"steps": []}
            self.assertEqual(drift.validate(repo, self.ci, release, [self.ruleset]), [])

    def test_sdk_exception_is_explicit(self):
        self.release = {"jobs": {"sdk-release": {"uses": drift.PREFIX + "sdk-release.yml@" + "a" * 40}}}
        self.assertEqual(drift.validate("tinybus", self.ci, self.release, [self.ruleset]), [])
        self.assertTrue(self.validate())

    def test_additional_active_rulesets_require_admin_bypass(self):
        other = copy.deepcopy(self.ruleset)
        other["bypass_actors"] = []
        self.assertTrue(drift.validate("tinyjuice", self.ci, self.release, [self.ruleset, other]))


if __name__ == "__main__":
    unittest.main()
