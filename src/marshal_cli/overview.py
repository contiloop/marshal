"""Live platoon and squad status read model.

This module never mutates artifacts. It assembles a snapshot of the platoon
checklist together with each squad's `state.json` and `start-gate.json` so the
`status`, `next`, and `dispatch` commands can reason about progress and
dependency readiness.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from marshal_cli.jsonio import JsonIOError, parse_json_object, read_json
from marshal_cli.models import (
    JsonObject,
    JsonValue,
    SquadState,
    Stage,
    StartGateRecord,
    ValidationError,
    validate_squad_id,
)
from marshal_cli.paths import ArtifactRoot

if TYPE_CHECKING:
    from pathlib import Path

OVERVIEW_CONTEXT = "overview"


@dataclass(frozen=True, slots=True)
class StartGateStatus:
    """Whether a squad has a fresh, passed start gate."""

    present: bool
    passed: bool
    fresh: bool

    def to_jsonable(self) -> JsonObject:
        """Return a JSON-compatible start-gate status object."""
        return {"present": self.present, "passed": self.passed, "fresh": self.fresh}


@dataclass(frozen=True, slots=True)
class SquadStatus:
    """A single squad's derived live status."""

    squad_id: str
    scope: str | None
    depends_on: tuple[str, ...]
    blocks: tuple[str, ...]
    initialized: bool
    stage: Stage | None
    active_attempt: int | None
    start_gate: StartGateStatus
    dependencies_satisfied: bool
    started: bool
    done: bool
    aborted: bool
    blocked: bool
    runnable: bool
    next_to_start: bool

    def to_jsonable(self) -> JsonObject:
        """Return a JSON-compatible squad status object."""
        return {
            "squad_id": self.squad_id,
            "scope": self.scope,
            "depends_on": list(self.depends_on),
            "blocks": list(self.blocks),
            "initialized": self.initialized,
            "stage": None if self.stage is None else self.stage.value,
            "active_attempt": self.active_attempt,
            "start_gate": self.start_gate.to_jsonable(),
            "dependencies_satisfied": self.dependencies_satisfied,
            "started": self.started,
            "done": self.done,
            "aborted": self.aborted,
            "blocked": self.blocked,
            "runnable": self.runnable,
            "next_to_start": self.next_to_start,
        }


@dataclass(frozen=True, slots=True)
class PlatoonStatus:
    """The whole platoon snapshot."""

    platoon_goal: str | None
    global_order: tuple[tuple[str, ...], ...]
    squads: tuple[SquadStatus, ...]

    def squad(self, squad_id: str) -> SquadStatus | None:
        """Return the status for one squad, or None when it is unknown."""
        for status in self.squads:
            if status.squad_id == squad_id:
                return status
        return None

    def next_squads(self) -> tuple[SquadStatus, ...]:
        """Return squads ready to start, ordered by the global dependency order."""
        ready = {
            status.squad_id: status for status in self.squads if status.next_to_start
        }
        ordered: list[SquadStatus] = []
        for wave in self.global_order:
            ordered.extend(ready[squad_id] for squad_id in wave if squad_id in ready)
        placed = {status.squad_id for status in ordered}
        ordered.extend(
            status
            for status in self.squads
            if status.next_to_start and status.squad_id not in placed
        )
        return tuple(ordered)

    def to_jsonable(self) -> JsonObject:
        """Return a JSON-compatible platoon status object."""
        return {
            "platoon_goal": self.platoon_goal,
            "global_order": [list(wave) for wave in self.global_order],
            "squads": [status.to_jsonable() for status in self.squads],
            "next_squads": [status.squad_id for status in self.next_squads()],
        }


@dataclass(frozen=True, slots=True)
class _SquadInputs:
    squad_id: str
    scope: str | None
    depends_on: tuple[str, ...]
    state: SquadState | None
    start_gate: StartGateRecord | None
    dispatched: bool


def collect_platoon_status(root: str | Path) -> PlatoonStatus:
    """Assemble a live platoon snapshot from on-disk artifacts."""
    artifact_root = ArtifactRoot.from_user_input(root)
    checklist = _read_optional(
        artifact_root.omo_path("platoon", "checklist.json"),
    )
    if checklist is None:
        reason = "platoon checklist is missing; run marshal init first"
        root_text = str(artifact_root.root)
        raise ValidationError(OVERVIEW_CONTEXT, "checklist", root_text, reason)

    inputs = _collect_inputs(artifact_root, checklist)
    done_by_squad = {item.squad_id: _is_done(item.state) for item in inputs}
    blocks_by_squad = _blocks_by_squad(inputs)
    squads = tuple(
        _squad_status(item, done_by_squad, blocks_by_squad.get(item.squad_id, ()))
        for item in inputs
    )
    return PlatoonStatus(
        platoon_goal=_optional_text(checklist.get("platoon_goal")),
        global_order=_global_order(checklist.get("global_order")),
        squads=squads,
    )


def _collect_inputs(
    artifact_root: ArtifactRoot,
    checklist: JsonObject,
) -> tuple[_SquadInputs, ...]:
    squads = checklist.get("squads")
    if not isinstance(squads, dict):
        reason = "checklist squads must be an object"
        raise ValidationError(OVERVIEW_CONTEXT, "squads", repr(squads), reason)
    return tuple(
        _squad_inputs(artifact_root, _validated_squad_id(squad_id), entry)
        for squad_id, entry in squads.items()
    )


