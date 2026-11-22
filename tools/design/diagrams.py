"""Generated diagram blocks in feature specifications (T-96).

An author places, anywhere in the body of a feature specification (in any of the six
sections, as often as wanted, the same ID more than once if useful):

    <!-- diagram:start system-architecture/4-target-state-the-product-vision-mostly-planned -->
    <!-- diagram:end -->

The start marker is the only place a diagram is attached: there is no metadata list.
`python -m tools.design index` fills the lines between the two markers from the authoritative
source. Nothing outside the markers is ever rewritten, except the start marker's fingerprint.

Fingerprints (U13, diagram library 6.5): a generated start marker records a fingerprint of
the content last generated, `<!-- diagram:start <ID> sha256:<16 hex> -->`. Comparing the
block (B) and what the source generates now (G) with it (F) gives: current; case 1 (source
changed, block untouched: refreshed); case 2 (block edited by hand, source unchanged) and
case 3 (both changed): conflicts (E15), never overwritten, reconciled only explicitly
(`python -m tools.design reconcile`). Comparison is exact; only line endings are
normalised. A block edited to exactly the new output only gets its fingerprint updated.
Markers without a fingerprint keep the T-96 behaviour (any difference is stale) until their
first refresh adds one.

Sources come from the diagram registry (designs/diagrams/registry.yml, registry.py): an ID or
an alias names a registered diagram (a standalone Mermaid source, or an architecture diagram
registered in place); architecture catalog IDs that are not registered yet still resolve to
the catalog. An ID used by two sources, a source without exactly one Mermaid block, a retired
diagram (E11) or a source that cannot be found (E7) is a problem, never a guess.

The generated lines are one contiguous block: a caption line (label, title linked to the
source document and heading, the ID, a "generated copy" note, and the legend link for
architecture diagrams), then the Mermaid source in a fence that is always closed before the
end marker. Blank lines of the source are written as `%%`, a Mermaid comment line, so the
diagram renders the same and the block has no blank line (Mark Sharp keeps such a block,
which starts with an HTML comment, verbatim). The fence is long enough that no line of the
source can close it early.

Parsing rules (all outside the YAML front matter):
- Markers are recognised only on a line of their own, outside fenced code (examples in code
  blocks are ignored) and outside the summary and Related features blocks.
- Inside a diagram block, its own Mermaid fence is tracked: a start-marker-like line inside
  that fence is Mermaid content; an end marker reached while the fence is still open is
  reported (the fence must be closed before the end marker). A source whose Mermaid contains
  any `<!-- diagram:` line is refused (reported), so a copy can never contain one.
- Blocks belong in the six sections: a start marker before `## 1. Objective` is reported.
  A marker that is not alone on its line (in a list item, a quote or a sentence) is reported.
- A start marker inside a block (nesting), an end marker without a start, a start marker
  without an end, an empty or unknown ID, and any `<!-- diagram:` line that is not exactly a
  start or end marker are problems. A file with any such problem is never rewritten.
"""

from __future__ import annotations

import dataclasses
import difflib
import hashlib
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .workspace import Feature, Problem, _cell, _link, discover, replace_span, write_feature_text

START = re.compile(r"<!--\s*diagram:start(?:\s+(?P<id>(?!sha256:)\S+))?(?:\s+sha256:(?P<fp>[0-9a-f]{16}))?\s*-->\Z")
END = "<!-- diagram:end -->"
END_RE = re.compile(r"<!--\s*diagram:end\s*-->\Z")
LIKE_MARKER = re.compile(r"<!--\s*diagram\s*:", re.I)
FENCE_OPEN = re.compile(r"\s*(`{3,}|~{3,})(.*)\Z")
GENERATED_STARTS = ("<!-- summary:start", "<!-- related-features:start")
GENERATED_ENDS = ("<!-- summary:end -->", "<!-- related-features:end -->")
LEGEND = "docs/architecture/conventions.md#1-implementation-status-legend"
FIRST_SECTION = "## 1. Objective"
NOTE = "generated copy; edit the source, not this block"


@dataclass(frozen=True)
class Block:
    start: int            # 0-based index of the start-marker line in the file
    end: int              # 0-based index of the end-marker line
    diagram_id: str
    fp: str | None = None # the fingerprint recorded in the start marker (U13), None for an old marker


