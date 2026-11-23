"""The interface between the Feature Designer (VS Code, T-97) and the design tooling.

    python -m tools.design designer  < request.json  > response.json

One JSON request on stdin, one JSON response on stdout (UTF-8, sorted keys, ASCII-escaped,
so the same input always gives the same bytes). Nothing here writes a file: operations that
change a document return *proposed edits*, and the editor applies them through its own
editing API (undo/redo, unsaved buffers). Every edit response carries `base`, the SHA-256
and line count of the text it was computed from, so the editor can reject an edit when the
document changed in the meantime.

Requests (all carry "version": 1 and "op"):
- {"op": "library"}
    the diagram library from the diagram registry: architecture (document-owned) diagrams
    grouped by document, and feature-owned diagrams grouped by their owner. Each item has its
    stable `id`, its `aliases` (former catalog IDs, which keep resolving), `format`,
    `category` and `status`; architecture diagrams not registered yet keep their catalog ID.
- {"op": "resolve", "diagram_id": <ID or alias>}
    the one authoritative source of a diagram: its stable ID, aliases, kind, format, path,
    1-based line of the Mermaid block, title, owner, category, status, the editor to open it
    with ("text" or "architecture-docs") and a problem ('' when it can be used). Read only.
- {"op": "insert", "path": <feature file>, "text": <its current, possibly unsaved text>,
   "at": <0-based line index to insert before>, "diagram_id": <ID>}
    the lines of a T-96 diagram block for that position, or a refusal when the position is
    not allowed (outside the six sections, not at a block boundary, inside a code block,
    table, <details> group or generated block) or the result would add a problem.
- {"op": "refresh", "path": ..., "text": ...}
    per-block edits that bring the diagram blocks of that text up to date with their sources
    (none when the file has a problem that `index` would refuse to touch).
- {"op": "blocks", "path": ..., "text": ...}
    the state of every diagram block in that text (T-97 PR B), so the editor can render each
    block from its authoritative source: `state` is current, fingerprint (only the marker is
    out of date), empty, outdated (the source changed, the copy was not edited), conflict
    (E15; `conflict` says which case), retired (E11), missing (E6/E7), unknown (E1) or problem;
    `generated` is what the source generates now ([] when it cannot be used), `embedded` the
    copy in the text, `diff` a unified diff between them for outdated and conflicting blocks,
    `source` the resolved source (as `resolve` describes it, null when unknown) and `message`
    the problem `check` reports for that block. Also `blocking`, `conflicts` and `stale` (the
    number of blocks `index` would refresh), as `refresh` reports them. Read only.
- {"op": "diagram-name", "owner": <feature ID>, "title": ..., "category": ...}
    the repository path `new diagram` would create for these values, and a problem ('' when
    it can be created). Read only: nothing is created or reserved.
- {"op": "remove-block", "path": ..., "text": ..., "line": <0-based start-marker line>}
    the edit that removes a diagram block whose diagram was retired (E11), with one adjacent
    blank line; refused for any other block.
- {"op": "feature-index", "texts": {<feature path>: <unsaved text>, ...}}
    the complete text of designs/index/feature-index.md as `index` would write it, using the
    given unsaved texts instead of those files on disk; and, in `diagram_index`, the same for
    designs/index/diagram-index.md (from the files on disk; null when there is nothing to index).

Edits are {"start": s, "end": e, "lines": [...]}: replace lines s..e-1 (0-based, counted by
"\\n" exactly like the T-96 scanner; e == s inserts) with `lines` (no line endings; the
editor uses the document's own line ending, also reported as `newline`). Edits in one
response never overlap and are listed top to bottom; apply them all as one edit.

Exit codes: 0 the response has "ok": true; 1 the request was refused ("ok": false, error
code "refused"); 2 a malformed request or an internal error ("ok": false, other codes).
"""

from __future__ import annotations

import difflib
import hashlib
import json
import posixpath
import re
from collections import Counter
from pathlib import Path

from . import diagrams, ownership
from .architecture import catalog, documents
from .ids import DIAGRAM_ID
from .workspace import (FEATURES, INDEX, SECTIONS, DesignError, _fence_step, discover, marker_span, render_index)

VERSION = 1
EXIT_OK, EXIT_REFUSED, EXIT_BAD = 0, 1, 2
_LINE_PREFIX = re.compile(r"^line \d+: ")
_ATX = re.compile(r"^ {0,3}#{1,6}(\s|$)")
_BREAK = re.compile(r"^ {0,3}((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})$")


class Refused(Exception):
    """The request is valid but cannot be carried out (exit 1)."""


