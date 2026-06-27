"""Platoon assignment packet writer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

from marshal_cli.jsonio import write_json
from marshal_cli.models import (
    AssignedScope,
    JsonObject,
    PlatoonAssignment,
    ValidationError,
    validate_dependency_references,
    validate_squad_id,
)
from marshal_cli.paths import ArtifactRoot

BASIC_RULES: Final[tuple[str, ...]] = (
    "no-fallback",
    "failing-first-proof",
    "no-suppress-tests-lints-errors",
    "minimal-change",
    "evidence-based-completion",
    "cleanup-receipt",
    "no-tautological-tests",
    "real-surface-e2e",
)
SUCCESS_EVIDENCE: Final[tuple[str, ...]] = (
    "RED/GREEN logs",
    "real-surface proof",
)
CONVERSATION_POLICY: Final = (
    "Workers report blockers to Squad Leader; user questions go through the "
    "Platoon Leader conversation queue."
)
ABORT_POLICY: Final = (
    "If the user changes overall direction, the Platoon Leader propagates aborts "
    "to every active squad."
)
SCOPE_CONTEXT: Final = "scope"
SPEC_FIELD: Final = "spec"
ASSIGNMENT_CONTEXT: Final = "assignment"
DEPENDS_ON_FIELD: Final = "depends_on"
SCOPE_PART_COUNT: Final = 3


@dataclass(frozen=True, slots=True)
class AssignmentWriteResult:
    """Paths and dependency order produced by `marshal init`."""

    checklist_path: Path
    assignment_paths: dict[str, Path]
    dependency_order: tuple[tuple[str, ...], ...]

    def to_jsonable(self) -> JsonObject:
        """Return the command result as JSON-compatible data."""
        assignment_paths: JsonObject = {
            squad_id: str(path) for squad_id, path in self.assignment_paths.items()
        }
        return {
            "checklist_path": str(self.checklist_path),
            "assignment_paths": assignment_paths,
            "dependency_order": [list(wave) for wave in self.dependency_order],
        }


@dataclass(frozen=True, slots=True)
class _ScopeSpec:
    squad_id: str
    goal: str
    depends_on: tuple[str, ...]


def create_assignment_packets(
    root: str | Path,
    platoon_goal: str,
    scope_specs: tuple[str, ...],
) -> AssignmentWriteResult:
    """Create the platoon checklist and one assignment packet per squad."""
    artifact_root = ArtifactRoot.from_user_input(root)
    parsed_specs = _parse_scope_specs(scope_specs)
    known_squads = tuple(scope.squad_id for scope in parsed_specs)
    _validate_all_dependencies(parsed_specs, known_squads)

    global_order = _dependency_order(parsed_specs)
    assigned_scopes = _assigned_scopes(parsed_specs)
    squads_summary = {scope.squad_id: scope.goal for scope in parsed_specs}
    assignments = tuple(
        PlatoonAssignment(
            platoon_goal=platoon_goal,
            global_order=global_order,
            squads_summary=squads_summary,
            assigned_scope=scope,
            basic_rules=BASIC_RULES,
            conversation_policy=CONVERSATION_POLICY,
            abort_policy=ABORT_POLICY,
        )
        for scope in assigned_scopes
    )

    checklist = _checklist(platoon_goal, global_order, assigned_scopes)
    checklist_path = artifact_root.omo_path("platoon", "checklist.json")
    assignment_paths = {
        assignment.assigned_scope.squad_id: artifact_root.omo_path(
            "squad",
            assignment.assigned_scope.squad_id,
            "assignment.json",
        )
        for assignment in assignments
    }

    write_json(checklist_path, checklist)
    for assignment in assignments:
        write_json(
            assignment_paths[assignment.assigned_scope.squad_id],
            assignment.to_jsonable(),
        )

    return AssignmentWriteResult(
        checklist_path=checklist_path,
        assignment_paths=assignment_paths,
        dependency_order=global_order,
    )


def _parse_scope_specs(raw_specs: tuple[str, ...]) -> tuple[_ScopeSpec, ...]:
    if not raw_specs:
        missing_scope = "<missing>"
        reason = "at least one --scope is required"
        raise _invalid_scope(missing_scope, reason)

    specs = tuple(_parse_scope_spec(raw_spec) for raw_spec in raw_specs)
    seen: set[str] = set()
    for spec in specs:
        if spec.squad_id in seen:
            raise _invalid_scope(spec.squad_id, "duplicate squad id")
        seen.add(spec.squad_id)
    return specs


def _parse_scope_spec(raw_spec: str) -> _ScopeSpec:
    parts = tuple(part.strip() for part in raw_spec.split("|"))
    if len(parts) != SCOPE_PART_COUNT:
        reason = "expected <squad-id>|<goal>|<depends_csv_or_->"
        raise _invalid_scope(raw_spec, reason)

    squad_id, goal, raw_dependencies = parts
    _ = validate_squad_id(squad_id)
    if not goal:
        reason = "goal must be non-empty"
        raise _invalid_scope(raw_spec, reason)

    dependencies = _dependencies(raw_dependencies)
    return _ScopeSpec(squad_id=squad_id, goal=goal, depends_on=dependencies)


def _dependencies(raw_dependencies: str) -> tuple[str, ...]:
    if raw_dependencies == "-":
        return ()
    dependencies = tuple(
        dependency.strip()
        for dependency in raw_dependencies.split(",")
        if dependency.strip()
    )
    if not dependencies:
        reason = "dependency list must be non-empty"
        raise _invalid_scope(raw_dependencies, reason)
    return dependencies


def _validate_all_dependencies(
    specs: tuple[_ScopeSpec, ...],
    known_squads: tuple[str, ...],
) -> None:
    for spec in specs:
        for dependency in spec.depends_on:
            if dependency not in known_squads:
                reason = "unknown dependency"
                raise ValidationError(
                    ASSIGNMENT_CONTEXT,
                    DEPENDS_ON_FIELD,
                    dependency,
                    reason,
                )
        validate_dependency_references(spec.squad_id, spec.depends_on, known_squads)


def _dependency_order(specs: tuple[_ScopeSpec, ...]) -> tuple[tuple[str, ...], ...]:
    remaining = {scope.squad_id for scope in specs}
    completed: set[str] = set()
    waves: list[tuple[str, ...]] = []

    while remaining:
        ready = tuple(
            scope.squad_id
            for scope in specs
            if scope.squad_id in remaining
            and all(dependency in completed for dependency in scope.depends_on)
        )
        if not ready:
            blocked = ",".join(sorted(remaining))
            reason = "dependency cycle"
            raise ValidationError(
                ASSIGNMENT_CONTEXT,
                DEPENDS_ON_FIELD,
                blocked,
                reason,
            )
        waves.append(ready)
        completed.update(ready)
        remaining.difference_update(ready)

    return tuple(waves)


def _assigned_scopes(specs: tuple[_ScopeSpec, ...]) -> tuple[AssignedScope, ...]:
    dependents = _dependents_by_squad(specs)
    return tuple(
        AssignedScope(
            squad_id=spec.squad_id,
            goal=spec.goal,
            in_scope=(spec.goal,),
            out_of_scope=tuple(
                other.goal for other in specs if other.squad_id != spec.squad_id
            ),
            depends_on=spec.depends_on,
            blocks=dependents[spec.squad_id],
            success_evidence=SUCCESS_EVIDENCE,
        )
        for spec in specs
    )


def _dependents_by_squad(specs: tuple[_ScopeSpec, ...]) -> dict[str, tuple[str, ...]]:
    dependents: dict[str, list[str]] = {spec.squad_id: [] for spec in specs}
    for spec in specs:
        for dependency in spec.depends_on:
            dependents[dependency].append(spec.squad_id)
    return {
        squad_id: tuple(blocked_squads)
        for squad_id, blocked_squads in dependents.items()
    }


def _checklist(
    platoon_goal: str,
    global_order: tuple[tuple[str, ...], ...],
    assigned_scopes: tuple[AssignedScope, ...],
) -> JsonObject:
    squads: JsonObject = {
        scope.squad_id: {
            "scope": scope.goal,
            "status": "sync",
            "depends_on": list(scope.depends_on),
        }
        for scope in assigned_scopes
    }
    squads_summary: JsonObject = {
        scope.squad_id: scope.goal for scope in assigned_scopes
    }
    return {
        "platoon_goal": platoon_goal,
        "squads": squads,
        "global_order": [list(wave) for wave in global_order],
        "squads_summary": squads_summary,
        "basic_rules": list(BASIC_RULES),
    }


def _invalid_scope(value: str, reason: str) -> ValidationError:
    return ValidationError(SCOPE_CONTEXT, SPEC_FIELD, value, reason)


__all__ = ["AssignmentWriteResult", "create_assignment_packets"]
