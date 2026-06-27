from pathlib import Path

import pytest

from marshal_cli.cli import main
from marshal_cli.jsonio import read_json
from marshal_cli.models import ValidationError
from marshal_cli.platoon import create_assignment_packets


def test_create_assignment_packets_writes_checklist_and_assignments(
    tmp_path: Path,
) -> None:
    result = create_assignment_packets(
        root=tmp_path,
        platoon_goal="Ship cache and dashboard",
        scope_specs=(
            "squad-a|Redis cache|-",
            "squad-b|Admin dashboard|squad-a",
        ),
    )

    checklist = read_json(tmp_path / ".omo" / "platoon" / "checklist.json")
    squad_a = read_json(tmp_path / ".omo" / "squad" / "squad-a" / "assignment.json")
    squad_b = read_json(tmp_path / ".omo" / "squad" / "squad-b" / "assignment.json")

    assert result.dependency_order == (("squad-a",), ("squad-b",))
    assert checklist["global_order"] == [["squad-a"], ["squad-b"]]
    assert "squads_summary" in checklist
    assert checklist["basic_rules"] == [
        "no-fallback",
        "failing-first-proof",
        "no-suppress-tests-lints-errors",
        "minimal-change",
        "evidence-based-completion",
        "cleanup-receipt",
        "no-tautological-tests",
        "real-surface-e2e",
    ]
    assert squad_a["assigned_scope"] == {
        "squad_id": "squad-a",
        "goal": "Redis cache",
        "in_scope": ["Redis cache"],
        "out_of_scope": ["Admin dashboard"],
        "depends_on": [],
        "blocks": ["squad-b"],
        "success_evidence": ["RED/GREEN logs", "real-surface proof"],
    }
    assert squad_b["global_order"] == [["squad-a"], ["squad-b"]]


def test_create_assignment_packets_rejects_missing_dependency_before_write(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError, match=r"missing-squad.*unknown dependency"):
        _ = create_assignment_packets(
            root=tmp_path,
            platoon_goal="Bad plan",
            scope_specs=("squad-a|Redis cache|missing-squad",),
        )

    assert not (tmp_path / ".omo" / "platoon" / "checklist.json").exists()
    assert not (tmp_path / ".omo" / "squad" / "squad-a" / "assignment.json").exists()


def test_init_command_prints_written_paths_and_dependency_order(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        (
            "init",
            "--root",
            str(tmp_path),
            "--goal",
            "Ship cache and dashboard",
            "--scope",
            "squad-a|Redis cache|-",
            "--scope",
            "squad-b|Admin dashboard|squad-a",
        ),
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert '"dependency_order"' in captured.out
    assert '"squad-a"' in captured.out
    assert '"squad-b"' in captured.out
    assert '"assignment_paths"' in captured.out
    assert (tmp_path / ".omo" / "platoon" / "checklist.json").exists()
    assert (tmp_path / ".omo" / "squad" / "squad-a" / "assignment.json").exists()
    assert (tmp_path / ".omo" / "squad" / "squad-b" / "assignment.json").exists()
