"""Argparse command surface for platoon assignment initialization."""

from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING

from marshal_cli.models import JsonObject, ValidationError
from marshal_cli.paths import PathSecurityError
from marshal_cli.platoon import create_assignment_packets

if TYPE_CHECKING:
    from collections.abc import Sequence


class _InitNamespace(argparse.Namespace):
    root: str
    goal: str
    scope_values: list[str]

    def __init__(self) -> None:
        super().__init__()
        self.root = ""
        self.goal = ""
        self.scope_values = []


def run_init_command(arguments: Sequence[str]) -> int:
    """Run the `marshal init` command."""
    parser = _build_init_parser()
    parsed = _InitNamespace()
    _ = parser.parse_args(arguments, namespace=parsed)
    try:
        result = create_assignment_packets(
            root=parsed.root,
            platoon_goal=parsed.goal,
            scope_specs=tuple(parsed.scope_values),
        )
    except (PathSecurityError, ValidationError) as error:
        parser.error(str(error))
    _write_result(result.to_jsonable())
    return 0


def _build_init_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="marshal init",
        description="Create platoon checklist and squad assignment packets.",
    )
    _ = parser.add_argument("--root", required=True)
    _ = parser.add_argument("--goal", required=True)
    _ = parser.add_argument(
        "--scope",
        action="append",
        dest="scope_values",
        metavar="<squad-id>|<goal>|<depends_csv_or_->",
        required=True,
        help="Squad assignment format: <squad-id>|<goal>|<depends_csv_or_->.",
    )
    return parser


def _write_result(result: JsonObject) -> None:
    _ = sys.stdout.write(json.dumps(result, indent=2, sort_keys=True))
    _ = sys.stdout.write("\n")


__all__ = ["run_init_command"]
