"""Start-work delegation adapter for passed Marshal squads."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from marshal_cli.jsonio import JsonIOError, read_json
from marshal_cli.ledger import latest_attempt_events
from marshal_cli.models import (
    DelegationPayload,
    JsonObject,
    PlatoonAssignment,
    SquadState,
    Stage,
    StartGateRecord,
    ValidationError,
    validate_squad_id,
)
from marshal_cli.paths import ArtifactRoot, PathSecurityError

if TYPE_CHECKING:
    from collections.abc import Sequence

DELEGATION_CONTEXT: Final = "delegation"


class _DelegateNamespace(argparse.Namespace):
    root: str
    squad_id: str

    def __init__(self) -> None:
        super().__init__()
        self.root = ""
        self.squad_id = ""


@dataclass(frozen=True, slots=True)
class _DelegationArtifacts:
    root: ArtifactRoot
    squad_id: str
    assignment_path: Path
    state_path: Path
    start_gate_path: Path
    ledger_path: Path


def build_delegation_payload(root: str | Path, squad_id: str) -> DelegationPayload:
    """Build the JSON contract emitted to a root start-work caller."""
    artifacts = _artifact_paths(root, squad_id)
    assignment_json = _read_json_artifact(artifacts.assignment_path, "assignment")
    state_json = _read_json_artifact(artifacts.state_path, "state")
    start_gate_json = _read_start_gate_json(artifacts.start_gate_path)

    assignment = PlatoonAssignment.from_mapping(assignment_json)
    state = SquadState.from_mapping(state_json)
    start_gate = StartGateRecord.from_mapping(start_gate_json)
    _validate_squad_artifacts(artifacts.squad_id, assignment, state, start_gate)

    latest = latest_attempt_events(artifacts.root.root, artifacts.squad_id)
    plan = _plan_value(state, artifacts.squad_id)
    return DelegationPayload(
        squad_id=artifacts.squad_id,
        plan=plan,
        state=str(artifacts.state_path),
        ledger=str(artifacts.ledger_path),
        assignment=str(artifacts.assignment_path),
        active_attempt=state.active_attempt,
        start_gate_status=start_gate.gate_status,
        command=_command(plan, artifacts.root.root, state.worktree),
        payload={
            "assignment": assignment_json,
            "state": state_json,
            "start_gate": start_gate_json,
            "latest_ledger_events": list(latest.event_lines),
            "artifact_paths": {
                "assignment": str(artifacts.assignment_path),
                "state": str(artifacts.state_path),
                "start_gate": str(artifacts.start_gate_path),
                "ledger": str(artifacts.ledger_path),
            },
        },
    )


def run_delegate_command(arguments: Sequence[str]) -> int:
    """Run the delegate-start-work CLI command."""
    parser = _build_delegate_parser()
    parsed = _DelegateNamespace()
    _ = parser.parse_args(arguments, namespace=parsed)
    try:
        result = build_delegation_payload(parsed.root, parsed.squad_id)
    except (JsonIOError, PathSecurityError, ValidationError) as error:
        parser.error(str(error))
    _write_result(result.to_jsonable())
    return 0


def _artifact_paths(root: str | Path, squad_id: str) -> _DelegationArtifacts:
    artifact_root = ArtifactRoot.from_user_input(root)
    validated_squad_id = validate_squad_id(squad_id)
    squad_path = ("squad", validated_squad_id)
    return _DelegationArtifacts(
        root=artifact_root,
        squad_id=validated_squad_id,
        assignment_path=artifact_root.omo_path(*squad_path, "assignment.json"),
        state_path=artifact_root.omo_path(*squad_path, "state.json"),
        start_gate_path=artifact_root.omo_path(*squad_path, "start-gate.json"),
        ledger_path=artifact_root.omo_path(*squad_path, "ledger.jsonl"),
    )


def _read_json_artifact(path: Path, field: str) -> JsonObject:
    try:
        return read_json(path)
    except JsonIOError as error:
        raise ValidationError(
            DELEGATION_CONTEXT,
            field,
            str(path),
            str(error),
        ) from error


def _read_start_gate_json(path: Path) -> JsonObject:
    try:
        return read_json(path)
    except JsonIOError as error:
        reason = "start gate has not passed or handover artifact is missing"
        raise ValidationError(
            DELEGATION_CONTEXT,
            "start gate",
            str(path),
            reason,
        ) from error


def _validate_squad_artifacts(
    squad_id: str,
    assignment: PlatoonAssignment,
    state: SquadState,
    start_gate: StartGateRecord,
) -> None:
    if assignment.assigned_scope.squad_id != squad_id:
        reason = "assignment belongs to a different squad"
        raise ValidationError(DELEGATION_CONTEXT, "assignment", squad_id, reason)
    if state.squad_id != squad_id:
        reason = "state belongs to a different squad"
        raise ValidationError(DELEGATION_CONTEXT, "state", squad_id, reason)
    if state.current_stage is Stage.ABORTED:
        reason = "squad is aborted; delegation and start-work are blocked"
        stage = state.current_stage.value
        raise ValidationError(DELEGATION_CONTEXT, "state", stage, reason)
    if state.current_stage is Stage.DONE:
        reason = "squad is already done; nothing to delegate"
        stage = state.current_stage.value
        raise ValidationError(DELEGATION_CONTEXT, "state", stage, reason)
    if start_gate.squad_id != squad_id:
        reason = "start gate belongs to a different squad"
        raise ValidationError(DELEGATION_CONTEXT, "start gate", squad_id, reason)
    if start_gate.gate_status != "passed":
        reason = "start gate has not passed"
        raise ValidationError(
            DELEGATION_CONTEXT,
            "start gate",
            start_gate.gate_status,
            reason,
        )
    if (
        start_gate.active_attempt != state.active_attempt
        or start_gate.current_stage != state.current_stage
    ):
        reason = "start gate is stale; run a fresh start gate for the current stage"
        actual = f"{start_gate.current_stage.value} attempt {start_gate.active_attempt}"
        raise ValidationError(DELEGATION_CONTEXT, "start gate", actual, reason)


def _plan_value(state: SquadState, squad_id: str) -> str:
    if state.plan_artifact is None:
        return squad_id
    return state.plan_artifact


def _command(plan: str, root: Path, worktree: str | None) -> str:
    plan_stem = _plan_stem(plan)
    command = f"$start-work {shlex.quote(plan_stem)}"
    if worktree is None:
        return command
    quoted_worktree = shlex.quote(str(_absolute_worktree(root, worktree)))
    return f"{command} --worktree {quoted_worktree}"


def _plan_stem(plan: str) -> str:
    return Path(plan).stem or plan


def _absolute_worktree(root: Path, worktree: str) -> Path:
    path = Path(worktree).expanduser()
    if path.is_absolute():
        return path
    return root / path


def _build_delegate_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="marshal delegate-start-work",
        description="Emit a start-work command and payload for a passed squad gate.",
    )
    _ = parser.add_argument("--root", required=True)
    _ = parser.add_argument("--squad", dest="squad_id", required=True)
    return parser


def _write_result(result: JsonObject) -> None:
    _ = sys.stdout.write(json.dumps(result, indent=2, sort_keys=True))
    _ = sys.stdout.write("\n")


__all__ = ["build_delegation_payload", "run_delegate_command"]
