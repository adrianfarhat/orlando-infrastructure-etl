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
import os
import posixpath
import re
import tempfile
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
    category: str = "other"


def validate_title(title: str) -> str:
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


_validate_title = validate_title                       # the Phase 1 name


def owner_slug(spec: str) -> str:
    """The owner part of a diagram file name: the feature's file name without .md, or its
    folder name for a parent feature's README.md (diagram library 5.1)."""
    name = posixpath.basename(spec)
    if name.lower() == "readme.md":
        return posixpath.basename(posixpath.dirname(spec))
    return name[:-3] if name.lower().endswith(".md") else name


def source_name(spec: str, category: str, title: str) -> str:
    """`<owner-slug>_<category>_<diagram-name>.md` (names are made once and never parsed)."""
    return f"{owner_slug(spec)}_{category}_{slugify(title)}.md"


def new_diagram(root: Path, owner: str, title: str, category: str = "other") -> CreatedDiagram:
    """Create a standalone Mermaid diagram owned by `owner` in the `diagrams/` folder next to
    the owner's specification, with the next diagram ID that was never used, and register it.
    All or nothing (diagram library 8.1): under the registry lock, the file is created
    exclusively and the registry replaced by compare-and-swap; on any failure the new file is
    removed and the registry is left as it was."""
    from . import registry
    from .ids import committed_ids, next_diagram_id
    root = Path(root).resolve()
    title = validate_title(title)
    owner = (owner or "").strip().upper()
    if not FEATURE_ID.match(owner):
        raise DesignError(f"--feature must be a feature ID such as FD-0001, not {owner!r}")
    if category not in registry.CATEGORIES:
        raise DesignError(f"--category must be one of {', '.join(registry.CATEGORIES)}, not {category!r}")
    features, _ = discover(root)
    dupes = duplicate_ids(features)
    if dupes:
        raise DesignError("duplicate feature IDs must be fixed first: " + "; ".join(p.message for p in dupes[:3]))
    matches = [f for f in features if f.feature_id == owner]
    if not matches:
        raise DesignError(f"no feature has the ID {owner}")
    spec = matches[0].path
    folder = posixpath.join(posixpath.dirname(spec), "diagrams")
    rel = posixpath.join(folder, source_name(spec, category, title))
    target = root / rel
    if target.exists():
        raise DesignError(f"{rel} already exists; nothing was overwritten (choose another title or category)")
    try:
        template = (root / DIAGRAM_TEMPLATE).read_bytes().decode("utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError) as exc:
        raise DesignError(f"cannot read the template {DIAGRAM_TEMPLATE} ({type(exc).__name__})") from None
    with registry.lock(root):
        reg = registry.load(root)
        doc = registry._writable(reg)
        in_tree = registry.all_ids(root, reg) + [_text(r.diagram_id) for r in diagram_records(root)]
        diagram_id = next_diagram_id(owner, in_tree, committed_ids(root))   # stops here without full history
        text = _render(template, diagram_id, owner, title, posixpath.relpath(spec, folder))
        create_exclusively(target, text, rel, root)
        try:
            doc["diagrams"].append(registry.entry_map(diagram_id, title, "feature", owner, "mermaid-md", category, rel))
            registry.save(root, doc, reg.sha)
        except BaseException as exc:                    # roll back: only the file this command created
            try:
                target.unlink()
            except OSError:
                pass
            if isinstance(exc, DesignError):
                raise DesignError(f"{exc}; {rel} was not kept") from None
            raise
    registry.write_diagram_index(root)                  # generated from the registry, like the feature index
    return CreatedDiagram(rel, diagram_id, owner, category)


def guard_write(root: Path, path: Path) -> None:
    """Every file the diagram commands write goes through here: files under docs/architecture/
    (including docs/architecture/diagrams/) belong to technical-lead and change only through
    its documentation workflow, so the tooling never writes them (diagram library 5.2, 6.5)."""
    try:
        rel = Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        raise DesignError(f"{path} is outside the repository; nothing was written") from None
    if rel == "docs/architecture" or rel.startswith("docs/architecture/"):
        raise DesignError(f"{rel} is under docs/architecture/, which changes only through technical-lead's "
                          "documentation workflow; nothing was written")


def create_exclusively(target: Path, text: str, rel: str, root: Path | None = None) -> None:
    """Write `text` to a temporary file in the same folder, then link it to `target` with an
    operation that fails if the name exists: the file appears whole or not at all."""
    if root is not None:
        guard_write(root, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".diagram.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(text.encode("utf-8"))
        try:
            os.link(tmp, target)
        except FileExistsError:
            raise DesignError(f"{rel} already exists; nothing was overwritten") from None
        except OSError:                                  # a file system without hard links
            try:
                with open(target, "x", encoding="utf-8", newline="\n") as handle:
                    handle.write(text)
            except FileExistsError:
                raise DesignError(f"{rel} already exists; nothing was overwritten") from None
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def retitled(root: Path, rel: str, title: str) -> str:
    """The source text with its front matter `title:` line changed (used by
    `registry relink --title`); refuses when there is not exactly one title line."""
    text = (Path(root) / rel).read_bytes().decode("utf-8")
    front, _ = split_front_matter(text)
    if front is None:
        raise DesignError(f"{rel} has no front matter")
    lines = text.split("\n")
    end = next(i for i in range(1, len(lines)) if lines[i].rstrip("\r") == "---")
    hits = [i for i in range(1, end) if re.match(r"title\s*:", lines[i])]
    if len(hits) != 1:
        raise DesignError(f"{rel} needs exactly one `title:` line in its front matter")
    i = hits[0]
    newline = "\r" if lines[i].endswith("\r") else ""
    comment = re.search(r"\s+#.*$", lines[i].rstrip("\r"))
    lines[i] = f"title: {json.dumps(title, ensure_ascii=False)}" + (comment.group(0) if comment else "") + newline
    return "\n".join(lines)


def write_atomically(path: Path, text: str, root: Path | None = None) -> None:
    if root is not None:
        guard_write(root, path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".diagram.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(text.encode("utf-8"))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


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
