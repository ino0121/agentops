-- aops 레지스트리·승인 테이블
-- 조직이 함께 쓰는 에이전트 레지스트리, 검증 결과, 배포 요청·승인, 배포·운영 지정 이력, 관리자 정책.
-- 값 형식은 현재 aops 코드(v1 manifest.py·registry.py·governance.py)를 따른다.
--   SPEC 항목: SPEC.md 15개 필드와 허용 값 (예: data_sensitivity 공개|내부|대외비|개인정보)
--   ID: uuid4().hex (32자리 16진수), 해시: sha256 16진수 64자리, 사람: 계정 이메일, 시각: UTC
--   구조가 있는 상세 값: JSON 문자열 (*_json)
-- __SCHEMA__ 는 실행할 때 <catalog>.<schema> 로 바뀐다. 다시 실행해도 된다 (IF NOT EXISTS).
-- 모든 테이블은 catalog commits를 켠다. 여러 테이블을 BEGIN ATOMIC 한 트랜잭션으로 바꾸려면 필요하다.
-- PRIMARY KEY·FOREIGN KEY는 Unity Catalog 정보용 제약이라 강제되지 않는다. 허용 값은 CHECK로 강제한다.

CREATE TABLE IF NOT EXISTS __SCHEMA__.policies (
  policy_version INT NOT NULL COMMENT '정책 버전. 1부터 1씩 늘어난다',
  status STRING NOT NULL COMMENT '정책 상태. active(현재 적용, 하나만) | retired(이전 정책)',
  schema_version INT NOT NULL COMMENT '정책 파일(policy.toml) 형식 버전',
  approver_group STRING NOT NULL COMMENT '배포를 승인할 수 있는 워크스페이스 그룹 이름',
  approvals_required INT NOT NULL COMMENT '배포 한 건에 필요한 승인 수',
  self_approval_allowed BOOLEAN NOT NULL COMMENT '요청자·담당자 본인 승인 허용 여부. 운영은 false',
  allowed_servers ARRAY<STRING> NOT NULL COMMENT '허용하는 에이전트 서버 종류. 예: agentbricks (DurableAgentServer)',
  allowed_model_services ARRAY<STRING> NOT NULL COMMENT '에이전트가 쓸 수 있는 Gateway Model Service 이름 목록',
  min_correctness DOUBLE COMMENT 'validate 평가의 정답성 최소 점수 (0~1). SPEC success_criteria가 더 높으면 그 값을 쓴다',
  min_redteam_pass_rate DOUBLE COMMENT '레드팀 시험 최소 통과율 (0~1)',
  required_guardrails_json STRING COMMENT '데이터 민감도별 필수 가드레일 (JSON). 예: {"대외비": ["kr-pii", "jailbreak"]}',
  body STRING NOT NULL COMMENT '정책 원문 (policy.toml 내용 그대로)',
  created_by STRING NOT NULL COMMENT '정책을 올린 관리자 이메일',
  created_at TIMESTAMP NOT NULL COMMENT '정책을 올린 시각 (UTC)',
  CONSTRAINT policies_pk PRIMARY KEY (policy_version)
)
COMMENT '관리자 정책(배포 형식). aops admin policy set이 새 버전을 추가하고, validate·register·배포 Job이 active 정책을 읽는다'
TBLPROPERTIES ('delta.feature.catalogManaged' = 'supported');

