# aops

AgentOps(`aops`)는 AI 에이전트를 만들고, 실험하고, 평가하고, 등록하고, 배포하고, 운영하는 전 과정을 관리하는 오픈소스 도구입니다. 실행 엔진은 직접 만들지 않습니다. Claude Code·Codex 같은 하네스와 Databricks·MLflow·Omnigent의 기능을 그대로 쓰고, 그 위를 하나의 프로젝트 정의(`aops.toml`)와 명령 체계로 묶습니다.

## 핵심

- **하네스를 바꿔도 세션과 메모리가 이어집니다.** Claude Code 사용량이 떨어지면 Codex로 넘어가 같은 대화를 계속합니다. 세션·메모리의 정본은 aops가 갖고, 전환할 때 인계 파일·짧은 안내·기록 조회 도구(`aops-recall` MCP)로 맥락을 이어 붙입니다. 같은 하네스로 돌아가면 그 하네스의 세션을 그대로 재개합니다.
- **폴더 하나가 프로젝트입니다.** `aops init`이 만든 폴더 안에서 실험·비교·평가를 합니다. aops가 하네스 설정(`AGENTS.md`, `CLAUDE.md`, `.codex/`, `.claude/`)을 만들어 두므로, 터미널에서 `claude`·`codex`를 직접 실행해도 같은 지시·스킬·도구·기록이 적용됩니다.
- **같은 질문을 구성별로 나란히 비교합니다.** 질문 × 구성(하네스·모델·가드레일) × 반복을 한 번에 돌려 답변, 도구·스킬 사용률, 토큰·지연을 표로 봅니다. 평가는 MLflow로 합니다.
- **가드레일을 켜고 끄고 시험하고, 에이전트와 함께 배포합니다.** 지시·규칙·판정 모델 세 층을 층별로 켜고 끄고, 레드팀 시험으로 차단·통과·오탐을 확인합니다.
- **개발은 자유, 등록부터 강제입니다.** 개발 중에는 아무것도 강제하지 않습니다. hook·기록·가드레일·평가는 사용자가 원해서 켜는 기능이고 언제든 끌 수 있습니다. 조직에 등록하고 배포할 때(`validate`·`register`·`deploy`)만 관리자가 정한 정책을 코드로 검사합니다.

## 사용자

| 사용자 | 하는 일 |
| --- | --- |
| 개발자 | 에이전트를 만들고 실험·비교·평가합니다. 원할 때 기록하고 원할 때 평가합니다 |
| 관리자 | 조직에 등록·배포되는 에이전트의 형식(정책)을 정하고, 배포를 승인하고, 운영 현황을 봅니다 |

## 에디션

뒤 에디션이 앞 에디션의 기능을 모두 포함합니다(local ⊂ dbx ⊂ omni). 기능별로 섞어 쓸 수도 있습니다. 예를 들어 워크스페이스에 Agent memory 프리뷰가 꺼져 있으면 메모리만 local 구현을 씁니다.

| | local | dbx | omni |
| --- | --- | --- | --- |
| 대상 | 개인·오프라인 실험 | Databricks를 쓰는 조직 | Omnigent를 쓰는 조직 |
| 실행 위치 | 내 PC | 내 PC 또는 Databricks Sandbox | Omnigent 세션 |
| 모델 연결 | 사용자가 하네스에 설정한 그대로 | Unity Gateway 경유 권장 | Omnigent → Unity Gateway |
| 기록·평가 | 원본 이벤트 + 프로젝트 MLflow | MLflow trace(Unity Catalog 저장) + Databricks MLflow Experiment | dbx와 같음 + Omnigent 세션 |
| 화면 | 로컬 개발 화면 | 로컬 개발 화면 + `agentbricks dev` 채팅 화면, 운영은 console App(Databricks App) | Omnigent 화면 안의 aops 화면 |
| 검증·승인·레지스트리 | 로컬 검사(강제 없음) | Lakeflow Job으로 검증, Unity Catalog Delta 테이블에 레지스트리·승인 기록 | dbx와 같음 |

## 아키텍처

