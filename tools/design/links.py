"""Design-specific link and reference checks (T-94 Phase 2, M3). Read-only.

What is checked, all inside designs/:
- Relative Markdown links and reference-style link definitions in the hand-written
  Markdown files: the target must exist (with the exact letter case, as on GitHub) and stay
  inside the repository; a #anchor into a Markdown file (in designs/ or elsewhere, such as
  docs/architecture/) must be one of its headings (anchors as in markdown.py).
- architecture_refs in each feature: a repository-relative path to a document in
  docs/architecture/, optionally with a #anchor that must be one of its headings.
- In proposed diagram files (diagrams/ folders): source_diagram must be a diagram ID in the
  architecture index; source_document and source_heading must exist and agree with it;
  base_commit must look like a commit hash.

What is not checked, on purpose:
- Generated content: designs/index/, and the summary and Related features blocks of each
  feature (they are generated from metadata that is checked directly, so a problem is
  reported once, at its source). designs/templates/ holds {{placeholders}}, not links.
- External links (http:, mailto: and so on), #L line anchors and other anchors into
  non-Markdown files, and every file outside designs/: repository-wide link checking is
  T-81. Mermaid syntax is T-82.
- HTML links (<a href>), links inside fenced or inline code or HTML comments, autolinks
  and protocol-relative links (//host/...).
Known limits (shared with the Phase 1 link pattern): a link target with parentheses must be
written as <path(1).md>, and a link in an indented (four-space) code block is still checked.
"""

from __future__ import annotations

import difflib
import os
import posixpath
import re
from pathlib import Path
from urllib.parse import unquote

from ruamel.yaml.error import YAMLError

from . import markdown
from .workspace import (ARCHITECTURE, DESIGNS, FEATURES, MAX_FILE_BYTES, Feature, Problem, _LINK,
                        _outside_code, _summary_span, _yaml, marker_span, split_front_matter)

SKIPPED_FOLDERS = ("designs/index", "designs/templates")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
_DEFINITION = re.compile(r" {0,3}\[(?:[^\]\\]|\\.)+\]:[ \t]*(<[^>]*>|\S+)")
_CODE_SPAN = re.compile(r"(`+).+?(?<!`)\1(?!`)")
_COMMIT = re.compile(r"[0-9a-f]{7,40}\Z")
_COMMENT = re.compile(r"<!--.*?-->", re.S)


class _Repo:
    """Exact-case existence and heading anchors, cached for one check."""

    def __init__(self, root: Path):
        self.root = root
        self._listing: dict[str, set[str] | None] = {}
        self._anchors: dict[str, set[str] | None] = {}

    def names(self, folder: str) -> set[str] | None:
        if folder not in self._listing:
            try:
                self._listing[folder] = set(os.listdir(self.root / folder)) if (self.root / folder).is_dir() else None
            except OSError:
                self._listing[folder] = None
        return self._listing[folder]

    def exists(self, rel: str) -> bool:
        """True when every segment exists with exactly this letter case."""
        folder = ""
        for segment in rel.split("/"):
            names = self.names(folder)
            if names is None or segment not in names:
                return False
            folder = f"{folder}/{segment}" if folder else segment
        return True

    def anchors(self, rel: str) -> set[str] | None:
        """The heading anchors of a Markdown file (front matter is not a heading)."""
        if rel not in self._anchors:
            path = self.root / rel
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    raise OSError
                text = path.read_bytes().decode("utf-8")
            except (OSError, UnicodeDecodeError):
                self._anchors[rel] = None
            else:
                front, body = split_front_matter(text)
                self._anchors[rel] = {h.anchor for h in markdown.parse(body if front is not None else text).headings
                                      if h.anchor}
        return self._anchors[rel]

    def suggest_file(self, rel: str) -> str:
        folder, name = posixpath.split(rel)
        names = self.names(folder) or set()
        lowered = {n.lower(): n for n in names}
        if name.lower() in lowered:
            return f" (did you mean {posixpath.join(folder, lowered[name.lower()])}? letter case matters on GitHub)"
        close = difflib.get_close_matches(name, sorted(names), n=1)
        return f" (did you mean {posixpath.join(folder, close[0])}?)" if close else ""


def _suggest_anchor(anchor: str, anchors: set[str]) -> str:
    close = difflib.get_close_matches(anchor.lower(), sorted(anchors), n=1, cutoff=0.6)
    return f" (did you mean #{close[0]}?)" if close else ""


def _is_absolute(path: str) -> bool:
    return path.startswith(("/", "\\")) or bool(re.match(r"[A-Za-z]:[\\/]", path))


# --------------------------------------------------------------------------- links

