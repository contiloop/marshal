"""Shared Marshal model types, enums, and validation helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final, override

SQUAD_ID_PATTERN: Final = re.compile(r"^squad-[a-z0-9]+(?:-[a-z0-9]+)*$")

type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
type JsonObject = dict[str, JsonValue]
type JsonMapping = Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ValidationError(Exception):
    """Typed parse failure for a Marshal artifact contract."""

    context: str
    field: str
    value: str
    reason: str

    @override
    def __str__(self) -> str:
        """Render a CLI-safe validation message."""
        return f"{self.context} {self.field} invalid: {self.value!r} ({self.reason})"


@unique
class Stage(StrEnum):
    """Squad lifecycle stages persisted in state files."""

    SYNC = "sync"
    PLAN = "plan"
    WORK = "work"
    REVIEW = "review"
    DONE = "done"
    BLOCKED = "blocked"
    ABORTED = "aborted"


@unique
class ReportType(StrEnum):
    """Backward-routing report types accepted by Squad Leader."""

    INTENT_UNCLEAR = "intent_unclear"
    REQUIREMENT_MISSING = "requirement_missing"
    DESIGN_FLAW = "design_flaw"
    DEPENDENCY_UNEXPECTED = "dependency_unexpected"
    EXECUTION_FAILURE = "execution_failure"
    THIRD_FAILURE = "third_failure"
    BLOCKED = "blocked"


@unique
class ReportSource(StrEnum):
    """Marshal stage or worker source for a report."""

    SYNC = "sync"
    PLAN = "plan"
    WORK = "work"
    REVIEW = "review"
    WORKER = "worker"


@unique
class StartGateSource(StrEnum):
    """Source artifact categories accepted by the start gate."""

    ASSIGNMENT = "assignment"
    STATE = "state"
    PLAN = "plan"
    HANDOVER = "handover"


def validate_squad_id(squad_id: str) -> str:
    """Return a squad id only when it matches Marshal's slug contract."""
    if SQUAD_ID_PATTERN.fullmatch(squad_id) is None:
        context = "squad"
        field = "squad_id"
        reason = "expected squad-<slug>"
        raise invalid(context, field, squad_id, reason)
    return squad_id


def validate_stage(stage: str) -> Stage:
    """Parse a persisted stage string into a Stage enum."""
    try:
        return Stage(stage)
    except ValueError as exc:
        context = "state"
        field = "stage"
        reason = "unknown stage"
        raise invalid(context, field, stage, reason) from exc


def validate_report_type(report_type: str) -> ReportType:
    """Parse a report type string into an allowed routing signal."""
    try:
        return ReportType(report_type)
    except ValueError as exc:
        context = "report"
        field = "type"
        reason = "unsupported report type"
        raise invalid(context, field, report_type, reason) from exc


def validate_dependency_references(
    squad_id: str,
    depends_on: tuple[str, ...],
    known_squads: tuple[str, ...],
) -> None:
    """Ensure dependencies point to known squads and never to the same squad."""
    known = set(known_squads)
    for dependency in depends_on:
        _ = validate_squad_id(dependency)
        if dependency == squad_id:
            context = "assignment"
            field = "depends_on"
            reason = "self dependency"
            raise invalid(context, field, dependency, reason)
        if dependency not in known:
            context = "assignment"
            field = "depends_on"
            reason = "unknown dependency"
            raise invalid(context, field, dependency, reason)


def validate_worker_conversation_policy(policy: str) -> str:
    """Return policy text only when workers are barred from direct user asks."""
    normalized = policy.casefold()
    if "ask user directly" in normalized or "may ask user" in normalized:
        context = "conversation_policy"
        field = "worker"
        reason = "worker cannot ask user directly"
        raise invalid(context, field, policy, reason)
    return policy


def required_value(data: JsonMapping, field: str, context: str) -> JsonValue:
    """Return a required JSON value or raise the artifact validation error."""
    if field not in data:
        raise invalid(context, field, "<missing>", "required field")
    return data[field]


def invalid(context: str, field: str, value: str, reason: str) -> ValidationError:
    """Build a typed Marshal validation error."""
    return ValidationError(context, field, value, reason)


def required_str(data: JsonMapping, field: str, context: str) -> str:
    """Return a required non-empty string field."""
    value = required_value(data, field, context)
    if isinstance(value, str) and value:
        return value
    raise invalid(context, field, repr(value), "expected non-empty string")


def optional_str(data: JsonMapping, field: str, context: str) -> str | None:
    """Return an optional string or null field."""
    if field not in data:
        return None
    value = data[field]
    if value is None:
        return None
    if isinstance(value, str) and value:
        return value
    raise invalid(context, field, repr(value), "expected string or null")


def required_positive_int(data: JsonMapping, field: str, context: str) -> int:
    """Return a required positive integer field."""
    value = required_value(data, field, context)
    if isinstance(value, bool):
        raise invalid(context, field, str(value), "expected positive integer")
    if isinstance(value, int) and value > 0:
        return value
    raise invalid(context, field, repr(value), "expected positive integer")


def required_mapping(data: JsonMapping, field: str, context: str) -> JsonObject:
    """Return a required JSON object field."""
    value = required_value(data, field, context)
    if isinstance(value, dict):
        return value
    raise invalid(context, field, repr(value), "expected object")


def required_str_tuple(
    data: JsonMapping,
    field: str,
    context: str,
) -> tuple[str, ...]:
    """Return a required list of strings as an immutable tuple."""
    value = required_value(data, field, context)
    if isinstance(value, list):
        return str_tuple(value, field, context)
    raise invalid(context, field, repr(value), "expected string list")


def required_mapping_tuple(
    data: JsonMapping,
    field: str,
    context: str,
) -> tuple[JsonObject, ...]:
    """Return a required list of JSON objects as an immutable tuple."""
    value = required_value(data, field, context)
    if isinstance(value, list):
        return tuple(mapping_item(item, field, context) for item in value)
    raise invalid(context, field, repr(value), "expected object list")


def required_str_map(data: JsonMapping, field: str, context: str) -> dict[str, str]:
    """Return a required mapping with string values."""
    mapping = required_mapping(data, field, context)
    return {key: string_item(value, field, context) for key, value in mapping.items()}


def required_order(
    data: JsonMapping,
    field: str,
    context: str,
) -> tuple[tuple[str, ...], ...]:
    """Return required global squad waves."""
    value = required_value(data, field, context)
    if isinstance(value, list):
        return tuple(
            str_tuple(list_item(wave, field, context), field, context) for wave in value
        )
    raise invalid(context, field, repr(value), "expected squad id waves")


def str_tuple(values: list[JsonValue], field: str, context: str) -> tuple[str, ...]:
    """Return string-only JSON array items as an immutable tuple."""
    return tuple(string_item(value, field, context) for value in values)


def string_item(value: JsonValue, field: str, context: str) -> str:
    """Return one non-empty string item."""
    if isinstance(value, str) and value:
        return value
    raise invalid(context, field, repr(value), "expected string item")


def mapping_item(value: JsonValue, field: str, context: str) -> JsonObject:
    """Return one JSON object item."""
    if isinstance(value, dict):
        return value
    raise invalid(context, field, repr(value), "expected object item")


def list_item(value: JsonValue, field: str, context: str) -> list[JsonValue]:
    """Return one JSON list item."""
    if isinstance(value, list):
        return value
    raise invalid(context, field, repr(value), "expected list item")
