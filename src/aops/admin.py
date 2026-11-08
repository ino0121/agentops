"""`aops admin setup`: the organisation's shared pieces, shown first and applied with `--apply`.

Steps: registry tables, the active policy, the aops package for the Jobs, the aops server app and the
grants its service principal needs. Run by a workspace admin with their own Databricks login.
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import tempfile
from importlib import resources
from pathlib import Path
from typing import Any

STEPS = ("tables", "policy", "dist", "app", "grants")
REPO = Path(__file__).resolve().parents[2]
APP_REQUIREMENTS = "fastapi>=0.162\nuvicorn>=0.54\npython-multipart>=0.0.20\ndatabricks-sdk>=0.158\n"


def ddl() -> str:
    repo_file = REPO / "bundles" / "registry" / "tables.sql"
    if repo_file.is_file():
        return repo_file.read_text(encoding="utf-8")
    return resources.files("aops.dbx").joinpath("tables.sql").read_text(encoding="utf-8")


def statements(sql: str) -> list[str]:
    body = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    return [part.strip().rstrip(";") for part in body.split(";\n") if part.strip().rstrip(";").strip()]


def add_command(sub: argparse._SubParsersAction) -> None:
    admin = sub.add_parser("admin", help="조직 공통 자원 준비 (관리자)")
    actions = admin.add_subparsers(dest="action", required=True)
    setup = actions.add_parser("setup", help="레지스트리·정책·Job용 패키지·aops 서버·권한 (미리보기, --apply로 실행)")
    setup.add_argument("--profile", required=True, help="관리자의 Databricks CLI 프로필")
    setup.add_argument("--registry", required=True, help="레지스트리 스키마 <catalog>.<schema>")
    setup.add_argument("--warehouse", required=True, help="SQL warehouse ID")
    setup.add_argument("--app", default="aops-server", help="aops 서버 앱 이름")
    setup.add_argument("--approval-mode", choices=["required", "optional", "auto"], default="required")
    setup.add_argument("--validation-mode", choices=["mandatory", "optional", "exempt"], default="mandatory")
    setup.add_argument("--approver-group", default="")
    setup.add_argument("--only", help=f"쉼표로 고른 단계만 ({', '.join(STEPS)})")
    setup.add_argument("--apply", action="store_true", help="미리보기 대신 실행")


def cmd_admin(args: argparse.Namespace) -> int:
    from databricks.sdk import WorkspaceClient

    from .dbx.sql import Sql

    steps = [s.strip() for s in args.only.split(",")] if args.only else list(STEPS)
    w = WorkspaceClient(profile=args.profile)
    sql = Sql(w, args.warehouse, args.registry)
    catalog, schema = args.registry.split(".")
    me = w.current_user.me().user_name
    print(f"aops admin setup · {w.config.host} · {args.registry} · {'실행' if args.apply else '미리보기'} (관리자 {me})")

    if "tables" in steps:
        stmts = statements(ddl().replace("__SCHEMA__", args.registry))
        print(f"\n[tables] 레지스트리 테이블·뷰: 문 {len(stmts)}개 (IF NOT EXISTS, 다시 실행해도 됨)")
        if args.apply:
            for stmt in stmts:
                sql.run(stmt)
            print("  ok")

    if "policy" in steps:
        body = {"validation_mode": args.validation_mode, "approval_mode": args.approval_mode,
                "approval_channel": "console", "approver_group": args.approver_group, "required_approvals": 1,
                "security_levels": ["general", "important", "secret"]}
        print(f"\n[policy] 정책: {json.dumps(body, ensure_ascii=False)}")
        if args.apply:
            current = sql.one(f"SELECT policy_version, body FROM {sql.table('policies')} WHERE status = 'active' "
                              "ORDER BY policy_version DESC LIMIT 1")
            if current and json.loads(current["body"]) == body:
                print(f"  같은 정책이 이미 적용돼 있습니다 (버전 {current['policy_version']})")
            else:
                version = (int(current["policy_version"]) if current else 0) + 1
                sql.run(f"UPDATE {sql.table('policies')} SET status = 'retired' WHERE status = 'active'")
                sql.run(f"INSERT INTO {sql.table('policies')} VALUES (:v, 'active', parse_json(:b), :by, current_timestamp())",
                        {"v": version, "b": body, "by": me})
                print(f"  정책 버전 {version} 적용")

    wheel_path = None
    if "dist" in steps or "app" in steps:
        print(f"\n[dist] Job용 aops 패키지: uv build → /Volumes/{catalog}/{schema}/aops_dist/")
        if args.apply:
            sql.run(f"CREATE VOLUME IF NOT EXISTS {args.registry}.aops_dist COMMENT 'aops validate·배포 Job이 설치하는 aops 패키지'")
            out = Path(tempfile.mkdtemp(prefix="aops-dist-"))
            subprocess.run(["uv", "build", "--wheel", "--out-dir", str(out)], cwd=REPO, check=True, capture_output=True)
            wheel = next(out.glob("aops_cli-*.whl"))
            wheel_path = f"/Volumes/{catalog}/{schema}/aops_dist/{wheel.name}"
            w.files.upload(wheel_path, io.BytesIO(wheel.read_bytes()), overwrite=True)
            print(f"  {wheel_path}")
        else:
            wheel_path = f"/Volumes/{catalog}/{schema}/aops_dist/aops_cli-<version>-py3-none-any.whl"

    app = None
    if "app" in steps:
        print(f"\n[app] aops 서버 앱 {args.app}: SQL warehouse 자원(CAN USE), 사용자 권한 범위 files, 코드 배포")
        if args.apply:
            app = _deploy_app(w, args, wheel_path, me)
            print(f"  {app.url}  (서비스 주체 {app.service_principal_client_id})")

    if "grants" in steps:
        if app is None:
            try:
                app = w.apps.get(args.app)
            except Exception:
                app = None
        sp = app.service_principal_client_id if app else "<앱 서비스 주체>"
        grants = [
            f"GRANT USE CATALOG ON CATALOG `{catalog}` TO `{sp}`",
            f"GRANT USE SCHEMA, CREATE VOLUME, SELECT, MODIFY ON SCHEMA `{catalog}`.`{schema}` TO `{sp}`",
            f"GRANT READ VOLUME ON VOLUME `{catalog}`.`{schema}`.`aops_dist` TO `{sp}`",
        ]
        print("\n[grants] aops 서버 서비스 주체 권한 (사람에게는 USE·SELECT만 준다)")
        for grant in grants:
            print(f"  {grant}")
        if args.apply:
            for grant in grants:
                sql.run(grant)
            print("  ok")

    if not args.apply:
        print("\n미리보기입니다. 실행하려면 --apply를 붙이세요.")
    return 0


def _deploy_app(w: Any, args: argparse.Namespace, wheel_path: str | None, me: str) -> Any:
    from databricks.sdk.service.apps import App, AppDeployment, AppResource, AppResourceSqlWarehouse, \
        AppResourceSqlWarehouseSqlWarehousePermission

    try:
        app = w.apps.get(args.app)
    except Exception:
        resource = AppResource(name="sql-warehouse", sql_warehouse=AppResourceSqlWarehouse(
            id=args.warehouse, permission=AppResourceSqlWarehouseSqlWarehousePermission.CAN_USE))
        app = w.apps.create_and_wait(App(name=args.app, description="aops 서버: console 화면과 /api/v1",
                                         resources=[resource], user_api_scopes=["files"]))
    build = Path(tempfile.mkdtemp(prefix="aops-app-"))
    shutil.copytree(REPO / "src" / "aops", build / "src" / "aops", ignore=shutil.ignore_patterns("__pycache__"))
    (build / "requirements.txt").write_text(APP_REQUIREMENTS)
    env = [{"name": "PYTHONPATH", "value": "src"}, {"name": "AOPS_REGISTRY", "value": args.registry},
           {"name": "AOPS_WAREHOUSE_ID", "valueFrom": "sql-warehouse"}, {"name": "AOPS_DIST_WHEEL", "value": wheel_path or ""}]
    command = ["python", "-m", "uvicorn", "aops.server.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
    lines = ["command: " + json.dumps(command), "env:"]
    for item in env:
        key = "valueFrom" if "valueFrom" in item else "value"
        lines.append(f"  - name: {item['name']}\n    {key}: {json.dumps(item[key])}")
    (build / "app.yaml").write_text("\n".join(lines) + "\n")
    target = f"/Workspace/Users/{me}/{args.app}"
    subprocess.run(["databricks", "workspace", "import-dir", str(build), target, "--overwrite", "-p", args.profile],
                   check=True, capture_output=True)
    w.apps.deploy_and_wait(args.app, AppDeployment(source_code_path=target))
    return w.apps.get(args.app)
