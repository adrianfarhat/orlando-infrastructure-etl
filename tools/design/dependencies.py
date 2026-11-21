"""Feature dependencies (T-94 Phase 2, M2): read depends_on, derive "used by", and generate
each feature's "Related features" rows and the feature index columns.

A prerequisite is declared once, in the depends_on list of the feature that needs it
(designs/DECISIONS.md). Everything else is derived from those lists and identified by
feature ID, so moving or renaming a file changes only the generated links.

Generated rows sit between RELATED_START... and RELATED_END in each specification; only
those lines are ever rewritten (by `index`, and by New Feature when it moves a parent).
Every generated relationship is marked PROPOSED: no evidence field exists yet.

The graph's own consistency is checked here, because the graph is built here: an unknown
feature ID, a feature that depends on itself, an ID listed twice, and dependency cycles
(reported for review, never resolved). Link and reference checks are M3.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from pathlib import Path

from .workspace import (FEATURES, ID_RE, Feature, Problem, _cell, _link, discover, marker_span, replace_span,
                        write_feature_text)

RELATED_START = "<!-- related-features:start"
RELATED_END = "<!-- related-features:end -->"
RELATED_HEADER = ["| Feature | Relationship | Reference | Evidence status |", "|---|---|---|---|"]
NO_RELATED = "| — | — | — | — |"
PROPOSED = "🔷 PROPOSED"


@dataclass(frozen=True)
class Dependency:
    target: str                   # a feature ID
    optional: bool
    condition: str | None
    position: int                 # its index in depends_on


@dataclass(frozen=True)
class Graph:
    by_id: dict                   # feature ID -> [Feature, ...] (more than one: a duplicate ID)
    depends: dict                 # feature path -> [Dependency, ...] (as declared, repeats and self removed)
    used_by: dict                 # feature ID -> [(Feature, Dependency), ...]
    problems: tuple


def declared(feature: Feature) -> list[Dependency]:
    """The feature's depends_on entries, when its metadata is valid (Phase 1 format)."""
    if not feature.meta_ok:
        return []
    out = []
    for i, entry in enumerate(feature.meta.get("depends_on") or []):
        if isinstance(entry, dict):
            condition = entry.get("condition")
            out.append(Dependency(entry["id"], entry.get("optional") is True,
                                  condition.strip() if isinstance(condition, str) and condition.strip() else None, i))
        else:
            out.append(Dependency(entry, False, None, i))
    return out


def build(features: list[Feature]) -> Graph:
    by_id: dict[str, list[Feature]] = {}
    for f in features:
        if f.feature_id:
            by_id.setdefault(f.feature_id, []).append(f)
    depends, used_by, problems = {}, {}, []
    for f in features:
        kept, seen = [], set()
        for d in declared(f):
            where = f"depends_on[{d.position}]"
            if d.target == f.feature_id:
                problems.append(Problem(f.path, f"{where}: a feature cannot depend on itself ({d.target})"))
                continue
            if d.target in seen:
                problems.append(Problem(f.path, f"{where}: {d.target} is listed more than once"))
                continue
            seen.add(d.target)
            if d.target not in by_id:
                problems.append(Problem(f.path, f"{where}: {d.target} is not the ID of any feature"))
            kept.append(d)
            used_by.setdefault(d.target, []).append((f, d))
        depends[f.path] = kept
    for target in used_by:
        used_by[target].sort(key=lambda item: (_number(item[0].feature_id), item[0].path))
    graph = Graph(by_id, depends, used_by, ())
    return Graph(by_id, depends, used_by, tuple(problems + _cycles(graph)))


def _number(fid: str | None) -> int:
    m = ID_RE.match(fid or "")
    return int(m.group(1)) if m else 10 ** 6


def _cycles(graph: Graph) -> list[Problem]:
    """One problem per group of features that depend on each other in a circle (a
    strongly connected component of two or more IDs), with one example path."""
    edges: dict[str, set[str]] = {}
    for fid, files in graph.by_id.items():
        for f in files:
            edges.setdefault(fid, set()).update(d.target for d in graph.depends.get(f.path, [])
                                                if d.target in graph.by_id)
    index, low, on_stack, stack, groups, counter = {}, {}, set(), [], [], [0]

    def visit(v):                                     # Tarjan's algorithm, iteratively
        work = [(v, iter(sorted(edges.get(v, ()), key=_number)))]
        index[v] = low[v] = counter[0]; counter[0] += 1
        stack.append(v); on_stack.add(v)
        while work:
            node, children = work[-1]
            child = next(children, None)
            if child is None:
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[node])
                if low[node] == index[node]:
                    group = []
                    while True:
                        w = stack.pop(); on_stack.discard(w); group.append(w)
                        if w == node:
                            break
                    if len(group) > 1:
                        groups.append(sorted(group, key=_number))
            elif child not in index:
                index[child] = low[child] = counter[0]; counter[0] += 1
                stack.append(child); on_stack.add(child)
                work.append((child, iter(sorted(edges.get(child, ()), key=_number))))
            elif child in on_stack:
                low[node] = min(low[node], index[child])

    for v in sorted(edges, key=_number):
        if v not in index:
            visit(v)
    out = []
    for group in sorted(groups, key=lambda g: _number(g[0])):
        start = group[0]
        path = _path_back(start, set(group), edges)
        first = sorted(graph.by_id[start], key=lambda f: f.path)[0]
        out.append(Problem(first.path, f"dependency cycle among {', '.join(group)} (review their depends_on lists; "
                                       f"nothing was changed), for example: {' → '.join(path)}"))
    return out


