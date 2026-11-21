"""Generated diagram blocks in feature specifications (T-96).

An author places, anywhere in the body of a feature specification (in any of the six
sections, as often as wanted, the same ID more than once if useful):

    <!-- diagram:start system-architecture/4-target-state-the-product-vision-mostly-planned -->
    <!-- diagram:end -->

The start marker is the only place a diagram is attached: there is no metadata list.
`python -m tools.design index` fills the lines between the two markers from the authoritative
source, and `check` compares them with what the source produces now (the full text, not a
fingerprint). Nothing outside the markers is ever rewritten.

Sources:
- an architecture catalog ID (designs/index/architecture-index.md): the Mermaid block under
  that heading in docs/architecture/, labelled "Current architecture" (milestone 1);
- the `diagram_id` of a proposed-diagram file in a `diagrams/` folder under designs/features/
  (from templates/diagram.md): its single Mermaid block, labelled "Proposed" (milestone 2).
  An ID used by two sources, or a proposed file without exactly one Mermaid block, is a
  problem, never a guess.

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

import difflib
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .workspace import Feature, Problem, _cell, _link, discover, replace_span, write_feature_text

START = re.compile(r"<!--\s*diagram:start(?:\s+(?P<id>\S+))?\s*-->\Z")
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


# --------------------------------------------------------------------------- sources

def sources(root: Path) -> dict[str, Source]:
    """Every diagram a block can name, by ID: architecture catalog IDs (current architecture)
    and the `diagram_id` of proposed-diagram files in `diagrams/` folders (milestone 2)."""
    from .architecture import catalog, documents
    out = {}
    for d in catalog(documents(root)):
        doc_title = d.title or posixpath.basename(d.document)
        title = f"{doc_title} › {d.heading.text}" if d.heading is not None and d.heading.text else doc_title
        out[d.diagram_id] = Source(d.diagram_id, "current", title, d.document,
                                   d.heading.anchor if d.heading is not None else "", d.source,
                                   d.diagram_type == "architecture", d.closed)
    for did, source in list(out.items()):
        out[did] = _refuse_markers(source)
    for source in map(_refuse_markers, _proposed(root)):
        if source.diagram_id in out:
            first = out[source.diagram_id]
            reason = (f"is used by more than one diagram ({first.path} and {source.path})"
                      if first.problem == "" or "more than one" not in first.problem else first.problem)
            out[source.diagram_id] = Source(source.diagram_id, "ambiguous", "", source.path, "", (), False,
                                            problem=reason)
        else:
            out[source.diagram_id] = source
    return out


def _refuse_markers(source: Source) -> Source:
    """A source whose Mermaid contains a line that looks like a diagram marker could not be
    told apart from the block's own end marker, so it is never embedded (reported instead)."""
    if source.problem or not any(LIKE_MARKER.search(line) for line in source.lines):
        return source
    return Source(source.diagram_id, source.kind, source.title, source.path, source.anchor, (), False,
                  problem=f"cannot be embedded: its Mermaid source in {source.path} contains a line with "
                          "'<!-- diagram:', which would be read as a marker; change that line in the source")


def _proposed(root: Path) -> list[Source]:
    """Proposed diagrams: files in `diagrams/` folders under designs/features/ whose metadata
    has a `diagram_id`. Each must hold exactly one Mermaid block; the file is the source."""
    from ruamel.yaml.error import YAMLError
    from . import markdown
    from .links import diagram_files
    from .workspace import _yaml, split_front_matter
    out = []
    for rel in diagram_files(root):
        try:
            text = (root / rel).read_bytes().decode("utf-8")
            front, body = split_front_matter(text)
            meta = _yaml().load(front) if front is not None else None
        except (OSError, UnicodeDecodeError, YAMLError):
            continue                                     # reported by the link and reference checks
        if not isinstance(meta, dict) or not isinstance(meta.get("diagram_id"), str) or not meta["diagram_id"].strip():
            continue                                     # no ID (for example a copy of the template): not attachable
        did = meta["diagram_id"].strip()
        doc = markdown.parse(body)
        if re.search(r"\s", did):
            out.append(Source(did, "proposed", did, rel, "", (), False,
                              problem=f"in {rel} contains whitespace, so no diagram marker can name it; "
                                      "use an ID like FD-0001-D1"))
            continue
        title = meta.get("title") if isinstance(meta.get("title"), str) and meta["title"].strip() else None
        title = title or (doc.headings[0].text if doc.headings else posixpath.basename(rel))
        if len(doc.diagrams) != 1:
            out.append(Source(did, "proposed", title, rel, "", (), False,
                              problem=f"is a proposed diagram in {rel}, which must hold exactly one Mermaid block "
                                      f"(found {len(doc.diagrams)})"))
            continue
        d = doc.diagrams[0]
        out.append(Source(did, "proposed", title, rel, "", d.source, False, d.closed))
    return out


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
                    blocks.append(Block(block[0], i, block[1]))
                    block, inner = None, None
                continue
            if _fence(raw) and not (_fence(raw)[0] == "`" and "`" in _fence(raw)[2]):
                inner = _fence(raw)
            elif END_RE.match(s):
                blocks.append(Block(block[0], i, block[1]))
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
            block = (i, m.group("id") or "")
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


