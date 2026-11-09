"""Harness project settings made from aops.toml.

aops writes the instructions into a marked block of CLAUDE.md and AGENTS.md and copies each skill
folder to where each harness looks for project skills. It never removes what it did not write:
text outside the marked block stays, and only skills aops placed are updated or removed. A skill
copy someone edited by hand is left alone and reported.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .hashing import folder_sha256
from .project import Project

START = "<!-- aops:start · made from aops.toml, aops rewrites this block -->"
END = "<!-- aops:end -->"
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
    for name in INSTRUCTION_FILES:
        if _write_block(project.root / name, text):
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


def _write_block(path: Path, text: str) -> bool:
    block = f"{START}\n{text}\n{END}" if text else ""
    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    if START in old and END in old:
        head, rest = old.split(START, 1)
        tail = rest.split(END, 1)[1]
        new = (head + block + tail) if block else (head.rstrip() + tail).strip() + "\n"
    elif block:
        new = (old.rstrip() + "\n\n" + block + "\n") if old.strip() else block + "\n"
    else:
        return False
    if new == old:
        return False
    path.write_text(new, encoding="utf-8")
    return True
