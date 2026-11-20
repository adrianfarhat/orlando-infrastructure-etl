"""The `impact check` report: text, JSON and Markdown (T-83, 83b-3).

Findings keep their severity and ID; an acknowledged WARNING is shown as acknowledged
with its reason, never removed. The change-impact section is informational: it has no
IDs, needs no acknowledgement and never affects the exit code. A doc shown as "changed"
was changed in this change set; that is not a record that it was reviewed.

All three formats are deterministic: the same repository state and acknowledgements
give byte-identical output. Repository-controlled text (file names, reasons) is escaped:
control and format characters in text and Markdown, Markdown syntax in Markdown, and
exact values in JSON.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from . import __version__
from .findings import SCHEMA_VERSION, Finding
from .paths import printable
from .rules import ImpactEntry

TEXT_LIMIT = 1000


@dataclass(frozen=True)
class CheckReport:
    head: str | None
    base_ref: str | None
    baseline: str
    sources: tuple[str, ...]
    findings: tuple[Finding, ...]
    acknowledged: dict[str, str]                 # finding id -> reason
    impact: tuple[ImpactEntry, ...]
    component_docs: dict[str, tuple[str, ...]]   # component id -> mapped docs (registry)
    unsupported: tuple[str, ...]
    references_not_scanned: tuple[tuple[str, str], ...]

    @property
    def errors(self) -> int:
        return sum(f.severity == "ERROR" for f in self.findings)

    @property
    def warnings(self) -> int:
        return sum(f.severity == "WARNING" for f in self.findings)

    @property
    def acknowledged_warnings(self) -> int:
        return sum(f.severity == "WARNING" and f.id in self.acknowledged for f in self.findings)

    @property
    def exit_code(self) -> int:
        # Acknowledgements never apply to ERRORs, so every ERROR is unacknowledged.
        return 1 if self.errors else 0


def _t(text: str) -> str:
    return printable(text, TEXT_LIMIT, double_backslash=False)


# --------------------------------------------------------------------------- JSON

def render_json(report: CheckReport) -> str:
    doc = {
        "schema_version": SCHEMA_VERSION,
        "tool": "impact",
        "version": __version__,
        "command": "check",
        "head": report.head,
        "base": report.base_ref,
        "baseline": report.baseline,
        "sources": list(report.sources),
        "summary": {"errors": report.errors, "warnings": report.warnings,
                    "acknowledged_warnings": report.acknowledged_warnings,
                    "unacknowledged_warnings": report.warnings - report.acknowledged_warnings,
                    "changes": len(report.impact), "exit_code": report.exit_code},
        "findings": [{**f.as_dict(), "acknowledged": f.id in report.acknowledged,
                      "ack_reason": report.acknowledged.get(f.id)} for f in report.findings],
        "impact": [asdict(e) for e in report.impact],
        "unsupported": list(report.unsupported),
        "references_not_scanned": [{"file": f, "reason": r} for f, r in report.references_not_scanned],
    }
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------- text

def _summary(report: CheckReport) -> str:
    acked = report.acknowledged_warnings
    return (f"Summary: {report.errors} ERROR, {report.warnings} WARNING ({acked} acknowledged, "
            f"{report.warnings - acked} unacknowledged) | exit code {report.exit_code}")


def _base(report: CheckReport) -> str:
    if report.base_ref is None:
        return "local changes"
    return f"base {_t(report.base_ref)} (merge-base {report.baseline[:7]})"


def render_text(report: CheckReport) -> str:
    head = report.head[:7] if report.head else "no commits"
    sources = _t(" + ".join(report.sources)) if report.sources else "no configuration loaded"
    lines = [f"impact check | HEAD {head} | {_base(report)} | {len(report.impact)} changes | {sources}"]
    for f in report.findings:
        state = ""
        if f.severity == "WARNING":
            state = (f"  [acknowledged: {_t(report.acknowledged[f.id])}]" if f.id in report.acknowledged
                     else "  [unacknowledged]")
        lines.append(f"{f.severity:<8} {f.id}  {_t(f.source)}  {_t(f.location)}  {_t(f.message)}{state}")
    lines.append("")
    lines.append("Change impact (informational; not findings, no acknowledgement needed):")
    if not report.impact:
        lines.append("  no changes")
    for e in report.impact:
        lines.extend("  " + x for x in _entry_lines(e))
    for name in report.unsupported:
        lines.append(f"  not analysed (unsupported name): {_t(name)}")
    for file, reason in report.references_not_scanned:
        lines.append(f"  not scanned for references: {_t(file)} ({_t(reason)})")
    lines.append("")
    lines.append(_summary(report))
    return "\n".join(lines) + "\n"


def _entry_lines(e: ImpactEntry) -> list[str]:
    name = f"{_t(e.old_path)} -> {_t(e.path)}" if e.old_path else _t(e.path)
    head = f"{e.kind} {name} [{', '.join(e.origins)}]"
    if e.ignored:
        return [f"{head}: ignored (impact.yml ignore)"]
    comps = ", ".join(e.components) or "unregistered"
    if e.old_components:
        comps += f" (was {', '.join(e.old_components)})"
    out = [f"{head}: component {comps}; purpose {e.purpose}; content {_t(e.content)}; "
           f"documentation obligation {'yes' if e.doc_obligation else 'no'}"]
    if e.docs:
        out.append("  docs: " + "; ".join(
            f"{_t(d.doc)} ({d.kind}{', changed in this change set' if d.changed else ''})" for d in e.docs))
    if e.contracts:
        out.append("  contracts: " + "; ".join(f"{_t(p)} -> {_t(c)}" for p, c in e.contracts))
    out.append("  tests: " + ("; ".join(_t(t) for t in e.tests) + f" ({e.tests_basis})" if e.tests
                              else e.tests_basis))
    if e.dependents:
        out.append("  dependents (one hop): " + "; ".join(
            f"{d.component} depends on {d.depends_on} ({d.basis}: {_t(d.detail)})" for d in e.dependents))
    if e.triggers or e.unscanned_triggers:
        out.append("  content triggers: " + "; ".join(
            [f"{t} (matched)" for t in e.triggers] + [f"{t} (not scanned)" for t in e.unscanned_triggers]))
    return out


# --------------------------------------------------------------------------- Markdown

# Characters that can start Markdown syntax inside a table cell or list item: emphasis,
# code, links and images ([ ] ! after escaping), HTML (< >), tables (|), headings (#),
# strikethrough (~) and the escape character itself. Every value is written after a fixed
# prefix ("| " or "- "), so block markers such as "-", "+" or "1." cannot start a block.
_MD_SPECIAL = "\\`*_{}[]<>#!|~"


def _md(text: str) -> str:
    """Escape for Markdown (including tables): control characters first, then syntax."""
    shown = printable(text, TEXT_LIMIT, double_backslash=False).replace("\n", " ")
    return "".join("\\" + ch if ch in _MD_SPECIAL else ch for ch in shown)


def _doc_status(report: CheckReport, cid: str, entries: list[ImpactEntry]) -> str:
    finding = next((f for f in report.findings if f.rule == "docs-not-updated" and f.subject == cid), None)
    if finding is not None:
        if finding.id in report.acknowledged:
            return f"Documentation review required: acknowledged ({_md(report.acknowledged[finding.id])})"
        return f"Documentation review required: unacknowledged (`{finding.id}`)"
    if not report.component_docs.get(cid):
        return "No documentation obligation (`docs: []`)"
    if not any(e.doc_obligation for e in entries):
        return "No documentation obligation (test, generated or experimental files, or no content change)"
    if any(d.changed for e in entries for d in e.docs if d.doc in report.component_docs[cid]):
        return "A mapped doc changed in this change set (not a record of review)"
    return "Documentation obligation; the docs-not-updated rule is off"


def render_markdown(report: CheckReport) -> str:
    acked = report.acknowledged_warnings
    out = ["## Documentation impact", "",
           f"`impact check`: {_md(_base(report))}; {len(report.impact)} changes; "
           f"{report.errors} ERROR, {report.warnings} WARNING ({acked} acknowledged, "
           f"{report.warnings - acked} unacknowledged); exit code {report.exit_code}.", ""]
    by_component: dict[str, list[ImpactEntry]] = {}
    for e in report.impact:
        if not e.ignored:
            for cid in sorted(set(e.components + e.old_components)):
                by_component.setdefault(cid, []).append(e)
    if by_component:
        out += ["| Component | Documentation | Changed in this change set | Status |", "|---|---|---|---|"]
        for cid in sorted(by_component):
            entries = by_component[cid]
            docs = report.component_docs.get(cid, ())
            changed = {d.doc for e in entries for d in e.docs if d.changed}
            listed = "<br>".join(_md(d) for d in docs) or "none"
            flags = "<br>".join("yes" if d in changed else "no" for d in docs) or "-"
            out.append(f"| {_md(cid)} | {listed} | {flags} | {_doc_status(report, cid, entries)} |")
        out.append("")
    else:
        out += ["No registered component changed.", ""]

    out += ["### Findings", ""]
    if report.findings:
        out += ["| Severity | ID | Rule | File | Message | Acknowledgement |", "|---|---|---|---|---|---|"]
        for f in report.findings:
            ack = ("n/a (ERRORs cannot be acknowledged)" if f.severity == "ERROR" else
                   f"acknowledged: {_md(report.acknowledged[f.id])}" if f.id in report.acknowledged
                   else "unacknowledged")
            out.append(f"| {f.severity} | `{f.id}` | {_md(f.rule)} | {_md(f.source)} | {_md(f.message)} | {ack} |")
    else:
        out.append("None.")
    out.append("")

    out += ["### Change impact (informational)", ""]
    if not report.impact:
        out.append("No changes.")
    for e in report.impact:
        first, *rest = _entry_lines(e)
        out.append(f"- {_md(first)}")
        out.extend(f"  - {_md(x.strip())}" for x in rest)
    for name in report.unsupported:
        out.append(f"- not analysed (unsupported name): {_md(name)}")
    for file, reason in report.references_not_scanned:
        out.append(f"- not scanned for references: {_md(file)} ({_md(reason)})")
    out.append("")
    return "\n".join(out)
