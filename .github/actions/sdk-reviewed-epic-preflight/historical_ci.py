"""Prove a historical pull-request association from immutable CI job evidence."""

from __future__ import annotations

import io
import re
import zipfile


MODULE_CI_PIN = "4adc1080fb495098e7af1aade82ed7e6e3c69bb7"
CHECKOUT_ACTION_PIN = "11d5960a326750d5838078e36cf38b85af677262"
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
MAX_LOG_BYTES = 16 * 1024 * 1024
MAX_LOG_FILES = 64


def verify_empty_association(api, workflow_run: dict, job: dict, pull: dict) -> None:
    """Accept an empty PR association only when immutable fmt logs bind this PR."""
    _verify_reusable_workflow_pin(workflow_run)
    archive = api.job_logs_archive(job["id"])
    text = _decode_archive(archive)
    synthetic_sha = _checkout_merge_sha(text, pull["number"])
    synthetic_parents = api.commit_parents(synthetic_sha)
    reviewed_parents = api.commit_parents(pull["merge_sha"])
    if synthetic_parents != reviewed_parents:
        raise ValueError("historical CI checkout parents did not match the reviewed merge")


def _verify_reusable_workflow_pin(workflow_run: dict) -> None:
    references = workflow_run.get("referenced_workflows")
    if not isinstance(references, list) or not references:
        raise ValueError("historical CI reusable workflow references were missing")
    expected_path = f"tinyhumansai/.github/.github/workflows/module-ci.yml@{MODULE_CI_PIN}"
    matching = []
    for reference in references:
        if not isinstance(reference, dict):
            raise ValueError("historical CI reusable workflow reference was malformed")
        path = reference.get("path")
        sha = reference.get("sha")
        if not isinstance(path, str) or not re.fullmatch(r"[0-9a-f]{40}", str(sha)):
            raise ValueError("historical CI reusable workflow reference was malformed")
        if path.startswith("tinyhumansai/.github/.github/workflows/module-ci.yml@"):
            if path != expected_path or sha != MODULE_CI_PIN:
                raise ValueError("historical CI reusable workflow pin was not trusted")
            matching.append(reference)
    if len(matching) != 1:
        raise ValueError("historical CI reusable workflow pin could not be proven")


def _decode_archive(archive: bytes) -> str:
    if not isinstance(archive, bytes) or not archive or len(archive) > MAX_ARCHIVE_BYTES:
        raise ValueError("historical CI job logs were missing or exceeded their size bound")
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
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


def _checkout_merge_sha(text: str, reviewed_pr: int) -> str:
    lines = text.splitlines()
    complete_job = [i for i, line in enumerate(lines) if "Complete job name: module-ci / fmt" in line]
    if len(complete_job) != 1:
        raise ValueError("historical fmt job identity was missing or ambiguous")
    setup_end = complete_job[0]
    setup_lines = lines[:setup_end]
    uses_matches = [
        (index, match.group(1))
        for index, line in enumerate(setup_lines)
        if (match := re.search(
            r"\bUses: tinyhumansai/\.github/\.github/workflows/module-ci\.yml@([0-9a-f]{40})\b",
            line,
        ))
    ]
    if len(uses_matches) != 1 or uses_matches[0][1] != MODULE_CI_PIN:
        raise ValueError("historical fmt job did not identify the pinned reusable workflow")
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
    if len(pull_refs) < 2 or any(reference != str(reviewed_pr) for reference in pull_refs):
        raise ValueError("historical fmt checkout did not resolve the exact reviewed PR merge ref")
    checkout_commands = [line for line in checkout_lines if re.search(r"\bgit checkout\b", line)]
    if len(checkout_commands) != 1 or not re.search(
        rf"\bgit checkout\b.*refs/remotes/pull/{reviewed_pr}/merge\s*$",
        checkout_commands[0],
    ):
        raise ValueError("historical fmt checkout command was ambiguous")
    fetch_commands = [line for line in checkout_lines if re.search(r"\bgit .*\bfetch\b", line)]
    if len(fetch_commands) != 1 or len(re.findall(
        rf"refs/remotes/pull/{reviewed_pr}/merge", fetch_commands[0]
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
    return resolved
