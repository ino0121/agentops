from __future__ import annotations

import argparse

from . import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aops", description="aops v2")
    parser.add_argument("--version", action="version", version=f"aops {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0