# --------------------------------------------------------------------------- check and refresh

def _suggest(diagram_id: str, known) -> str:
    close = difflib.get_close_matches(diagram_id, sorted(k for k, s in known.items() if not s.problem), n=1, cutoff=0.5)
    return (f" (did you mean {close[0]}?)" if close else
            " (see designs/index/architecture-index.md#diagrams, or the diagram_id of a proposed diagram file)")


def file_problems(rel: str, text: str, known: dict[str, Source]) -> list[Problem]:
    """Every diagram problem of one feature file: structure, unknown IDs, stale or edited blocks."""
    return [p for p, _ in _classified(rel, text, known)]


def _classified(rel: str, text: str, known: dict[str, Source]) -> list[tuple[Problem, bool]]:
    """(problem, regenerable): regenerable problems (a stale, empty or hand-edited block in a
    well-formed file) are what `index` fixes; any other problem stops `index` for the file."""
    blocks, structural = scan(text)
    return ([(Problem(rel, f"line {n}: {msg}"), False) for n, msg in structural]
            + [(p, False) for p in _content_problems(rel, text, known, blocks, unusable=True)]
            + [(p, True) for p in _content_problems(rel, text, known, blocks)])


def _content_problems(rel: str, text: str, known: dict[str, Source], blocks, unusable: bool = False) -> list[Problem]:
    """unusable=True: IDs that cannot be resolved; False: blocks that differ from their source."""
    out = []
    lines = text.replace("\r\n", "\n").split("\n")
    for b in blocks:
        if not b.diagram_id:
            continue
        source = known.get(b.diagram_id)
        if source is None:
            if unusable:
                out.append(Problem(rel, f"line {b.start + 1}: unknown diagram ID {b.diagram_id!r}"
                                        f"{_suggest(b.diagram_id, known)}"))
            continue
        if source.problem:
            if unusable:
                out.append(Problem(rel, f"line {b.start + 1}: diagram ID {b.diagram_id!r} {source.problem}"))
            continue
        if not source.closed:
            if unusable:
                out.append(Problem(rel, f"line {b.start + 1}: the source Mermaid block of {b.diagram_id} in "
                                        f"{source.path} has no closing fence; fix the source first"))
            continue
        if unusable:
            continue
        current, expected = lines[b.start + 1:b.end], render(source, rel)
        if current == expected:
            continue
        if not current:
            what = "is empty"
        elif current[1:] != expected[1:]:
            what = (f"differs from the authoritative Mermaid source in {source.path}"
                    f"{'#' + source.anchor if source.anchor else ''} (stale, or edited by hand)")
        else:
            what = "has a caption or source link that differs from the generated one (edited by hand?)"
        out.append(Problem(rel, f"line {b.start + 1}: the diagram block for {b.diagram_id} {what}: "
                                "run `python -m tools.design index`"))
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
        out += [p for p, regenerable in _classified(f.path, text, known) if regenerable]
    return out


def blocking(text: str, rel: str, known: dict[str, Source]) -> list[str]:
    """Why `index` must leave this file's diagram blocks alone (empty: it may refresh them)."""
    return [p.message for p, regenerable in _classified(rel, text, known) if not regenerable]


def apply(text: str, rel: str, known: dict[str, Source]) -> str:
    """The file text with every diagram block regenerated; only lines between markers change."""
    blocks, _ = scan(text)
    keep = split_keep(text)
    for b in reversed(blocks):
        keep = split_keep(replace_span(keep, b.start, b.end, render(known[b.diagram_id], rel)))
    return "".join(keep)


def split_keep(text: str) -> list[str]:
    """Lines with their endings, split on '\\n' only, exactly as `scan` counts them (unlike
    str.splitlines, which also breaks on U+2028, form feed, a lone CR and others)."""
    parts = re.split(r"(?<=\n)", text)
    return parts[:-1] if parts and parts[-1] == "" else parts


def refresh(root: Path) -> list[tuple[str, int]]:
    """Regenerate stale diagram blocks in feature files with valid metadata and no diagram
    problem. Returns (path, number of blocks) for each rewritten file."""
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
        new = apply(text, f.path, known)
        if new.replace("\r\n", "\n") != text.replace("\r\n", "\n"):
            write_feature_text(path, new)
            changed.append((f.path, len(blocks)))
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
