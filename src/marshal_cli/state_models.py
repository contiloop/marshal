"""State domain models for Marshal orchestration artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from marshal_cli.model_types import (
    JsonMapping,
    JsonObject,
    Stage,
    optional_str,
    required_mapping_tuple,
    required_positive_int,
    required_str,
    required_str_tuple,
    validate_squad_id,
    validate_stage,
)

if TYPE_CHECKING:
    from marshal_cli.assignment_models import AssignedScope


@dataclass(frozen=True, slots=True)
class StageHistoryEntry:
    """A stage result entry in squad state history."""

    stage: Stage
    result: str
    ts: str

    def to_jsonable(self) -> JsonObject:
        """Return a JSON-compatible stage history object."""
        return {"stage": self.stage.value, "result": self.result, "ts": self.ts}

    @classmethod
    def from_mapping(cls, data: JsonMapping) -> StageHistoryEntry:
        """Parse one stage history entry."""
        return cls(
            stage=validate_stage(required_str(data, "stage", "stage_history")),
            result=required_str(data, "result", "stage_history"),
            ts=required_str(data, "ts", "stage_history"),
        )


@dataclass(frozen=True, slots=True)
class BacktrackRecord:
    """A backward route record preserved in squad state."""

    from_stage: Stage
    to_stage: Stage
    reason: str
    attempt: int
    findings: tuple[str, ...]
    ts: str

    def to_jsonable(self) -> JsonObject:
        """Return a JSON-compatible backtrack object."""
        return {
            "from": self.from_stage.value,
            "to": self.to_stage.value,
            "reason": self.reason,
            "attempt": self.attempt,
            "findings": list(self.findings),
            "ts": self.ts,
        }

    @classmethod
    def from_mapping(cls, data: JsonMapping) -> BacktrackRecord:
        """Parse one backtrack log record."""
        return cls(
            from_stage=validate_stage(required_str(data, "from", "backtrack")),
            to_stage=validate_stage(required_str(data, "to", "backtrack")),
            reason=required_str(data, "reason", "backtrack"),
            attempt=required_positive_int(data, "attempt", "backtrack"),
            findings=required_str_tuple(data, "findings", "backtrack"),
            ts=required_str(data, "ts", "backtrack"),
        )


@dataclass(frozen=True, slots=True)
class SquadState:
    """Persisted Squad Leader state."""

    squad_id: str
    scope: str
    current_stage: Stage
    active_attempt: int
    stage_history: tuple[StageHistoryEntry, ...]
    backtrack_log: tuple[BacktrackRecord, ...]
    sync_artifact: str | None
    plan_artifact: str | None
    boulder: str | None
    branch: str | None
    worktree: str | None

    @classmethod
    def new(cls, scope: AssignedScope, plan_artifact: str | None = None) -> SquadState:
        """Create the initial sync-stage state for an assigned scope."""
        return cls(
            squad_id=scope.squad_id,
            scope=scope.goal,
            current_stage=Stage.SYNC,
            active_attempt=1,
            stage_history=(
                StageHistoryEntry(stage=Stage.SYNC, result="initialized", ts="pending"),
            ),
            backtrack_log=(),
            sync_artifact=None,
            plan_artifact=plan_artifact,
            boulder=None,
            branch=None,
            worktree=None,
        )

    def to_jsonable(self) -> JsonObject:
        """Return a JSON-compatible squad state object."""
        return {
            "squad_id": self.squad_id,
            "scope": self.scope,
            "current_stage": self.current_stage.value,
            "active_attempt": self.active_attempt,
            "stage_history": [entry.to_jsonable() for entry in self.stage_history],
            "backtrack_log": [entry.to_jsonable() for entry in self.backtrack_log],
            "sync_artifact": self.sync_artifact,
            "plan_artifact": self.plan_artifact,
            "boulder": self.boulder,
            "branch": self.branch,
            "worktree": self.worktree,
        }

    @classmethod
    def from_mapping(cls, data: JsonMapping) -> SquadState:
        """Parse a persisted squad state object."""
        return cls(
            squad_id=validate_squad_id(required_str(data, "squad_id", "state")),
            scope=required_str(data, "scope", "state"),
            current_stage=validate_stage(
                required_str(data, "current_stage", "state"),
            ),
            active_attempt=required_positive_int(data, "active_attempt", "state"),
            stage_history=tuple(
                StageHistoryEntry.from_mapping(entry)
                for entry in required_mapping_tuple(data, "stage_history", "state")
            ),
            backtrack_log=tuple(
                BacktrackRecord.from_mapping(entry)
                for entry in required_mapping_tuple(data, "backtrack_log", "state")
            ),
            sync_artifact=optional_str(data, "sync_artifact", "state"),
            plan_artifact=optional_str(data, "plan_artifact", "state"),
            boulder=optional_str(data, "boulder", "state"),
            branch=optional_str(data, "branch", "state"),
            worktree=optional_str(data, "worktree", "state"),
        )