class BadRequest(Exception):
    """The request is malformed (exit 2)."""


def dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def _lines(text: str) -> list[str]:
    return [line[:-1] if line.endswith("\r") else line for line in text.split("\n")]


def _base(text: str) -> dict:
    return {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "line_count": len(text.split("\n"))}


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


# --------------------------------------------------------------------------- library

def library(root: Path) -> dict:
    from . import registry
    known = diagrams.sources(root)
    reg = registry.load(root)
    by_alias = {a: e for e in reg.entries for a in e.aliases}
    groups: dict[str, dict] = {}
    for d in catalog(documents(root)):
        g = groups.setdefault(d.document, {"document": d.document, "title": d.title or posixpath.basename(d.document),
                                           "diagrams": []})
        e = by_alias.get(d.diagram_id)
        ident = e.diagram_id if e is not None else d.diagram_id
        s = known.get(ident)
        g["diagrams"].append({"id": ident, "aliases": list(e.aliases) if e is not None else [], "kind": "current",
                              "owner": None, "path": d.document, "line": d.line,
                              "format": e.format if e is not None else "mermaid-embedded",
                              "category": e.category if e is not None else None,
                              "status": e.status if e is not None else "unregistered",
                              "title": d.heading.text if d.heading is not None and d.heading.text else g["title"],
                              "problem": s.problem if s else ""})
    features, _ = discover(root)
    owned = {f.feature_id: {"feature_id": f.feature_id, "title": f.title or "", "path": f.path, "diagrams": []}
             for f in features if f.feature_id}
    issues: dict[str, str] = {}
    for p in ownership.problems(root, features):
        issues.setdefault(p.path, p.message)
    unowned = []
    entries = {e.diagram_id: e for e in reg.entries}
    for s in diagrams.proposed_sources(root):
        e = entries.get(s.diagram_id)
        entry = {"id": s.diagram_id, "aliases": list(e.aliases) if e else [], "kind": "proposed",
                 "owner": s.owner or None, "path": s.path, "line": s.line, "title": s.title,
                 "format": e.format if e else "mermaid-md", "category": e.category if e else None,
                 "status": e.status if e else "active", "problem": s.problem or issues.get(s.path, "")}
        (owned[s.owner]["diagrams"] if s.owner in owned else unowned).append(entry)
    registered = {e.path for e in reg.entries}
    for f in registry.source_files(root):              # unregistered sources: shown with their problem (E5)
        if f.path not in registered and f.path.startswith(FEATURES + "/"):
            unowned.append({"id": f.diagram_id, "aliases": [], "kind": "proposed", "owner": f.feature_id or None,
                            "path": f.path, "line": 0, "title": f.title, "format": "mermaid-md", "category": None,
                            "status": "unregistered",
                            "problem": f"not registered: run `python -m tools.design registry adopt {f.path} "
                                       "--category <category>` (E5)"})

    def order(entry):
        m = DIAGRAM_ID.match(entry["id"])
        return (0, int(m.group(2)), entry["path"]) if m else (1, 0, entry["id"] + "\0" + entry["path"])
    for g in owned.values():
        g["diagrams"].sort(key=order)
    return {"architecture": [groups[k] for k in sorted(groups)],
            "features": [owned[k] for k in sorted(owned)],
            "unowned": sorted(unowned, key=lambda e: e["path"])}


# --------------------------------------------------------------------------- positions