CREATE TABLE IF NOT EXISTS __SCHEMA__.agents (
  agent_id STRING NOT NULL COMMENT '에이전트 ID. 소문자 kebab-case, 64자 이하 (SPEC agent_id)',
  name STRING NOT NULL COMMENT '표시 이름 (SPEC agent_name)',
  description STRING NOT NULL COMMENT '한 줄 설명. SPEC.md 본문 1번 섹션의 첫 문장',
  agent_type STRING NOT NULL COMMENT '에이전트 유형. skill-based-agent | code-based-agent | genie-agent (build_type에서 정해짐)',
  build_type STRING NOT NULL COMMENT '만드는 방식. skill | code | no-code (SPEC build_type)',
  serving_type STRING NOT NULL COMMENT '서빙 방식. apps | job | se | genie (SPEC serving_type)',
  origin STRING NOT NULL COMMENT '출처. 에이전트를 만든 플랫폼이나 조직을 적는다 (SPEC origin). 예: databricks, 사내 개발 플랫폼 이름',
  owner STRING NOT NULL COMMENT '담당자 이메일 (SPEC owner)',
  owner_group STRING NOT NULL COMMENT '담당 조직 (SPEC owner_group)',
  service_criticality STRING NOT NULL COMMENT '서비스 중요도. 상 | 중 | 하 (SPEC service_criticality)',
  data_sensitivity STRING NOT NULL COMMENT '데이터 민감도. 공개 | 내부 | 대외비 | 개인정보 (SPEC data_sensitivity)',
  security_level STRING NOT NULL COMMENT '보안 등급. 일반 | 강화 (SPEC security_level)',
  uc_permissions ARRAY<STRUCT<object: STRING, privilege: STRING>> NOT NULL COMMENT '필요한 UC 권한. object는 세 부분 이름(catalog.schema.object) (SPEC uc_permissions)',
  success_criteria_json STRING NOT NULL COMMENT '성공 기준 (JSON): correctness_min·relevance_min·safety_min(0~1), latency_p90_seconds(초) (SPEC success_criteria)',
  flagship_model BOOLEAN NOT NULL COMMENT '대표 모델 사용 선언 (SPEC flagship_model)',
  model_service STRING NOT NULL COMMENT '기본 Gateway Model Service 이름 (SPEC model_service)',
  lifecycle STRING NOT NULL COMMENT '생애 상태. active(사용 중) | retired(종료)',
  current_version STRING COMMENT '가장 최근에 등록한 버전. 운영 버전은 production 테이블에서 본다',
  spec_uri STRING COMMENT '최근 등록 버전의 소스 스냅샷 경로 (UC Volume)',
  created_at TIMESTAMP NOT NULL COMMENT '처음 등록한 시각 (UTC)',
  updated_at TIMESTAMP NOT NULL COMMENT '마지막으로 바뀐 시각 (UTC)',
  CONSTRAINT agents_pk PRIMARY KEY (agent_id)
)
COMMENT '조직 레지스트리에 등록된 에이전트와 SPEC 정보. aops register가 처음 등록할 때 만들고 새 버전마다 갱신한다'
TBLPROPERTIES ('delta.feature.catalogManaged' = 'supported');

CREATE TABLE IF NOT EXISTS __SCHEMA__.validations (
  validation_id STRING NOT NULL COMMENT '검증 ID. uuid4().hex',
  agent_id STRING NOT NULL COMMENT '검증한 에이전트 ID',
  candidate_version STRING NOT NULL COMMENT '후보 버전. major.minor.patch (SPEC agent_version)',
  artifact_sha256 STRING NOT NULL COMMENT '검사한 후보 소스 묶음(tar.gz)의 sha256',
  artifact_path STRING NOT NULL COMMENT '검증 대기 위치에 올린 후보 소스 경로 (UC Volume)',
  policy_version INT NOT NULL COMMENT '검사에 쓴 관리자 정책 버전',
  job_id BIGINT COMMENT 'validate Lakeflow Job ID',
  job_run_id BIGINT COMMENT 'validate Job 실행 ID',
  mlflow_run_id STRING COMMENT '평가 결과를 남긴 MLflow run ID (32자리 16진수)',
  status STRING NOT NULL COMMENT '검증 상태. running | passed | failed',
  checks_json STRING COMMENT '단계별 결과 (JSON 배열): format·evaluate·guardrails·compat 단계의 status·detail',
  correctness DOUBLE COMMENT '평가 정답성 평균 (0~1)',
  relevance DOUBLE COMMENT '평가 관련성 평균 (0~1)',
  safety DOUBLE COMMENT '평가 안전성 평균 (0~1)',
  latency_p90_seconds DOUBLE COMMENT '평가 실행의 응답 지연 p90 (초)',
  redteam_pass_rate DOUBLE COMMENT '레드팀 시험 통과율 (0~1)',
  requested_by STRING NOT NULL COMMENT 'aops validate를 실행한 사람 이메일',
  started_at TIMESTAMP NOT NULL COMMENT 'Job 시작 시각 (UTC)',
  finished_at TIMESTAMP COMMENT 'Job 종료 시각 (UTC). 실행 중이면 비어 있음',
  CONSTRAINT validations_pk PRIMARY KEY (validation_id),
  CONSTRAINT validations_policy_fk FOREIGN KEY (policy_version) REFERENCES __SCHEMA__.policies (policy_version)
)
COMMENT 'aops validate Job 결과. 같은 소스 해시로 현재 정책에서 통과한 행만 등록·배포의 근거가 된다. 개발 중 기록은 보지 않는다'
TBLPROPERTIES ('delta.feature.catalogManaged' = 'supported');