def design_files(root: Path) -> list[str]:
    """The hand-written Markdown files under designs/, in path order."""
    out = []
    for folder, dirs, files in os.walk(root / DESIGNS):
        rel_folder = Path(folder).relative_to(root).as_posix()
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not os.path.islink(os.path.join(folder, d))
                         and posixpath.join(rel_folder, d) not in SKIPPED_FOLDERS)
        for name in sorted(files):
            if name.lower().endswith(".md") and not name.startswith(".") and not os.path.islink(os.path.join(folder, name)):
                out.append(posixpath.join(rel_folder, name))
    return sorted(out)


def _checked_lines(text: str) -> list[str]:
    """The lines whose links are checked: front matter, fenced code, inline code and the
    generated summary and Related features blocks are blanked (line numbers are kept)."""
    lines = text.split("\n")
    front, _ = split_front_matter(text)
    if front is not None:
        yaml_lines = front.count("\n") + 1 if front else 0
        for i in range(yaml_lines + 2):                  # the two '---' lines and the YAML between them
            lines[i] = ""
    from .dependencies import RELATED_END, RELATED_START
    keep = [line + "\n" for line in lines]
    for status, start, end in (_summary_span(keep), marker_span(keep, RELATED_START, RELATED_END)):
        if status == "ok":
            for i in range(start, end + 1):
                lines[i] = ""
    from .diagrams import spans                   # generated diagram blocks (T-96): checked by `check`
    for start, end in spans(text):                # against their source instead, so reported once
        for i in range(start, end + 1):
            lines[i] = ""
    lines = _outside_code("\n".join(lines))
    # HTML comments (also across lines) are not rendered, so their links are not checked
    text = _COMMENT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), "\n".join(lines))
    return [_CODE_SPAN.sub(lambda m: " " * len(m.group(0)), line) for line in text.split("\n")]


def _targets(line: str):
    for m in _LINK.finditer(line.replace("\\[", "  ").replace("\\]", "  ")):
        yield m.group(2)
    d = _DEFINITION.match(line)
    if d:
        yield d.group(1)


def check_link(repo: _Repo, source: str, target: str) -> str | None:
    """Why a link target in `source` is broken, or None when it is fine or not checked here."""
    raw = target[1:-1] if target.startswith("<") and target.endswith(">") else target
    if raw.startswith("//"):                             # protocol-relative: an external link
        return None
    if _is_absolute(raw):                                # before the scheme test: C:/x is a drive, not a URL
        return "an absolute path; use a path relative to this file"
    if not raw or _SCHEME.match(raw):
        return None
    path, _, anchor = raw.partition("#")
    path = unquote(path.split("?", 1)[0])
    anchor = unquote(anchor)
    if not path:
        resolved = source
    else:
        if "\\" in path:
            return "uses '\\'; use '/' in links"
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source), path))
        if resolved == ".." or resolved.startswith("../"):
            return "points outside the repository"
        if resolved == ".":
            return None
        if not repo.exists(resolved):
            return f"{resolved} does not exist{repo.suggest_file(resolved)}"
    if anchor and resolved.lower().endswith(".md") and (repo.root / resolved).is_file():
        anchors = repo.anchors(resolved)
        if anchors is not None and anchor not in anchors:
            return f"{resolved} has no heading with the anchor #{anchor}{_suggest_anchor(anchor, anchors)}"
    return None


def link_problems(root: Path, repo: _Repo | None = None) -> list[Problem]:
    repo = repo or _Repo(root)
    out = []
    for rel in design_files(root):
        try:
            if (root / rel).stat().st_size > MAX_FILE_BYTES:
                continue
            text = (root / rel).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue                                     # reported elsewhere for features; not a link problem
        for number, line in enumerate(_checked_lines(text.replace("\r\n", "\n")), start=1):
            for target in _targets(line):
                reason = check_link(repo, rel, target)
                if reason:
                    out.append(Problem(rel, f"line {number}: broken link ({target}): {reason}"))
    return out


# --------------------------------------------------------------------------- architecture_refs

def architecture_path_problem(value) -> str | None:
    """Why a value cannot be a reference to a document in docs/architecture/ (syntax only)."""
    if not isinstance(value, str) or not value.strip():
        return "is empty"
    path = value.split("#", 1)[0]
    if _is_absolute(path):
        return "must be a repository-relative path such as docs/architecture/system-architecture.md, not an absolute path"
    if "\\" in path:
        return "uses '\\'; use '/'"
    normal = posixpath.normpath(path)
    if not normal.startswith(ARCHITECTURE + "/") or not normal.lower().endswith(".md"):
        return f"must be a Markdown document in {ARCHITECTURE}/ (for example docs/architecture/system-architecture.md)"
    return None


def normal_architecture_ref(value: str) -> tuple[str, str]:
    """(normalised path, anchor) of a syntactically valid reference."""
    path, _, anchor = value.strip().partition("#")
    return posixpath.normpath(path), anchor


