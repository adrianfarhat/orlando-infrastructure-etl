"""Generated copies of architecture diagrams in docs/architecture/ documents (T-97 M1).

After stage M1 an architecture diagram's authoritative source is a standalone file in
docs/architecture/diagrams/ (registry format `mermaid-md`, owned by its document), and the
document shows a generated copy of it (diagram library U3, section 6.6):

    <!-- diagram:start AD-0013 sha256:<16 hex> -->
    <!-- generated copy of AD-0013 from diagrams/<file>.md: edit the source, not this copy -->
    ```mermaid
    <the source's Mermaid lines, verbatim: blank lines are kept, never written as %%>
    ```
    <!-- diagram:end -->

The fingerprint (U13) covers the comment line, the fence and the Mermaid lines (not the
markers). No caption: the legend paragraph above stays hand-written, outside the region.

The tooling never writes docs/architecture/ (diagram library 5.2; the write guard,
ownership.guard_write, stays exactly as strict). Nothing in this module writes a file. A copy
that is out of date or edited is *reported* by `check` and `index --check`, and technical-lead
applies the exact text printed by `python -m tools.design architecture copy` in its
documentation workflow (decision C1: U5 refresh is report-and-apply for docs/architecture/).

`snapshot` records the pre-migration state once (read only); `verify` proves every M1 state
against it (V1-V7 of the M1 execution specification, section 4.6). Byte identity is defined on
LF content, which is what Git stores (the Windows working tree may be CRLF).
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path

from .diagrams import END, END_RE, LIKE_MARKER, START, Block, _closes, _fence, _fence_for, classify, start_marker
from .workspace import ARCHITECTURE, DesignError, Problem

SNAPSHOT_VERSION = 1
COMMENT = re.compile(r"<!-- generated copy of (?P<id>\S+) from (?P<path>\S+): edit the source, not this copy -->\Z")
# The approved source file names (diagram library 12.3; confirmed for M1 in designs/DECISIONS.md, Q1).
# `verify` checks an extracted diagram's path against this list; the tooling never derives names.
M1_SOURCES = {
    "AD-0001": "conventions_legend_implementation-status.md",
    "AD-0002": "database-schema_data-model_current-model.md",
    "AD-0003": "database-schema_data-model_target-model.md",
    "AD-0004": "database-schema_process_team-workflow.md",
    "AD-0005": "etl-workflow_process_common-pattern.md",
    "AD-0006": "etl-workflow_process_streets-road-segments.md",
    "AD-0007": "etl-workflow_process_wastewater-utility-lines.md",
    "AD-0008": "etl-workflow_process_manholes.md",
    "AD-0009": "etl-workflow_process_safety-gates.md",
    "AD-0010": "system-architecture_system-architecture_current-state.md",
    "AD-0011": "system-architecture_system-architecture_credential-boundary.md",
    "AD-0012": "system-architecture_system-architecture_inside-the-web-app.md",
    "AD-0013": "system-architecture_sequence_one-map-pan.md",
    "AD-0014": "system-architecture_system-architecture_target-state.md",
}
DOCUMENT_SOURCES = ARCHITECTURE + "/diagrams"
COPY_COMMAND = "python -m tools.design architecture copy"


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- scanning

def scan(text: str) -> tuple[list[Block], list[tuple[int, str]]]:
    """The generated regions of an architecture document and its structural problems
    (1-based line, message). Markers count only on a line of their own, outside fenced code
    (examples in code blocks are ignored) and outside code spans; inside a region its own
    Mermaid fence is tracked, as in diagrams.scan. There is no six-section rule and there
    are no summary blocks in these documents."""
    lines = _lf(text).split("\n")
    blocks, problems = [], []
    fence = block = inner = None
    for i, raw in enumerate(lines):
        s = raw.strip()
        if block is not None:
            if inner is not None:
                if _closes(raw, inner):
                    inner = None
                elif END_RE.match(s):
                    problems.append((i + 1, f"the Mermaid fence of the generated copy of {block[1] or '(no ID)'} "
                                            f"(line {block[0] + 1}) is not closed before {END}: technical-lead replaces "
                                            f"the region with the output of `{COPY_COMMAND} {block[1] or '<ID>'}`"))
                    blocks.append(Block(block[0], i, block[1], block[2]))
                    block = inner = None
                continue
            f = _fence(raw)
            if f and not (f[0] == "`" and "`" in f[2]):
                inner = f
            elif END_RE.match(s):
                blocks.append(Block(block[0], i, block[1], block[2]))
                block = None
            elif START.match(s):
                problems.append((i + 1, f"diagram:start inside the generated copy that starts on line {block[0] + 1}: "
                                        f"regions cannot be nested (add the missing {END})"))
            elif LIKE_MARKER.match(s):
                problems.append((i + 1, f"malformed diagram marker {s!r}: a generated copy is "
                                        f"<!-- diagram:start <ID> sha256:<fingerprint> --> ... {END}"))
            continue
        if fence is not None:
            if _closes(raw, fence):
                fence = None
            continue
        f = _fence(raw)
        if f and not (f[0] == "`" and "`" in f[2]):
            fence = f
            continue
        m = START.match(s)
        if m:
            if not m.group("id"):
                problems.append((i + 1, "diagram:start has no diagram ID: a generated copy names its registry ID"))
            block = (i, m.group("id") or "", m.group("fp"))
        elif END_RE.match(s):
            problems.append((i + 1, f"{END} without a matching <!-- diagram:start <ID> -->"))
        elif LIKE_MARKER.match(s):
            problems.append((i + 1, f"malformed diagram marker {s!r}: a generated copy is "
                                    f"<!-- diagram:start <ID> sha256:<fingerprint> --> ... {END}"))
        elif LIKE_MARKER.search(re.sub(r"(`+).+?\1", "", s)):
            problems.append((i + 1, "a diagram marker must stand alone on its own line (not in a list item, quote "
                                    "or sentence); write examples in a code block or code span"))
    if block is not None:
        problems.append((block[0] + 1, f"diagram:start {block[1] or '(no ID)'} has no matching {END}"))
    return blocks, problems


def spans(text: str) -> list[tuple[int, int]]:
    """0-based (start, end) marker lines of the well-formed generated regions."""
    return [(b.start, b.end) for b in scan(text)[0]]


# --------------------------------------------------------------------------- sources and rendering

@dataclass(frozen=True)
class Expected:
    """What a region for one registry entry must hold, or why none can be generated."""
    entry: object                  # registry.Entry
    source: object                 # diagrams.Source ('' problem when usable)
    lines: tuple[str, ...] = ()    # the generated lines (comment, fence, Mermaid, fence)
    problem: str = ""


def _source_fences(root: Path, source) -> tuple[str, str]:
    """The opening and closing fence lines of a standalone source, as written (LF)."""
    try:
        lines = _lf((Path(root) / source.path).read_bytes().decode("utf-8")).split("\n")
        return lines[source.line - 1], lines[source.line + len(source.lines)]
    except (OSError, UnicodeDecodeError, IndexError):
        return "", ""


def render(entry, source, document: str, fences: tuple[str, str] | None = None) -> list[str]:
    """The generated lines of the copy of `entry` (from `source`) in `document` (section 3.1):
    the comment line naming the ID and the source, then the Mermaid lines in a fence. Raises
    DesignError rather than write a fence that differs from the source's own (`fences`)."""
    rel = posixpath.relpath(source.path, posixpath.dirname(document))
    if "--" in rel or rel.endswith("-") or re.search(r"[\s>]", rel):
        raise DesignError(f"the source path {rel} cannot be written in an HTML comment (no '--', '>' or spaces)")
    fence = _fence_for(source.lines)
    if fences is not None and (fences[0] != fence + "mermaid" or fences[1] != fence):
        raise DesignError(f"the generated fence {fence + 'mermaid'!r} would differ from the source's fence "
                          f"{fences[0]!r} in {source.path}: make the source's fence exactly {fence + 'mermaid'!r} "
                          f"and {fence!r}")
    return [f"<!-- generated copy of {entry.diagram_id} from {rel}: edit the source, not this copy -->",
            fence + "mermaid", *source.lines, fence]