@dataclass(frozen=True)
class Source:
    diagram_id: str
    kind: str             # "current" (architecture catalog) or "proposed" (milestone 2)
    title: str            # plain text
    path: str             # repository-relative file the diagram lives in
    anchor: str           # heading anchor in that file ('' for none)
    lines: tuple[str, ...]
    legend: bool          # link the architecture legend (architecture-type diagrams)
    closed: bool = True
    problem: str = ""     # why this ID cannot be used (ambiguous or malformed source); '' when fine
    line: int = 0         # 1-based line of the source's opening Mermaid fence in `path` (0: unknown)
    owner: str = ""       # proposed diagrams: the owning feature's ID from `feature_id` ('' when not set)


# --------------------------------------------------------------------------- sources

def _current(d) -> Source:
    """The Source of an architecture catalog diagram (embedded in its document)."""
    doc_title = d.title or posixpath.basename(d.document)
    title = f"{doc_title} › {d.heading.text}" if d.heading is not None and d.heading.text else doc_title
    return Source(d.diagram_id, "current", title, d.document, d.heading.anchor if d.heading is not None else "",
                  d.source, d.diagram_type == "architecture", d.closed, line=d.line)


def sources(root: Path) -> dict[str, Source]:
    """Every diagram a block can name, by ID and by alias (each Source carries the name it was
    looked up by, so a block that uses a former catalog ID keeps its generated text)."""
    from . import registry
    from .architecture import catalog, documents
    reg = registry.load(root)
    cat = catalog(documents(root))
    position: dict[tuple, int] = {}
    by_position = {}
    for d in cat:
        key = registry.catalog_key(d)
        position[key] = position.get(key, 0) + 1
        by_position[(key[0], key[1], position[key])] = d
    out: dict[str, Source] = {}
    covered = set()

    def put(name: str, src: Source):
        src = dataclasses.replace(src, diagram_id=name)
        if name in out:
            first = out[name]
            out[name] = Source(name, "ambiguous", "", src.path, "", (), False, line=src.line, owner=src.owner,
                               problem=f"is used by more than one diagram ({first.path} and {src.path}) (E2)")
        else:
            out[name] = src

    for e in reg.entries:
        if e.status == "retired":
            src = Source(e.diagram_id, "retired", e.title, e.path, "", (), False,
                         owner=e.owner_ref if e.owner_kind == "feature" else "",
                         problem=f"was retired on {e.retired} (E11): remove this block or reference another diagram")
        elif e.format == "mermaid-embedded":
            d = by_position.get((e.path, None if e.anchor in ("", "top") else e.anchor, e.ordinal))
            if d is None:
                src = Source(e.diagram_id, "missing", e.title, e.path, e.anchor, (), False,
                             problem=f"cannot be found: no Mermaid diagram {e.ordinal} under #{e.anchor or 'top'} in "
                                     f"{e.path} (E7); re-point it with `python -m tools.design registry relink "
                                     f"{e.diagram_id} --heading <anchor>`")
            else:
                src = _current(d)
                covered.add(d.diagram_id)
        else:
            src = _registered_source(root, e)
        for name in (e.diagram_id, *e.aliases):
            put(name, src)
    for d in cat:                                       # not registered yet (before stage M0)
        if d.diagram_id not in covered and d.diagram_id not in out:
            out[d.diagram_id] = _current(d)
    return {k: _refuse_markers(v) for k, v in out.items()}


def proposed_sources(root: Path) -> list[Source]:
    """One source per registered feature-owned diagram, in path order."""
    from . import registry
    reg = registry.load(root)
    return [_refuse_markers(_registered_source(root, e)) for e in sorted(reg.entries, key=lambda x: x.path)
            if e.owner_kind == "feature" and e.status == "active" and e.format == "mermaid-md"]


def _refuse_markers(source: Source) -> Source:
    """A source whose Mermaid contains a line that looks like a diagram marker could not be
    told apart from the block's own end marker, so it is never embedded (reported instead)."""
    if source.problem or not any(LIKE_MARKER.search(line) for line in source.lines):
        return source
    return Source(source.diagram_id, source.kind, source.title, source.path, source.anchor, (), False,
                  line=source.line, owner=source.owner,
                  problem=f"cannot be embedded: its Mermaid source in {source.path} contains a line with "
                          "'<!-- diagram:', which would be read as a marker; change that line in the source")


