"""File-based Platoon Leader conversation queue.

Workers, work, and review never talk to the user directly; sync and plan own
question content but still need permission. Every user-facing question is posted
here instead, to `.omo/platoon/questions.jsonl`, where the Platoon Leader
serialises and answers it. The file is an append-only event log: a `question`
event opens an item and a matching `answer` event resolves it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from marshal_cli.conversation_models import (
    AnswerResult,
    AskResult,
    Question,
    QueueView,
)
from marshal_cli.jsonio import JsonIOError, append_jsonl, parse_json_object
from marshal_cli.models import (
    JsonObject,
    ReportSource,
    ValidationError,
    validate_squad_id,
)
from marshal_cli.paths import ArtifactRoot

if TYPE_CHECKING:
    from pathlib import Path

CONVERSATION_CONTEXT: Final = "conversation"
_QUESTION_SEGMENTS: Final = ("platoon", "questions.jsonl")
_QUESTION_KIND: Final = "question"
_ANSWER_KIND: Final = "answer"


def ask_question(
    root: str | Path,
    squad_id: str,
    source: ReportSource,
    question: str,
) -> AskResult:
    """Post a user-facing question to the Platoon Leader queue."""
    artifact_root = ArtifactRoot.from_user_input(root)
    validated_squad_id = validate_squad_id(squad_id)
    text = _required_text(question, "question")
    queue_path = artifact_root.omo_path(*_QUESTION_SEGMENTS)
    existing = _read_questions(queue_path)
    question_id = _next_question_id(existing)
    append_jsonl(
        queue_path,
        {
            "kind": _QUESTION_KIND,
            "id": question_id,
            "squad_id": validated_squad_id,
            "source": source.value,
            "question": text,
            "ts": _utc_timestamp(),
        },
    )
    return AskResult(
        question_id=question_id,
        squad_id=validated_squad_id,
        source=source,
        question=text,
        queue_path=queue_path,
    )


def list_questions(root: str | Path) -> QueueView:
    """Return the pending and answered questions in queue order."""
    artifact_root = ArtifactRoot.from_user_input(root)
    queue_path = artifact_root.omo_path(*_QUESTION_SEGMENTS)
    questions = _read_questions(queue_path)
    pending = tuple(q for q in questions if q.answer is None)
    answered = tuple(q for q in questions if q.answer is not None)
    return QueueView(pending=pending, answered=answered, queue_path=queue_path)


def answer_question(
    root: str | Path,
    question_id: str,
    answer: str,
) -> AnswerResult:
    """Record the Platoon Leader's answer to one queued question."""
    artifact_root = ArtifactRoot.from_user_input(root)
    text = _required_text(answer, "answer")
    queue_path = artifact_root.omo_path(*_QUESTION_SEGMENTS)
    questions = _read_questions(queue_path)
    target = _find_question(questions, question_id)
    if target.answer is not None:
        reason = "question is already answered"
        raise ValidationError(CONVERSATION_CONTEXT, "id", question_id, reason)
    append_jsonl(
        queue_path,
        {
            "kind": _ANSWER_KIND,
            "id": question_id,
            "answer": text,
            "ts": _utc_timestamp(),
        },
    )
    return AnswerResult(question_id=question_id, answer=text, queue_path=queue_path)


def _find_question(questions: tuple[Question, ...], question_id: str) -> Question:
    for question in questions:
        if question.question_id == question_id:
            return question
    reason = "unknown question id"
    raise ValidationError(CONVERSATION_CONTEXT, "id", question_id, reason)


def _read_questions(queue_path: Path) -> tuple[Question, ...]:
    questions: dict[str, Question] = {}
    order: list[str] = []
    for event in _read_events(queue_path):
        _apply_event(event, queue_path, questions, order)
    return tuple(questions[question_id] for question_id in order)


def _apply_event(
    event: JsonObject,
    queue_path: Path,
    questions: dict[str, Question],
    order: list[str],
) -> None:
    kind = event.get("kind")
    question_id = _event_id(event, queue_path)
    if kind == _QUESTION_KIND:
        questions[question_id] = _question_from_event(event, queue_path)
        order.append(question_id)
    elif kind == _ANSWER_KIND:
        existing = questions.get(question_id)
        if existing is not None:
            questions[question_id] = _with_answer(existing, event, queue_path)
    else:
        raise JsonIOError(queue_path, "unknown conversation event kind")


def _question_from_event(event: JsonObject, queue_path: Path) -> Question:
    return Question(
        question_id=_event_id(event, queue_path),
        squad_id=validate_squad_id(_event_str(event, "squad_id", queue_path)),
        source=_event_source(event, queue_path),
        question=_event_str(event, "question", queue_path),
        ts=_event_str(event, "ts", queue_path),
        answer=None,
        answered_ts=None,
    )


def _with_answer(question: Question, event: JsonObject, queue_path: Path) -> Question:
    return Question(
        question_id=question.question_id,
        squad_id=question.squad_id,
        source=question.source,
        question=question.question,
        ts=question.ts,
        answer=_event_str(event, "answer", queue_path),
        answered_ts=_event_str(event, "ts", queue_path),
    )


def _read_events(queue_path: Path) -> tuple[JsonObject, ...]:
    if not queue_path.exists():
        return ()
    try:
        text = queue_path.read_text(encoding="utf-8")
    except OSError as error:
        raise JsonIOError(queue_path, "failed to read conversation queue") from error
    return tuple(
        parse_json_object(line, queue_path) for line in text.splitlines() if line
    )


def _event_id(event: JsonObject, queue_path: Path) -> str:
    return _event_str(event, "id", queue_path)


def _event_str(event: JsonObject, field: str, queue_path: Path) -> str:
    value = event.get(field)
    if isinstance(value, str) and value:
        return value
    raise JsonIOError(queue_path, f"conversation event missing {field}")


def _event_source(event: JsonObject, queue_path: Path) -> ReportSource:
    value = _event_str(event, "source", queue_path)
    try:
        return ReportSource(value)
    except ValueError as error:
        raise JsonIOError(queue_path, "invalid conversation source") from error


def _next_question_id(questions: tuple[Question, ...]) -> str:
    return f"q-{len(questions) + 1:04d}"


def _required_text(value: str, field: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        reason = f"{field} must be non-empty"
        raise ValidationError(CONVERSATION_CONTEXT, field, value, reason)
    return trimmed


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "AnswerResult",
    "AskResult",
    "Question",
    "QueueView",
    "answer_question",
    "ask_question",
    "list_questions",
]
