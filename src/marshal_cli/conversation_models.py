"""Domain models for the Platoon Leader conversation queue."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from marshal_cli.models import JsonObject, ReportSource


@dataclass(frozen=True, slots=True)
class Question:
    """A queued user-facing question and its resolution, if any."""

    question_id: str
    squad_id: str
    source: ReportSource
    question: str
    ts: str
    answer: str | None
    answered_ts: str | None

    @property
    def status(self) -> str:
        """Return whether the question is pending or answered."""
        return "answered" if self.answer is not None else "pending"

    def to_jsonable(self) -> JsonObject:
        """Return a JSON-compatible question object."""
        return {
            "question_id": self.question_id,
            "squad_id": self.squad_id,
            "source": self.source.value,
            "question": self.question,
            "ts": self.ts,
            "status": self.status,
            "answer": self.answer,
            "answered_ts": self.answered_ts,
        }


@dataclass(frozen=True, slots=True)
class AskResult:
    """Result of posting one question to the queue."""

    question_id: str
    squad_id: str
    source: ReportSource
    question: str
    queue_path: Path

    def to_jsonable(self) -> JsonObject:
        """Return a JSON-compatible ask result object."""
        return {
            "question_id": self.question_id,
            "squad_id": self.squad_id,
            "source": self.source.value,
            "question": self.question,
            "status": "pending",
            "queue_path": str(self.queue_path),
        }


@dataclass(frozen=True, slots=True)
class AnswerResult:
    """Result of answering one queued question."""

    question_id: str
    answer: str
    queue_path: Path

    def to_jsonable(self) -> JsonObject:
        """Return a JSON-compatible answer result object."""
        return {
            "question_id": self.question_id,
            "answer": self.answer,
            "status": "answered",
            "queue_path": str(self.queue_path),
        }


@dataclass(frozen=True, slots=True)
class QueueView:
    """The folded view of every queued question."""

    pending: tuple[Question, ...]
    answered: tuple[Question, ...]
    queue_path: Path

    def to_jsonable(self, *, include_answered: bool) -> JsonObject:
        """Return a JSON-compatible queue view object."""
        view: JsonObject = {
            "pending": [question.to_jsonable() for question in self.pending],
            "pending_count": len(self.pending),
            "answered_count": len(self.answered),
            "queue_path": str(self.queue_path),
        }
        if include_answered:
            view["answered"] = [question.to_jsonable() for question in self.answered]
        return view


__all__ = ["AnswerResult", "AskResult", "Question", "QueueView"]
