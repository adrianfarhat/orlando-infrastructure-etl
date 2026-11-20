"""Findings: stable IDs, a fixed order, and deterministic text and JSON reports.

A finding ID is `<rule>:<10 hex chars>`, from a SHA-256 of the rule, source,
location and subject. The message text is deliberately not part of the ID, so
rewording a message never invalidates an acknowledgement. Two different problems
with the same ID are an internal error, never silently merged.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable

from . import __version__
from .config import Problem
from .paths import printable

SCHEMA_VERSION = 1
SEVERITY_ORDER = {"ERROR": 0, "WARNING": 1}


class DuplicateFindingError(RuntimeError):
    """Two different problems produced the same finding ID (a bug in a check)."""


@dataclass(frozen=True)
class Finding:
    id: str
    rule: str
    severity: str
    source: str
    location: str
    subject: str
    message: str

    def sort_key(self) -> tuple:
        return (SEVERITY_ORDER[self.severity], self.rule, self.source, self.location, self.subject, self.id)

    def as_dict(self) -> dict:
        return {"id": self.id, "rule": self.rule, "severity": self.severity, "source": self.source,
                "location": self.location, "subject": self.subject, "message": self.message}


def finding_id(rule: str, source: str, location: str, subject: str) -> str:
    key = "\0".join((rule, source, location, subject)).encode("utf-8", "surrogatepass")
    return f"{rule}:{hashlib.sha256(key).hexdigest()[:10]}"


# Backstop: no report field may grow without bound, whatever a check puts in it. Inputs
# are already limited (paths <= 4096 bytes, ids <= 100 characters, values summarised),
# so legitimate values fit; the ID is computed from the full, uncut values.
MAX_FIELD = 6000


def _cap(text: str) -> str:
    return text if len(text) <= MAX_FIELD else f"{text[:MAX_FIELD]}... ({len(text)} characters)"


def from_problems(problems: Iterable[Problem]) -> tuple[Finding, ...]:
    by_id: dict[str, Finding] = {}
    for p in problems:
        if p.severity not in SEVERITY_ORDER:
            raise ValueError(f"unknown severity {p.severity!r}")
        f = Finding(finding_id(p.rule, p.source, p.location, p.subject), p.rule, p.severity,
                    _cap(p.source), _cap(p.location), _cap(p.subject), _cap(p.message))
        if f.id in by_id and by_id[f.id] != f:
            raise DuplicateFindingError(f"finding id {f.id} produced by two different problems")
        by_id[f.id] = f
    return tuple(sorted(by_id.values(), key=Finding.sort_key))


@dataclass(frozen=True)
class Report:
    command: str
    head: str | None
    files: int
    sources: tuple[str, ...]           # configuration files read, e.g. ("impact.yml", "registry/components.yml")
    findings: tuple[Finding, ...]

    @property
    def errors(self) -> int:
        return sum(f.severity == "ERROR" for f in self.findings)

    @property
    def warnings(self) -> int:
        return sum(f.severity == "WARNING" for f in self.findings)

    @property
    def exit_code(self) -> int:
        return 1 if self.errors else 0


def render_json(report: Report) -> str:
    doc = {
        "schema_version": SCHEMA_VERSION,
        "tool": "impact",
        "version": __version__,
        "command": report.command,
        "head": report.head,
        "sources": list(report.sources),
        "summary": {"errors": report.errors, "warnings": report.warnings, "files": report.files,
                    "exit_code": report.exit_code},
        "findings": [f.as_dict() for f in report.findings],
    }
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render_text(report: Report) -> str:
    head = report.head[:7] if report.head else "no commits"
    # The source names come from configuration (the registry path): escape and bound them.
    sources = (printable(" + ".join(report.sources), 1000, double_backslash=False)
               if report.sources else "no configuration loaded")
    lines = [f"impact {report.command} | HEAD {head} | {report.files} files | {sources}"]
    for f in report.findings:
        # Names can contain control or format characters (e.g. U+202E): escape them in the
        # human-readable report. The JSON report keeps exact values for programs.
        source, location, message = (printable(x, 1000, double_backslash=False)
                                     for x in (f.source, f.location, f.message))
        lines.append(f"{f.severity:<8} {f.id}  {source}  {location}  {message}")
    lines.append(f"Summary: {report.errors} ERROR, {report.warnings} WARNING | exit code {report.exit_code}")
    return "\n".join(lines) + "\n"
