"""Argparse command surface for `abort` and `complete`."""

from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING, Final

from marshal_cli.jsonio import JsonIOError
from marshal_cli.lifecycle import abort_platoon, abort_squad, complete_squad
from marshal_cli.models import JsonObject, ValidationError
from marshal_cli.paths import PathSecurityError

if TYPE_CHECKING:
    from collections.abc import Sequence

_OPERATIONAL_ERRORS: Final = (JsonIOError, PathSecurityError, ValidationError)


class _AbortNamespace(argparse.Namespace):
    root: str
    squad_id: str
    abort_all: bool
    reason: str

    def __init__(self) -> None:
        super().__init__()
        self.root = ""
        self.squad_id = ""
        self.abort_all = False
        self.reason = ""


class _CompleteNamespace(argparse.Namespace):
    root: str
    squad_id: str
    evidence: list[str]
    detail: str

    def __init__(self) -> None:
        super().__init__()
        self.root = ""
        self.squad_id = ""
        self.evidence = []
        self.detail = ""


def run_abort_command(arguments: Sequence[str]) -> int:
    """Run the `marshal abort` command."""
    parser = _build_abort_parser()
    parsed = _AbortNamespace()
    _ = parser.parse_args(arguments, namespace=parsed)
    if parsed.abort_all == bool(parsed.squad_id):
        parser.error("provide exactly one of --squad or --all")
    try:
        result = (
            abort_platoon(parsed.root, parsed.reason)
            if parsed.abort_all
            else abort_squad(parsed.root, parsed.squad_id, parsed.reason)
        )
    except _OPERATIONAL_ERRORS as error:
        parser.error(str(error))
    _write_result(result.to_jsonable())
    return 0


def run_complete_command(arguments: Sequence[str]) -> int:
    """Run the `marshal complete` command."""
    parser = _build_complete_parser()
    parsed = _CompleteNamespace()
    _ = parser.parse_args(arguments, namespace=parsed)
    try:
        result = complete_squad(
            parsed.root,
            parsed.squad_id,
            tuple(parsed.evidence),
            parsed.detail,
        )
    except _OPERATIONAL_ERRORS as error:
        parser.error(str(error))
    _write_result(result.to_jsonable())
    return 0


def _build_abort_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="marshal abort",
        description="Abort one squad or every active squad and block delegation.",
    )
    _ = parser.add_argument("--root", required=True)
    _ = parser.add_argument("--squad", dest="squad_id", default="")
    _ = parser.add_argument("--all", dest="abort_all", action="store_true")
    _ = parser.add_argument("--reason", required=True)
    return parser


def _build_complete_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="marshal complete",
        description="Record an evidence-backed done claim for a squad.",
    )
    _ = parser.add_argument("--root", required=True)
    _ = parser.add_argument("--squad", dest="squad_id", required=True)
    _ = parser.add_argument("--evidence", action="append", default=[], required=True)
    _ = parser.add_argument("--detail", required=True)
    return parser


def _write_result(result: JsonObject) -> None:
    _ = sys.stdout.write(json.dumps(result, indent=2, sort_keys=True))
    _ = sys.stdout.write("\n")


__all__ = ["run_abort_command", "run_complete_command"]