def _registered_source(root: Path, e) -> Source:
    """A registered standalone Mermaid source (`mermaid-md`): exactly one Mermaid block."""
    from . import markdown
    from .workspace import split_front_matter
    kind = "proposed" if e.owner_kind == "feature" else "current"
    owner = e.owner_ref if e.owner_kind == "feature" else ""
    try:
        text = (root / e.path).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return Source(e.diagram_id, "missing", e.title, e.path, "", (), False, owner=owner,
                      problem=f"cannot be read: its source {e.path} is missing or not UTF-8 (E7)")
    _, body = split_front_matter(text)
    offset = text[:len(text) - len(body)].count("\n") if text.endswith(body) else 0
    doc = markdown.parse(body)
    if len(doc.diagrams) != 1:
        return Source(e.diagram_id, kind, e.title, e.path, "", (), False, owner=owner,
                      problem=f"has a source {e.path} that must hold exactly one Mermaid block "
                              f"(found {len(doc.diagrams)})")
    d = doc.diagrams[0]
    legend = e.owner_kind == "document" and d.diagram_type == "architecture"
    return Source(e.diagram_id, kind, e.title, e.path, "", d.source, legend, d.closed, line=d.line + offset, owner=owner)


# --------------------------------------------------------------------------- scanning

def _body_start(lines: list[str]) -> int:
    """Index of the first line after the YAML front matter (0 when there is none)."""
    if lines and lines[0].lstrip("﻿").rstrip("\r") == "---":
        for i in range(1, len(lines)):
            if lines[i].rstrip("\r") == "---":
                return i + 1
    return 0


def _fence(line: str):
    m = FENCE_OPEN.match(line)
    return (m.group(1)[0], len(m.group(1)), m.group(2)) if m else None


def _closes(line: str, fence) -> bool:
    f = _fence(line)
    return bool(f and f[0] == fence[0] and f[1] >= fence[1] and not f[2].strip())


def scan(text: str) -> tuple[list[Block], list[tuple[int, str]]]:
    """The diagram blocks of a feature file and its structural problems (1-based line, message)."""
    lines = text.replace("\r\n", "\n").split("\n")
    blocks, problems = [], []
    fence = None                  # an open code fence outside diagram blocks
    generated = None              # inside a summary or Related features block
    block = None                  # (start index, id) of the open diagram block
    inner = None                  # the open Mermaid fence inside the diagram block
    in_sections = False           # past '## 1. Objective' (blocks belong in the six sections)
    for i in range(_body_start(lines), len(lines)):
        raw = lines[i]
        s = raw.strip()
        if block is not None:
            if inner is not None:
                if _closes(raw, inner):
                    inner = None
                elif END_RE.match(s):
                    problems.append((i + 1, f"the Mermaid fence of the diagram block for {block[1] or '(no ID)'} "
                                            f"(line {block[0] + 1}) is not closed before <!-- diagram:end -->: delete "
                                            "the lines between the two markers and run `python -m tools.design index`"))
                    blocks.append(Block(block[0], i, block[1], block[2]))
                    block, inner = None, None
                continue
            if _fence(raw) and not (_fence(raw)[0] == "`" and "`" in _fence(raw)[2]):
                inner = _fence(raw)
            elif END_RE.match(s):
                blocks.append(Block(block[0], i, block[1], block[2]))
                block = None
            elif START.match(s):
                problems.append((i + 1, f"diagram:start inside the diagram block that starts on line {block[0] + 1}: "
                                        "blocks cannot be nested (add the missing <!-- diagram:end -->)"))
            elif LIKE_MARKER.match(s):
                problems.append((i + 1, f"malformed diagram marker {s!r}: use <!-- diagram:start <ID> --> and "
                                        f"{END}"))
            continue
        if fence is not None:
            if _closes(raw, fence):
                fence = None
            continue
        f = _fence(raw)
        if f and not (f[0] == "`" and "`" in f[2]):
            fence = f
            continue
        if generated is not None:
            if s == generated:
                generated = None
            elif LIKE_MARKER.match(s):
                problems.append((i + 1, "a diagram marker inside a generated summary or Related features block "
                                        "would be overwritten: move it outside that block"))
            continue
        for start, end in zip(GENERATED_STARTS, GENERATED_ENDS):
            if s.startswith(start):
                generated = end
        if generated is not None:
            continue
        if s == FIRST_SECTION:
            in_sections = True
        m = START.match(s)
        if m:
            if not m.group("id"):
                problems.append((i + 1, "diagram:start has no diagram ID: use <!-- diagram:start <ID> --> with an "
                                        "ID from designs/index/architecture-index.md#diagrams"))
            if not in_sections:
                problems.append((i + 1, f"diagram blocks belong in the six sections: move this block below "
                                        f"'{FIRST_SECTION}'"))
            block = (i, m.group("id") or "", m.group("fp"))
        elif END_RE.match(s):
            problems.append((i + 1, f"{END} without a matching <!-- diagram:start <ID> -->"))
        elif LIKE_MARKER.match(s):
            problems.append((i + 1, f"malformed diagram marker {s!r}: use <!-- diagram:start <ID> --> and {END}"))
        elif LIKE_MARKER.search(re.sub(r"(`+).+?\1", "", s)):
            problems.append((i + 1, "a diagram marker must stand alone on its own line (not in a list item, quote "
                                    "or sentence), with a blank line before and after the block"))
    if block is not None:
        problems.append((block[0] + 1, f"diagram:start {block[1] or '(no ID)'} has no matching {END}"))
    return blocks, problems


