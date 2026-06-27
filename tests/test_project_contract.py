from importlib.metadata import entry_points, version

import pytest

from marshal_cli import __version__
from marshal_cli.cli import main


def test_package_version_matches_distribution_when_imported() -> None:
    assert __version__ == version("marshal")


def test_console_script_points_to_cli_main() -> None:
    matches = tuple(
        entry_point
        for entry_point in entry_points(group="console_scripts")
        if entry_point.name == "marshal"
    )

    assert len(matches) == 1
    assert matches[0].value == "marshal_cli.cli:main"


def test_main_prints_help_when_no_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(())

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "usage:" in captured.out
    assert "marshal" in captured.out
    assert "delegate-start-work" in captured.out


def test_state_group_prints_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        _ = main(("state", "--help"))

    captured = capsys.readouterr()

    assert raised.value.code == 0
    assert "usage: marshal state" in captured.out
    assert "state init" in captured.out


def test_ledger_group_prints_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        _ = main(("ledger", "--help"))

    captured = capsys.readouterr()

    assert raised.value.code == 0
    assert "usage: marshal ledger" in captured.out
    assert "ledger latest" in captured.out


def test_main_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        _ = main(("--version",))

    captured = capsys.readouterr()

    assert raised.value.code == 0
    assert "marshal 0.1.0" in captured.out


def test_unknown_command_fails_clearly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        _ = main(("not-a-command",))

    captured = capsys.readouterr()

    assert raised.value.code != 0
    assert "unknown command: not-a-command" in captured.err
