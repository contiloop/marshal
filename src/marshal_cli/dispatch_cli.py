"""Argparse command surface for `run-start-work` and `dispatch`."""

from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING, Final

from marshal_cli.dispatch import StartWorkRequest, dispatch_squad, execute_start_work
from marshal_cli.jsonio import JsonIOError
from marshal_cli.models import JsonObject, ValidationError
from marshal_cli.paths import PathSecurityError

if TYPE_CHECKING:
    from collections.abc import Sequence

_OPERATIONAL_ERRORS: Final = (JsonIOError, PathSecurityError, ValidationError)


class _StartWorkNamespace(argparse.Namespace):
    root: str
    squad_id: str
    runner: str | None
    dry_run: bool
    timeout: int | None

    def __init__(self) -> None:
        super().__init__()
        self.root = ""
        self.squad_id = ""
        self.runner = None
        self.dry_run = False
        self.timeout = None


def run_run_start_work_command(arguments: Sequence[str]) -> int:
    """Run the `marshal run-start-work` command (adapter mode)."""
    parser = _start_work_parser(
        "marshal run-start-work",
        "Invoke the external start-work runner for a gated squad.",
        squad_required=True,
    )
    parsed = _StartWorkNamespace()
    _ = parser.parse_args(arguments, namespace=parsed)
    try:
        result = execute_start_work(_start_work_request(parsed))
    except _OPERATIONAL_ERRORS as error:
        parser.error(str(error))
    _write_result(result.to_jsonable())
    return result.exit_code()


def run_dispatch_command(arguments: Sequence[str]) -> int:
    """Run the `marshal dispatch` command (dependency-gated start-work)."""
    parser = _start_work_parser(
        "marshal dispatch",
        "Dispatch a runnable squad, auto-selecting one when --squad is omitted.",
        squad_required=False,
    )
    parsed = _StartWorkNamespace()
    _ = parser.parse_args(arguments, namespace=parsed)
    try:
        result = dispatch_squad(_start_work_request(parsed))
    except _OPERATIONAL_ERRORS as error:
        parser.error(str(error))
    _write_result(result.to_jsonable())
    return result.exit_code()


def _start_work_request(parsed: _StartWorkNamespace) -> StartWorkRequest:
    return StartWorkRequest(
        root=parsed.root,
        squad_id=parsed.squad_id,
        runner=parsed.runner,
        dry_run=parsed.dry_run,
        timeout=parsed.timeout,
    )


def _start_work_parser(
    prog: str,
    description: str,
    *,
    squad_required: bool,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=description)
    _ = parser.add_argument("--root", required=True)
    _ = parser.add_argument("--squad", dest="squad_id", required=squad_required)
    _ = parser.add_argument(
        "--runner",
        help="External start-work command (falls back to MARSHAL_START_WORK_RUNNER).",
    )
    _ = parser.add_argument("--dry-run", dest="dry_run", action="store_true")
    _ = parser.add_argument("--timeout", type=int)
    return parser


def _write_result(result: JsonObject) -> None:
    _ = sys.stdout.write(json.dumps(result, indent=2, sort_keys=True))
    _ = sys.stdout.write("\n")


__all__ = ["run_dispatch_command", "run_run_start_work_command"]
