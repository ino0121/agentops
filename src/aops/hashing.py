"""Content hashes that match across the registry, UC skills and runtime checks.

A folder hash is SHA-256 over every file in path order as ``relative path \\0 length \\0 content``.
The combined skills hash is SHA-256 over ``alias:hash`` lines sorted by alias.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def folder_sha256(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        data = path.read_bytes()
        digest.update(path.relative_to(folder).as_posix().encode())
        digest.update(b"\0")
        digest.update(str(len(data)).encode())
        digest.update(b"\0")
        digest.update(data)
    return digest.hexdigest()


def skills_sha256(skills: dict[str, str]) -> str:
    """`skills` maps alias to folder hash."""
    lines = "\n".join(f"{alias}:{skills[alias]}" for alias in sorted(skills))
    return hashlib.sha256(lines.encode()).hexdigest()
