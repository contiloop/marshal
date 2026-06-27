from pathlib import Path

import pytest

from marshal_cli.cli import main
from marshal_cli.jsonio import read_json
from marshal_cli.ledger import (
    LedgerAppendRequest,
    append_ledger_entry,
    latest_attempt_events,
)
from marshal_cli.models import JsonMapping, JsonValue, Report
from marshal_cli.platoon import create_assignment_packets
from marshal_cli.squad_state import initialize_squad_state, route_squad_report


def test_latest_attempt_events_exclude_aborted_attempt_history(
    tmp_path: Path,
) -> None:
    # Given
    _create_initialized_state(tmp_path)
    _ = append_ledger_entry(
        tmp_path,
        LedgerAppendRequest(
            squad_id="squad-a",
            event="task-started",
            attempt=1,
            stage="work",
            task="worker-a",
            detail="started",
            findings=(),
            evidence=(),
        ),
    )
    _ = append_ledger_entry(
        tmp_path,
        LedgerAppendRequest(
            squad_id="squad-a",
            event="backtrack",
            attempt=1,
            stage="work",
            task="worker-a",
            detail="design flaw",
            findings=("dependency unexpected",),
            evidence=(),
        ),
    )
    _ = route_squad_report(
        tmp_path,
        "squad-a",
        Report.from_mapping(
            {
                "source": "work",
                "type": "design_flaw",
                "detail": "dependency unexpected",
                "findings": ["dependency unexpected"],
                "evidence": [],
            },
        ),
    )
    _ = append_ledger_entry(
        tmp_path,
        LedgerAppendRequest(
            squad_id="squad-a",
            event="task-started",
            attempt=2,
            stage="plan",
            task="replan",
            detail="restarted",
            findings=(),
            evidence=(),
        ),
    )

    # When
    latest = latest_attempt_events(tmp_path, "squad-a")

    # Then
    ledger_path = tmp_path / ".omo" / "squad" / "squad-a" / "ledger.jsonl"
    raw_lines = ledger_path.read_text(encoding="utf-8").splitlines()
    assert len(raw_lines) == 5
    assert all('"attempt":1' in line for line in raw_lines[:4])
    assert any('"event":"attempt-aborted"' in line for line in raw_lines)
    assert any('"event":"backtrack"' in line for line in raw_lines)
    assert latest.event_lines == (raw_lines[4],)
    assert latest.active_attempt == 2
    assert latest.ledger_path == ledger_path


def test_ledger_commands_use_real_cli_surface(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    _create_initialized_state(tmp_path)
    _ = main(
        (
            "ledger",
            "append",
            "--root",
            str(tmp_path),
            "--squad",
            "squad-a",
            "--event",
            "task-started",
            "--attempt",
            "1",
            "--stage",
            "work",
            "--task",
            "worker-a",
            "--detail",
            "started",
        ),
    )
    _ = route_squad_report(
        tmp_path,
        "squad-a",
        Report.from_mapping(
            {
                "source": "work",
                "type": "design_flaw",
                "detail": "dependency unexpected",
                "findings": ["dependency unexpected"],
                "evidence": [],
            },
        ),
    )
    _ = main(
        (
            "ledger",
            "append",
            "--root",
            str(tmp_path),
            "--squad",
            "squad-a",
            "--event",
            "task-started",
            "--attempt",
            "2",
            "--stage",
            "plan",
            "--task",
            "replan",
            "--detail",
            "restarted",
            "--finding",
            "plan updated",
            "--evidence",
            "plan.log",
        ),
    )
    _ = capsys.readouterr()

    # When
    latest_code = main(
        ("ledger", "latest", "--root", str(tmp_path), "--squad", "squad-a"),
    )

    # Then
    captured = capsys.readouterr()
    assert latest_code == 0
    assert '"active_attempt": 2' in captured.out
    assert '"attempt": 2' in captured.out
    assert '"attempt": 1' not in captured.out
    assert '"plan updated"' in captured.out
    assert '"plan.log"' in captured.out


def test_malformed_ledger_append_fails_without_appending(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    _create_initialized_state(tmp_path)
    ledger_path = tmp_path / ".omo" / "squad" / "squad-a" / "ledger.jsonl"
    before = _line_count(ledger_path)

    # When
    with pytest.raises(SystemExit) as raised:
        _ = main(
            (
                "ledger",
                "append",
                "--root",
                str(tmp_path),
                "--squad",
                "squad-a",
                "--event",
                "task-started",
                "--attempt",
                "0",
                "--stage",
                "bad",
                "--task",
                "",
                "--detail",
                "",
            ),
        )

    # Then
    captured = capsys.readouterr()
    assert raised.value.code != 0
    assert _line_count(ledger_path) == before
    assert "attempt" in captured.err
    assert "invalid" in captured.err


def _create_initialized_state(root: Path) -> None:
    _create_assignment(root)
    _ = initialize_squad_state(root, "squad-a", None)


def _create_assignment(root: Path) -> None:
    _ = create_assignment_packets(
        root=root,
        platoon_goal="Ship cache",
        scope_specs=("squad-a|Redis cache|-",),
    )


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def _json_object_list(value: JsonValue) -> tuple[JsonMapping, ...]:
    if isinstance(value, list):
        return tuple(_json_object(item) for item in value)
    pytest.fail("expected JSON object list")


def _json_object(value: JsonValue) -> JsonMapping:
    if isinstance(value, dict):
        return value
    pytest.fail("expected JSON object")


def test_ledger_state_round_trip_keeps_required_state_fields(tmp_path: Path) -> None:
    # Given
    _create_initialized_state(tmp_path)

    # When
    state = read_json(tmp_path / ".omo" / "squad" / "squad-a" / "state.json")

    # Then
    history = _json_object_list(state["stage_history"])
    assert state["active_attempt"] == 1
    assert history[0]["stage"] == "sync"
