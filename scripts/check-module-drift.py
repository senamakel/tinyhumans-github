"""Check public upstream module callers and main protections; never mutate GitHub."""
import base64
import json
import os
import re
import sys
import urllib.request

import yaml

REPOS = ("tinybus", "tinybox", "tinychannels", "tinycomputer", "tinyconnectors",
         "tinydocs", "tinyhosts", "tinyjuice", "tinymcp", "tinyruntime",
         "tinysearch", "tinyvoice", "tinywallet")
PREFIX = "tinyhumansai/.github/.github/workflows/"
CHECKS = tuple("module-ci / " + name for name in (
    "fmt", "clippy", "test", "coverage", "docs", "msrv", "supply-chain",
    *(f"{suite} ({runner}-latest)" for suite in ("module-e2e", "feature-tests")
      for runner in ("ubuntu", "macos", "windows"))))


def pinned(job, workflow):
    """Require a canonical reusable workflow pinned to a full commit SHA."""
    return bool(re.fullmatch(re.escape(PREFIX + workflow + "@") + r"[0-9a-f]{40}",
                             job.get("uses", "")))


def applies_to_main(ruleset):
    refs = ruleset.get("conditions", {}).get("ref_name", {})
    includes = refs.get("include", [])
    excludes = refs.get("exclude", [])
    return (any(x in includes for x in ("refs/heads/main", "~DEFAULT_BRANCH", "~ALL"))
            and not excludes)


def admin_bypass(ruleset):
    return any(x.get("actor_type") == "RepositoryRole" and x.get("actor_id") == 5
               and x.get("bypass_mode") == "always"
               for x in ruleset.get("bypass_actors", []))


def validate(repo, ci, release, rulesets):
    """Return all contract violations from already decoded API documents."""
    errors = []
    jobs = ci.get("jobs", {})
    if set(jobs) != {"module-ci"} or not pinned(jobs.get("module-ci", {}), "module-ci.yml"):
        errors.append("CI must contain only module-ci calling the pinned canonical workflow")
    release_name = "sdk-release" if repo == "tinybus" else "module-release"
    release_jobs = release.get("jobs", {})
    job = release_jobs.get(release_name, {})
    if set(release_jobs) - {"resolve", release_name} or not pinned(job, release_name + ".yml"):
        errors.append("release must call the pinned canonical " + release_name)
    if repo != "tinybus" and job.get("with", {}).get("distro-builds", True) is not True:
        errors.append("release must enable all 17 native and distro targets")
    active = [x for x in rulesets if x.get("enforcement") == "active" and x.get("target") == "branch"]
    if any(not admin_bypass(x) for x in active):
        errors.append("every active branch ruleset must allow administrator bypass always")
    protected = False
    for ruleset in active:
        if not applies_to_main(ruleset):
            continue
        rules = {x["type"]: x.get("parameters", {}) for x in ruleset.get("rules", [])}
        status = rules.get("required_status_checks", {})
        checks = {x.get("context") for x in status.get("required_status_checks", [])
                  if x.get("integration_id") == 15368}
        if (set(CHECKS) <= checks and status.get("strict_required_status_checks_policy") is True
                and {"pull_request", "deletion", "non_fast_forward"} <= rules.keys()
                and rules["pull_request"].get("required_review_thread_resolution") is True
                and admin_bypass(ruleset)):
            protected = True
    if not protected:
        errors.append("main lacks an active strict PR ruleset with all 13 GitHub Actions checks")
    return errors


def api(path):
    """Read GitHub metadata with an optional token; errors fail the audit."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "module-drift-check",
               "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request("https://api.github.com/repos/tinyhumansai/" + path, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def workflow(repo, name):
    result = api(repo + "/contents/.github/workflows/" + name + ".yml?ref=main")
    return yaml.safe_load(base64.b64decode(result["content"]))


def main():
    failed = False
    for repo in REPOS:
        try:
            ci, release = workflow(repo, "ci"), workflow(repo, "release")
            listed = api(repo + "/rulesets?includes_parents=true&per_page=100")
            if len(listed) == 100:
                raise ValueError("ruleset listing may be truncated")
            rulesets = [api(repo + "/rulesets/" + str(x["id"])) for x in listed]
            errors = validate(repo, ci, release, rulesets)
        except Exception as error:
            # Do not print request headers or tokens.
            errors = ["GitHub metadata audit failed: " + type(error).__name__]
        if errors:
            failed = True
            for error in errors:
                print(repo + ": " + error, file=sys.stderr)
        else:
            print(repo + ": shared callers and main rulesets pass")
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
