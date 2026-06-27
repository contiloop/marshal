from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from marshal_cli.cli import main
from tests.marshal_support import (
    bool_value,
    gate_squad_a,
    init_two_squads,
    json_cli,
    obj,
    str_list,
    str_value,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_complete_requires_real_evidence_and_advances_waves(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    init_two_squads(tmp_path, capsys)
    gate_squad_a(tmp_path, capsys)
    evidence = tmp_path / ".omo" / "evidence" / "a-e2e.log"
    evidence.parent.mkdir(parents=True)
    _ = evidence.write_text("RED/GREEN; real-surface proof\n", encoding="utf-8")

    # When / Then: missing evidence file is rejected
    with pytest.raises(SystemExit) as raised:
        _ = main(
            (
                "complete",
                "--root",
                str(tmp_path),
                "--squad",
                "squad-a",
                "--evidence",
                ".omo/evidence/missing.log",
                "--detail",
                "done",
            ),
        )
    captured = capsys.readouterr()
    assert raised.value.code != 0
    assert "evidence files do not exist" in captured.err

    # When: a real evidence file is supplied
    completed = json_cli(
        (
            "complete",
            "--root",
            str(tmp_path),
            "--squad",
            "squad-a",
            "--evidence",
            ".omo/evidence/a-e2e.log",
            "--detail",
            "cache shipped",
        ),
        capsys,
    )
    nxt = json_cli(("next", "--root", str(tmp_path)), capsys)

    # Then
    assert str_value(completed["current_stage"]) == "done"
    assert str_list(nxt["next_squads"]) == ("squad-b",)


def test_abort_blocks_delegation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    init_two_squads(tmp_path, capsys)
    gate_squad_a(tmp_path, capsys)

    # When
    aborted = json_cli(
        (
            "abort",
            "--root",
            str(tmp_path),
            "--squad",
            "squad-a",
            "--reason",
            "user changed direction",
        ),
        capsys,
    )

    # Then
    assert str_value(aborted["current_stage"]) == "aborted"
    with pytest.raises(SystemExit) as raised:
        _ = main(("delegate-start-work", "--root", str(tmp_path), "--squad", "squad-a"))
    captured = capsys.readouterr()
    assert raised.value.code != 0
    assert "squad is aborted" in captured.err


def test_evidence_check_strict_requires_real_surface(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    init_two_squads(tmp_path, capsys)
    gate_squad_a(tmp_path, capsys)

    # When
    report = json_cli(
        ("evidence", "check", "--root", str(tmp_path), "--squad", "squad-a"),
        capsys,
    )
    strict_code = main(
        (
            "evidence",
            "check",
            "--root",
            str(tmp_path),
            "--squad",
            "squad-a",
            "--strict",
            "--require-real-surface",
        ),
    )
    _ = capsys.readouterr()

    # Then: start-gate recorded real file paths but no real-surface marker yet
    assert bool_value(report["all_paths_present"]) is True
    assert bool_value(report["has_real_surface"]) is False
    assert strict_code == 1


def test_handover_emits_packet_and_next_action(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    init_two_squads(tmp_path, capsys)
    gate_squad_a(tmp_path, capsys)

    # When
    packet = json_cli(
        ("handover", "--root", str(tmp_path), "--squad", "squad-a"), capsys
    )

    # Then
    assert str_value(packet["current_stage"]) == "sync"
    assert "sync" in str_value(packet["next_action"]).lower()
    platoon = obj(obj(packet["packet"])["platoon"])
    assert str_list(platoon["next_squads"]) == ("squad-a",)
    assert (tmp_path / ".omo" / "squad" / "squad-a" / "handover.json").exists()