# --------------------------------------------------------------------------- rendering

def _fence_for(lines) -> str:
    longest = max((len(m.group(1)) for line in lines for m in [re.match(r"\s*(`+)", line)] if m), default=0)
    return "`" * max(3, longest + 1)


def render(source: Source, feature_path: str) -> list[str]:
    """The generated lines between the markers, for a feature at `feature_path`."""
    here = posixpath.dirname(feature_path)
    link = _link(posixpath.relpath(source.path, here)) + ("#" + quote(source.anchor, safe="-_.~%") if source.anchor else "")
    label = "✅ Current architecture" if source.kind == "current" else "🔷 Proposed"
    caption = f"**{label}: [{_cell(source.title)}]({link})** · `{source.diagram_id}` · {NOTE}"
    if source.legend:
        caption += f" · [legend]({_link(posixpath.relpath(LEGEND.split('#')[0], here))}#{LEGEND.split('#')[1]})"
    fence = _fence_for(source.lines)
    body = [line if line.strip() else "%%" for line in source.lines]
    return [caption, fence + "mermaid", *body, fence]


def fingerprint(lines) -> str:
    """The fingerprint of generated content (U13): exact, with line endings as the only
    normalisation (lines are compared without a trailing CR)."""
    return hashlib.sha256("\n".join(line[:-1] if line.endswith("\r") else line for line in lines)
                          .encode("utf-8")).hexdigest()[:16]


def start_marker(name: str, lines) -> str:
    return f"<!-- diagram:start {name} sha256:{fingerprint(lines)} -->"


def classify(block: Block, current: list[str], expected: list[str]) -> str:
    """current | empty | stale (old marker) | case1 | fp-only | case2 | case3 (U13)."""
    if block.fp is None:
        if current == expected:
            return "current"
        return "empty" if not current else "stale"
    if not current:
        return "empty"                                  # cleared on purpose: nothing to lose
    if fingerprint(current) == block.fp:
        return "current" if fingerprint(expected) == block.fp else "case1"
    if current == expected:
        return "fp-only"
    return "case2" if fingerprint(expected) == block.fp else "case3"


REGENERABLE = ("empty", "stale", "case1", "fp-only")
CONFLICTS = ("case2", "case3")


# --------------------------------------------------------------------------- check and refresh

def _suggest(diagram_id: str, known) -> str:
    close = difflib.get_close_matches(diagram_id, sorted(k for k, s in known.items() if not s.problem), n=1, cutoff=0.5)
    return (f" (did you mean {close[0]}?)" if close else
            " (see designs/index/architecture-index.md#diagrams, or the diagram_id of a proposed diagram file)")


def file_problems(rel: str, text: str, known: dict[str, Source]) -> list[Problem]:
    """Every diagram problem of one feature file: structure, unknown IDs, stale or edited blocks."""
    return [p for p, _ in _classified(rel, text, known)]


def _classified(rel: str, text: str, known: dict[str, Source]) -> list[tuple[Problem, str]]:
    """(problem, kind): "block" problems stop `index` for the whole file (structure, unusable
    IDs); "conflict" problems (E15) leave that block alone; "regen" problems are what `index`
    fixes."""
    blocks, structural = scan(text)
    return ([(Problem(rel, f"line {n}: {msg}"), "block") for n, msg in structural]
            + [(p, "block") for p in _content_problems(rel, text, known, blocks, unusable=True)]
            + _block_states(rel, text, known, blocks))


