"""Fail-closed verification for the temporary reviewed module release path."""

from __future__ import annotations

import json
import ipaddress
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_ci import verify_ci_merge_provenance
from historical_ci import read_ci_checkout_proof


MODULE_PROFILES = {
    "tinyhumansai/tinyconnectors": {
        "package": "tinyconnectors", "asset": "tinyconnectors", "manifest": "Cargo.toml",
        "extra_files": [], "workflow_id": 345777017,
        "module_ci_sha": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
    },
    "tinyhumansai/tinybox": {
        "package": "tinybox-module", "asset": "tinybox", "manifest": "Cargo.toml",
        "extra_files": [], "workflow_id": 334144667,
        "module_ci_sha": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
    },
    "tinyhumansai/tinyjuice": {
        "package": "tinyjuice-module", "asset": "tinyjuice-module", "manifest": "Cargo.toml",
        "extra_files": ["docs/specs/tinybus-module.md"], "workflow_id": 307270985,
        "module_ci_sha": "3e87ade76b622844985d0c665a3b075313e4545c",
    },
    "tinyhumansai/tinywallet": {
        "package": "tinywallet-module", "asset": "tinywallet-module", "manifest": "Cargo.toml",
        "extra_files": [], "workflow_id": 331024528,
        "module_ci_sha": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
    },
    "tinyhumansai/tinymcp": {
        "package": "tinymcp", "asset": "tinymcp", "manifest": "Cargo.toml",
        "extra_files": [], "workflow_id": 339480400,
        "module_ci_sha": "62c8ae0468f3882b75947d5cba9687e609ce1fed",
    },
    "tinyhumansai/tinychannels": {
        "package": "tinychannels-module", "asset": "tinychannels-module", "manifest": "Cargo.toml",
        "extra_files": [], "workflow_id": 307289287,
        "module_ci_sha": "3e87ade76b622844985d0c665a3b075313e4545c",
    },
    "tinyhumansai/tinydocs": {
        "package": "tinydocs-module", "asset": "tinydocs-module", "manifest": "Cargo.toml",
        "extra_files": ["docs/specs/tinybus-module.md"], "workflow_id": 331024957,
        "module_ci_sha": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
        "source_bundle": "tinydocs",
    },
    "tinyhumansai/tinyvoice": {
        "package": "tinyvoice-module", "asset": "tinyvoice-module",
        "manifest": "crates/tinyvoice-module/Cargo.toml", "extra_files": [],
        "workflow_id": 333928426,
        "module_ci_sha": "4adc1080fb495098e7af1aade82ed7e6e3c69bb7",
        "apt_packages": "libasound2-dev libx11-dev libxtst-dev libxi-dev",
    },
}
MODULE_PACKAGES = {repo: profile["package"] for repo, profile in MODULE_PROFILES.items()}
CI_WORKFLOW_IDS = {repo: profile["workflow_id"] for repo, profile in MODULE_PROFILES.items()}
EPIC_BASE = "epic/8056-modules-wiring"
CHECK_APP_ID = 15368
CI_WORKFLOW_PATH = ".github/workflows/ci.yml"
MAX_EPIC_MERGES = 64
MAX_REST_PAGES = 100
MAX_GRAPHQL_PAGES = 100
MAX_TAG_DEPTH = 5
MAX_CI_PROVENANCE_RUNS = 64
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+([+-][0-9A-Za-z.-]+)?$")
SHA = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_CHECKS = (
    "module-ci / fmt",
    "module-ci / clippy",
    "module-ci / test",
    "module-ci / coverage",
    "module-ci / docs",
    "module-ci / msrv",
    "module-ci / supply-chain",
    "module-ci / module-e2e (ubuntu-latest)",
    "module-ci / module-e2e (macos-latest)",
    "module-ci / module-e2e (windows-latest)",
    "module-ci / feature-tests (ubuntu-latest)",
    "module-ci / feature-tests (macos-latest)",
    "module-ci / feature-tests (windows-latest)",
)


class VerificationError(RuntimeError):
    """A release prerequisite could not be proven from canonical GitHub data."""


