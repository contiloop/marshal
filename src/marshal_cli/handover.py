"""Handover packet builder for passing a squad to the next agent.

A handover packet bundles everything a receiving agent needs to pass its
first-response gate: the assignment, the live state, the start gate, the
active-attempt ledger, the surrounding platoon picture, and a plain next-action
summary. Unlike `delegate-start-work`, this works at any stage (including
blocked or aborted) because its job is orientation, not dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from marshal_cli.jsonio import JsonIOError, read_json, write_json
from marshal_cli.ledger_core import latest_attempt_events
from marshal_cli.models import (
    JsonObject,
    PlatoonAssignment,
    SquadState,
    Stage,
    ValidationError,
    validate_squad_id,
)
from marshal_cli.overview import collect_platoon_status
from marshal_cli.paths import ArtifactRoot

if TYPE_CHECKING:
    from pathlib import Path

HANDOVER_CONTEXT: Final = "handover"

_NEXT_ACTION: Final[dict[Stage, str]] = {
    Stage.SYNC: "Resolve open sync questions with the user, then advance to plan.",
    Stage.PLAN: "Confirm the plan artifact and pass a plan start gate before work.",
    Stage.WORK: "Resume work; reproduce RED/GREEN and real-surface evidence.",
    Stage.REVIEW: "Verify real-surface evidence; accept or route the report back.",
    Stage.DONE: "Squad is complete; no further action.",
    Stage.BLOCKED: "Resolve the recorded blocker before any further work.",
    Stage.ABORTED: "Squad is aborted; do not dispatch or delegate.",
}


def next_action(stage: Stage) -> str:
    """Return the plain next-action summary for a squad stage."""
    return _NEXT_ACTION[stage]


@dataclass(frozen=True, slots=True)
class HandoverPacket:
    """A self-contained handover packet for one squad."""

    squad_id: str
    current_stage: str
    active_attempt: int
    next_action: str
    handover_path: Path
    body: JsonObject

    def to_jsonable(self) -> JsonObject:
        """Return a JSON-compatible handover packet object."""
        return {
            "squad_id": self.squad_id,
            "current_stage": self.current_stage,
            "active_attempt": self.active_attempt,
            "next_action": self.next_action,
            "handover_path": str(self.handover_path),
            "packet": self.body,
        }


def build_handover(root: str | Path, squad_id: str) -> HandoverPacket:
    """Assemble and persist a handover packet for one squad."""
    artifact_root = ArtifactRoot.from_user_input(root)
    validated_squad_id = validate_squad_id(squad_id)
    squad = validated_squad_id

    assignment_path = artifact_root.omo_path("squad", squad, "assignment.json")
    state_path = artifact_root.omo_path("squad", squad, "state.json")
    start_gate_path = artifact_root.omo_path("squad", squad, "start-gate.json")

    assignment = PlatoonAssignment.from_mapping(
        _read_required(assignment_path, "assignment"),
    )
    state = SquadState.from_mapping(_read_required(state_path, "state"))
    if state.squad_id != validated_squad_id:
        reason = "state belongs to a different squad"
        raise ValidationError(HANDOVER_CONTEXT, "state", state.squad_id, reason)

    start_gate = _read_optional(start_gate_path)
    latest = latest_attempt_events(artifact_root.root, validated_squad_id)
    platoon = collect_platoon_status(artifact_root.root)
    next_action_text = next_action(state.current_stage)

    body: JsonObject = {
        "assignment": assignment.to_jsonable(),
        "state": state.to_jsonable(),
        "start_gate": start_gate,
        "latest_ledger_events": list(latest.event_lines),
        "platoon": platoon.to_jsonable(),
        "next_action": next_action_text,
        "artifact_paths": {
            "assignment": str(assignment_path),
            "state": str(state_path),
            "start_gate": str(start_gate_path),
            "ledger": str(latest.ledger_path),
        },
    }
    handover_path = artifact_root.omo_path("squad", squad, "handover.json")
    write_json(handover_path, body)
    return HandoverPacket(
        squad_id=validated_squad_id,
        current_stage=state.current_stage.value,
        active_attempt=state.active_attempt,
        next_action=next_action_text,
        handover_path=handover_path,
        body=body,
    )


def _read_required(path: Path, field: str) -> JsonObject:
    try:
        return read_json(path)
    except JsonIOError as error:
        raise ValidationError(HANDOVER_CONTEXT, field, str(path), str(error)) from error


def _read_optional(path: Path) -> JsonObject | None:
    try:
        return read_json(path)
    except JsonIOError:
        return None


__all__ = ["HandoverPacket", "build_handover", "next_action"]
