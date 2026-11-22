"""Feature-owned diagrams (T-97 Phase 1).

A diagram file in a `diagrams/` folder under designs/features/ that has a `diagram_id` is a
named, attachable diagram, and it is owned by exactly one feature:
- `feature_id` is required and must be an existing feature's ID (the owner);
- `diagram_id` is the owner's ID plus `-D` and a number (FD-0001-D1), unique across all
  diagram files, independent of the file's name and folder, and never reused (ids.py);
- `title` is required: it is the diagram's readable name in the Feature Designer library.
Files without a `diagram_id` (for example a fresh copy of the template) are not attachable
and are not checked here, as before. Nothing here ever renumbers or rewrites a file:
`check` reports what to fix, and `new diagram` only creates new files.
"""

from __future__ import annotations

import difflib
import json
import posixpath
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .ids import DIAGRAM_ID, FEATURE_ID
from .workspace import (FEATURES, MAX_FILE_BYTES, MAX_NAME, DesignError, Feature, Problem, _yaml, discover,
                        duplicate_ids, slugify, split_front_matter)

DIAGRAM_TEMPLATE = "designs/templates/diagram.md"


@dataclass(frozen=True)
class DiagramFile:
    path: str             # repository-relative
    diagram_id: object    # the raw metadata values (validated by problems())
    feature_id: object
    title: object


def diagram_records(root: Path) -> list[DiagramFile]:
    """Every diagram file whose metadata could be read, in path order (unreadable files and
    invalid YAML are reported by the link and reference checks)."""
    from ruamel.yaml.error import YAMLError
    from .links import diagram_files
    out = []
    for rel in diagram_files(root):
        try:
            if (root / rel).stat().st_size > MAX_FILE_BYTES:
                continue
            front, _ = split_front_matter((root / rel).read_bytes().decode("utf-8"))
            meta = _yaml().load(front) if front is not None else None
        except (OSError, UnicodeDecodeError, YAMLError):
            continue
        if isinstance(meta, dict):
            out.append(DiagramFile(rel, meta.get("diagram_id"), meta.get("feature_id"), meta.get("title")))
    return out


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def problems(root: Path, features: list[Feature]) -> list[Problem]:
    known = sorted({f.feature_id for f in features if f.feature_id})
    seen: dict[str, list[str]] = {}
    out = []
    for r in diagram_records(root):
        did = _text(r.diagram_id)
        if not did or re.search(r"\s", did):
            continue                                     # not attachable, or reported by the diagram-block check
        m = DIAGRAM_ID.match(did)
        if not m:
            out.append(Problem(r.path, f"diagram_id {did!r} must be the owning feature's ID plus -D and a number, "
                                       "for example FD-0001-D1"))
        owner = _text(r.feature_id)
        if not owner:
            out.append(Problem(r.path, "feature_id is required: the ID of the feature that owns this diagram"
                                       + (f" (for {did}: {m.group(1)})" if m else "")))
        elif not FEATURE_ID.match(owner):
            out.append(Problem(r.path, f"feature_id must look like FD-0001, found {r.feature_id!r}"))
        elif owner not in known:
            close = difflib.get_close_matches(owner, known, n=1, cutoff=0.6)
            out.append(Problem(r.path, f"feature_id {owner} is not an existing feature"
                                       + (f" (did you mean {close[0]}?)" if close else "")
                                       + ": set it to the ID of the feature that owns this diagram"))
        elif m and m.group(1) != owner:
            out.append(Problem(r.path, f"diagram_id {did} does not belong to its owner {owner}: a diagram's ID starts "
                                       f"with its owner's feature ID. IDs are never renumbered automatically: correct "
                                       f"feature_id, or create the diagram again with `python -m tools.design new "
                                       f"diagram --feature {owner}`"))
        if not _text(r.title):
            out.append(Problem(r.path, "title is required: the diagram's readable name"))
        seen.setdefault(did, []).append(r.path)
    for did, paths in sorted(seen.items()):
        if len(paths) > 1:
            for p in paths:
                others = ", ".join(x for x in paths if x != p)
                out.append(Problem(p, f"duplicate diagram_id {did} (also in {others}): each diagram needs its own ID; "
                                      "give the newer one a new ID with `python -m tools.design new diagram`"))
    return out