def expected(root: Path, entry, document: str | None = None) -> Expected:
    """The copy an active document-owned `mermaid-md` entry generates in `document` (default:
    its owner), or the reason it cannot be generated."""
    from . import diagrams
    document = document or entry.owner_ref
    if entry.status == "retired":
        return Expected(entry, None, problem=f"was retired on {entry.retired} (E11): technical-lead removes this copy")
    if entry.owner_kind != "document":
        return Expected(entry, None, problem=f"is owned by feature {entry.owner_ref}: current-state documents show only "
                                             "document-owned diagrams; technical-lead removes this copy (Q5)")
    if entry.format != "mermaid-md":
        return Expected(entry, None, problem=f"is still embedded in {entry.path} ({entry.format}): a generated copy "
                                             "needs a standalone source in docs/architecture/diagrams/; finish its "
                                             "extraction (`python -m tools.design registry extract`) or remove this copy")
    source = diagrams._refuse_markers(diagrams._registered_source(root, entry))
    if source.problem:
        return Expected(entry, source, problem=source.problem)
    if not source.closed:
        return Expected(entry, source, problem=f"has a source {source.path} whose Mermaid block has no closing fence")
    try:
        lines = render(entry, source, document, _source_fences(root, source))
    except DesignError as exc:
        return Expected(entry, source, problem=str(exc))
    return Expected(entry, source, tuple(lines))


