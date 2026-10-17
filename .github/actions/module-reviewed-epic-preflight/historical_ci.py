"""Prove a historical pull-request association from immutable CI job evidence."""

from __future__ import annotations

import io
import re
import zipfile


CHECKOUT_ACTION_PIN = "11d5960a326750d5838078e36cf38b85af677262"
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
MAX_LOG_BYTES = 16 * 1024 * 1024
MAX_LOG_FILES = 64


def read_ci_checkout_proof(api, workflow_run: dict, job: dict, module_ci_pin: str) -> dict:
    """Identify the PR and synthetic commit selected by the pinned first checkout step."""
    _verify_reusable_workflow_pin(workflow_run, module_ci_pin)
    payload = api.job_logs(job["id"])
    text = _decode_job_logs(payload)
    pull_number, synthetic_sha = _checkout_merge_proof(text, module_ci_pin)
    synthetic_commit = api.commit_details(synthetic_sha)
    if synthetic_commit["parents"][1] != workflow_run["head_sha"]:
        raise ValueError("historical CI checkout head did not match the workflow run")
    return {"pull_number": pull_number, "synthetic_sha": synthetic_sha,
            "synthetic_commit": synthetic_commit}


def verify_ci_merge_provenance(api, workflow_run: dict, job: dict, pull: dict,
                               association: dict | None, checkout_proof: dict | None = None,
                               *, repository: str, epic_base: str,
                               module_ci_pin: str) -> None:
    """Bind the tested synthetic merge's ordered parents and tree to the released PR merge."""
    checkout_proof = checkout_proof or read_ci_checkout_proof(
        api, workflow_run, job, module_ci_pin
    )
    if checkout_proof["pull_number"] != pull["number"]:
        raise ValueError("historical fmt checkout did not resolve the exact reviewed PR")
    synthetic_commit = checkout_proof["synthetic_commit"]
    reviewed_commit = api.commit_details(pull["merge_sha"])
    if synthetic_commit["parents"] != reviewed_commit["parents"]:
        raise ValueError("historical CI checkout parents did not match the reviewed merge")
    if synthetic_commit["tree_sha"] != reviewed_commit["tree_sha"]:
        raise ValueError("historical CI checkout tree did not match the reviewed merge tree")
    if association is not None:
        _verify_event_association(
            association, pull, reviewed_commit["parents"], repository, epic_base
        )


def _verify_event_association(association: dict, pull: dict,
                              reviewed_parents: tuple[str, ...],
                              repository: str, epic_base: str) -> None:
    number = pull["number"]
    if association.get("url") != f"https://api.github.com/repos/{repository}/pulls/{number}":
        raise ValueError("workflow run pull request URL did not identify the canonical PR")
    base = association.get("base")
    head = association.get("head")
    if not isinstance(base, dict) or not isinstance(head, dict):
        raise ValueError("workflow run pull request base or head was missing")
    base_repo = base.get("repo")
    head_repo = head.get("repo")
    if (
        not isinstance(base_repo, dict)
        or base_repo.get("full_name") != repository
        or not isinstance(head_repo, dict)
        or head_repo.get("full_name") != pull["head_repository"]
    ):
        raise ValueError("workflow run pull request repository binding did not match")
    if (
        base.get("ref") != epic_base
        or base.get("sha") != reviewed_parents[0]
        or head.get("ref") != pull["head_ref"]
        or head.get("sha") != pull["head_sha"]
        or reviewed_parents[1] != pull["head_sha"]
    ):
        raise ValueError("workflow run pull request base or head binding did not match the reviewed merge")


def _verify_reusable_workflow_pin(workflow_run: dict, module_ci_pin: str) -> None:
    references = workflow_run.get("referenced_workflows")
    if not isinstance(references, list) or not references:
        raise ValueError("historical CI reusable workflow references were missing")
    expected_path = f"tinyhumansai/.github/.github/workflows/module-ci.yml@{module_ci_pin}"
    matching = []
    for reference in references:
        if not isinstance(reference, dict):
            raise ValueError("historical CI reusable workflow reference was malformed")
        path = reference.get("path")
        sha = reference.get("sha")
        if not isinstance(path, str) or not re.fullmatch(r"[0-9a-f]{40}", str(sha)):
            raise ValueError("historical CI reusable workflow reference was malformed")
        if path.startswith("tinyhumansai/.github/.github/workflows/module-ci.yml@"):
            if path != expected_path or sha != module_ci_pin:
                raise ValueError("historical CI reusable workflow pin was not trusted")
            matching.append(reference)
    if len(matching) != 1:
        raise ValueError("historical CI reusable workflow pin could not be proven")


