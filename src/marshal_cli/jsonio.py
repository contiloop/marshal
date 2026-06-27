"""JSON and JSONL artifact IO helpers."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final, override

from marshal_cli.paths import ensure_artifact_path

CONTROL_CHARACTER_LIMIT: Final = 0x20

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | JsonArray | JsonObject
type JsonArray = list[JsonValue]
type JsonObject = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class JsonIOError(Exception):
    """Raised when a JSON artifact cannot be read or written."""

    path: Path
    reason: str

    @override
    def __str__(self) -> str:
        """Return the IO failure reason with the artifact path."""
        return f"{self.reason}: {self.path}"


def write_json(path: str | Path, data: JsonObject) -> None:
    """Write a JSON object atomically after validating artifact containment."""
    safe_path = ensure_artifact_path(path)
    encoded = json.dumps(data, indent=2, sort_keys=True)
    temp_path: Path | None = None

    try:
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            delete=False,
            dir=safe_path.parent,
            encoding="utf-8",
            prefix=f".{safe_path.name}.",
            suffix=".tmp",
        ) as temp_file:
            _ = temp_file.write(encoded)
            _ = temp_file.write("\n")
            temp_path = Path(temp_file.name)
        _ = temp_path.replace(safe_path)
    except OSError as error:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise JsonIOError(safe_path, "failed to write JSON artifact") from error


def read_json(path: str | Path) -> JsonObject:
    """Read a JSON object artifact after validating artifact containment."""
    safe_path = ensure_artifact_path(path)
    try:
        raw_json = safe_path.read_text(encoding="utf-8")
    except OSError as error:
        raise JsonIOError(safe_path, "failed to read JSON artifact") from error

    decoded = _JsonReader(raw_json, safe_path).parse()
    return _json_object_from_decoded(decoded, safe_path)


def append_jsonl(path: str | Path, data: JsonObject) -> None:
    """Append a JSON object as one JSONL ledger entry."""
    safe_path = ensure_artifact_path(path)
    encoded = json.dumps(data, separators=(",", ":"), sort_keys=True)
    try:
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        with safe_path.open("a", encoding="utf-8") as ledger_file:
            _ = ledger_file.write(encoded)
            _ = ledger_file.write("\n")
    except OSError as error:
        raise JsonIOError(safe_path, "failed to append JSONL artifact") from error


def _json_object_from_decoded(decoded: JsonValue, source: Path) -> JsonObject:
    if isinstance(decoded, dict):
        return decoded
    raise JsonIOError(source, "JSON artifact must contain an object")


class _JsonReader:
    """Typed JSON parser used to avoid untyped stdlib JSON decode results."""

    __slots__: Final = ("index", "source", "text")
    text: str
    source: Path
    index: int

    def __init__(self, text: str, source: Path) -> None:
        self.text = text
        self.source = source
        self.index = 0

    def parse(self) -> JsonValue:
        value = self._parse_value()
        self._skip_whitespace()
        if self.index != len(self.text):
            raise JsonIOError(self.source, "invalid trailing JSON content")
        return value

    def _parse_value(self) -> JsonValue:
        self._skip_whitespace()
        if self.index >= len(self.text):
            raise JsonIOError(self.source, "unexpected end of JSON artifact")

        character = self.text[self.index]
        value: JsonValue
        if character == "{":
            value = self._parse_object()
        elif character == "[":
            value = self._parse_array()
        elif character == '"':
            value = self._parse_string()
        elif character == "t":
            self._consume_literal("true")
            value = True
        elif character == "f":
            self._consume_literal("false")
            value = False
        elif character == "n":
            self._consume_literal("null")
            value = None
        elif character == "-" or character.isdigit():
            value = self._parse_number()
        else:
            raise JsonIOError(self.source, "invalid JSON value")
        return value

    def _parse_object(self) -> JsonObject:
        self._expect("{")
        parsed: JsonObject = {}
        self._skip_whitespace()
        if self._consume_if("}"):
            return parsed

        while True:
            self._skip_whitespace()
            key = self._parse_string()
            self._skip_whitespace()
            self._expect(":")
            parsed[key] = self._parse_value()
            self._skip_whitespace()
            if self._consume_if("}"):
                return parsed
            self._expect(",")

    def _parse_array(self) -> JsonArray:
        self._expect("[")
        parsed: JsonArray = []
        self._skip_whitespace()
        if self._consume_if("]"):
            return parsed

        while True:
            parsed.append(self._parse_value())
            self._skip_whitespace()
            if self._consume_if("]"):
                return parsed
            self._expect(",")

    def _parse_string(self) -> str:
        self._expect('"')
        characters: list[str] = []
        while self.index < len(self.text):
            character = self.text[self.index]
            self.index += 1
            if character == '"':
                return "".join(characters)
            if character == "\\":
                characters.append(self._parse_escape())
            elif ord(character) < CONTROL_CHARACTER_LIMIT:
                raise JsonIOError(self.source, "invalid JSON string character")
            else:
                characters.append(character)
        raise JsonIOError(self.source, "unterminated JSON string")

    def _parse_escape(self) -> str:
        if self.index >= len(self.text):
            raise JsonIOError(self.source, "unterminated JSON escape")

        escape = self.text[self.index]
        self.index += 1
        parsed: str
        if escape in {'"', "\\", "/"}:
            parsed = escape
        elif escape == "b":
            parsed = "\b"
        elif escape == "f":
            parsed = "\f"
        elif escape == "n":
            parsed = "\n"
        elif escape == "r":
            parsed = "\r"
        elif escape == "t":
            parsed = "\t"
        elif escape == "u":
            parsed = self._parse_unicode_escape()
        else:
            raise JsonIOError(self.source, "invalid JSON escape")
        return parsed

    def _parse_unicode_escape(self) -> str:
        end = self.index + 4
        if end > len(self.text):
            raise JsonIOError(self.source, "unterminated JSON unicode escape")

        digits = self.text[self.index : end]
        self.index = end
        try:
            return chr(int(digits, 16))
        except ValueError as error:
            raise JsonIOError(self.source, "invalid JSON unicode escape") from error

    def _parse_number(self) -> int | float:
        start = self.index
        if self._consume_if("-") and self.index >= len(self.text):
            raise JsonIOError(self.source, "invalid JSON number")

        self._consume_integer_digits()
        is_float = False
        if self._consume_if("."):
            is_float = True
            self._consume_required_digits()
        if self._consume_if("e") or self._consume_if("E"):
            is_float = True
            _ = self._consume_if("+") or self._consume_if("-")
            self._consume_required_digits()

        number_text = self.text[start : self.index]
        try:
            if is_float:
                return float(number_text)
            return int(number_text)
        except ValueError as error:
            raise JsonIOError(self.source, "invalid JSON number") from error

    def _consume_integer_digits(self) -> None:
        if self._consume_if("0"):
            return
        self._consume_required_digits()

    def _consume_required_digits(self) -> None:
        start = self.index
        while self.index < len(self.text) and self.text[self.index].isdigit():
            self.index += 1
        if self.index == start:
            raise JsonIOError(self.source, "expected JSON number digit")

    def _consume_literal(self, literal: str) -> None:
        if self.text.startswith(literal, self.index):
            self.index += len(literal)
            return
        raise JsonIOError(self.source, "invalid JSON literal")

    def _skip_whitespace(self) -> None:
        while self.index < len(self.text) and self.text[self.index] in " \n\r\t":
            self.index += 1

    def _expect(self, expected: str) -> None:
        if self._consume_if(expected):
            return
        raise JsonIOError(self.source, "unexpected JSON token")

    def _consume_if(self, expected: str) -> bool:
        if self.text.startswith(expected, self.index):
            self.index += len(expected)
            return True
        return False


__all__ = [
    "JsonArray",
    "JsonIOError",
    "JsonObject",
    "JsonScalar",
    "JsonValue",
    "append_jsonl",
    "read_json",
    "write_json",
]
