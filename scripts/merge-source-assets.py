"""Merge flat source packages while preserving verified module artifacts."""
from pathlib import Path
import shutil
import sys

def merge(source, destination):
    """Validate every source entry before copying any files."""
    source, destination = Path(source), Path(destination)
    files = list(source.iterdir())
    if not files:
        raise ValueError("source artifact is empty")
    for entry in files:
        if entry.is_symlink() or not entry.is_file():
            raise ValueError("source artifacts must contain only top-level regular files")
        if (destination / entry.name).exists():
            raise ValueError("source artifact collides with module asset: " + entry.name)
    for entry in files:
        shutil.copyfile(entry, destination / entry.name)

if __name__ == "__main__":
    merge(*sys.argv[1:])
