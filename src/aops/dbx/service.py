"""The dbx lifecycle for skill agents: register, validate, deploy, promote, list and load.

The aops server calls these with the requester it identified; the functions act with the server's
own identity (the aops service principal in a Databricks App). validate and deploy do their work in
Lakeflow Jobs that run `aops-job`, as the same service principal.
"""

from __future__ import annotations

import io
import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .. import package
from ..hashing import skills_sha256
from .sql import Sql, loads

DEFAULT_POLICY = {
    "validation_mode": "mandatory",
    "approval_mode": "required",
    "approval_channel": "console",
    "approver_group": "",
    "required_approvals": 1,
    "security_levels": ["general", "important", "secret"],
}
CRITICALITY = {"low", "medium", "high"}
SENSITIVITY = {"public", "internal", "confidential", "personal"}
SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SECRET_PATTERNS = {
    "Databricks 토큰": re.compile(r"dapi[0-9a-f]{32}"),
    "GitHub 토큰": re.compile(r"gh[pousr]_[A-Za-z0-9]{36}"),
    "AWS 키": re.compile(r"AKIA[0-9A-Z]{16}"),
    "개인 키": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}
FORBIDDEN_FILES = re.compile(r"(^|/)(\.env(\..*)?|.*\.pem|id_rsa)$")


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str, command: str | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.command = status, code, message, command


@dataclass(frozen=True)
class Config:
    registry: str  # <catalog>.<schema>
    warehouse_id: str
    dist_wheel: str | None = None  # /Volumes/.../aops_cli-<version>-py3-none-any.whl for the Jobs
    profile: str | None = None  # only when the server runs outside Databricks Apps

    @classmethod
    def from_env(cls) -> Config | None:
        registry, warehouse = os.environ.get("AOPS_REGISTRY"), os.environ.get("AOPS_WAREHOUSE_ID")
        if not registry or not warehouse:
            return None
        return cls(registry, warehouse, os.environ.get("AOPS_DIST_WHEEL"), os.environ.get("AOPS_PROFILE"))

    @property
    def catalog(self) -> str:
        return self.registry.split(".")[0]

    @property
    def schema(self) -> str:
        return self.registry.split(".")[1]


@dataclass
class Caller:
    email: str
    token: str | None = None
    groups: list[str] = field(default_factory=list)


def now_id() -> str:
    return uuid.uuid4().hex


