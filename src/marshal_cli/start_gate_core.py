"""Start-gate ledger event writing."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from marshal_cli.ledger import LedgerAppendRequest
from marshal_cli.models import StartGateRecord, ValidationError

if TYPE_CHECKING:
    from pathlib import Path

START_GATE_CONTEXT = "start_gate"


def append_started_event(
    record: StartGateRecord,
    ledger_path: Path,
    detail: str,
) -> None:
    """Append the start-gate passed event to the squad ledger."""
    event = LedgerAppendRequest(
        squad_id=record.squad_id,
        event="started",
        attempt=record.active_attempt,
        stage=record.current_stage.value,
        task="start-gate",
        detail=detail,
        findings=(record.scope_authority, record.freshness),
        evidence=record.source_artifacts,
    ).to_event(datetime.now(UTC).isoformat())
    encoded = json.dumps(event.to_jsonable(), sort_keys=True)
    try:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("a", encoding="utf-8") as ledger_file:
            _ = ledger_file.write(encoded)
            _ = ledger_file.write("\n")
    except OSError as error:
        reason = "failed to append ledger artifact"
        raise ValidationError(
            START_GATE_CONTEXT,
            "ledger",
            str(ledger_path),
            reason,
        ) from error


__all__ = ["append_started_event"]
