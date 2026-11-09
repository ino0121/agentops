"""Harness project settings made from aops.toml.

aops writes CLAUDE.md and AGENTS.md from the instructions file (the whole file, nothing added) and copies
each skill folder to where each harness looks for project skills. It only changes what it wrote: a file
or skill copy it did not make, or one someone edited by hand, is left alone and reported.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .hashing import folder_sha256
from .project import Project

# Marks of the block form older aops versions wrote; such a file is aops's and is rewritten whole.
OLD_START, OLD_END = "<!-- aops:start", "<!-- aops:end -->"
INSTRUCTION_FILES = ("CLAUDE.md", "AGENTS.md")
SKILL_DIRS = {"claude": ".claude/skills", "codex": ".agents/skills"}


@dataclass
class SyncResult:
    written: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)  # edited by hand, left as is


def sync(project: Project) -> SyncResult:
    result = SyncResult()
    if not project.is_project:
        return result
    state_file = project.work / "sync.json"
    state: dict[str, str] = json.loads(state_file.read_text()) if state_file.is_file() else {}
    new_state: dict[str, str] = {}

    source = project.root / project.instructions
    text = source.read_text(encoding="utf-8").strip() if source.is_file() else ""
    wanted_text = text + "\n" if text else ""
    for name in INSTRUCTION_FILES:
        path = project.root / name
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current == wanted_text or (current is None and not wanted_text):
            if current is not None:
                new_state[name] = _sha(current)
            continue
        ours = current is None or (name in state and _sha(current) == state[name]) or \
            (name not in state and OLD_START in current and OLD_END in current)
        if not ours:
            result.kept.append(name)  # edited by hand, or a file aops did not make
            if name in state:
                new_state[name] = state[name]
            continue
        if wanted_text:
            path.write_text(wanted_text, encoding="utf-8")
            new_state[name] = _sha(wanted_text)
        else:
            path.unlink()
        result.written.append(name)

    skills = {folder.name: folder for folder in project.skill_folders()}
    for target_dir in SKILL_DIRS.values():
        for alias, folder in skills.items():
            target = project.root / target_dir / alias
            rel = target.relative_to(project.root).as_posix()
            wanted = folder_sha256(folder)
            if target.is_dir():
                current = folder_sha256(target)
                if current == wanted:
                    new_state[rel] = wanted
                    continue
                if rel in state and current != state[rel]:
                    result.kept.append(rel)  # someone changed aops's copy
                    new_state[rel] = state[rel]
                    continue
                if rel not in state:
                    result.kept.append(rel)  # a folder aops did not make
                    continue
                shutil.rmtree(target)
            shutil.copytree(folder, target)
            new_state[rel] = wanted
            result.written.append(rel)
        for rel in [r for r in state if r.startswith(target_dir + "/") and r not in new_state]:
            stale = project.root / rel
            if stale.is_dir() and folder_sha256(stale) == state[rel]:
                shutil.rmtree(stale)  # a skill aops placed that was removed from aops.toml
                result.written.append(rel)

    project.work.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(new_state, indent=2, sort_keys=True))
    return result


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
