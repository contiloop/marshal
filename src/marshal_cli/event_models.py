"""Event and report domain models for Marshal orchestration artifacts."""

from __future__ import annotations

from dataclasses import dataclass

from marshal_cli.model_types import (
    JsonMapping,
    JsonObject,
    ReportSource,
    ReportType,
    Stage,
    StartGateSource,
    invalid,
    required_mapping,
    required_positive_int,
    required_str,
    required_str_tuple,
    validate_report_type,
    validate_squad_id,
    validate_stage,
)


@dataclass(frozen=True, slots=True)
class Report:
    """A stage-to-Squad-Leader report."""

    source: ReportSource
    type: ReportType
    detail: str
    findings: tuple[str, ...]
    evidence: tuple[str, ...]

    def to_jsonable(self) -> JsonObject:
        """Return a JSON-compatible report object."""
        return {
            "source": self.source.value,
            "type": self.type.value,
            "detail": self.detail,
            "findings": list(self.findings),
            "evidence": list(self.evidence),
        }

    @classmethod
    def from_mapping(cls, data: JsonMapping) -> Report:
        """Parse a stage report from JSON."""
        source = required_str(data, "source", "report")
        try:
            report_source = ReportSource(source)
        except ValueError as exc:
            context = "report"
            field = "source"
            reason = "unsupported source"
            raise invalid(context, field, source, reason) from exc
        return cls(
            source=report_source,
            type=validate_report_type(required_str(data, "type", "report")),
            detail=required_str(data, "detail", "report"),
            findings=required_str_tuple(data, "findings", "report"),
            evidence=required_str_tuple(data, "evidence", "report"),
        )


@dataclass(frozen=True, slots=True)
class AttemptEvent:
    """An append-only attempt ledger event."""

    event: str
    squad_id: str
    attempt: int
    stage: Stage
    task: str
    detail: str
    findings: tuple[str, ...]
    evidence: tuple[str, ...]
    ts: str

    def __post_init__(self) -> None:
        """Validate the squad id after dataclass construction."""
        _ = validate_squad_id(self.squad_id)

    def to_jsonable(self) -> JsonObject:
        """Return a JSON-compatible attempt event object."""
        return {
            "event": self.event,
            "squad_id": self.squad_id,
            "attempt": self.attempt,
            "stage": self.stage.value,
            "task": self.task,
            "detail": self.detail,
            "findings": list(self.findings),
            "evidence": list(self.evidence),
            "ts": self.ts,
        }

    @classmethod
    def from_mapping(cls, data: JsonMapping) -> AttemptEvent:
        """Parse one append-only ledger event."""
        return cls(
            event=required_str(data, "event", "attempt"),
            squad_id=validate_squad_id(required_str(data, "squad_id", "attempt")),
            attempt=required_positive_int(data, "attempt", "attempt"),
            stage=validate_stage(required_str(data, "stage", "attempt")),
            task=required_str(data, "task", "attempt"),
            detail=required_str(data, "detail", "attempt"),
            findings=required_str_tuple(data, "findings", "attempt"),
            evidence=required_str_tuple(data, "evidence", "attempt"),
            ts=required_str(data, "ts", "attempt"),
        )


@dataclass(frozen=True, slots=True)
class StartGateRecord:
    """The persisted handover-lite start gate result."""

    squad_id: str
    gate_status: str
    source: StartGateSource
    current_stage: Stage
    active_attempt: int
    source_artifacts: tuple[str, ...]
    scope_authority: str
    freshness: str
    applied_example: str

    def to_jsonable(self) -> JsonObject:
        """Return a JSON-compatible start gate object."""
        return {
            "squad_id": self.squad_id,
            "gate_status": self.gate_status,
            "source": self.source.value,
            "current_stage": self.current_stage.value,
            "active_attempt": self.active_attempt,
            "source_artifacts": list(self.source_artifacts),
            "scope_authority": self.scope_authority,
            "freshness": self.freshness,
            "applied_example": self.applied_example,
        }

    @classmethod
    def from_mapping(cls, data: JsonMapping) -> StartGateRecord:
        """Parse a persisted start gate record."""
        source = required_str(data, "source", "start_gate")
        try:
            gate_source = StartGateSource(source)
        except ValueError as exc:
            context = "start_gate"
            field = "source"
            reason = "unsupported source"
            raise invalid(context, field, source, reason) from exc
        return cls(
            squad_id=validate_squad_id(required_str(data, "squad_id", "start_gate")),
            gate_status=required_str(data, "gate_status", "start_gate"),
            source=gate_source,
            current_stage=validate_stage(
                required_str(data, "current_stage", "start_gate"),
            ),
            active_attempt=required_positive_int(
                data,
                "active_attempt",
                "start_gate",
            ),
            source_artifacts=required_str_tuple(
                data,
                "source_artifacts",
                "start_gate",
            ),
            scope_authority=required_str(data, "scope_authority", "start_gate"),
            freshness=required_str(data, "freshness", "start_gate"),
            applied_example=required_str(data, "applied_example", "start_gate"),
        )


@dataclass(frozen=True, slots=True)
class DelegationPayload:
    """A start-work delegation payload emitted by Marshal."""

    squad_id: str
    plan: str
    state: str
    ledger: str
    assignment: str
    active_attempt: int
    start_gate_status: str
    command: str
    payload: JsonObject

    def to_jsonable(self) -> JsonObject:
        """Return a JSON-compatible delegation payload object."""
        return {
            "squad_id": self.squad_id,
            "plan": self.plan,
            "state": self.state,
            "ledger": self.ledger,
            "assignment": self.assignment,
            "active_attempt": self.active_attempt,
            "start_gate_status": self.start_gate_status,
            "command": self.command,
            "payload": self.payload,
        }

    @classmethod
    def from_mapping(cls, data: JsonMapping) -> DelegationPayload:
        """Parse a start-work delegation payload."""
        return cls(
            squad_id=validate_squad_id(required_str(data, "squad_id", "delegation")),
            plan=required_str(data, "plan", "delegation"),
            state=required_str(data, "state", "delegation"),
            ledger=required_str(data, "ledger", "delegation"),
            assignment=required_str(data, "assignment", "delegation"),
            active_attempt=required_positive_int(
                data,
                "active_attempt",
                "delegation",
            ),
            start_gate_status=required_str(data, "start_gate_status", "delegation"),
            command=required_str(data, "command", "delegation"),
            payload=dict(required_mapping(data, "payload", "delegation")),
        )
