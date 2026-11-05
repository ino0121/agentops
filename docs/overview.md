# aops 개요

[README](../README.md) · [개요](overview.md) · [명령어](commands.md) · [프로젝트 폴더](project.md) · [레지스트리·승인](registry.md)

## 개발부터 운영까지, 단계마다 쓰는 Databricks 기능

dbx 에디션 기준입니다. 1~4단계는 개발자가 자유롭게 쓰는 단계이고, 5단계(검증)부터 관리자 정책을 코드로 강제합니다.

| 단계 | aops가 하는 일 | 쓰는 Databricks 기능 | 명령 |
| --- | --- | --- | --- |
| 1. 만들기 | 프로젝트 폴더와 하네스 설정을 만들고, 개발 화면에서 하네스·모델·스킬·도구를 골라 에이전트를 구성합니다 | **Agent Bricks CLI·AgentKit**(`DurableAgentServer`): 배포 환경과 같은 에이전트 서버와 채팅 화면을 로컬에서 띄움 · **Unity Gateway Model services**: 모델 · **Databricks 제공 MCP·UC function·Genie**: 도구 · **Unity Gateway Skills**: 팀이 게시한 스킬 | `init` `dev` `add` |
| 2. 실험·비교 | 같은 질문을 하네스·모델·가드레일 구성별로 반복 실행해 답변·도구 사용률·토큰·지연을 나란히 비교합니다 | **MLflow 3 tracing**: 실행마다 trace를 Unity Catalog에 저장 · **Databricks Sandbox**: 격리된 실행 위치 · **Unity Gateway**: 요청·토큰 사용량 기록 | `run` |
| 3. 세션·메모리 | 하네스를 바꿔도 대화와 작업 맥락을 이어 붙이고, 사용자가 승인한 장기 메모리를 쌓습니다 | **Agent sessions·memory stores**(Lakebase): 세션과 메모리를 저장해 다른 PC·Sandbox에서 이어 감 | `session` `memory` |
| 4. 평가·가드레일 시험 | 원할 때 채점하고, 레드팀 사례로 가드레일 층별 차단·통과·오탐을 확인합니다 | **MLflow 평가**(`mlflow.genai.evaluate`, Databricks judge) · **UC 평가 데이터셋** · **Unity Gateway 서비스 정책**: 개인정보 가림·탈옥 판정 같은 가드레일 | `evaluate` |
| 5. 검증 | 커밋된 소스를 관리자 정책(형식·평가 점수·가드레일·호환 버전)으로 검사합니다. 강제가 시작되는 단계입니다 | **UC Volume**: 후보 소스 업로드 · **Lakeflow Jobs**(서버리스): 검사 실행 · **MLflow**: 평가 기록 · **Delta 테이블**: 정책(`policies`)과 검증 결과(`validations`) | `validate` |
| 6. 등록 | 검증을 통과한 소스만 버전으로 등록하고, 스킬을 팀에 게시합니다 | **UC registered model·MLflow LoggedModel**: 버전과 평가·trace 연결 · **UC Volume**: 소스 스냅샷 · **Delta 레지스트리**(`agents`·`agent_versions`) · **Unity Gateway Skills**: 스킬 게시 | `register` |
| 7. 승인·배포 | 배포 요청을 남기고, 승인 그룹이 승인하면 배포 Job이 배포합니다. 요청자는 스스로 승인할 수 없습니다 | **Delta 테이블 + multi-statement transaction**: 요청·승인 기록 · **governed tags**: 승인 태그 · **Databricks Apps**(console App): 승인 화면 · **Agent Runtime**(Databricks Apps)·**Runtime Store**(Lakebase): 배포와 중단 복구 · **MLflow tracing·Apps telemetry**: 운영 기록 | `deploy` |
| 8. 운영 | 운영 버전을 지정하거나 되돌리고, 사용량·예산·비용과 실행 중인 에이전트·MCP를 봅니다 | **Delta `production`·UC 모델 별칭**: 운영 버전 · **console App Monitor**: 운영 화면 · **system tables**(`system.ai_gateway.usage`·`system.billing.usage`·`system.access.audit`) · **Apps telemetry** · **예산 API** · **AI/BI 대시보드** | `promote` `monitor` |
| 준비 (관리자) | 조직 공통 레지스트리·검증 Job·배포 Job·console App을 한 번에 배포하고 정책 버전을 관리합니다 | **Declarative Automation Bundles**(`databricks.yml`) · **Unity Catalog 권한** | `admin` |

- Beta 기능: Agent Bricks CLI, Unity Gateway Skills, Agent sessions·memory, Databricks Sandbox, Unity Gateway 서비스 정책, Apps telemetry. 워크스페이스에서 꺼져 있으면 그 기능만 local 구현을 씁니다.
- local 에디션은 같은 1~4단계를 내 PC의 MLflow·SQLite·파일로 합니다(검증은 참고용, 등록·배포 없음). omni 에디션은 dbx에 Omnigent(세션 정본, CEL 정책, 관리형 에이전트)를 더합니다.

## aops가 지키는 원칙

- **하네스를 바꿔도 세션과 메모리가 이어집니다.** Claude Code 사용량이 떨어지면 Codex로 넘어가 같은 대화를 계속합니다. 세션·메모리의 정본은 aops가 갖고, 전환할 때 인계 파일·짧은 안내·기록 조회 도구(`aops-recall` MCP)로 맥락을 이어 붙입니다. 같은 하네스로 돌아가면 그 하네스의 세션을 그대로 재개합니다.
- **폴더 하나가 프로젝트입니다.** `aops init`이 만든 폴더 안에서 실험·비교·평가를 합니다. aops가 하네스 설정(`AGENTS.md`, `CLAUDE.md`, `.codex/`, `.claude/`)을 만들어 두므로, 터미널에서 `claude`·`codex`를 직접 실행해도 같은 지시·스킬·도구·기록이 적용됩니다.
- **개발은 자유, 등록부터 강제입니다.** 개발 중에는 아무것도 강제하지 않습니다. hook·기록·가드레일·평가는 사용자가 원해서 켜는 기능이고 언제든 끌 수 있습니다. 조직에 등록하고 배포할 때(`validate`·`register`·`deploy`)만 관리자가 정한 정책을 코드로 검사하고, 그 증거는 검증 Job이 직접 만듭니다.
- **Databricks 기능을 다시 만들지 않습니다.** 에이전트 서버, 채팅 화면, 기록 저장소, 작업 실행, 배포, 운영 화면 호스팅은 Databricks 기능을 그대로 씁니다. aops가 직접 만드는 것은 하네스 간 세션 인계, 배치 비교, 레지스트리·승인 흐름과 console App처럼 Databricks에 없는 부분뿐입니다.

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
