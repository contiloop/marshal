"""Assignment domain models for Marshal orchestration artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from marshal_cli.model_types import (
    JsonMapping,
    JsonObject,
    required_mapping,
    required_order,
    required_str,
    required_str_map,
    required_str_tuple,
    validate_dependency_references,
    validate_squad_id,
    validate_worker_conversation_policy,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class AssignedScope:
    """The scope contract assigned to one squad."""

    squad_id: str
    goal: str
    in_scope: tuple[str, ...]
    out_of_scope: tuple[str, ...]
    depends_on: tuple[str, ...]
    blocks: tuple[str, ...]
    success_evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate id-shaped fields after dataclass construction."""
        _ = validate_squad_id(self.squad_id)
        validate_dependency_references(self.squad_id, self.depends_on, self.depends_on)
        for blocked in self.blocks:
            _ = validate_squad_id(blocked)

    def to_jsonable(self) -> JsonObject:
        """Return a JSON-compatible assignment scope object."""
        return {
            "squad_id": self.squad_id,
            "goal": self.goal,
            "in_scope": list(self.in_scope),
            "out_of_scope": list(self.out_of_scope),
            "depends_on": list(self.depends_on),
            "blocks": list(self.blocks),
            "success_evidence": list(self.success_evidence),
        }

    @classmethod
    def from_mapping(cls, data: JsonMapping) -> AssignedScope:
        """Parse an assignment scope from a JSON mapping."""
        return cls(
            squad_id=required_str(data, "squad_id", "assigned_scope"),
            goal=required_str(data, "goal", "assigned_scope"),
            in_scope=required_str_tuple(data, "in_scope", "assigned_scope"),
            out_of_scope=required_str_tuple(data, "out_of_scope", "assigned_scope"),
            depends_on=required_str_tuple(data, "depends_on", "assigned_scope"),
            blocks=required_str_tuple(data, "blocks", "assigned_scope"),
            success_evidence=required_str_tuple(
                data,
                "success_evidence",
                "assigned_scope",
            ),
        )


@dataclass(frozen=True, slots=True)
class PlatoonAssignment:
    """A Platoon Leader packet for one squad."""

    platoon_goal: str
    global_order: tuple[tuple[str, ...], ...]
    squads_summary: Mapping[str, str]
    assigned_scope: AssignedScope
    basic_rules: tuple[str, ...]
    conversation_policy: str
    abort_policy: str

    def __post_init__(self) -> None:
        """Validate packet references and conversation policy."""
        known_squads = tuple(self.squads_summary)
        validate_dependency_references(
            self.assigned_scope.squad_id,
            self.assigned_scope.depends_on,
            known_squads,
        )
        _ = validate_worker_conversation_policy(self.conversation_policy)

    def to_jsonable(self) -> JsonObject:
        """Return a JSON-compatible assignment packet object."""
        return {
            "platoon_goal": self.platoon_goal,
            "global_order": [list(wave) for wave in self.global_order],
            "squads_summary": dict(self.squads_summary),
            "assigned_scope": self.assigned_scope.to_jsonable(),
            "basic_rules": list(self.basic_rules),
            "conversation_policy": self.conversation_policy,
            "abort_policy": self.abort_policy,
        }

    @classmethod
    def from_mapping(cls, data: JsonMapping) -> PlatoonAssignment:
        """Parse a Platoon Leader assignment packet."""
        return cls(
            platoon_goal=required_str(data, "platoon_goal", "assignment"),
            global_order=required_order(data, "global_order", "assignment"),
            squads_summary=required_str_map(data, "squads_summary", "assignment"),
            assigned_scope=AssignedScope.from_mapping(
                required_mapping(data, "assigned_scope", "assignment"),
            ),
            basic_rules=required_str_tuple(data, "basic_rules", "assignment"),
            conversation_policy=required_str(
                data,
                "conversation_policy",
                "assignment",
            ),
            abort_policy=required_str(data, "abort_policy", "assignment"),
        )
