"""Adapt the shared synthetic merge-history fixture to an allowlisted module."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


TRUSTED_MODULE_CI_PINS = {
    "tinyhumansai/tinyconnectors": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
    "tinyhumansai/tinybox": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
    "tinyhumansai/tinyjuice": "3e87ade76b622844985d0c665a3b075313e4545c",
    "tinyhumansai/tinywallet": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
    "tinyhumansai/tinymcp": "62c8ae0468f3882b75947d5cba9687e609ce1fed",
    "tinyhumansai/tinychannels": "3e87ade76b622844985d0c665a3b075313e4545c",
    "tinyhumansai/tinydocs": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
    "tinyhumansai/tinyvoice": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
    "tinyhumansai/tinymemes": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
    "tinyhumansai/tinysearch": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
    "tinyhumansai/tinyhosts": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
    "tinyhumansai/tinyflows": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
}


_fixture_path = Path(__file__).with_name("sdk-reviewed-release-fixtures.py")
_fixture_spec = importlib.util.spec_from_file_location("sdk_reviewed_fixture", _fixture_path)
_fixture_module = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_module)


def module_release_fixture(verifier, repository: str, package: str):
    """Return the shared four-merge fixture with canonical module identities."""
    fixture_verifier = SimpleNamespace(**vars(verifier))
    fixture_verifier.CI_WORKFLOW_ID = verifier.CI_WORKFLOW_IDS[repository]
    fake = _fixture_module.reviewed_release_fixture(fixture_verifier)
    api = fake.api
    api.repository = repository
    short_name = repository.split("/", 1)[1]
    fork_name = "senamakel/" + short_name
    workflow_pin = TRUSTED_MODULE_CI_PINS[repository]

    for pull in api.pulls.values():
        pull["base"]["repo"]["full_name"] = repository
        pull["head"]["repo"]["full_name"] = fork_name

    for runs in api.workflow_runs.values():
        for run in runs:
            run["workflow_id"] = verifier.CI_WORKFLOW_IDS[repository]
            run["repository"]["full_name"] = repository
            run["head_repository"]["full_name"] = fork_name
            for reference in run["referenced_workflows"]:
                reference["sha"] = workflow_pin
                reference["path"] = (
                    "tinyhumansai/.github/.github/workflows/module-ci.yml@" + workflow_pin
                )
            for association in run["pull_requests"]:
                association["url"] = (
                    f"https://api.github.com/repos/{repository}/pulls/"
                    f"{association['number']}"
                )
                association["base"]["repo"]["full_name"] = repository
                association["head"]["repo"]["full_name"] = fork_name

    for job_id, payload in api.logs.items():
        api.logs[job_id] = payload.replace(
            "4adc1080fb495098e7af1aade82ed7e6e3c69bb7", workflow_pin,
        )

    for jobs in api.workflow_jobs.values():
        for job in jobs:
            check_id = job["check_run_url"].rsplit("/", 1)[1]
            job["check_run_url"] = (
                f"https://api.github.com/repos/{repository}/check-runs/{check_id}"
            )

    api.release_package = package
    return fake
