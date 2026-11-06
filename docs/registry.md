# 레지스트리·승인 (dbx)

[README](../README.md) · [개요](overview.md) · [명령어](commands.md) · [프로젝트 폴더](project.md) · [레지스트리·승인](registry.md)

## 관리자 정책

"조직에 올리고 배포하려면 지켜야 할 형식"입니다. [`aops admin policy set`](commands.md#aops-admin)으로 올리면 Delta `policies`에 버전이 붙어 저장되고, validate Job·`register`·배포 Job이 같은 정책 버전을 읽습니다. 정책은 코드로만 검사합니다. 사람의 판단이 들어가는 곳은 승인 하나입니다.

| 항목 | 예 | 검사 시점 |
| --- | --- | --- |
| 필수 정보 | 소유 팀·담당자·데이터 등급·설명, 이름 규칙 | validate |
| 소스 | 커밋된 소스, 금지 파일·비밀값 없음 | validate |
| 실행 구성 | 에이전트 서버 종류, 허용 하네스·SDK 버전 범위, 허용 Model service·MCP, 도구 권한 방식 | validate |
| 가드레일 | 데이터 등급별 필수 층·규칙·Gateway 정책, 레드팀 최소 통과율 | validate, 배포 Job |
| 평가 | 필수 평가 데이터셋, 최소 점수 | validate |
| 운영 기록 | 배포 에이전트의 MLflow tracing·Apps telemetry | 배포 Job |
| 승인 | 승인 그룹, 필요한 승인 수, 자기 승인 금지 | deploy, console 화면 |
| 재검증 | 정책이 바뀌면 이전 정책의 검증으로 배포할 수 있는지 | deploy |

- 개발 단계의 기록·가드레일·평가 여부는 정책 항목이 될 수 없습니다. 정책은 등록·배포되는 결과물만 봅니다.
- 정책이 없으면 기본 정책(에이전트 서버 종류, 커밋된 소스, 비밀값 검사, 승인 1명)을 씁니다.

## aops 서버

조직이 함께 쓰는 Databricks App 하나입니다. console 화면과 aops API(`/api/v1`)를 함께 엽니다. `aops admin setup`이 배포하고, `aops monitor --web`이 console 화면을 엽니다. Omnigent UI와 Custom Front도 이 API에 붙습니다.

- **레지스트리:** 에이전트, 버전, 검증 결과, 배포 위치
- **배포 요청·승인:** 승인자에게만 [승인]·[반려] 버튼이 보입니다. 배포 승인·반려는 aops API의 승인 경로로만 하고, 기본 화면이 console 화면입니다. custom 에디션에서는 Custom Front가 같은 API를 부릅니다
- **모니터링:** `aops monitor`와 같은 데이터
- **운영 지정 이력**

## 레지스트리 테이블

`[dbx] registry` 스키마의 Unity Catalog managed Delta 테이블입니다. 정의는 [`bundles/registry/tables.sql`](../bundles/registry/tables.sql)에 있고, 모든 테이블·컬럼에 한글 설명이 있으며 허용 값은 CHECK 제약으로 막습니다. 한 번에 바뀌어야 하는 상태(예: 요청 상태 변경과 승인 이력 추가)는 한 트랜잭션으로 묶습니다.

| 테이블 | 내용 | 쓰는 주체 |
| --- | --- | --- |
| `policies` | 관리자 정책과 버전 | `aops admin policy` |
| `agents` | 등록된 에이전트와 SPEC 정보 | `register` |
| `validations` | 검증 결과 (정책 버전, 점수, 단계별 결과) | validate Job |
| `agent_versions` | 등록된 버전과 소스 스냅샷 경로·해시 | `register` |
| `deploy_requests` | 배포 요청과 상태 | `deploy`, 배포 Job |
| `approvals` | 승인·반려 이력 (추가만) | aops 서버 |
| `deployments` | 배포 결과 | 배포 Job |
| `production` | 운영 버전 지정·되돌림 이력 | `promote` |
| `agent_status` (뷰) | 에이전트별 최신 버전, 운영 버전, 최근 검증, 승인 대기 수 | aops 서버 |
