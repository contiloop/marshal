from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from marshal_cli.cli import main
from marshal_cli.jsonio import parse_json_object

if TYPE_CHECKING:
    from collections.abc import Sequence

    from marshal_cli.models import JsonObject, JsonValue

_CLI_SOURCE = Path("<cli>")
_RUNNER_SOURCE = """\
import json
import os
import sys

payload = json.load(sys.stdin)
marker = os.path.join(os.environ["MARSHAL_ROOT"], "runner-marker.txt")
with open(marker, "w", encoding="utf-8") as handle:
    handle.write(os.environ["MARSHAL_SQUAD"] + "|" + payload["command"])
sys.stdout.write("ran " + payload["squad_id"])
"""


def _run(arguments: Sequence[str], capsys: pytest.CaptureFixture[str]) -> str:
    exit_code = main(arguments)
    captured = capsys.readouterr()
    assert exit_code == 0, captured.err
    assert captured.err == ""
    return captured.out


def _json(arguments: Sequence[str], capsys: pytest.CaptureFixture[str]) -> JsonObject:
    return parse_json_object(_run(arguments, capsys), _CLI_SOURCE)


def _obj(value: JsonValue) -> JsonObject:
    if isinstance(value, dict):
        return value
    pytest.fail("expected JSON object")


def _str(value: JsonValue) -> str:
    if isinstance(value, str):
        return value
    pytest.fail("expected JSON string")


def _bool_value(value: JsonValue) -> bool:
    if isinstance(value, bool):
        return value
    pytest.fail("expected JSON bool")


def _str_list(value: JsonValue) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(_str(item) for item in value)
    pytest.fail("expected string list")


def _squads_by_id(status: JsonObject) -> dict[str, JsonObject]:
    squads = status["squads"]
    if not isinstance(squads, list):
        pytest.fail("expected squad list")
    return {_str(_obj(squad)["squad_id"]): _obj(squad) for squad in squads}