# --------------------------------------------------------------------------- check

def _documents(root: Path):
    from .architecture import documents
    return [d for d in documents(root) if d.parsed is not None]


def _classified(root: Path) -> list[tuple[Problem, str]]:
    """(problem, kind) for every architecture document: "block" (structure, unusable IDs),
    "regen" (technical-lead applies the printed copy) or "conflict" (E15)."""
    from . import registry
    lookup = registry.load(root).lookup()
    out: list[tuple[Problem, str]] = []
    for doc in _documents(root):
        if "diagram:" not in doc.text:
            continue
        blocks, structural = scan(doc.text)
        out += [(Problem(doc.path, f"line {n}: {msg}"), "block") for n, msg in structural]
        lines = _lf(doc.text).split("\n")
        for b in blocks:
            out += _region_problems(root, doc.path, lines, b, lookup)
    return out


def _region_problems(root: Path, rel: str, lines: list[str], b: Block, lookup) -> list[tuple[Problem, str]]:
    at = f"line {b.start + 1}: the generated copy of {b.diagram_id or '(no ID)'}"
    if not b.diagram_id:
        return []                                      # reported by scan
    e = lookup.get(b.diagram_id)
    if e is None:
        return [(Problem(rel, f"line {b.start + 1}: unknown diagram ID {b.diagram_id!r} in a generated copy (E1)"),
                 "block")]
    exp = expected(root, e, rel)
    if exp.problem:
        return [(Problem(rel, f"{at}: {e.diagram_id} {exp.problem}"), "block")]
    current = lines[b.start + 1:b.end]
    state = classify(b, current, list(exp.lines))
    if state == "current":
        return []
    span = f"lines {b.start + 1}-{b.end + 1}"
    fix = f"`{COPY_COMMAND} {e.diagram_id}`"
    src = exp.source.path
    moved = ""
    m = COMMENT.match(current[0]) if current else None
    want = COMMENT.match(exp.lines[0])
    if m and want and m.group("path") != want.group("path"):
        moved = (f" (it names its source as {m.group('path')}, but the registry's source of {e.diagram_id} is "
                 f"{want.group('path')}, E14)")
    if state == "empty":
        return [(Problem(rel, f"{at} is empty: technical-lead replaces {span} with the output of {fix}"), "regen")]
    if state == "case1":
        return [(Problem(rel, f"{at} is out of date with its source {src} (not edited since it was generated){moved}: "
                              f"technical-lead replaces {span} with the output of {fix}"), "regen")]
    if state == "fp-only":
        return [(Problem(rel, f"{at} matches its source, but its fingerprint is "
                              f"{'missing' if b.fp is None else 'out of date'}: technical-lead replaces the start "
                              f"marker on line {b.start + 1} with the one printed by {fix} (only the marker changes)"),
                 "regen")]
    workflow = (f"resolve it in technical-lead's documentation workflow: replace {span} with the output of {fix} "
                f"(discard the edit) or make the edit in the source {src} (apply to source)")
    if state == "case2":
        msg = f"{at} was edited by hand (its source {src} is unchanged){moved}, so it is never overwritten (E15): {workflow}"
    elif state == "case3":
        msg = (f"{at} and its source {src} have both changed since the copy was generated{moved}, so it is never "
               f"overwritten (E15): {workflow}")
    else:
        msg = (f"{at} has no fingerprint and differs from its source {src}{moved}; whether it was edited by hand cannot "
               f"be established, so it is never overwritten (E15): {workflow}")
    return [(Problem(rel, msg), "conflict")]