![aops 아키텍처: 에디션 경계와 Databricks 기능의 역할](docs/architecture.png)

- **경계:** local은 내 PC, dbx는 local에 Databricks 워크스페이스를 더한 것, omni는 dbx에 Omnigent를 더한 것입니다.
- **① Unity Gateway:** 하네스와 배포된 에이전트가 모델·도구를 부르는 경로입니다. 사용량·예산·서비스 정책(가드레일)이 여기서 적용됩니다. dbx에서 권장하지만 강제하지 않습니다.
- **② 기록·세션:**
  - 개발 기록은 aops가 본인 MLflow Experiment에 남기고, 사용자가 끌 수 있습니다.
  - 운영 기록은 배포 Job이 배포된 에이전트에 MLflow tracing과 Apps telemetry를 켜서 남깁니다. 정책상 필수입니다.
  - 세션·메모리는 Lakebase 기반 Agent sessions·memory에 저장해 다른 PC에서도 이어 갑니다.
- **③ 검증 → 등록 → 승인 (강제 구간):** `validate`는 Lakeflow Job으로 돌고, 레지스트리·승인 기록은 Unity Catalog Delta 테이블에 남습니다. 등록할 때 스킬을 Unity Gateway Skills로 게시합니다.
- **④ 배포·운영:** 승인된 버전만 배포 Job이 Agent Runtime(Databricks Apps)에 배포합니다. 관리자는 console App에서 승인하고 운영 현황을 봅니다.

## Databricks 기능 (dbx)

| 단계 | Databricks 기능 | aops |
| --- | --- | --- |
| 만들기·로컬 실행 | Agent Bricks CLI(`init`·`dev`), AgentKit `DurableAgentServer` | `aops init`, `aops dev` |
| 모델 호출 | Unity Gateway Model services | 모든 하네스·에이전트의 기본 경로 (권장) |
| 도구 | Databricks 제공 MCP(`system.ai.*`), UC MCP service, UC function, Genie | `aops add tool` |
| 스킬 | Unity Gateway Skills (Beta) | `aops register`가 게시 |
| 세션·메모리 | Agent sessions·memory (Lakebase, Beta) | `aops session`, `aops memory` |
| 실행 격리 | Databricks Sandbox (Beta) | 배치 분산, 배포 에이전트의 셸 실행 |
| 실행 기록 | MLflow 3 trace (Unity Catalog 저장) | `aops session show`, 개발 화면 기록 탭 |
| 평가 | `mlflow.genai.evaluate`, UC 평가 데이터셋 | `aops evaluate`, `aops validate` |
| 검증 실행 | Lakeflow Jobs (서버리스) | `aops validate` |
| 등록 | UC registered model, MLflow LoggedModel, UC Volume | `aops register` |
| 레지스트리·승인 기록 | Unity Catalog managed Delta 테이블, multi-statement transaction, governed tags | `register`·`deploy`·`promote`, console App |
| 가드레일 | Unity Gateway 서비스 정책 (Beta) | `aops evaluate --suite redteam`, `[release.guardrails]` |
| 배포 | `agentbricks deploy` → Agent Runtime(Databricks Apps), Runtime Store(Lakebase) | `aops deploy` (승인 뒤 배포 Job) |
| 운영 화면 | Databricks Apps (console App), AI/BI 대시보드 | `aops monitor --web` |
| 운영 데이터 | `system.ai_gateway.usage`, `system.billing.usage`, `system.access.audit`, Apps telemetry, 예산 API | `aops monitor` |
| 배포 자동화 | Declarative Automation Bundles (`databricks.yml`) | `aops admin setup` |

## 프로젝트 폴더

`aops init`이 만드는 폴더입니다.

