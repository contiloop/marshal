"""Start-gate validation and artifact writing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

from marshal_cli.jsonio import JsonIOError, read_json, write_json
from marshal_cli.models import (
    JsonObject,
    PlatoonAssignment,
    SquadState,
    StartGateRecord,
    StartGateSource,
    ValidationError,
    validate_squad_id,
)
from marshal_cli.paths import ArtifactRoot, ensure_artifact_path
from marshal_cli.start_gate_core import append_started_event

if TYPE_CHECKING:
    from marshal_cli.models import JsonMapping

START_GATE_CONTEXT = "start_gate"


@dataclass(frozen=True, slots=True)
class StartGateRequest:
    """Inputs needed to run one squad start gate."""

    root: str | Path
    squad_id: str
    source: StartGateSource
    applied_example: str
    plan_artifact: str | None


@dataclass(frozen=True, slots=True)
class StartGateResult:
    """Artifacts produced by a passed start gate."""

    record: StartGateRecord
    start_gate_path: Path
    assignment_path: Path
    state_path: Path
    checklist_path: Path
    ledger_path: Path
    plan_path: Path | None

    def to_jsonable(self) -> JsonObject:
        """Return the command result as JSON-compatible data."""
        paths: JsonObject = {
            "start_gate": str(self.start_gate_path),
            "assignment": str(self.assignment_path),
            "state": str(self.state_path),
            "checklist": str(self.checklist_path),
            "ledger": str(self.ledger_path),
        }
        if self.plan_path is not None:
            paths["plan"] = str(self.plan_path)
        return {
            "gate_status": self.record.gate_status,
            "current_stage": self.record.current_stage.value,
            "active_attempt": self.record.active_attempt,
            "source_artifacts": list(self.record.source_artifacts),
            "scope_authority": self.record.scope_authority,
            "freshness": self.record.freshness,
            "applied_example": self.record.applied_example,
            "artifact_paths": paths,
        }


def run_start_gate(request: StartGateRequest) -> StartGateResult:
    """Validate source artifacts before recording squad start."""
    artifact_root = ArtifactRoot.from_user_input(request.root)
    squad_id = validate_squad_id(request.squad_id)
    example = _required_example(request.applied_example)

    assignment_path = artifact_root.omo_path("squad", squad_id, "assignment.json")
    state_path = artifact_root.omo_path("squad", squad_id, "state.json")
    checklist_path = artifact_root.omo_path("platoon", "checklist.json")
    ledger_path = artifact_root.omo_path("squad", squad_id, "ledger.jsonl")
    start_gate_path = artifact_root.omo_path("squad", squad_id, "start-gate.json")

    assignment = PlatoonAssignment.from_mapping(
        _read_json_artifact(assignment_path, "assignment"),
    )
    state = SquadState.from_mapping(_read_json_artifact(state_path, "state"))
    checklist = _read_json_artifact(checklist_path, "checklist")
    _ = _read_ledger_lines(ledger_path)
    _validate_scope_authority(squad_id, assignment, state, checklist)
    plan_path = _read_plan_if_needed(artifact_root, request, state)

    record = StartGateRecord(
        squad_id=squad_id,
        gate_status="passed",
        source=request.source,
        current_stage=state.current_stage,
        active_attempt=state.active_attempt,
        source_artifacts=_source_artifacts(
            assignment_path,
            state_path,
            checklist_path,
            ledger_path,
            plan_path,
        ),
        scope_authority=f"{squad_id} owns {assignment.assigned_scope.goal}",
        freshness="passed",
        applied_example=example,
    )
    write_json(start_gate_path, record.to_jsonable())
    append_started_event(
        record,
        ledger_path,
        f"start gate passed from {request.source.value}",
    )
    return StartGateResult(
        record=record,
        start_gate_path=start_gate_path,
        assignment_path=assignment_path,
        state_path=state_path,
        checklist_path=checklist_path,
        ledger_path=ledger_path,
        plan_path=plan_path,
    )


def _required_example(example: str) -> str:
    trimmed = example.strip()
    if not trimmed:
        reason = "required applied example"
        raise ValidationError(START_GATE_CONTEXT, "example", example, reason)
    return trimmed


def _read_json_artifact(path: Path, field: str) -> JsonObject:
    try:
        return read_json(path)
    except JsonIOError as error:
        raise ValidationError(
            START_GATE_CONTEXT,
            field,
            str(path),
            str(error),
        ) from error


def _read_ledger_lines(ledger_path: Path) -> tuple[str, ...]:
    if not ledger_path.exists():
        return ()
    try:
        return tuple(ledger_path.read_text(encoding="utf-8").splitlines())
    except OSError as error:
        reason = "failed to read ledger artifact"
        raise ValidationError(
            START_GATE_CONTEXT,
            "ledger",
            str(ledger_path),
            reason,
        ) from error


def _validate_scope_authority(
    squad_id: str,
    assignment: PlatoonAssignment,
    state: SquadState,
    checklist: JsonMapping,
) -> None:
    if assignment.assigned_scope.squad_id != squad_id:
        reason = "assignment belongs to a different squad"
        raise ValidationError(
            START_GATE_CONTEXT,
            "assignment",
            assignment.assigned_scope.squad_id,
            reason,
        )
    if state.squad_id != squad_id:
        reason = "state belongs to a different squad"
        raise ValidationError(START_GATE_CONTEXT, "state", state.squad_id, reason)
    if state.scope != assignment.assigned_scope.goal:
        reason = "stale state scope"
        raise ValidationError(START_GATE_CONTEXT, "state", state.scope, reason)
    _validate_checklist_squad(squad_id, checklist)


def _validate_checklist_squad(squad_id: str, checklist: JsonMapping) -> None:
    squads = checklist.get("squads")
    if isinstance(squads, dict) and squad_id in squads:
        return
    reason = "checklist missing squad"
    raise ValidationError(START_GATE_CONTEXT, "checklist", squad_id, reason)


def _read_plan_if_needed(
    root: ArtifactRoot,
    request: StartGateRequest,
    state: SquadState,
) -> Path | None:
    plan_artifact = request.plan_artifact or state.plan_artifact
    if plan_artifact is None:
        source = request.source
        if source is StartGateSource.PLAN:
            reason = "plan source requires --plan or state plan_artifact"
            raise ValidationError(START_GATE_CONTEXT, "plan", "<missing>", reason)
        if (
            source is StartGateSource.ASSIGNMENT
            or source is StartGateSource.STATE
            or source is StartGateSource.HANDOVER
        ):
            return None
        assert_never(source)
    plan_path = _artifact_path(root, plan_artifact)
    try:
        content = plan_path.read_text(encoding="utf-8")
    except OSError as error:
        reason = "failed to read plan artifact"
        raise ValidationError(
            START_GATE_CONTEXT,
            "plan",
            str(plan_path),
            reason,
        ) from error
    if not content.strip():
        reason = "plan artifact is empty"
        raise ValidationError(START_GATE_CONTEXT, "plan", str(plan_path), reason)
    return plan_path


def _artifact_path(root: ArtifactRoot, artifact: str) -> Path:
    path = Path(artifact)
    candidate = path if path.is_absolute() else root.root / path
    return ensure_artifact_path(candidate, root.root / ".omo")


def _source_artifacts(
    assignment_path: Path,
    state_path: Path,
    checklist_path: Path,
    ledger_path: Path,
    plan_path: Path | None,
) -> tuple[str, ...]:
    required = (
        str(assignment_path),
        str(state_path),
        str(checklist_path),
        str(ledger_path),
    )
    if plan_path is None:
        return required
    return (*required, str(plan_path))


__all__ = ["StartGateRequest", "StartGateResult", "run_start_gate"]
