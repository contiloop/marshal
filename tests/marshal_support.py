"""Shared CLI helpers for Marshal operational command tests."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from marshal_cli.cli import main
from marshal_cli.jsonio import parse_json_object

if TYPE_CHECKING:
    from collections.abc import Sequence

    from marshal_cli.models import JsonObject, JsonValue

CLI_SOURCE = Path("<cli>")
RUNNER_SOURCE = """\
import json
import os
import sys

payload = json.load(sys.stdin)
marker = os.path.join(os.environ["MARSHAL_ROOT"], "runner-marker.txt")
with open(marker, "w", encoding="utf-8") as handle:
    handle.write(os.environ["MARSHAL_SQUAD"] + "|" + payload["command"])
sys.stdout.write("ran " + payload["squad_id"])
"""
FAILING_RUNNER_SOURCE = """\
import json
import sys

json.load(sys.stdin)
sys.exit(7)
"""


def run_cli(arguments: Sequence[str], capsys: pytest.CaptureFixture[str]) -> str:
    """Run a Marshal command, asserting a clean exit and empty stderr."""
    exit_code = main(arguments)
    captured = capsys.readouterr()
    assert exit_code == 0, captured.err
    assert captured.err == ""
    return captured.out


def json_cli(
    arguments: Sequence[str],
    capsys: pytest.CaptureFixture[str],
) -> JsonObject:
    """Run a Marshal command and parse its JSON stdout."""
    return parse_json_object(run_cli(arguments, capsys), CLI_SOURCE)


def parse_captured(capsys: pytest.CaptureFixture[str]) -> JsonObject:
    """Parse JSON already written to stdout (e.g. after a non-zero CLI exit)."""
    return parse_json_object(capsys.readouterr().out, CLI_SOURCE)


def obj(value: JsonValue) -> JsonObject:
    """Narrow a JSON value to an object."""
    if isinstance(value, dict):
        return value
    pytest.fail("expected JSON object")


def str_value(value: JsonValue) -> str:
    """Narrow a JSON value to a string."""
    if isinstance(value, str):
        return value
    pytest.fail("expected JSON string")


def bool_value(value: JsonValue) -> bool:
    """Narrow a JSON value to a bool."""
    if isinstance(value, bool):
        return value
    pytest.fail("expected JSON bool")


def str_list(value: JsonValue) -> tuple[str, ...]:
    """Narrow a JSON value to a tuple of strings."""
    if isinstance(value, list):
        return tuple(str_value(item) for item in value)
    pytest.fail("expected string list")


def squads_by_id(status: JsonObject) -> dict[str, JsonObject]:
    """Index a status snapshot's squads by id."""
    squads = status["squads"]
    if not isinstance(squads, list):
        pytest.fail("expected squad list")
    return {str_value(obj(squad)["squad_id"]): obj(squad) for squad in squads}


def init_two_squads(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Initialise squad-a (no deps) and squad-b (depends on squad-a)."""
    plan = root / ".omo" / "plans" / "squad-a.md"
    plan.parent.mkdir(parents=True)
    _ = plan.write_text("# plan\n", encoding="utf-8")
    _ = run_cli(
        (
            "init",
            "--root",
            str(root),
            "--goal",
            "Ship cache and dashboard",
            "--scope",
            "squad-a|Redis cache|-",
            "--scope",
            "squad-b|Dashboard|squad-a",
        ),
        capsys,
    )


def gate_squad_a(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Take squad-a through state init and a passed start gate."""
    _ = run_cli(
        (
            "state",
            "init",
            "--root",
            str(root),
            "--squad",
            "squad-a",
            "--plan",
            ".omo/plans/squad-a.md",
        ),
        capsys,
    )
    _ = run_cli(
        (
            "start-gate",
            "--root",
            str(root),
            "--squad",
            "squad-a",
            "--source",
            "assignment",
            "--example",
            "verify scope before work",
        ),
        capsys,
    )


def runner_command(tmp_path: Path, *, failing: bool = False) -> str:
    """Write a fake start-work runner script and return its command string."""
    script = tmp_path / ("failing-runner.py" if failing else "runner.py")
    _ = script.write_text(
        FAILING_RUNNER_SOURCE if failing else RUNNER_SOURCE,
        encoding="utf-8",
    )
    return f"{sys.executable} {script}"
