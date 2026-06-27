"""Adapter-mode start-work execution and dependency-gated dispatch.

`delegate-start-work` only emits a payload (manual mode). `run-start-work`
takes the same payload and hands it to an external start-work runner over a
subprocess boundary (adapter mode); Marshal never imports or mutates OMO
start-work internals. `dispatch` adds dependency-readiness checks before
calling the same execution path.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from marshal_cli.delegate import build_delegation_payload
from marshal_cli.jsonio import JsonIOError, read_json
from marshal_cli.ledger_core import LedgerAppendRequest, append_ledger_entry
from marshal_cli.models import (
    DelegationPayload,
    JsonObject,
    SquadState,
    ValidationError,
    validate_squad_id,
)
from marshal_cli.overview import PlatoonStatus, SquadStatus, collect_platoon_status
from marshal_cli.paths import ArtifactRoot

if TYPE_CHECKING:
    from pathlib import Path

DISPATCH_CONTEXT: Final = "dispatch"
RUNNER_ENV_VAR: Final = "MARSHAL_START_WORK_RUNNER"
DEFAULT_TIMEOUT_SECONDS: Final = 1800


@dataclass(frozen=True, slots=True)
class StartWorkRequest:
    """Inputs needed to run or preview one start-work invocation."""

    root: str | Path
    squad_id: str
    runner: str | None
    dry_run: bool
    timeout: int | None


@dataclass(frozen=True, slots=True)
class StartWorkResult:
    """Outcome of a run-start-work or dispatch invocation."""

    squad_id: str
    mode: str
    runner: tuple[str, ...]
    command: str
    active_attempt: int
    dry_run: bool
    returncode: int | None
    runner_stdout: str
    runner_stderr: str
    dispatched: bool
    payload: DelegationPayload

    def to_jsonable(self) -> JsonObject:
        """Return the start-work result as JSON-compatible data."""
        return {
            "squad_id": self.squad_id,
            "mode": self.mode,
            "runner": list(self.runner),
            "command": self.command,
            "active_attempt": self.active_attempt,
            "dry_run": self.dry_run,
            "returncode": self.returncode,
            "runner_stdout": self.runner_stdout,
            "runner_stderr": self.runner_stderr,
            "dispatched": self.dispatched,
            "delegation": self.payload.to_jsonable(),
        }

    def exit_code(self) -> int:
        """Return 0 on success, 1 when the runner reported failure."""
        return 0 if self.dispatched else 1


def execute_start_work(request: StartWorkRequest) -> StartWorkResult:
    """Run (or preview) the configured external start-work runner for a squad."""
    payload = build_delegation_payload(request.root, request.squad_id)
    runner_argv = _resolve_runner(request.runner)
    artifact_root = ArtifactRoot.from_user_input(request.root)
    squad_id = validate_squad_id(request.squad_id)
    state = _read_state(artifact_root, squad_id)

    if request.dry_run:
        return StartWorkResult(
            squad_id=squad_id,
            mode="dry-run",
            runner=runner_argv,
            command=payload.command,
            active_attempt=payload.active_attempt,
            dry_run=True,
            returncode=None,
            runner_stdout="",
            runner_stderr="",
            dispatched=False,
            payload=payload,
        )

    completed = _run_runner(runner_argv, payload, artifact_root, request.timeout)
    dispatched = completed.returncode == 0
    _record_dispatch(artifact_root, squad_id, state, runner_argv, completed.returncode)
    return StartWorkResult(
        squad_id=squad_id,
        mode="adapter",
        runner=runner_argv,
        command=payload.command,
        active_attempt=payload.active_attempt,
        dry_run=False,
        returncode=completed.returncode,
        runner_stdout=completed.stdout,
        runner_stderr=completed.stderr,
        dispatched=dispatched,
        payload=payload,
    )


def dispatch_squad(request: StartWorkRequest) -> StartWorkResult:
    """Select or validate a runnable squad, then run start-work for it."""
    status = collect_platoon_status(request.root)
    target = _dispatch_target(status, request.squad_id)
    _ensure_dispatchable(target)
    resolved = StartWorkRequest(
        root=request.root,
        squad_id=target.squad_id,
        runner=request.runner,
        dry_run=request.dry_run,
        timeout=request.timeout,
    )
    return execute_start_work(resolved)


def _dispatch_target(status: PlatoonStatus, squad_id: str) -> SquadStatus:
    if squad_id:
        explicit = status.squad(squad_id)
        if explicit is None:
            reason = "unknown squad in platoon checklist"
            raise ValidationError(DISPATCH_CONTEXT, "squad", squad_id, reason)
        return explicit
    candidates = status.next_squads()
    if not candidates:
        reason = "no runnable squad; dependencies unsatisfied or all squads started"
        raise ValidationError(DISPATCH_CONTEXT, "squad", "<none>", reason)
    return candidates[0]


def _ensure_dispatchable(target: SquadStatus) -> None:
    if target.aborted:
        reason = "squad is aborted"
        raise ValidationError(DISPATCH_CONTEXT, "squad", target.squad_id, reason)
    if target.done:
        reason = "squad is already done"
        raise ValidationError(DISPATCH_CONTEXT, "squad", target.squad_id, reason)
    if not target.dependencies_satisfied:
        reason = f"dependencies not done: {','.join(target.depends_on)}"
        raise ValidationError(DISPATCH_CONTEXT, "squad", target.squad_id, reason)
    if not target.start_gate.fresh:
        reason = "no fresh start gate; run marshal start-gate for the current stage"
        raise ValidationError(DISPATCH_CONTEXT, "squad", target.squad_id, reason)


def _resolve_runner(runner: str | None) -> tuple[str, ...]:
    source = runner or os.environ.get(RUNNER_ENV_VAR)
    if not source:
        reason = (
            f"no start-work runner; pass --runner or set {RUNNER_ENV_VAR} "
            "(use delegate-start-work for manual mode)"
        )
        raise ValidationError(DISPATCH_CONTEXT, "runner", "<missing>", reason)
    argv = tuple(shlex.split(source))
    if not argv:
        reason = "runner command is empty"
        raise ValidationError(DISPATCH_CONTEXT, "runner", source, reason)
    return argv


def _run_runner(
    runner_argv: tuple[str, ...],
    payload: DelegationPayload,
    artifact_root: ArtifactRoot,
    timeout: int | None,
) -> subprocess.CompletedProcess[str]:
    encoded = json.dumps(payload.to_jsonable(), sort_keys=True)
    try:
        return subprocess.run(  # noqa: S603 - runner argv is operator-provided by design
            list(runner_argv),
            input=encoded,
            capture_output=True,
            text=True,
            cwd=str(artifact_root.root),
            env=_runner_env(payload, artifact_root),
            timeout=timeout if timeout is not None else DEFAULT_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as error:
        reason = "start-work runner executable was not found"
        argv0 = runner_argv[0]
        raise ValidationError(DISPATCH_CONTEXT, "runner", argv0, reason) from error
    except subprocess.TimeoutExpired as error:
        reason = "start-work runner timed out"
        argv0 = runner_argv[0]
        raise ValidationError(DISPATCH_CONTEXT, "runner", argv0, reason) from error


def _runner_env(
    payload: DelegationPayload,
    artifact_root: ArtifactRoot,
) -> dict[str, str]:
    env = dict(os.environ)
    env["MARSHAL_ROOT"] = str(artifact_root.root)
    env["MARSHAL_SQUAD"] = payload.squad_id
    env["MARSHAL_PLAN"] = payload.plan
    env["MARSHAL_STATE"] = payload.state
    env["MARSHAL_LEDGER"] = payload.ledger
    env["MARSHAL_ASSIGNMENT"] = payload.assignment
    env["MARSHAL_COMMAND"] = payload.command
    return env


def _record_dispatch(
    artifact_root: ArtifactRoot,
    squad_id: str,
    state: SquadState,
    runner_argv: tuple[str, ...],
    returncode: int,
) -> None:
    runner_display = " ".join(runner_argv)
    request = LedgerAppendRequest(
        squad_id=squad_id,
        event="dispatched",
        attempt=state.active_attempt,
        stage=state.current_stage.value,
        task="run-start-work",
        detail=f"runner exited {returncode}",
        findings=(runner_display,),
        evidence=(),
    )
    _ = append_ledger_entry(artifact_root.root, request)


def _read_state(artifact_root: ArtifactRoot, squad_id: str) -> SquadState:
    state_path = artifact_root.omo_path("squad", squad_id, "state.json")
    try:
        raw = read_json(state_path)
    except JsonIOError as error:
        path = str(state_path)
        raise ValidationError(DISPATCH_CONTEXT, "state", path, str(error)) from error
    return SquadState.from_mapping(raw)


__all__ = [
    "StartWorkRequest",
    "StartWorkResult",
    "dispatch_squad",
    "execute_start_work",
]