class Service:
    def __init__(self, config: Config, workspace: Any = None):
        from databricks.sdk import WorkspaceClient

        self.config = config
        self.w = workspace or (WorkspaceClient(profile=config.profile) if config.profile else WorkspaceClient())
        self.sql = Sql(self.w, config.warehouse_id, config.registry)
        self._jobs: dict[str, int] = {}

    # ── identity ────────────────────────────────────────────────────────────

    def identify(self, token: str | None, email: str | None) -> Caller:
        """The requester: the forwarded user from Databricks Apps, or the owner of a bearer token."""
        groups: list[str] = []
        if token:
            me = self._as_user(token, "GET", "/api/2.0/preview/scim/v2/Me")
            if me.get("status") == 200:
                body = me["body"]
                email = email or body.get("userName")
                groups = [g.get("display") for g in body.get("groups", []) if g.get("display")]
        if not email:
            raise ServiceError(401, "unauthenticated", "요청한 사람을 확인할 수 없습니다")
        return Caller(email=email, token=token, groups=groups)

    def _as_user(self, token: str, method: str, path: str) -> dict[str, Any]:
        import urllib.error
        import urllib.request

        host = self.w.config.host.rstrip("/")
        req = urllib.request.Request(host + path, method=method, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                try:
                    return {"status": resp.status, "body": json.loads(data)}
                except ValueError:
                    return {"status": resp.status, "body": data}
        except urllib.error.HTTPError as error:
            return {"status": error.code, "body": None}

    def _is_owner(self, caller: Caller, agent: dict[str, Any]) -> bool:
        return caller.email == agent["owner"] or bool(agent.get("owner_group") and agent["owner_group"] in caller.groups)

    # ── registry reads ──────────────────────────────────────────────────────

    def policy(self) -> tuple[int, dict[str, Any]]:
        row = self.sql.one(f"SELECT policy_version, body FROM {self.sql.table('policies')} WHERE status = 'active' "
                           "ORDER BY policy_version DESC LIMIT 1")
        if not row:
            return 0, dict(DEFAULT_POLICY)
        return int(row["policy_version"]), {**DEFAULT_POLICY, **loads(row["body"])}

    def agent(self, agent_id: str) -> dict[str, Any] | None:
        return self.sql.one(f"SELECT * FROM {self.sql.table('agents')} WHERE agent_id = :id", {"id": agent_id})

    def versions(self, agent_id: str) -> list[dict[str, Any]]:
        return self.sql.run(f"SELECT * FROM {self.sql.table('agent_versions')} WHERE agent_id = :id ORDER BY registered_at",
                            {"id": agent_id})

    def version(self, agent_id: str, version: str) -> dict[str, Any] | None:
        return self.sql.one(f"SELECT * FROM {self.sql.table('agent_versions')} WHERE agent_id = :id AND version = :v",
                            {"id": agent_id, "v": version})

    def version_skills(self, agent_id: str, version: str) -> list[dict[str, Any]]:
        return self.sql.run(f"SELECT * FROM {self.sql.table('agent_version_skills')} WHERE agent_id = :id AND version = :v",
                            {"id": agent_id, "v": version})

    def production(self, agent_id: str) -> dict[str, Any] | None:
        return self.sql.one(f"SELECT * FROM {self.sql.table('agent_production')} WHERE agent_id = :id", {"id": agent_id})

    def list_agents(self, build_type: str | None = None) -> list[dict[str, Any]]:
        where, params = ("WHERE build_type = :t", {"t": build_type}) if build_type else ("", {})
        return self.sql.run(f"SELECT * FROM {self.sql.table('agent_status')} {where} ORDER BY agent_id", params)

    def events(self, agent_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.sql.run(f"SELECT * FROM {self.sql.table('agent_events')} WHERE agent_id = :id ORDER BY at DESC LIMIT {int(limit)}",
                            {"id": agent_id})
        for row in rows:
            row["detail"] = loads(row.get("detail")) or {}
        return rows

    def event(self, agent_id: str, version: str | None, kind: str, actor: str, detail: dict[str, Any] | None = None) -> None:
        self.sql.run(f"INSERT INTO {self.sql.table('agent_events')} VALUES (:e, :a, :v, :k, :actor, current_timestamp(), parse_json(:d))",
                     {"e": now_id(), "a": agent_id, "v": version, "k": kind, "actor": actor, "d": detail or {}})

    # ── register ────────────────────────────────────────────────────────────

    def register(self, caller: Caller, agent_id: str, data: bytes, version: str | None = None,
                 bump: str | None = None) -> dict[str, Any]:
        files = package.read(data)
        if "aops.toml" not in files or "SPEC.md" not in files:
            raise ServiceError(400, "not_an_agent", "버전 zip에 aops.toml과 SPEC.md가 있어야 합니다", "aops register")
        spec = package.front_matter(files["SPEC.md"].decode("utf-8"))
        if spec.get("agent_id", agent_id) != agent_id:
            raise ServiceError(400, "agent_id_mismatch", f"SPEC.md의 agent_id({spec.get('agent_id')})가 {agent_id}와 다릅니다")
        build_type = spec.get("build_type", "skill").replace("-", "_")
        if build_type != "skill":
            raise ServiceError(501, "not_implemented", "지금은 스킬 기반 에이전트만 등록합니다", "aops register")
        sha = package.files_sha256(list(files.items()))

        agent = self.agent(agent_id)
        if agent and not self._is_owner(caller, agent):
            raise ServiceError(403, "not_owner", "담당자·담당 팀만 새 버전을 등록할 수 있습니다", "aops register")
        existing = self.versions(agent_id)
        if existing and existing[-1]["source_sha256"] == sha:
            raise ServiceError(409, "unchanged", f"마지막 버전({existing[-1]['version']})과 내용이 같습니다", "aops register")
        new_version = version or next_version([v["version"] for v in existing], bump)
        if any(v["version"] == new_version for v in existing):
            raise ServiceError(409, "version_exists", f"{new_version}은 이미 등록된 버전입니다", "aops register")

        # 1. the version zip, written once into the agent's own volume
        self.sql.run(f"CREATE VOLUME IF NOT EXISTS {self.config.registry}.`{agent_id}` "
                     f"COMMENT 'aops 에이전트 {agent_id}의 버전 zip. 쓰기는 aops 서비스 주체만'")
        path = f"/Volumes/{self.config.catalog}/{self.config.schema}/{agent_id}/{new_version}.zip"
        self.w.files.upload(path, io.BytesIO(data), overwrite=False)

        # 2. skills: hashes for the record; the first registration creates each UC skill with no readers
        skills = skill_folders(files)
        hashes = {alias: package.files_sha256(list(content.items())) for alias, content in skills.items()}
        published: dict[str, str | None] = {}
        for alias, content in skills.items():
            uc_name = f"{self.config.registry}.{uc_skill_id(agent_id, alias)}"
            try:
                if not self._skill_exists(uc_name):
                    self._create_skill(uc_name)
                    self._sync_skill(uc_name, content)
                published[alias] = uc_name
            except Exception as error:  # preview off or Compliance Security Profile: skip publishing only
                published[alias] = None
                print(f"aops: UC Skill 단계를 건너뜁니다 ({alias}): {error}")

        # 3. the registry
        if not agent:
            owner = spec.get("owner") or caller.email
            self.sql.run(
                f"INSERT INTO {self.sql.table('agents')} VALUES (:id, :name, :desc, 'skill', :owner, :group, :crit, :sens, :sec, "
                "'registered', parse_json(:spec), :by, current_timestamp(), current_timestamp())",
                {"id": agent_id, "name": spec.get("name") or agent_id, "desc": spec.get("description"), "owner": owner,
                 "group": spec.get("owner_group") or None, "crit": pick(spec.get("service_criticality"), CRITICALITY, "medium"),
                 "sens": pick(spec.get("data_sensitivity"), SENSITIVITY, "internal"),
                 "sec": spec.get("security_level") or "general", "spec": spec, "by": caller.email},
            )
        else:
            self.sql.run(f"UPDATE {self.sql.table('agents')} SET spec = parse_json(:spec), updated_at = current_timestamp() "
                         "WHERE agent_id = :id", {"id": agent_id, "spec": spec})
        harness = re.search(r'harness\s*=\s*"(\w+)"', files["aops.toml"].decode("utf-8"))
        self.sql.run(
            f"INSERT INTO {self.sql.table('agent_versions')} VALUES (:id, :v, 'registered', :sha, :path, :size, :skills, "
            ":harness, NULL, parse_json(:spec), :by, current_timestamp())",
            {"id": agent_id, "v": new_version, "sha": sha, "path": path, "size": len(data), "skills": skills_sha256(hashes),
             "harness": harness.group(1) if harness else None, "spec": spec, "by": caller.email},
        )
        for alias, uc_name in published.items():
            self.sql.run(f"INSERT INTO {self.sql.table('agent_version_skills')} VALUES (:id, :v, :alias, :uc, :sha, :src, 'agent')",
                         {"id": agent_id, "v": new_version, "alias": alias, "uc": uc_name, "sha": hashes[alias],
                          "src": f"agent/skills/{alias}"})
        self.event(agent_id, new_version, "register", caller.email,
                   {"artifact_path": path, "skills": published, "first": not existing})
        return {**self.version(agent_id, new_version), "skills": [{"skill_alias": a, "uc_name": u} for a, u in published.items()]}

    # ── UC skills ───────────────────────────────────────────────────────────

    def _skill_exists(self, uc_name: str) -> bool:
        try:
            self.w.ai_gateway.get_skill(f"skills/{uc_name}")
            return True
        except Exception as error:
            if "NOT_FOUND" in str(error) or "does not exist" in str(error).lower() or "not found" in str(error).lower():
                return False
            raise

    def _create_skill(self, uc_name: str) -> None:
        from databricks.sdk.service.catalog import Skill

        catalog, schema, skill_id = uc_name.split(".", 2)
        self.w.ai_gateway.create_skill(Skill(comment="aops가 관리하는 운영 스킬"), f"schemas/{catalog}.{schema}", skill_id)

    def _skill_path(self, uc_name: str) -> str:
        catalog, schema, skill_id = uc_name.split(".", 2)
        return f"/Skills/{catalog}/{schema}/{skill_id}"

    def _sync_skill(self, uc_name: str, content: dict[str, bytes]) -> None:
        """Make the UC skill hold exactly `content`: changed files, SKILL.md last, stale files removed, finalize."""
        base = self._skill_path(uc_name)
        remote = set(self._remote_files(base))
        for rel in sorted(content, key=lambda r: (r == "SKILL.md", r)):
            self.w.files.upload(f"{base}/{rel}", io.BytesIO(content[rel]), overwrite=True)
        for rel in remote - set(content):
            self.w.files.delete(f"{base}/{rel}")
        self.w.ai_gateway.finalize_skill(f"skills/{uc_name}")

    def _remote_files(self, base: str, prefix: str = "") -> list[str]:
        out = []
        try:
            entries = list(self.w.files.list_directory_contents(f"{base}/{prefix}".rstrip("/")))
        except Exception:
            return out
        for entry in entries:
            rel = entry.path[len(base) + 1:]
            if entry.is_directory:
                out.extend(self._remote_files(base, rel))
            else:
                out.append(rel)
        return out

    # ── validate ────────────────────────────────────────────────────────────

    def start_validation(self, caller: Caller, agent_id: str, version: str | None = None) -> dict[str, Any]:
        agent = self._agent_or_404(agent_id)
        if not self._is_owner(caller, agent):
            raise ServiceError(403, "not_owner", "담당자·담당 팀만 검사를 요청할 수 있습니다", "aops validate")
        target = self._version_or_latest(agent_id, version)
        policy_version, _ = self.policy()
        run_id = now_id()
        self.sql.run(
            f"INSERT INTO {self.sql.table('validation_runs')} VALUES (:r, :a, :v, :sha, :p, 'job', 'queued', NULL, NULL, NULL, NULL, "
            ":by, current_timestamp(), NULL)",
            {"r": run_id, "a": agent_id, "v": target["version"], "sha": target["source_sha256"], "p": policy_version, "by": caller.email},
        )
        job_run = self._run_job("validate", run_id)
        self.sql.run(f"UPDATE {self.sql.table('validation_runs')} SET job_run_id = :j WHERE validation_run_id = :r",
                     {"j": job_run, "r": run_id})
        return self.validation(run_id)

    def validation(self, run_id: str) -> dict[str, Any]:
        row = self.sql.one(f"SELECT * FROM {self.sql.table('validation_runs')} WHERE validation_run_id = :r", {"r": run_id})
        if not row:
            raise ServiceError(404, "not_found", "검사 실행이 없습니다")
        row["steps"] = loads(row.get("steps")) or []
        row["checks"] = loads(row.get("checks")) or {}
        row["policy_version"] = int(row["policy_version"])
        return row

    def run_validation(self, run_id: str) -> str:
        """Inside the validate Job: check the registered zip against the policy and record the result."""
        run = self.validation(run_id)
        self.sql.run(f"UPDATE {self.sql.table('validation_runs')} SET status = 'running' WHERE validation_run_id = :r", {"r": run_id})
        steps: list[dict[str, Any]] = []
        try:
            version = self.version(run["agent_id"], run["version"])
            data = self.w.files.download(version["artifact_path"]).contents.read()
            files = package.read(data)
            steps = check_skill_agent(files)
            if package.files_sha256(list(files.items())) != version["source_sha256"]:
                steps.append({"name": "record", "status": "failed", "detail": "버전 zip이 등록 때 해시와 다릅니다"})
            status = "passed" if all(s["status"] != "failed" for s in steps) else "failed"
            reason = None if status == "passed" else "; ".join(s["detail"] for s in steps if s["status"] == "failed")
        except Exception as error:
            status, reason = "error", f"{type(error).__name__}: {error}"
        self.sql.run(
            f"UPDATE {self.sql.table('validation_runs')} SET status = :s, steps = parse_json(:steps), failure_reason = :why, "
            "ended_at = current_timestamp() WHERE validation_run_id = :r",
            {"s": status, "steps": steps, "why": reason, "r": run_id},
        )
        self.event(run["agent_id"], run["version"], "validate", run["started_by"], {"status": status, "validation_run_id": run_id})
        return status

    # ── deploy ──────────────────────────────────────────────────────────────

    def request_deploy(self, caller: Caller, agent_id: str, version: str | None = None, reason: str | None = None) -> dict[str, Any]:
        agent = self._agent_or_404(agent_id)
        if not self._is_owner(caller, agent):
            raise ServiceError(403, "not_owner", "담당자·담당 팀만 배포를 요청할 수 있습니다", "aops deploy")
        target = self._version_or_latest(agent_id, version)
        open_gate = self.sql.one(
            f"SELECT g.gate_id, g.version FROM {self.sql.table('release_gates')} g LEFT JOIN {self.sql.table('deployments')} d "
            "ON d.deployment_id = g.deployment_id WHERE g.agent_id = :a AND (g.decision IN ('validating', 'pending_approval') "
            "OR (g.decision = 'approved' AND (d.status IS NULL OR d.status = 'running')))", {"a": agent_id})
        if open_gate and open_gate["version"] == target["version"]:
            return self.advance(open_gate["gate_id"])  # the same request again: keep following it
        if open_gate:
            raise ServiceError(409, "gate_open", f"진행 중인 배포 요청이 있습니다 ({open_gate['version']}, {open_gate['gate_id']})", "aops deploy")
        policy_version, policy = self.policy()
        production = self.production(agent_id)
        upgrade = upgrade_type(production["current_version"] if production else None, target["version"])
        gate_id = now_id()
        self.sql.run(
            f"INSERT INTO {self.sql.table('release_gates')} VALUES (:g, :a, :v, :by, :why, current_timestamp(), :up, :p, :vm, NULL, "
            ":am, :ch, :n, NULL, NULL, 'validating', NULL, NULL, current_timestamp())",
            {"g": gate_id, "a": agent_id, "v": target["version"], "by": caller.email, "why": reason, "up": upgrade,
             "p": policy_version, "vm": policy["validation_mode"], "am": policy["approval_mode"],
             "ch": policy["approval_channel"], "n": int(policy["required_approvals"])},
        )
        self.event(agent_id, target["version"], "gate_requested", caller.email, {"gate_id": gate_id, "upgrade_type": upgrade})

        passed = self._passed_validation(agent_id, target["version"], policy_version)
        if policy["validation_mode"] == "exempt" or passed:
            self._after_gate(gate_id, passed["validation_run_id"] if passed else None)
        else:
            run = self.start_validation(caller, agent_id, target["version"])
            self._set_gate(gate_id, validation_run_id=run["validation_run_id"])
            threading.Thread(target=self._follow, args=(gate_id,), daemon=True).start()
        return self.gate(gate_id)

    def _passed_validation(self, agent_id: str, version: str, policy_version: int) -> dict[str, Any] | None:
        return self.sql.one(f"SELECT validation_run_id FROM {self.sql.table('validation_runs')} WHERE agent_id = :a AND version = :v "
                            "AND policy_version = :p AND status = 'passed' AND mode = 'job' ORDER BY started_at DESC LIMIT 1",
                            {"a": agent_id, "v": version, "p": policy_version})

    def _follow(self, gate_id: str, timeout: int = 1800) -> None:
        """Background: move the gate on when its validation ends. advance() is also called on every read."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.advance(gate_id)["decision"] != "validating":
                return
            time.sleep(5)

    def advance(self, gate_id: str) -> dict[str, Any]:
        """Move a validating gate on once its validation has finished. Safe to call from anywhere, any time."""
        gate = self.gate(gate_id)
        if gate["decision"] != "validating" or not gate.get("validation_run_id"):
            return gate
        run = self.validation(gate["validation_run_id"])
        if run["status"] not in ("passed", "failed", "stale", "error"):
            return gate
        if run["status"] == "passed":
            self._after_gate(gate_id, run["validation_run_id"])
        elif self.sql.update(f"UPDATE {self.sql.table('release_gates')} SET decision = 'rejected', decision_reason = :why, "
                             "updated_at = current_timestamp() WHERE gate_id = :g AND decision = 'validating'",
                             {"g": gate_id, "why": f"검사 {run['status']}: {run.get('failure_reason') or ''}"}):
            self.event(gate["agent_id"], gate["version"], "gate_rejected", "policy:gate", {"gate_id": gate_id, "validation": run["status"]})
        return self.gate(gate_id)

    def _after_gate(self, gate_id: str, run_id: str | None) -> None:
        moved = self.sql.update(f"UPDATE {self.sql.table('release_gates')} SET decision = 'pending_approval', validation_run_id = :r, "
                                "updated_at = current_timestamp() WHERE gate_id = :g AND decision = 'validating'", {"g": gate_id, "r": run_id})
        if not moved:
            return
        gate = self.gate(gate_id)
        if gate["approval_mode"] == "auto":
            self.sql.run(f"INSERT INTO {self.sql.table('approvals')} VALUES (:id, :g, 'policy:auto', 'approve', '정책의 자동 승인', "
                         "'policy', current_timestamp())", {"id": now_id(), "g": gate_id})
            self._approved(gate)

    def approve(self, caller: Caller, gate_id: str, comment: str | None = None) -> dict[str, Any]:
        gate = self.gate(gate_id)
        if gate["decision"] != "pending_approval":
            raise ServiceError(409, "not_pending", "승인 대기 중인 요청이 아닙니다")
        if caller.email == gate["requester"]:
            raise ServiceError(403, "self_approval", "요청자 본인은 승인할 수 없습니다")
        _, policy = self.policy()
        if policy["approver_group"] and policy["approver_group"] not in caller.groups:
            raise ServiceError(403, "not_approver", f"승인 그룹({policy['approver_group']})만 승인할 수 있습니다")
        self.sql.run(f"INSERT INTO {self.sql.table('approvals')} VALUES (:id, :g, :by, 'approve', :c, 'console', current_timestamp())",
                     {"id": now_id(), "g": gate_id, "by": caller.email, "c": comment})
        approved = self.sql.one(f"SELECT count(*) AS n FROM {self.sql.table('approvals')} WHERE gate_id = :g AND decision = 'approve'",
                                {"g": gate_id})
        if int(approved["n"]) >= int(gate["required_approvals"]):
            self._approved(gate)
        return self.gate(gate_id)

    def _approved(self, gate: dict[str, Any]) -> None:
        deployment_id = now_id()
        if not self.sql.update(f"UPDATE {self.sql.table('release_gates')} SET decision = 'approved', deployment_id = :d, "
                               "updated_at = current_timestamp() WHERE gate_id = :g AND decision = 'pending_approval'",
                               {"g": gate["gate_id"], "d": deployment_id}):
            return
        self.sql.run(f"INSERT INTO {self.sql.table('deployments')} VALUES (:d, :g, :a, :v, 'production', NULL, NULL, 'running', NULL, "
                     "NULL, current_timestamp(), NULL)", {"d": deployment_id, "g": gate["gate_id"], "a": gate["agent_id"], "v": gate["version"]})
        self.event(gate["agent_id"], gate["version"], "gate_approved", "policy:auto" if gate["approval_mode"] == "auto" else gate["requester"],
                   {"gate_id": gate["gate_id"], "approval_mode": gate["approval_mode"]})
        job_run = self._run_job("deploy", gate["gate_id"])
        self.sql.run(f"UPDATE {self.sql.table('deployments')} SET job_run_id = :j WHERE deployment_id = :d",
                     {"j": job_run, "d": deployment_id})

    def run_deploy(self, gate_id: str) -> str:
        """Inside the deploy Job: check the approval again and roll the version out."""
        gate = self.gate(gate_id)
        deployment_id = gate["deployment_id"]
        try:
            if gate["decision"] != "approved":
                raise RuntimeError(f"승인되지 않은 요청입니다 ({gate['decision']})")
            agent_id, version = gate["agent_id"], gate["version"]
            target = self.version(agent_id, version)
            files = package.read(self.w.files.download(target["artifact_path"]).contents.read())
            if package.files_sha256(list(files.items())) != target["source_sha256"]:
                raise RuntimeError("버전 zip이 등록 때 해시와 다릅니다")
            production = self.production(agent_id)
            live = {s["skill_alias"]: s["skill_sha256"] for s in self.version_skills(agent_id, production["current_version"])} if production else {}
            names = []
            for alias, content in skill_folders(files).items():
                row = next((s for s in self.version_skills(agent_id, version) if s["skill_alias"] == alias), None)
                if not row or not row["uc_name"]:
                    continue
                if not self._skill_exists(row["uc_name"]):
                    self._create_skill(row["uc_name"])
                    self._sync_skill(row["uc_name"], content)
                elif live.get(alias) != row["skill_sha256"] or not production:
                    self._sync_skill(row["uc_name"], content)  # skipped when the content is already this version
                names.append(row["uc_name"])
            previous = production["current_version"] if production else None
            self.sql.run(f"UPDATE {self.sql.table('agent_versions')} SET status = 'retired' WHERE agent_id = :a AND status = 'production'",
                         {"a": agent_id})
            self.sql.run(f"UPDATE {self.sql.table('agent_versions')} SET status = 'production' WHERE agent_id = :a AND version = :v",
                         {"a": agent_id, "v": version})
            self.sql.run(
                f"MERGE INTO {self.sql.table('agent_production')} t USING (SELECT :a AS agent_id) s ON t.agent_id = s.agent_id "
                "WHEN MATCHED THEN UPDATE SET previous_version = t.current_version, current_version = :v, target = :t, updated_by = :by, "
                "updated_at = current_timestamp() WHEN NOT MATCHED THEN INSERT (agent_id, current_version, previous_version, target, updated_by, updated_at) "
                "VALUES (:a, :v, NULL, :t, :by, current_timestamp())",
                {"a": agent_id, "v": version, "t": ", ".join(names), "by": gate["requester"]},
            )
            self.sql.run(f"UPDATE {self.sql.table('agents')} SET lifecycle = 'production', updated_at = current_timestamp() WHERE agent_id = :a",
                         {"a": agent_id})
            self.sql.run(f"UPDATE {self.sql.table('deployments')} SET status = 'succeeded', target = :t, ended_at = current_timestamp() "
                         "WHERE deployment_id = :d", {"t": ", ".join(names), "d": deployment_id})
            kind = "rollback" if gate["upgrade_type"] == "rollback" else "deploy"
            self.event(agent_id, version, kind, gate["requester"], {"gate_id": gate_id, "previous": previous, "skills": names})
            return "succeeded"
        except Exception as error:
            self.sql.run(f"UPDATE {self.sql.table('deployments')} SET status = 'failed', detail = parse_json(:d), ended_at = current_timestamp() "
                         "WHERE deployment_id = :id", {"d": {"error": f"{type(error).__name__}: {error}"}, "id": deployment_id})
            raise

    def gate(self, gate_id: str) -> dict[str, Any]:
        row = self.sql.one(f"SELECT * FROM {self.sql.table('release_gates')} WHERE gate_id = :g", {"g": gate_id})
        if not row:
            raise ServiceError(404, "not_found", "배포 요청이 없습니다")
        deployment = self.sql.one(f"SELECT status FROM {self.sql.table('deployments')} WHERE deployment_id = :d",
                                  {"d": row["deployment_id"]}) if row.get("deployment_id") else None
        row["deployment_status"] = deployment["status"] if deployment else None
        approvals = self.sql.one(f"SELECT count(*) AS n FROM {self.sql.table('approvals')} WHERE gate_id = :g AND decision = 'approve'",
                                 {"g": gate_id})
        row["approvals"] = int(approvals["n"]) if approvals else 0
        return row

    def _set_gate(self, gate_id: str, **values: Any) -> None:
        sets = ", ".join(f"{k} = :{k}" for k in values)
        self.sql.run(f"UPDATE {self.sql.table('release_gates')} SET {sets}, updated_at = current_timestamp() WHERE gate_id = :g",
                     {**values, "g": gate_id})

    # ── promote, load ───────────────────────────────────────────────────────

    def promote(self, caller: Caller, agent_id: str, principals: list[str], revoke: bool = False) -> list[dict[str, Any]]:
        from databricks.sdk.service.catalog import PermissionsChange

        agent = self._agent_or_404(agent_id)
        if not self._is_owner(caller, agent):
            raise ServiceError(403, "not_owner", "담당자·담당 팀만 권한을 줄 수 있습니다", "aops promote")
        production = self.production(agent_id)
        if not production:
            raise ServiceError(409, "no_production", "운영 버전이 없습니다. 먼저 aops deploy 하세요", "aops promote")
        names = [s["uc_name"] for s in self.version_skills(agent_id, production["current_version"]) if s["uc_name"]]
        grants = []
        for principal in principals:
            name = principal.split(":", 1)[1] if ":" in principal else principal
            for uc_name in names:
                change = PermissionsChange(principal=name, remove=["READ_VOLUME"]) if revoke else PermissionsChange(principal=name, add=["READ_VOLUME"])
                self.w.grants.update("skill", uc_name, changes=[change])
                grants.append({"agent_id": agent_id, "securable": f"skill:{uc_name}", "principal": principal,
                               "permission": "READ_VOLUME", "granted": not revoke})
            self.event(agent_id, production["current_version"], "promote", caller.email,
                       {"principal": principal, "permission": "READ_VOLUME", "granted": not revoke, "skills": names})
        return grants

    def load(self, caller: Caller, agent_id: str, version: str | None = None) -> dict[str, Any]:
        agent = self._agent_or_404(agent_id)
        target, allowed = self._loadable(caller, agent, version)
        if allowed:
            self.event(agent_id, target["version"], "load", caller.email, {"version": target["version"]})
        return {"agent_id": agent_id, "build_type": agent["build_type"], "version": target["version"], "link": None,
                "allowed": allowed,
                "archive": {"url": f"/api/v1/agents/{agent_id}/versions/{target['version']}/archive",
                            "sha256": target["source_sha256"], "size_bytes": int(target["size_bytes"] or 0)} if allowed else None}

    def archive(self, caller: Caller, agent_id: str, version: str) -> bytes:
        agent = self._agent_or_404(agent_id)
        target, allowed = self._loadable(caller, agent, version)
        if not allowed:
            raise ServiceError(403, "no_access", "이 에이전트를 가져올 권한이 없습니다. 담당자에게 promote를 요청하세요", "aops load")
        return self.w.files.download(target["artifact_path"]).contents.read()

    def _loadable(self, caller: Caller, agent: dict[str, Any], version: str | None) -> tuple[dict[str, Any], bool]:
        owner = self._is_owner(caller, agent)
        production = self.production(agent["agent_id"])
        if version and version != (production or {}).get("current_version"):
            if not owner:
                raise ServiceError(403, "not_owner", "운영 버전이 아닌 버전은 담당자·담당 팀만 가져올 수 있습니다", "aops load")
            target = self.version(agent["agent_id"], version)
            if not target:
                raise ServiceError(404, "not_found", f"{version} 버전이 없습니다", "aops load")
            return target, True
        if not production:
            raise ServiceError(409, "no_production", "운영 버전이 없습니다", "aops load")
        target = self.version(agent["agent_id"], production["current_version"])
        if owner:
            return target, True
        skills = [s["uc_name"] for s in self.version_skills(agent["agent_id"], target["version"]) if s["uc_name"]]
        return target, bool(skills) and all(self._can_read_skill(caller, name) for name in skills)

    def _can_read_skill(self, caller: Caller, uc_name: str) -> bool:
        """Reading SKILL.md with the requester's own token: 200 means READ_VOLUME (directly or through a group)."""
        if caller.token:
            result = self._as_user(caller.token, "GET", f"/api/2.0/fs/files{self._skill_path(uc_name)}/SKILL.md")
            if result["status"] in (200, 404):
                return result["status"] == 200
        effective = self.w.grants.get_effective("skill", uc_name, principal=caller.email)
        privileges = {p.privilege.value if hasattr(p.privilege, "value") else str(p.privilege)
                      for a in (effective.privilege_assignments or []) for p in (a.privileges or [])}
        return bool(privileges & {"READ_VOLUME", "ALL_PRIVILEGES", "MANAGE"})

    # ── helpers ─────────────────────────────────────────────────────────────

    def _agent_or_404(self, agent_id: str) -> dict[str, Any]:
        agent = self.agent(agent_id)
        if not agent:
            raise ServiceError(404, "not_found", f"등록된 에이전트가 아닙니다: {agent_id}")
        return agent

    def _version_or_latest(self, agent_id: str, version: str | None) -> dict[str, Any]:
        target = self.version(agent_id, version) if version else (self.versions(agent_id) or [None])[-1]
        if not target:
            raise ServiceError(404, "not_found", f"등록된 버전이 없습니다: {agent_id} {version or ''}".strip(), "aops register")
        return target

    def _run_job(self, kind: str, target_id: str) -> int:
        job_id = self._job(kind)
        run = self.w.jobs.run_now(job_id, job_parameters={"id": target_id})
        return run.run_id

    def _job(self, kind: str) -> int:
        """The validate or deploy Job, created by this identity so it runs as itself."""
        if kind in self._jobs:
            return self._jobs[kind]
        from databricks.sdk.service import compute, jobs

        name = f"aops-{kind}"
        for job in self.w.jobs.list(name=name):
            self._jobs[kind] = job.job_id
            return job.job_id
        if not self.config.dist_wheel:
            raise ServiceError(500, "no_wheel", "Job에 쓸 aops 패키지 경로(AOPS_DIST_WHEEL)가 없습니다. aops admin setup을 다시 실행하세요")
        params = ["--kind", kind, "--id", "{{job.parameters.id}}", "--registry", self.config.registry,
                  "--warehouse", self.config.warehouse_id]
        created = self.w.jobs.create(
            name=name,
            description=f"aops {kind} (aops 서버가 만든 Job, 서비스 주체로 실행)",
            max_concurrent_runs=10 if kind == "validate" else 1,
            performance_target=jobs.PerformanceTarget.PERFORMANCE_OPTIMIZED,
            parameters=[jobs.JobParameterDefinition(name="id", default="")],
            environments=[jobs.JobEnvironment(environment_key="aops", spec=compute.Environment(
                environment_version="2", dependencies=[self.config.dist_wheel, "databricks-sdk>=0.158"]))],
            tasks=[jobs.Task(task_key=kind, environment_key="aops", max_retries=0, disable_auto_optimization=True,
                             python_wheel_task=jobs.PythonWheelTask(package_name="aops_cli", entry_point="aops-job", parameters=params))],
        )
        self._jobs[kind] = created.job_id
        return created.job_id


# ── pure helpers ────────────────────────────────────────────────────────────

def uc_skill_id(agent_id: str, alias: str) -> str:
    return f"{agent_id}__{alias}".lower()


def skill_folders(files: dict[str, bytes]) -> dict[str, dict[str, bytes]]:
    """agent/skills/<alias>/… → {alias: {relative path: content}} for folders that hold SKILL.md."""
    out: dict[str, dict[str, bytes]] = {}
    for rel, data in files.items():
        parts = rel.split("/")
        if len(parts) >= 4 and parts[0] == "agent" and parts[1] == "skills":
            out.setdefault(parts[2], {})["/".join(parts[3:])] = data
    return {alias: content for alias, content in out.items() if "SKILL.md" in content}


def next_version(existing: list[str], bump: str | None) -> str:
    if not existing:
        return "1.0.0"
    major, minor, patch = (int(x) for x in max(existing, key=semver).split("."))
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "fix":
        return f"{major}.{minor}.{patch + 1}"
    return f"{major}.{minor + 1}.0"


def semver(text: str) -> tuple[int, ...]:
    return tuple(int(x) for x in text.split("."))


def upgrade_type(current: str | None, new: str) -> str:
    if not current:
        return "initial"
    a, b = semver(current), semver(new)
    if b < a:
        return "rollback"
    return "major" if b[0] > a[0] else "minor" if b[1] > a[1] else "patch"


def pick(value: str | None, allowed: set[str], default: str) -> str:
    return value if value in allowed else default


def check_skill_agent(files: dict[str, bytes]) -> list[dict[str, Any]]:
    """The validate steps for a skill agent: format, skills, secrets."""
    steps: list[dict[str, Any]] = []
    spec = package.front_matter(files.get("SPEC.md", b"").decode("utf-8", "replace"))
    missing = [k for k in ("agent_id", "name", "build_type") if not spec.get(k)]
    bad = [k for k, allowed in (("service_criticality", CRITICALITY), ("data_sensitivity", SENSITIVITY)) if spec.get(k) not in allowed]
    detail = "SPEC.md 필수 항목과 값이 맞습니다" if not missing and not bad else \
        f"SPEC.md: 빈 항목 {missing or '-'}, 허용되지 않는 값 {bad or '-'}"
    steps.append({"name": "format", "status": "passed" if not missing and not bad else "failed", "detail": detail})

    problems = []
    skills = skill_folders(files)
    if not skills:
        problems.append("agent/skills 아래에 SKILL.md가 있는 스킬이 없습니다")
    for alias, content in skills.items():
        front = package.front_matter(content["SKILL.md"].decode("utf-8", "replace"))
        if not SKILL_NAME.match(alias):
            problems.append(f"{alias}: 스킬 이름은 소문자·숫자·하이픈 64자 이하")
        if front.get("name") != alias:
            problems.append(f"{alias}: SKILL.md의 name이 폴더 이름과 다릅니다")
        if not 1 <= len(front.get("description", "").encode()) <= 1024:
            problems.append(f"{alias}: description은 1~1024바이트")
    steps.append({"name": "skills", "status": "failed" if problems else "passed",
                  "detail": "; ".join(problems) if problems else f"스킬 {len(skills)}개 형식이 맞습니다 ({', '.join(sorted(skills))})"})

    leaks = [f"{rel} ({label})" for rel, data in files.items() for label, pattern in SECRET_PATTERNS.items()
             if pattern.search(data.decode("utf-8", "ignore"))]
    leaks += [f"{rel} (금지 파일)" for rel in files if FORBIDDEN_FILES.search(rel)]
    steps.append({"name": "secrets", "status": "failed" if leaks else "passed",
                  "detail": "비밀값·금지 파일: " + ", ".join(leaks) if leaks else "비밀값·금지 파일이 없습니다"})
    return steps
