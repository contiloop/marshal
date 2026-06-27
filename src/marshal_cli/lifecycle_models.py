"""Result models for squad lifecycle transitions (abort and complete)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from marshal_cli.models import JsonObject


@dataclass(frozen=True, slots=True)
class AbortResult:
    """Outcome of aborting one squad."""

    squad_id: str
    previous_stage: str
    current_stage: str
    active_attempt: int
    reason: str
    state_path: Path

    def to_jsonable(self) -> JsonObject:
        """Return a JSON-compatible abort result object."""
        return {
            "squad_id": self.squad_id,
            "previous_stage": self.previous_stage,
            "current_stage": self.current_stage,
            "active_attempt": self.active_attempt,
            "reason": self.reason,
            "state_path": str(self.state_path),
        }


@dataclass(frozen=True, slots=True)
class AbortAllResult:
    """Outcome of aborting every active squad in the platoon."""

    aborted: tuple[AbortResult, ...]
    skipped: tuple[str, ...]

    def to_jsonable(self) -> JsonObject:
        """Return a JSON-compatible platoon abort result object."""
        return {
            "aborted": [result.to_jsonable() for result in self.aborted],
            "skipped": list(self.skipped),
        }


@dataclass(frozen=True, slots=True)
class CompleteResult:
    """Outcome of recording an evidence-backed done claim."""

    squad_id: str
    previous_stage: str
    current_stage: str
    active_attempt: int
    evidence: tuple[str, ...]
    state_path: Path

    def to_jsonable(self) -> JsonObject:
        """Return a JSON-compatible complete result object."""
        return {
            "squad_id": self.squad_id,
            "previous_stage": self.previous_stage,
            "current_stage": self.current_stage,
            "active_attempt": self.active_attempt,
            "evidence": list(self.evidence),
            "state_path": str(self.state_path),
        }


__all__ = ["AbortAllResult", "AbortResult", "CompleteResult"]
