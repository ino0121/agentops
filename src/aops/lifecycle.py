"""`aops register`, `validate`, `deploy`, `promote`, `list` and `load` (dbx edition, through the aops server)."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from . import package
from .client import Server, ServerError
from .project import Project
from .sync import sync

DONE = ("passed", "failed", "stale", "error")


def _project() -> Project:
    project = Project.find()
    if not project.is_project or not project.name:
        raise ValueError("aops 프로젝트 폴더가 아닙니다 (aops.toml [project] name 필요)")
    return project


def _say(text: str) -> None:
    print(text, flush=True)


def cmd_register(args: argparse.Namespace) -> int:
    project = _project()
    archive = package.build(project)
    _say(f"버전 zip: 파일 {len(archive.files)}개, {len(archive.data):,} bytes, 해시 {archive.sha256[:12]}")
    row = Server(project).upload(f"/projects/{project.name}/registrations", {"version": args.version, "bump": args.bump},
                                 "archive", f"{project.name}.zip", archive.data)
    _say(f"등록: {project.name} {row['version']} (상태 {row['status']})")
    _say(f"  볼륨: {row['artifact_path']}")
    for skill in row.get("skills") or []:
        where = skill.get("uc_name") or "UC Skill 게시 건너뜀"
        _say(f"  스킬 {skill['skill_alias']} → UC Skill {where}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    project = _project()
    server = Server(project)
    run = server.request("POST", f"/projects/{project.name}/validations", body={"version": args.version})
    _say(f"검사 시작: {project.name} {run['version']} (validate Job)")
    run = _wait_validation(server, run["validation_run_id"])
    _print_steps(run)
    return 0 if run["status"] == "passed" else 1


def _poll(server: Server, path: str, tries: int = 5) -> dict[str, Any]:
    """GET while waiting on a Job. A passing server error (restart, write conflict) is asked again."""
    for attempt in range(tries):
        try:
            return server.request("GET", path)
        except ServerError as error:
            if error.status < 500 or attempt == tries - 1:
                raise
            time.sleep(3)
    raise AssertionError("unreachable")


def _wait_validation(server: Server, run_id: str) -> dict[str, Any]:
    last = None
    while True:
        run = _poll(server, f"/validations/{run_id}")
        if run["status"] != last:
            _say(f"  검사 {run['status']}")
            last = run["status"]
        if run["status"] in DONE:
            return run
        time.sleep(3)


def _print_steps(run: dict[str, Any]) -> None:
    for step in run.get("steps") or []:
        mark = "✓" if step["status"] == "passed" else "✗"
        _say(f"  {mark} {step['name']}: {step.get('detail') or ''}")


def cmd_deploy(args: argparse.Namespace) -> int:
    project = _project()
    server = Server(project)
    gate = server.request("POST", f"/projects/{project.name}/deploy-requests", body={"version": args.version, "reason": args.reason})
    _say(f"배포 요청: {project.name} {gate['version']} (변경 폭 {gate['upgrade_type']}, 검사 {gate['validation_policy_mode']}, "
         f"승인 {gate['approval_mode']})")
    seen: set[str] = set()
    while True:
        detail = _poll(server, f"/release-gates/{gate['gate_id']}")
        state = (detail["decision"], detail.get("deployment_status"))
        if state not in seen:
            seen.add(state)
            _report_gate(detail)
        if detail["decision"] in ("rejected", "canceled") or detail.get("deployment_status") in ("succeeded", "failed"):
            return 0 if detail.get("deployment_status") == "succeeded" else 1
        time.sleep(3)


def _report_gate(gate: dict[str, Any]) -> None:
    decision, deployment = gate["decision"], gate.get("deployment_status")
    if decision == "validating":
        _say("  Gate: validate Job으로 검사 중…")
    elif decision == "pending_approval":
        _say("  Gate 통과 → " + ("정책 자동 승인 중…" if gate["approval_mode"] == "auto" else "승인 대기 (console 화면)"))
    elif decision == "approved" and deployment == "running":
        if gate.get("validation"):
            _print_steps(gate["validation"])
        _say(f"  승인됨 ({'정책 자동 승인' if gate['approval_mode'] == 'auto' else '승인자'}) → 배포 Job 실행 중…")
    elif deployment == "succeeded":
        _say(f"  운영 반영 완료: {gate['agent_id']} {gate['version']} (UC Skill 내용이 이 버전으로 바뀌었습니다)")
    elif deployment == "failed":
        _say("  배포 실패: 서버 기록(deployments)을 확인하세요")
    elif decision == "rejected":
        _say(f"  반려: {gate.get('decision_reason') or ''}")


def cmd_promote(args: argparse.Namespace) -> int:
    project = Project.find()
    grants = Server(project).request("POST", f"/agents/{args.agent_id}/promote", body={"principals": args.to, "revoke": args.revoke})
    for grant in grants:
        verb = "부여" if grant["granted"] else "회수"
        _say(f"{grant['principal']}: {grant['permission']} {verb} ({grant['securable']})")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    project = Project.find()
    params = f"?build_type={args.type.replace('-', '_')}" if args.type else ""
    page = Server(project).request("GET", f"/agents{params}")
    rows = page["items"]
    if not rows:
        _say("등록된 에이전트가 없습니다")
        return 0
    _say(f"{'에이전트':<22} {'종류':<8} {'운영 버전':<10} {'최신':<8} {'상태':<11} 담당")
    for row in rows:
        _say(f"{row['agent_id']:<22} {row['build_type']:<8} {row.get('production_version') or '-':<10} "
             f"{row.get('latest_version') or '-':<8} {row['lifecycle']:<11} {row['owner']}")
    return 0


def cmd_load(args: argparse.Namespace) -> int:
    here = Project.find()
    server = Server(here if here.is_project else None)
    info = server.request("POST", f"/agents/{args.agent_id}/load", body={"version": args.version})
    if not info["allowed"]:
        _say("이 에이전트를 가져올 권한이 없습니다. 담당자에게 promote를 요청하세요")
        return 1
    if info.get("link"):
        _say(f"{args.agent_id}: {info['link']}")
        return 0
    dest = Path(args.dir or args.agent_id).resolve()
    if dest.exists() and any(dest.iterdir()):
        raise ValueError(f"{dest}가 비어 있지 않습니다. --dir로 다른 폴더를 고르세요")
    data = server.request("GET", f"/agents/{args.agent_id}/versions/{info['version']}/archive", raw=True)
    files = package.unpack(data, dest, info["archive"]["sha256"])
    project = Project.load(dest)
    sync(project)
    _say(f"가져옴: {args.agent_id} {info['version']} → {dest} (파일 {len(files)}개, 해시 확인)")
    for folder in project.skill_folders():
        _say(f"  skill {folder.name}")
    _say(f'next: cd {dest} && aops run "<질문>"')
    return 0


def add_commands(sub: argparse._SubParsersAction) -> dict[str, Any]:
    p = sub.add_parser("register", help="버전 저장 (dbx)")
    p.add_argument("--version")
    p.add_argument("--bump", choices=["fix", "minor", "major"])
    p = sub.add_parser("validate", help="관리자 정책 검사 (validate Job)")
    p.add_argument("--version")
    p = sub.add_parser("deploy", help="배포 요청 → 검사·승인 → 운영 반영")
    p.add_argument("--version")
    p.add_argument("--reason")
    p = sub.add_parser("promote", help="대상자 권한 부여")
    p.add_argument("agent_id")
    p.add_argument("--to", action="append", required=True, help="group:<계정 그룹> | user:<이메일> | sp:<application ID>")
    p.add_argument("--revoke", action="store_true")
    p = sub.add_parser("list", help="등록된 에이전트 목록")
    p.add_argument("--type", choices=["skill", "code", "no-code"])
    p = sub.add_parser("load", help="등록된 에이전트를 가져와 쓰기")
    p.add_argument("agent_id")
    p.add_argument("--version")
    p.add_argument("--dir")
    return {"register": cmd_register, "validate": cmd_validate, "deploy": cmd_deploy, "promote": cmd_promote,
            "list": cmd_list, "load": cmd_load}


def run(handler: Any, args: argparse.Namespace) -> int:
    try:
        return handler(args)
    except ServerError as error:
        print(f"aops: {error} (HTTP {error.status})", file=sys.stderr)
        return 2
