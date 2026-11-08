"""`aops init`: a new agent folder from the skill template."""

from __future__ import annotations

import re
from pathlib import Path

from .project import CONFIG_FILE, Project
from .sync import sync

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")

AOPS_TOML = """\
config_version = 1

[project]
name = "{name}"
edition = "{edition}"              # local | dbx | omni | custom

[agent]
harness = "{harness}"              # claude | codex
instructions = "agent/instructions.md"
skills = ["agent/skills/*"]

[session]
handoff_tokens = {{ codex = 2000, claude = 4000 }}
"""

DBX_TOML = """
[dbx]
profile = ""                   # Databricks CLI 프로필
server = ""                    # aops 서버 주소 (https://<app>.databricksapps.com)
"""

SPEC_MD = """\
---
agent_id: {name}
name: {name}
build_type: skill
owner:
owner_group:
service_criticality: medium    # low | medium | high
data_sensitivity: internal     # public | internal | confidential | personal
security_level: general
description: 부가세가 포함된 금액을 계산하고 설명한다
---

# {name}

이 에이전트가 하는 일, 쓰는 사람, 주의할 점을 적습니다.
"""

INSTRUCTIONS_MD = """\
당신은 가격 계산을 돕는 에이전트입니다.

- 금액 계산은 `vat-calculator` 스킬의 규칙을 따릅니다.
- 답은 한국어로, 표를 먼저 보여 주고 계산 과정을 짧게 덧붙입니다.
"""

SKILL_MD = """\
---
name: vat-calculator
description: 한국 부가가치세(10%)를 계산한다. 공급가액, 부가세, 합계 금액을 묻는 질문에 쓴다.
---

# 부가세 계산

1. 부가세 = 공급가액 × 10%. 원 단위 미만은 버린다.
2. 합계 = 공급가액 + 부가세.
3. 합계만 주어지면 공급가액 = 합계 ÷ 1.1(원 미만 버림), 부가세 = 합계 − 공급가액.
4. 답은 `공급가액 | 부가세 | 합계` 표로, 천 단위 쉼표를 붙여 보여 준다.
"""

QUESTIONS_YAML = """\
questions:
  - id: q1
    text: 공급가액 12,000원의 부가세와 합계는?
  - id: q2
    text: 합계 55,000원이면 공급가액과 부가세는 얼마야?
  - id: q3
    text: 공급가액 9,999원짜리 3개를 사면 합계는?
"""

GITIGNORE = "runs/\n.aops/\n"


def create(parent: Path, name: str, *, harness: str = "claude", edition: str = "local") -> Project:
    if not NAME.match(name):
        raise ValueError("name must be lowercase letters, digits and hyphens (up to 63 characters)")
    root = parent / name
    if (root / CONFIG_FILE).exists():
        raise ValueError(f"{root} is already an aops project")
    files = {
        CONFIG_FILE: AOPS_TOML.format(name=name, harness=harness, edition=edition) + (DBX_TOML if edition != "local" else ""),
        "SPEC.md": SPEC_MD.format(name=name),
        "agent/instructions.md": INSTRUCTIONS_MD,
        "agent/skills/vat-calculator/SKILL.md": SKILL_MD,
        "evals/questions.yaml": QUESTIONS_YAML,
        ".gitignore": GITIGNORE,
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    project = Project.load(root)
    sync(project)
    return project