def problems(root: Path) -> list[Problem]:
    """Every generated-copy problem in docs/architecture/ (for `check`)."""
    return [p for p, _ in _classified(Path(root))]


def stale(root: Path) -> list[Problem]:
    """The copies technical-lead must apply or resolve (for `index --check` and `index`)."""
    return [p for p, kind in _classified(Path(root)) if kind in ("regen", "conflict")]


def regions(root: Path) -> dict[str, list[tuple[str, Block]]]:
    """Well-formed regions by the ID or alias they name: [(document, block), ...]."""
    out: dict[str, list[tuple[str, Block]]] = {}
    for doc in _documents(root):
        if "diagram:" in doc.text:
            for b in scan(doc.text)[0]:
                out.setdefault(b.diagram_id, []).append((doc.path, b))
    return out


# --------------------------------------------------------------------------- the printed copy (section 3.3)

def _new_region(entry, lines) -> list[str]:
    return [start_marker(entry.diagram_id, lines), *lines, END]


def apply_copies(text: str, replacements: list[dict]) -> str:
    """The LF text after the replacements of one document (what technical-lead's edits give).
    Pure: nothing is written."""
    lines = _lf(text).split("\n")
    for r in sorted((r for r in replacements if r.get("start_line")), key=lambda r: r["start_line"], reverse=True):
        lines[r["start_line"] - 1:r["end_line"]] = r["new_lines"]
    return "\n".join(lines)


def plan_copies(root: Path, ids: list[str] | None = None, document: str | None = None) -> dict:
    """What technical-lead replaces, per document, to show the current copy of each named
    diagram (or every extracted diagram of `document`): the 1-based line range, the exact old
    text and its SHA-256, the exact new lines, and the document's LF SHA-256 after all of them.
    Read only."""
    from . import registry
    from .architecture import catalog, documents
    root = Path(root)
    reg = registry.load(root)
    lookup = reg.lookup()
    if bool(ids) == bool(document):
        raise DesignError("give diagram IDs or --document, not both")
    targets, refused = [], []
    if document:
        document = posixpath.normpath(document.replace("\\", "/"))
        if not document.startswith(ARCHITECTURE + "/"):
            document = posixpath.join(ARCHITECTURE, document)
        targets = [e for e in reg.entries if e.status == "active" and e.owner_kind == "document"
                   and e.format == "mermaid-md" and e.owner_ref == document]
        if not targets:
            raise DesignError(f"{document} has no extracted (mermaid-md) diagram; nothing to print")
    else:
        for ident in ids:
            e = lookup.get(ident)
            if e is None:
                refused.append(f"{ident} is not in the registry as an ID or an alias (E1)")
            elif e.owner_kind != "document" or e.format != "mermaid-md" or e.status != "active":
                refused.append(f"{ident}: {expected(root, e).problem or 'has no standalone document-owned source'}")
            elif e not in targets:
                targets.append(e)
        if refused:
            raise DesignError("nothing to print: " + "; ".join(refused))
    docs = {d.path: d for d in documents(root) if d.parsed is not None}
    cat = catalog(list(docs.values()))
    found = regions(root)
    by_doc: dict[str, dict] = {}
    for e in targets:
        doc = docs.get(e.owner_ref)
        if doc is None:
            raise DesignError(f"{e.diagram_id}: its owning document {e.owner_ref} cannot be read")
        exp = expected(root, e)
        if exp.problem:
            raise DesignError(f"{e.diagram_id} {exp.problem}; nothing to print")
        lines = _lf(doc.text).split("\n")
        item = by_doc.setdefault(e.owner_ref, {"path": e.owner_ref, "sha256_before": _sha(_lf(doc.text)),
                                               "replacements": [], "current": [], "not_shown": []})
        new = _new_region(e, exp.lines)
        names = {e.diagram_id, *e.aliases}
        own = [b for n in names for p, b in found.get(n, []) if p == e.owner_ref]
        raw = [d for d in cat if d.document == e.owner_ref and d.diagram_id in e.aliases]
        for d in raw:
            if not d.closed:
                raise DesignError(f"{e.diagram_id}: the raw block on line {d.line} of {e.owner_ref} has no closing fence")
            start, end = d.line, d.line + len(d.source) + 1
            if own:
                item["replacements"].append(_replacement(e, lines, start, end, [], "raw-block (delete: the document "
                                                         "already shows the generated copy)"))
            else:
                item["replacements"].append(_replacement(e, lines, start, end, new, "raw-block"))
        for b in own:
            state = classify(b, lines[b.start + 1:b.end], list(exp.lines))
            if state == "current" and b.diagram_id == e.diagram_id:
                item["current"].append(e.diagram_id)
            else:
                item["replacements"].append(_replacement(e, lines, b.start + 1, b.end + 1, new, f"region ({state})"))
        if not raw and not own:
            item["not_shown"].append({"diagram_id": e.diagram_id, "new_lines": new, "new_text": "\n".join(new)})
    for item in by_doc.values():
        reps = sorted(item["replacements"], key=lambda r: r["start_line"])
        for a, b in zip(reps, reps[1:]):
            if b["start_line"] <= a["end_line"]:
                raise DesignError(f"{item['path']}: the replacements for {a['diagram_id']} and {b['diagram_id']} overlap")
        item["replacements"] = reps
        item["sha256_after"] = _sha(apply_copies(docs[item["path"]].text, reps))
    return {"version": 1, "documents": [by_doc[k] for k in sorted(by_doc)]}


