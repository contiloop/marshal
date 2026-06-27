"""View models for the live platoon and squad status snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marshal_cli.models import JsonObject, Stage


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


__all__ = ["PlatoonStatus", "SquadStatus", "StartGateStatus"]
