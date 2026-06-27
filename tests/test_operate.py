from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from marshal_cli.cli import main
from tests.marshal_support import (
    bool_value,
    gate_squad_a,
    init_two_squads,
    json_cli,
    parse_captured,
    run_cli,
    runner_command,
    squads_by_id,
    str_list,
    str_value,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_status_and_next_track_dependencies(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    init_two_squads(tmp_path, capsys)

    # When
    status = json_cli(("status", "--root", str(tmp_path)), capsys)
    nxt = json_cli(("next", "--root", str(tmp_path)), capsys)

    # Then
    by_id = squads_by_id(status)
    assert str_list(status["next_squads"]) == ("squad-a",)
    assert bool_value(by_id["squad-a"]["next_to_start"]) is True
    assert str_list(by_id["squad-a"]["blocks"]) == ("squad-b",)
    assert bool_value(by_id["squad-b"]["dependencies_satisfied"]) is False
    assert str_list(nxt["next_squads"]) == ("squad-a",)


def test_run_start_work_invokes_external_runner(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    init_two_squads(tmp_path, capsys)
    gate_squad_a(tmp_path, capsys)
    runner = runner_command(tmp_path)

    # When
    result = json_cli(
        (
            "run-start-work",
            "--root",
            str(tmp_path),
            "--squad",
            "squad-a",
            "--runner",
            runner,
        ),
        capsys,
    )

    # Then
    assert bool_value(result["dispatched"]) is True
    assert str_value(result["runner_stdout"]) == "ran squad-a"
    marker = (tmp_path / "runner-marker.txt").read_text(encoding="utf-8")
    assert marker == "squad-a|$start-work squad-a"
    ledger = (tmp_path / ".omo" / "squad" / "squad-a" / "ledger.jsonl").read_text(
        encoding="utf-8",
    )
    assert '"event":"dispatched"' in ledger


def test_failed_runner_is_not_marked_dispatched(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given a runner that exits non-zero
    init_two_squads(tmp_path, capsys)
    gate_squad_a(tmp_path, capsys)
    runner = runner_command(tmp_path, failing=True)

    # When run-start-work invokes it (exit 7 -> command exit 1)
    exit_code = main(
        (
            "run-start-work",
            "--root",
            str(tmp_path),
            "--squad",
            "squad-a",
            "--runner",
            runner,
        ),
    )
    result = parse_captured(capsys)

    # Then the failure is recorded distinctly and the squad stays runnable
    assert exit_code == 1
    assert bool_value(result["dispatched"]) is False
    ledger = (tmp_path / ".omo" / "squad" / "squad-a" / "ledger.jsonl").read_text(
        encoding="utf-8",
    )
    assert '"event":"dispatch-failed"' in ledger
    assert '"event":"dispatched"' not in ledger
    nxt = json_cli(("next", "--root", str(tmp_path)), capsys)
    assert str_list(nxt["next_squads"]) == ("squad-a",)


def test_dry_run_previews_without_a_runner(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given no runner configured at all
    monkeypatch.delenv("MARSHAL_START_WORK_RUNNER", raising=False)
    init_two_squads(tmp_path, capsys)
    gate_squad_a(tmp_path, capsys)

    # When previewing the dispatch
    result = json_cli(
        ("run-start-work", "--root", str(tmp_path), "--squad", "squad-a", "--dry-run"),
        capsys,
    )

    # Then the payload is previewed even though no runner is set
    assert str_value(result["mode"]) == "dry-run"
    assert str_list(result["runner"]) == ()
    assert str_value(result["command"]) == "$start-work squad-a"


def test_run_start_work_without_runner_explains_manual_mode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    monkeypatch.delenv("MARSHAL_START_WORK_RUNNER", raising=False)
    init_two_squads(tmp_path, capsys)
    gate_squad_a(tmp_path, capsys)

    # When / Then
    with pytest.raises(SystemExit) as raised:
        _ = main(("run-start-work", "--root", str(tmp_path), "--squad", "squad-a"))
    captured = capsys.readouterr()
    assert raised.value.code != 0
    assert "delegate-start-work for manual mode" in captured.err


def test_dispatch_blocks_until_dependencies_complete(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    init_two_squads(tmp_path, capsys)
    runner = runner_command(tmp_path)
    _ = run_cli(
        ("state", "init", "--root", str(tmp_path), "--squad", "squad-b"),
        capsys,
    )

    # When / Then
    with pytest.raises(SystemExit) as raised:
        _ = main(
            (
                "dispatch",
                "--root",
                str(tmp_path),
                "--squad",
                "squad-b",
                "--runner",
                runner,
            ),
        )
    captured = capsys.readouterr()
    assert raised.value.code != 0
    assert "dependencies not done: squad-a" in captured.err
