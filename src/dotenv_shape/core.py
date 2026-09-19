"""Conservative dotenv parsing; result objects contain shape metadata only."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z", re.ASCII)
_SPACE = " \t"
_ESCAPES = frozenset('\\"nrt$')


@dataclass(frozen=True)
class Entry:
    """A valid assignment's name, physical line, and empty-value flag."""

    key: str
    line: int
    empty: bool


@dataclass(frozen=True)
class Finding:
    """A diagnostic that never stores configuration values or source lines."""

    kind: str
    file: str
    key: str | None = None
    line: int | None = None
    first_line: int | None = None

    def to_dict(self) -> dict[str, str | int]:
        result: dict[str, str | int] = {"kind": self.kind, "file": self.file}
        if self.key is not None:
            result["key"] = self.key
        if self.line is not None:
            result["line"] = self.line
        if self.first_line is not None:
            result["first_line"] = self.first_line
        return result


@dataclass(frozen=True)
class ParsedDocument:
    """Unique valid assignments and parse findings; first valid assignment wins."""

    entries: tuple[Entry, ...]
    findings: tuple[Finding, ...]


@dataclass(frozen=True)
class CheckResult:
    findings: tuple[Finding, ...]

    @property
    def ok(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict[str, object]:
        return {"ok": self.ok, "findings": [item.to_dict() for item in self.findings]}


def _value_is_empty(raw: str) -> bool | None:
    """Return emptiness, or None for malformed syntax. Never return the value."""
    raw = raw.lstrip(_SPACE)
    if not raw:
        return True
    if "\r" in raw or "\x00" in raw:
        return None
    quote = raw[0]
    if quote in "\"'":
        index = 1
        while index < len(raw):
            char = raw[index]
            if char == quote:
                tail = raw[index + 1:]
                if tail and tail[0] not in _SPACE:
                    return None
                tail = tail.lstrip(_SPACE)
                if tail and not tail.startswith("#"):
                    return None
                return index == 1
            if quote == '"' and char == "\\":
                index += 1
                if index == len(raw) or raw[index] not in _ESCAPES:
                    return None
            index += 1
        return None
    end = len(raw)
    for index, char in enumerate(raw):
        if char == "#" and (index == 0 or raw[index - 1] in _SPACE):
            end = index
            break
        if char in "\"'":
            return None
    return not raw[:end].rstrip(_SPACE)


def _parse_text(text: str, file_id: str) -> ParsedDocument:
    if not isinstance(text, str):
        raise TypeError("dotenv input must be text")
    if text.startswith("\ufeff"):
        text = text[1:]
    entries: dict[str, Entry] = {}
    findings: list[Finding] = []
    lines = text.split("\n")
    for line_number, source in enumerate(lines, 1):
        if source.endswith("\r") and line_number < len(lines):
            source = source[:-1]
        source = source.strip(_SPACE)
        if not source or source.startswith("#"):
            continue
        if source.startswith("export") and len(source) > 6 and source[6] in _SPACE:
            source = source[6:].lstrip(_SPACE)
        candidate, separator, raw_value = source.partition("=")
        key = candidate.rstrip(_SPACE)
        if not separator or not _KEY.fullmatch(key):
            findings.append(Finding("malformed_entry", file_id, line=line_number))
            continue
        empty = _value_is_empty(raw_value)
        if empty is None:
            findings.append(Finding("malformed_entry", file_id, key=key, line=line_number))
            continue
        if key in entries:
            findings.append(Finding("duplicate_key", file_id, key, line_number, entries[key].line))
        else:
            entries[key] = Entry(key, line_number, empty)
    return ParsedDocument(tuple(entries.values()), tuple(findings))


def parse_text(text: str) -> ParsedDocument:
    """Parse one document using the fixed file identifier ``document``.

    Values are inspected only for syntax and emptiness. They are absent from
    return objects and diagnostic messages. No interpolation is performed.
    """
    return _parse_text(text, "document")


def check_texts(
    example: str,
    targets: Sequence[str],
    *,
    strict_extra: bool = False,
    require_nonempty: bool = False,
) -> CheckResult:
    """Compare valid target keys with the example's valid keys.

    Identifiers are ``example`` and ``target:1``, ``target:2``, and so on.
    At least one target is required. Duplicate/malformed entries are findings
    in either kind of file. Missing and extra keys are sorted by name.
    """
    if type(strict_extra) is not bool or type(require_nonempty) is not bool:
        raise TypeError("comparison options must be booleans")
    if isinstance(targets, (str, bytes)) or not isinstance(targets, Sequence):
        raise TypeError("targets must be a sequence of text documents")
    if not targets:
        raise ValueError("at least one target document is required")
    reference = _parse_text(example, "example")
    expected = {entry.key for entry in reference.entries}
    findings = list(reference.findings)
    for index, text in enumerate(targets, 1):
        file_id = f"target:{index}"
        parsed = _parse_text(text, file_id)
        entries = {entry.key: entry for entry in parsed.entries}
        findings.extend(parsed.findings)
        for key in sorted(expected - entries.keys()):
            findings.append(Finding("missing_key", file_id, key))
        if strict_extra:
            for key in sorted(entries.keys() - expected):
                findings.append(Finding("extra_key", file_id, key, entries[key].line))
        if require_nonempty:
            for key in sorted(expected & entries.keys()):
                entry = entries[key]
                if entry.empty:
                    findings.append(Finding("empty_required_value", file_id, key, entry.line))
    return CheckResult(tuple(findings))