CREATE TABLE IF NOT EXISTS __SCHEMA__.agent_versions (
  agent_id STRING NOT NULL COMMENT '에이전트 ID',
  version STRING NOT NULL COMMENT '등록 버전. major.minor.patch, SPEC agent_version과 같다',
  semver_type STRING NOT NULL COMMENT '이전 등록 버전 대비 변경 크기. major | minor | patch',
  model_service STRING NOT NULL COMMENT '이 버전이 쓰는 Gateway Model Service 이름',
  artifact_path STRING NOT NULL COMMENT '소스 스냅샷 경로. /Volumes/<catalog>/<schema>/agent_artifacts/agents/<agent_id>/<version>/<sha256>.tar.gz',
  artifact_sha256 STRING NOT NULL COMMENT '소스 스냅샷(tar.gz)의 sha256',
  artifact_size BIGINT NOT NULL COMMENT '소스 스냅샷 크기 (바이트)',
  skill_names ARRAY<STRING> NOT NULL COMMENT '포함된 스킬 이름 목록',
  harness STRING COMMENT '실행 하네스. codex | claude. 코드 에이전트는 비어 있음',
  harness_version STRING COMMENT '고정한 하네스 버전 (uv.lock 기준)',
  sdk_versions MAP<STRING, STRING> COMMENT '고정한 상위 패키지 버전 (uv.lock 기준). 예: {"mlflow": "3.17.2"}',
  uv_lock_sha256 STRING COMMENT 'uv.lock 파일의 sha256',
  git_commit STRING COMMENT '등록한 소스의 git 커밋 (40자리)',
  uc_model_name STRING COMMENT 'UC registered model 이름 (catalog.schema.model)',
  uc_model_version INT COMMENT 'UC registered model 버전 번호',
  logged_model_id STRING COMMENT 'MLflow LoggedModel ID (m-로 시작)',
  validation_id STRING NOT NULL COMMENT '등록 근거가 된 통과 검증 ID',
  policy_version INT NOT NULL COMMENT '등록할 때 적용된 관리자 정책 버전',
  spec_json STRING NOT NULL COMMENT '등록 시점의 SPEC.md 15개 필드 전체 (JSON)',
  registered_by STRING NOT NULL COMMENT 'aops register를 실행한 사람 이메일',
  registered_at TIMESTAMP NOT NULL COMMENT '등록 시각 (UTC)',
  CONSTRAINT agent_versions_pk PRIMARY KEY (agent_id, version),
  CONSTRAINT agent_versions_agent_fk FOREIGN KEY (agent_id) REFERENCES __SCHEMA__.agents (agent_id),
  CONSTRAINT agent_versions_validation_fk FOREIGN KEY (validation_id) REFERENCES __SCHEMA__.validations (validation_id)
)
COMMENT '등록된 버전과 소스 스냅샷. 바꾸지 않는다. 통과한 검증이 있는 소스만 들어온다'
TBLPROPERTIES ('delta.feature.catalogManaged' = 'supported');

