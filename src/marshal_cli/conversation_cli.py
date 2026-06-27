"""Argparse command surface for the Platoon Leader conversation queue."""

from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING, Final, NoReturn

from marshal_cli.conversation import (
    answer_question,
    ask_question,
    list_questions,
)
from marshal_cli.jsonio import JsonIOError
from marshal_cli.models import JsonObject, ReportSource, ValidationError
from marshal_cli.paths import PathSecurityError

if TYPE_CHECKING:
    from collections.abc import Sequence

_CONVERSATION_ERRORS: Final = (JsonIOError, PathSecurityError, ValidationError)
CONVERSATION_COMMAND_HELP: Final = """commands:
  conversation ask     post a user-facing question to the Platoon Leader queue
  conversation list    print pending (and, with --all, answered) questions
  conversation answer  record the Platoon Leader's answer to a question"""


class _AskNamespace(argparse.Namespace):
    root: str
    squad_id: str
    source: str
    question: str

    def __init__(self) -> None:
        super().__init__()
        self.root = ""
        self.squad_id = ""
        self.source = ""
        self.question = ""


class _ListNamespace(argparse.Namespace):
    root: str
    show_all: bool

    def __init__(self) -> None:
        super().__init__()
        self.root = ""
        self.show_all = False


class _AnswerNamespace(argparse.Namespace):
    root: str
    question_id: str
    answer: str

    def __init__(self) -> None:
        super().__init__()
        self.root = ""
        self.question_id = ""
        self.answer = ""


def run_conversation_command(arguments: Sequence[str]) -> int:
    """Run the `marshal conversation` command group."""
    parser = _build_conversation_parser()
    if not arguments:
        parser.error("unknown command: <missing>")
    if arguments[0].startswith("-"):
        _ = parser.parse_args(arguments)
        parser.print_help()
        return 0

    command = arguments[0]
    if command == "ask":
        return _run_ask(arguments[1:])
    if command == "list":
        return _run_list(arguments[1:])
    if command == "answer":
        return _run_answer(arguments[1:])
    return _parser_error(parser, f"unknown command: {command}")


def _run_ask(arguments: Sequence[str]) -> int:
    parser = _build_ask_parser()
    parsed = _AskNamespace()
    _ = parser.parse_args(arguments, namespace=parsed)
    try:
        result = ask_question(
            parsed.root,
            parsed.squad_id,
            ReportSource(parsed.source),
            parsed.question,
        )
    except _CONVERSATION_ERRORS as error:
        parser.error(str(error))
    _write_result(result.to_jsonable())
    return 0


def _run_list(arguments: Sequence[str]) -> int:
    parser = _build_list_parser()
    parsed = _ListNamespace()
    _ = parser.parse_args(arguments, namespace=parsed)
    try:
        view = list_questions(parsed.root)
    except _CONVERSATION_ERRORS as error:
        parser.error(str(error))
    _write_result(view.to_jsonable(include_answered=parsed.show_all))
    return 0


def _run_answer(arguments: Sequence[str]) -> int:
    parser = _build_answer_parser()
    parsed = _AnswerNamespace()
    _ = parser.parse_args(arguments, namespace=parsed)
    try:
        result = answer_question(parsed.root, parsed.question_id, parsed.answer)
    except _CONVERSATION_ERRORS as error:
        parser.error(str(error))
    _write_result(result.to_jsonable())
    return 0


def _build_conversation_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="marshal conversation",
        description="Post, list, and answer Platoon Leader queue questions.",
        epilog=CONVERSATION_COMMAND_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def _build_ask_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="marshal conversation ask",
        description="Post a user-facing question to the Platoon Leader queue.",
    )
    _ = parser.add_argument("--root", required=True)
    _ = parser.add_argument("--squad", dest="squad_id", required=True)
    _ = parser.add_argument(
        "--source",
        required=True,
        choices=[source.value for source in ReportSource],
    )
    _ = parser.add_argument("--question", required=True)
    return parser


def _build_list_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="marshal conversation list",
        description="Print pending (and, with --all, answered) questions.",
    )
    _ = parser.add_argument("--root", required=True)
    _ = parser.add_argument("--all", dest="show_all", action="store_true")
    return parser


def _build_answer_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="marshal conversation answer",
        description="Record the Platoon Leader's answer to a question.",
    )
    _ = parser.add_argument("--root", required=True)
    _ = parser.add_argument("--id", dest="question_id", required=True)
    _ = parser.add_argument("--answer", required=True)
    return parser


def _write_result(result: JsonObject) -> None:
    _ = sys.stdout.write(json.dumps(result, indent=2, sort_keys=True))
    _ = sys.stdout.write("\n")


def _parser_error(parser: argparse.ArgumentParser, message: str) -> NoReturn:
    parser.error(message)


__all__ = ["run_conversation_command"]