def position_problem(text: str, at: int) -> str:
    """Why a block may not be inserted before 0-based line `at` ('' when it may)."""
    lines = _lines(text)
    if not isinstance(at, int) or isinstance(at, bool) or not 0 <= at <= len(lines):
        return f"the position must be a line index between 0 and {len(lines)}"
    body = diagrams._body_start(lines)
    first = end = None
    fence, depth, seen_six = None, 0, False
    fence_before_at = depth_before_at = None
    for i in range(body, len(lines)):
        if i == at:
            fence_before_at, depth_before_at = fence, depth
        line = lines[i]
        inside = fence is not None
        fence, is_fence = _fence_step(line, fence)
        if inside or is_fence:
            continue
        depth += len(re.findall(r"<details[\s>]", line, re.I)) - len(re.findall(r"</details>", line, re.I))
        if first is None:
            if line.strip() == SECTIONS[0]:
                first = i
            continue
        if line.startswith("## 6."):
            seen_six = True
        elif seen_six and end is None and (_BREAK.match(line) or re.match(r"^#{1,2}\s", line)
                                           or re.match(r"^\s*<details[\s>]", line, re.I)):
            end = i
    if at == len(lines):
        fence_before_at, depth_before_at = fence, depth
    end = len(lines) if end is None else end
    if first is None:
        return f"the document has no `{SECTIONS[0]}` section"
    if not first < at <= end:
        return "blocks can be inserted only inside the six sections"
    if fence_before_at is not None:
        return "not inside a code block"
    if depth_before_at and depth_before_at > 0:
        return "not inside a <details> group"
    from .dependencies import RELATED_END, RELATED_START
    spans = [marker_span(lines, "<!-- summary:start", "<!-- summary:end -->"),
             marker_span(lines, RELATED_START, RELATED_END)]
    if any(status == "ok" and s < at <= e for status, s, e in spans):
        return "not inside a generated summary or Related features block"
    if any(b.start < at <= b.end for b in diagrams.scan(text)[0]):
        return "not inside a generated diagram block"
    prev = lines[at - 1] if at > 0 else ""
    nxt = lines[at] if at < len(lines) else ""
    if prev.lstrip().startswith("|") and nxt.lstrip().startswith("|"):
        return "not inside a table"
    if prev.strip() and nxt.strip() and not _ATX.match(prev) and not diagrams.END_RE.match(prev.strip()):
        return "not at a block boundary (inside a paragraph, list or quote)"
    return ""


# --------------------------------------------------------------------------- operations

def _messages(rel: str, text: str, known) -> Counter:
    return Counter(_LINE_PREFIX.sub("", p.message) for p in diagrams.file_problems(rel, text, known))


def insert(root: Path, rel: str, text: str, at: int, diagram_id: str) -> dict:
    reason = position_problem(text, at)
    if reason:
        raise Refused(f"cannot insert here: {reason}")
    known = diagrams.sources(root)
    source = known.get(diagram_id)
    if source is None:
        raise Refused(f"unknown diagram ID {diagram_id!r}")
    if source.problem:
        raise Refused(f"diagram {diagram_id} cannot be inserted: {source.problem}")
    lines = _lines(text)
    generated = diagrams.render(source, rel)
    block = [diagrams.start_marker(diagram_id, generated), *generated, diagrams.END]
    before = [""] if at > 0 and lines[at - 1].strip() else []
    after = [""] if at < len(lines) and lines[at].strip() else []
    new = before + block + after
    added = _messages(rel, "\n".join(lines[:at] + new + lines[at:]), known) - _messages(rel, "\n".join(lines), known)
    if added:
        raise Refused("the insertion would add a problem: " + "; ".join(sorted(added)))
    return {"base": _base(text), "newline": _newline(text), "edits": [{"start": at, "end": at, "lines": new}]}


def refresh(root: Path, rel: str, text: str) -> dict:
    """Edits for the refreshable blocks only (each replaces the start marker, for its new
    fingerprint, and the generated lines). Conflicts (E15) are listed, never edited."""
    known = diagrams.sources(root)
    blocking = diagrams.blocking(text, rel, known)
    edits = []
    if not blocking:
        for start, end, new in diagrams.regenerated(text, rel, known):
            edits.append({"start": start, "end": end, "lines": new})
    return {"base": _base(text), "newline": _newline(text), "blocking": blocking,
            "conflicts": diagrams.conflicts(text, rel, known) if not blocking else [], "edits": edits}


def resolve(root: Path, ident: str) -> dict:
    """The authoritative source of one diagram (diagram library 6.2); read only."""
    from . import registry
    known = diagrams.sources(root)
    described = _describe(ident, registry.load(root).lookup(), known)
    if described is None:
        raise Refused(f"{ident} is not in the registry as an ID or an alias, nor in the architecture catalog (E1)")
    return described


def _describe(ident: str, lookup: dict, known: dict) -> dict | None:
    e = lookup.get(ident)
    s = known.get(ident)
    if e is None and s is None:
        return None
    if e is not None:
        canonical = known.get(e.diagram_id, s)
        return {"id": e.diagram_id, "aliases": list(e.aliases), "kind": canonical.kind if canonical else "missing",
                "format": e.format, "path": e.path, "line": canonical.line if canonical else 0, "title": e.title,
                "owner": {"kind": e.owner_kind, "ref": e.owner_ref}, "category": e.category, "status": e.status,
                "editor": "architecture-docs" if e.owner_kind == "document" else "text",
                "problem": canonical.problem if canonical else "cannot be found (E7)"}
    return {"id": ident, "aliases": [], "kind": s.kind, "format": "mermaid-embedded", "path": s.path, "line": s.line,
            "title": s.title, "owner": None, "category": None, "status": "unregistered",
            "editor": "architecture-docs", "problem": s.problem}


