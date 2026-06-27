"""Argparse command surface for `evidence check` and `handover`."""

from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING, Final, NoReturn

from marshal_cli.evidence import check_evidence
from marshal_cli.handover import build_handover
from marshal_cli.jsonio import JsonIOError
from marshal_cli.models import JsonObject, ValidationError
from marshal_cli.paths import PathSecurityError

if TYPE_CHECKING:
    from collections.abc import Sequence

_OPERATIONAL_ERRORS: Final = (JsonIOError, PathSecurityError, ValidationError)
EVIDENCE_COMMAND_HELP: Final = """commands:
  evidence check  verify active-attempt ledger evidence files exist"""


class _EvidenceNamespace(argparse.Namespace):
    root: str
    squad_id: str
    require_real_surface: bool
    strict: bool

    def __init__(self) -> None:
        super().__init__()
        self.root = ""
        self.squad_id = ""
        self.require_real_surface = False
        self.strict = False


class _HandoverNamespace(argparse.Namespace):
    root: str
    squad_id: str

    def __init__(self) -> None:
        super().__init__()
        self.root = ""
        self.squad_id = ""


def run_evidence_command(arguments: Sequence[str]) -> int:
    """Run the `marshal evidence` command group."""
    parser = _build_evidence_group_parser()
    if not arguments:
        parser.error("unknown command: <missing>")
    if arguments[0].startswith("-"):
        _ = parser.parse_args(arguments)
        parser.print_help()
        return 0
    command = arguments[0]
    if command == "check":
        return _run_evidence_check(arguments[1:])
    return _parser_error(parser, f"unknown command: {command}")


def run_handover_command(arguments: Sequence[str]) -> int:
    """Run the `marshal handover` command."""
    parser = _build_handover_parser()
    parsed = _HandoverNamespace()
    _ = parser.parse_args(arguments, namespace=parsed)
    try:
        result = build_handover(parsed.root, parsed.squad_id)
    except _OPERATIONAL_ERRORS as error:
        parser.error(str(error))
    _write_result(result.to_jsonable())
    return 0


def _run_evidence_check(arguments: Sequence[str]) -> int:
    parser = _build_evidence_check_parser()
    parsed = _EvidenceNamespace()
    _ = parser.parse_args(arguments, namespace=parsed)
    try:
        report = check_evidence(parsed.root, parsed.squad_id)
    except _OPERATIONAL_ERRORS as error:
        parser.error(str(error))
    _write_result(report.to_jsonable())
    ok = report.ok(require_real_surface=parsed.require_real_surface)
    if parsed.strict and not ok:
        return 1
    return 0


def _build_evidence_group_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="marshal evidence",
        description="Inspect recorded squad evidence.",
        epilog=EVIDENCE_COMMAND_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def _build_evidence_check_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="marshal evidence check",
        description="Verify active-attempt ledger evidence files exist.",
    )
    _ = parser.add_argument("--root", required=True)
    _ = parser.add_argument("--squad", dest="squad_id", required=True)
    _ = parser.add_argument(
        "--require-real-surface",
        dest="require_real_surface",
        action="store_true",
    )
    _ = parser.add_argument("--strict", action="store_true")
    return parser


def _build_handover_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="marshal handover",
        description="Emit a handover packet for the next agent.",
    )
    _ = parser.add_argument("--root", required=True)
    _ = parser.add_argument("--squad", dest="squad_id", required=True)
    return parser


def _write_result(result: JsonObject) -> None:
    _ = sys.stdout.write(json.dumps(result, indent=2, sort_keys=True))
    _ = sys.stdout.write("\n")


def _parser_error(parser: argparse.ArgumentParser, message: str) -> NoReturn:
    parser.error(message)


__all__ = ["run_evidence_command", "run_handover_command"]
