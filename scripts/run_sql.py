"""Run a SQL file against the e2e workspace, one statement at a time.

Reads AOPS_E2E_PROFILE, AOPS_E2E_SCHEMA and AOPS_E2E_WAREHOUSE_ID from .env.e2e,
replaces __SCHEMA__ in the file, and stops at the first failed statement.

    python scripts/run_sql.py bundles/registry/tables.sql
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def statements(sql: str) -> list[str]:
    body = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    return [part.strip() for part in body.split(";\n") if part.strip().rstrip(";").strip()]


def api(profile: str, method: str, path: str, payload: dict | None = None) -> dict:
    command = ["databricks", "api", method, path, "--profile", profile]
    if payload is not None:
        command += ["--json", json.dumps(payload)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return json.loads(result.stdout or "{}")


def execute(profile: str, warehouse_id: str, statement: str) -> dict:
    response = api(profile, "post", "/api/2.0/sql/statements", {
        "warehouse_id": warehouse_id,
        "statement": statement,
        "wait_timeout": "50s",
        "format": "JSON_ARRAY",
        "disposition": "INLINE",
    })
    while response.get("status", {}).get("state") in {"PENDING", "RUNNING"}:
        time.sleep(2)
        response = api(profile, "get", f"/api/2.0/sql/statements/{response['statement_id']}")
    return response


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    env = load_env(ROOT / ".env.e2e")
    profile, schema, warehouse_id = env["AOPS_E2E_PROFILE"], env["AOPS_E2E_SCHEMA"], env["AOPS_E2E_WAREHOUSE_ID"]
    sql = Path(sys.argv[1]).read_text(encoding="utf-8").replace("__SCHEMA__", schema)
    items = statements(sql)
    for index, statement in enumerate(items, 1):
        response = execute(profile, warehouse_id, statement)
        status = response.get("status", {})
        summary = " ".join(statement.split())[:90]
        if status.get("state") != "SUCCEEDED":
            print(f"[{index}/{len(items)}] FAILED {summary}")
            print("  " + (status.get("error") or {}).get("message", str(status))[:600])
            return 1
        print(f"[{index}/{len(items)}] ok {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
