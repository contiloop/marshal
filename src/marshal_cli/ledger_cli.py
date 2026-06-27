"""Argparse command surface for append-only squad attempt ledgers."""

from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING, Final, NoReturn

from marshal_cli.jsonio import JsonIOError
from marshal_cli.ledger_core import (
    LedgerAppendRequest,
    append_ledger_entry,
    latest_attempt_events,
)
from marshal_cli.models import JsonObject, ValidationError
from marshal_cli.paths import PathSecurityError

if TYPE_CHECKING:
    from collections.abc import Sequence

LEDGER_COMMAND_HELP: Final = """commands:
  ledger append  append one event to a squad attempt ledger
  ledger latest  print only events from the active state attempt"""


class _AppendNamespace(argparse.Namespace):
    root: str
    squad_id: str
    event: str
    attempt: int
    stage: str
    task: str
    detail: str
    findings: list[str]
    evidence: list[str]

    def __init__(self) -> None:
        super().__init__()
        self.root = ""
        self.squad_id = ""
        self.event = ""
        self.attempt = 0
        self.stage = ""
        self.task = ""
        self.detail = ""
        self.findings = []
        self.evidence = []


class _LatestNamespace(argparse.Namespace):
    root: str
    squad_id: str

    def __init__(self) -> None:
        super().__init__()
        self.root = ""
        self.squad_id = ""


def run_ledger_command(arguments: Sequence[str]) -> int:
    """Run the `marshal ledger` command group."""
    parser = _build_ledger_parser()
    if not arguments:
        parser.error("unknown command: <missing>")
    if arguments[0].startswith("-"):
        _ = parser.parse_args(arguments)
        parser.print_help()
        return 0

    command = arguments[0]
    if command == "append":
        return _run_append(arguments[1:])
    if command == "latest":
        return _run_latest(arguments[1:])
    return _parser_error(parser, f"unknown command: {command}")


def _build_ledger_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="marshal ledger",
        description="Inspect and append squad attempt ledger events.",
        epilog=LEDGER_COMMAND_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def _run_append(arguments: Sequence[str]) -> int:
    parser = _build_append_parser()
    parsed = _AppendNamespace()
    _ = parser.parse_args(arguments, namespace=parsed)
    try:
        result = append_ledger_entry(parsed.root, _append_request(parsed))
    except (JsonIOError, PathSecurityError, ValidationError) as error:
        parser.error(str(error))
    _write_result(result.to_jsonable())
    return 0


def _run_latest(arguments: Sequence[str]) -> int:
    parser = _build_latest_parser()
    parsed = _LatestNamespace()
    _ = parser.parse_args(arguments, namespace=parsed)
    try:
        result = latest_attempt_events(parsed.root, parsed.squad_id)
    except (JsonIOError, PathSecurityError, ValidationError) as error:
        parser.error(str(error))
    _write_text(result.to_json_text())
    return 0


def _append_request(parsed: _AppendNamespace) -> LedgerAppendRequest:
    return LedgerAppendRequest(
        squad_id=parsed.squad_id,
        event=parsed.event,
        attempt=parsed.attempt,
        stage=parsed.stage,
        task=parsed.task,
        detail=parsed.detail,
        findings=tuple(parsed.findings),
        evidence=tuple(parsed.evidence),
    )


def _build_append_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="marshal ledger append",
        description="Append one event to a squad attempt ledger.",
    )
    _ = parser.add_argument("--root", required=True)
    _ = parser.add_argument("--squad", dest="squad_id", required=True)
    _ = parser.add_argument("--event", required=True)
    _ = parser.add_argument("--attempt", type=int, required=True)
    _ = parser.add_argument("--stage", required=True)
    _ = parser.add_argument("--task", required=True)
    _ = parser.add_argument("--detail", required=True)
    _ = parser.add_argument("--finding", action="append", dest="findings", default=[])
    _ = parser.add_argument("--evidence", action="append", default=[])
    return parser


def _build_latest_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="marshal ledger latest",
        description="Print only events from the active state attempt.",
    )
    _ = parser.add_argument("--root", required=True)
    _ = parser.add_argument("--squad", dest="squad_id", required=True)
    return parser


def _write_result(result: JsonObject) -> None:
    _ = sys.stdout.write(json.dumps(result, indent=2, sort_keys=True))
    _ = sys.stdout.write("\n")


def _write_text(result: str) -> None:
    _ = sys.stdout.write(result)
    _ = sys.stdout.write("\n")


def _parser_error(parser: argparse.ArgumentParser, message: str) -> NoReturn:
    parser.error(message)


__all__ = ["run_ledger_command"]