def _init_two_squads(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plan = root / ".omo" / "plans" / "squad-a.md"
    plan.parent.mkdir(parents=True)
    _ = plan.write_text("# plan\n", encoding="utf-8")
    _ = _run(
        (
            "init",
            "--root",
            str(root),
            "--goal",
            "Ship cache and dashboard",
            "--scope",
            "squad-a|Redis cache|-",
            "--scope",
            "squad-b|Dashboard|squad-a",
        ),
        capsys,
    )


def _gate_squad_a(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _ = _run(
        (
            "state",
            "init",
            "--root",
            str(root),
            "--squad",
            "squad-a",
            "--plan",
            ".omo/plans/squad-a.md",
        ),
        capsys,
    )
    _ = _run(
        (
            "start-gate",
            "--root",
            str(root),
            "--squad",
            "squad-a",
            "--source",
            "assignment",
            "--example",
            "verify scope before work",
        ),
        capsys,
    )


def _runner_command(tmp_path: Path) -> str:
    script = tmp_path / "runner.py"
    _ = script.write_text(_RUNNER_SOURCE, encoding="utf-8")
    return f"{sys.executable} {script}"


def test_status_and_next_track_dependencies(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    _init_two_squads(tmp_path, capsys)

    # When
    status = _json(("status", "--root", str(tmp_path)), capsys)
    nxt = _json(("next", "--root", str(tmp_path)), capsys)

    # Then
    by_id = _squads_by_id(status)
    assert _str_list(status["next_squads"]) == ("squad-a",)
    assert _bool_value(by_id["squad-a"]["next_to_start"]) is True
    assert _str_list(by_id["squad-a"]["blocks"]) == ("squad-b",)
    assert _bool_value(by_id["squad-b"]["dependencies_satisfied"]) is False
    assert _str_list(nxt["next_squads"]) == ("squad-a",)


def test_run_start_work_invokes_external_runner(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    _init_two_squads(tmp_path, capsys)
    _gate_squad_a(tmp_path, capsys)
    runner = _runner_command(tmp_path)

    # When
    result = _json(
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
    assert _bool_value(result["dispatched"]) is True
    assert _str(result["runner_stdout"]) == "ran squad-a"
    marker = (tmp_path / "runner-marker.txt").read_text(encoding="utf-8")
    assert marker == "squad-a|$start-work squad-a"
    ledger = (tmp_path / ".omo" / "squad" / "squad-a" / "ledger.jsonl").read_text(
        encoding="utf-8",
    )
    assert '"event":"dispatched"' in ledger


def test_run_start_work_without_runner_explains_manual_mode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    monkeypatch.delenv("MARSHAL_START_WORK_RUNNER", raising=False)
    _init_two_squads(tmp_path, capsys)
    _gate_squad_a(tmp_path, capsys)

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
    _init_two_squads(tmp_path, capsys)
    runner = _runner_command(tmp_path)
    _ = _run(("state", "init", "--root", str(tmp_path), "--squad", "squad-b"), capsys)

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


def test_complete_requires_real_evidence_and_advances_waves(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    _init_two_squads(tmp_path, capsys)
    _gate_squad_a(tmp_path, capsys)
    evidence = tmp_path / ".omo" / "evidence" / "a-e2e.log"
    evidence.parent.mkdir(parents=True)
    _ = evidence.write_text("RED/GREEN; real-surface proof\n", encoding="utf-8")

    # When / Then: missing evidence file is rejected
    with pytest.raises(SystemExit) as raised:
        _ = main(
            (
                "complete",
                "--root",
                str(tmp_path),
                "--squad",
                "squad-a",
                "--evidence",
                ".omo/evidence/missing.log",
                "--detail",
                "done",
            ),
        )
    captured = capsys.readouterr()
    assert raised.value.code != 0
    assert "evidence files do not exist" in captured.err

    # When: a real evidence file is supplied
    completed = _json(
        (
            "complete",
            "--root",
            str(tmp_path),
            "--squad",
            "squad-a",
            "--evidence",
            ".omo/evidence/a-e2e.log",
            "--detail",
            "cache shipped",
        ),
        capsys,
    )
    nxt = _json(("next", "--root", str(tmp_path)), capsys)

    # Then
    assert _str(completed["current_stage"]) == "done"
    assert _str_list(nxt["next_squads"]) == ("squad-b",)


def test_abort_blocks_delegation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    _init_two_squads(tmp_path, capsys)
    _gate_squad_a(tmp_path, capsys)

    # When
    aborted = _json(
        (
            "abort",
            "--root",
            str(tmp_path),
            "--squad",
            "squad-a",
            "--reason",
            "user changed direction",
        ),
        capsys,
    )

    # Then
    assert _str(aborted["current_stage"]) == "aborted"
    with pytest.raises(SystemExit) as raised:
        _ = main(("delegate-start-work", "--root", str(tmp_path), "--squad", "squad-a"))
    captured = capsys.readouterr()
    assert raised.value.code != 0
    assert "squad is aborted" in captured.err


def test_evidence_check_strict_requires_real_surface(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    _init_two_squads(tmp_path, capsys)
    _gate_squad_a(tmp_path, capsys)

    # When
    report = _json(
        ("evidence", "check", "--root", str(tmp_path), "--squad", "squad-a"),
        capsys,
    )
    strict_code = main(
        (
            "evidence",
            "check",
            "--root",
            str(tmp_path),
            "--squad",
            "squad-a",
            "--strict",
            "--require-real-surface",
        ),
    )
    _ = capsys.readouterr()

    # Then: start-gate recorded real file paths but no real-surface marker yet
    assert _bool_value(report["all_paths_present"]) is True
    assert _bool_value(report["has_real_surface"]) is False
    assert strict_code == 1


def test_handover_emits_packet_and_next_action(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    _init_two_squads(tmp_path, capsys)
    _gate_squad_a(tmp_path, capsys)

    # When
    packet = _json(("handover", "--root", str(tmp_path), "--squad", "squad-a"), capsys)

    # Then
    assert _str(packet["current_stage"]) == "sync"
    assert "sync" in _str(packet["next_action"]).lower()
    platoon = _obj(_obj(packet["packet"])["platoon"])
    assert _str_list(platoon["next_squads"]) == ("squad-a",)
    assert (tmp_path / ".omo" / "squad" / "squad-a" / "handover.json").exists()
