"""Argparse command surface for Marshal operational commands."""

from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING, Final, NoReturn

from marshal_cli.dispatch import StartWorkRequest, dispatch_squad, execute_start_work
from marshal_cli.evidence import check_evidence
from marshal_cli.handover import build_handover
from marshal_cli.jsonio import JsonIOError
from marshal_cli.lifecycle import abort_platoon, abort_squad, complete_squad
from marshal_cli.models import JsonObject, ValidationError
from marshal_cli.overview import collect_platoon_status
from marshal_cli.paths import PathSecurityError

if TYPE_CHECKING:
    from collections.abc import Sequence

_OPERATIONAL_ERRORS: Final = (JsonIOError, PathSecurityError, ValidationError)
EVIDENCE_COMMAND_HELP: Final = """commands:
  evidence check  verify active-attempt ledger evidence files exist"""


class _RootNamespace(argparse.Namespace):
    root: str

    def __init__(self) -> None:
        super().__init__()
        self.root = ""


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


def run_status_command(arguments: Sequence[str]) -> int:
    """Run the `marshal status` command."""
    parser = _root_parser("marshal status", "Show live platoon and squad status.")
    parsed = _RootNamespace()
    _ = parser.parse_args(arguments, namespace=parsed)
    try:
        result = collect_platoon_status(parsed.root)
    except _OPERATIONAL_ERRORS as error:
        parser.error(str(error))
    _write_result(result.to_jsonable())
    return 0


def run_next_command(arguments: Sequence[str]) -> int:
    """Run the `marshal next` command."""
    parser = _root_parser(
        "marshal next",
        "Print the next squads whose dependencies are satisfied.",
    )
    parsed = _RootNamespace()
    _ = parser.parse_args(arguments, namespace=parsed)
    try:
        status = collect_platoon_status(parsed.root)
    except _OPERATIONAL_ERRORS as error:
        parser.error(str(error))
    nxt = status.next_squads()
    _write_result(
        {
            "next_squads": [squad.squad_id for squad in nxt],
            "squads": [squad.to_jsonable() for squad in nxt],
        },
    )
    return 0


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


def _start_work_request(parsed: _StartWorkNamespace) -> StartWorkRequest:
    return StartWorkRequest(
        root=parsed.root,
        squad_id=parsed.squad_id,
        runner=parsed.runner,
        dry_run=parsed.dry_run,
        timeout=parsed.timeout,
    )


def _root_parser(prog: str, description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=description)
    _ = parser.add_argument("--root", required=True)
    return parser


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


__all__ = [
    "run_abort_command",
    "run_complete_command",
    "run_dispatch_command",
    "run_evidence_command",
    "run_handover_command",
    "run_next_command",
    "run_run_start_work_command",
    "run_status_command",
]