BLOCK_STATES = {"current": "current", "fp-only": "fingerprint", "empty": "empty", "case1": "outdated",
                "case2": "conflict", "case3": "conflict", "legacy": "conflict"}


def blocks(root: Path, rel: str, text: str) -> dict:
    """Every diagram block of `text` with its state, its source and both versions (PR B)."""
    from . import registry
    known = diagrams.sources(root)
    lookup = registry.load(root).lookup()
    found, _ = diagrams.scan(text)
    lines = text.replace("\r\n", "\n").split("\n")
    messages: dict[int, str] = {}
    for p in diagrams.file_problems(rel, text, known):
        n = re.match(r"line (\d+): ", p.message)
        if n:
            messages.setdefault(int(n.group(1)) - 1, _LINE_PREFIX.sub("", p.message))
    out = []
    for b in found:
        embedded = lines[b.start + 1:b.end]
        s = known.get(b.diagram_id) if b.diagram_id else None
        item = {"start": b.start, "end": b.end, "id": b.diagram_id, "marker": lines[b.start],
                "embedded": embedded, "generated": [],
                "diff": [], "conflict": None, "message": messages.get(b.start, ""),
                "source": _describe(b.diagram_id, lookup, known) if b.diagram_id else None}
        if not b.diagram_id:
            item["state"] = "problem"
        elif s is None:
            item["state"] = "unknown"
        elif s.kind == "retired":
            item["state"] = "retired"
        elif s.kind == "missing":
            item["state"] = "missing"
        elif s.problem or not s.closed:
            item["state"] = "problem"
        else:
            expected = diagrams.render(s, rel)
            kind = diagrams.classify(b, embedded, expected)
            item["generated"] = expected
            item["state"] = BLOCK_STATES[kind]
            if item["state"] == "conflict":
                item["conflict"] = kind
            if item["state"] in ("conflict", "outdated"):
                item["diff"] = list(difflib.unified_diff(embedded, expected, "copy in this document",
                                                         f"generated from {s.path}", n=2, lineterm=""))
        if not item["message"] and item["state"] in ("unknown", "retired", "missing", "problem") and s is not None:
            item["message"] = f"diagram ID {b.diagram_id!r} {s.problem}" if s.problem else ""
        out.append(item)
    summary = refresh(root, rel, text)
    return {"base": summary["base"], "blocks": out, "blocking": summary["blocking"],
            "conflicts": summary["conflicts"], "stale": len(summary["edits"])}


def diagram_name(root: Path, owner, title, category) -> dict:
    """The path `new diagram` would create, and why it cannot be created ('' when it can)."""
    from . import registry
    from .ids import FEATURE_ID
    try:
        clean = ownership.validate_title(title)
        if not isinstance(owner, str) or not FEATURE_ID.match(owner):
            raise DesignError(f"the owner must be a feature ID such as FD-0001, not {owner!r}")
        if category not in registry.CATEGORIES:
            raise DesignError(f"the category must be one of {', '.join(registry.CATEGORIES)}")
        features, _ = discover(root)
        spec = next((f.path for f in features if f.feature_id == owner), None)
        if spec is None:
            raise DesignError(f"no feature has the ID {owner}")
        rel = posixpath.join(posixpath.dirname(spec), "diagrams", ownership.source_name(spec, category, clean))
    except DesignError as exc:
        return {"path": "", "problem": str(exc)}
    return {"path": rel, "problem": f"{rel} already exists; choose another name or category" if (root / rel).exists()
            else ""}


def remove_block(root: Path, rel: str, text: str, line: int) -> dict:
    """The edit that removes one block whose diagram was retired (diagram library E11)."""
    known = diagrams.sources(root)
    block = next((b for b in diagrams.scan(text)[0] if b.start == line), None)
    if block is None:
        raise Refused(f"there is no diagram block starting at line {line + 1}")
    s = known.get(block.diagram_id) if block.diagram_id else None
    if s is None or s.kind != "retired":
        raise Refused(f"only a block whose diagram was retired can be removed here; {block.diagram_id or 'this block'} "
                      "is not retired")
    lines = _lines(text)
    start, end = block.start, block.end + 1
    if end < len(lines) and not lines[end].strip() and (start == 0 or not lines[start - 1].strip()):
        end += 1                                        # the blank line the insertion added after it
    elif end == len(lines) and start > 0 and not lines[start - 1].strip():
        start -= 1
    return {"base": _base(text), "newline": _newline(text), "edits": [{"start": start, "end": end, "lines": []}]}


