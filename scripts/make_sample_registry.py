"""Build sample registry data from real agent sources.

Creates source archives the same way the v1 registry does (sorted files, mtime 0,
gzip without a file name), then writes bundles/registry/sample_data.sql whose hashes,
sizes, paths and skill names match those archives. IDs are uuid5(...).hex so a rerun
produces the same rows.

    python scripts/make_sample_registry.py <archive-output-dir>

Workspace, schema and people come from .env.e2e (AOPS_E2E_SCHEMA, AOPS_E2E_HOST,
AOPS_E2E_WORKSPACE_ID, AOPS_E2E_DEVELOPER, AOPS_E2E_APPROVER). Agent sources are the
v1 samples and the Agent Bricks demo checked out next to this repository. The generated
SQL contains those values, so it is not committed.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import tomllib
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
sys.path.insert(0, str(ROOT / "scripts"))
from run_sql import load_env  # noqa: E402

ENV = load_env(ROOT / ".env.e2e")
CATALOG, SCHEMA = ENV["AOPS_E2E_SCHEMA"].split(".")
VOLUME = "agent_artifacts"
VOLUME_ROOT = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"
HOST = ENV["AOPS_E2E_HOST"]
WORKSPACE_ID = ENV["AOPS_E2E_WORKSPACE_ID"]
DEVELOPER = ENV["AOPS_E2E_DEVELOPER"]
APPROVER = ENV["AOPS_E2E_APPROVER"]
NAMESPACE = uuid.UUID("6f1c3a52-6d0e-4c49-9a59-2f5a3c1b7e01")

CODE_AGENT_SPEC = """---
agent_id: agentops-code
agent_name: AgentOps Code Agent
agent_version: "1.0.0"
build_type: code
serving_type: apps
origin: databricks
owner: __DEVELOPER__
owner_group: AI-CoE
service_criticality: 하
data_sensitivity: 내부
security_level: 일반
uc_permissions: []
success_criteria:
  correctness_min: 0.8
  relevance_min: 0.9
  safety_min: 1.0
  latency_p90_seconds: 30
flagship_model: false
model_service: system.ai.gpt-5-nano
---

## 1. 목적

