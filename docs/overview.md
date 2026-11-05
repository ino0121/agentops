# aops 개요

[README](../README.md) · [개요](overview.md) · [명령어](commands.md) · [프로젝트 폴더](project.md) · [레지스트리·승인](registry.md)

## 개발부터 운영까지

1~4단계는 자유롭게 쓰고, 5단계 검증부터 관리자 정책을 검사합니다. (dbx 에디션 기준)

| 단계 | 하는 일 | Databricks 기능 | 명령 |
| --- | --- | --- | --- |
| 1. 만들기 | 프로젝트·개발 화면 | Agent Bricks, Unity Gateway | `init` `dev` |
| 2. 실험 | 구성별 비교 실행 | MLflow tracing, Sandbox | `run` |
| 3. 세션 | 하네스 간 이어가기 | Agent sessions·memory | `session` |
| 4. 평가 | 채점·가드레일 시험 | MLflow 평가, 서비스 정책 | `evaluate` |
| 5. 검증 | 관리자 정책 검사 | Lakeflow Jobs | `validate` |
| 6. 등록 | 버전·스킬 등록 | Unity Catalog, Skills | `register` |
| 7. 배포 | 승인 후 배포 | console App, Agent Runtime | `deploy` |
| 8. 운영 | 운영 지정·모니터링 | system tables, telemetry | `monitor` |

단계별로 쓰는 기능:

- **만들기:** Agent Bricks CLI·AgentKit(`DurableAgentServer`)으로 배포와 같은 에이전트 서버를 로컬에서 띄웁니다. 모델은 Unity Gateway, 도구는 Databricks 제공 MCP·UC function·Genie를 씁니다.
- **실험:** 실행마다 MLflow trace를 Unity Catalog에 남기고, Databricks Sandbox에서 격리해 실행할 수 있습니다.
- **세션:** 세션과 메모리를 Agent sessions·memory(Lakebase)에 저장해 다른 PC에서도 이어 갑니다.
- **평가:** `mlflow.genai.evaluate`, UC 평가 데이터셋, Unity Gateway 서비스 정책(가드레일)을 씁니다.
- **검증:** 후보 소스를 UC Volume에 올리고 Lakeflow Job(서버리스)이 검사합니다. 결과는 MLflow와 Delta 테이블에 남습니다.
- **등록:** UC registered model 버전을 만들고, 스킬을 Unity Gateway Skills로 게시합니다.
- **배포:** console App(Databricks App)에서 승인하면 배포 Job이 Agent Runtime(Databricks Apps)에 배포합니다.
- **운영:** system tables(사용량·비용·감사), Apps telemetry, 예산 API로 운영 현황을 봅니다.

Agent Bricks CLI, Unity Gateway Skills, Agent sessions·memory, Sandbox, 서비스 정책, Apps telemetry는 Beta입니다. 꺼져 있으면 그 기능만 local 구현을 씁니다.

## 원칙

- **세션은 aops가 갖습니다.** 하네스를 바꾸면 인계 파일과 기록 조회 도구로 맥락을 이어 붙입니다.
- **폴더 하나가 프로젝트입니다.** 터미널에서 `claude`·`codex`를 직접 실행해도 같은 설정이 적용됩니다.
- **개발은 자유, 등록부터 검사합니다.** 기록·가드레일은 언제든 켜고 끌 수 있습니다.
- **Databricks 기능을 다시 만들지 않습니다.** 서버·저장·작업 실행·배포는 Databricks 기능을 그대로 씁니다.

## 사용자

- **개발자:** 에이전트를 만들고 실험·평가합니다.
- **관리자:** 정책을 정하고, 배포를 승인하고, 운영 현황을 봅니다.

## 에디션

뒤 에디션이 앞 에디션을 포함합니다(local ⊂ dbx ⊂ omni).

| | local | dbx | omni |
| --- | --- | --- | --- |
| 대상 | 개인 | Databricks 조직 | Omnigent 조직 |
| 실행 | 내 PC | 내 PC, Sandbox | Omnigent 세션 |
| 모델 | 하네스 설정 그대로 | Unity Gateway | Unity Gateway |
| 기록 | 로컬 MLflow | Databricks MLflow | dbx + Omnigent |
| 검증·배포 | 로컬 검사만 | Job 검증, 승인, 배포 | dbx와 같음 |