def _generated(root: Path, rel: str, content: str) -> dict:
    path = root / rel
    disk = path.read_bytes() if path.is_file() else None
    current = disk.decode("utf-8", "replace") if disk is not None else None
    return {"path": rel, "content": content, "base": _base(current) if current is not None else None,
            "changed": current is None or current.replace("\r\n", "\n") != content}


def feature_index(root: Path, texts: dict[str, str]) -> dict:
    from . import registry
    out = _generated(root, INDEX, render_index(root, texts))
    out["diagram_index"] = (None if registry._nothing_to_index(root)
                            else _generated(root, registry.DIAGRAM_INDEX, registry.render_diagram_index(root)))
    return out


# --------------------------------------------------------------------------- requests

def _feature_path(root: Path, value) -> str:
    if not isinstance(value, str) or not value:
        raise BadRequest("`path` must be a feature file path such as designs/features/x.md")
    rel = posixpath.normpath(value.replace("\\", "/"))
    if rel.startswith("../") or rel.startswith("/") or re.match(r"[A-Za-z]:", rel) or not rel.startswith(FEATURES + "/"):
        raise BadRequest(f"`path` must be a feature file under {FEATURES}/: {value!r}")
    features, _ = discover(root)
    if rel not in {f.path for f in features}:
        raise BadRequest(f"{rel} is not a feature specification")
    return rel


def _text(value, name: str = "text") -> str:
    if not isinstance(value, str):
        raise BadRequest(f"`{name}` must be the document text (a string)")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise BadRequest(f"`{name}` is not valid Unicode text (it contains a lone surrogate)") from None
    return value


def handle(root: Path, request) -> tuple[dict, int]:
    """(response, exit code) for one request."""
    try:
        if not isinstance(request, dict):
            raise BadRequest("the request must be a JSON object")
        if request.get("version") != VERSION:
            raise BadRequest(f"unsupported request version {request.get('version')!r} (this tool speaks {VERSION})")
        op = request.get("op")
        if op == "library":
            result = library(root)
        elif op == "insert":
            at, did = request.get("at"), request.get("diagram_id")
            if not isinstance(at, int) or isinstance(at, bool):
                raise BadRequest("`at` must be a line index (an integer)")
            if not isinstance(did, str) or not did:
                raise BadRequest("`diagram_id` must be a diagram ID")
            result = insert(root, _feature_path(root, request.get("path")), _text(request.get("text")), at, did)
        elif op == "refresh":
            result = refresh(root, _feature_path(root, request.get("path")), _text(request.get("text")))
        elif op == "resolve":
            did = request.get("diagram_id")
            if not isinstance(did, str) or not did:
                raise BadRequest("`diagram_id` must be a diagram ID or alias")
            result = resolve(root, did)
        elif op == "blocks":
            result = blocks(root, _feature_path(root, request.get("path")), _text(request.get("text")))
        elif op == "diagram-name":
            result = diagram_name(root, request.get("owner"), request.get("title"), request.get("category"))
        elif op == "remove-block":
            line = request.get("line")
            if not isinstance(line, int) or isinstance(line, bool):
                raise BadRequest("`line` must be the 0-based line of the block's start marker (an integer)")
            result = remove_block(root, _feature_path(root, request.get("path")), _text(request.get("text")), line)
        elif op == "feature-index":
            texts = request.get("texts", {})
            if not isinstance(texts, dict):
                raise BadRequest("`texts` must map feature paths to their unsaved text")
            result = feature_index(root, {_feature_path(root, k): _text(v, k) for k, v in texts.items()})
        else:
            raise BadRequest(f"unknown op {op!r} (library, insert, refresh, resolve, blocks, diagram-name, "
                             "remove-block, feature-index)")
        return {"version": VERSION, "op": op, "ok": True, **result}, EXIT_OK
    except Refused as exc:
        return {"version": VERSION, "ok": False, "error": {"code": "refused", "message": str(exc)}}, EXIT_REFUSED
    except BadRequest as exc:
        return {"version": VERSION, "ok": False, "error": {"code": "bad-request", "message": str(exc)}}, EXIT_BAD
    except DesignError as exc:
        return {"version": VERSION, "ok": False, "error": {"code": "workspace", "message": str(exc)}}, EXIT_BAD
    except Exception as exc:                        # the editor always gets JSON (QA D2)
        return {"version": VERSION, "ok": False,
                "error": {"code": "internal", "message": f"{type(exc).__name__}: {exc}"[:500]}}, EXIT_BAD
