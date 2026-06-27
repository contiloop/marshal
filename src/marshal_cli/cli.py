"""Argparse command surface for Marshal."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, NoReturn

if TYPE_CHECKING:
    from collections.abc import Sequence

from marshal_cli import __version__
from marshal_cli.delegate import run_delegate_command
from marshal_cli.init_cli import run_init_command
from marshal_cli.ledger import run_ledger_command
from marshal_cli.models import JsonObject, Report, ValidationError
from marshal_cli.squad_state import initialize_squad_state, route_squad_report
from marshal_cli.start_gate_cli import run_start_gate_command

PROGRAM_NAME: Final = "marshal"
COMMAND_HELP: Final = """commands:
  init                 create platoon checklist and squad assignment packets
  state init           create a squad state artifact
  start-gate           record a handover-lite/start gate pass
  route                route a stage report through the Squad Leader
  ledger append        append one attempt ledger event
  ledger latest        print active-attempt ledger events
  delegate-start-work  emit the start-work delegation payload"""
STATE_COMMAND_HELP: Final = """commands:
  state init  create a squad state artifact from an assignment packet"""


@dataclass(frozen=True, slots=True)
class _RouteArguments:
    root: str
    squad_id: str
    report: Report


class _StateInitNamespace(argparse.Namespace):
    root: str
    squad_id: str
    plan_artifact: str | None

    def __init__(self) -> None:
        super().__init__()
        self.root = ""
        self.squad_id = ""
        self.plan_artifact = None


class _RouteNamespace(argparse.Namespace):
    root: str
    squad_id: str
    source: str
    report_type: str
    detail: str
    findings: list[str]
    evidence: list[str]

    def __init__(self) -> None:
        super().__init__()
        self.root = ""
        self.squad_id = ""
        self.source = ""
        self.report_type = ""
        self.detail = ""
        self.findings = []
        self.evidence = []


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog=PROGRAM_NAME,
        description="Standalone platoon and squad orchestration CLI prototype.",
        epilog=COMMAND_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _ = parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def _build_state_init_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"{PROGRAM_NAME} state init",
        description="Create a squad state artifact from an assignment packet.",
    )
    _ = parser.add_argument("--root", required=True)
    _ = parser.add_argument("--squad", dest="squad_id", required=True)
    _ = parser.add_argument("--plan", dest="plan_artifact")
    return parser


def _build_route_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"{PROGRAM_NAME} route",
        description="Route a stage report through the Squad Leader state machine.",
    )
    _ = parser.add_argument("--root", required=True)
    _ = parser.add_argument("--squad", dest="squad_id", required=True)
    _ = parser.add_argument("--source", required=True)
    _ = parser.add_argument("--type", dest="report_type", required=True)
    _ = parser.add_argument("--detail", required=True)
    _ = parser.add_argument("--finding", action="append", dest="findings", default=[])
    _ = parser.add_argument("--evidence", action="append", default=[])
    return parser


def run(arguments: Sequence[str]) -> int:
    """Run Marshal with explicit arguments."""
    if not arguments:
        parser = build_parser()
        parser.print_help()
        return 0
    if arguments[0].startswith("-"):
        parser = build_parser()
        _ = parser.parse_args(arguments)
        parser.print_help()
        return 0

    command = arguments[0]
    remaining = arguments[1:]
    if command == "init":
        result = run_init_command(remaining)
    elif command == "state":
        result = _run_state(remaining)
    elif command == "route":
        result = _run_route(remaining)
    elif command == "ledger":
        result = run_ledger_command(remaining)
    elif command == "start-gate":
        result = run_start_gate_command(remaining)
    elif command == "delegate-start-work":
        result = run_delegate_command(remaining)
    else:
        parser = build_parser()
        result = _parser_error(parser, f"unknown command: {command}")
    return result


def _run_state(arguments: Sequence[str]) -> int:
    parser = _build_state_parser()
    if not arguments:
        parser.error("unknown command: <missing>")
    if arguments[0].startswith("-"):
        _ = parser.parse_args(arguments)
        parser.print_help()
        return 0

    command = arguments[0]
    if command == "init":
        return _run_state_init(arguments[1:])
    return _parser_error(parser, f"unknown command: {command}")


def _build_state_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog=f"{PROGRAM_NAME} state",
        description="Manage squad state artifacts.",
        epilog=STATE_COMMAND_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def _run_state_init(arguments: Sequence[str]) -> int:
    parser = _build_state_init_parser()
    parsed = _StateInitNamespace()
    _ = parser.parse_args(arguments, namespace=parsed)
    try:
        result = initialize_squad_state(
            parsed.root,
            parsed.squad_id,
            parsed.plan_artifact,
        )
    except ValidationError as error:
        parser.error(str(error))
    _write_result(result.to_jsonable())
    return 0


def _run_route(arguments: Sequence[str]) -> int:
    parser = _build_route_parser()
    parsed = _RouteNamespace()
    _ = parser.parse_args(arguments, namespace=parsed)
    try:
        route_arguments = _route_arguments(parsed)
        result = route_squad_report(
            route_arguments.root,
            route_arguments.squad_id,
            route_arguments.report,
        )
    except ValidationError as error:
        parser.error(str(error))
    _write_result(result.to_jsonable())
    return 0


def _route_arguments(parsed: _RouteNamespace) -> _RouteArguments:
    report = Report.from_mapping(
        {
            "source": parsed.source,
            "type": parsed.report_type,
            "detail": parsed.detail,
            "findings": list(parsed.findings),
            "evidence": list(parsed.evidence),
        },
    )
    return _RouteArguments(root=parsed.root, squad_id=parsed.squad_id, report=report)


def _write_result(result: JsonObject) -> None:
    _ = sys.stdout.write(json.dumps(result, indent=2, sort_keys=True))
    _ = sys.stdout.write("\n")


def _parser_error(parser: argparse.ArgumentParser, message: str) -> NoReturn:
    parser.error(message)


def main(arguments: Sequence[str] | None = None) -> int:
    """Run Marshal from the console script entry point."""
    selected_arguments = sys.argv[1:] if arguments is None else arguments
    return run(selected_arguments)