def _architecture_ref_problem(repo: _Repo, value) -> str | None:
    syntax = architecture_path_problem(value)
    if syntax:
        return syntax
    path, anchor = normal_architecture_ref(value)
    if not repo.exists(path) or not (repo.root / path).is_file():
        return f"{path} does not exist{repo.suggest_file(path)}"
    anchors = repo.anchors(path)
    if anchor and anchors is not None and unquote(anchor) not in anchors:
        return f"{path} has no heading with the anchor #{anchor}{_suggest_anchor(anchor, anchors)}"
    return None


def architecture_ref_problems(features: list[Feature], repo: _Repo) -> list[Problem]:
    out = []
    for f in features:
        refs = f.meta.get("architecture_refs") if f.meta else None
        if not (isinstance(refs, list) and all(isinstance(r, str) for r in refs)):
            continue                                     # the format problem is reported by read_feature
        for i, ref in enumerate(refs):
            reason = _architecture_ref_problem(repo, ref)
            if reason:
                out.append(Problem(f.path, f"architecture_refs[{i}] ({ref!r}) {reason}"))
    return out


# --------------------------------------------------------------------------- proposed diagrams

def diagram_files(root: Path) -> list[str]:
    return [rel for rel in design_files(root)
            if rel.startswith(FEATURES + "/") and "diagrams" in rel.split("/")[2:-1]]


def diagram_problems(root: Path, repo: _Repo) -> list[Problem]:
    from .architecture import architecture_diagrams, catalog, documents   # imports workspace, which imports this lazily
    docs = documents(root)
    by_id = {d.diagram_id: d for d in catalog(docs)}
    for d in architecture_diagrams(root, docs):         # T-97 M1: a former catalog ID of an extracted diagram
        if d.format == "mermaid-md":                    # (document = owner, heading = that of its copy)
            for alias in d.aliases:
                by_id.setdefault(alias, d)
    out = []
    for rel in diagram_files(root):
        try:
            text = (root / rel).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            out.append(Problem(rel, "cannot be read as UTF-8"))
            continue
        front, _ = split_front_matter(text)
        if front is None:
            continue                                     # a diagram file without metadata: nothing to check
        try:
            meta = _yaml().load(front)
        except YAMLError:
            out.append(Problem(rel, "the diagram metadata is not valid YAML"))
            continue
        if not isinstance(meta, dict):
            continue

        def text_of(key):
            value = meta.get(key)
            return value.strip() if isinstance(value, str) else ("" if value is None else str(value))

        source_diagram, document, heading = text_of("source_diagram"), text_of("source_document"), text_of("source_heading")
        commit = text_of("base_commit")
        if source_diagram:
            found = by_id.get(source_diagram)
            if found is None:
                close = difflib.get_close_matches(source_diagram, sorted(by_id), n=1, cutoff=0.6)
                out.append(Problem(rel, f"source_diagram {source_diagram!r} is not a diagram ID in the architecture "
                                        "index" + (f" (did you mean {close[0]}?)" if close else
                                                   " (see designs/index/architecture-index.md#diagrams)")))
            elif document and posixpath.normpath(document) != found.document:     # first, in every M1 state
                out.append(Problem(rel, f"source_document {document!r} does not match source_diagram "
                                        f"{source_diagram!r}, which is in {found.document}"))
            elif getattr(found, "format", "") == "mermaid-md" and found.heading is None:   # T-97 M1
                if document and heading:
                    out.append(Problem(rel, f"source_heading {heading!r} cannot be checked against source_diagram "
                                            f"{source_diagram!r}: {found.diagram_id} is extracted to {found.path}, and "
                                            f"its document {found.document} does not show its generated copy yet "
                                            "(see `python -m tools.design check`)"))
            else:
                expected_heading = found.heading.anchor if found.heading is not None else ""
                if document and heading and heading != expected_heading:    # without a document: one problem below
                    out.append(Problem(rel, f"source_heading {heading!r} does not match source_diagram "
                                            f"{source_diagram!r}, which is under #{expected_heading or '(no heading)'}"))
        if document:
            reason = _architecture_ref_problem(repo, document + (f"#{heading}" if heading else ""))
            if reason:
                out.append(Problem(rel, f"source_document/source_heading ({document}"
                                        f"{'#' + heading if heading else ''}) {reason}"))
        elif heading:
            out.append(Problem(rel, "source_heading is set but source_document is empty"))
        if commit and not _COMMIT.match(commit):
            out.append(Problem(rel, f"base_commit {commit!r} does not look like a commit hash "
                                    "(7 to 40 lower-case hex characters, from `git rev-parse --short HEAD`)"))
    return out


def check(root: Path, features: list[Feature]) -> list[Problem]:
    """Every M3 problem: links, architecture_refs and proposed-diagram references."""
    repo = _Repo(root)
    return link_problems(root, repo) + architecture_ref_problems(features, repo) + diagram_problems(root, repo)