def _decode_job_logs(payload: bytes) -> str:
    if not isinstance(payload, bytes) or not payload or len(payload) > MAX_ARCHIVE_BYTES:
        raise ValueError("historical CI job logs were missing or exceeded their size bound")
    if not zipfile.is_zipfile(io.BytesIO(payload)):
        try:
            return payload.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as error:
            raise ValueError("historical CI job logs were not valid UTF-8") from error
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
            names = [name for name in bundle.namelist() if not name.endswith("/")]
            if not names or len(names) > MAX_LOG_FILES:
                raise ValueError("historical CI job log archive had an invalid file set")
            chunks = []
            total = 0
            for name in names:
                info = bundle.getinfo(name)
                if info.file_size < 0 or total + info.file_size > MAX_LOG_BYTES:
                    raise ValueError("historical CI job logs exceeded their expanded size bound")
                payload = bundle.read(name)
                total += len(payload)
                chunks.append(payload.decode("utf-8", errors="strict"))
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError) as error:
        raise ValueError("historical CI job log archive was invalid") from error
    return "\n".join(chunks)


def _checkout_merge_proof(text: str, module_ci_pin: str) -> tuple[int, str]:
    lines = text.splitlines()
    complete_job = [
        i for i, line in enumerate(lines)
        if _runner_setup_message(line) == "Complete job name: module-ci / fmt"
    ]
    if len(complete_job) != 1:
        raise ValueError("historical fmt job identity was missing or ambiguous")
    setup_end = complete_job[0]
    setup_lines = lines[:setup_end]
    uses_records = [
        (index, _runner_setup_message(line)[len("Uses: "):])
        for index, line in enumerate(setup_lines)
        if (_runner_setup_message(line) or "").startswith("Uses: ")
    ]
    inputs_start = next(
        (index for index, line in enumerate(setup_lines) if "##[group] Inputs" in line),
        len(setup_lines),
    )
    expected_workflow = f"tinyhumansai/.github/.github/workflows/module-ci.yml@{module_ci_pin}"
    if (
        len(uses_records) != 1
        or uses_records[0][1] != expected_workflow
        or uses_records[0][0] >= inputs_start
    ):
        raise ValueError("historical fmt job did not identify the pinned reusable workflow")
    if any("##[group]Run " in line for line in lines[:setup_end]):
        raise ValueError("historical fmt job started an action before its runner identity")
    action_starts = [
        index for index, line in enumerate(lines[setup_end + 1:], start=setup_end + 1)
        if "##[group]Run " in line
    ]
    if not action_starts:
        raise ValueError("historical fmt job has no checkout step")
    first_start = action_starts[0]
    checkout_steps = [
        index for index in action_starts
        if re.search(r"##\[group\]Run actions/checkout@", lines[index])
    ]
    if len(checkout_steps) != 1 or checkout_steps[0] != first_start:
        raise ValueError("historical fmt checkout step was duplicated or out of order")
    if not re.search(rf"##\[group\]Run actions/checkout@{CHECKOUT_ACTION_PIN}\s*$", lines[first_start]):
        raise ValueError("historical fmt job did not start with the pinned checkout action")
    checkout_end = action_starts[1] if len(action_starts) > 1 else len(lines)
    checkout_lines = lines[first_start:checkout_end]
    pull_refs = re.findall(r"refs/remotes/pull/([0-9]+)/merge", "\n".join(checkout_lines))
    if len(pull_refs) < 2 or any(reference != pull_refs[0] for reference in pull_refs):
        raise ValueError("historical fmt checkout did not resolve one exact PR merge ref")
    pull_number = int(pull_refs[0])
    if pull_number < 1:
        raise ValueError("historical fmt checkout PR number was invalid")
    checkout_commands = [line for line in checkout_lines if re.search(r"\bgit checkout\b", line)]
    if len(checkout_commands) != 1 or not re.search(
        rf"\bgit checkout\b.*refs/remotes/pull/{pull_number}/merge\s*$",
        checkout_commands[0],
    ):
        raise ValueError("historical fmt checkout command was ambiguous")
    fetch_commands = [line for line in checkout_lines if re.search(r"\bgit .*\bfetch\b", line)]
    if len(fetch_commands) != 1 or len(re.findall(
        rf"refs/remotes/pull/{pull_number}/merge", fetch_commands[0]
    )) != 1:
        raise ValueError("historical fmt fetch did not identify one exact reviewed PR merge ref")
    log_indexes = [
        index for index, line in enumerate(checkout_lines)
        if re.search(r"\bgit log -1 --format=%H\s*$", line)
    ]
    if len(log_indexes) != 1:
        raise ValueError("historical fmt checkout did not identify one resolved merge SHA")
    command_index = log_indexes[0]
    resolved = None
    for line in checkout_lines[command_index + 1:]:
        if "[command]" in line:
            break
        match = re.search(r"\b([0-9a-f]{40})\s*$", line)
        if match:
            resolved = match.group(1)
            break
    if resolved is None:
        raise ValueError("historical fmt checkout merge SHA was missing")
    return pull_number, resolved


def _runner_setup_message(line: str) -> str | None:
    match = re.fullmatch(
        r"(?:module-ci / fmt\tUNKNOWN STEP\t)?[0-9]{4}-[0-9]{2}-[0-9]{2}T"
        r"[0-9:.]+Z (.*)",
        line,
    )
    return None if match is None else match.group(1)
