# aops v2

AgentOps(`aops`)는 에이전트의 전 라이프사이클을 관리하는 오픈소스 도구입니다. 자체 실행 엔진 없이 기존 하네스(Codex, Claude Code 등)와 플랫폼 SDK를 감싸는 래퍼를 목표로 합니다.

## 상태

v2는 처음부터 다시 만들고 있습니다. 지금 들어 있는 것은 아래 두 가지입니다.

| 구성 | 내용 |
| --- | --- |
| `aops` CLI 골격 | `aops --version`만 있습니다 (`src/codex_agentops/`) |
| 레지스트리 테이블 정의 | `bundles/registry/tables.sql`: Databricks Unity Catalog Delta 테이블 8개와 요약 뷰 1개 |

## 레지스트리 테이블

조직이 함께 쓰는 에이전트 레지스트리와 배포 승인 기록입니다. 모든 테이블·컬럼에 한글 설명이 있고, 허용 값은 CHECK 제약으로 막습니다.

| 테이블 | 내용 |
| --- | --- |
| `policies` | 관리자 정책(배포 형식). 버전마다 한 행 |
| `agents` | 등록된 에이전트와 SPEC 정보 |
| `validations` | 검증 결과 (정책 버전, 점수, 단계별 결과) |
| `agent_versions` | 등록된 버전과 소스 스냅샷 경로·해시 |
| `deploy_requests` | 배포 요청과 상태 |
| `approvals` | 승인·반려 이력 (추가만) |
| `deployments` | 배포 결과 |
| `production` | 운영 버전 지정·되돌림 이력 |
| `agent_status` (뷰) | 에이전트별 최신 버전, 운영 버전, 최근 검증, 승인 대기 수 |

만들기:

```bash
cp .env.e2e.example .env.e2e      # Databricks CLI 프로필, <catalog>.<schema>, SQL warehouse ID
python3 scripts/run_sql.py bundles/registry/tables.sql
```

- 필요: Databricks CLI 로그인, 서버리스 SQL warehouse, 대상 스키마에 테이블을 만들 권한
- 다시 실행해도 됩니다 (`IF NOT EXISTS`). 여러 테이블을 한 트랜잭션으로 바꿀 수 있도록 catalog commits(`delta.feature.catalogManaged`)를 켭니다.

## 개발

```bash
uv run pytest
```

v1(마지막 버전 1.3.0)은 [`v1.3.0` 태그](https://github.com/jeeHwon/agentops/tree/v1.3.0)에 있습니다. v2는 v1 코드를 가져오지 않습니다.
