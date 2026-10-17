"""Merge an exact, preflight-selected source package bundle into release assets."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import tempfile


SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+([+-][0-9A-Za-z.-]+)?$")
TINYBUS_ARCHIVE = re.compile(r"^tinybus-source-[0-9a-f]{12}\.tar\.gz$")


def _regular_file(path: Path) -> bool:
    """Reject links and special files before accepting any source asset."""
    return not path.is_symlink() and path.is_file()


def merge(bundle: str, version: str, source: Path | str, destination: Path | str) -> None:
    """Merge only the exact TinyDocs crate and pinned TinyBus source archive."""
    if bundle != "tinydocs":
        raise ValueError("unsupported reviewed source bundle")
    if not SEMVER.fullmatch(version):
        raise ValueError("source bundle version is invalid")

    source = Path(source)
    destination = Path(destination)
    if source.is_symlink() or not source.is_dir():
        raise ValueError("source assets must be a real directory")
    if destination.is_symlink() or not destination.is_dir():
        raise ValueError("release assets must be a real directory")

    entries = list(source.iterdir())
    package_name = f"tinydocs-bus-{version}.crate"
    if (
        len(entries) != 2
        or any(not _regular_file(entry) for entry in entries)
        or {entry.name for entry in entries if entry.name.endswith(".crate")} != {package_name}
        or sum(bool(TINYBUS_ARCHIVE.fullmatch(entry.name)) for entry in entries) != 1
        or any(entry.name != package_name and not TINYBUS_ARCHIVE.fullmatch(entry.name) for entry in entries)
    ):
        raise ValueError("source bundle must contain the exact source asset set")
    if any((destination / entry.name).exists() or (destination / entry.name).is_symlink() for entry in entries):
        raise ValueError("source asset collides with a verified release asset")

    staging = Path(tempfile.mkdtemp(prefix=".tinydocs-source-assets-", dir=destination))
    try:
        for entry in entries:
            shutil.copyfile(entry, staging / entry.name)
        staged = list(staging.iterdir())
        if len(staged) != len(entries) or any(not _regular_file(entry) for entry in staged):
            raise ValueError("staged source bundle is incomplete")
        for entry in staged:
            os.replace(entry, destination / entry.name)
    finally:
        shutil.rmtree(staging)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    merge(args.bundle, args.version, args.source, args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
