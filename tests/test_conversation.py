from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from marshal_cli.cli import main
from marshal_cli.jsonio import parse_json_object

if TYPE_CHECKING:
    from collections.abc import Sequence

    from marshal_cli.models import JsonObject, JsonValue

_CLI_SOURCE = Path("<cli>")


def _run(arguments: Sequence[str], capsys: pytest.CaptureFixture[str]) -> str:
    exit_code = main(arguments)
    captured = capsys.readouterr()
    assert exit_code == 0, captured.err
    assert captured.err == ""
    return captured.out


def _json(arguments: Sequence[str], capsys: pytest.CaptureFixture[str]) -> JsonObject:
    return parse_json_object(_run(arguments, capsys), _CLI_SOURCE)


def _obj(value: JsonValue) -> JsonObject:
    if isinstance(value, dict):
        return value
    pytest.fail("expected JSON object")


def _str(value: JsonValue) -> str:
    if isinstance(value, str):
        return value
    pytest.fail("expected JSON string")


def _objs(value: JsonValue) -> tuple[JsonObject, ...]:
    if isinstance(value, list):
        return tuple(_obj(item) for item in value)
    pytest.fail("expected JSON list")


def test_conversation_queue_serialises_questions_and_answers(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given a worker and a plan question posted to the queue
    asked = _json(
        (
            "conversation",
            "ask",
            "--root",
            str(tmp_path),
            "--squad",
            "squad-a",
            "--source",
            "worker",
            "--question",
            "TTL 60s or 300s?",
        ),
        capsys,
    )
    _ = _run(
        (
            "conversation",
            "ask",
            "--root",
            str(tmp_path),
            "--squad",
            "squad-a",
            "--source",
            "plan",
            "--question",
            "Approve plan v2?",
        ),
        capsys,
    )

    # When the Platoon Leader lists the queue, both are pending in order
    pending_view = _json(("conversation", "list", "--root", str(tmp_path)), capsys)

    # Then
    assert _str(asked["question_id"]) == "q-0001"
    pending = _objs(pending_view["pending"])
    assert tuple(_str(question["question_id"]) for question in pending) == (
        "q-0001",
        "q-0002",
    )
    assert _str(pending[0]["source"]) == "worker"

    # When the first question is answered
    _ = _run(
        (
            "conversation",
            "answer",
            "--root",
            str(tmp_path),
            "--id",
            "q-0001",
            "--answer",
            "Use 300s",
        ),
        capsys,
    )
    resolved = _json(
        ("conversation", "list", "--root", str(tmp_path), "--all"),
        capsys,
    )

    # Then only q-0002 stays pending and q-0001 carries its answer
    still_pending = _objs(resolved["pending"])
    answered = _objs(resolved["answered"])
    assert tuple(_str(q["question_id"]) for q in still_pending) == ("q-0002",)
    assert _str(answered[0]["question_id"]) == "q-0001"
    assert _str(answered[0]["answer"]) == "Use 300s"


def test_conversation_answer_rejects_unknown_and_duplicate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given one answered question
    _ = _run(
        (
            "conversation",
            "ask",
            "--root",
            str(tmp_path),
            "--squad",
            "squad-a",
            "--source",
            "worker",
            "--question",
            "Pick a value?",
        ),
        capsys,
    )
    _ = _run(
        (
            "conversation",
            "answer",
            "--root",
            str(tmp_path),
            "--id",
            "q-0001",
            "--answer",
            "Use 300s",
        ),
        capsys,
    )

    # When answering an unknown id
    with pytest.raises(SystemExit) as unknown:
        _ = main(
            (
                "conversation",
                "answer",
                "--root",
                str(tmp_path),
                "--id",
                "q-9999",
                "--answer",
                "x",
            ),
        )
    unknown_err = capsys.readouterr().err

    # And when answering the same id twice
    with pytest.raises(SystemExit) as duplicate:
        _ = main(
            (
                "conversation",
                "answer",
                "--root",
                str(tmp_path),
                "--id",
                "q-0001",
                "--answer",
                "again",
            ),
        )
    duplicate_err = capsys.readouterr().err

    # Then both are rejected
    assert unknown.value.code != 0
    assert "unknown question id" in unknown_err
    assert duplicate.value.code != 0
    assert "already answered" in duplicate_err


def test_conversation_ask_rejects_direct_user_source(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # When a caller tries to post as the user (no such source)
    with pytest.raises(SystemExit) as raised:
        _ = main(
            (
                "conversation",
                "ask",
                "--root",
                str(tmp_path),
                "--squad",
                "squad-a",
                "--source",
                "user",
                "--question",
                "x",
            ),
        )
    captured = capsys.readouterr()

    # Then argparse rejects the source outright
    assert raised.value.code != 0
    assert "invalid choice: 'user'" in captured.err
