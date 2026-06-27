"""Squad lifecycle transitions Marshal records directly: abort and complete.

These are the only forward/terminal transitions Marshal owns. Backward routing
lives in `squad_state`; the actual implementation work happens in the external
start-work runner. `abort` records an operator stop (and blocks later
delegation); `complete` records an evidence-backed `done` claim so dependency
waves can advance.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from marshal_cli.evidence import resolve_evidence_path
from marshal_cli.jsonio import JsonIOError, read_json, write_json
from marshal_cli.ledger_core import LedgerAppendRequest, append_ledger_entry
from marshal_cli.lifecycle_models import (
    AbortAllResult,
    AbortResult,
    CompleteResult,
)
from marshal_cli.models import (
    SquadState,
    Stage,
    StageHistoryEntry,
    ValidationError,
    validate_squad_id,
)
from marshal_cli.overview import collect_platoon_status
from marshal_cli.paths import ArtifactRoot

if TYPE_CHECKING:
    from pathlib import Path

LIFECYCLE_CONTEXT: Final = "lifecycle"


def abort_squad(root: str | Path, squad_id: str, reason: str) -> AbortResult:
    """Record an operator abort for one squad."""
    artifact_root = ArtifactRoot.from_user_input(root)
    validated_squad_id = validate_squad_id(squad_id)
    abort_reason = _required_reason(reason)
    state = _load_state(artifact_root, validated_squad_id)
    _ensure_abortable(state)
    return _apply_abort(artifact_root, state, abort_reason)


def abort_platoon(root: str | Path, reason: str) -> AbortAllResult:
    """Abort every active squad and report which squads were skipped."""
    artifact_root = ArtifactRoot.from_user_input(root)
    abort_reason = _required_reason(reason)
    status = collect_platoon_status(artifact_root.root)
    aborted: list[AbortResult] = []
    skipped: list[str] = []
    for squad in status.squads:
        if not squad.initialized or squad.done or squad.aborted:
            skipped.append(squad.squad_id)
            continue
        state = _load_state(artifact_root, squad.squad_id)
        aborted.append(_apply_abort(artifact_root, state, abort_reason))
    return AbortAllResult(aborted=tuple(aborted), skipped=tuple(skipped))


def complete_squad(
    root: str | Path,
    squad_id: str,
    evidence: tuple[str, ...],
    detail: str,
) -> CompleteResult:
    """Record a done claim, requiring real evidence files to exist."""
    artifact_root = ArtifactRoot.from_user_input(root)
    validated_squad_id = validate_squad_id(squad_id)
    done_detail = _required_detail(detail)
    state = _load_state(artifact_root, validated_squad_id)
    _ensure_completable(state)
    _verify_evidence(artifact_root, evidence)

    timestamp = _utc_timestamp()
    routed = replace(
        state,
        current_stage=Stage.DONE,
        stage_history=(
            *state.stage_history,
            StageHistoryEntry(stage=Stage.DONE, result=done_detail, ts=timestamp),
        ),
    )
    state_path = artifact_root.omo_path("squad", validated_squad_id, "state.json")
    write_json(state_path, routed.to_jsonable())
    _append_event(
        artifact_root,
        validated_squad_id,
        event="completed",
        stage=Stage.DONE,
        attempt=routed.active_attempt,
        task="complete",
        detail=done_detail,
        evidence=evidence,
    )
    return CompleteResult(
        squad_id=validated_squad_id,
        previous_stage=state.current_stage.value,
        current_stage=routed.current_stage.value,
        active_attempt=routed.active_attempt,
        evidence=evidence,
        state_path=state_path,
    )


def _apply_abort(
    artifact_root: ArtifactRoot,
    state: SquadState,
    reason: str,
) -> AbortResult:
    timestamp = _utc_timestamp()
    routed = replace(
        state,
        current_stage=Stage.ABORTED,
        stage_history=(
            *state.stage_history,
            StageHistoryEntry(stage=Stage.ABORTED, result=reason, ts=timestamp),
        ),
    )
    state_path = artifact_root.omo_path("squad", state.squad_id, "state.json")
    write_json(state_path, routed.to_jsonable())
    _append_event(
        artifact_root,
        state.squad_id,
        event="aborted",
        stage=Stage.ABORTED,
        attempt=routed.active_attempt,
        task="abort",
        detail=reason,
        evidence=(),
    )
    return AbortResult(
        squad_id=state.squad_id,
        previous_stage=state.current_stage.value,
        current_stage=routed.current_stage.value,
        active_attempt=routed.active_attempt,
        reason=reason,
        state_path=state_path,
    )


def _ensure_abortable(state: SquadState) -> None:
    if state.current_stage is Stage.ABORTED:
        reason = "squad is already aborted"
        raise ValidationError(LIFECYCLE_CONTEXT, "state", state.squad_id, reason)
    if state.current_stage is Stage.DONE:
        reason = "cannot abort a completed squad"
        raise ValidationError(LIFECYCLE_CONTEXT, "state", state.squad_id, reason)


def _ensure_completable(state: SquadState) -> None:
    if state.current_stage is Stage.ABORTED:
        reason = "cannot complete an aborted squad"
        raise ValidationError(LIFECYCLE_CONTEXT, "state", state.squad_id, reason)
    if state.current_stage is Stage.DONE:
        reason = "squad is already done"
        raise ValidationError(LIFECYCLE_CONTEXT, "state", state.squad_id, reason)


def _verify_evidence(artifact_root: ArtifactRoot, evidence: tuple[str, ...]) -> None:
    if not evidence:
        reason = "done claim requires at least one --evidence path"
        raise ValidationError(LIFECYCLE_CONTEXT, "evidence", "<missing>", reason)
    missing = [
        value
        for value in evidence
        if not resolve_evidence_path(artifact_root, value)[1]
    ]
    if missing:
        reason = "evidence files do not exist"
        raise ValidationError(LIFECYCLE_CONTEXT, "evidence", ",".join(missing), reason)


def _append_event(  # noqa: PLR0913 - one ledger row needs all attempt fields
    artifact_root: ArtifactRoot,
    squad_id: str,
    *,
    event: str,
    stage: Stage,
    attempt: int,
    task: str,
    detail: str,
    evidence: tuple[str, ...],
) -> None:
    request = LedgerAppendRequest(
        squad_id=squad_id,
        event=event,
        attempt=attempt,
        stage=stage.value,
        task=task,
        detail=detail,
        findings=(),
        evidence=evidence,
    )
    _ = append_ledger_entry(artifact_root.root, request)


def _load_state(artifact_root: ArtifactRoot, squad_id: str) -> SquadState:
    state_path = artifact_root.omo_path("squad", squad_id, "state.json")
    try:
        raw = read_json(state_path)
    except JsonIOError as error:
        reason = "squad state is missing; run marshal state init first"
        path = str(state_path)
        raise ValidationError(LIFECYCLE_CONTEXT, "state", path, reason) from error
    state = SquadState.from_mapping(raw)
    if state.squad_id != squad_id:
        reason = "state belongs to a different squad"
        raise ValidationError(LIFECYCLE_CONTEXT, "state", state.squad_id, reason)
    return state


def _required_reason(reason: str) -> str:
    trimmed = reason.strip()
    if not trimmed:
        message = "abort requires a --reason"
        raise ValidationError(LIFECYCLE_CONTEXT, "reason", reason, message)
    return trimmed


def _required_detail(detail: str) -> str:
    trimmed = detail.strip()
    if not trimmed:
        message = "complete requires a --detail done claim"
        raise ValidationError(LIFECYCLE_CONTEXT, "detail", detail, message)
    return trimmed


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "AbortAllResult",
    "AbortResult",
    "CompleteResult",
    "abort_platoon",
    "abort_squad",
    "complete_squad",
]
