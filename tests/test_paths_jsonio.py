from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from marshal_cli.jsonio import append_jsonl, read_json, write_json
from marshal_cli.paths import ArtifactRoot, PathSecurityError

if TYPE_CHECKING:
    from pathlib import Path


def test_omo_path_builds_inside_artifact_root_when_segments_are_safe(
    tmp_path: Path,
) -> None:
    root = ArtifactRoot.from_user_input(tmp_path)

    artifact_path = root.omo_path("squad", "squad-a", "state.json")

    assert artifact_path == tmp_path / ".omo" / "squad" / "squad-a" / "state.json"


def test_from_user_input_rejects_protected_roots_before_writing() -> None:
    with pytest.raises(PathSecurityError, match="khala"):
        _ = ArtifactRoot.from_user_input("/Users/inertia/Desktop/agent_study/khala")

    with pytest.raises(PathSecurityError, match="plugins"):
        _ = ArtifactRoot.from_user_input("/Users/inertia/.codex/plugins")


def test_omo_path_rejects_parent_traversal_before_writing(tmp_path: Path) -> None:
    root = ArtifactRoot.from_user_input(tmp_path)

    with pytest.raises(PathSecurityError, match="outside artifact root"):
        _ = root.omo_path("..", "outside.json")

    assert not (tmp_path / "outside.json").exists()


def test_omo_path_rejects_escape_when_user_root_contains_omo_segment(
    tmp_path: Path,
) -> None:
    user_root = tmp_path / ".omo" / "nested-root"
    root = ArtifactRoot.from_user_input(user_root)

    with pytest.raises(PathSecurityError, match="outside artifact root"):
        _ = root.omo_path("..", "outside.json")

    assert not (user_root / "outside.json").exists()


def test_write_json_creates_parent_directories_and_read_json_returns_mapping(
    tmp_path: Path,
) -> None:
    root = ArtifactRoot.from_user_input(tmp_path)
    state_path = root.omo_path("squad", "squad-a", "state.json")

    write_json(state_path, {"current_stage": "sync", "attempt": 1})
    loaded = read_json(state_path)

    assert loaded == {"current_stage": "sync", "attempt": 1}


def test_append_jsonl_creates_append_only_ledger_entries(tmp_path: Path) -> None:
    root = ArtifactRoot.from_user_input(tmp_path)
    ledger_path = root.omo_path("squad", "squad-a", "ledger.jsonl")

    append_jsonl(ledger_path, {"event": "started", "attempt": 1})
    append_jsonl(ledger_path, {"event": "done", "attempt": 1})

    assert ledger_path.read_text(encoding="utf-8").splitlines() == [
        '{"attempt":1,"event":"started"}',
        '{"attempt":1,"event":"done"}',
    ]


def test_write_json_rejects_symlink_escape_before_writing(tmp_path: Path) -> None:
    root = ArtifactRoot.from_user_input(tmp_path / "root")
    outside = tmp_path / "outside"
    outside.mkdir()
    omo_dir = tmp_path / "root" / ".omo"
    omo_dir.mkdir(parents=True)
    escaping_link = omo_dir / "escape"
    escaping_link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathSecurityError, match="outside artifact root"):
        _ = root.omo_path("escape", "state.json")

    assert not (outside / "state.json").exists()
