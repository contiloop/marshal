"""Append-only squad attempt ledger domain and queries."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from marshal_cli.jsonio import JsonIOError, append_jsonl, read_json
from marshal_cli.models import (
    AttemptEvent,
    JsonObject,
    SquadState,
    ValidationError,
    validate_squad_id,
)
from marshal_cli.paths import ArtifactRoot

if TYPE_CHECKING:
    from pathlib import Path

ATTEMPT_PATTERN: Final = re.compile(r'"attempt"\s*:\s*([1-9][0-9]*)')


@dataclass(frozen=True, slots=True)
class LedgerAppendRequest:
    """CLI-facing data required to append one ledger event."""

    squad_id: str
    event: str
    attempt: int
    stage: str
    task: str
    detail: str
    findings: tuple[str, ...]
    evidence: tuple[str, ...]

    def to_event(self, timestamp: str) -> AttemptEvent:
        """Parse the request into a validated ledger event."""
        return AttemptEvent.from_mapping(
            {
                "event": self.event,
                "squad_id": self.squad_id,
                "attempt": self.attempt,
                "stage": self.stage,
                "task": self.task,
                "detail": self.detail,
                "findings": list(self.findings),
                "evidence": list(self.evidence),
                "ts": timestamp,
            },
        )


@dataclass(frozen=True, slots=True)
class _LedgerAppendResult:
    ledger_path: Path
    event: AttemptEvent

    def to_jsonable(self) -> JsonObject:
        """Return the append result as JSON-compatible data."""
        return {
            "ledger_path": str(self.ledger_path),
            "event": self.event.to_jsonable(),
        }


@dataclass(frozen=True, slots=True)
class _LatestLedgerResult:
    squad_id: str
    ledger_path: Path
    state_path: Path
    active_attempt: int
    event_lines: tuple[str, ...]

    def to_json_text(self) -> str:
        lines = [
            "{",
            f'  "active_attempt": {self.active_attempt},',
            '  "events": [',
            *_event_json_lines(self.event_lines),
            "  ],",
            f'  "ledger_path": {json.dumps(str(self.ledger_path))},',
            f'  "squad_id": {json.dumps(self.squad_id)},',
            f'  "state_path": {json.dumps(str(self.state_path))}',
            "}",
        ]
        return "\n".join(lines)


def append_ledger_entry(
    root: str | Path,
    request: LedgerAppendRequest,
) -> _LedgerAppendResult:
    """Append one validated event to `.omo/squad/<id>/ledger.jsonl`."""
    event = request.to_event(_utc_timestamp())
    artifact_root = ArtifactRoot.from_user_input(root)
    ledger_path = _ledger_path(artifact_root, event.squad_id)
    append_jsonl(ledger_path, event.to_jsonable())
    return _LedgerAppendResult(ledger_path=ledger_path, event=event)


def latest_attempt_events(root: str | Path, squad_id: str) -> _LatestLedgerResult:
    """Read ledger events whose attempt matches `state.json.active_attempt`."""
    artifact_root = ArtifactRoot.from_user_input(root)
    validated_squad_id = validate_squad_id(squad_id)
    state_path = _state_path(artifact_root, validated_squad_id)
    state = SquadState.from_mapping(read_json(state_path))
    if state.squad_id != validated_squad_id:
        context = "ledger"
        field = "squad_id"
        reason = "state belongs to a different squad"
        raise ValidationError(context, field, state.squad_id, reason)

    ledger_path = _ledger_path(artifact_root, validated_squad_id)
    event_lines = tuple(
        line
        for line in _read_ledger_lines(ledger_path)
        if _line_attempt(line, ledger_path) == state.active_attempt
    )
    return _LatestLedgerResult(
        squad_id=validated_squad_id,
        ledger_path=ledger_path,
        state_path=state_path,
        active_attempt=state.active_attempt,
        event_lines=event_lines,
    )


def _read_ledger_lines(ledger_path: Path) -> tuple[str, ...]:
    if not ledger_path.exists():
        return ()
    try:
        lines = ledger_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise JsonIOError(ledger_path, "failed to read JSONL artifact") from error
    return tuple(line for line in lines if line)


def _line_attempt(line: str, ledger_path: Path) -> int:
    found = ATTEMPT_PATTERN.search(line)
    if found is None:
        raise JsonIOError(ledger_path, "invalid ledger attempt")
    return int(found.group(1))


def _event_json_lines(event_lines: tuple[str, ...]) -> list[str]:
    emitted: list[str] = []
    for index, line in enumerate(event_lines):
        suffix = "," if index < len(event_lines) - 1 else ""
        rendered = line.replace('"attempt":', '"attempt": ')
        emitted.append(f"    {rendered}{suffix}")
    return emitted


def _ledger_path(root: ArtifactRoot, squad_id: str) -> Path:
    return root.omo_path("squad", squad_id, "ledger.jsonl")


def _state_path(root: ArtifactRoot, squad_id: str) -> Path:
    return root.omo_path("squad", squad_id, "state.json")


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()