def _replacement(e, lines: list[str], start: int, end: int, new: list[str], kind: str) -> dict:
    old = "\n".join(lines[start - 1:end])
    whole = "\n".join(lines)
    return {"diagram_id": e.diagram_id, "kind": kind, "start_line": start, "end_line": end, "old_text": old,
            "old_sha256": _sha(old), "old_unique": whole.count(old) == 1, "new_lines": new, "new_text": "\n".join(new)}


# --------------------------------------------------------------------------- snapshot (section 4.6)

def snapshot(root: Path) -> dict:
    """The pre-migration record (JSON, version 1): every architecture document's LF text and
    SHA-256, and every document-owned diagram with its registry fields and exact Mermaid
    lines. Refused unless every active document-owned diagram is still embedded and found:
    it records the state before M1. Read only (the caller writes it outside docs/architecture/)."""
    from . import registry
    from .architecture import catalog, documents
    from .ids import _git
    root = Path(root)
    reg = registry.load(root)
    bad = reg.problems + registry.identity_problems(reg)
    if bad:
        raise DesignError("the registry has problems; fix them first: " + "; ".join(p.message for p in bad[:3]))
    docs = documents(root)
    unreadable = [d.path for d in docs if d.parsed is None]
    if unreadable:
        raise DesignError(f"cannot read {', '.join(unreadable)}")
    raw_items = {item.get("diagram_id"): item for item in (reg.data or {}).get("diagrams") or [] if isinstance(item, dict)}
    cat = catalog(docs)
    texts = {d.path: _lf(d.text) for d in docs}
    diagrams_out = []
    for e in reg.entries:
        if e.owner_kind != "document" or e.status != "active":
            continue
        if e.format != "mermaid-embedded":
            raise DesignError(f"{e.diagram_id} is already {e.format}: the snapshot records the state before M1")
        located, _ = registry.locate_embedded(root, e)
        if located is None or not located.closed:
            raise DesignError(f"{e.diagram_id} cannot be found in {e.path} (see `python -m tools.design check`)")
        lines = texts[e.path].split("\n")
        first = located.line
        cf = raw_items.get(e.diagram_id, {}).get("created_from")
        diagrams_out.append({
            "diagram_id": e.diagram_id, "aliases": list(e.aliases), "title": e.title, "category": e.category,
            "owner": {"kind": e.owner_kind, "ref": e.owner_ref}, "format": e.format, "anchor": e.anchor,
            "ordinal": e.ordinal, "status": e.status, "created": e.created,
            "created_from": json.loads(json.dumps(cf, default=str)) if cf is not None else None,
            "document": e.path, "heading_anchor": located.heading.anchor if located.heading is not None else "",
            "opening_line": first, "opening_fence": lines[first - 1], "closing_fence": lines[first + len(located.source)],
            "mermaid_lines": list(located.source), "mermaid_sha256": _sha("\n".join(located.source)),
            "blank_lines": [first + 1 + i for i, x in enumerate(located.source) if not x.strip()],
            "diagram_type": located.diagram_type})
    unregistered = [d.diagram_id for d in cat if not any(d.diagram_id in x["aliases"] for x in diagrams_out)]
    if unregistered:
        raise DesignError(f"architecture diagrams not registered: {', '.join(unregistered)} (run registry "
                          "adopt-architecture first)")
    head = _git(root, "rev-parse", "HEAD")
    commit = head.stdout.decode("ascii", "replace").strip() if head.returncode == 0 else None
    return {"version": SNAPSHOT_VERSION, "tool": "python -m tools.design architecture snapshot", "commit": commit,
            "byte_identity": "LF-normalised content (equal to the Git blob)",
            "documents": {p: {"sha256": _sha(t), "text": t} for p, t in sorted(texts.items())},
            "diagrams": diagrams_out}