CREATE TABLE IF NOT EXISTS __SCHEMA__.deploy_requests (
  request_id STRING NOT NULL COMMENT '배포 요청 ID. uuid4().hex',
  agent_id STRING NOT NULL COMMENT '배포할 에이전트 ID',
  version STRING NOT NULL COMMENT '배포할 등록 버전',
  target_workspace STRING NOT NULL COMMENT '배포할 워크스페이스 주소',
  app_name STRING NOT NULL COMMENT '배포할 Databricks App 이름. agent-bricks-<이름>',
  validation_id STRING NOT NULL COMMENT '요청 근거가 된 통과 검증 ID',
  policy_version INT NOT NULL COMMENT '요청할 때 적용된 관리자 정책 버전',
  requested_by STRING NOT NULL COMMENT 'aops deploy를 실행한 사람 이메일',
  requested_at TIMESTAMP NOT NULL COMMENT '요청 시각 (UTC)',
  state STRING NOT NULL COMMENT '요청 상태. pending(승인 대기) | approved | rejected | deployed | failed',
  updated_at TIMESTAMP NOT NULL COMMENT '상태가 마지막으로 바뀐 시각 (UTC)',
  CONSTRAINT deploy_requests_pk PRIMARY KEY (request_id),
  CONSTRAINT deploy_requests_version_fk FOREIGN KEY (agent_id, version) REFERENCES __SCHEMA__.agent_versions (agent_id, version)
)
COMMENT '배포 요청. aops deploy가 만들고, console App 승인과 배포 Job이 상태를 바꾼다'
TBLPROPERTIES ('delta.feature.catalogManaged' = 'supported');

CREATE TABLE IF NOT EXISTS __SCHEMA__.approvals (
  approval_id STRING NOT NULL COMMENT '승인 기록 ID. uuid4().hex',
  request_id STRING NOT NULL COMMENT '대상 배포 요청 ID',
  approver STRING NOT NULL COMMENT '결정한 사람 이메일. 요청자·담당자와 달라야 한다',
  decision STRING NOT NULL COMMENT '결정. approved | rejected',
  reason STRING COMMENT '결정 사유. 반려할 때는 필수',
  decided_at TIMESTAMP NOT NULL COMMENT '결정 시각 (UTC)',
  CONSTRAINT approvals_pk PRIMARY KEY (approval_id),
  CONSTRAINT approvals_request_fk FOREIGN KEY (request_id) REFERENCES __SCHEMA__.deploy_requests (request_id)
)
COMMENT '배포 승인·반려 이력. 추가만 하고 고치지 않는다. console App만 쓴다'
TBLPROPERTIES ('delta.feature.catalogManaged' = 'supported');

CREATE TABLE IF NOT EXISTS __SCHEMA__.deployments (
  deployment_id STRING NOT NULL COMMENT '배포 기록 ID. uuid4().hex',
  request_id STRING NOT NULL COMMENT '승인된 배포 요청 ID',
  agent_id STRING NOT NULL COMMENT '배포한 에이전트 ID',
  version STRING NOT NULL COMMENT '배포한 등록 버전',
  app_name STRING NOT NULL COMMENT 'Databricks App 이름',
  app_url STRING COMMENT 'Databricks App 주소',
  apps_deployment_id STRING COMMENT 'Databricks Apps 배포 ID (32자리 16진수)',
  server STRING NOT NULL COMMENT '에이전트 서버 종류. agentbricks(DurableAgentServer)만 허용',
  guardrail_check_json STRING COMMENT '배포 시 가드레일 점검 결과 (JSON): 상태, 확인한 Gateway 정책, 레드팀 통과율',
  telemetry_enabled BOOLEAN NOT NULL COMMENT 'Apps telemetry(otel_* 테이블)를 켰는지',
  status STRING NOT NULL COMMENT '배포 상태. running | succeeded | failed',
  deploy_job_run_id BIGINT COMMENT '배포 Job 실행 ID',
  deployed_by STRING NOT NULL COMMENT '배포 Job을 실행한 주체 (서비스 주체 application ID 또는 이메일)',
  started_at TIMESTAMP NOT NULL COMMENT '배포 시작 시각 (UTC)',
  finished_at TIMESTAMP COMMENT '배포 종료 시각 (UTC)',
  CONSTRAINT deployments_pk PRIMARY KEY (deployment_id),
  CONSTRAINT deployments_request_fk FOREIGN KEY (request_id) REFERENCES __SCHEMA__.deploy_requests (request_id)
)
COMMENT '배포 Job 결과. 승인된 요청마다 한 번 이상 생긴다'
TBLPROPERTIES ('delta.feature.catalogManaged' = 'supported');

