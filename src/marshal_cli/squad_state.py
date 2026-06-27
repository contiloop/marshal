"""Squad Leader state creation and backward routing."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, assert_never

if TYPE_CHECKING:
    from pathlib import Path

from marshal_cli.jsonio import read_json, write_json
from marshal_cli.models import (
    BacktrackRecord,
    JsonObject,
    PlatoonAssignment,
    Report,
    ReportSource,
    ReportType,
    SquadState,
    Stage,
    StageHistoryEntry,
    ValidationError,
    validate_squad_id,
)
from marshal_cli.paths import ArtifactRoot
from marshal_cli.squad_ledger import append_backtrack_events

STATE_CONTEXT = "state"
SQUAD_FIELD = "squad_id"


@dataclass(frozen=True, slots=True)
class StateInitResult:
    """Result emitted after creating a squad state artifact."""

    squad_id: str
    state_path: Path
    current_stage: str
    active_attempt: int
    plan_artifact: str | None

    def to_jsonable(self) -> JsonObject:
        """Return the state-init result as JSON-compatible data."""
        return {
            "squad_id": self.squad_id,
            "state_path": str(self.state_path),
            "current_stage": self.current_stage,
            "active_attempt": self.active_attempt,
            "plan_artifact": self.plan_artifact,
        }


@dataclass(frozen=True, slots=True)
class RouteResult:
    """Result emitted after routing a stage report."""

    squad_id: str
    state_path: Path
    report_path: Path
    current_stage: str
    active_attempt: int
    escalation_detail: str | None

    def to_jsonable(self) -> JsonObject:
        """Return the route result as JSON-compatible data."""
        return {
            "squad_id": self.squad_id,
            "state_path": str(self.state_path),
            "report_path": str(self.report_path),
            "current_stage": self.current_stage,
            "active_attempt": self.active_attempt,
            "escalation_detail": self.escalation_detail,
        }


def initialize_squad_state(
    root: str | Path,
    squad_id: str,
    plan_artifact: str | None,
) -> StateInitResult:
    """Create `.omo/squad/<id>/state.json` from an assignment packet."""
    artifact_root = ArtifactRoot.from_user_input(root)
    validated_squad_id = validate_squad_id(squad_id)
    assignment_path = _assignment_path(artifact_root, validated_squad_id)
    assignment = PlatoonAssignment.from_mapping(read_json(assignment_path))
    if assignment.assigned_scope.squad_id != validated_squad_id:
        reason = "assignment belongs to a different squad"
        raise ValidationError(
            STATE_CONTEXT,
            SQUAD_FIELD,
            assignment.assigned_scope.squad_id,
            reason,
        )

    state = SquadState.new(assignment.assigned_scope, plan_artifact=plan_artifact)
    state_path = _state_path(artifact_root, validated_squad_id)
    write_json(state_path, state.to_jsonable())
    return StateInitResult(
        squad_id=validated_squad_id,
        state_path=state_path,
        current_stage=state.current_stage.value,
        active_attempt=state.active_attempt,
        plan_artifact=state.plan_artifact,
    )


def route_squad_report(
    root: str | Path,
    squad_id: str,
    report: Report,
) -> RouteResult:
    """Route a stage report and persist the updated state/report artifacts."""
    artifact_root = ArtifactRoot.from_user_input(root)
    validated_squad_id = validate_squad_id(squad_id)
    state_path = _state_path(artifact_root, validated_squad_id)
    state = SquadState.from_mapping(read_json(state_path))
    if state.squad_id != validated_squad_id:
        reason = "state belongs to a different squad"
        raise ValidationError(STATE_CONTEXT, SQUAD_FIELD, state.squad_id, reason)

    routed = _route_state(state, report, _utc_timestamp())
    append_backtrack_events(
        _ledger_path(artifact_root, validated_squad_id),
        state,
        routed,
        report,
        _source_stage(report.source, state.current_stage),
    )
    report_path = _report_path(artifact_root, validated_squad_id)
    write_json(
        report_path,
        {
            "report": report.to_jsonable(),
            "route": {
                "from": _source_stage(report.source, state.current_stage).value,
                "to": routed.current_stage.value,
                "active_attempt": routed.active_attempt,
            },
        },
    )
    write_json(state_path, routed.to_jsonable())
    return RouteResult(
        squad_id=validated_squad_id,
        state_path=state_path,
        report_path=report_path,
        current_stage=routed.current_stage.value,
        active_attempt=routed.active_attempt,
        escalation_detail=_escalation_detail(report),
    )


def _route_state(state: SquadState, report: Report, timestamp: str) -> SquadState:
    report_type = report.type
    if (
        report_type is ReportType.INTENT_UNCLEAR
        or report_type is ReportType.REQUIREMENT_MISSING
    ):
        return _with_stage(state, Stage.SYNC, report.detail, timestamp)
    if (
        report_type is ReportType.DESIGN_FLAW
        or report_type is ReportType.DEPENDENCY_UNEXPECTED
        or report_type is ReportType.THIRD_FAILURE
    ):
        next_attempt = state.active_attempt + 1
        return _with_backtrack(state, report, Stage.PLAN, next_attempt, timestamp)
    if report_type is ReportType.EXECUTION_FAILURE:
        return _with_stage(state, Stage.WORK, report.detail, timestamp)
    if report_type is ReportType.BLOCKED:
        detail = f"blocked: {report.detail}"
        return _with_stage(state, Stage.BLOCKED, detail, timestamp)
    assert_never(report_type)


def _with_backtrack(
    state: SquadState,
    report: Report,
    target: Stage,
    active_attempt: int,
    timestamp: str,
) -> SquadState:
    source_stage = _source_stage(report.source, state.current_stage)
    backtrack = BacktrackRecord(
        from_stage=source_stage,
        to_stage=target,
        reason=report.type.value,
        attempt=active_attempt,
        findings=report.findings,
        ts=timestamp,
    )
    return replace(
        state,
        current_stage=target,
        active_attempt=active_attempt,
        stage_history=(
            *state.stage_history,
            _history_entry(target, report.detail, timestamp),
        ),
        backtrack_log=(*state.backtrack_log, backtrack),
    )


def _with_stage(
    state: SquadState,
    target: Stage,
    result: str,
    timestamp: str,
) -> SquadState:
    return replace(
        state,
        current_stage=target,
        stage_history=(*state.stage_history, _history_entry(target, result, timestamp)),
    )


def _history_entry(stage: Stage, result: str, timestamp: str) -> StageHistoryEntry:
    return StageHistoryEntry(stage=stage, result=result, ts=timestamp)


def _source_stage(source: ReportSource, current_stage: Stage) -> Stage:
    if source is ReportSource.SYNC:
        return Stage.SYNC
    if source is ReportSource.PLAN:
        return Stage.PLAN
    if source is ReportSource.WORK:
        return Stage.WORK
    if source is ReportSource.REVIEW:
        return Stage.REVIEW
    if source is ReportSource.WORKER:
        return current_stage
    assert_never(source)


def _escalation_detail(report: Report) -> str | None:
    report_type = report.type
    if report_type is ReportType.BLOCKED:
        return report.detail
    if (
        report_type is ReportType.INTENT_UNCLEAR
        or report_type is ReportType.REQUIREMENT_MISSING
        or report_type is ReportType.DESIGN_FLAW
        or report_type is ReportType.DEPENDENCY_UNEXPECTED
        or report_type is ReportType.EXECUTION_FAILURE
        or report_type is ReportType.THIRD_FAILURE
    ):
        return None
    assert_never(report_type)


def _assignment_path(root: ArtifactRoot, squad_id: str) -> Path:
    return root.omo_path("squad", squad_id, "assignment.json")


def _state_path(root: ArtifactRoot, squad_id: str) -> Path:
    return root.omo_path("squad", squad_id, "state.json")


def _report_path(root: ArtifactRoot, squad_id: str) -> Path:
    return root.omo_path("squad", squad_id, "reports", "latest.json")


def _ledger_path(root: ArtifactRoot, squad_id: str) -> Path:
    return root.omo_path("squad", squad_id, "ledger.jsonl")


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "RouteResult",
    "StateInitResult",
    "initialize_squad_state",
    "route_squad_report",
]