def _content_problems(rel: str, text: str, known: dict[str, Source], blocks, unusable: bool = False) -> list[Problem]:
    """IDs that cannot be resolved (unusable=True), as `index` must not touch those files."""
    out = []
    for b in blocks:
        if not b.diagram_id:
            continue
        source = known.get(b.diagram_id)
        if source is None:
            out.append(Problem(rel, f"line {b.start + 1}: unknown diagram ID {b.diagram_id!r}"
                                    f"{_suggest(b.diagram_id, known)} (E1)"))
        elif source.problem:
            out.append(Problem(rel, f"line {b.start + 1}: diagram ID {b.diagram_id!r} {source.problem}"))
        elif not source.closed:
            out.append(Problem(rel, f"line {b.start + 1}: the source Mermaid block of {b.diagram_id} in "
                                    f"{source.path} has no closing fence; fix the source first"))
    return out


def _usable(b: Block, known) -> bool:
    s = known.get(b.diagram_id) if b.diagram_id else None
    return s is not None and not s.problem and s.closed


def _block_states(rel: str, text: str, known: dict[str, Source], blocks) -> list[tuple[Problem, str]]:
    out = []
    lines = text.replace("\r\n", "\n").split("\n")
    for b in blocks:
        if not _usable(b, known):
            continue
        source = known[b.diagram_id]
        current, expected = lines[b.start + 1:b.end], render(source, rel)
        state = classify(b, current, expected)
        at = f"line {b.start + 1}: the diagram block for {b.diagram_id}"
        fix = f"`python -m tools.design reconcile --file {rel} --line {b.start + 1} --discard` or `--apply-to-source`"
        if state == "current":
            continue
        if state == "empty":
            out.append((Problem(rel, f"{at} is empty: run `python -m tools.design index`"), "regen"))
        elif state == "stale":
            if current[1:] != expected[1:]:
                what = (f"differs from the authoritative Mermaid source in {source.path}"
                        f"{'#' + source.anchor if source.anchor else ''} (stale, or edited by hand)")
            else:
                what = "has a caption or source link that differs from the generated one (edited by hand?)"
            out.append((Problem(rel, f"{at} {what}: run `python -m tools.design index`"), "regen"))
        elif state == "case1":
            out.append((Problem(rel, f"{at} is out of date with its source {source.path} (not edited since it was "
                                     "generated): run `python -m tools.design index`"), "regen"))
        elif state == "fp-only":
            out.append((Problem(rel, f"{at} matches its source, but its fingerprint is out of date: run "
                                     "`python -m tools.design index`"), "regen"))
        elif state == "case2":
            out.append((Problem(rel, f"{at} was edited by hand (its source {source.path} is unchanged), so it is "
                                     f"never overwritten automatically (E15): reconcile with {fix}"), "conflict"))
        else:
            out.append((Problem(rel, f"{at} and its source {source.path} have both changed since the block was "
                                     f"generated, so it is never overwritten automatically (E15): reconcile with {fix}"),
                        "conflict"))
    return out


def problems(root: Path, features: list[Feature] | None = None) -> list[Problem]:
    if features is None:
        features, _ = discover(root)
    known = sources(root)
    out = []
    for f in features:
        try:
            text = (root / f.path).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        out += file_problems(f.path, text, known)
    for source in known.values():                 # a proposed ID no marker could ever name
        if source.kind == "proposed" and "contains whitespace" in source.problem:
            out.append(Problem(source.path, f"diagram_id {source.diagram_id!r} contains whitespace, so no "
                                            "diagram marker can name it; use an ID like FD-0001-D1"))
    return out


def stale(root: Path) -> list[Problem]:
    """Only the blocks `index` would rewrite (for `index --check`)."""
    features, _ = discover(root)
    known = sources(root)
    out = []
    for f in features:
        try:
            text = (root / f.path).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        out += [p for p, kind in _classified(f.path, text, known) if kind in ("regen", "conflict")]
    return out


def blocking(text: str, rel: str, known: dict[str, Source]) -> list[str]:
    """Why `index` must leave this file's diagram blocks alone (empty: it may refresh them).
    A conflict (E15) does not block the file: only that block is left alone."""
    return [p.message for p, kind in _classified(rel, text, known) if kind == "block"]


