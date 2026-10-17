"""Shared synthetic API and merge-history fixtures for SDK release tests."""

def reviewed_release_fixture(verifier):
    class Api:
        def __init__(self):
            self.repository = "tinyhumansai/tinybus"
            self.tags = {"v0.1.7": sha(5)}
            self.main = sha(1)
            self.pulls = {}
            self.associations = {}
            self.reviews = {}
            self.threads = {}
            self.checks = {}
            self.workflow_runs = {}
            self.workflow_jobs = {}

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

        def workflow_runs_for_commit(self, commit):
            return self.workflow_runs.get(commit, [])

        def jobs_for_workflow_run(self, run_id, attempt):
            return self.workflow_jobs[(run_id, attempt)]

    class Git:
        def __init__(self, parents):
            self.parents = parents
            self.tag_sha = sha(5)
            self.main_sha = sha(1)

        def parents_of(self, commit):
            return self.parents[commit]

        def is_ancestor_of(self, commit, head):
            return commit == head

    base = sha(1)
    merges = {72: sha(2), 74: sha(3), 73: sha(4), 75: sha(5)}
    heads = {72: sha(12), 74: sha(13), 73: sha(14), 75: sha(15)}
    parents = {
        merges[72]: (base, heads[72]),
        merges[74]: (merges[72], heads[74]),
        merges[73]: (merges[74], heads[73]),
        merges[75]: (merges[73], heads[75]),
    }
    api = Api()
    api.associations = {merge: [number] for number, merge in merges.items()}
    for number, merge in merges.items():
        api.pulls[number] = {
            "number": number,
            "state": "closed",
            "merged": True,
            "merge_commit_sha": merge,
            "base": {
                "ref": "epic/8056-modules-wiring",
                "repo": {"full_name": "tinyhumansai/tinybus"},
            },
            "head": {
                "sha": heads[number],
                "ref": "feature",
                "repo": {"full_name": "senamakel/tinybus"},
            },
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
                "head_sha": heads[number],
                "check_suite": {"id": 2000 + number},
            }
            for index, name in enumerate(verifier.REQUIRED_CHECKS)
        ]
        run_id = 1000 + number
        api.workflow_runs[heads[number]] = [{
            "id": run_id,
            "workflow_id": verifier.CI_WORKFLOW_ID,
            "path": ".github/workflows/ci.yml",
            "event": "pull_request",
            "status": "completed",
            "conclusion": "success",
            "head_sha": heads[number],
            "head_branch": "feature",
            "head_repository": {"full_name": "senamakel/tinybus"},
            "repository": {"full_name": "tinyhumansai/tinybus"},
            "pull_requests": [{"number": number}],
            "run_number": 100 + number,
            "run_attempt": 1,
            "check_suite_id": 2000 + number,
        }]
        api.workflow_jobs[(run_id, 1)] = [
            {
                "id": 3000 + index,
                "name": name,
                "run_id": run_id,
                "run_attempt": 1,
                "head_sha": heads[number],
                "status": "completed",
                "conclusion": "success",
                "check_run_url": (
                    f"https://api.github.com/repos/tinyhumansai/tinybus/check-runs/{index}"
                ),
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
    fake.tag_sha = merges[75]
    fake.parents = parents
    fake.associations = api.associations
    fake.reviews = api.reviews
    fake.threads = api.threads
    fake.checks = api.checks
    fake.workflow_runs = api.workflow_runs
    fake.workflow_jobs = api.workflow_jobs
    fake.checked_heads = api.checked_heads
    return fake


def sha(value):
    return f"{value:040x}"