CREATE TABLE IF NOT EXISTS __SCHEMA__.production (
  transition_id STRING NOT NULL COMMENT '운영 지정 기록 ID. uuid4().hex',
  agent_id STRING NOT NULL COMMENT '에이전트 ID',
  version STRING NOT NULL COMMENT '운영으로 지정한 버전',
  previous_version STRING COMMENT '바로 전 운영 버전. 첫 지정이면 비어 있음',
  deployment_id STRING NOT NULL COMMENT '이 버전이 실제로 배포된 배포 기록 ID',
  action STRING NOT NULL COMMENT 'promote(새 버전 지정) | rollback(과거 운영 버전을 다시 지정)',
  is_current BOOLEAN NOT NULL COMMENT '현재 운영 버전인지. 에이전트마다 하나만 true',
  reason STRING COMMENT '지정·되돌림 사유',
  updated_by STRING NOT NULL COMMENT 'aops promote를 실행한 사람 이메일',
  updated_at TIMESTAMP NOT NULL COMMENT '지정 시각 (UTC)',
  CONSTRAINT production_pk PRIMARY KEY (transition_id),
  CONSTRAINT production_deployment_fk FOREIGN KEY (deployment_id) REFERENCES __SCHEMA__.deployments (deployment_id)
)
COMMENT '운영 버전 지정 이력. aops promote가 한 트랜잭션에서 새 행을 넣고 이전 행의 is_current를 끈다'
TBLPROPERTIES ('delta.feature.catalogManaged' = 'supported');

-- 허용 값 (CHECK)
ALTER TABLE __SCHEMA__.policies DROP CONSTRAINT IF EXISTS policies_status_ck;
ALTER TABLE __SCHEMA__.policies ADD CONSTRAINT policies_status_ck CHECK (status IN ('active', 'retired'));
ALTER TABLE __SCHEMA__.agents DROP CONSTRAINT IF EXISTS agents_id_ck;
ALTER TABLE __SCHEMA__.agents ADD CONSTRAINT agents_id_ck CHECK (agent_id RLIKE '^[a-z0-9]+(-[a-z0-9]+)*$' AND length(agent_id) <= 64);
ALTER TABLE __SCHEMA__.agents DROP CONSTRAINT IF EXISTS agents_type_ck;
ALTER TABLE __SCHEMA__.agents ADD CONSTRAINT agents_type_ck CHECK (agent_type IN ('skill-based-agent', 'code-based-agent', 'genie-agent'));
ALTER TABLE __SCHEMA__.agents DROP CONSTRAINT IF EXISTS agents_build_type_ck;
ALTER TABLE __SCHEMA__.agents ADD CONSTRAINT agents_build_type_ck CHECK (build_type IN ('skill', 'code', 'no-code'));
ALTER TABLE __SCHEMA__.agents DROP CONSTRAINT IF EXISTS agents_origin_ck;
ALTER TABLE __SCHEMA__.agents ADD CONSTRAINT agents_origin_ck CHECK (length(trim(origin)) > 0);
ALTER TABLE __SCHEMA__.agents DROP CONSTRAINT IF EXISTS agents_criticality_ck;
ALTER TABLE __SCHEMA__.agents ADD CONSTRAINT agents_criticality_ck CHECK (service_criticality IN ('상', '중', '하'));
ALTER TABLE __SCHEMA__.agents DROP CONSTRAINT IF EXISTS agents_sensitivity_ck;
ALTER TABLE __SCHEMA__.agents ADD CONSTRAINT agents_sensitivity_ck CHECK (data_sensitivity IN ('공개', '내부', '대외비', '개인정보'));
ALTER TABLE __SCHEMA__.agents DROP CONSTRAINT IF EXISTS agents_security_ck;
ALTER TABLE __SCHEMA__.agents ADD CONSTRAINT agents_security_ck CHECK (security_level IN ('일반', '강화'));
ALTER TABLE __SCHEMA__.agents DROP CONSTRAINT IF EXISTS agents_lifecycle_ck;
ALTER TABLE __SCHEMA__.agents ADD CONSTRAINT agents_lifecycle_ck CHECK (lifecycle IN ('active', 'retired'));
ALTER TABLE __SCHEMA__.validations DROP CONSTRAINT IF EXISTS validations_status_ck;
ALTER TABLE __SCHEMA__.validations ADD CONSTRAINT validations_status_ck CHECK (status IN ('running', 'passed', 'failed'));
ALTER TABLE __SCHEMA__.agent_versions DROP CONSTRAINT IF EXISTS agent_versions_semver_ck;
ALTER TABLE __SCHEMA__.agent_versions ADD CONSTRAINT agent_versions_semver_ck CHECK (semver_type IN ('major', 'minor', 'patch') AND version RLIKE '^(0|[1-9][0-9]*)[.](0|[1-9][0-9]*)[.](0|[1-9][0-9]*)$');
ALTER TABLE __SCHEMA__.agent_versions DROP CONSTRAINT IF EXISTS agent_versions_sha_ck;
ALTER TABLE __SCHEMA__.agent_versions ADD CONSTRAINT agent_versions_sha_ck CHECK (artifact_sha256 RLIKE '^[0-9a-f]{64}$');
ALTER TABLE __SCHEMA__.deploy_requests DROP CONSTRAINT IF EXISTS deploy_requests_state_ck;
ALTER TABLE __SCHEMA__.deploy_requests ADD CONSTRAINT deploy_requests_state_ck CHECK (state IN ('pending', 'approved', 'rejected', 'deployed', 'failed'));
ALTER TABLE __SCHEMA__.approvals DROP CONSTRAINT IF EXISTS approvals_decision_ck;
ALTER TABLE __SCHEMA__.approvals ADD CONSTRAINT approvals_decision_ck CHECK (decision IN ('approved', 'rejected') AND (decision = 'approved' OR reason IS NOT NULL));
ALTER TABLE __SCHEMA__.deployments DROP CONSTRAINT IF EXISTS deployments_server_ck;
ALTER TABLE __SCHEMA__.deployments ADD CONSTRAINT deployments_server_ck CHECK (server = 'agentbricks');
ALTER TABLE __SCHEMA__.deployments DROP CONSTRAINT IF EXISTS deployments_status_ck;
ALTER TABLE __SCHEMA__.deployments ADD CONSTRAINT deployments_status_ck CHECK (status IN ('running', 'succeeded', 'failed'));
ALTER TABLE __SCHEMA__.production DROP CONSTRAINT IF EXISTS production_action_ck;
ALTER TABLE __SCHEMA__.production ADD CONSTRAINT production_action_ck CHECK (action IN ('promote', 'rollback'));

