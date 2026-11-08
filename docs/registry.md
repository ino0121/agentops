# 레지스트리·승인 (dbx)

[README](../README.md) · [개요](overview.md) · [명령어](commands.md) · [프로젝트 폴더](project.md) · [레지스트리·승인](registry.md)

## 관리자 정책

"조직에 배포하려면 지켜야 할 형식"입니다. [`aops admin policy set`](commands.md#aops-admin)으로 올리면 Delta `policies`에 버전이 붙어 저장되고, validate Job·aops 서버·배포 Job이 같은 정책 버전을 읽습니다. 정책은 코드로만 검사합니다. 사람의 판단이 들어가는 곳은 승인 하나입니다.

| 항목 | 예 | 검사 시점 |
| --- | --- | --- |
| 필수 정보 | 소유 팀·담당자·데이터 등급·설명, 이름 규칙 | validate |
| 소스 | 등록된 버전, 금지 파일·비밀값 없음 | validate |
| 실행 구성 | 에이전트 서버 종류, 허용 하네스·SDK 버전 범위, 허용 Model service·MCP, 도구 권한 방식 | validate |
| 가드레일 | 데이터 등급별 필수 층·규칙·Gateway 정책, 레드팀 최소 통과율 | validate, 배포 Job |
| 평가 | 필수 평가 데이터셋, 최소 점수 | validate |
| 노코드 | Genie 정의 작성 규칙과 수준(오류·경고), 서비스 중요도별 벤치마크 정확도 기준 | validate |
| 운영 기록 | 배포 에이전트의 MLflow tracing·Apps telemetry | 배포 Job |
| 검증 방식 | `mandatory`(기본, 통과한 검사 필요)·`optional`·`exempt` | deploy |
| 승인 | 승인 그룹, 필요한 승인 수, 자기 승인 금지, 승인 방식(`required` 기본·`optional`·`auto`), 결재 채널(console 기본·외부 결재 확장) | deploy, console 화면 |
| 보안 등급 | 등급 목록, 등급별 공개 범위 | validate, promote |
| 재검증 | 정책이 바뀌면 이전 정책의 검사로 배포할 수 있는지 | deploy |

- 개발 단계의 기록·가드레일·평가 여부는 정책 항목이 될 수 없습니다. 정책은 등록·배포되는 결과물만 봅니다.
- 정책이 없으면 기본 정책(에이전트 서버 종류, 비밀값 검사, 검사 필수, 승인 1명, 결재 console, 보안 등급 3단계)을 씁니다.

## aops 서버

조직이 함께 쓰는 Databricks App 하나입니다. console 화면과 aops API(`/api/v1`)를 함께 엽니다. `aops admin setup`이 배포하고, `aops monitor --web`이 console 화면을 엽니다. Omnigent UI와 Custom Front도 이 API에 붙습니다.

- **레지스트리:** 에이전트, 버전, 검사 결과, 배포 위치
- **배포 요청·승인:** 승인자에게만 [승인]·[반려] 버튼이 보입니다. 배포 승인·반려는 aops API의 승인 경로로만 하고, 기본 화면이 console 화면입니다. custom 에디션에서는 Custom Front가 같은 API를 부릅니다
- **모니터링:** `aops monitor`와 같은 데이터
- **배포 이력**

## 권한과 가져오기

`promote`가 Databricks 권한을 주고, Databricks가 그 권한을 강제합니다. aops는 부여·회수 이력을 남깁니다.

| 종류 | `promote`가 주는 권한 | 가져오기 (`load`) |
| --- | --- | --- |
| 노코드 | 운영용 Genie Agent `CAN RUN` (공개 그룹은 배포 때 자동) | Genie Agent 링크 |
| 코드 | 운영 앱 `CAN USE` | 앱 링크 |
| 스킬 | UC Skill `READ_VOLUME` | 운영 버전을 내 PC 폴더로 |

스킬 기반은 시점마다 보이는 것이 다릅니다.

| 시점 | 목록 (`list`) | 버전 zip | UC Skill | `load` |
| --- | --- | --- | --- | --- |
| `register` 뒤 | 조직 사용자 모두 | 담당자·담당 팀만 | 만들어졌지만 읽는 사람 없음 | 담당자·담당 팀만 |
| `deploy` 뒤 | 같음 | 같음 | 운영 버전으로 바뀜 | 담당자·담당 팀 |
| `promote` 뒤 | 같음 | 같음 | 대상자에게 `READ_VOLUME` | 대상자는 운영 버전만 |

- 대상 그룹은 계정 그룹이어야 합니다. 작업 공간 그룹에는 Unity Catalog 권한을 줄 수 없습니다.
- 버전 zip이 든 볼륨에는 운영 전 버전도 있어서 대상자에게 권한을 주지 않습니다. `load`는 aops 서버가 요청한 사람의 권한을 확인하고 운영 버전만 내줍니다.
- 상위 객체의 권한은 아래로 내려옵니다. 레지스트리 스키마에는 사람에게 사용·조회 권한만 줍니다.

## 레지스트리 테이블

`[dbx] registry` 스키마의 Unity Catalog managed Delta 테이블입니다. 정의는 [`bundles/registry/tables.sql`](../bundles/registry/tables.sql)에 있고, 모든 테이블·컬럼에 한글 설명이 있으며 허용 값은 CHECK 제약으로 막습니다. 한 번에 바뀌어야 하는 상태(예: 요청 상태 변경과 승인 이력 추가)는 한 트랜잭션으로 묶습니다. 쓰기는 aops 서비스 주체만 하고, 사람에게는 조회 권한만 줍니다.

| 테이블 | 내용 | 쓰는 주체 |
| --- | --- | --- |
| `policies` | 관리자 정책과 버전 | `aops admin policy` |
| `agents` | 등록된 에이전트와 SPEC 정보 | `register` (노코드는 배포 Job) |
| `agent_versions` | 저장된 버전과 버전 zip 경로·해시 | `register` (노코드는 배포 Job) |
| `validations` | 검사 결과 (정책 버전, 점수, 단계별 결과) | validate Job |
| `deploy_requests` | 배포 요청과 상태 | `deploy`, 배포 Job |
| `approvals` | 승인·반려 이력 (추가만) | aops 서버 |
| `deployments` | 배포 결과 | 배포 Job |
| `production` | 운영 버전과 되돌림 이력 | 배포 Job |
| `agent_status` (뷰) | 에이전트별 최신 버전, 운영 버전, 최근 검사, 승인 대기 수 | aops 서버 |