def read_snapshot(path: Path) -> tuple[dict, str]:
    """(snapshot, SHA-256 of its file); DesignError when it cannot be used."""
    try:
        data = Path(path).read_bytes()
        snap = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise DesignError(f"the snapshot {path} cannot be read ({type(exc).__name__})") from None
    if not isinstance(snap, dict) or snap.get("version") != SNAPSHOT_VERSION or not isinstance(snap.get("diagrams"), list) \
            or not isinstance(snap.get("documents"), dict):
        raise DesignError(f"{path} is not an architecture snapshot (version {SNAPSHOT_VERSION})")
    for rel, doc in snap["documents"].items():
        if not isinstance(doc, dict) or _sha(doc.get("text", "")) != doc.get("sha256"):
            raise DesignError(f"the snapshot {path} is damaged: the text of {rel} does not match its SHA-256")
    for d in snap["diagrams"]:
        if not isinstance(d, dict) or _sha("\n".join(d.get("mermaid_lines", []))) != d.get("mermaid_sha256"):
            raise DesignError(f"the snapshot {path} is damaged: the Mermaid lines of "
                              f"{d.get('diagram_id') if isinstance(d, dict) else '?'} do not match their SHA-256")
    return snap, hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- verify (V1-V7)

def strip_regions(text: str) -> tuple[str, list[str]]:
    """The LF text with each region's start marker, generated comment and end marker removed
    (the V4 invariant gives the pre-M1 document), and the problems found doing so."""
    lines = _lf(text).split("\n")
    blocks, structural = scan(text)
    problems = [f"line {n}: {msg}" for n, msg in structural]
    drop = set()
    for b in blocks:
        drop.update((b.start, b.end))
        if b.start + 1 < b.end and COMMENT.match(lines[b.start + 1]):
            drop.add(b.start + 1)
        else:
            problems.append(f"line {b.start + 2}: the region of {b.diagram_id} does not start with the generated comment")
    return "\n".join(x for i, x in enumerate(lines) if i not in drop), problems


