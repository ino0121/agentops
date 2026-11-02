import pytest

from codex_agentops import __version__
from codex_agentops.cli import main


def test_version_flag_prints_v2(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"aops {__version__}"
