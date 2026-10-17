"""Adapt the shared synthetic merge-history fixture to an allowlisted module."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_fixture_path = Path(__file__).with_name("sdk-reviewed-release-fixtures.py")
_fixture_spec = importlib.util.spec_from_file_location("sdk_reviewed_fixture", _fixture_path)
_fixture_module = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_module)


def module_release_fixture(verifier, repository: str, package: str):
    """Return the shared four-merge fixture with canonical module identities."""
    fake = _fixture_module.reviewed_release_fixture(verifier)
    api = fake.api
    api.repository = repository
    short_name = repository.split("/", 1)[1]
    fork_name = "senamakel/" + short_name

    for pull in api.pulls.values():
        pull["base"]["repo"]["full_name"] = repository
        pull["head"]["repo"]["full_name"] = fork_name

    for runs in api.workflow_runs.values():
        for run in runs:
            run["workflow_id"] = verifier.CI_WORKFLOW_IDS[repository]
            run["repository"]["full_name"] = repository
            run["head_repository"]["full_name"] = fork_name
            for association in run["pull_requests"]:
                association["url"] = (
                    f"https://api.github.com/repos/{repository}/pulls/"
                    f"{association['number']}"
                )
                association["base"]["repo"]["full_name"] = repository
                association["head"]["repo"]["full_name"] = fork_name

    for jobs in api.workflow_jobs.values():
        for job in jobs:
            check_id = job["check_run_url"].rsplit("/", 1)[1]
            job["check_run_url"] = (
                f"https://api.github.com/repos/{repository}/check-runs/{check_id}"
            )

    api.release_package = package
    return fake
