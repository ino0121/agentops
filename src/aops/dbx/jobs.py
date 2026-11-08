"""`aops-job`: the entry point of the validate and deploy Lakeflow Jobs (python wheel task)."""

from __future__ import annotations

import argparse
import sys

from .service import Config, Service


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aops-job")
    parser.add_argument("--kind", choices=["validate", "deploy"], required=True)
    parser.add_argument("--id", required=True, help="validation_run_id (validate) or gate_id (deploy)")
    parser.add_argument("--registry", required=True)
    parser.add_argument("--warehouse", required=True)
    args = parser.parse_args(argv)
    service = Service(Config(registry=args.registry, warehouse_id=args.warehouse))
    if args.kind == "validate":
        status = service.run_validation(args.id)
        print(f"validation {args.id}: {status}")
        return 0 if status in ("passed", "failed") else 1
    status = service.run_deploy(args.id)
    print(f"deploy {args.id}: {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