class GitHubApi:
    """Small read-only GitHub API client with explicit bounded pagination."""

    def __init__(self, token: str, repository: str):
        self.token = token
        self.repository = repository

    def _request(self, path: str, *, method: str = "GET", payload: dict | None = None):
        url = f"https://api.github.com/{path.lstrip('/')}"
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as error:
            raise VerificationError(f"GitHub API request failed: {method} {path}") from error

    def rest_pages(self, path: str, *, collection: str | None = None) -> list:
        results = []
        for page in range(1, MAX_REST_PAGES + 1):
            separator = "&" if "?" in path else "?"
            response = self._request(f"{path}{separator}per_page=100&page={page}")
            values = response if collection is None else response.get(collection)
            if not isinstance(values, list):
                raise VerificationError(f"GitHub API returned an invalid page for {path}")
            results.extend(values)
            if len(values) < 100:
                return results
        raise VerificationError(f"GitHub API pagination exceeded its bound for {path}")

    def graphql_pages(self, query: str, variables: dict, connection: str) -> list:
        results = []
        cursor = None
        for _ in range(MAX_GRAPHQL_PAGES):
            page_variables = dict(variables, cursor=cursor)
            response = self._request("graphql", method="POST", payload={
                "query": query,
                "variables": page_variables,
            })
            if response.get("errors"):
                raise VerificationError("GitHub GraphQL request returned errors")
            try:
                result = response["data"]["repository"]["pullRequest"][connection]
                nodes = result["nodes"]
                page_info = result["pageInfo"]
            except (KeyError, TypeError) as error:
                raise VerificationError("GitHub GraphQL response was incomplete") from error
            if not isinstance(nodes, list) or not isinstance(page_info, dict):
                raise VerificationError("GitHub GraphQL response was malformed")
            results.extend(nodes)
            has_next_page = page_info.get("hasNextPage")
            if not isinstance(has_next_page, bool):
                raise VerificationError("GitHub GraphQL pageInfo was incomplete")
            if not has_next_page:
                return results
            cursor = page_info.get("endCursor")
            if not isinstance(cursor, str) or not cursor:
                raise VerificationError("GitHub GraphQL pagination cursor was missing")
        raise VerificationError("GitHub GraphQL pagination exceeded its bound")

    def tag_commit(self, tag: str) -> str:
        encoded_tag = urllib.parse.quote(tag, safe="")
        ref = self._request(f"repos/{self.repository}/git/ref/tags/{encoded_tag}")
        target = ref.get("object", {})
        for _ in range(MAX_TAG_DEPTH):
            sha = _sha(target.get("sha"), "tag object")
            object_type = target.get("type")
            if object_type == "commit":
                return sha
            if object_type != "tag":
                raise VerificationError("release tag does not resolve to a commit")
            tag_object = self._request(f"repos/{self.repository}/git/tags/{sha}")
            target = tag_object.get("object", {})
        raise VerificationError("release tag nesting exceeded its bound")

    def main_sha(self) -> str:
        response = self._request(f"repos/{self.repository}/branches/main")
        if not isinstance(response, dict) or response.get("protected") is not True:
            raise VerificationError("canonical main branch protection could not be proven")
        try:
            return _sha(response["commit"]["sha"], "main branch")
        except (KeyError, TypeError) as error:
            raise VerificationError("canonical main branch response was incomplete") from error

    def pull_request(self, number: int) -> dict:
        return self._request(f"repos/{self.repository}/pulls/{number}")

    def pull_requests_for_commit(self, commit: str) -> list:
        return self.rest_pages(f"repos/{self.repository}/commits/{commit}/pulls")

    def reviews_for_pull(self, number: int) -> list:
        return self.rest_pages(f"repos/{self.repository}/pulls/{number}/reviews")

    def review_threads_for_pull(self, number: int) -> list:
        query = """
        query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
          repository(owner: $owner, name: $name) {
            pullRequest(number: $number) {
              reviewThreads(first: 100, after: $cursor) {
                nodes { isResolved isOutdated }
                pageInfo { hasNextPage endCursor }
              }
            }
          }
        }
        """
        owner, name = self.repository.split("/", 1)
        return self.graphql_pages(
            query,
            {"owner": owner, "name": name, "number": number},
            "reviewThreads",
        )

    def check_runs_for_commit(self, commit: str) -> list:
        return self.rest_pages(
            f"repos/{self.repository}/commits/{commit}/check-runs",
            collection="check_runs",
        )

    def workflow_runs_for_commit(self, commit: str) -> list:
        return self.rest_pages(
            f"repos/{self.repository}/actions/runs?head_sha={commit}",
            collection="workflow_runs",
        )

    def jobs_for_workflow_run(self, run_id: int, attempt: int) -> list:
        return self.rest_pages(
            f"repos/{self.repository}/actions/runs/{run_id}/attempts/{attempt}/jobs",
            collection="jobs",
        )

    def job_logs(self, job_id: int) -> bytes:
        if type(job_id) is not int or job_id < 1:
            raise VerificationError("canonical fmt job id was invalid")
        url = f"https://api.github.com/repos/{self.repository}/actions/jobs/{job_id}/logs"
        request = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            try:
                response = opener.open(request, timeout=30)
            except urllib.error.HTTPError as redirect:
                if redirect.code not in {301, 302, 303, 307, 308}:
                    raise VerificationError("canonical fmt job logs could not be downloaded") from redirect
                location = redirect.headers.get("Location")
                parsed = urllib.parse.urlsplit(location or "")
                host = (parsed.hostname or "").lower().rstrip(".")
                try:
                    port = parsed.port
                except ValueError:
                    port = -1
                try:
                    address = ipaddress.ip_address(host)
                except ValueError:
                    address = None
                if (
                    parsed.scheme != "https"
                    or not host
                    or parsed.username
                    or parsed.password
                    or port not in (None, 443)
                    or parsed.fragment
                    or host == "localhost"
                    or host.endswith((".localhost", ".local"))
                    or (address is not None and not address.is_global)
                ):
                    raise VerificationError("canonical fmt job log redirect was invalid") from redirect
                # The signed archive URL is deliberately requested without GitHub credentials.
                response = opener.open(urllib.request.Request(location), timeout=30)
            with response:
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        if int(content_length) > 8 * 1024 * 1024:
                            raise VerificationError("canonical fmt job logs exceeded their size bound")
                    except ValueError as error:
                        raise VerificationError("canonical fmt job log size was malformed") from error
                payload = response.read(8 * 1024 * 1024 + 1)
                if len(payload) > 8 * 1024 * 1024:
                    raise VerificationError("canonical fmt job logs exceeded their size bound")
                return payload
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise VerificationError("canonical fmt job logs could not be downloaded") from error

    def commit_details(self, commit: str) -> dict:
        commit = _sha(commit, "historical CI checkout")
        response = self._request(f"repos/{self.repository}/git/commits/{commit}")
        parents = response.get("parents") if isinstance(response, dict) else None
        tree = response.get("tree") if isinstance(response, dict) else None
        if not isinstance(parents, list) or len(parents) != 2:
            raise VerificationError("historical CI merge commit did not have two parents")
        try:
            tree_sha = _sha(tree["sha"], "historical merge tree")
            parent_shas = tuple(_sha(parent["sha"], "historical merge parent") for parent in parents)
        except (KeyError, TypeError) as error:
            raise VerificationError("historical CI merge tree or parents were malformed") from error
        return {"tree_sha": tree_sha, "parents": parent_shas}

    def commit_parents(self, commit: str) -> tuple[str, ...]:
        return self.commit_details(commit)["parents"]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Keep bearer credentials off the signed job-log archive redirect."""

    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


class BareHistory:
    """Fetch Git objects without creating a working tree or executing source."""

    def __init__(self, repository: str, tag: str, tag_sha: str, main_sha: str,
                 remote_url: str | None = None):
        self._temporary = tempfile.TemporaryDirectory(prefix="module-reviewed-history-")
        self.git_dir = Path(self._temporary.name) / "history.git"
        self._run(["git", "init", "--bare", str(self.git_dir)])
        remote = remote_url or f"https://github.com/{repository}.git"
        tag_ref = f"refs/tags/{tag}:refs/tags/{tag}"
        main_ref = "refs/heads/main:refs/remotes/canonical/main"
        self._run([
            "git", "--git-dir", str(self.git_dir), "fetch", "--no-tags",
            "--no-recurse-submodules", remote, tag_ref, main_ref,
        ])
        fetched_tag = self._run([
            "git", "--git-dir", str(self.git_dir), "rev-parse", f"refs/tags/{tag}^{{commit}}",
        ]).strip()
        fetched_main = self._run([
            "git", "--git-dir", str(self.git_dir), "rev-parse", "refs/remotes/canonical/main",
        ]).strip()
        if fetched_tag != tag_sha or fetched_main != main_sha:
            raise VerificationError("canonical tag or main moved during preflight")
        self.tag_sha = fetched_tag
        self.main_sha = fetched_main

    def _run(self, args: list[str]) -> str:
        environment = os.environ.copy()
        for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"):
            environment.pop(name, None)
        result = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        if result.returncode != 0:
            raise VerificationError("bare Git history verification failed")
        return result.stdout

    def parents_of(self, commit: str) -> tuple[str, ...]:
        values = self._run([
            "git", "--git-dir", str(self.git_dir), "rev-list", "--parents", "-n", "1", commit,
        ]).split()
        if not values or values[0] != commit:
            raise VerificationError("Git returned an unexpected commit during history walk")
        return tuple(values[1:])

    def is_ancestor_of(self, commit: str, head: str) -> bool:
        result = self._run_status([
            "git", "--git-dir", str(self.git_dir), "merge-base", "--is-ancestor", commit, head,
        ])
        if result == 0:
            return True
        if result == 1:
            return False
        raise VerificationError("Git ancestry verification failed")

    def _run_status(self, args: list[str]) -> int:
        environment = os.environ.copy()
        for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"):
            environment.pop(name, None)
        result = subprocess.run(args, check=False, capture_output=True, text=True, env=environment)
        if result.returncode not in (0, 1):
            raise VerificationError("Git ancestry verification failed")
        return result.returncode

    def close(self):
        self._temporary.cleanup()


def verify_tag_binding(api, tag: str, expected_sha: str, package: str) -> None:
    _validate_module(api.repository, package)
    if not tag.startswith("v") or not SEMVER.fullmatch(tag[1:]):
        raise VerificationError("release tag must be a canonical module semver tag")
    expected_sha = _sha(expected_sha, "preflight source")
    actual_sha = api.tag_commit(tag)
    if actual_sha != expected_sha:
        raise VerificationError("release tag no longer resolves to the verified module source SHA")


def verify_reviewed_release(api, git_factory, repository: str, tag: str, version: str,
                            package: str, reviewed_pr: int) -> str:
    _validate_inputs(repository, tag, version, package, reviewed_pr)
    if getattr(api, "repository", None) != repository:
        raise VerificationError("GitHub API repository does not match the canonical module profile")
    tag_sha = api.tag_commit(tag)
    main_sha = api.main_sha()
    history = git_factory(repository, tag, tag_sha, main_sha)
    try:
        if history.tag_sha != tag_sha or history.main_sha != main_sha:
            raise VerificationError("canonical tag or main moved during preflight")
        release_pull = _validate_pull(api.pull_request(reviewed_pr), repository, tag_sha)
        if release_pull["number"] != reviewed_pr:
            raise VerificationError("release pull request number did not match its API response")

        current = tag_sha
        seen = set()
        verified_prs = 0
        for _ in range(MAX_EPIC_MERGES + 1):
            if history.is_ancestor_of(current, main_sha):
                if verified_prs == 0:
                    raise VerificationError("reviewed-epic path contains no epic PR merges")
                return tag_sha
            if verified_prs >= MAX_EPIC_MERGES:
                raise VerificationError("epic first-parent history exceeded its bound")
            if current in seen:
                raise VerificationError("epic first-parent history contains a cycle")
            seen.add(current)

            parents = history.parents_of(current)
            if len(parents) != 2:
                raise VerificationError("epic commit is not a two-parent pull-request merge")
            first_parent, second_parent = parents
            associated = api.pull_requests_for_commit(current)
            matching = []
            for item in associated:
                number = item.get("number")
                if not isinstance(number, int):
                    raise VerificationError("associated pull request was missing its number")
                pull = _validate_pull(api.pull_request(number), repository, current)
                if pull["head_sha"] == second_parent:
                    matching.append(pull)
            if len(matching) != 1:
                raise VerificationError("epic merge did not have one exact merged pull request")
            pull = matching[0]
            if verified_prs == 0 and pull["number"] != reviewed_pr:
                raise VerificationError("tag did not identify the requested reviewed pull request")
            _verify_effective_reviews(api, pull)
            _verify_review_threads(api, pull)
            _verify_required_checks(api, pull)
            verified_prs += 1
            current = first_parent
        raise VerificationError("epic first-parent history exceeded its bound")
    finally:
        close = getattr(history, "close", None)
        if close is not None:
            close()


def _validate_inputs(repository: str, tag: str, version: str, package: str, reviewed_pr: int):
    _validate_module(repository, package)
    if not SEMVER.fullmatch(version) or tag != f"v{version}":
        raise VerificationError("release tag and module version must be matching semver values")
    if not isinstance(reviewed_pr, int) or reviewed_pr < 1:
        raise VerificationError("reviewed pull request number must be a positive integer")


def _validate_pull(pull: dict, repository: str, merge_sha: str) -> dict:
    if not isinstance(pull, dict):
        raise VerificationError("GitHub returned an invalid pull request")
    base = pull.get("base") or {}
    base_repo = base.get("repo") or {}
    head = pull.get("head") or {}
    author = pull.get("user") or {}
    if (
        pull.get("merged") is not True
        or pull.get("state") != "closed"
        or pull.get("merge_commit_sha") != merge_sha
        or base_repo.get("full_name") != repository
        or base.get("ref") != EPIC_BASE
    ):
        raise VerificationError("pull request was not merged to the approved canonical epic base")
    number = pull.get("number")
    if not isinstance(number, int) or number < 1:
        raise VerificationError("GitHub pull request number was invalid")
    head_repository = (head.get("repo") or {}).get("full_name")
    head_ref = head.get("ref")
    if not isinstance(head_repository, str) or not head_repository:
        raise VerificationError("pull request head repository was missing")
    if not isinstance(head_ref, str) or not head_ref:
        raise VerificationError("pull request head branch was missing")
    return {
        "number": number,
        "head_sha": _sha(head.get("sha"), "pull request head"),
        "head_ref": head_ref,
        "head_repository": head_repository,
        "author": author.get("login"),
        "merge_sha": _sha(pull.get("merge_commit_sha"), "pull request merge"),
    }


def _verify_effective_reviews(api, pull: dict) -> None:
    latest = {}
    for review in api.reviews_for_pull(pull["number"]):
        user = review.get("user") or {}
        login = user.get("login")
        state = review.get("state")
        if not login or login == pull["author"] or state not in {
            "APPROVED", "CHANGES_REQUESTED", "DISMISSED",
        }:
            continue
        key = (review.get("submitted_at") or "", int(review.get("id") or 0))
        if login not in latest or key > latest[login][0]:
            latest[login] = (key, state)
    if any(state == "CHANGES_REQUESTED" for _, state in latest.values()):
        raise VerificationError("pull request has an effective changes-requested review")


def _verify_review_threads(api, pull: dict) -> None:
    threads = api.review_threads_for_pull(pull["number"])
    if any(thread.get("isResolved") is not True for thread in threads):
        raise VerificationError("pull request has an unresolved review thread")


def _verify_required_checks(api, pull: dict) -> None:
    runs = api.check_runs_for_commit(pull["head_sha"])
    workflow_runs = api.workflow_runs_for_commit(pull["head_sha"])
    canonical_runs = [
        run for run in workflow_runs
        if isinstance(run, dict)
        and run.get("path") == CI_WORKFLOW_PATH
        and run.get("workflow_id") == CI_WORKFLOW_IDS[api.repository]
        and run.get("event") == "pull_request"
        and run.get("head_sha") == pull["head_sha"]
        and run.get("head_branch") == pull["head_ref"]
        and (run.get("repository") or {}).get("full_name") == api.repository
        and (run.get("head_repository") or {}).get("full_name") == pull["head_repository"]
        and type(run.get("id")) is int
        and run["id"] > 0
        and type(run.get("run_number")) is int
        and run["run_number"] > 0
        and type(run.get("run_attempt")) is int
        and run["run_attempt"] > 0
        and run.get("check_suite_id") is not None
    ]
    associated_runs = []
    empty_association_runs = []
    associated_pull_by_run = {}
    for run in canonical_runs:
        associated_pulls = run.get("pull_requests")
        if not isinstance(associated_pulls, list):
            raise VerificationError("canonical CI workflow run has a missing or malformed pull request association")
        if not associated_pulls:
            empty_association_runs.append(run)
            continue
        associated_numbers = []
        for associated_pull in associated_pulls:
            if not isinstance(associated_pull, dict):
                raise VerificationError("canonical CI workflow run has a malformed pull request association")
            number = associated_pull.get("number")
            if type(number) is not int or number < 1:
                raise VerificationError("canonical CI workflow run has a malformed pull request association")
            associated_numbers.append(number)
        if len(set(associated_numbers)) != len(associated_numbers):
            raise VerificationError("canonical CI workflow run has duplicate pull request associations")
        if pull["number"] in associated_numbers:
            associated_runs.append(run)
            associated_pull_by_run[run["id"]] = next(
                item for item in associated_pulls if item.get("number") == pull["number"]
            )
    canonical_runs = associated_runs + empty_association_runs
    if not canonical_runs:
        raise VerificationError("canonical CI workflow run could not be proven for the exact pull request")
    if len(canonical_runs) > MAX_CI_PROVENANCE_RUNS:
        raise VerificationError("canonical CI provenance candidates exceeded their bound")

    selected_jobs = None
    checkout_proof = None
    workflow_run = None
    workflow_association = None
    canonical_runs.sort(key=lambda run: (run["run_number"], run["run_attempt"], run["id"]), reverse=True)
    for candidate in canonical_runs:
        association_list = candidate["pull_requests"]
        if association_list:
            workflow_run = candidate
            workflow_association = associated_pull_by_run[candidate["id"]]
            break

        jobs = api.jobs_for_workflow_run(candidate["id"], candidate["run_attempt"])
        fmt_job = _fmt_job_for_run(jobs, candidate, pull)
        try:
            proof = read_ci_checkout_proof(
                api, candidate, fmt_job, MODULE_PROFILES[api.repository]["module_ci_sha"]
            )
        except ValueError as error:
            raise VerificationError(str(error)) from error
        if proof["pull_number"] != pull["number"]:
            # The pinned runner checkout proves this empty-association run belongs to another PR.
            continue
        workflow_run = candidate
        workflow_association = None
        selected_jobs = jobs
        checkout_proof = proof
        break

    if workflow_run is None:
        raise VerificationError("canonical CI workflow run could not be proven for the exact pull request")
    if workflow_run.get("status") != "completed" or workflow_run.get("conclusion") != "success":
        raise VerificationError("latest canonical CI workflow run is not successful")

    historical_empty_association = workflow_run.get("pull_requests") == []
    if not historical_empty_association and workflow_association is None:
        raise VerificationError("canonical CI run association for the exact pull request was lost")

    jobs = selected_jobs or api.jobs_for_workflow_run(workflow_run["id"], workflow_run["run_attempt"])
    job_by_name = {}
    for job in jobs:
        name = job.get("name") if isinstance(job, dict) else None
        if name in REQUIRED_CHECKS:
            if name in job_by_name:
                raise VerificationError(f"canonical CI job is duplicated: {name}")
            job_by_name[name] = job

    for required in REQUIRED_CHECKS:
        job = job_by_name.get(required)
        if job is None:
            raise VerificationError(f"trusted CI check is missing from canonical workflow run: {required}")
        if (
            job.get("run_id") != workflow_run["id"]
            or job.get("run_attempt") != workflow_run["run_attempt"]
            or job.get("head_sha") != pull["head_sha"]
            or job.get("status") != "completed"
            or job.get("conclusion") != "success"
        ):
            raise VerificationError(f"canonical CI job is not successful: {required}")
        check_run_id = _check_run_id(job.get("check_run_url"), api.repository)
        matching = [
            run for run in runs
            if run.get("name") == required
            and (run.get("app") or {}).get("id") == CHECK_APP_ID
            and run.get("id") == check_run_id
            and run.get("head_sha") == pull["head_sha"]
            and ((run.get("check_suite") or {}).get("id") == workflow_run["check_suite_id"])
        ]
        if not matching:
            raise VerificationError(f"trusted CI check is missing: {required}")
        latest = max(
            matching,
            key=lambda run: (run.get("started_at") or run.get("created_at") or "", int(run.get("id") or 0)),
        )
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            raise VerificationError(f"trusted CI check is not successful: {required}")
        if required == REQUIRED_CHECKS[0]:
            try:
                verify_ci_merge_provenance(
                    api, workflow_run, job, pull, workflow_association, checkout_proof,
                    repository=api.repository, epic_base=EPIC_BASE,
                    module_ci_pin=MODULE_PROFILES[api.repository]["module_ci_sha"],
                )
            except ValueError as error:
                raise VerificationError(str(error)) from error


def _fmt_job_for_run(jobs: list, workflow_run: dict, pull: dict) -> dict:
    matches = [job for job in jobs if isinstance(job, dict) and job.get("name") == REQUIRED_CHECKS[0]]
    if len(matches) != 1:
        raise VerificationError("empty-association run did not contain one canonical fmt job")
    job = matches[0]
    if (
        type(job.get("id")) is not int
        or job["id"] < 1
        or job.get("run_id") != workflow_run["id"]
        or job.get("run_attempt") != workflow_run["run_attempt"]
        or job.get("head_sha") != pull["head_sha"]
        or job.get("status") != "completed"
    ):
        raise VerificationError("empty-association fmt job was incomplete or mismatched")
    return job


def _check_run_id(value, repository: str) -> int:
    if not isinstance(value, str):
        raise VerificationError("canonical CI job did not identify its check run")
    match = re.fullmatch(
        rf"https://api\.github\.com/repos/{re.escape(repository)}/check-runs/([0-9]+)",
        value,
    )
    if match is None:
        raise VerificationError("canonical CI job check-run URL was invalid")
    return int(match.group(1))


def _validate_module(repository: str, package: str) -> dict:
    """Resolve only an exact canonical repository and compiled-in package."""
    profile = _module_profile(repository)
    if profile["package"] != package:
        raise VerificationError("repository and module package are outside the reviewed allowlist")
    return profile


def _module_profile(repository: str) -> dict:
    """Resolve the literal profile before reading repository-specific API data."""
    profile = MODULE_PROFILES.get(repository)
    if profile is None:
        raise VerificationError("repository is outside the reviewed module allowlist")
    return profile


def _sha(value, label: str) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise VerificationError(f"{label} SHA was invalid")
    return value


def main() -> int:
    mode = os.environ.get("MODE", "reviewed")
    repository = os.environ.get("GH_REPO", "")
    tag = os.environ.get("TAG", "")
    profile = _module_profile(repository)
    supplied_package = os.environ.get("PACKAGE", "")
    if supplied_package and supplied_package != profile["package"]:
        raise VerificationError("repository and module package are outside the reviewed allowlist")
    if mode == "tag-only" and not supplied_package:
        raise VerificationError("tag-only verification requires the compiled-in module package")
    package = profile["package"]
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        raise VerificationError("GitHub read token was not provided")
    api = GitHubApi(token, repository)
    if mode == "tag-only":
        verify_tag_binding(api, tag, os.environ.get("EXPECTED_SHA", ""), package)
        print("release tag still matches the verified module source SHA")
        return 0
    if mode != "reviewed":
        raise VerificationError("unknown module release verification mode")
    try:
        reviewed_pr = int(os.environ.get("REVIEWED_PR", ""))
    except ValueError as error:
        raise VerificationError("reviewed pull request number was invalid") from error
    source_sha = verify_reviewed_release(
        api,
        BareHistory,
        repository,
        tag,
        os.environ.get("VERSION", ""),
        package,
        reviewed_pr,
    )
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"source-sha={source_sha}\n")
        output.write(f"module-package={profile['package']}\n")
        output.write(f"module-asset={profile['asset']}\n")
        output.write(f"module-manifest={profile['manifest']}\n")
        output.write(f"extra-packaged-files={json.dumps(profile['extra_files'], separators=(',', ':'))}\n")
        output.write(f"module-apt-packages={profile.get('apt_packages', '')}\n")
        output.write(f"module-source-bundle={profile.get('source_bundle', '')}\n")
    print(f"verified reviewed module source {source_sha}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except VerificationError as error:
        print(f"Module release preflight refused: {error}", file=sys.stderr)
        raise SystemExit(1)