AgentOps의 Skill-based Agent와 Registry 설계를 공개 자료 기준으로 설명합니다.
"""

SOURCES = {
    "release-sample-agent": WORKSPACE / "agentops/samples/release-agent",
    "price-helper-agent": WORKSPACE / "agentops/samples/price-helper-agent",
    "agentops-code": WORKSPACE / "backup/agentops-bricks-demo",
}


def rid(*parts: str) -> str:
    return uuid.uuid5(NAMESPACE, "/".join(parts)).hex


def skill_files(root: Path) -> list[Path]:
    files = [root / "AGENTS.md", root / "README.md", root / "SPEC.md"]
    for directory in (root / "skills", root / "agents"):
        if directory.exists():
            files += sorted(p for p in directory.rglob("*") if p.is_file() and p.name != ".DS_Store")
    if (root / ".aops/release.json").exists():
        files.append(root / ".aops/release.json")
    return files


def code_files(root: Path) -> list[Path]:
    files = [root / name for name in ("AGENTS.md", "README.md", "AGENTKIT_CONTRACT.md", "CHAT_APP.md",
                                       "agent.toml", "app.yaml", "pyproject.toml", "uv.lock")]
    for directory in ("agent", "runtime", "ui", "tests"):
        files += sorted(p for p in (root / directory).rglob("*")
                        if p.is_file() and "__pycache__" not in p.parts and p.name != ".DS_Store")
    return files


def archive(root: Path, files: list[Path], overrides: dict[str, bytes]) -> tuple[bytes, dict[str, str]]:
    contents = {p.relative_to(root).as_posix(): p.read_bytes() for p in files}
    contents.update(overrides)
    checksums, output = {}, io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as tar:
            for relative in sorted(contents):
                data = contents[relative]
                checksums[relative] = hashlib.sha256(data).hexdigest()
                info = tarfile.TarInfo(relative)
                info.size, info.mtime, info.mode = len(data), 0, 0o644
                tar.addfile(info, io.BytesIO(data))
    return output.getvalue(), checksums


def spec_fields(spec_text: str) -> dict:
    front = spec_text.split("---", 2)[1]
    fields: dict = {}
    criteria: dict = {}
    for line in front.splitlines():
        if not line.strip():
            continue
        key, _, value = line.strip().partition(":")
        value = value.strip().strip('"')
        if line.startswith("  "):
            criteria[key] = float(value)
        elif key == "success_criteria":
            fields[key] = criteria
        elif key == "uc_permissions":
            fields[key] = []
        elif key == "flagship_model":
            fields[key] = value == "true"
        else:
            fields[key] = value
    return fields


def git_commit(path: Path) -> str | None:
    result = subprocess.run(["git", "-C", str(path), "log", "-1", "--format=%H", "--", "."],
                            capture_output=True, text=True, check=False)
    return result.stdout.strip() or None


def locked_versions(lock: Path, names: list[str]) -> dict[str, str]:
    packages = tomllib.loads(lock.read_text(encoding="utf-8")).get("package", [])
    found = {p["name"]: p["version"] for p in packages if p.get("name") in names}
    return {name: found[name] for name in names if name in found}


def q(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def arr(values: list[str]) -> str:
    return "array(" + ", ".join(q(v) for v in values) + ")" if values else "CAST(array() AS ARRAY<STRING>)"


def mp(values: dict[str, str]) -> str:
    return "map(" + ", ".join(f"{q(k)}, {q(v)}" for k, v in values.items()) + ")" if values else "CAST(map() AS MAP<STRING, STRING>)"


def ts(value: str) -> str:
    return f"TIMESTAMP '{value}'"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    out = Path(sys.argv[1])
    built = {}
    for agent_id, root in SOURCES.items():
        if agent_id == "agentops-code":
            spec_text = CODE_AGENT_SPEC.replace("__DEVELOPER__", DEVELOPER)
            data, sums = archive(root, code_files(root), {"SPEC.md": spec_text.encode()})
        else:
            spec_text = (root / "SPEC.md").read_text(encoding="utf-8").replace("owner@example.com", DEVELOPER)
            data, sums = archive(root, skill_files(root), {"SPEC.md": spec_text.encode()})
        sha = hashlib.sha256(data).hexdigest()
        spec = spec_fields(spec_text)
        built[agent_id] = {
            "sha": sha, "size": len(data), "spec": spec,
            "skills": sorted({p.split("/")[1] for p in sums if p.startswith("skills/")}),
            "commit": git_commit(root) if agent_id != "agentops-code" else None,
            "description": re.search(r"## 1\..*?\n\n(.+?)[\n]", spec_text.split("---", 2)[2] + "\n", re.S),
        }
        staging = out / "staging" / agent_id / f"{sha}.tar.gz"
        staging.parent.mkdir(parents=True, exist_ok=True)
        staging.write_bytes(data)
        if agent_id != "price-helper-agent":
            version_path = out / "agents" / agent_id / spec["agent_version"] / f"{sha}.tar.gz"
            version_path.parent.mkdir(parents=True, exist_ok=True)
            version_path.write_bytes(data)

    readme_first = {
        "release-sample-agent": "문서의 핵심 내용과 후속 행동을 요약하고 결과를 검증합니다.",
        "price-helper-agent": "가격·부가세와 단위를 계산합니다.",
        "agentops-code": "AgentOps의 Skill-based Agent와 Registry 설계를 공개 자료 기준으로 설명합니다.",
    }
    code_lock = SOURCES["agentops-code"] / "uv.lock"
    code_sdk = locked_versions(code_lock, ["databricks-agentbricks", "databricks-agents", "databricks-langchain",
                                           "databricks-sdk", "langgraph", "mlflow"])
    uv_lock_sha = hashlib.sha256(code_lock.read_bytes()).hexdigest()

    policy_body = (
        'policy_version = 1\nschema_version = 1\n\n[release]\nrequired = ["agent_id", "agent_name", "agent_version", '
        '"owner", "owner_group", "data_sensitivity", "success_criteria", "model_service"]\n\n[runtime]\n'
        'servers = ["agentbricks"]\nmodel_services = ["system.ai.gpt-5-6-sol", "system.ai.gpt-5-nano", '
        '"system.ai.claude-sonnet-5-5"]\n\n[evaluate]\nmin_correctness = 0.8\n\n[guardrails]\nmin_redteam_pass_rate = 0.95\n'
        '"대외비" = ["kr-pii", "jailbreak"]\n"개인정보" = ["kr-pii", "jailbreak"]\n\n[operations]\ntracing = true\n'
        'apps_telemetry = true\n\n[approval]\ngroup = "agent-approvers"\nrequired = 1\nself_approval = false\n'
        'revalidate_on_policy_change = true\n'
    )
    sql = [
        "-- 시험용 샘플 데이터. scripts/make_sample_registry.py가 실제 에이전트 소스에서 만든다.",
        f"-- 소스 묶음(tar.gz)은 같은 스크립트가 만들고 {VOLUME_ROOT}에 올린다.",
        "-- 검증 점수·Job 실행 ID·배포 기록은 시험용 값이다 (실제 Job·앱 실행 결과가 아님).",
        "",
        "INSERT INTO __SCHEMA__.policies VALUES",
        f"  (1, 'active', 1, 'agent-approvers', 1, false, array('agentbricks'), "
        f"array('system.ai.gpt-5-6-sol', 'system.ai.gpt-5-nano', 'system.ai.claude-sonnet-5-5'), 0.8, 0.95, "
        f"{q(json.dumps({'대외비': ['kr-pii', 'jailbreak'], '개인정보': ['kr-pii', 'jailbreak']}, ensure_ascii=False))}, "
        f"{q(policy_body)}, {q(DEVELOPER)}, {ts('2026-11-02 00:10:00')});",
        "",
    ]

    plan = {
        "release-sample-agent": dict(status="passed", start="2026-11-02 00:20:00", end="2026-11-02 00:31:00",
                                     scores=(0.86, 0.93, 1.0, 8.4, 0.97), job_run=846193027514288),
        "price-helper-agent": dict(status="failed", start="2026-11-02 00:40:00", end="2026-11-02 00:52:00",
                                   scores=(0.84, 0.91, 1.0, 41.2, 0.92), job_run=846193027519356),
        "agentops-code": dict(status="passed", start="2026-11-02 01:00:00", end="2026-11-02 01:14:00",
                              scores=(0.88, 0.92, 1.0, 5.7, 0.96), job_run=846193027523041),
    }
    validation_rows = []
    for agent_id, p in plan.items():
        b = built[agent_id]
        version = b["spec"]["agent_version"]
        correctness, relevance, safety, latency, redteam = p["scores"]
        crit = b["spec"]["success_criteria"]
        guard_ok = redteam >= 0.95
        checks = [
            {"step": "format", "status": "passed", "detail": "SPEC.md 15개 필드, 금지 파일·비밀값 없음"},
            {"step": "evaluate", "status": "passed",
             "detail": f"correctness {correctness} >= {crit['correctness_min']}, relevance {relevance}, "
                       f"safety {safety}, latency_p90 {latency}s <= {crit['latency_p90_seconds']}s"},
            {"step": "guardrails", "status": "passed" if guard_ok else "failed",
             "detail": f"레드팀 통과율 {redteam} {'>=' if guard_ok else '<'} 0.95"
                       + ("" if guard_ok else " (주민등록번호 형식 질문 2건 통과)")},
            {"step": "compat", "status": "passed",
             "detail": "openai-codex 0.163.0 허용" if agent_id != "agentops-code"
             else f"databricks-agentbricks {code_sdk.get('databricks-agentbricks')} 허용, server = agentbricks"},
        ]
        b["validation_id"] = rid("validation", agent_id, version)
        staging_path = f"{VOLUME_ROOT}/staging/{agent_id}/{b['sha']}.tar.gz"
        validation_rows.append(
            f"  ({q(b['validation_id'])}, {q(agent_id)}, {q(version)}, {q(b['sha'])}, "
            f"{q(staging_path)}, 1, 1093812675342210, {p['job_run']}, "
            f"{q(rid('mlflow-run', agent_id, version))}, {q(p['status'])}, {q(json.dumps(checks, ensure_ascii=False))}, "
            f"{correctness}, {relevance}, {safety}, {latency}, {redteam}, {q(DEVELOPER)}, {ts(p['start'])}, {ts(p['end'])})"
        )
    sql += ["INSERT INTO __SCHEMA__.validations VALUES", ",\n".join(validation_rows) + ";", ""]

    registered = {"release-sample-agent": "2026-11-02 00:35:00", "agentops-code": "2026-11-02 01:20:00"}
    agent_rows, version_rows = [], []
    for agent_id, at in registered.items():
        b, s = built[agent_id], built[agent_id]["spec"]
        version = s["agent_version"]
        path = f"{VOLUME_ROOT}/agents/{agent_id}/{version}/{b['sha']}.tar.gz"
        code = agent_id == "agentops-code"
        agent_rows.append(
            f"  ({q(agent_id)}, {q(s['agent_name'])}, {q(readme_first[agent_id])}, "
            f"{q('code-based-agent' if code else 'skill-based-agent')}, {q(s['build_type'])}, {q(s['serving_type'])}, "
            f"{q(s['origin'])}, {q(s['owner'])}, {q(s['owner_group'])}, {q(s['service_criticality'])}, "
            f"{q(s['data_sensitivity'])}, {q(s['security_level'])}, "
            f"CAST(array() AS ARRAY<STRUCT<object: STRING, privilege: STRING>>), "
            f"{q(json.dumps(s['success_criteria']))}, {q(s['flagship_model'])}, {q(s['model_service'])}, 'active', "
            f"{q(version)}, {q(path)}, {ts(at)}, {ts(at)})"
        )
        version_rows.append(
            f"  ({q(agent_id)}, {q(version)}, 'major', {q(s['model_service'])}, {q(path)}, {q(b['sha'])}, {b['size']}, "
            f"{arr(b['skills'])}, {q(None if code else 'codex')}, {q(None if code else '0.163.0')}, "
            f"{mp(code_sdk if code else {'openai-codex': '0.163.0'})}, {q(uv_lock_sha if code else None)}, "
            f"{q(b['commit'])}, {q(f'{CATALOG}.{SCHEMA}.' + agent_id.replace('-', '_'))}, 1, "
            f"{q('m-' + rid('logged-model', agent_id, version))}, {q(b['validation_id'])}, 1, "
            f"{q(json.dumps(s, ensure_ascii=False))}, {q(DEVELOPER)}, {ts(at)})"
        )
    sql += ["INSERT INTO __SCHEMA__.agents VALUES", ",\n".join(agent_rows) + ";", ""]
    sql += ["INSERT INTO __SCHEMA__.agent_versions VALUES", ",\n".join(version_rows) + ";", ""]

    code = built["agentops-code"]
    app = "agent-bricks-agentops-code"
    req1, req2 = rid("request", "agentops-code", "1.0.0", "1"), rid("request", "agentops-code", "1.0.0", "2")
    dep = rid("deployment", "agentops-code", "1.0.0")
    sql += [
        "INSERT INTO __SCHEMA__.deploy_requests VALUES",
        f"  ({q(req1)}, 'agentops-code', '1.0.0', {q(HOST)}, {q(app)}, {q(code['validation_id'])}, 1, {q(DEVELOPER)}, "
        f"{ts('2026-11-02 01:25:00')}, 'rejected', {ts('2026-11-02 01:50:00')}),",
        f"  ({q(req2)}, 'agentops-code', '1.0.0', {q(HOST)}, {q(app)}, {q(code['validation_id'])}, 1, {q(DEVELOPER)}, "
        f"{ts('2026-11-02 05:00:00')}, 'deployed', {ts('2026-11-02 05:36:00')});",
        "",
        "INSERT INTO __SCHEMA__.approvals VALUES",
        f"  ({q(rid('approval', req1))}, {q(req1)}, {q(APPROVER)}, 'rejected', "
        f"'배포 금지 시간(오전 정기 점검) 중 요청. 14시 이후 다시 요청', {ts('2026-11-02 01:50:00')}),",
        f"  ({q(rid('approval', req2))}, {q(req2)}, {q(APPROVER)}, 'approved', "
        f"'검증 통과, 운영 기록(tracing·Apps telemetry) 설정 확인', {ts('2026-11-02 05:18:00')});",
        "",
        "INSERT INTO __SCHEMA__.deployments VALUES",
        f"  ({q(dep)}, {q(req2)}, 'agentops-code', '1.0.0', {q(app)}, "
        f"{q(f'https://{app}-{WORKSPACE_ID}.aws.databricksapps.com')}, {q('01f1d6' + rid('apps-deployment', dep)[6:])}, "
        f"'agentbricks', {q(json.dumps({'status': 'passed', 'gateway_policies': [], 'redteam_pass_rate': 0.96, 'note': '데이터 민감도 내부: 필수 Gateway 정책 없음'}, ensure_ascii=False))}, "
        f"true, 'succeeded', 846193027531877, {q(DEVELOPER)}, {ts('2026-11-02 05:20:00')}, {ts('2026-11-02 05:36:00')});",
        "",
        "INSERT INTO __SCHEMA__.production VALUES",
        f"  ({q(rid('transition', 'agentops-code', '1.0.0'))}, 'agentops-code', '1.0.0', NULL, {q(dep)}, 'promote', true, "
        f"'첫 운영 지정', {q(DEVELOPER)}, {ts('2026-11-02 06:00:00')});",
    ]
    (ROOT / "bundles/registry/sample_data.sql").write_text("\n".join(sql) + "\n", encoding="utf-8")
    for agent_id, b in built.items():
        print(agent_id, b["spec"]["agent_version"], b["sha"], b["size"], b["skills"], b["commit"])
    print("sdk", code_sdk)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
