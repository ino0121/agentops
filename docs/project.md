# 프로젝트 폴더와 aops.toml

[README](../README.md) · [개요](overview.md) · [명령어](commands.md) · [프로젝트 폴더](project.md) · [레지스트리·승인](registry.md)

`aops init`이 만드는 폴더입니다.

```text
my-agent/
├── pyproject.toml        aops 버전 고정 (uv 프로젝트)
├── uv.lock               aops + 하네스 + 상위 SDK의 정확한 버전
├── aops.toml             프로젝트 정의 (모든 설정의 기준)
├── SPEC.md               에이전트 정보 (등록할 때 쓰는 15개 필드)
├── agent/
│   ├── instructions.md   하네스 공통 지시
│   ├── skills/<name>/SKILL.md
│   └── tools.toml        MCP 서버·도구 선언
├── guardrails/
│   ├── rules.toml        2층 규칙
│   └── redteam.yaml      가드레일 시험 사례
├── evals/
│   ├── questions.yaml    배치 질문
│   └── datasets/         정답이 있는 평가 데이터
├── memory/               장기 메모리 (Markdown, 승인된 항목만)
├── genie/agent.json      (노코드) Genie Agent 정의 (Databricks에서 가져온 것)
├── AGENTS.md  CLAUDE.md  .codex/  .claude/  .agents/skills/
│                         하네스 프로젝트 설정 (aops가 aops.toml에서 만든다)
├── agent.toml            (dbx) Agent Bricks 프로젝트 선언
├── runtime/              (dbx) DurableAgentServer 진입점
├── databricks.yml        (dbx) 번들
├── runs/                 세션·원본 이벤트·local MLflow (git 제외)
└── .aops/                인계 파일, 배치 칸 작업 폴더 (git 제외)
```

```toml
# aops.toml
config_version = 1

[project]
name = "price-helper"
edition = "local"              # local | dbx | omni

[agent]
harness = "claude"             # 기본 하네스: claude | codex
model = "<model-name>"         # dbx에서는 Unity Gateway Model service 이름
instructions = "agent/instructions.md"
skills = ["agent/skills/*"]
tools = "agent/tools.toml"

[guardrails]                   # 개발 중 시험용 스위치. 언제든 끄고 켤 수 있다
instructions = true            # 1층 지시
rules = "log"                  # 2층 규칙: off | log | enforce
gateway = false                # Unity Gateway 서비스 정책 (dbx 이상)
judge = "off"                  # 3층 판정 (Gateway를 쓰지 않을 때)

[session]
capture_terminal = true        # 터미널에서 직접 쓴 하네스 세션도 기록
handoff_tokens = { codex = 2000, claude = 4000 }   # 인계 안내·파일 크기
summarizer = "rules"           # rules | next-harness | <model-name>

[memory]
long_term = true
review_writes = true           # 메모리 변경은 사용자 승인 후 반영
harness_memory = "keep"        # 하네스 자체 메모리: keep | import | off

[[variants]]                   # 배치 비교용 구성. 지정하지 않은 값은 위 설정을 따른다
name = "claude-guard-on"
rules = "enforce"

[[variants]]
name = "codex-guard-off"
harness = "codex"
rules = "off"

[release]                      # 등록·배포할 구성. dbx·omni에서 validate가 관리자 정책으로 검사한다
spec = "SPEC.md"
evals = "evals/datasets/main"

[release.guardrails]           # 운영에서 켜 둘 가드레일. 개발 중 [guardrails]와 별개
instructions = true
rules = "enforce"
gateway_policies = ["pii", "jailbreak"]

[dbx]
profile = "my-workspace"
catalog = "main"
schema = "agents"
experiment = "/Users/<me>/aops/price-helper"   # 개발 기록은 기본으로 본인 폴더
gateway = true                 # 모델 호출을 Unity Gateway로 (권장)
registry = "main.aops"         # 레지스트리·승인 테이블 스키마 (조직 공통)
validate_job = "aops-validate"
console_app = "aops-console"
approvers = "group:agent-approvers"   # 배포 승인 그룹. 요청자 본인은 승인할 수 없다
```

`AGENTS.md`·`.claude/` 같은 하네스 설정은 `aops.toml`에서 만들어지는 생성물입니다. `aops.toml`이 바뀌면 다음 aops 명령이 다시 만들고, 사람이 직접 고친 부분이 있으면 덮어쓰기 전에 차이를 보여 주고 묻습니다. 사용자가 지우거나 끈 hook은 다시 넣지 않습니다.