CREATE OR REPLACE VIEW __SCHEMA__.agent_status (
  agent_id COMMENT '에이전트 ID',
  name COMMENT '표시 이름',
  agent_type COMMENT '에이전트 유형',
  owner COMMENT '담당자 이메일',
  owner_group COMMENT '담당 조직',
  data_sensitivity COMMENT '데이터 민감도',
  latest_version COMMENT '가장 최근 등록 버전',
  production_version COMMENT '현재 운영 버전',
  production_since COMMENT '현재 운영 버전으로 지정된 시각',
  last_validated_version COMMENT '가장 최근 검증한 후보 버전',
  last_validation_status COMMENT '가장 최근 검증 상태',
  pending_requests COMMENT '승인 대기 중인 배포 요청 수'
)
COMMENT 'console App 레지스트리 화면용 요약: 에이전트별 최신 등록 버전, 운영 버전, 최근 검증, 승인 대기 요청'
AS
WITH latest_validation AS (
  SELECT agent_id,
         max_by(candidate_version, started_at) AS last_validated_version,
         max_by(status, started_at) AS last_validation_status
  FROM __SCHEMA__.validations GROUP BY agent_id
),
pending AS (
  SELECT agent_id, count(*) AS pending_requests
  FROM __SCHEMA__.deploy_requests WHERE state = 'pending' GROUP BY agent_id
)
SELECT a.agent_id, a.name, a.agent_type, a.owner, a.owner_group, a.data_sensitivity,
       a.current_version,
       p.version,
       p.updated_at,
       v.last_validated_version, v.last_validation_status,
       coalesce(q.pending_requests, 0)
FROM __SCHEMA__.agents a
LEFT JOIN __SCHEMA__.production p ON p.agent_id = a.agent_id AND p.is_current
LEFT JOIN latest_validation v ON v.agent_id = a.agent_id
LEFT JOIN pending q ON q.agent_id = a.agent_id;
