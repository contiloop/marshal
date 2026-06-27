"""Protected artifact path helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Self, override

PROTECTED_ROOTS: Final[tuple[Path, ...]] = (
    Path("/Users/inertia/Desktop/agent_study/khala").resolve(strict=False),
    Path("/Users/inertia/.codex/plugins").resolve(strict=False),
)


@dataclass(frozen=True, slots=True)
class PathSecurityError(Exception):
    """Raised when an artifact path would escape or touch a protected root."""

    path: Path
    reason: str

    @override
    def __str__(self) -> str:
        """Return the security reason with the rejected path."""
        return f"{self.reason}: {self.path}"


@dataclass(frozen=True, slots=True)
class ArtifactRoot:
    """Caller-provided artifact root parsed into a safe path boundary."""

    root: Path

    @classmethod
    def from_user_input(cls, value: str | Path) -> Self:
        """Parse user input and reject protected artifact roots."""
        resolved = Path(value).expanduser().resolve(strict=False)
        _raise_if_protected(resolved)
        return cls(root=resolved)

    def omo_path(self, *segments: str) -> Path:
        """Return a safe path below this root's `.omo` artifact directory."""
        artifact_root = self.root / ".omo"
        candidate = artifact_root.joinpath(*segments)
        return ensure_artifact_path(candidate, artifact_root)


def ensure_artifact_path(
    value: str | Path,
    artifact_root: str | Path | None = None,
) -> Path:
    """Reject protected paths and symlink/path traversal escapes."""
    candidate = _absolute_without_resolving(value)
    resolved = candidate.resolve(strict=False)
    _raise_if_protected(resolved)
    root = (
        _artifact_anchor(candidate)
        if artifact_root is None
        else _artifact_root(artifact_root)
    )

    if not resolved.is_relative_to(root):
        raise PathSecurityError(resolved, "path resolves outside artifact root")

    return candidate


def _artifact_root(value: str | Path) -> Path:
    return _absolute_without_resolving(value).resolve(strict=False)


def _absolute_without_resolving(value: str | Path) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate
    return Path.cwd() / candidate


def _artifact_anchor(candidate: Path) -> Path:
    for index, part in enumerate(candidate.parts):
        if part == ".omo":
            return Path(*candidate.parts[: index + 1])
    raise PathSecurityError(candidate, "artifact path must be under a .omo directory")


def _raise_if_protected(resolved: Path) -> None:
    for protected_root in PROTECTED_ROOTS:
        if resolved == protected_root or resolved.is_relative_to(protected_root):
            raise PathSecurityError(resolved, "protected artifact root is forbidden")


__all__ = ["ArtifactRoot", "PathSecurityError", "ensure_artifact_path"]
