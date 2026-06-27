"""Argparse glue for the `marshal hook` Codex entry points.

Each subcommand reads a Codex hook payload from stdin, runs the pure renderer in
`hook_core`, and writes compact single-line JSON to stdout (or nothing). The
governing rule for a hook is: malformed or absent input yields empty output and
**exit 0**, so a hook can never crash or stall Codex.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

from marshal_cli.hook_core import (
    parse_hook_input,
    render_stop_output,
    render_user_prompt_submit_output,
)
from marshal_cli.jsonio import JsonIOError, parse_json_object

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from marshal_cli.hook_core import CodexHookInput

PROGRAM_NAME: Final = "marshal hook"
_STDIN_SOURCE: Final = Path("<stdin>")
HOOK_COMMAND_HELP: Final = """commands:
  user-prompt-submit  inject live platoon/squad status as additional context
  stop                continue an active squad under Marshal (block to continue)
  subagent-stop       same continuation check after a subagent finishes"""


def run_hook_command(arguments: Sequence[str]) -> int:
    """Dispatch a `marshal hook <event>` subcommand."""
    parser = _build_hook_parser()
    if not arguments:
        parser.error("unknown command: <missing>")
    if arguments[0].startswith("-"):
        _ = parser.parse_args(arguments)
        parser.print_help()
        return 0

    command = arguments[0]
    handler = _HOOK_COMMANDS.get(command)
    if handler is None:
        parser.error(f"unknown command: {command}")
    return handler(arguments[1:])


def _run_user_prompt_submit(arguments: Sequence[str]) -> int:
    _parse_event_args(arguments, "user-prompt-submit")
    _emit(_read_and_render(render_user_prompt_submit_output))
    return 0


def _run_stop(arguments: Sequence[str]) -> int:
    _parse_event_args(arguments, "stop")
    _emit(_read_and_render(render_stop_output))
    return 0


def _run_subagent_stop(arguments: Sequence[str]) -> int:
    _parse_event_args(arguments, "subagent-stop")
    _emit(_read_and_render(render_stop_output))
    return 0


def _read_and_render(render: Callable[[CodexHookInput], str]) -> str:
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return ""
    if not raw.strip():
        return ""
    try:
        payload = parse_json_object(raw, _STDIN_SOURCE)
    except JsonIOError:
        return ""
    parsed = parse_hook_input(payload)
    if parsed is None:
        return ""
    try:
        return render(parsed)
    except Exception:  # noqa: BLE001 - a hook must never crash Codex; stay quiet.
        return ""


def _emit(text: str) -> None:
    if text:
        _ = sys.stdout.write(text)


def _parse_event_args(arguments: Sequence[str], event: str) -> None:
    parser = argparse.ArgumentParser(
        prog=f"{PROGRAM_NAME} {event}",
        description=f"Run the Marshal {event} Codex hook (reads JSON on stdin).",
    )
    _ = parser.parse_args(arguments)


def _build_hook_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog=PROGRAM_NAME,
        description="Codex hook entry points owned by the Marshal control-plane.",
        epilog=HOOK_COMMAND_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


_HOOK_COMMANDS: Final[dict[str, Callable[[Sequence[str]], int]]] = {
    "user-prompt-submit": _run_user_prompt_submit,
    "stop": _run_stop,
    "subagent-stop": _run_subagent_stop,
}


__all__ = ["run_hook_command"]
