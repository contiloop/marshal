from pathlib import Path

import pytest

from marshal_cli.cli import main
from marshal_cli.jsonio import read_json
from marshal_cli.ledger import latest_attempt_events
from marshal_cli.models import JsonMapping, JsonValue, Report, StartGateSource
from marshal_cli.platoon import create_assignment_packets
from marshal_cli.squad_state import initialize_squad_state, route_squad_report
from marshal_cli.start_gate import StartGateRequest, run_start_gate


def test_state_init_writes_sync_state_when_assignment_exists(tmp_path: Path) -> None:
    # Given
    _create_assignment(tmp_path)

    # When
    result = initialize_squad_state(tmp_path, "squad-a", ".omo/plans/squad-a.md")

    # Then
    state = read_json(tmp_path / ".omo" / "squad" / "squad-a" / "state.json")
    assert result.state_path == tmp_path / ".omo" / "squad" / "squad-a" / "state.json"
    assert state["squad_id"] == "squad-a"
    assert state["current_stage"] == "sync"
    assert state["active_attempt"] == 1
    assert state["plan_artifact"] == ".omo/plans/squad-a.md"


def test_route_sends_intent_unclear_to_sync_when_reported(tmp_path: Path) -> None:
    # Given
    _create_initialized_state(tmp_path)

    # When
    result = route_squad_report(
        tmp_path,
        "squad-a",
        Report.from_mapping(
            {
                "source": "work",
                "type": "intent_unclear",
                "detail": "goal needs product decision",
                "findings": ["owner unknown"],
                "evidence": ["work.log"],
            },
        ),
    )

    # Then
    state = read_json(tmp_path / ".omo" / "squad" / "squad-a" / "state.json")
    assert result.current_stage == "sync"
    assert state["current_stage"] == "sync"
    assert state["active_attempt"] == 1


def test_route_sends_design_flaw_to_plan_and_increments_attempt(
    tmp_path: Path,
) -> None:
    # Given
    _create_initialized_state(tmp_path)

    # When
    result = route_squad_report(
        tmp_path,
        "squad-a",
        Report.from_mapping(
            {
                "source": "work",
                "type": "design_flaw",
                "detail": "unexpected dependency",
                "findings": ["pub/sub required"],
                "evidence": ["worker.log"],
            },
        ),
    )

    # Then
    state = read_json(tmp_path / ".omo" / "squad" / "squad-a" / "state.json")
    backtrack = _json_object_list(state["backtrack_log"])[-1]
    assert result.current_stage == "plan"
    assert state["current_stage"] == "plan"
    assert state["active_attempt"] == 2
    assert backtrack["to"] == "plan"
    assert backtrack["findings"] == ["pub/sub required"]


def test_route_appends_aborted_and_backtrack_ledger_events(tmp_path: Path) -> None:
    # Given
    _create_initialized_state(tmp_path)
    report = Report.from_mapping(
        {
            "source": "work",
            "type": "design_flaw",
            "detail": "unexpected dependency",
            "findings": ["pub/sub required"],
            "evidence": ["worker.log"],
        },
    )

    # When
    result = route_squad_report(tmp_path, "squad-a", report)

    # Then
    ledger_path = tmp_path / ".omo" / "squad" / "squad-a" / "ledger.jsonl"
    ledger_text = ledger_path.read_text(encoding="utf-8")
    assert result.active_attempt == 2
    assert '"event":"attempt-aborted"' in ledger_text
    assert '"event":"backtrack"' in ledger_text
    assert '"attempt":1' in ledger_text
    assert "pub/sub required" in ledger_text
    assert "worker.log" in ledger_text

    _ = run_start_gate(
        StartGateRequest(
            root=tmp_path,
            squad_id="squad-a",
            source=StartGateSource.PLAN,
            applied_example="If plan restarts, verify attempt 2 before work.",
            plan_artifact=None,
        ),
    )
    latest = latest_attempt_events(tmp_path, "squad-a")
    assert latest.active_attempt == 2
    assert latest.event_lines
    assert all(_has_attempt(line, 2) for line in latest.event_lines)
    assert all(not _has_attempt(line, 1) for line in latest.event_lines)


def test_route_keeps_execution_failure_in_work_without_increment(
    tmp_path: Path,
) -> None:
    # Given
    _create_initialized_state(tmp_path)

    # When
    result = route_squad_report(
        tmp_path,
        "squad-a",
        Report.from_mapping(
            {
                "source": "work",
                "type": "execution_failure",
                "detail": "unit test failed",
                "findings": ["cache miss"],
                "evidence": ["pytest.log"],
            },
        ),
    )

    # Then
    state = read_json(tmp_path / ".omo" / "squad" / "squad-a" / "state.json")
    assert result.current_stage == "work"
    assert state["current_stage"] == "work"
    assert state["active_attempt"] == 1
    assert state["backtrack_log"] == []


def test_route_sends_blocked_to_blocked_with_escalation_detail(
    tmp_path: Path,
) -> None:
    # Given
    _create_initialized_state(tmp_path)

    # When
    result = route_squad_report(
        tmp_path,
        "squad-a",
        Report.from_mapping(
            {
                "source": "work",
                "type": "blocked",
                "detail": "vendor credential missing",
                "findings": ["cannot access cache"],
                "evidence": ["blocked.log"],
            },
        ),
    )

    # Then
    state = read_json(tmp_path / ".omo" / "squad" / "squad-a" / "state.json")
    latest_history = _json_object_list(state["stage_history"])[-1]
    assert result.current_stage == "blocked"
    assert result.escalation_detail == "vendor credential missing"
    assert state["current_stage"] == "blocked"
    assert latest_history["result"] == "blocked: vendor credential missing"


def test_state_and_route_commands_use_real_cli_surface(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    _create_assignment(tmp_path)

    # When
    init_code = main(("state", "init", "--root", str(tmp_path), "--squad", "squad-a"))
    route_code = main(
        (
            "route",
            "--root",
            str(tmp_path),
            "--squad",
            "squad-a",
            "--source",
            "work",
            "--type",
            "design_flaw",
            "--detail",
            "unexpected dependency",
            "--finding",
            "pub/sub required",
        ),
    )

    # Then
    captured = capsys.readouterr()
    state = read_json(tmp_path / ".omo" / "squad" / "squad-a" / "state.json")
    assert init_code == 0
    assert route_code == 0
    assert '"current_stage": "plan"' in captured.out
    assert state["current_stage"] == "plan"


def _create_initialized_state(root: Path) -> None:
    _create_assignment(root)
    plan_path = root / ".omo" / "plans" / "squad-a.md"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    _ = plan_path.write_text("# squad-a plan\n", encoding="utf-8")
    _ = initialize_squad_state(root, "squad-a", ".omo/plans/squad-a.md")


def _create_assignment(root: Path) -> None:
    _ = create_assignment_packets(
        root=root,
        platoon_goal="Ship cache",
        scope_specs=("squad-a|Redis cache|-",),
    )


def _json_object_list(value: JsonValue) -> tuple[JsonMapping, ...]:
    if isinstance(value, list):
        return tuple(_json_object(item) for item in value)
    pytest.fail("expected JSON object list")


def _json_object(value: JsonValue) -> JsonMapping:
    if isinstance(value, dict):
        return value
    pytest.fail("expected JSON object")


def _has_attempt(event_line: str, attempt: int) -> bool:
    return f'"attempt":{attempt}' in event_line or f'"attempt": {attempt}' in event_line
