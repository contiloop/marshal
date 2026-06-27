from pathlib import Path

import pytest

from marshal_cli.cli import main
from marshal_cli.delegate import build_delegation_payload
from marshal_cli.jsonio import read_json, write_json
from marshal_cli.ledger import LedgerAppendRequest, append_ledger_entry
from marshal_cli.models import JsonMapping, JsonValue, Report, StartGateSource
from marshal_cli.platoon import create_assignment_packets
from marshal_cli.squad_state import initialize_squad_state, route_squad_report
from marshal_cli.start_gate import StartGateRequest, run_start_gate

CONTRACT_KEYS = (
    "squad_id",
    "plan",
    "state",
    "ledger",
    "assignment",
    "active_attempt",
    "start_gate_status",
    "command",
    "payload",
)


def test_delegate_start_work_emits_mvp_contract_after_passed_gate(
    tmp_path: Path,
) -> None:
    # Given
    _create_started_squad(tmp_path)

    # When
    result = build_delegation_payload(tmp_path, "squad-a")
    payload = result.to_jsonable()

    # Then
    nested_payload = _json_object(payload["payload"])
    latest_events = _string_list(nested_payload["latest_ledger_events"])
    assert tuple(payload) == CONTRACT_KEYS
    assert payload["squad_id"] == "squad-a"
    assert payload["plan"] == ".omo/plans/squad-a.md"
    assert payload["command"] == "$start-work squad-a"
    assert payload["start_gate_status"] == "passed"
    assert payload["active_attempt"] == 2
    assert payload["state"] == str(_state_path(tmp_path))
    assert payload["assignment"] == str(_assignment_path(tmp_path))
    assert payload["ledger"] == str(_ledger_path(tmp_path))
    assert nested_payload["state"] == read_json(_state_path(tmp_path))
    assert nested_payload["assignment"] == read_json(_assignment_path(tmp_path))
    assert nested_payload["start_gate"] == read_json(_start_gate_path(tmp_path))
    assert latest_events
    assert all(_has_attempt(event, 2) for event in latest_events)
    assert all(not _has_attempt(event, 1) for event in latest_events)
    assert any('"detail":"restarted after replan"' in event for event in latest_events)


def test_delegate_start_work_command_includes_absolute_worktree(
    tmp_path: Path,
) -> None:
    # Given
    _create_started_squad(tmp_path)
    worktree = tmp_path / "worktrees" / "squad-a"
    state_path = _state_path(tmp_path)
    state = read_json(state_path)
    state["worktree"] = str(worktree)
    write_json(state_path, state)

    # When
    result = build_delegation_payload(tmp_path, "squad-a")

    # Then
    assert result.command == f"$start-work squad-a --worktree {worktree}"


def test_delegate_start_work_quotes_unsafe_plan_and_worktree_arguments(
    tmp_path: Path,
) -> None:
    # Given
    _create_started_squad(tmp_path)
    worktree = tmp_path / "worktrees" / "unsafe path; touch owned"
    state_path = _state_path(tmp_path)
    state = read_json(state_path)
    state["plan_artifact"] = ".omo/plans/squad a; touch owned.md"
    state["worktree"] = str(worktree)
    write_json(state_path, state)

    # When
    result = build_delegation_payload(tmp_path, "squad-a")

    # Then
    assert (
        result.command == f"$start-work 'squad a; touch owned' --worktree '{worktree}'"
    )


