from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from marshal_cli.cli import main

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class _PathSnapshot:
    exists: bool
    size: int | None
    modified_ns: int | None


def test_full_public_cli_workflow_emits_start_work_without_invoking(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    plan_path = tmp_path / ".omo" / "plans" / "squad-a.md"
    plan_path.parent.mkdir(parents=True)
    _ = plan_path.write_text("# squad-a work plan\n", encoding="utf-8")

    # When
    _ = _run_command(
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
        capsys,
    )
    _ = _run_command(
        (
            "state",
            "init",
            "--root",
            str(tmp_path),
            "--squad",
            "squad-a",
            "--plan",
            ".omo/plans/squad-a.md",
        ),
        capsys,
    )
    _ = _run_command(
        (
            "start-gate",
            "--root",
            str(tmp_path),
            "--squad",
            "squad-a",
            "--source",
            "assignment",
            "--example",
            "If design flaw appears, route to plan.",
        ),
        capsys,
    )
    route_output = _run_command(
        (
            "route",
            "--root",
            str(tmp_path),
            "--squad",
            "squad-a",
            "--source",
            "work",
            "--type",
            "design_flaw",
            "--detail",
            "unexpected dependency",
            "--finding",
            "plan missing dependency edge",
        ),
        capsys,
    )
    _ = _run_command(
        (
            "start-gate",
            "--root",
            str(tmp_path),
            "--squad",
            "squad-a",
            "--source",
            "plan",
            "--example",
            "If plan restarts, verify attempt 2 before work.",
        ),
        capsys,
    )
    ledger_output = _run_command(
        ("ledger", "latest", "--root", str(tmp_path), "--squad", "squad-a"),
        capsys,
    )
    delegate_output = _run_command(
        ("delegate-start-work", "--root", str(tmp_path), "--squad", "squad-a"),
        capsys,
    )

    # Then
    assert '"current_stage": "plan"' in route_output
    assert '"active_attempt": 2' in ledger_output
    assert '"events": [\n    {' in ledger_output
    assert '"attempt":  2' in ledger_output
    assert '"command": "$start-work squad-a"' in delegate_output
    assert '"start_gate_status": "passed"' in delegate_output
    assert (tmp_path / ".omo" / "platoon" / "checklist.json").exists()
    assert (tmp_path / ".omo" / "squad" / "squad-a" / "assignment.json").exists()
    assert (tmp_path / ".omo" / "squad" / "squad-a" / "state.json").exists()
    assert (tmp_path / ".omo" / "squad" / "squad-a" / "start-gate.json").exists()
    assert (tmp_path / ".omo" / "squad" / "squad-a" / "ledger.jsonl").exists()


def test_readme_documents_exact_workflow_and_start_work_boundary() -> None:
    # Given
    readme = _readme_text()
    workflow_commands = (
        'uv run marshal init --root "$QA_ROOT" --goal "Ship cache and dashboard"',
        _command(
            'uv run marshal state init --root "$QA_ROOT" --squad squad-a',
            '--plan ".omo/plans/squad-a.md"',
        ),
        _command(
            'uv run marshal start-gate --root "$QA_ROOT" --squad squad-a',
            "--source assignment",
            '--example "If design flaw appears, route to plan."',
        ),
        _command(
            'uv run marshal route --root "$QA_ROOT" --squad squad-a',
            "--source work --type design_flaw",
            '--detail "unexpected dependency"',
            '--finding "plan missing dependency edge"',
        ),
        _command(
            'uv run marshal start-gate --root "$QA_ROOT" --squad squad-a',
            "--source plan",
            '--example "If plan restarts, verify attempt 2 before work."',
        ),
        'uv run marshal ledger latest --root "$QA_ROOT" --squad squad-a',
        'uv run marshal delegate-start-work --root "$QA_ROOT" --squad squad-a',
    )

    # When / Then
    for command in workflow_commands:
        assert command in readme
    assert "start-work is emitted, not invoked" in readme


def test_init_help_documents_scope_format(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given / When
    with pytest.raises(SystemExit) as raised:
        _ = main(("init", "--help"))

    # Then
    captured = capsys.readouterr()
    assert raised.value.code == 0
    assert "<squad-id>|<goal>|<depends_csv_or_->" in captured.out


def test_public_cli_rejects_protected_roots_before_writing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    khala_artifact = Path(
        "/Users/inertia/Desktop/agent_study/khala/.omo/platoon/checklist.json",
    )
    plugin_artifact = Path("/Users/inertia/.codex/plugins/.omo/platoon/checklist.json")
    khala_before = _snapshot(khala_artifact)
    plugin_before = _snapshot(plugin_artifact)

    # When / Then
    _assert_protected_root_rejected(
        "/Users/inertia/Desktop/agent_study/khala",
        "khala",
        capsys,
    )
    _assert_protected_root_rejected(
        "/Users/inertia/.codex/plugins",
        "plugins",
        capsys,
    )
    assert _snapshot(khala_artifact) == khala_before
    assert _snapshot(plugin_artifact) == plugin_before


def _run_command(
    arguments: Sequence[str],
    capsys: pytest.CaptureFixture[str],
) -> str:
    exit_code = main(arguments)
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    return captured.out


def _readme_text() -> str:
    path = Path(__file__).resolve().parents[1] / "README.md"
    return path.read_text(encoding="utf-8")


def _command(*parts: str) -> str:
    return " ".join(parts)


def _assert_protected_root_rejected(
    root: str,
    expected_text: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        _ = main(
            (
                "init",
                "--root",
                root,
                "--goal",
                "Forbidden",
                "--scope",
                "squad-a|Bad|-",
            ),
        )
    captured = capsys.readouterr()
    assert raised.value.code != 0
    assert "protected artifact root is forbidden" in captured.err
    assert expected_text in captured.err


def _snapshot(path: Path) -> _PathSnapshot:
    if not path.exists():
        return _PathSnapshot(exists=False, size=None, modified_ns=None)
    stat = path.stat()
    return _PathSnapshot(
        exists=True,
        size=stat.st_size,
        modified_ns=stat.st_mtime_ns,
    )
