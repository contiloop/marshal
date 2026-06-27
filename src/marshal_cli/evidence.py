"""Evidence verification for the active attempt ledger.

Before a `done` claim is trusted, the evidence recorded in the active-attempt
ledger events should point at files that actually exist (real-surface proof).
This module reads those events and reports which evidence entries resolve to
real files and which are missing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from marshal_cli.jsonio import JsonIOError, parse_json_object
from marshal_cli.ledger_core import latest_attempt_events
from marshal_cli.paths import ArtifactRoot

if TYPE_CHECKING:
    from collections.abc import Iterable

    from marshal_cli.models import JsonObject, JsonValue

EVIDENCE_CONTEXT: Final = "evidence"
_REAL_SURFACE_MARKERS: Final = ("real-surface", "real surface")
_PATH_SUFFIXES: Final = (
    ".md",
    ".json",
    ".jsonl",
    ".log",
    ".txt",
    ".py",
    ".png",
    ".diff",
    ".patch",
    ".html",
)


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """One evidence string and whether it resolves to a real file."""

    value: str
    kind: str
    exists: bool
    resolved: str | None

    def to_jsonable(self) -> JsonObject:
        """Return a JSON-compatible evidence item object."""
        return {
            "value": self.value,
            "kind": self.kind,
            "exists": self.exists,
            "resolved": self.resolved,
        }


@dataclass(frozen=True, slots=True)
class EvidenceReport:
    """The result of checking active-attempt ledger evidence."""

    squad_id: str
    active_attempt: int
    items: tuple[EvidenceItem, ...]
    missing_paths: tuple[str, ...]
    all_paths_present: bool
    has_real_surface: bool

    def to_jsonable(self) -> JsonObject:
        """Return a JSON-compatible evidence report object."""
        return {
            "squad_id": self.squad_id,
            "active_attempt": self.active_attempt,
            "items": [item.to_jsonable() for item in self.items],
            "missing_paths": list(self.missing_paths),
            "all_paths_present": self.all_paths_present,
            "has_real_surface": self.has_real_surface,
        }

    def ok(self, *, require_real_surface: bool) -> bool:
        """Return whether the report satisfies the requested strictness."""
        if not self.all_paths_present:
            return False
        return self.has_real_surface or not require_real_surface


def check_evidence(root: str | Path, squad_id: str) -> EvidenceReport:
    """Collect and classify evidence from the active-attempt ledger."""
    artifact_root = ArtifactRoot.from_user_input(root)
    latest = latest_attempt_events(artifact_root.root, squad_id)
    values = _evidence_values(latest.event_lines, latest.ledger_path)
    items = tuple(_evidence_item(artifact_root, value) for value in values)
    missing = tuple(
        item.value for item in items if item.kind == "path" and not item.exists
    )
    has_real_surface = any(_is_real_surface(item.value) for item in items)
    return EvidenceReport(
        squad_id=latest.squad_id,
        active_attempt=latest.active_attempt,
        items=items,
        missing_paths=missing,
        all_paths_present=not missing,
        has_real_surface=has_real_surface,
    )


def resolve_evidence_path(root: ArtifactRoot, value: str) -> tuple[Path, bool]:
    """Resolve one evidence value to an absolute path and whether it exists."""
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root.root / candidate
    return candidate, candidate.exists()


def looks_like_path(value: str) -> bool:
    """Return whether an evidence string is shaped like a file reference."""
    if "/" in value or "\\" in value:
        return True
    return " " not in value and Path(value).suffix.lower() in _PATH_SUFFIXES


def _evidence_item(root: ArtifactRoot, value: str) -> EvidenceItem:
    if not looks_like_path(value):
        return EvidenceItem(value=value, kind="note", exists=False, resolved=None)
    resolved, exists = resolve_evidence_path(root, value)
    return EvidenceItem(
        value=value,
        kind="path",
        exists=exists,
        resolved=str(resolved),
    )


def _evidence_values(lines: Iterable[str], ledger_path: Path) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for line in lines:
        for value in _line_evidence(line, ledger_path):
            if value not in seen:
                seen.add(value)
                values.append(value)
    return tuple(values)


def _line_evidence(line: str, ledger_path: Path) -> tuple[str, ...]:
    try:
        event = parse_json_object(line, ledger_path)
    except JsonIOError as error:
        raise JsonIOError(ledger_path, "invalid ledger evidence line") from error
    evidence = event.get("evidence")
    if not isinstance(evidence, list):
        return ()
    return tuple(_string_value(value) for value in evidence if _is_text(value))


def _is_text(value: JsonValue) -> bool:
    return isinstance(value, str) and bool(value)


def _string_value(value: JsonValue) -> str:
    return value if isinstance(value, str) else ""


def _is_real_surface(value: str) -> bool:
    folded = value.casefold()
    return any(marker in folded for marker in _REAL_SURFACE_MARKERS)


__all__ = [
    "EvidenceItem",
    "EvidenceReport",
    "check_evidence",
    "looks_like_path",
    "resolve_evidence_path",
]
