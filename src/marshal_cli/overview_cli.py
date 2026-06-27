"""Argparse command surface for `status` and `next`."""

from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING, Final

from marshal_cli.jsonio import JsonIOError
from marshal_cli.models import JsonObject, ValidationError
from marshal_cli.overview import collect_platoon_status
from marshal_cli.paths import PathSecurityError

if TYPE_CHECKING:
    from collections.abc import Sequence

_OPERATIONAL_ERRORS: Final = (JsonIOError, PathSecurityError, ValidationError)


class _RootNamespace(argparse.Namespace):
    root: str

    def __init__(self) -> None:
        super().__init__()
        self.root = ""


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


def _root_parser(prog: str, description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=description)
    _ = parser.add_argument("--root", required=True)
    return parser


def _write_result(result: JsonObject) -> None:
    _ = sys.stdout.write(json.dumps(result, indent=2, sort_keys=True))
    _ = sys.stdout.write("\n")


__all__ = ["run_next_command", "run_status_command"]
