"""Ledger events emitted by squad routing transitions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from marshal_cli.jsonio import append_jsonl
from marshal_cli.ledger import LedgerAppendRequest

if TYPE_CHECKING:
    from pathlib import Path

    from marshal_cli.models import Report, SquadState, Stage


def append_backtrack_events(
    ledger_path: Path,
    previous: SquadState,
    routed: SquadState,
    report: Report,
    source_stage: Stage,
) -> None:
    """Append old-attempt audit events when routing creates a new attempt."""
    if routed.active_attempt == previous.active_attempt:
        return

    event_details = (
        (
            "attempt-aborted",
            source_stage.value,
            f"aborted after {report.type.value}: {report.detail}",
        ),
        (
            "backtrack",
            routed.current_stage.value,
            f"backtrack to {routed.current_stage.value}: {report.detail}",
        ),
    )
    for event, stage, detail in event_details:
        request = LedgerAppendRequest(
            squad_id=previous.squad_id,
            event=event,
            attempt=previous.active_attempt,
            stage=stage,
            task="route",
            detail=detail,
            findings=report.findings,
            evidence=report.evidence,
        )
        append_jsonl(ledger_path, request.to_event(_utc_timestamp()).to_jsonable())


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()


__all__ = ["append_backtrack_events"]