def verify(root: Path, snapshot_path: Path) -> dict:
    """Prove the current state against the snapshot (section 4.6). Read only."""
    from . import diagrams, registry
    from .architecture import architecture_diagrams, documents, render_architecture_index
    from .markdown import parse
    from .workspace import _yaml, split_front_matter
    root = Path(root)
    snap, snap_sha = read_snapshot(snapshot_path)
    found: list[dict] = []

    def fail(check, message):
        found.append({"check": check, "message": message})

    reg = registry.load(root)
    for p in reg.problems + registry.identity_problems(reg):
        fail("V1", f"registry: {p.message}")
    by_id = reg.by_id()
    want = {d["diagram_id"]: d for d in snap["diagrams"]}
    active = {e.diagram_id for e in reg.entries if e.owner_kind == "document" and e.status == "active"}
    if active != set(want):
        fail("V1", f"active document-owned entries {sorted(active)} differ from the snapshot's {sorted(want)}")
    for e in reg.entries:
        if e.diagram_id.startswith("AD-") and e.diagram_id not in want:
            fail("V1", f"{e.diagram_id} is not in the snapshot (no other AD entry may exist during M1)")
    raw_items = {item.get("diagram_id"): item for item in (reg.data or {}).get("diagrams") or [] if isinstance(item, dict)}
    docs = {d.path: d for d in documents(root)}
    found_regions = regions(root)
    sources = {s.path: s for s in registry.source_files(root)}
    extracted, embedded = [], []
    for did, w in want.items():
        e = by_id.get(did)
        if e is None:
            fail("V1", f"{did} is missing from the registry")
            continue
        cf = raw_items.get(did, {}).get("created_from")
        now = {"aliases": list(e.aliases), "title": e.title, "category": e.category,
               "owner": {"kind": e.owner_kind, "ref": e.owner_ref}, "status": e.status, "created": e.created,
               "created_from": json.loads(json.dumps(cf, default=str)) if cf is not None else None}
        for key, value in now.items():
            if value != w[key]:
                fail("V2", f"{did}: {key} is {value!r}, the snapshot has {w[key]!r}")
        if e.format == "mermaid-md":
            extracted.append(did)
            _verify_extracted(root, e, w, docs, found_regions, sources, fail, _yaml, split_front_matter, diagrams)
        elif e.format == "mermaid-embedded":
            embedded.append(did)
            located, _ = registry.locate_embedded(root, e)
            if located is None:
                fail("V3", f"{did}: its embedded block cannot be found in {e.path}")
                continue
            if list(located.source) != w["mermaid_lines"]:
                fail("V3", f"{did}: the embedded block differs from the snapshot{_first_difference(located.source, w)}")
            text = _lf(docs[e.path].text).split("\n") if e.path in docs and docs[e.path].parsed else []
            fences = (text[located.line - 1], text[located.line + len(located.source)]) if text else ("", "")
            if fences != (w["opening_fence"], w["closing_fence"]):
                fail("V3", f"{did}: the fence lines {fences} differ from the snapshot's")
        else:
            fail("V3", f"{did}: format {e.format} is not an M1 state")
    # V4: stripping the regions gives the snapshot document exactly
    for rel, w in snap["documents"].items():
        d = docs.get(rel)
        if d is None or d.parsed is None:
            fail("V4", f"{rel} is missing or cannot be read")
            continue
        stripped, problems = strip_regions(d.text)
        for p in problems:
            fail("V4", f"{rel}: {p}")
        if stripped != w["text"]:
            fail("V4", f"{rel}: without its generated markers it differs from the snapshot"
                       f"{_first_text_difference(stripped, w['text'])}")
    for rel in sorted(set(docs) - set(snap["documents"])):
        fail("V4", f"{rel} is not in the snapshot")
    # V5: the architecture index still lists the same diagrams
    rows = architecture_diagrams(root)
    types: dict[str, int] = {}
    for w in snap["diagrams"]:
        types[w["diagram_type"] or "not marked"] = types.get(w["diagram_type"] or "not marked", 0) + 1
    by_type = ", ".join(f"{n} {t}" for t, n in sorted(types.items()))
    row_types: dict[str, int] = {}
    for r in rows:
        row_types[r.diagram_type or "not marked"] = row_types.get(r.diagram_type or "not marked", 0) + 1
    if len(rows) != len(want) or row_types != types:
        fail("V5", f"{len(rows)} diagrams ({row_types}) instead of {len(want)} ({types})")
    summary = f"{len(want)} diagram{'s' if len(want) != 1 else ''} ({by_type})."
    if summary not in render_architecture_index(root):
        fail("V5", f"the architecture index summary does not say {summary!r}")
    snap_aliases = sorted(w["aliases"][0] if w["aliases"] else w["diagram_id"] for w in snap["diagrams"])
    if sorted(r.alias for r in rows) != snap_aliases:
        fail("V5", f"the index rows' diagram IDs {sorted(r.alias for r in rows)} differ from the snapshot's")
    # V6: the legend anchor; no diagram in diagram-library.md
    legend_doc, legend_anchor = diagrams.LEGEND.split("#")
    ld = docs.get(legend_doc)
    if ld is None or ld.parsed is None or legend_anchor not in {h.anchor for h in ld.parsed.headings}:
        fail("V6", f"the legend anchor {diagrams.LEGEND} does not resolve")
    lib = docs.get(ARCHITECTURE + "/diagram-library.md")
    if lib is not None and lib.parsed is not None and (parse(lib.text).diagrams or spans(lib.text)):
        fail("V6", "docs/architecture/diagram-library.md contains a Mermaid block or a generated copy")
    checks = {}
    for v in ("V1", "V2", "V3", "V4", "V5", "V6"):
        checks[v] = "fail" if any(f["check"] == v for f in found) else "pass"
    checks["V7"] = ("not run here: `python -m tools.design check` and `python -m tools.design index --check` must be run "
                    "separately (PR acceptance)")
    return {"version": 1, "ok": not found, "snapshot": {"path": str(snapshot_path), "sha256": snap_sha,
                                                        "commit": snap.get("commit")},
            "checks": checks, "problems": found, "extracted": sorted(extracted), "embedded": sorted(embedded)}