def conflicts(text: str, rel: str, known: dict[str, Source]) -> list[str]:
    return [p.message for p, kind in _classified(rel, text, known) if kind == "conflict"]


def regenerated(text: str, rel: str, known: dict[str, Source]) -> list[tuple[int, int, list[str]]]:
    """(start, end, lines) for every block `index` may refresh: the start marker (with its new
    fingerprint) and the generated lines; conflicts (E15) and current blocks are left alone."""
    blocks, _ = scan(text)
    lines = text.replace("\r\n", "\n").split("\n")
    out = []
    for b in blocks:
        if not _usable(b, known):
            continue
        expected = render(known[b.diagram_id], rel)
        if classify(b, lines[b.start + 1:b.end], expected) in REGENERABLE:
            out.append((b.start, b.end, [start_marker(b.diagram_id, expected), *expected]))
    return out


def apply(text: str, rel: str, known: dict[str, Source]) -> str:
    """The file text with every refreshable block regenerated: only each block's start marker
    and the lines between its markers change, and conflicts are never touched."""
    keep = split_keep(text)
    for start, end, new in reversed(regenerated(text, rel, known)):
        newline = "\r\n" if keep[start].endswith("\r\n") else "\n"
        keep = keep[:start] + [line + newline for line in new] + keep[end:]
    return "".join(keep)


def split_keep(text: str) -> list[str]:
    """Lines with their endings, split on '\\n' only, exactly as `scan` counts them (unlike
    str.splitlines, which also breaks on U+2028, form feed, a lone CR and others)."""
    parts = re.split(r"(?<=\n)", text)
    return parts[:-1] if parts and parts[-1] == "" else parts


def refresh(root: Path) -> list[tuple[str, int]]:
    """Regenerate the refreshable diagram blocks (U13: never a conflict) in feature files with
    valid metadata and no structural diagram problem. Returns (path, number of blocks
    refreshed) for each rewritten file."""
    features, _ = discover(root)
    known = sources(root)
    changed = []
    for f in features:
        if not f.meta_ok:
            continue
        path = root / f.path
        text = path.read_bytes().decode("utf-8")
        blocks, _ = scan(text)
        if not blocks or blocking(text, f.path, known):
            continue
        todo = regenerated(text, f.path, known)
        new = apply(text, f.path, known)
        if todo and new.replace("\r\n", "\n") != text.replace("\r\n", "\n"):
            write_feature_text(path, new)
            changed.append((f.path, len(todo)))
    return changed


def spans(text: str) -> list[tuple[int, int]]:
    """0-based (start, end) line indices of well-formed diagram blocks (for the link check)."""
    blocks, _ = scan(text)
    return [(b.start, b.end) for b in blocks]


def ids_in(text: str) -> list[str]:
    """The diagram IDs a feature attaches, in order of first appearance."""
    seen = []
    for b in scan(text)[0]:
        if b.diagram_id and b.diagram_id not in seen:
            seen.append(b.diagram_id)
    return seen



# --------------------------------------------------------------------------- reconciliation (U13)

@dataclass(frozen=True)
class Reconciliation:
    rel: str
    block: Block
    action: str               # "discard" or "apply-to-source"
    state: str
    diff: str                 # what will change, as a unified diff
    token: str                # changes when the document or the source changes (confirm with it)
    document_text: str        # the new document text
    source_path: str = ""     # apply-to-source: the source file and its new text
    source_text: str = ""
    warning: str = ""         # shown with the preview (for example: the source changed too)


def feature_document(root: Path, rel: str) -> str:
    """`rel` as a feature specification path, or ValueError: reconciliation rewrites only
    feature documents inside the repository (never docs/architecture/ or any other file)."""
    norm = posixpath.normpath(str(rel).replace("\\", "/"))
    if norm.startswith("../") or norm == ".." or norm.startswith("/") or re.match(r"[A-Za-z]:", norm):
        raise ValueError(f"{rel} is outside the repository")
    features, _ = discover(root)
    if norm not in {f.path for f in features}:
        raise ValueError(f"{rel} is not a feature specification under designs/features/: reconciliation only "
                         "changes feature documents")
    return norm


def _block_at(text: str, line: int) -> Block:
    blocks, structural = scan(text)
    if structural:
        raise ValueError("the document has diagram-marker problems; fix them first (python -m tools.design check)")
    for b in blocks:
        if b.start + 1 == line:
            return b
    raise ValueError(f"no diagram block starts on line {line}")


