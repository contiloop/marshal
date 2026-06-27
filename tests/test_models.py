import pytest

from marshal_cli.models import (
    AssignedScope,
    AttemptEvent,
    DelegationPayload,
    PlatoonAssignment,
    Report,
    SquadState,
    Stage,
    StageHistoryEntry,
    StartGateRecord,
    ValidationError,
    validate_dependency_references,
    validate_report_type,
    validate_squad_id,
    validate_stage,
    validate_worker_conversation_policy,
)


def test_assignment_round_trips_when_scope_is_valid() -> None:
    scope = AssignedScope(
        squad_id="squad-a",
        goal="Redis cache",
        in_scope=("cache",),
        out_of_scope=("dashboard",),
        depends_on=(),
        blocks=("squad-c",),
        success_evidence=("RED/GREEN", "real CLI proof"),
    )
    assignment = PlatoonAssignment(
        platoon_goal="Ship cache and dashboard",
        global_order=(("squad-a",), ("squad-c",)),
        squads_summary={"squad-a": "Redis cache", "squad-c": "Dashboard"},
        assigned_scope=scope,
        basic_rules=("failing-first-proof", "evidence-based-completion"),
        conversation_policy=(
            "Workers report blockers to Squad Leader; no direct user asks."
        ),
        abort_policy="Platoon Leader propagates aborts.",
    )

    parsed = PlatoonAssignment.from_mapping(assignment.to_jsonable())

    assert parsed == assignment


def test_state_round_trips_when_created_from_assignment_scope() -> None:
    scope = AssignedScope(
        squad_id="squad-a",
        goal="Redis cache",
        in_scope=("cache",),
        out_of_scope=("dashboard",),
        depends_on=(),
        blocks=(),
        success_evidence=("RED/GREEN",),
    )
    state = SquadState.new(scope, plan_artifact=".omo/plans/squad-a.md")

    parsed = SquadState.from_mapping(state.to_jsonable())

    assert parsed == state
    assert parsed.current_stage is Stage.SYNC
    assert parsed.stage_history == (
        StageHistoryEntry(stage=Stage.SYNC, result="initialized", ts="pending"),
    )


def test_report_attempt_start_gate_and_delegation_round_trip() -> None:
    report = Report.from_mapping(
        {
            "source": "work",
            "type": "design_flaw",
            "detail": "Pub/sub missing from plan",
            "findings": ["TTL alone is stale"],
            "evidence": ["worker-output.log"],
        },
    )
    attempt = AttemptEvent.from_mapping(
        {
            "event": "task-started",
            "squad_id": "squad-a",
            "attempt": 1,
            "stage": "work",
            "task": "cache worker",
            "detail": "started",
            "findings": [],
            "evidence": ["task.log"],
            "ts": "2026-06-27T00:00:00Z",
        },
    )
    gate = StartGateRecord.from_mapping(
        {
            "squad_id": "squad-a",
            "gate_status": "passed",
            "source": "assignment",
            "current_stage": "work",
            "active_attempt": 1,
            "source_artifacts": [
                ".omo/squad/squad-a/assignment.json",
                ".omo/squad/squad-a/state.json",
            ],
            "scope_authority": "squad-a owns Redis cache",
            "freshness": "assignment and state agree",
            "applied_example": "Report design_flaw to Squad Leader.",
        },
    )
    delegation = DelegationPayload.from_mapping(
        {
            "squad_id": "squad-a",
            "plan": ".omo/plans/squad-a.md",
            "state": ".omo/squad/squad-a/state.json",
            "ledger": ".omo/squad/squad-a/ledger.jsonl",
            "assignment": ".omo/squad/squad-a/assignment.json",
            "active_attempt": 1,
            "start_gate_status": "passed",
            "command": "$start-work squad-a",
            "payload": {"report": report.to_jsonable()},
        },
    )

    assert Report.from_mapping(report.to_jsonable()) == report
    assert AttemptEvent.from_mapping(attempt.to_jsonable()) == attempt
    assert StartGateRecord.from_mapping(gate.to_jsonable()) == gate
    assert DelegationPayload.from_mapping(delegation.to_jsonable()) == delegation


def test_validation_helpers_reject_invalid_contract_values() -> None:
    with pytest.raises(ValidationError, match="squad_id"):
        _ = validate_squad_id("Squad A")
    with pytest.raises(ValidationError, match="stage"):
        _ = validate_stage("waiting")
    with pytest.raises(ValidationError, match="report type invalid"):
        _ = validate_report_type("ask_user_directly")
    with pytest.raises(ValidationError, match="unknown dependency"):
        validate_dependency_references("squad-a", ("squad-b",), ("squad-a",))
    with pytest.raises(ValidationError, match="worker cannot ask user directly"):
        _ = validate_worker_conversation_policy("Worker may ask user directly.")


def test_report_rejects_direct_user_ask_type() -> None:
    with pytest.raises(ValidationError, match="report type invalid"):
        _ = Report.from_mapping(
            {
                "source": "work",
                "type": "ask_user_directly",
                "detail": "bad",
                "findings": [],
                "evidence": [],
            },
        )
