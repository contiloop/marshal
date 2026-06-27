from pathlib import Path

import pytest

from marshal_cli.cli import main
from marshal_cli.jsonio import read_json, write_json
from marshal_cli.platoon import create_assignment_packets
from marshal_cli.squad_state import initialize_squad_state


def test_start_gate_passes_and_records_started_event(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    _create_initialized_state(tmp_path)
    example = "If design flaw appears, report design_flaw to Squad Leader."

    # When
    exit_code = main(
        (
            "start-gate",
            "--root",
            str(tmp_path),
            "--squad",
            "squad-a",
            "--source",
            "assignment",
            "--example",
            example,
        ),
    )

    # Then
    captured = capsys.readouterr()
    gate_path = tmp_path / ".omo" / "squad" / "squad-a" / "start-gate.json"
    ledger_path = tmp_path / ".omo" / "squad" / "squad-a" / "ledger.jsonl"
    gate = read_json(gate_path)
    assert exit_code == 0
    assert '"gate_status": "passed"' in captured.out
    assert '"current_stage": "sync"' in captured.out
    assert '"active_attempt": 1' in captured.out
    assert gate["source_artifacts"] == [
        str(tmp_path / ".omo" / "squad" / "squad-a" / "assignment.json"),
        str(tmp_path / ".omo" / "squad" / "squad-a" / "state.json"),
        str(tmp_path / ".omo" / "platoon" / "checklist.json"),
        str(ledger_path),
    ]
    assert gate["scope_authority"] == "squad-a owns Redis cache"
    assert gate["freshness"] == "passed"
    assert gate["applied_example"] == example
    ledger_text = ledger_path.read_text(encoding="utf-8")
    assert '"event": "started"' in ledger_text
    assert '"attempt": 1' in ledger_text


def test_start_gate_rejects_empty_example_without_started_event(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    _create_initialized_state(tmp_path)
    ledger_path = tmp_path / ".omo" / "squad" / "squad-a" / "ledger.jsonl"
    before = _line_count(ledger_path)

    # When
    with pytest.raises(SystemExit) as raised:
        _ = main(
            (
                "start-gate",
                "--root",
                str(tmp_path),
                "--squad",
                "squad-a",
                "--source",
                "assignment",
                "--example",
                "",
            ),
        )

    # Then
    captured = capsys.readouterr()
    assert raised.value.code != 0
    assert _line_count(ledger_path) == before
    assert "example" in captured.err
    assert "required" in captured.err


def test_start_gate_rejects_stale_state_without_started_event(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    _create_initialized_state(tmp_path)
    state_path = tmp_path / ".omo" / "squad" / "squad-a" / "state.json"
    state = read_json(state_path)
    state["scope"] = "Old scope"
    write_json(state_path, state)
    ledger_path = tmp_path / ".omo" / "squad" / "squad-a" / "ledger.jsonl"

    # When
    with pytest.raises(SystemExit) as raised:
        _ = main(
            (
                "start-gate",
                "--root",
                str(tmp_path),
                "--squad",
                "squad-a",
                "--source",
                "state",
                "--example",
                "If stale state appears, stop before starting.",
            ),
        )

    # Then
    captured = capsys.readouterr()
    assert raised.value.code != 0
    assert _line_count(ledger_path) == 0
    assert "stale" in captured.err


def test_start_gate_rejects_plan_artifact_outside_root_omo(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    _create_initialized_state(tmp_path)
    external_plan = tmp_path / "outside-plan.md"
    _ = external_plan.write_text("# outside plan\n", encoding="utf-8")
    ledger_path = tmp_path / ".omo" / "squad" / "squad-a" / "ledger.jsonl"
    gate_path = tmp_path / ".omo" / "squad" / "squad-a" / "start-gate.json"

    # When
    with pytest.raises(SystemExit) as raised:
        _ = main(
            (
                "start-gate",
                "--root",
                str(tmp_path),
                "--squad",
                "squad-a",
                "--source",
                "plan",
                "--plan",
                str(external_plan),
                "--example",
                "If plan is external, reject it before start.",
            ),
        )

    # Then
    captured = capsys.readouterr()
    assert raised.value.code != 0
    assert "outside artifact root" in captured.err or "artifact root" in captured.err
    assert not gate_path.exists()
    assert _line_count(ledger_path) == 0


def test_start_gate_accepts_relative_plan_under_root_omo(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    _create_initialized_state(tmp_path)
    plan_path = tmp_path / ".omo" / "plans" / "squad-a.md"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    _ = plan_path.write_text("# squad-a plan\n", encoding="utf-8")

    # When
    exit_code = main(
        (
            "start-gate",
            "--root",
            str(tmp_path),
            "--squad",
            "squad-a",
            "--source",
            "plan",
            "--plan",
            ".omo/plans/squad-a.md",
            "--example",
            "If plan is under root .omo, allow it.",
        ),
    )

    # Then
    captured = capsys.readouterr()
    assert exit_code == 0
    assert str(plan_path) in captured.out


def _create_initialized_state(root: Path) -> None:
    _ = create_assignment_packets(
        root=root,
        platoon_goal="Ship cache",
        scope_specs=("squad-a|Redis cache|-",),
    )
    _ = initialize_squad_state(root, "squad-a", None)


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())