# --------------------------------------------------------------------------- new diagram

@dataclass(frozen=True)
class CreatedDiagram:
    path: str
    diagram_id: str
    owner: str


def _validate_title(title: str) -> str:
    if not isinstance(title, str):
        raise DesignError("the diagram title must be text")
    clean = " ".join(title.split())
    if not clean:
        raise DesignError("the diagram title is empty")
    if len(clean) > MAX_NAME:
        raise DesignError(f"the diagram title is longer than {MAX_NAME} characters")
    if any(unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn") for ch in title):
        raise DesignError("the diagram title contains a control or invisible character")
    return clean


def new_diagram(root: Path, owner: str, title: str) -> CreatedDiagram:
    """Create a diagram file owned by `owner` in the `diagrams/` folder next to the owner's
    specification, with the next diagram ID that was never used (working tree and history)."""
    from .ids import committed_ids, next_diagram_id
    root = Path(root).resolve()
    title = _validate_title(title)
    owner = (owner or "").strip().upper()
    if not FEATURE_ID.match(owner):
        raise DesignError(f"--feature must be a feature ID such as FD-0001, not {owner!r}")
    features, _ = discover(root)
    dupes = duplicate_ids(features)
    if dupes:
        raise DesignError("duplicate feature IDs must be fixed first: " + "; ".join(p.message for p in dupes[:3]))
    matches = [f for f in features if f.feature_id == owner]
    if not matches:
        raise DesignError(f"no feature has the ID {owner}")
    spec = matches[0].path
    folder = posixpath.join(posixpath.dirname(spec), "diagrams")
    target = root / folder / f"{slugify(title)}.md"
    rel = posixpath.join(folder, target.name)
    if target.exists():
        raise DesignError(f"{rel} already exists; nothing was overwritten (choose another title)")
    try:
        template = (root / DIAGRAM_TEMPLATE).read_bytes().decode("utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError) as exc:
        raise DesignError(f"cannot read the template {DIAGRAM_TEMPLATE} ({type(exc).__name__})") from None
    in_tree = [_text(r.diagram_id) for r in diagram_records(root)]
    diagram_id = next_diagram_id(owner, in_tree, committed_ids(root))   # stops here without full history
    text = _render(template, diagram_id, owner, title, posixpath.relpath(spec, folder))
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(target, "x", encoding="utf-8", newline="\n") as handle:     # never overwrites
            handle.write(text)
    except FileExistsError:
        raise DesignError(f"{rel} already exists; nothing was overwritten") from None
    return CreatedDiagram(rel, diagram_id, owner)


def _render(template: str, diagram_id: str, owner: str, title: str, spec_link: str) -> str:
    def meta(key: str, value: str, text: str) -> str:
        pattern = re.compile(rf'^{key}: ""', re.M)
        if len(pattern.findall(text)) != 1:
            raise DesignError(f"the template {DIAGRAM_TEMPLATE} needs exactly one empty `{key}: \"\"` line")
        return pattern.sub(lambda _m: f"{key}: {json.dumps(value, ensure_ascii=False)}", text, count=1)
    text = meta("diagram_id", diagram_id, template)
    text = meta("title", title, text)
    text = meta("feature_id", owner, text)
    text = text.replace("[Diagram title]", title, 1)
    text = text.replace("[feature ID plus a number, e.g. FD-0001-D1]", f"`{diagram_id}`", 1)
    text = text.replace("[feature ID, with a relative link to its specification]", f"[{owner}]({spec_link})", 1)
    return text