def _verify_extracted(root, e, w, docs, found_regions, sources, fail, _yaml, split_front_matter, diagrams):
    did = e.diagram_id
    name = M1_SOURCES.get(did)
    if name is not None and e.path != f"{DOCUMENT_SOURCES}/{name}":
        fail("V3", f"{did}: its source is {e.path}, the approved name is {DOCUMENT_SOURCES}/{name}")
    elif posixpath.dirname(e.path) != DOCUMENT_SOURCES:
        fail("V3", f"{did}: its source {e.path} is not in {DOCUMENT_SOURCES}/")
    s = sources.get(e.path)
    if s is None or s.diagram_id != did or s.owner_document != e.owner_ref or s.title != e.title or s.feature_id:
        fail("V3", f"{did}: the front matter of {e.path} does not hold diagram_id {did}, owner_document "
                   f"{e.owner_ref} and the registry title (and no feature_id)")
    else:
        front, _ = split_front_matter((Path(root) / e.path).read_bytes().decode("utf-8"))
        meta = _yaml().load(front)
        if list(meta) != ["diagram_id", "title", "owner_document"]:
            fail("V3", f"{did}: the front matter keys of {e.path} are {list(meta)}, expected diagram_id, title, "
                       "owner_document")
    src = diagrams._refuse_markers(diagrams._registered_source(root, e))
    if src.problem or not src.closed:
        fail("V3", f"{did}: {src.problem or 'its source block has no closing fence'}")
        return
    if list(src.lines) != w["mermaid_lines"]:
        fail("V3", f"{did}: the source's Mermaid lines differ from the snapshot{_first_difference(src.lines, w)}")
    fences = _source_fences(root, src)
    if fences != (w["opening_fence"], w["closing_fence"]):
        fail("V3", f"{did}: the source's fence lines {fences} differ from the snapshot's")
    names = (did, *e.aliases)
    own = [(p, b) for n in names for p, b in found_regions.get(n, []) if p == e.owner_ref]
    if len(own) != 1:
        fail("V3", f"{did}: {len(own)} generated copies in {e.owner_ref} (exactly one expected)")
        return
    _, b = own[0]
    if b.diagram_id != did:
        fail("V3", f"{did}: the copy's marker names {b.diagram_id}, not the canonical ID")
    exp = expected(Path(root), e)
    lines = _lf(docs[e.owner_ref].text).split("\n")
    current = lines[b.start + 1:b.end]
    if exp.problem:
        fail("V3", f"{did}: {exp.problem}")
    elif classify(b, current, list(exp.lines)) != "current":
        fail("V3", f"{did}: the copy on line {b.start + 1} of {e.owner_ref} is not current "
                   f"({classify(b, current, list(exp.lines))})")
    body = current[2:-1]
    if body != w["mermaid_lines"]:
        fail("V3", f"{did}: the copy's Mermaid lines differ from the snapshot{_first_difference(body, w)}")
    extra = [i for i, x in enumerate(body) if x.strip() == "%%" and (i >= len(w["mermaid_lines"])
                                                                     or w["mermaid_lines"][i].strip() != "%%")]
    if extra:
        fail("V3", f"{did}: the copy has '%%' lines the snapshot does not have (copy lines {extra})")


def _first_difference(lines, w) -> str:
    for i, (a, b) in enumerate(zip(lines, w["mermaid_lines"])):
        if a != b:
            return f" (Mermaid line {i + 1}: {a!r} instead of {b!r})"
    return f" ({len(lines)} lines instead of {len(w['mermaid_lines'])})"


def _first_text_difference(a: str, b: str) -> str:
    x, y = a.split("\n"), b.split("\n")
    for i, (p, q) in enumerate(zip(x, y)):
        if p != q:
            return f" (first difference at line {i + 1}: {p[:80]!r} instead of {q[:80]!r})"
    return f" ({len(x)} lines instead of {len(y)})"
