"""Acknowledgements: `- ack <finding-id>: <reason>` lines, checked mechanically (T-83, 83b-3).

An acknowledgement records a decision about a WARNING ("reviewed; no change needed
because ..."). It never removes a finding or changes its severity: the finding is
reported as acknowledged, with the reason. Acknowledgements apply to WARNINGs only; an
acknowledgement naming an ERROR is reported and the ERROR still counts (exit code 1).

Only lines that start with "- ack" are acknowledgement lines (other text, such as the
rest of a PR description, is ignored). Each problem with an acknowledgement is an
`ack-problem` WARNING (configurable: WARNING or off in impact.yml); a problematic
acknowledgement is not applied:
- malformed: the line starts with "- ack" but is not "- ack <rule>:<10 hex>: <reason>";
- unknown: no current finding has that ID (stale, mistyped, or an ack-problem itself);
- ERROR: the finding is an ERROR;
- reason: empty, a placeholder from impact.yml `acks.placeholders` (compared without
  case and trailing "." or "!"), or shorter than `acks.min_reason_length` characters;
- duplicate: the same ID acknowledged more than once (the first valid one is used).
The tool cannot judge whether a reason is true; it only checks its form.

ack-problem IDs come from the problem kind and the acknowledged ID or line text, never
from line numbers, so they stay stable when lines move.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .config import Config, Problem
from .findings import Finding

SOURCE = "acknowledgements"
MAX_ACK_BYTES = 1_000_000
MAX_SHOWN_LINES = 10

_ACK_START = re.compile(r"[ \t]*-[ \t]+ack(?:[ \t]|\Z)")
_ACK = re.compile(r"[ \t]*-[ \t]+ack[ \t]+(?P<id>[a-z0-9]+(?:-[a-z0-9]+)*:[0-9a-f]{10})[ \t]*:(?P<reason>.*)\Z")


class AckFileError(Exception):
    """The acknowledgement file is unusable (too large, not UTF-8): exit code 2."""


@dataclass(frozen=True)
class Ack:
    id: str
    reason: str
    line: int


@dataclass(frozen=True)
class Parsed:
    acks: tuple[Ack, ...]
    malformed: tuple[tuple[int, str], ...]      # (line number, line text)


@dataclass(frozen=True)
class Applied:
    acknowledged: dict[str, str]                # finding id -> reason
    problems: tuple[Problem, ...]               # ack-problem WARNINGs (empty when the rule is off)


def decode(data: bytes) -> str:
    if len(data) > MAX_ACK_BYTES:
        raise AckFileError(f"the acknowledgement file is larger than {MAX_ACK_BYTES} bytes")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise AckFileError("the acknowledgement file is not valid UTF-8") from None
    return text[1:] if text.startswith("﻿") else text


def parse(text: str) -> Parsed:
    acks, malformed = [], []
    for number, line in enumerate(text.splitlines(), start=1):
        if not _ACK_START.match(line):
            continue
        m = _ACK.match(line)
        if m:
            acks.append(Ack(m.group("id"), m.group("reason").strip(), number))
        else:
            malformed.append((number, line.strip()))
    return Parsed(tuple(acks), tuple(malformed))


def reason_problem(reason: str, config: Config) -> str | None:
    if not reason:
        return "the reason is empty"
    if reason.casefold().rstrip(".! \t") in {p.casefold() for p in config.ack_placeholders}:
        return f"the reason is a placeholder ({reason!r})"
    if len(reason) < config.ack_min_reason_length:
        return f"the reason is too short ({len(reason)} < {config.ack_min_reason_length} characters)"
    return None


def apply(findings: Iterable[Finding], parsed: Parsed, config: Config) -> Applied:
    by_id = {f.id: f for f in findings}
    acknowledged: dict[str, str] = {}
    issues: dict[str, tuple[str, list[int]]] = {}      # subject -> (message, line numbers)

    def issue(subject: str, message: str, line: int) -> None:
        issues.setdefault(subject, (message, []))[1].append(line)

    for number, text in parsed.malformed:
        issue(f"malformed: {text}", "not an acknowledgement of the form `- ack <finding-id>: <reason>`; "
                                     "ignored", number)
    seen: dict[str, int] = {}
    for ack in parsed.acks:
        seen[ack.id] = seen.get(ack.id, 0) + 1
        if seen[ack.id] > 1:
            issue(f"duplicate: {ack.id}", f"{ack.id} is acknowledged more than once; the first valid "
                                          "acknowledgement is used", ack.line)
        finding = by_id.get(ack.id)
        if finding is None:
            issue(f"unknown: {ack.id}", f"no current finding has the ID {ack.id} (stale or mistyped); ignored",
                  ack.line)
            continue
        if finding.severity == "ERROR":
            issue(f"error: {ack.id}", f"{ack.id} is an ERROR; acknowledgements apply to WARNINGs only, so "
                                      "the ERROR still counts", ack.line)
            continue
        bad = reason_problem(ack.reason, config)
        if bad:
            issue(f"reason: {ack.id}", f"{bad}; {ack.id} stays unacknowledged", ack.line)
            continue
        acknowledged.setdefault(ack.id, ack.reason)

    problems: list[Problem] = []
    if config.rules.get("ack-problem", "WARNING") != "off":
        for subject, (message, lines) in issues.items():
            shown = ", ".join(map(str, lines[:MAX_SHOWN_LINES]))
            more = f" (+{len(lines) - MAX_SHOWN_LINES} more)" if len(lines) > MAX_SHOWN_LINES else ""
            problems.append(Problem(SOURCE, "ack", subject, "ack-problem", "WARNING",
                                    f"{message} (line {shown}{more})"))
    return Applied(acknowledged, tuple(sorted(problems)))