def _path_back(start: str, members: set[str], edges: dict[str, set[str]]) -> list[str]:
    """The shortest path start → ... → start inside the group (breadth first, lowest IDs first)."""
    previous = {start: None}
    queue = [start]
    while queue:
        node = queue.pop(0)
        for child in sorted(edges.get(node, ()), key=_number):
            if child == start:
                path = [node]                         # walk back from node to start
                while previous[path[-1]] is not None:
                    path.append(previous[path[-1]])
                return list(reversed(path)) + [start]
            if child in members and child not in previous:
                previous[child] = node
                queue.append(child)
    return [start, start]


# --------------------------------------------------------------------------- rendering

def _relationship(direction: str, d: Dependency) -> str:
    if not d.optional:
        return direction
    return f"{direction} (optional{': ' + _cell(d.condition) if d.condition else ''})"


def _feature_cell(fid: str, files: list[Feature]) -> str:
    if not files:
        return f"{fid} · *no feature has this ID*"
    titles = sorted({f.title for f in files if f.title})
    return f"{fid} · {_cell(titles[0]) if len(titles) == 1 else '*' + str(len(files)) + ' files share this ID*'}"


def _reference(files: list[Feature], here: str) -> str:
    if not files:
        return "—"
    return "<br>".join(f"[{_cell(f.path[len(FEATURES) + 1:])}]({_link(posixpath.relpath(f.path, here))})"
                       for f in sorted(files, key=lambda f: f.path))


def render_related(feature: Feature, graph: Graph) -> list[str]:
    """The Related features table (header and rows) for one feature."""
    here = posixpath.dirname(feature.path)
    rows = []
    for d in graph.depends.get(feature.path, []):
        files = graph.by_id.get(d.target, [])
        rows.append(f"| {_feature_cell(d.target, files)} | {_relationship('Depends on', d)} | "
                    f"{_reference(files, here)} | {PROPOSED} |")
    for source, d in graph.used_by.get(feature.feature_id, []) if feature.feature_id else []:
        if source.path == feature.path:
            continue
        rows.append(f"| {_feature_cell(source.feature_id, [source])} | {_relationship('Used by', d)} | "
                    f"{_reference([source], here)} | {PROPOSED} |")
    return RELATED_HEADER + (rows or [NO_RELATED])


def apply_related(text: str, feature: Feature, graph: Graph) -> tuple[str, str]:
    lines = text.splitlines(keepends=True)
    status, start, end = marker_span(lines, RELATED_START, RELATED_END)
    if status != "ok":
        return text, status
    return replace_span(lines, start, end, render_related(feature, graph)), "ok"


def related_problems(root: Path, features: list[Feature], graph: Graph) -> list[Problem]:
    """Missing, repeated or stale Related features blocks (features with valid metadata only)."""
    out = []
    for f in features:
        if not f.meta_ok:
            continue
        text = (root / f.path).read_bytes().decode("utf-8")
        new, status = apply_related(text, f, graph)
        if status == "missing":
            out.append(Problem(f.path, "missing the generated Related features block (the lines between "
                                       "<!-- related-features:start ... --> and <!-- related-features:end -->)"))
        elif status != "ok":
            out.append(Problem(f.path, f"the generated Related features block is "
                                       f"{'repeated' if status == 'several' else 'not closed'}: keep exactly one "
                                       "related-features:start and one related-features:end marker"))
        elif new.replace("\r\n", "\n") != text.replace("\r\n", "\n"):
            out.append(Problem(f.path, "the Related features rows are out of date with depends_on: "
                                       "run `python -m tools.design index`"))
    return out


def stale_related(root: Path) -> list[Problem]:
    features, _ = discover(root)
    return related_problems(root, features, build(features))


def refresh_related(root: Path, concerning: str | None = None) -> list[str]:
    """Rewrite stale Related features blocks of features with valid metadata and exactly
    one block; with `concerning` (a feature ID), only the blocks whose rows can mention
    that feature. Returns the repository-relative paths that were rewritten."""
    features, _ = discover(root)
    graph = build(features)
    if concerning is not None:
        related = {concerning} | {d.target for f in graph.by_id.get(concerning, [])
                                  for d in graph.depends.get(f.path, [])}
        related |= {source.feature_id for source, _ in graph.used_by.get(concerning, [])}
    changed = []
    for f in features:
        if not f.meta_ok or (concerning is not None and f.feature_id not in related):
            continue
        path = root / f.path
        text = path.read_bytes().decode("utf-8")
        new, status = apply_related(text, f, graph)
        if status != "ok" or new.replace("\r\n", "\n") == text.replace("\r\n", "\n"):
            continue
        write_feature_text(path, new)
        changed.append(f.path)
    return changed


def index_cells(feature: Feature, graph: Graph, index_dir: str) -> tuple[str, str]:
    """The feature index's "Depends on" and "Used by" cells."""
    def link(fid: str, files: list[Feature], note: str = "") -> str:
        if len(files) == 1:
            text = f"[{fid}]({_link(posixpath.relpath(files[0].path, index_dir))})"
        else:
            text = fid + (" (unknown)" if not files else " (duplicate ID)")
        return text + note

    deps = [link(d.target, graph.by_id.get(d.target, []), " (optional)" if d.optional else "")
            for d in graph.depends.get(feature.path, [])]
    users, seen = [], set()
    for source, d in graph.used_by.get(feature.feature_id, []) if feature.feature_id else []:
        if source.path in seen or source.path == feature.path:
            continue
        seen.add(source.path)
        users.append(link(source.feature_id, [source], " (optional)" if d.optional else ""))
    return (", ".join(deps) or "-", ", ".join(users) or "-")
