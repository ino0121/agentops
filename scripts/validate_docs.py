"""Write docs/validate.md from the self-check rules (aops.validate).

    uv run python scripts/validate_docs.py
"""

from pathlib import Path

from aops.validate import markdown

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    (ROOT / "docs" / "validate.md").write_text(markdown(), encoding="utf-8")
    print("wrote docs/validate.md")


if __name__ == "__main__":
    main()