def _squad_inputs(
    artifact_root: ArtifactRoot,
    squad_id: str,
    entry: JsonValue,
) -> _SquadInputs:
    state = _read_state(artifact_root, squad_id)
    start_gate = _read_start_gate(artifact_root, squad_id)
    scope = state.scope if state is not None else _entry_scope(entry)
    return _SquadInputs(
        squad_id=squad_id,
        scope=scope,
        depends_on=_entry_depends_on(entry),
        state=state,
        start_gate=start_gate,
        dispatched=_is_dispatched(artifact_root, squad_id, state),
    )


def _blocks_by_squad(inputs: tuple[_SquadInputs, ...]) -> dict[str, tuple[str, ...]]:
    blocks: dict[str, list[str]] = {item.squad_id: [] for item in inputs}
    for item in inputs:
        for dependency in item.depends_on:
            if dependency in blocks:
                blocks[dependency].append(item.squad_id)
    return {squad_id: tuple(blocked) for squad_id, blocked in blocks.items()}


def _squad_status(
    item: _SquadInputs,
    done_by_squad: dict[str, bool],
    blocks: tuple[str, ...],
) -> SquadStatus:
    state = item.state
    stage = None if state is None else state.current_stage
    done = _is_done(state)
    aborted = stage is Stage.ABORTED
    blocked = stage is Stage.BLOCKED
    start_gate = _start_gate_status(item.start_gate, state)
    dependencies_satisfied = all(
        done_by_squad.get(dependency, False) for dependency in item.depends_on
    )
    started = item.dispatched
    runnable = dependencies_satisfied and not done and not aborted
    next_to_start = runnable and not started and not blocked
    return SquadStatus(
        squad_id=item.squad_id,
        scope=item.scope,
        depends_on=item.depends_on,
        blocks=blocks,
        initialized=state is not None,
        stage=stage,
        active_attempt=None if state is None else state.active_attempt,
        start_gate=start_gate,
        dependencies_satisfied=dependencies_satisfied,
        started=started,
        done=done,
        aborted=aborted,
        blocked=blocked,
        runnable=runnable,
        next_to_start=next_to_start,
    )


def _start_gate_status(
    start_gate: StartGateRecord | None,
    state: SquadState | None,
) -> StartGateStatus:
    if start_gate is None:
        return StartGateStatus(present=False, passed=False, fresh=False)
    passed = start_gate.gate_status == "passed"
    fresh = (
        passed
        and state is not None
        and start_gate.current_stage == state.current_stage
        and start_gate.active_attempt == state.active_attempt
    )
    return StartGateStatus(present=True, passed=passed, fresh=fresh)


def _is_done(state: SquadState | None) -> bool:
    return state is not None and state.current_stage is Stage.DONE


def _is_dispatched(
    artifact_root: ArtifactRoot,
    squad_id: str,
    state: SquadState | None,
) -> bool:
    if state is None:
        return False
    ledger_path = artifact_root.omo_path("squad", squad_id, "ledger.jsonl")
    if not ledger_path.exists():
        return False
    attempt = state.active_attempt
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    return any(_is_dispatch_line(line, ledger_path, attempt) for line in lines)


def _is_dispatch_line(line: str, ledger_path: Path, active_attempt: int) -> bool:
    if not line:
        return False
    event = parse_json_object(line, ledger_path)
    return event.get("event") == "dispatched" and event.get("attempt") == active_attempt


def _read_state(artifact_root: ArtifactRoot, squad_id: str) -> SquadState | None:
    raw = _read_optional(artifact_root.omo_path("squad", squad_id, "state.json"))
    if raw is None:
        return None
    return SquadState.from_mapping(raw)


def _read_start_gate(
    artifact_root: ArtifactRoot,
    squad_id: str,
) -> StartGateRecord | None:
    raw = _read_optional(artifact_root.omo_path("squad", squad_id, "start-gate.json"))
    if raw is None:
        return None
    return StartGateRecord.from_mapping(raw)


def _read_optional(path: Path) -> JsonObject | None:
    try:
        return read_json(path)
    except JsonIOError:
        return None


def _entry_scope(entry: JsonValue) -> str | None:
    if isinstance(entry, dict):
        return _optional_text(entry.get("scope"))
    return None


def _entry_depends_on(entry: JsonValue) -> tuple[str, ...]:
    if not isinstance(entry, dict):
        return ()
    depends_on = entry.get("depends_on")
    if not isinstance(depends_on, list):
        return ()
    return tuple(item for item in depends_on if isinstance(item, str) and item)


def _global_order(value: JsonValue) -> tuple[tuple[str, ...], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        tuple(item for item in wave if isinstance(item, str) and item)
        for wave in value
        if isinstance(wave, list)
    )


def _optional_text(value: JsonValue) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _validated_squad_id(squad_id: str) -> str:
    return validate_squad_id(squad_id)


__all__ = [
    "PlatoonStatus",
    "SquadStatus",
    "StartGateStatus",
    "collect_platoon_status",
]