```text
my-agent/
├── pyproject.toml        aops 버전 고정 (uv 프로젝트)
├── uv.lock               aops + 하네스 + 상위 SDK의 정확한 버전
├── aops.toml             프로젝트 정의의 정본
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
├── memory/               장기 메모리 (Markdown 정본, 승인된 항목만)
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

## 명령어

명령은 16개입니다. 개발자가 매일 쓰는 것은 개발 명령 7개이고, 등록·배포는 dbx·omni에서만, `admin`은 관리자만 씁니다.

**개발 (모든 에디션, 강제 없음)**

| 명령 | 하는 일 | local | dbx | omni |
| --- | --- | :-: | :-: | :-: |
| [`aops init`](#aops-init) | 프로젝트 폴더 만들기 | ● | ● | ● |
| [`aops dev`](#aops-dev) | 개발 화면 (Chat·Batch·Evaluate·기록·메모리) | ● | ● | ● |
| [`aops run`](#aops-run) | 질문 하나, 또는 질문 파일 × 구성 × 반복(배치) | ● | ● | ● |
| [`aops evaluate`](#aops-evaluate) | 채점, 가드레일 시험, 이어가기 시험 | ● | ● | ● |
| [`aops session`](#aops-session) | 세션 보기·하네스 전환·가져오기·내보내기 | ● | ● | ● |
| [`aops memory`](#aops-memory) | 장기 메모리 보기·승인·삭제 | ● | ● | ● |
| [`aops add` · `remove`](#aops-add--remove) | 스킬·도구·MCP 추가·제거 | ● | ● | ● |

**등록·배포 (dbx·omni, 관리자 정책을 코드로 강제)**

| 명령 | 하는 일 | local | dbx | omni |
| --- | --- | :-: | :-: | :-: |
| [`aops configure`](#aops-configure) | Databricks·Omnigent 연결, 에디션 이전 | – | ● | ● |
| [`aops validate`](#aops-validate) | 등록 전 관리자 정책 검사 (강제 시작점) | 참고용 | ● | ● |
| [`aops register`](#aops-register) | 버전 등록 | – | ● | ● |
| [`aops deploy`](#aops-deploy) | 배포 요청 (승인 뒤 배포) | – | ● | ● |
| [`aops promote`](#aops-promote) | 운영 버전 지정 (되돌리기 포함) | – | ● | ● |

**운영·관리**

| 명령 | 하는 일 | local | dbx | omni |
| --- | --- | :-: | :-: | :-: |
| [`aops monitor`](#aops-monitor) | 사용량·예산·비용, 운영 중인 에이전트와 MCP | ● | ● | ● |
| [`aops doctor`](#aops-doctor) | 설치·버전·설정 점검 | ● | ● | ● |
| [`aops harness`](#aops-harness) | 하네스 설치·버전 관리 | ● | ● | ● |
| [`aops admin`](#aops-admin) | 조직 공통 자원 준비, 관리자 정책 | – | ● | ● |

### 개발

#### `aops init`

```bash
aops init <name> [--harness claude|codex] [--edition local|dbx|omni] [--no-ui]
```

- 프로젝트 폴더를 만들고 `uv sync`로 aops와 하네스를 설치합니다.
- 하네스 프로젝트 설정을 만듭니다. 이 폴더에서 `claude`·`codex`를 직접 실행해도 aops 설정과 기록이 적용됩니다. 하네스에서 이 폴더와 hook을 신뢰로 승인해야 하고, 회사 관리 설정이 프로젝트 hook을 막지 않아야 합니다.
- 예시 질문 3개와 기본 가드레일 규칙을 넣고, 끝나면 `aops dev`를 엽니다. `--no-ui`면 열지 않습니다.
- dbx: Agent Bricks 프로젝트(`agent.toml`, `runtime/`)와 Unity Catalog 이름·Gateway 기본값을 함께 만듭니다.
- omni: 같은 정의로 Omnigent 에이전트 YAML을 만듭니다.

#### `aops dev`

```bash
aops dev [--port <port>] [--host 127.0.0.1]
```

- 로컬 개발 화면을 띄웁니다. 탭은 Chat, Batch, Evaluate, 기록, 메모리입니다.
- 가드레일 층별 스위치, 하네스·모델·스킬·도구 선택도 이 화면에서 합니다. 바꾼 값은 `aops.toml`에 저장됩니다.
- dbx: 모델은 Unity Gateway Model services, 도구는 Databricks 제공 MCP·UC MCP service, 스킬은 Unity Gateway Skills, 기록은 MLflow trace에서 고르고 봅니다. 실행 위치로 내 PC 또는 Databricks Sandbox를 고릅니다.
- dbx의 Agent Bricks 프로젝트면 `agentbricks dev`도 함께 띄웁니다. 배포 환경과 같은 에이전트 서버(`DurableAgentServer`, 포트 8000)와 채팅 화면이 열리고, aops는 그 서버를 Batch·Evaluate 비교 대상으로 붙입니다.

#### `aops run`

```bash
aops run "<질문>" [--harness claude|codex] [--json]
aops run <questions.yaml> [--variants a,b] [--repeat N] [--concurrency N] [--json]
```

- **질문 하나:** 현재 세션에 이어 붙입니다. 다른 하네스로 실행하면 인계가 일어납니다.
- **질문 파일(배치):** 질문 × 구성 × 반복의 모든 칸을 실행하고 비교표를 냅니다. 칸마다 작업 폴더(git worktree)를 나눠 서로 파일을 덮어쓰지 않습니다.
  - 결과: 칸별 답변, 도구·스킬 사용, 가드레일 판정, 토큰·지연
  - 질문별 도구 사용률: 그 도구를 쓴 실행 수 / 반복 수. 호출 횟수도 따로 셉니다
- 구독 로그인은 한도가 개인 사용 기준이라, 구독 로그인 배치는 기본 동시 실행 수를 낮게 둡니다. 큰 배치는 API 키나 Unity Gateway를 권합니다.
- dbx: 칸 하나가 MLflow trace 하나입니다(`batch_id`·`variant`·`question_id` 태그).
- omni: Omnigent 세션으로 실행합니다.

#### `aops evaluate`

```bash
aops evaluate [dataset] [--scorers ...] [--variants a,b]
aops evaluate --suite redteam [--variants a,b] [--target deployed]
aops evaluate --suite handoff
```

- 원할 때 채점합니다. `mlflow.genai.evaluate`를 쓰고 결과는 항상 MLflow에 남깁니다.
- `--suite redteam`: 가드레일 시험입니다. `guardrails/redteam.yaml`의 사례로 층별 차단·통과·오탐을 표로 냅니다. `--variants`로 가드레일을 켠 구성과 끈 구성을 나란히 비교하고, `--target deployed`면 배포된 에이전트를 시험합니다.
- `--suite handoff`: 하네스를 바꿔도 맥락이 이어지는지 시험합니다.
- local: 프로젝트 MLflow(`runs/mlflow.db`)에 남깁니다. 판정 모델은 사용자가 지정합니다. 결과는 개발 화면 Evaluate 탭이나 `mlflow ui`로 봅니다.
- dbx: Databricks MLflow Experiment, UC 평가 데이터셋, Databricks judge를 씁니다. Unity Gateway 정책은 붙여야 할 정책 목록을 점검표로 보여 주고, 시험 질문으로 실제 차단되는지 확인합니다.
- omni: Omnigent 정책(CEL)으로 시험합니다.

#### `aops session`

```bash
aops session list
aops session show <id>
aops session switch --harness claude|codex
aops session import --from claude|codex [--session <id>]
aops session export <id>
```

- `list`·`show`: 세션과 구간(하네스·턴 범위), 전환 기록, 인계 내용, 턴별 도구 호출을 보여 줍니다.
- `switch`: 지금 세션을 다른 하네스로 옮깁니다. 같은 하네스·같은 버전으로 돌아가면 그 하네스의 세션을 재개하고, 아니면 인계로 이어 갑니다. 전환 시점은 사용자가 정합니다. aops는 자동으로 전환하지 않습니다.
- `import`: 하네스에 있던 세션 기록을 aops 세션으로 가져옵니다. 사용자가 실행할 때만 가져옵니다.
- `export`: 하네스와 무관한 형식(JSON)으로 내보냅니다.
- 터미널에서 직접 쓴 하네스 세션의 기록은 `[session] capture_terminal`(개발 화면 스위치)로 켜고 끕니다.
- dbx: 세션을 Agent sessions에 저장해 다른 PC나 Databricks Sandbox에서 이어 갑니다.

#### `aops memory`

```bash
aops memory list [--pending]
aops memory search "<검색어>"
aops memory accept <id>
aops memory forget <id>
```

- 하네스가 제안한 메모리 변경을 보고 승인(`accept`)하거나 지웁니다(`forget`). 승인한 항목만 장기 메모리가 됩니다(`[memory] review_writes`).
- local: `memory/`의 Markdown이 정본이고, 검색은 SQLite로 합니다.
- dbx: Agent memory stores에 저장하고, 저장소 단위로 권한을 줍니다.

#### `aops add` · `remove`

```bash
aops add skill <path>
aops add tool <name>
aops add mcp <name|url>
aops remove skill|tool|mcp <name>
```

- `skill`: `SKILL.md` 폴더를 `agent/skills/`에 넣고 하네스별 위치에 배치합니다. 형식은 추가할 때 검사합니다.
- `tool`·`mcp`: local은 로컬 MCP 서버를 `agent/tools.toml`에 등록합니다. dbx는 Databricks 제공 MCP(`system.ai.web_search`, `system.ai.dbsql`, 코드 실행 `system.ai.sandbox` 등), UC MCP service, UC function, Genie를 붙이고, Agent Bricks 프로젝트에는 `agentbricks tools add`로 반영합니다.
- 조직에 스킬을 게시하는 일은 `aops register`가 합니다.

### 등록·배포 (dbx·omni)

조직 배포는 항상 아래 순서로만 합니다. 내 PC에서 바로 조직 배포를 하지 않습니다.

```text
aops validate          후보 소스 업로드 → Lakeflow Job이 관리자 정책 검사 → validations
aops register 1.2.0    통과한 소스만 등록 → agent_versions, UC 모델 버전, Unity Gateway Skills 게시
aops deploy 1.2.0      배포 요청 → deploy_requests (승인 대기)
console App            승인 그룹이 [승인]·[반려] → approvals
배포 Job               승인 기록 재확인 → agentbricks deploy → deployments
aops promote 1.2.0     운영 버전 지정 → production
```

#### `aops configure`

```bash
aops configure [--edition dbx|omni] [--dry-run]
```

- Databricks CLI 프로필, 카탈로그·스키마·Experiment·Unity Gateway Model service·SQL warehouse를 확인해 `aops.toml [dbx]`에 저장합니다.
- 조직 공통 레지스트리·validate Job·console App이 있는지와 내 권한(읽기·요청·승인)을 확인합니다.
- 프리뷰(Sandbox, Unity Gateway Skills, Agent memory, 서비스 정책 등) 상태를 확인하고, 꺼진 기능은 local 구현을 쓰도록 `[providers]`를 제안합니다.
- **에디션 이전:** local 프로젝트에서 처음 실행하면 데이터를 옮길지 묻습니다. 세션은 Agent sessions로, 메모리는 memory stores로, 평가 기록은 Databricks Experiment로, 평가 데이터는 UC 평가 데이터셋으로 옮깁니다. `--dry-run`은 이전 계획과 옮길 수 없는 항목만 보여 줍니다. 옮기지 않아도 dbx 기능은 쓸 수 있습니다.
- omni: Omnigent에 로그인하고, dbx 프로젝트를 omni로 옮깁니다.

#### `aops validate`

```bash
aops validate [--local]
```

강제가 시작되는 첫 단계입니다. 조직 레지스트리에 올릴 후보를 관리자 정책으로 검사합니다.

- 커밋된 소스만 검사합니다. 커밋하지 않은 변경이 있으면 거부합니다.
- 후보 소스와 `uv.lock`을 묶어 UC Volume의 검증 대기 위치에 올리고, validate Lakeflow Job(서버리스)을 실행합니다. 올린 소스로 검사하므로 내 PC 상태와 무관합니다.
- 검사 단계 (항목과 기준은 [관리자 정책](#관리자-정책)에서 옵니다):
  1. **형식:** `[release]` 필수 항목, `SPEC.md`, `agent.toml`, 스킬 형식, 도구 권한, 허용된 Model service·MCP, 비밀값·금지 파일, 에이전트 서버 종류
  2. **평가:** `[release] evals` 데이터셋을 채점해 정책의 최소 점수와 비교
  3. **가드레일:** `[release.guardrails]`에 정책이 요구하는 층·규칙이 있는지, 레드팀 통과율
  4. **호환:** `uv.lock`의 하네스·SDK 버전이 허용 범위와 호환표에 있는지
  5. **기록:** MLflow run과 Delta `validations`에 단계별 결과, 소스 해시, 정책 버전을 남김
- 개발 중 기록에 기대지 않습니다. 개발 중 trace나 평가를 했는지는 보지 않고, 필요한 증거는 이 Job이 직접 만듭니다. 개발 중 hook을 꺼 둔 사람도 불리하지 않습니다.
- `--local`: 같은 단계를 내 PC에서 돌립니다. 미리 확인하는 용도라 결과는 참고용이고 승인 근거가 되지 않습니다. local 에디션에는 이 방식만 있습니다.

#### `aops register`

```bash
aops register [--version x.y.z]
```

- 같은 소스 해시로 현재 정책에서 통과한 검증이 있어야 등록됩니다.
- 검증 대기 위치의 소스 스냅샷을 버전 위치로 옮기고, UC registered model 버전과 MLflow LoggedModel을 만듭니다. 평가와 trace가 같은 model ID로 이어집니다.
- 스킬을 Unity Gateway Skills로 게시합니다. 팀의 코딩 에이전트는 `ug skills add`로 받아 씁니다.
- Delta `agents`·`agent_versions`에 소스 해시, git 커밋, 하네스·SDK 버전, UC 모델 버전, 근거 검증을 남깁니다. 버전은 `SPEC.md`의 `agent_version`과 같아야 합니다.
- omni: Omnigent 에이전트로도 등록합니다.

#### `aops deploy`

```bash
aops deploy [--version x.y.z] [--target <workspace>]
aops deploy --dev
```

- **요청:** Delta `deploy_requests`에 승인 대기로 남깁니다. 검증할 때의 정책 버전이 지금 정책과 다르면 다시 `validate`하라고 안내합니다.
- **승인:** console App에서 승인 그룹(`[dbx] approvers`)이 합니다. 요청자 본인은 승인할 수 없습니다.
- **배포:** 배포 Job(서비스 주체 실행)이 승인 기록을 다시 확인하고 `agentbricks deploy`로 Agent Runtime(Databricks Apps)에 배포합니다. 앱 이름은 `agent-bricks-<name>`입니다.
- **에이전트 서버:** AgentKit `DurableAgentServer`(`/api/invocations`)입니다. 요청 ID로 중복 실행을 막고, 동기·스트리밍·백그라운드 호출을 같은 실행으로 다룹니다. Runtime Store(Lakebase)가 실행 상태를 보관해 중단된 실행을 복구합니다.
- **가드레일:** 개발 중 스위치(`[guardrails]`)가 아니라 배포 구성(`[release.guardrails]`)이 배포 패키지에 들어갑니다. Unity Gateway 정책 점검 결과는 `deployments`에 남습니다.
- **운영 기록:** 배포된 에이전트에 MLflow tracing과 Apps telemetry를 켭니다. 정책에 따라 켜지는 조직 서비스의 기록이라, 에이전트를 쓰는 최종 사용자 쪽에서는 끌 수 없습니다.
- **`--dev`:** 승인 없이 본인 이름이 붙은 앱(`agent-bricks-dev-<user>-<name>`)으로 배포합니다. 세션·메모리처럼 배포해야만 시험할 수 있는 기능을 위한 개인 시험 배포입니다. 운영 후보로 남지 않고, `promote` 대상이 아니며, console App의 운영 목록에 나오지 않습니다.
- omni: Omnigent 관리형 에이전트로 게시하고 정책을 함께 넣습니다.

#### `aops promote`

```bash
aops promote <version> [--expected-version <현재 운영 버전>]
```

- 통과한 검증과 완료된 배포가 있는 버전만 운영으로 지정합니다. Delta `production`과 UC 모델 별칭을 한 번에 바꿉니다.
- `--expected-version`: 현재 운영 버전을 확인한 뒤 바꿉니다(동시 변경 방지).
- 되돌리기도 이 명령으로 합니다. 과거에 운영이었던 버전을 지정하면 됩니다.

### 운영·관리

#### `aops monitor`

```bash
aops monitor [--me | --all] [--watch] [--web]
aops monitor dashboard
```

개인 사용자와 관리자가 사용량·예산과 운영 중인 에이전트를 한곳에서 봅니다. 주 화면은 console App의 Monitor 화면이고(`--web`), CLI는 같은 데이터를 표로 보여 줍니다(`--watch`로 주기 갱신).

| 보기 | 개인 (`--me`, 기본) | 관리자 (`--all`) |
| --- | --- | --- |
| 사용량 | 내가 부른 요청·토큰·MCP 도구 호출 | 전체·사용자별·에이전트별 사용량 |
| 예산 | 내 예산 소진율 | 예산별 소진율, 차단·알림 기준 근접 |
| 비용 | 내가 만든 앱의 비용 | 앱·Model service별 비용 |
| 에이전트 | 내가 배포한 에이전트의 상태 | 실행 중인 에이전트 전체와 각자 쓰는 MCP |
| 품질·가드레일 | 내 에이전트 평가 점수, 내 기록의 차단 건수 | 배포된 에이전트별 점수, 정책별 차단 건수 |

- 출처: Unity Gateway 사용량(`system.ai_gateway.usage`), 비용(`system.billing.usage`), 감사 로그(`system.access.audit`), Apps telemetry, 예산 API, aops로 배포한 에이전트의 상태 경로(`/aops/status`). 항목마다 데이터 기준 시각을 함께 보여 줍니다. Databricks 문서 기준으로 사용량은 최대 1시간, 비용은 최대 12시간 늦게 반영됩니다.
- 관리자 보기는 등록·배포된 에이전트와 플랫폼 기록만 다룹니다. 개발자의 개발 중 기록은 그 사람이 고른 위치에 남고, aops는 그것을 관리자 보기에 모으지 않습니다.
- `dashboard`: 관리자 현황용 AI/BI 대시보드를 만들고 게시합니다.
- local: aops 이벤트로 하네스별 토큰·세션 사용량만 보여 줍니다. omni: Omnigent 세션 현황을 함께 보여 줍니다.

#### `aops doctor`

```bash
aops doctor
aops doctor --fix sync|migrate
```

- 설치 버전과 호환표, 인증, 프리뷰, 프로젝트·hook 신뢰 상태, 하네스 설정을 덮어쓰는 회사 관리 설정, Unity Gateway 주소·토큰이 함께 설정됐는지를 점검합니다.
- 결과는 알림입니다. 자동으로 고치지 않고, 사용자가 일부러 끈 것(hook, 기록, 가드레일)은 문제가 아니라 "꺼짐"으로 표시합니다.
- `--fix sync`: 하네스 설정을 지금 다시 만듭니다. 평소에는 aops 명령이 자동으로 합니다.
- `--fix migrate`: aops 저장 형식을 새 버전으로 옮깁니다. 평소에는 aops를 올린 뒤 처음 실행할 때 백업하고 묻습니다.

#### `aops harness`

```bash
aops harness list
aops harness install|use claude|codex[@<version>] [--untested]
aops harness upgrade claude|codex
```

- 호환표의 고정 버전을 uv로 설치·전환합니다. `--untested`로 검증 전 버전도 경고와 함께 쓸 수 있습니다.
- `upgrade`: 호환표의 다음 버전으로 올리고, 녹화된 출력 재생 시험을 통과하지 못하면 되돌립니다.
- dbx: `ug`(Unity Gateway CLI)로 하네스를 Unity Gateway에 연결합니다.

#### `aops admin`

```bash
aops admin setup [--apply]
aops admin policy set <policy.toml>
aops admin policy show|diff
```

관리자만 씁니다.

- `setup`: 조직 공통 자원을 번들(`databricks.yml`)로 한 번 배포합니다.
  - 레지스트리 스키마와 테이블
  - validate Job, 배포 Job (서버리스, 서비스 주체 실행)
  - console App과 Apps telemetry 대상 스키마
  - monitor용 뷰
  - 승인 태그 정책 (governed tags)
- 권한 부여는 미리 보여 주고 `--apply`일 때만 실행합니다.
- `policy`: 관리자 정책을 올리고 버전을 관리합니다.

### 관리자 정책

"조직에 올리고 배포하려면 지켜야 할 형식"입니다. `aops admin policy set`으로 올리면 Delta `policies`에 버전이 붙어 저장되고, validate Job·`register`·배포 Job이 같은 정책 버전을 읽습니다. 정책은 코드로만 검사합니다. 사람의 판단이 들어가는 곳은 승인 하나입니다.

| 항목 | 예 | 검사 시점 |
| --- | --- | --- |
| 필수 정보 | 소유 팀·담당자·데이터 등급·설명, 이름 규칙 | validate |
| 소스 | 커밋된 소스, 금지 파일·비밀값 없음 | validate |
| 실행 구성 | 에이전트 서버 종류, 허용 하네스·SDK 버전 범위, 허용 Model service·MCP, 도구 권한 방식 | validate |
| 가드레일 | 데이터 등급별 필수 층·규칙·Gateway 정책, 레드팀 최소 통과율 | validate, 배포 Job |
| 평가 | 필수 평가 데이터셋, 최소 점수 | validate |
| 운영 기록 | 배포 에이전트의 MLflow tracing·Apps telemetry | 배포 Job |
| 승인 | 승인 그룹, 필요한 승인 수, 자기 승인 금지 | deploy, console App |
| 재검증 | 정책이 바뀌면 이전 정책의 검증으로 배포할 수 있는지 | deploy |

- 개발 단계의 기록·가드레일·평가 여부는 정책 항목이 될 수 없습니다. 정책은 등록·배포되는 결과물만 봅니다.
- 정책이 없으면 기본 정책(에이전트 서버 종류, 커밋된 소스, 비밀값 검사, 승인 1명)을 씁니다.

### console App

조직이 함께 쓰는 Databricks App입니다. 따로 명령이 없고, `aops admin setup`이 배포하며 `aops monitor --web`이 엽니다.

- **레지스트리:** 에이전트, 버전, 검증 결과, 배포 위치
- **배포 요청·승인:** 승인자에게만 [승인]·[반려] 버튼이 보입니다. 배포 승인·반려는 이 화면에서만 합니다
- **모니터링:** `aops monitor`와 같은 데이터
- **운영 지정 이력**

### 레지스트리 테이블

`[dbx] registry` 스키마의 Unity Catalog managed Delta 테이블입니다. 정의는 [`bundles/registry/tables.sql`](bundles/registry/tables.sql)에 있고, 모든 테이블·컬럼에 한글 설명이 있으며 허용 값은 CHECK 제약으로 막습니다. 한 번에 바뀌어야 하는 상태(예: 요청 상태 변경과 승인 이력 추가)는 한 트랜잭션으로 묶습니다.

| 테이블 | 내용 | 쓰는 주체 |
| --- | --- | --- |
| `policies` | 관리자 정책과 버전 | `aops admin policy` |
| `agents` | 등록된 에이전트와 SPEC 정보 | `register` |
| `validations` | 검증 결과 (정책 버전, 점수, 단계별 결과) | validate Job |
| `agent_versions` | 등록된 버전과 소스 스냅샷 경로·해시 | `register` |
| `deploy_requests` | 배포 요청과 상태 | `deploy`, 배포 Job |
| `approvals` | 승인·반려 이력 (추가만) | console App |
| `deployments` | 배포 결과 | 배포 Job |
| `production` | 운영 버전 지정·되돌림 이력 | `promote` |
| `agent_status` (뷰) | 에이전트별 최신 버전, 운영 버전, 최근 검증, 승인 대기 수 | console App |

## 라이선스

[MIT](LICENSE)
