"""Argparse command surface for start-gate validation."""

from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING

from marshal_cli.models import JsonObject, StartGateSource, ValidationError
from marshal_cli.paths import PathSecurityError
from marshal_cli.start_gate import StartGateRequest, run_start_gate

if TYPE_CHECKING:
    from collections.abc import Sequence


class _StartGateNamespace(argparse.Namespace):
    root: str
    squad_id: str
    source: str
    example: str
    plan_artifact: str | None

    def __init__(self) -> None:
        super().__init__()
        self.root = ""
        self.squad_id = ""
        self.source = ""
        self.example = ""
        self.plan_artifact = None


def run_start_gate_command(arguments: Sequence[str]) -> int:
    """Run the `marshal start-gate` command."""
    parser = _build_start_gate_parser()
    parsed = _StartGateNamespace()
    _ = parser.parse_args(arguments, namespace=parsed)
    try:
        result = run_start_gate(
            StartGateRequest(
                root=parsed.root,
                squad_id=parsed.squad_id,
                source=StartGateSource(parsed.source),
                applied_example=parsed.example,
                plan_artifact=parsed.plan_artifact,
            ),
        )
    except (PathSecurityError, ValidationError) as error:
        parser.error(str(error))
    _write_result(result.to_jsonable())
    return 0


def _build_start_gate_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="marshal start-gate",
        description="Validate handover-lite inputs before squad work starts.",
    )
    _ = parser.add_argument("--root", required=True)
    _ = parser.add_argument("--squad", dest="squad_id", required=True)
    _ = parser.add_argument(
        "--source",
        required=True,
        choices=[source.value for source in StartGateSource],
    )
    _ = parser.add_argument("--example", required=True)
    _ = parser.add_argument("--plan", dest="plan_artifact")
    return parser


def _write_result(result: JsonObject) -> None:
    _ = sys.stdout.write(json.dumps(result, indent=2, sort_keys=True))
    _ = sys.stdout.write("\n")


__all__ = ["run_start_gate_command"]