def test_delegate_start_work_cli_uses_real_command_surface(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    _create_started_squad(tmp_path)

    # When
    exit_code = main(
        ("delegate-start-work", "--root", str(tmp_path), "--squad", "squad-a"),
    )

    # Then
    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"command": "$start-work squad-a"' in captured.out
    assert '"start_gate_status": "passed"' in captured.out
    assert '"latest_ledger_events"' in captured.out


def test_delegate_start_work_refuses_missing_start_gate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    _create_initialized_state(tmp_path)

    # When
    with pytest.raises(SystemExit) as raised:
        _ = main(("delegate-start-work", "--root", str(tmp_path), "--squad", "squad-a"))

    # Then
    captured = capsys.readouterr()
    assert raised.value.code != 0
    assert "start gate" in captured.err
    assert "not passed" in captured.err


def test_delegate_start_work_refuses_non_passed_start_gate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    _create_started_squad(tmp_path)
    start_gate = read_json(_start_gate_path(tmp_path))
    start_gate["gate_status"] = "failed"
    write_json(_start_gate_path(tmp_path), start_gate)

    # When
    with pytest.raises(SystemExit) as raised:
        _ = main(("delegate-start-work", "--root", str(tmp_path), "--squad", "squad-a"))

    # Then
    captured = capsys.readouterr()
    assert raised.value.code != 0
    assert "start gate" in captured.err
    assert "not passed" in captured.err


def test_delegate_start_work_refuses_stale_start_gate_after_backtrack(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    _create_initialized_state(tmp_path)
    _ = run_start_gate(
        StartGateRequest(
            root=tmp_path,
            squad_id="squad-a",
            source=StartGateSource.ASSIGNMENT,
            applied_example="If design fails, route back to plan.",
            plan_artifact=None,
        ),
    )
    _ = route_squad_report(
        tmp_path,
        "squad-a",
        Report.from_mapping(
            {
                "source": "work",
                "type": "design_flaw",
                "detail": "unexpected dependency",
                "findings": ["pub/sub required"],
                "evidence": ["attempt-1.log"],
            },
        ),
    )

    # When
    with pytest.raises(SystemExit) as raised:
        _ = main(("delegate-start-work", "--root", str(tmp_path), "--squad", "squad-a"))

    # Then
    captured = capsys.readouterr()
    assert raised.value.code != 0
    assert "start gate" in captured.err
    assert (
        "stale" in captured.err or "fresh" in captured.err or "current" in captured.err
    )

    # When
    _ = run_start_gate(
        StartGateRequest(
            root=tmp_path,
            squad_id="squad-a",
            source=StartGateSource.PLAN,
            applied_example="If plan restarts, verify attempt 2 before work.",
            plan_artifact=None,
        ),
    )
    exit_code = main(
        ("delegate-start-work", "--root", str(tmp_path), "--squad", "squad-a"),
    )

    # Then
    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"active_attempt": 2' in captured.out
    assert '"current_stage": "plan"' in captured.out


def _create_started_squad(root: Path) -> None:
    _create_initialized_state(root)
    _ = append_ledger_entry(
        root,
        LedgerAppendRequest(
            squad_id="squad-a",
            event="task-started",
            attempt=1,
            stage="work",
            task="worker-a",
            detail="started old attempt",
            findings=(),
            evidence=(),
        ),
    )
    _ = route_squad_report(
        root,
        "squad-a",
        Report.from_mapping(
            {
                "source": "work",
                "type": "design_flaw",
                "detail": "unexpected dependency",
                "findings": ["pub/sub required"],
                "evidence": ["attempt-1.log"],
            },
        ),
    )
    _ = append_ledger_entry(
        root,
        LedgerAppendRequest(
            squad_id="squad-a",
            event="task-started",
            attempt=2,
            stage="plan",
            task="replan",
            detail="restarted after replan",
            findings=("dependency mapped",),
            evidence=("attempt-2.log",),
        ),
    )
    _ = run_start_gate(
        StartGateRequest(
            root=root,
            squad_id="squad-a",
            source=StartGateSource.ASSIGNMENT,
            applied_example="If design fails, route back to plan.",
            plan_artifact=None,
        ),
    )


def _create_initialized_state(root: Path) -> None:
    _ = create_assignment_packets(
        root=root,
        platoon_goal="Ship cache",
        scope_specs=("squad-a|Redis cache|-",),
    )
    plan_path = root / ".omo" / "plans" / "squad-a.md"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    _ = plan_path.write_text("# squad-a plan\n", encoding="utf-8")
    _ = initialize_squad_state(root, "squad-a", ".omo/plans/squad-a.md")


def _assignment_path(root: Path) -> Path:
    return root / ".omo" / "squad" / "squad-a" / "assignment.json"


def _ledger_path(root: Path) -> Path:
    return root / ".omo" / "squad" / "squad-a" / "ledger.jsonl"


def _start_gate_path(root: Path) -> Path:
    return root / ".omo" / "squad" / "squad-a" / "start-gate.json"


def _state_path(root: Path) -> Path:
    return root / ".omo" / "squad" / "squad-a" / "state.json"


def _json_object(value: JsonValue) -> JsonMapping:
    if isinstance(value, dict):
        return value
    pytest.fail("expected JSON object")


def _string_list(value: JsonValue) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(_string_item(item) for item in value)
    pytest.fail("expected string list")


def _string_item(value: JsonValue) -> str:
    if isinstance(value, str):
        return value
    pytest.fail("expected string item")


def _has_attempt(event_line: str, attempt: int) -> bool:
    return f'"attempt":{attempt}' in event_line or f'"attempt": {attempt}' in event_line