def _body_from_block(block_lines: list[str]) -> list[str]:
    """The Mermaid lines of a generated block (caption, fence, body, fence); a bare `%%` line is
    the T-96 form of a blank line and becomes blank again."""
    if len(block_lines) < 3 or not block_lines[1].lstrip("`").startswith("mermaid"):
        raise ValueError("the block does not have the generated layout (caption, then a Mermaid fence)")
    fence = block_lines[1][:len(block_lines[1]) - len(block_lines[1].lstrip("`"))]
    if block_lines[-1].strip() != fence:
        raise ValueError("the block's Mermaid fence is not closed as generated")
    return ["" if line == "%%" else line for line in block_lines[2:-1]]


def plan_reconcile(root: Path, rel: str, line: int, action: str) -> Reconciliation:
    """What "Discard manual change" or "Apply to source" would do (nothing is written)."""
    from . import registry
    root = Path(root)
    rel = feature_document(root, rel)
    path = root / rel
    text = path.read_bytes().decode("utf-8")
    known = sources(root)
    b = _block_at(text, line)
    if not _usable(b, known):
        raise ValueError(f"diagram {b.diagram_id!r} cannot be resolved; see python -m tools.design check")
    source = known[b.diagram_id]
    lines = text.replace("\r\n", "\n").split("\n")
    current = lines[b.start + 1:b.end]
    expected = render(source, rel)
    state = classify(b, current, expected)
    source_path = source_text = ""
    source_bytes = b""
    if action == "discard":
        new_lines = [start_marker(b.diagram_id, expected), *expected]
    elif action == "apply-to-source":
        entry = registry.load(root).lookup().get(b.diagram_id)
        if entry is None or entry.format != "mermaid-md":
            raise ValueError(f"{b.diagram_id} has no standalone source: an architecture diagram changes only through "
                             "technical-lead's documentation workflow")
        if entry.owner_kind != "feature":
            raise ValueError(f"{b.diagram_id} is owned by {entry.owner_ref}: document-owned sources change only through "
                             "technical-lead's documentation workflow (this preview can be handed to it)")
        source_path = entry.path
        source_bytes = (root / source_path).read_bytes()
        src_text = source_bytes.decode("utf-8")
        new_body = _body_from_block(current)
        if any(LIKE_MARKER.search(x) for x in new_body):
            raise ValueError("the block's Mermaid contains a line with '<!-- diagram:', which would make the source "
                             "impossible to embed; remove that line first")
        src_lines = src_text.split("\n")
        first = source.line                                   # 1-based line of the opening fence
        close = first + len(source.lines)                     # 0-based index of the closing fence
        eol = "\r" if src_lines[first - 1].endswith("\r") else ""
        source_text = "\n".join(src_lines[:first] + [x + eol for x in new_body] + src_lines[close:])
        regenerated_source = dataclasses.replace(source, lines=tuple(new_body))
        expected = render(regenerated_source, rel)
        new_lines = [start_marker(b.diagram_id, expected), *expected]
    else:
        raise ValueError("action must be discard or apply-to-source")
    keep = split_keep(text)
    newline = "\r\n" if keep[b.start].endswith("\r\n") else "\n"
    document_text = "".join(keep[:b.start] + [x + newline for x in new_lines] + keep[b.end:])
    diff = "".join(difflib.unified_diff(text.replace("\r\n", "\n").splitlines(True),
                                        document_text.replace("\r\n", "\n").splitlines(True),
                                        fromfile=rel, tofile=rel + " (after)"))
    if source_path:
        diff += "".join(difflib.unified_diff(source_bytes.decode("utf-8").replace("\r\n", "\n").splitlines(True),
                                             source_text.replace("\r\n", "\n").splitlines(True),
                                             fromfile=source_path, tofile=source_path + " (after)"))
    token = hashlib.sha256(text.encode("utf-8") + b"\0" + source_bytes + b"\0" + action.encode()).hexdigest()[:16]
    warning = ""
    if action == "apply-to-source" and state == "case3":
        warning = ("the source has also changed since this block was generated: applying replaces those source "
                   "changes with the block's content (see the diff)")
    return Reconciliation(rel, b, action, state, diff, token, document_text, source_path, source_text, warning)
