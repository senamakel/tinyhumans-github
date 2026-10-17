"""Fail-closed verification for TinyBus's temporary reviewed-epic SDK release."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


CANONICAL_REPO = "tinyhumansai/tinybus"
EPIC_BASE = "epic/8056-modules-wiring"
SDK_PACKAGE = "tinybus"
CHECK_APP_ID = 15368
MAX_EPIC_MERGES = 64
MAX_REST_PAGES = 100
MAX_GRAPHQL_PAGES = 100
MAX_TAG_DEPTH = 5
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
            if not page_info.get("hasNextPage"):
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


class BareHistory:
    """Fetch Git objects without creating a working tree or executing source."""

    def __init__(self, repository: str, tag: str, tag_sha: str, main_sha: str,
                 remote_url: str | None = None):
        self._temporary = tempfile.TemporaryDirectory(prefix="sdk-reviewed-history-")
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


def verify_tag_binding(api, tag: str, expected_sha: str) -> None:
    if api.repository != CANONICAL_REPO or not tag.startswith("v") or not SEMVER.fullmatch(tag[1:]):
        raise VerificationError("release tag binding is restricted to canonical TinyBus semver tags")
    expected_sha = _sha(expected_sha, "preflight source")
    actual_sha = api.tag_commit(tag)
    if actual_sha != expected_sha:
        raise VerificationError("release tag no longer resolves to the preflight source SHA")


def verify_reviewed_release(api, git_factory, repository: str, tag: str, version: str,
                            package: str, reviewed_pr: int) -> str:
    _validate_inputs(repository, tag, version, package, reviewed_pr)
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
    if repository != CANONICAL_REPO:
        raise VerificationError("reviewed-epic SDK release is restricted to canonical TinyBus")
    if package != SDK_PACKAGE:
        raise VerificationError("reviewed-epic SDK release is restricted to the tinybus package")
    if not SEMVER.fullmatch(version) or tag != f"v{version}":
        raise VerificationError("release tag and SDK version must be matching semver values")
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
    return {
        "number": number,
        "head_sha": _sha(head.get("sha"), "pull request head"),
        "author": author.get("login"),
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
    for required in REQUIRED_CHECKS:
        matching = [
            run for run in runs
            if run.get("name") == required
            and (run.get("app") or {}).get("id") == CHECK_APP_ID
        ]
        if not matching:
            raise VerificationError(f"trusted CI check is missing: {required}")
        latest = max(
            matching,
            key=lambda run: (run.get("started_at") or run.get("created_at") or "", int(run.get("id") or 0)),
        )
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            raise VerificationError(f"trusted CI check is not successful: {required}")


def _sha(value, label: str) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise VerificationError(f"{label} SHA was invalid")
    return value


def main() -> int:
    mode = os.environ.get("MODE", "reviewed")
    repository = os.environ.get("GH_REPO", "")
    tag = os.environ.get("TAG", "")
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        raise VerificationError("GitHub read token was not provided")
    api = GitHubApi(token, repository)
    if mode == "tag-only":
        verify_tag_binding(api, tag, os.environ.get("EXPECTED_SHA", ""))
        print("release tag still matches the verified source SHA")
        return 0
    if mode != "reviewed":
        raise VerificationError("unknown SDK release verification mode")
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
        os.environ.get("PACKAGE", ""),
        reviewed_pr,
    )
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"source-sha={source_sha}\n")
    print(f"verified reviewed TinyBus SDK source {source_sha}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except VerificationError as error:
        print(f"SDK release preflight refused: {error}", file=sys.stderr)
        raise SystemExit(1)
