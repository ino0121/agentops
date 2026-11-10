"""Project folder and the settings aops reads from aops.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_FILE = "aops.toml"

# Size of what is handed to the next harness, in tokens (design default).
DEFAULT_HANDOFF_TOKENS = {"codex": 2000, "claude": 4000}


@dataclass(frozen=True)
class Project:
    root: Path
    name: str | None = None
    edition: str = "local"
    harness: str = "claude"
    model: str | None = None
    instructions: str = "agent/instructions.md"
    skills: tuple[str, ...] = ("agent/skills/*",)
    user_settings: bool = False  # Claude: also read the user's own settings (~/.claude: MCP servers, hooks, CLAUDE.md)
    handoff_tokens: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_HANDOFF_TOKENS))
    dbx: dict[str, Any] = field(default_factory=dict)

    @property
    def runs(self) -> Path:
        """Records that stay with the project (sessions, raw harness events). Not committed."""
        return self.root / "runs"

    @property
    def work(self) -> Path:
        """Scratch files such as handoff files. Not committed."""
        return self.root / ".aops"

    @property
    def is_project(self) -> bool:
        return (self.root / CONFIG_FILE).is_file()

    def skill_folders(self) -> list[Path]:
        """Folders that hold a SKILL.md, from the `[agent] skills` patterns."""
        found: dict[Path, None] = {}
        for pattern in self.skills:
            for path in sorted(self.root.glob(pattern)):
                if (path / "SKILL.md").is_file():
                    found[path] = None
        return list(found)

    @classmethod
    def find(cls, start: Path | None = None) -> Project:
        """The nearest folder with aops.toml, or the start folder when there is none."""
        here = (start or Path.cwd()).resolve()
        for folder in (here, *here.parents):
            if (folder / CONFIG_FILE).is_file():
                return cls.load(folder)
        return cls(root=here)

    @classmethod
    def load(cls, root: Path) -> Project:
        data = tomllib.loads((root / CONFIG_FILE).read_text(encoding="utf-8"))
        project = data.get("project", {})
        agent = data.get("agent", {})
        session = data.get("session", {})
        tokens = {**DEFAULT_HANDOFF_TOKENS, **{k: int(v) for k, v in session.get("handoff_tokens", {}).items()}}
        skills = agent.get("skills", ["agent/skills/*"])
        return cls(
            root=root.resolve(),
            name=project.get("name"),
            edition=project.get("edition", "local"),
            harness=agent.get("harness", "claude"),
            model=agent.get("model"),
            instructions=agent.get("instructions", "agent/instructions.md"),
            skills=tuple([skills] if isinstance(skills, str) else skills),
            user_settings=bool(agent.get("user_settings", False)),
            handoff_tokens=tokens,
            dbx=dict(data.get("dbx", {})),
        )
