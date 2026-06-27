from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING

import pytest

from marshal_cli.cli import main
from marshal_cli.jsonio import parse_json_object
from tests.marshal_support import (
    CLI_SOURCE,
    gate_squad_a,
    init_two_squads,
    obj,
    run_cli,
    str_value,
)

if TYPE_CHECKING:
    from pathlib import Path

    from marshal_cli.models import JsonObject, JsonValue


def _run_hook(
    event: str,
    payload: JsonValue | str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    exit_code = main(("hook", event))
    captured = capsys.readouterr()
    assert exit_code == 0, captured.err
    assert captured.err == ""
    return captured.out


def _stop_payload(root: Path, **overrides: JsonValue) -> JsonObject:
    payload: JsonObject = {
        "hook_event_name": "Stop",
        "session_id": "codex:abc",
        "cwd": str(root),
        "model": "test",
        "permission_mode": "default",
        "stop_hook_active": False,
    }
    payload.update(overrides)
    return payload


def test_stop_blocks_on_active_gated_squad(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    init_two_squads(tmp_path, capsys)
    gate_squad_a(tmp_path, capsys)

    # When
    out = _run_hook("stop", _stop_payload(tmp_path), capsys, monkeypatch)

    # Then
    decision = parse_json_object(out, CLI_SOURCE)
    assert str_value(decision["decision"]) == "block"
    reason = str_value(decision["reason"])
    assert "squad-a" in reason
    assert "stage `sync`" in reason
    assert "marshal status" in reason
    assert "squad-b" not in reason


def test_stop_silent_when_squad_initialized_but_not_gated(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    init_two_squads(tmp_path, capsys)
    _ = run_cli(
        ("state", "init", "--root", str(tmp_path), "--squad", "squad-a"),
        capsys,
    )

    # When
    out = _run_hook("stop", _stop_payload(tmp_path), capsys, monkeypatch)

    # Then
    assert out == ""


def test_stop_silent_without_initialized_squad(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    init_two_squads(tmp_path, capsys)

    # When
    out = _run_hook("stop", _stop_payload(tmp_path), capsys, monkeypatch)

    # Then
    assert out == ""


def test_stop_silent_without_platoon(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a directory with no Marshal platoon
    # When
    out = _run_hook("stop", _stop_payload(tmp_path), capsys, monkeypatch)

    # Then
    assert out == ""


def test_stop_silent_when_stop_hook_active(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    init_two_squads(tmp_path, capsys)
    gate_squad_a(tmp_path, capsys)

    # When
    payload = _stop_payload(tmp_path, stop_hook_active=True)
    out = _run_hook("stop", payload, capsys, monkeypatch)

    # Then
    assert out == ""


def test_stop_silent_on_context_pressure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    init_two_squads(tmp_path, capsys)
    gate_squad_a(tmp_path, capsys)
    transcript = tmp_path / "transcript.txt"
    _ = transcript.write_text("... context compacted ...", encoding="utf-8")

    # When
    payload = _stop_payload(tmp_path, transcript_path=str(transcript))
    out = _run_hook("stop", payload, capsys, monkeypatch)

    # Then
    assert out == ""


def test_subagent_stop_matches_stop(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    init_two_squads(tmp_path, capsys)
    gate_squad_a(tmp_path, capsys)

    # When
    stop_out = _run_hook("stop", _stop_payload(tmp_path), capsys, monkeypatch)
    subagent_out = _run_hook(
        "subagent-stop",
        _stop_payload(tmp_path, hook_event_name="SubagentStop"),
        capsys,
        monkeypatch,
    )

    # Then
    assert subagent_out == stop_out
    decision = parse_json_object(subagent_out, CLI_SOURCE)
    assert str_value(decision["decision"]) == "block"


def test_user_prompt_submit_injects_status(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    init_two_squads(tmp_path, capsys)
    payload: JsonObject = {
        "hook_event_name": "UserPromptSubmit",
        "cwd": str(tmp_path),
        "prompt": "what now?",
    }

    # When
    out = _run_hook("user-prompt-submit", payload, capsys, monkeypatch)

    # Then
    output = parse_json_object(out, CLI_SOURCE)
    specific = obj(output["hookSpecificOutput"])
    assert str_value(specific["hookEventName"]) == "UserPromptSubmit"
    context = str_value(specific["additionalContext"])
    assert "squad-a" in context
    assert "marshal status" in context


def test_user_prompt_submit_silent_without_platoon(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a directory with no Marshal platoon
    payload: JsonObject = {
        "hook_event_name": "UserPromptSubmit",
        "cwd": str(tmp_path),
    }

    # When
    out = _run_hook("user-prompt-submit", payload, capsys, monkeypatch)

    # Then
    assert out == ""


def test_hook_silent_on_malformed_stdin(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    init_two_squads(tmp_path, capsys)
    gate_squad_a(tmp_path, capsys)

    # When / Then
    no_cwd: JsonObject = {"hook_event_name": "Stop"}
    assert _run_hook("stop", "not json at all", capsys, monkeypatch) == ""
    assert _run_hook("stop", "", capsys, monkeypatch) == ""
    assert _run_hook("stop", no_cwd, capsys, monkeypatch) == ""


def test_hook_unknown_subcommand_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given / When / Then
    with pytest.raises(SystemExit):
        _ = main(("hook", "not-a-real-event"))
    _ = capsys.readouterr()
