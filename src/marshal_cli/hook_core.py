"""Codex hook entry-point logic for the Marshal control-plane.

These functions let Marshal own Codex's `UserPromptSubmit`, `Stop`, and
`SubagentStop` hooks directly. Marshal is the entry point: it reads its own
platoon and squad artifacts (never a TypeScript reimplementation) and tells
Codex whether to keep working an active squad or how the platoon currently
stands. Rendering is pure and defensive -- an uninitialised platoon, a protected
path, or absent state yields an empty string so the hook stays quiet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from marshal_cli.handover import next_action
from marshal_cli.jsonio import JsonIOError, read_json
from marshal_cli.models import SquadState, Stage, ValidationError
from marshal_cli.overview import collect_platoon_status
from marshal_cli.paths import ArtifactRoot, PathSecurityError

if TYPE_CHECKING:
    from marshal_cli.model_types import JsonObject, JsonValue
    from marshal_cli.overview_models import SquadStatus

ACTIVE_STAGES: Final = frozenset(
    {Stage.SYNC, Stage.PLAN, Stage.WORK, Stage.REVIEW},
)

CONTEXT_PRESSURE_MARKERS: Final[tuple[str, ...]] = (
    "context compacted",
    "context_length_exceeded",
    "skill descriptions were shortened",
    "context_too_large",
    "codex ran out of room in the model's context window",
    "your input exceeds the context window",
    "long threads and multiple compactions",
)

_READ_ERRORS: Final = (ValidationError, JsonIOError, PathSecurityError, OSError)

_STOP_DIRECTIVE_HEADER: Final = (
    "<marshal-continuation>\n"
    "Marshal is the control-plane for this work. Do NOT stop and do NOT ask "
    "whether to continue while a squad is active. Continue the squad below under "
    "Marshal's orchestration."
)

_WORKTREE_NOTE: Final = "(run every edit, test, and command inside it)"


@dataclass(frozen=True, slots=True)
class CodexHookInput:
    """The fields Marshal needs from a Codex hook payload."""

    cwd: str
    stop_hook_active: bool
    transcript_path: str | None


@dataclass(frozen=True, slots=True)
class _ActiveSquad:
    squad_id: str
    stage: Stage
    active_attempt: int
    plan_artifact: str | None
    worktree: str | None
    next_action: str
    paths: dict[str, str]


def parse_hook_input(raw: JsonValue) -> CodexHookInput | None:
    """Leniently parse a Codex hook payload; return None when unusable.

    Only a non-empty `cwd` is required. Every other field is optional, nullable,
    or defaulted so the hook tolerates Codex input variants.
    """
    if not isinstance(raw, dict):
        return None
    cwd = raw.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return None
    transcript_path = raw.get("transcript_path")
    return CodexHookInput(
        cwd=cwd,
        stop_hook_active=raw.get("stop_hook_active") is True,
        transcript_path=(
            transcript_path
            if isinstance(transcript_path, str) and transcript_path
            else None
        ),
    )


def transcript_has_context_pressure(transcript_path: str | None) -> bool:
    """Report whether the transcript shows a context-pressure marker."""
    if transcript_path is None:
        return False
    try:
        text = Path(transcript_path).read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return any(marker in text for marker in CONTEXT_PRESSURE_MARKERS)


def render_stop_output(parsed: CodexHookInput) -> str:
    """Render the Stop/SubagentStop output: block to continue, or empty."""
    if parsed.stop_hook_active:
        return ""
    if transcript_has_context_pressure(parsed.transcript_path):
        return ""
    squads = _active_gated_squads(parsed.cwd)
    if not squads:
        return ""
    return _compact(
        {"decision": "block", "reason": _render_directive(parsed.cwd, squads)}
    )


def render_user_prompt_submit_output(parsed: CodexHookInput) -> str:
    """Render the UserPromptSubmit output: inject platoon status, or empty."""
    summary = _render_status_summary(parsed.cwd)
    if not summary:
        return ""
    return _compact(
        {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": summary,
            },
        },
    )


def _active_gated_squads(cwd: str) -> tuple[_ActiveSquad, ...]:
    try:
        artifact_root = ArtifactRoot.from_user_input(cwd)
        platoon = collect_platoon_status(artifact_root.root)
    except _READ_ERRORS:
        return ()
    active: list[_ActiveSquad] = []
    for status in platoon.squads:
        if not _is_active_gated(status):
            continue
        squad = _load_active_squad(artifact_root, status.squad_id)
        if squad is not None:
            active.append(squad)
    return tuple(active)


def _is_active_gated(status: SquadStatus) -> bool:
    return (
        status.initialized and status.stage in ACTIVE_STAGES and status.start_gate.fresh
    )


def _load_active_squad(
    artifact_root: ArtifactRoot,
    squad_id: str,
) -> _ActiveSquad | None:
    state_path = artifact_root.omo_path("squad", squad_id, "state.json")
    try:
        state = SquadState.from_mapping(read_json(state_path))
    except _READ_ERRORS:
        return None
    if state.current_stage not in ACTIVE_STAGES:
        return None
    return _ActiveSquad(
        squad_id=squad_id,
        stage=state.current_stage,
        active_attempt=state.active_attempt,
        plan_artifact=state.plan_artifact,
        worktree=state.worktree,
        next_action=next_action(state.current_stage),
        paths={
            "state": str(state_path),
            "assignment": str(
                artifact_root.omo_path("squad", squad_id, "assignment.json"),
            ),
            "start_gate": str(
                artifact_root.omo_path("squad", squad_id, "start-gate.json"),
            ),
            "ledger": str(
                artifact_root.omo_path("squad", squad_id, "ledger.jsonl"),
            ),
        },
    )


def _render_directive(cwd: str, squads: tuple[_ActiveSquad, ...]) -> str:
    sections: list[str] = [_STOP_DIRECTIVE_HEADER, ""]
    for squad in squads:
        sections.extend(_squad_block(squad))
        sections.append("")
    sections.append(_stop_directive_footer(cwd))
    return "\n".join(sections).strip()


def _stop_directive_footer(cwd: str) -> str:
    return (
        "# What to do now\n"
        "1. Read the squad state and ledger above; they are the source of truth "
        "for the active attempt and recorded evidence.\n"
        f"2. Run `marshal status --root {cwd}` for the live platoon picture and "
        f"`marshal handover --root {cwd} --squad <squad>` for a full orientation "
        "packet.\n"
        "3. Advance the squad's current stage; record attempts and evidence in "
        "the ledger as you go.\n"
        "4. When the stage is verified, advance Marshal (route/complete) rather "
        "than ending the turn.\n"
        "Do not print a completion message while any squad above is still "
        "active.\n"
        "</marshal-continuation>"
    )


def _squad_block(squad: _ActiveSquad) -> list[str]:
    heading = (
        f"## Squad `{squad.squad_id}` "
        f"(stage `{squad.stage.value}`, attempt {squad.active_attempt})"
    )
    block = [heading, f"- Next action: {squad.next_action}"]
    if squad.plan_artifact:
        block.append(f"- Plan artifact: `{squad.plan_artifact}`")
    if squad.worktree:
        block.append(f"- Worktree: `{squad.worktree}` {_WORKTREE_NOTE}")
    block.append(f"- State: `{squad.paths['state']}`")
    block.append(f"- Assignment: `{squad.paths['assignment']}`")
    block.append(f"- Start gate: `{squad.paths['start_gate']}`")
    block.append(f"- Ledger: `{squad.paths['ledger']}`")
    return block


def _render_status_summary(cwd: str) -> str:
    try:
        artifact_root = ArtifactRoot.from_user_input(cwd)
        platoon = collect_platoon_status(artifact_root.root)
    except _READ_ERRORS:
        return ""
    lines = [
        "<marshal-status>",
        "Marshal is orchestrating this work (control-plane).",
    ]
    if platoon.platoon_goal:
        lines.append(f"- Platoon goal: {platoon.platoon_goal}")
    lines.extend(_status_line(status) for status in platoon.squads)
    next_ids = [status.squad_id for status in platoon.next_squads()]
    if next_ids:
        lines.append(f"- Runnable next: {', '.join(next_ids)}")
    lines.append(_status_detail_hint(str(artifact_root.root)))
    lines.append("</marshal-status>")
    return "\n".join(lines)


def _status_detail_hint(cwd: str) -> str:
    return (
        f"Use `marshal status --root {cwd}`, `marshal next --root {cwd}`, and "
        f"`marshal handover --root {cwd} --squad <squad>` for detail."
    )


def _status_line(status: SquadStatus) -> str:
    stage = "uninitialized" if status.stage is None else status.stage.value
    attempt = (
        "" if status.active_attempt is None else f" attempt {status.active_attempt}"
    )
    flags = _status_flags(status)
    flag_text = f" [{', '.join(flags)}]" if flags else ""
    return f"- {status.squad_id}: stage {stage}{attempt}{flag_text}"


def _status_flags(status: SquadStatus) -> list[str]:
    flags: list[str] = []
    if status.done:
        flags.append("done")
    if status.aborted:
        flags.append("aborted")
    if status.blocked:
        flags.append("blocked")
    if status.start_gate.fresh:
        flags.append("gated")
    if status.started:
        flags.append("dispatched")
    if status.next_to_start:
        flags.append("runnable")
    return flags


def _compact(payload: JsonObject) -> str:
    return json.dumps(payload, separators=(",", ":")) + "\n"


__all__ = [
    "CodexHookInput",
    "parse_hook_input",
    "render_stop_output",
    "render_user_prompt_submit_output",
    "transcript_has_context_pressure",
]
