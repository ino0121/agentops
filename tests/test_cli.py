import pytest

from aops import __version__
from aops.cli import main


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"aops {__version__}"


def test_unknown_harness_is_one_line_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["session", "switch", "--harness", "nope"]) == 2
    assert capsys.readouterr().err.strip().startswith("aops: unknown harness 'nope'")


def test_init_creates_a_skill_agent(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["init", "price-helper"]) == 0
    assert (tmp_path / "price-helper" / ".claude/skills/my-skill/SKILL.md").is_file()
    assert main(["init", "Bad Name"]) == 2
