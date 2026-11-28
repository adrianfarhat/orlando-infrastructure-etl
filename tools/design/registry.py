"""The diagram registry (T-97 PR A; design: docs/architecture/diagram-library.md).

`designs/diagrams/registry.yml` is the single, authoritative mapping from a stable diagram ID
to its owner, format, category, title, source path and lifecycle. It never holds diagram
content. It is written only by `python -m tools.design` commands, always under a lock and by
compare-and-swap (the file is replaced only if nobody changed it meanwhile):

- `new diagram` (ownership.py) creates a standalone Mermaid source and its entry together;
- `registry adopt <path>` registers an existing, unregistered Mermaid source;
- `registry adopt-architecture` registers the architecture diagrams in place (stage M0:
  format `mermaid-embedded`, an `AD-nnnn` ID, the former catalog ID as a permanent alias;
  no document is changed);
- `registry relink` changes a path or title, or re-points an embedded entry after a
  heading rename (never guessed);
- `registry retire` marks a diagram retired after listing its references (never reused);
- `registry move` and `registry adopt-moves` (moves.py, PR B2b-2a) change paths for a batch
  through a recorded, recoverable move transaction (transactions.py, version 2 records).

Validation (`check`) reports, never fixes: duplicate IDs and aliases (E2), ID/alias
collisions (E8), owners and ID prefixes (E9), sources that are missing (E7), moved (E6),
copied (E4) or unregistered (E5), in-file identity that disagrees with the registry (E3),
unknown formats and categories, and sources outside their approved directories (U12).
"""

from __future__ import annotations

import datetime as _dt
import difflib
import hashlib
import io
import json
import os
import posixpath
import re
import platform
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from .ids import DIAGRAM_ID, DOCUMENT_DIAGRAM_ID, FEATURE_ID
from .workspace import (ARCHITECTURE, FEATURES, MAX_FILE_BYTES, DesignError, Feature, Problem, _same_text, _yaml,
                        discover, split_front_matter, write_generated)

REGISTRY = "designs/diagrams/registry.yml"
LOCK = "designs/diagrams/.registry.lock"
DIAGRAM_INDEX = "designs/index/diagram-index.md"
DOCUMENT_SOURCES = "docs/architecture/diagrams"        # document-owned standalone sources (U12)
SCHEMA_VERSION = 1
# The controlled category list (U7). Changing it is a schema change: a DECISIONS entry, this
# list and its tests; removing or renaming one needs a version bump and a migration command.
CATEGORIES = ("system-architecture", "data-model", "process", "sequence", "state", "ui", "legend", "other")
# Formats accepted now; the reserved ones are known but refused until their own approved work.
FORMATS = ("mermaid-md", "mermaid-embedded")
RESERVED_FORMATS = {"drawio-svg": "visual diagrams arrive with the draw.io integration (PR C)",
                    "mermaid-mmd": "reserved for a later, separately approved design",
                    "dbml": "reserved for a later, separately approved design"}
STATUSES = ("active", "retired")
STALE_LOCK_SECONDS = 600
# M0: the category of an adopted architecture diagram, from its `%% diagram-type:` marker.
CATEGORY_BY_TYPE = {"architecture": "system-architecture", "er": "data-model", "process": "process",
                    "sequence": "sequence", "example": "legend"}
HEADER = ("# The diagram registry (T-97): stable diagram IDs, owners, formats and source paths.\n"
          "# Written only by `python -m tools.design` commands (new diagram, registry adopt,\n"
          "# registry adopt-architecture, registry relink, registry retire); review changes in pull\n"
          "# requests. Never holds diagram content. See docs/architecture/diagram-library.md.\n")


@dataclass(frozen=True)
class Entry:
    diagram_id: str
    title: str
    owner_kind: str               # "feature" or "document"
    owner_ref: str                # a feature ID, or a repository path of the owning document
    format: str
    category: str
    path: str                     # repository-relative source (for mermaid-embedded: the owning document)
    aliases: tuple[str, ...] = ()
    status: str = "active"
    retired: str = ""
    created: str = ""
    anchor: str = ""              # mermaid-embedded: the heading anchor ('' or "top": before the first heading)
    ordinal: int = 1              # mermaid-embedded: 1-based position among the diagrams under that heading
    line: int = 0                 # 1-based line of the entry in registry.yml


@dataclass
class Registry:
    entries: list[Entry] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)   # schema problems (the file as written)
    sha: str | None = None                                  # SHA-256 of the file bytes; None when absent
    data: object = None                                     # the round-trip YAML document (for writing)

    @property
    def exists(self) -> bool:
        return self.sha is not None

    def by_id(self) -> dict[str, Entry]:
        return {e.diagram_id: e for e in self.entries}

    def lookup(self) -> dict[str, Entry]:
        """Every ID and alias, to its entry (first one wins; duplicates are E2/E8 problems)."""
        out: dict[str, Entry] = {}
        for e in self.entries:
            out.setdefault(e.diagram_id, e)
        for e in self.entries:
            for a in e.aliases:
                out.setdefault(a, e)
        return out


# --------------------------------------------------------------------------- reading

def _rt_yaml():
    from ruamel.yaml import YAML
    y = YAML()                                       # round trip: keeps comments and order
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 4096
    y.preserve_quotes = True
    return y


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(root: Path) -> Registry:
    """The registry as written. An absent file is an empty registry (before the first entry)."""
    path = Path(root) / REGISTRY
    if not path.is_file():
        return Registry()
    data = path.read_bytes()
    reg = Registry(sha=_sha(data))
    if len(data) > MAX_FILE_BYTES:
        reg.problems.append(Problem(REGISTRY, f"larger than {MAX_FILE_BYTES} bytes"))
        return reg
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        reg.problems.append(Problem(REGISTRY, "not valid UTF-8"))
        return reg
    from ruamel.yaml.error import YAMLError
    try:
        doc = _rt_yaml().load(text)
    except YAMLError as exc:
        reg.problems.append(Problem(REGISTRY, f"not valid YAML: {str(exc).splitlines()[0][:200]}"))
        return reg
    reg.data = doc
    if not isinstance(doc, dict):
        reg.problems.append(Problem(REGISTRY, "must be a mapping with `version` and `diagrams`"))
        return reg
    if doc.get("version") != SCHEMA_VERSION:
        reg.problems.append(Problem(REGISTRY, f"`version` must be {SCHEMA_VERSION}, found {doc.get('version')!r}"))
    items = doc.get("diagrams")
    if items is None:
        items = []
    if not isinstance(items, list):
        reg.problems.append(Problem(REGISTRY, "`diagrams` must be a list"))
        return reg
    for n, item in enumerate(items):
        line = (item.lc.line + 1) if hasattr(item, "lc") and item.lc.line is not None else 0
        entry, problems = _entry(item, line, n)
        reg.problems += problems
        if entry is not None:
            reg.entries.append(entry)
    return reg


def _entry(item, line: int, n: int) -> tuple[Entry | None, list[Problem]]:
    where = f"line {line}" if line else f"entry {n + 1}"
    bad = []

    def p(msg):
        bad.append(Problem(REGISTRY, f"{where}: {msg}"))

    if not isinstance(item, dict):
        p("each entry must be a mapping")
        return None, bad
    did = item.get("diagram_id")
    did = did.strip() if isinstance(did, str) else ""
    if not did:
        p("diagram_id is required")
    elif not (DIAGRAM_ID.match(did) or DOCUMENT_DIAGRAM_ID.match(did)):
        p(f"diagram_id {did!r} must look like FD-0001-D1 (feature-owned) or AD-0001 (document-owned)")
    title = item.get("title")
    title = " ".join(title.split()) if isinstance(title, str) else ""
    if not title:
        p(f"{did or 'the entry'}: title is required")
    owner = item.get("owner")
    kind = ref = ""
    if not isinstance(owner, dict) or not isinstance(owner.get("kind"), str) or not isinstance(owner.get("ref"), str):
        p(f"{did or 'the entry'}: owner must be {{kind: feature, ref: FD-0001}} or {{kind: document, ref: <path>}}")
    else:
        kind, ref = owner["kind"].strip(), owner["ref"].strip()
        if kind not in ("feature", "document"):
            p(f"{did}: owner kind must be feature or document, found {kind!r}")
    fmt = item.get("format") if isinstance(item.get("format"), str) else ""
    if fmt in RESERVED_FORMATS:
        p(f"{did}: format {fmt} is not accepted yet ({RESERVED_FORMATS[fmt]})")
    elif fmt not in FORMATS:
        p(f"{did}: format must be one of {', '.join(FORMATS)}, found {fmt!r}")
    category = item.get("category") if isinstance(item.get("category"), str) else ""
    if category not in CATEGORIES:
        close = difflib.get_close_matches(category, CATEGORIES, n=1, cutoff=0.6)
        p(f"{did}: category must be one of {', '.join(CATEGORIES)}, found {category!r}"
          + (f" (did you mean {close[0]}?)" if close else ""))
    path = item.get("path") if isinstance(item.get("path"), str) else ""
    path_problem = path_syntax_problem(path)
    if path_problem:
        p(f"{did}: path {path!r} {path_problem}")
    aliases = item.get("aliases") if item.get("aliases") is not None else []
    if not isinstance(aliases, list) or not all(isinstance(a, str) and a.strip() and not re.search(r"\s", a)
                                                for a in aliases):
        p(f"{did}: aliases must be a list of IDs without spaces")
        aliases = []
    status = item.get("status", "active")
    retired = item.get("retired")
    retired = str(retired) if retired is not None else ""
    if status not in STATUSES:
        p(f"{did}: status must be active or retired, found {status!r}")
    elif status == "retired" and not retired:
        p(f"{did}: a retired diagram needs `retired: <date>`")
    anchor, ordinal = "", 1
    if fmt == "mermaid-embedded":
        anchor = item.get("anchor") if isinstance(item.get("anchor"), str) else None
        ordinal = item.get("ordinal")
        if anchor is None:
            p(f"{did}: a mermaid-embedded entry needs `anchor` (the heading anchor, or top)")
            anchor = ""
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 1:
            p(f"{did}: a mermaid-embedded entry needs `ordinal` (1 or more)")
            ordinal = 1
    created = item.get("created")
    created = str(created) if created is not None else ""
    if bad:
        return None, bad
    return Entry(did, title, kind, ref, fmt, category, path, tuple(a.strip() for a in aliases), status, retired,
                 created, anchor, ordinal, line), []


def path_syntax_problem(path: str) -> str:
    if not path:
        return "is required"
    if "\\" in path:
        return "must use / separators"
    if path.startswith("/") or re.match(r"[A-Za-z]:", path):
        return "must be repository-relative"
    if posixpath.normpath(path) != path or path.startswith("../") or path == "..":
        return "must be a normalised path inside the repository"
    return ""


# --------------------------------------------------------------------------- in-file identity

@dataclass(frozen=True)
class SourceFile:
    path: str
    diagram_id: str
    title: str
    feature_id: str
    owner_document: str


def source_files(root: Path) -> list[SourceFile]:
    """Every standalone Mermaid source in an approved directory whose front matter has a
    diagram_id: diagrams/ folders under designs/features/, and docs/architecture/diagrams/."""
    from ruamel.yaml.error import YAMLError
    from .links import diagram_files
    out = []
    candidates = list(diagram_files(root))
    base = Path(root) / DOCUMENT_SOURCES
    if base.is_dir():
        candidates += sorted(posixpath.join(DOCUMENT_SOURCES, n) for n in os.listdir(base)
                             if n.lower().endswith(".md") and not n.startswith(".") and (base / n).is_file())
    for rel in candidates:
        try:
            if (Path(root) / rel).stat().st_size > MAX_FILE_BYTES:
                continue
            front, _ = split_front_matter((Path(root) / rel).read_bytes().decode("utf-8"))
            meta = _yaml().load(front) if front is not None else None
        except (OSError, UnicodeDecodeError, YAMLError):
            continue
        if not isinstance(meta, dict):
            continue
        did = meta.get("diagram_id")
        if not isinstance(did, str) or not did.strip():
            continue

        def text(key):
            v = meta.get(key)
            return " ".join(v.split()) if isinstance(v, str) else ""
        out.append(SourceFile(rel, did.strip(), text("title"), text("feature_id"), text("owner_document")))
    return out


def _exact_case_exists(root: Path, rel: str) -> bool:
    """True when every segment exists with exactly this letter case (GitHub is case-sensitive)."""
    here = Path(root)
    for part in rel.split("/"):
        try:
            names = os.listdir(here)
        except OSError:
            return False
        if part not in names:
            return False
        here = here / part
    return True


def approved_directory_problem(kind: str, fmt: str, path: str, owner_ref: str) -> str:
    """Why a source path is outside its owner kind's approved directory (U12), '' when fine."""
    if fmt == "mermaid-embedded":
        if kind != "document":
            return "a mermaid-embedded entry must be owned by a document"
        if path != owner_ref:
            return f"a mermaid-embedded entry's path must be its owning document ({owner_ref})"
        if not (path.startswith(ARCHITECTURE + "/") and path.endswith(".md")):
            return f"a mermaid-embedded entry must point at a document under {ARCHITECTURE}/"
        return ""
    if kind == "document":
        if posixpath.dirname(path) != DOCUMENT_SOURCES:
            return f"document-owned sources belong in {DOCUMENT_SOURCES}/ (U12)"
    elif kind == "feature":
        parts = path.split("/")
        if not (path.startswith(FEATURES + "/") and "diagrams" in parts[2:-1]):
            return f"feature-owned sources belong in a diagrams/ folder under {FEATURES}/ (U12)"
    if fmt == "mermaid-md" and not path.endswith(".md"):
        return "a mermaid-md source must be a .md file"
    return ""


# --------------------------------------------------------------------------- validation

def problems(root: Path, features: list[Feature] | None = None, reg: Registry | None = None) -> list[Problem]:
    """Every registry problem (schema and references), without changing anything."""
    root = Path(root)
    reg = reg if reg is not None else load(root)
    if features is None:
        features, _ = discover(root)
    out = list(reg.problems) + identity_problems(reg)
    feature_ids = {f.feature_id for f in features if f.feature_id}
    files = {s.path: s for s in source_files(root)}
    file_ids: dict[str, list[SourceFile]] = {}
    for s in files.values():
        file_ids.setdefault(s.diagram_id, []).append(s)
    registered_paths = {e.path for e in reg.entries if e.format == "mermaid-md"}
    for e in reg.entries:
        where = f"line {e.line}: {e.diagram_id}"
        # E9: owner and ID prefix
        if e.owner_kind == "feature":
            m = DIAGRAM_ID.match(e.diagram_id)
            if not m:
                out.append(Problem(REGISTRY, f"{where} is owned by a feature: feature-owned IDs look like FD-0001-D1 (E9)"))
            elif m.group(1) != e.owner_ref:
                out.append(Problem(REGISTRY, f"{where} is owned by {e.owner_ref} in the registry: the ID prefix must be "
                                             "the owner's (E9)"))
            if not FEATURE_ID.match(e.owner_ref):
                out.append(Problem(REGISTRY, f"{where}: owner ref {e.owner_ref!r} must be a feature ID such as FD-0001 (E9)"))
            elif e.owner_ref not in feature_ids:
                out.append(Problem(REGISTRY, f"{where}: owner {e.owner_ref} is not an existing feature (E9)"))
        else:
            if not DOCUMENT_DIAGRAM_ID.match(e.diagram_id):
                out.append(Problem(REGISTRY, f"{where} is owned by a document: document-owned IDs look like AD-0001 (E9)"))
            if path_syntax_problem(e.owner_ref) or not _exact_case_exists(root, e.owner_ref):
                out.append(Problem(REGISTRY, f"{where}: owning document {e.owner_ref!r} does not exist (E9)"))
        # U12: approved directories
        reason = approved_directory_problem(e.owner_kind, e.format, e.path, e.owner_ref)
        if reason:
            out.append(Problem(REGISTRY, f"{where}: {reason}"))
            continue
        if e.status == "retired":
            continue                                   # a retired source may be deleted
        if e.format == "mermaid-embedded":
            located, candidate = locate_embedded(root, e)
            if located is None:
                out.append(Problem(REGISTRY, f"{where}: no Mermaid diagram {e.ordinal} under #{e.anchor or 'top'} in "
                                             f"{e.path}" + (f" (the document has {candidate})" if candidate else "")
                                             + f"; if the heading was renamed, re-point it explicitly with `python -m "
                                             f"tools.design registry relink {e.diagram_id} --heading <anchor>` (E7, U11)"))
            continue
        # mermaid-md: the source file
        if not _exact_case_exists(root, e.path):
            moved = sorted(s.path for s in file_ids.get(e.diagram_id, []) if s.path not in registered_paths)
            if len(moved) > 1:                         # PR B2b-2a: ambiguous, never guessed
                out.append(Problem(REGISTRY, f"{where} is at {len(moved)} unregistered paths ({', '.join(moved)}): "
                                             "nothing is guessed; keep one of them, then relink it explicitly with "
                                             f"`python -m tools.design registry relink {e.diagram_id} --path <path>` (E6)"))
            elif moved:
                batch = (f"; to update the registry for every moved feature-owned source at once, run `python -m "
                         f"tools.design registry adopt-moves` (or `--from {e.path} --to {moved[0]}` for this one)"
                         if e.owner_kind == "feature" else "")
                out.append(Problem(REGISTRY, f"{where} moved to {moved[0]}: run `python -m tools.design registry relink "
                                             f"{e.diagram_id} --path {moved[0]}` (E6){batch}"))
            else:
                out.append(Problem(REGISTRY, f"{where}'s source {e.path} does not exist (E7)"))
            continue
        s = files.get(e.path)
        if s is None:
            out.append(Problem(e.path, f"registered as {e.diagram_id} but has no diagram_id in its front matter (E3)"))
            continue
        if s.diagram_id != e.diagram_id:
            out.append(Problem(e.path, f"holds {s.diagram_id} but the registry maps {e.diagram_id} to it (E3)"))
        owner_in_file = s.feature_id if e.owner_kind == "feature" else s.owner_document
        field_name = "feature_id" if e.owner_kind == "feature" else "owner_document"
        if owner_in_file != e.owner_ref:
            out.append(Problem(e.path, f"{field_name} is {owner_in_file or '(missing)'} but the registry's owner of "
                                       f"{e.diagram_id} is {e.owner_ref}; reuse never changes the owner (E3, U10)"))
        if s.title != e.title:
            out.append(Problem(e.path, f"title {s.title!r} differs from the registry's {e.title!r}: change both with "
                                       f"`python -m tools.design registry relink {e.diagram_id} --title …`"))
    # unregistered sources: E4 (a copy of a registered diagram) or E5
    by_id = reg.by_id()
    for s in files.values():
        if s.path in registered_paths:
            continue
        e = by_id.get(s.diagram_id)
        if e is not None and e.format == "mermaid-md" and _exact_case_exists(root, e.path):
            out.append(Problem(s.path, f"is a copy of {s.diagram_id} ({e.path}): create diagrams with `python -m "
                                       "tools.design new diagram` (E4)"))
        elif e is None and not (DIAGRAM_ID.match(s.diagram_id) or DOCUMENT_DIAGRAM_ID.match(s.diagram_id)):
            out.append(Problem(s.path, f"diagram_id {s.diagram_id!r} is not a valid diagram ID, so it cannot be "
                                       "registered or named by a diagram block: create diagrams with `python -m "
                                       "tools.design new diagram` (E5)"))
        elif e is None:
            out.append(Problem(s.path, f"{s.diagram_id} is not registered: run `python -m tools.design registry adopt "
                                       f"{s.path} --category <category>` (E5)"))
        elif e.format == "mermaid-embedded" and e.status == "active" and posixpath.dirname(s.path) == DOCUMENT_SOURCES:
            out.append(Problem(s.path, f"holds {s.diagram_id}, which is still registered as embedded in {e.path}: "
                                       f"extraction not finished; run `python -m tools.design registry extract "
                                       f"{s.diagram_id} --path {s.path} --snapshot <file>` (T-97 M1)"))
    return out + extraction_problems(root, reg)


def extraction_problems(root: Path, reg: Registry) -> list[Problem]:
    """T-97 M1: an extracted (document-owned mermaid-md) diagram whose raw block is still in its
    document (a second copy, E2 family: it would be counted twice), or that its document does
    not show at all (U3: architecture pages show the generated copy)."""
    from .architecture import catalog, documents
    from .architecture_copies import COPY_COMMAND, regions
    extracted = [e for e in reg.entries if e.status == "active" and e.owner_kind == "document" and e.format == "mermaid-md"]
    if not extracted:
        return []
    cat = catalog(documents(root))
    shown = regions(root)
    out = []
    for e in extracted:
        raw = [d for d in cat if d.document == e.owner_ref and d.diagram_id in e.aliases]
        for d in raw:
            out.append(Problem(d.document, f"line {d.line}: this Mermaid block is a second copy of {e.diagram_id} (its "
                                           f"source is {e.path}): technical-lead replaces it with the generated copy "
                                           f"(`{COPY_COMMAND} {e.diagram_id}`) (E2)"))
        names = (e.diagram_id, *e.aliases)
        if not raw and not any(p == e.owner_ref for n in names for p, _ in shown.get(n, [])):
            out.append(Problem(e.owner_ref, f"does not show {e.diagram_id} (its source is {e.path}): technical-lead adds "
                                            f"the generated copy printed by `{COPY_COMMAND} {e.diagram_id}` (U3)"))
    return out


def locate_embedded(root: Path, e: Entry):
    """(catalog diagram, '') when an embedded entry's block is found; (None, what the
    document has) otherwise (U11: nothing is guessed)."""
    from .architecture import catalog, documents
    want = e.anchor if e.anchor not in ("", "top") else None
    found = [d for d in catalog(documents(root)) if d.document == e.path]
    under = [d for d in found if (d.heading.anchor if d.heading is not None else None) == want]
    if len(under) >= e.ordinal:
        return under[e.ordinal - 1], ""
    if not found:
        return None, "no Mermaid diagrams"
    return None, "diagrams under " + ", ".join(sorted({f"#{d.heading.anchor if d.heading is not None else 'top'}"
                                                       for d in found}))


def catalog_aliases(reg: Registry) -> dict[str, Entry]:
    """Embedded entries by the catalog diagram they point at (document, anchor, ordinal)."""
    return {(e.path, e.anchor if e.anchor not in ("", "top") else None, e.ordinal): e
            for e in reg.entries if e.format == "mermaid-embedded"}


def catalog_key(d) -> tuple:
    return d.document, (d.heading.anchor if d.heading is not None else None)


# --------------------------------------------------------------------------- writing (lock and compare-and-swap)

_LOCK_BYTE = 1 << 30        # Windows locks a byte range: one far past the metadata, which stays readable


def _os_lock(fd: int) -> bool:
    """Take an exclusive operating-system lock on the open lock file, without waiting. The
    system releases it when the process ends, however it ends."""
    try:
        if sys.platform == "win32":
            import msvcrt
            os.lseek(fd, _LOCK_BYTE, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _os_unlock(fd: int) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt
            os.lseek(fd, _LOCK_BYTE, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


_held: dict[str, int] = {}     # repository root -> how many times this process holds its lock


def _lock_key(root: Path) -> str:
    return os.path.normcase(str(Path(root).resolve()))


def holds_lock(root: Path) -> bool:
    """Whether this process holds the registry lock of `root`."""
    return _held.get(_lock_key(root), 0) > 0


@contextmanager
def lock(root: Path):
    """The registry lock (E12): created exclusively and held, while the command runs, with an
    operating-system lock that ends with the process; removed afterwards, never broken. Every
    design-tool writer takes it (T-97 PR B2b-1, D3). It is never waited for, so two writers can
    never deadlock; a writer that already holds it in this process may take it again."""
    key = _lock_key(root)
    if _held.get(key, 0) > 0:
        _held[key] += 1
        try:
            yield
        finally:
            _held[key] -= 1
        return
    path = Path(root) / LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
    except FileExistsError:
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            age = 0
        hint = (f"; it is older than {STALE_LOCK_SECONDS // 60} minutes: if no diagram command is running, run "
                "`python -m tools.design registry unlock`, which removes it only after verifying that no process "
                "holds it" if age > STALE_LOCK_SECONDS else "")
        raise DesignError(f"another diagram command is running ({LOCK} exists){hint}; nothing was changed (E12)") from None
    try:
        os.write(fd, json.dumps({"pid": os.getpid(), "host": platform.node(), "time": time.time()}).encode("utf-8"))
        held = _os_lock(fd)
        for _ in range(20):                         # a liveness check (`unlock`, `transaction status`) may hold the
            if held:                                # operating-system lock for an instant; after 1 s the command runs
                break                               # on the lock file alone, as before (the file still excludes others)
            time.sleep(0.05)
            held = _os_lock(fd)
    except BaseException:
        os.close(fd)
        os.unlink(path)
        raise
    _held[key] = 1
    try:
        yield
    finally:
        _held.pop(key, None)
        if held:
            _os_unlock(fd)
        os.close(fd)
        for attempt in range(60):                   # a liveness check may have the file open for an instant, and
            try:                                    # Windows refuses to delete an open file: never leave it behind
                os.unlink(path)
                break
            except FileNotFoundError:
                break
            except OSError:
                time.sleep(0.05)


@dataclass(frozen=True)
class LockState:
    exists: bool
    pid: int | None = None
    host: str = ""
    age_seconds: float = 0.0
    removable: bool = False
    reason: str = ""


def unlock(root: Path, confirm: bool, patient: bool = True) -> LockState:
    """Remove a stale registry lock only when it is verified that no process holds it: the
    command that created it holds an operating-system lock on it while it runs, which the
    system releases when that process ends. If that lock can be taken now, nobody owns the
    file. A lock from another computer, an unreadable lock, or one that is still held is kept.
    Nothing is removed without `confirm`."""
    path = Path(root) / LOCK
    if not path.exists():
        return LockState(False, reason="there is no registry lock")
    try:
        age = time.time() - path.stat().st_mtime
        data = json.loads(path.read_bytes().decode("utf-8") or "{}")
    except (OSError, UnicodeDecodeError, ValueError):
        return LockState(True, reason=f"{LOCK} cannot be read, so its owner cannot be verified; if you are sure no "
                                      "diagram command is running on any computer, delete it by hand")
    pid, host = data.get("pid"), data.get("host")
    pid = pid if isinstance(pid, int) and not isinstance(pid, bool) else None
    if pid is None or not isinstance(host, str) or not host:
        return LockState(True, pid, str(host or ""), age,
                         reason=f"{LOCK} does not record its process and computer, so its owner cannot be verified; "
                                "if you are sure no diagram command is running on any computer, delete it by hand")
    if host != platform.node():
        return LockState(True, pid, host, age, reason=f"the lock was taken on another computer ({host}), where its "
                                                      "process cannot be checked from here")
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:
        return LockState(True, pid, host, age, reason="the lock file is in use: a diagram command still holds it")
    try:
        taken = False
        for _ in range(10 if patient else 1):          # the system may release a dead process's lock a moment late
            taken = _os_lock(fd)
            if taken:
                break
            time.sleep(0.2)
        if not taken:
            return LockState(True, pid, host, age, reason=f"process {pid} still holds the lock: wait for the diagram "
                                                          "command to finish")
        try:
            state = LockState(True, pid, host, age, removable=True,
                              reason=f"no process holds the lock (process {pid} has ended)")
            if confirm:
                _os_unlock(fd)
                os.close(fd)
                fd = -1
                try:
                    os.unlink(path)
                except OSError:                     # Windows: a command opened it meanwhile (POSIX would allow the unlink)
                    return LockState(True, pid, host, age, reason="the lock file is in use; it was kept")
            return state
        finally:
            if fd != -1:
                _os_unlock(fd)
    finally:
        if fd != -1:
            os.close(fd)


def dump(doc) -> str:
    stream = io.StringIO()
    _rt_yaml().dump(doc, stream)
    return stream.getvalue()


def _tx_guard(root) -> None:
    """Q1 (PR B2b-2a): no registry writer runs while a registry move is unresolved (or a record
    cannot be read); recovery writes the registry through its own compare-and-swap instead."""
    from . import transactions
    transactions.registry_guard(root)


def save(root: Path, doc, expected_sha: str | None) -> None:
    """Replace registry.yml with `doc` only if it still has `expected_sha` (None: it must
    still be absent). The new file is written whole to a temporary file first (E12)."""
    from . import transactions
    transactions.registry_guard(root)               # Q1 (PR B2b-2a): never while a registry move is unresolved
    path = Path(root) / REGISTRY
    path.parent.mkdir(parents=True, exist_ok=True)
    text = dump(doc).replace("\r\n", "\n")          # one line-ending style (comments keep what they were read with)
    if not text.startswith("#"):
        text = HEADER + text
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".registry.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(text.encode("utf-8"))
        current = _sha(path.read_bytes()) if path.is_file() else None
        if current != expected_sha:
            raise DesignError("the registry changed while this command ran; nothing was written (E12)")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _new_doc():
    from ruamel.yaml.comments import CommentedMap, CommentedSeq
    doc = CommentedMap()
    doc["version"] = SCHEMA_VERSION
    doc["diagrams"] = CommentedSeq()
    return doc


def _flow_map(**items):
    from ruamel.yaml.comments import CommentedMap
    m = CommentedMap(items)
    m.fa.set_flow_style()
    return m


def _flow_seq(values):
    from ruamel.yaml.comments import CommentedSeq
    s = CommentedSeq(values)
    s.fa.set_flow_style()
    return s


def entry_map(diagram_id: str, title: str, owner_kind: str, owner_ref: str, fmt: str, category: str, path: str,
              aliases=(), anchor: str | None = None, ordinal: int | None = None, created: str | None = None):
    from ruamel.yaml.comments import CommentedMap
    m = CommentedMap()
    m["diagram_id"] = diagram_id
    m["title"] = title
    m["owner"] = _flow_map(kind=owner_kind, ref=owner_ref)
    m["format"] = fmt
    m["category"] = category
    m["path"] = path
    if anchor is not None:
        m["anchor"] = anchor
        m["ordinal"] = ordinal
    m["aliases"] = _flow_seq(list(aliases))
    m["status"] = "active"
    m["created"] = created or _dt.date.today().isoformat()
    m["created_from"] = None
    return m


def identity_problems(reg: Registry) -> list[Problem]:
    """Duplicate IDs and aliases (E2) and ID/alias collisions (E8): the registry cannot be
    trusted to resolve an ID while any of these exists."""
    out = []
    ids: dict[str, list[Entry]] = {}
    aliases: dict[str, list[Entry]] = {}
    for e in reg.entries:
        ids.setdefault(e.diagram_id, []).append(e)
        for a in e.aliases:
            aliases.setdefault(a, []).append(e)
    for did, es in sorted(ids.items()):
        if len(es) > 1:
            out.append(Problem(REGISTRY, f"{did} is registered twice (lines "
                                         f"{', '.join(str(e.line) for e in es)}): each diagram has one entry (E2)"))
    for a, es in sorted(aliases.items()):
        if len(es) > 1:
            out.append(Problem(REGISTRY, f"{a} is an alias of more than one entry (lines "
                                         f"{', '.join(str(e.line) for e in es)}) (E2)"))
        if a in ids:
            out.append(Problem(REGISTRY, f"{a} is both a registry ID and an alias of {es[0].diagram_id} (E8)"))
        if DIAGRAM_ID.match(a) or DOCUMENT_DIAGRAM_ID.match(a):
            out.append(Problem(REGISTRY, f"alias {a} of {es[0].diagram_id} looks like a diagram ID; aliases are "
                                         "former catalog IDs (E8)"))
    return out


def _writable(reg: Registry):
    """The YAML document to append to (a new one when the file is absent); refuses a
    registry with problems, including duplicate or colliding IDs and aliases (it is never
    rewritten while invalid)."""
    bad = reg.problems + identity_problems(reg)
    if bad:
        raise DesignError("the registry has problems; fix them first (python -m tools.design check): "
                          + "; ".join(p.message for p in bad[:3]))
    if reg.data is None:
        return _new_doc()
    if reg.data.get("diagrams") is None:
        from ruamel.yaml.comments import CommentedSeq
        reg.data["diagrams"] = CommentedSeq()
    return reg.data


def _find_item(doc, diagram_id: str):
    for item in doc["diagrams"]:
        if isinstance(item, dict) and item.get("diagram_id") == diagram_id:
            return item
    raise DesignError(f"{diagram_id} is not in the registry")


def all_ids(root: Path, reg: Registry) -> list[str]:
    """Every diagram ID and alias in the working tree (registry and source files)."""
    out = [e.diagram_id for e in reg.entries] + [a for e in reg.entries for a in e.aliases]
    out += [s.diagram_id for s in source_files(root)]
    return out


# --------------------------------------------------------------------------- operations

def adopt(root: Path, rel: str, category: str) -> Entry:
    """Register an existing, unregistered standalone Mermaid source (for example one left by
    an interrupted `new diagram`, or made before the registry existed). Writes only the registry."""
    root = Path(root).resolve()
    rel = posixpath.normpath(rel.replace("\\", "/"))
    if category not in CATEGORIES:
        raise DesignError(f"--category must be one of {', '.join(CATEGORIES)}")
    with lock(root):
        _tx_guard(root)                                  # Q1 (B2b-2a): before anything is written
        reg = load(root)
        doc = _writable(reg)
        files = {s.path: s for s in source_files(root)}
        s = files.get(rel)
        if s is None:
            raise DesignError(f"{rel} is not a Mermaid diagram source with a diagram_id in an approved directory "
                              f"(a diagrams/ folder under {FEATURES}/, or {DOCUMENT_SOURCES}/)")
        if any(e.path == rel for e in reg.entries):
            raise DesignError(f"{rel} is already registered")
        if not (DIAGRAM_ID.match(s.diagram_id) or DOCUMENT_DIAGRAM_ID.match(s.diagram_id)):
            raise DesignError(f"{rel}: diagram_id {s.diagram_id!r} is not a valid diagram ID (FD-0001-D1 or AD-0001); "
                              "create diagrams with `python -m tools.design new diagram`")
        if s.diagram_id in reg.lookup():
            raise DesignError(f"{s.diagram_id} is already registered for another source: this file is a copy (E4); "
                              "create new diagrams with `python -m tools.design new diagram`")
        if s.feature_id and not s.owner_document:
            kind, ref = "feature", s.feature_id
        elif s.owner_document and not s.feature_id:
            kind, ref = "document", s.owner_document
        else:
            raise DesignError(f"{rel} must name exactly one owner: feature_id or owner_document")
        reason = approved_directory_problem(kind, "mermaid-md", rel, ref)
        if reason:
            raise DesignError(f"{rel}: {reason}")
        if not s.title:
            raise DesignError(f"{rel} has no title")
        doc["diagrams"].append(entry_map(s.diagram_id, s.title, kind, ref, "mermaid-md", category, rel))
        save(root, doc, reg.sha)
        write_diagram_index(root)  # D3 (PR B2b-1): inside the lock, like every other write
    return load(root).by_id()[s.diagram_id]


def adopt_architecture(root: Path) -> list[Entry]:
    """Stage M0: register every architecture catalog diagram that is not registered yet, in
    catalog order, as `mermaid-embedded` with a new AD ID and its catalog ID as an alias.
    Writes only the registry: no document and no diagram is changed."""
    from .architecture import catalog, documents
    from .ids import committed_ids, next_document_diagram_id
    root = Path(root).resolve()
    created = []
    with lock(root):
        _tx_guard(root)                                  # Q1 (B2b-2a): before anything is written
        reg = load(root)
        doc = _writable(reg)
        known = reg.lookup()
        located = {}
        for e in reg.entries:
            if e.format == "mermaid-embedded":
                d, _ = locate_embedded(root, e)
                if d is not None:
                    located[d.diagram_id] = e
        in_tree = all_ids(root, reg)
        committed = committed_ids(root)
        position: dict[tuple, int] = {}
        new_items = []
        for d in catalog(documents(root)):
            key = catalog_key(d)
            position[key] = position.get(key, 0) + 1
            if d.diagram_id in known or d.diagram_id in located:
                continue
            did = next_document_diagram_id(in_tree, committed)
            in_tree.append(did)
            heading = d.heading.text if d.heading is not None and d.heading.text else (d.title or d.document)
            category = CATEGORY_BY_TYPE.get(d.diagram_type or "", "other")
            anchor = d.heading.anchor if d.heading is not None and d.heading.anchor else "top"
            item = entry_map(did, heading, "document", d.document, "mermaid-embedded", category, d.document,
                             aliases=[d.diagram_id], anchor=anchor, ordinal=position[key])
            new_items.append((item, did))
        for item, did in new_items:
            doc["diagrams"].append(item)
        if new_items:
            save(root, doc, reg.sha)
            write_diagram_index(root)  # D3 (PR B2b-1): inside the lock, like every other write
    by_id = load(root).by_id()
    return [by_id[did] for _, did in new_items]


def relink(root: Path, ident: str, path: str | None = None, title: str | None = None,
           heading: str | None = None, ordinal: int | None = None) -> Entry:
    """Change one diagram's path or title, or re-point an embedded entry (explicit only; the
    owner and the ID never change)."""
    from . import ownership
    root = Path(root).resolve()
    if path is None and title is None and heading is None:
        raise DesignError("nothing to change: give --path, --title or --heading")
    with lock(root):
        _tx_guard(root)                                  # Q1 (B2b-2a): before anything is written
        reg = load(root)
        doc = _writable(reg)
        e = reg.lookup().get(ident)
        if e is None:
            raise DesignError(f"{ident} is not in the registry as an ID or an alias (E1)")
        item = _find_item(doc, e.diagram_id)
        source_rewrite = None
        if path is not None:
            new = posixpath.normpath(path.replace("\\", "/"))
            if e.format != "mermaid-md":
                raise DesignError(f"{e.diagram_id} is {e.format}: only standalone sources can be moved")
            problem = path_syntax_problem(new) or approved_directory_problem(e.owner_kind, e.format, new, e.owner_ref)
            if problem:
                raise DesignError(f"cannot relink {e.diagram_id} to {new}: {problem}")
            if not _exact_case_exists(root, new):
                raise DesignError(f"{new} does not exist (with exactly this letter case)")
            files = {s.path: s for s in source_files(root)}
            s = files.get(new)
            if s is None or s.diagram_id != e.diagram_id:
                raise DesignError(f"{new} does not hold {e.diagram_id} in its front matter; nothing was changed")
            if any(x.path == new and x.diagram_id != e.diagram_id for x in reg.entries):
                raise DesignError(f"{new} is already registered for another diagram")
            item["path"] = new
        if heading is not None:
            if e.format != "mermaid-embedded":
                raise DesignError(f"{e.diagram_id} is not an embedded diagram: --heading applies to mermaid-embedded")
            probe = Entry(e.diagram_id, e.title, e.owner_kind, e.owner_ref, e.format, e.category, e.path,
                          anchor=heading, ordinal=ordinal or 1)
            found, what = locate_embedded(root, probe)
            if found is None:
                raise DesignError(f"no Mermaid diagram {ordinal or 1} under #{heading} in {e.path}"
                                  + (f" (the document has {what})" if what else "") + "; nothing was changed")
            item["anchor"] = heading
            item["ordinal"] = ordinal or 1
        if title is not None:
            clean = ownership.validate_title(title)
            item["title"] = clean
            if e.format == "mermaid-md" and e.owner_kind == "document":
                found = {s.path: s for s in source_files(root)}.get(item["path"])
                if found is None or found.title != clean:
                    raise DesignError(f"{e.diagram_id} is owned by {e.owner_ref}: its source {item['path']} changes "
                                      "only through technical-lead's documentation workflow. Change the title in that "
                                      "file there first; then this command updates the registry to match. Nothing "
                                      "was changed")
            elif e.format == "mermaid-md":
                target = item["path"]
                source_rewrite = (root / target, ownership.retitled(root, target, clean))
        if source_rewrite is not None:                   # the source first; the registry then names it
            ownership.write_atomically(*source_rewrite, root=root)
        save(root, doc, reg.sha)
        write_diagram_index(root)  # D3 (PR B2b-1): inside the lock, like every other write
    return load(root).by_id()[e.diagram_id]


def references(root: Path, entry: Entry, reg: Registry | None = None) -> list[str]:
    """Every reference to a diagram (by ID or alias): diagram blocks in feature documents,
    and `created_from` links in the registry. One line per reference."""
    from . import diagrams
    names = {entry.diagram_id, *entry.aliases}
    out = []
    features, _ = discover(root)
    for f in features:
        try:
            text = (Path(root) / f.path).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for b in diagrams.scan(text)[0]:
            if b.diagram_id in names:
                out.append(f"{f.path} line {b.start + 1}: diagram block {b.diagram_id}")
    reg = reg if reg is not None else load(root)
    if reg.data is not None:
        for item in reg.data.get("diagrams") or []:
            cf = item.get("created_from") if isinstance(item, dict) else None
            if isinstance(cf, dict) and cf.get("diagram") in names:
                out.append(f"{REGISTRY}: {item.get('diagram_id')} was created from it")
    return out


def retire(root: Path, ident: str, confirm: bool) -> tuple[Entry, list[str], bool]:
    """(entry, references, retired). Without `confirm` nothing changes: the references are
    returned so they can be shown first (R3). The ID is never issued again."""
    root = Path(root).resolve()
    with lock(root):
        _tx_guard(root)                                  # Q1 (B2b-2a): before anything is written
        reg = load(root)
        doc = _writable(reg)
        e = reg.lookup().get(ident)
        if e is None:
            raise DesignError(f"{ident} is not in the registry as an ID or an alias (E1)")
        if e.status == "retired":
            raise DesignError(f"{e.diagram_id} was already retired on {e.retired}")
        refs = references(root, e, reg)
        if not confirm:
            return e, refs, False
        item = _find_item(doc, e.diagram_id)
        item["status"] = "retired"
        item.insert(list(item.keys()).index("status") + 1, "retired", _dt.date.today().isoformat())
        save(root, doc, reg.sha)
        write_diagram_index(root)  # D3 (PR B2b-1): inside the lock, like every other write
    return load(root).by_id()[e.diagram_id], refs, True


# --------------------------------------------------------------------------- M1: extraction (T-97)

EXTRACT_WRITES = (REGISTRY, DIAGRAM_INDEX)
SOURCE_KEYS = ["diagram_id", "title", "owner_document"]


def _read(root: Path, rel: str) -> bytes:
    try:
        return (Path(root) / rel).read_bytes()
    except OSError:
        return b""


def _token(*parts: bytes) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(hashlib.sha256(p).digest())
    return h.hexdigest()[:16]


def _fence_count(body: str) -> int:
    """Fenced code blocks in a Markdown body (any language)."""
    from .diagrams import _closes, _fence
    count, fence = 0, None
    for line in body.replace("\r\n", "\n").split("\n"):
        if fence is not None:
            if _closes(line, fence):
                fence = None
            continue
        f = _fence(line)
        if f and not (f[0] == "`" and "`" in f[2]):
            fence, count = f, count + 1
    return count


def _source_problems(root: Path, e: Entry, rel: str, raw, files: dict) -> tuple[list[str], tuple[str, ...]]:
    """Why `rel` cannot become the standalone source of embedded entry `e` (whose raw block is
    `raw`), and the source's Mermaid lines."""
    from . import diagrams
    from .diagrams import LIKE_MARKER
    bad = []
    where = f"{e.diagram_id} --path {rel}"
    problem = path_syntax_problem(rel) or approved_directory_problem(e.owner_kind, "mermaid-md", rel, e.owner_ref)
    if problem:
        return [f"{where}: {problem}"], ()
    full = Path(root) / rel
    if not _exact_case_exists(root, rel):
        return [f"{where}: the file does not exist with exactly this letter case"], ()
    here = Path(root)
    for part in rel.split("/"):
        here = here / part
        if os.path.islink(here) or (hasattr(os.path, "isjunction") and os.path.isjunction(here)):
            return [f"{where}: {here.relative_to(root).as_posix()} is a symbolic link or junction (links are refused)"], ()
    try:
        full.resolve().relative_to(Path(root).resolve())
    except ValueError:
        return [f"{where}: the path leaves the repository (links are refused)"], ()
    if not full.is_file():
        return [f"{where}: not a regular file (links are refused)"], ()
    if full.stat().st_nlink > 1:
        return [f"{where}: the file has more than one name (a hard link); links are refused"], ()
    s = files.get(rel)
    if s is None:
        return [f"{where}: no front matter with a diagram_id"], ()
    try:
        text = full.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return [f"{where}: cannot be read as UTF-8"], ()
    front, body = split_front_matter(text)
    meta = _yaml().load(front) if front is not None else None
    if not isinstance(meta, dict) or list(meta) != SOURCE_KEYS:
        bad.append(f"{where}: the front matter must hold exactly {', '.join(SOURCE_KEYS)} in this order, found "
                   f"{list(meta) if isinstance(meta, dict) else 'none'}")
    if s.diagram_id != e.diagram_id:
        bad.append(f"{where}: the file holds diagram_id {s.diagram_id}, not {e.diagram_id} (E3)")
    if s.feature_id:
        bad.append(f"{where}: the file has a feature_id; a document-owned source names only owner_document (U10)")
    if s.owner_document != e.owner_ref:
        bad.append(f"{where}: owner_document is {s.owner_document or '(missing)'}, the registry's owner is "
                   f"{e.owner_ref} (E3, U10)")
    if s.title != e.title:
        bad.append(f"{where}: title {s.title!r} differs from the registry's {e.title!r}")
    if LIKE_MARKER.search(text):
        bad.append(f"{where}: the file contains '<!-- diagram:' text, which would be read as a marker")
    if _fence_count(body) != 1:
        bad.append(f"{where}: the file must hold exactly one fenced block, the Mermaid block (found {_fence_count(body)})")
    probe = Entry(e.diagram_id, e.title, e.owner_kind, e.owner_ref, "mermaid-md", e.category, rel)
    src = diagrams._registered_source(root, probe)
    if src.problem or not src.closed:
        bad.append(f"{where}: {src.problem or 'its Mermaid block has no closing fence'}")
        return bad, ()
    if list(src.lines) != list(raw.source):
        first = next((i for i, (a, b) in enumerate(zip(src.lines, raw.source)) if a != b), min(len(src.lines),
                                                                                              len(raw.source)))
        bad.append(f"{where}: its Mermaid lines are not byte-identical to the raw block in {e.owner_ref} (line "
                   f"{raw.line} there; first difference at Mermaid line {first + 1})")
    src_lines = text.replace("\r\n", "\n").split("\n")
    doc_lines = _read(root, e.owner_ref).decode("utf-8", "replace").replace("\r\n", "\n").split("\n")
    try:
        src_fences = (src_lines[src.line - 1], src_lines[src.line + len(src.lines)])
        doc_fences = (doc_lines[raw.line - 1], doc_lines[raw.line + len(raw.source)])
    except IndexError:
        src_fences, doc_fences = ("",), ("?",)
    if src_fences != doc_fences:
        bad.append(f"{where}: its fence lines {src_fences} differ from the document's {doc_fences}")
    return bad, tuple(src.lines)


def plan_extract(root: Path, items: list[tuple[str, str]], snapshot: Path | str) -> dict:
    """What `registry extract` would do (read only): switch each named embedded entry of one
    document to its standalone source. Every check of the whole batch runs first; any problem
    refuses all of it. The token binds the registry, each source, the document and the
    snapshot (their exact bytes)."""
    from .architecture_copies import read_snapshot
    root = Path(root)
    reg = load(root)
    bad = [p.message for p in reg.problems + identity_problems(reg)]
    lookup = reg.lookup()
    if not items:
        bad.append("name at least one diagram: registry extract <ID> --path <source> [<ID> --path <source> ...]")
    try:
        snap, snap_sha = read_snapshot(Path(snapshot))
    except DesignError as exc:
        snap, snap_sha = None, ""
        bad.append(str(exc))
    by_snap = {d["diagram_id"]: d for d in snap["diagrams"]} if snap else {}
    files = {s.path: s for s in source_files(root)}
    planned, owners, seen_ids, seen_paths = [], set(), set(), {}
    for ident, path in items:
        rel = posixpath.normpath(str(path).replace("\\", "/"))
        e = lookup.get(ident)
        if e is None:
            bad.append(f"{ident} is not in the registry as an ID or an alias (E1)")
            continue
        if e.diagram_id in seen_ids:
            bad.append(f"{ident}: {e.diagram_id} is named twice")
            continue
        seen_ids.add(e.diagram_id)
        key = rel.casefold()
        if key in seen_paths:
            bad.append(f"{ident}: --path {rel} is also given for {seen_paths[key]} (paths must differ, also in letter case)")
        seen_paths[key] = e.diagram_id
        if e.status != "active" or e.owner_kind != "document" or e.format != "mermaid-embedded":
            bad.append(f"{ident}: {e.diagram_id} is not an active embedded document-owned diagram "
                       f"({e.status}, {e.owner_kind}, {e.format}); only those are extracted")
            continue
        owners.add(e.owner_ref)
        other = [x.diagram_id for x in reg.entries if x.path == rel and x.diagram_id != e.diagram_id]
        if other:
            bad.append(f"{ident}: {rel} is already registered for {', '.join(other)}")
        raw, what = locate_embedded(root, e)
        if raw is None:
            bad.append(f"{ident}: its raw block is not found in {e.path}" + (f" ({what})" if what else "") + " (E7)")
            continue
        if not raw.closed:
            bad.append(f"{ident}: its raw block in {e.path} (line {raw.line}) has no closing fence")
            continue
        problems, lines = _source_problems(root, e, rel, raw, files)
        bad += problems
        w = by_snap.get(e.diagram_id)
        if snap is not None and w is None:
            bad.append(f"{ident}: {e.diagram_id} is not in the snapshot")
        elif w is not None and (w.get("document") != e.owner_ref or list(lines) != w["mermaid_lines"]):
            bad.append(f"{ident}: the source's Mermaid lines (or document) differ from the snapshot's record of "
                       f"{e.diagram_id}: the switch is tied to the recorded pre-migration bytes")
        planned.append({"diagram_id": e.diagram_id, "aliases": list(e.aliases), "title": e.title, "path": rel,
                        "from": e.path, "anchor": e.anchor, "ordinal": e.ordinal, "line": raw.line,
                        "mermaid_sha256": hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest() if lines else ""})
    if len(owners) > 1:
        bad.append(f"one document per run: the diagrams named belong to {', '.join(sorted(owners))}")
    document = sorted(owners)[0] if len(owners) == 1 else ""
    reg_bytes = _read(root, REGISTRY)
    parts = [reg_bytes, _read(root, document) if document else b"", Path(snapshot).read_bytes() if snap else b"",
             json.dumps([[p["diagram_id"], p["path"]] for p in planned]).encode("utf-8")]
    parts += [_read(root, p["path"]) for p in planned]
    return {"version": 1, "action": "extract", "document": document, "diagrams": planned,
            "registry_sha256": _sha(reg_bytes), "snapshot": {"path": str(snapshot), "sha256": snap_sha},
            "writes": list(EXTRACT_WRITES), "problems": bad, "token": "" if bad else _token(*parts)}


def extract(root: Path, items: list[tuple[str, str]], snapshot: Path | str, confirm: str) -> dict:
    """Carry out exactly the plan that printed `confirm`: under the registry lock, refused while
    a registry move is unresolved (Q1) or a Git operation is in progress (D4), planned and
    validated again, then one compare-and-swap replacement of the registry (only `format` and
    `path` change; `anchor` and `ordinal` are removed) and the diagram index, inside the lock.
    Writes nothing else: never docs/architecture/."""
    from . import transactions
    root = Path(root).resolve()
    if not isinstance(confirm, str) or not confirm:
        raise DesignError("give the token the plan printed (--confirm TOKEN)")
    with lock(root):
        transactions._fault(root, "extract-after-lock")
        _tx_guard(root)
        transactions._git_ready(root)
        plan = plan_extract(root, items, snapshot)
        if plan["problems"]:
            raise DesignError("the extraction was refused; nothing was changed:\n"
                              + "\n".join(f"  - {p}" for p in plan["problems"]))
        if plan["token"] != confirm:
            raise DesignError("the registry, a source, the document or the snapshot changed since the extraction was "
                              "planned; nothing was changed. Plan it again (without --confirm)")
        reg = load(root)
        doc = _writable(reg)
        if reg.sha != plan["registry_sha256"]:
            raise DesignError("the registry changed while this command ran; nothing was written (E12)")
        for p in plan["diagrams"]:
            item = _find_item(doc, p["diagram_id"])
            item["format"] = "mermaid-md"
            item["path"] = p["path"]
            for key in ("anchor", "ordinal"):
                if key in item:
                    del item[key]
        transactions._fault(root, "extract-before-registry")
        transactions._git_ready(root)                   # once more, just before the registry changes
        again = plan_extract(root, items, snapshot)     # the sources, document and snapshot are unchanged
        if again["problems"] or again["token"] != confirm:
            raise DesignError("a source, the document, the snapshot or the registry changed while this command ran; "
                              "nothing was written. Plan it again (without --confirm)")
        save(root, doc, reg.sha)
        transactions._fault(root, "extract-after-registry")
        index = write_diagram_index(root)               # D3: inside the lock
    plan.update(done=True, token="", index=index, registry_sha256_after=_sha(_read(root, REGISTRY)))
    return plan


def plan_revert(root: Path, ident: str, heading: str, ordinal: int | None) -> dict:
    """What `registry extract --revert` would do (read only): set an extracted document-owned
    entry back to `mermaid-embedded` at `heading`/`ordinal` of its owner document, only when that
    document holds a raw block there whose lines equal the source's and no generated copy of it."""
    from . import diagrams
    from .architecture_copies import regions
    root = Path(root)
    reg = load(root)
    bad = [p.message for p in reg.problems + identity_problems(reg)]
    ordinal = ordinal or 1
    e = reg.lookup().get(ident)
    plan = {"version": 1, "action": "revert", "diagram_id": e.diagram_id if e else ident, "heading": heading,
            "ordinal": ordinal, "writes": list(EXTRACT_WRITES), "problems": bad, "token": ""}
    if e is None:
        bad.append(f"{ident} is not in the registry as an ID or an alias (E1)")
        return plan
    if e.status != "active" or e.owner_kind != "document" or e.format != "mermaid-md" \
            or posixpath.dirname(e.path) != DOCUMENT_SOURCES:
        bad.append(f"{e.diagram_id} is not an active document-owned mermaid-md diagram in {DOCUMENT_SOURCES}/; only an "
                   "extracted diagram is reverted")
        return plan
    if not heading:
        bad.append("give --heading <anchor> (the heading the raw block is under in the document)")
        return plan
    src = diagrams._registered_source(root, e)
    if src.problem or not src.closed:
        bad.append(f"{e.diagram_id}: {src.problem or 'its source block has no closing fence'}")
        return plan
    probe = Entry(e.diagram_id, e.title, e.owner_kind, e.owner_ref, "mermaid-embedded", e.category, e.owner_ref,
                  anchor=heading, ordinal=ordinal)
    raw, what = locate_embedded(root, probe)
    if raw is None:
        bad.append(f"{e.owner_ref} has no raw Mermaid block {ordinal} under #{heading}" + (f" ({what})" if what else ""))
    elif list(raw.source) != list(src.lines) or not raw.closed:
        bad.append(f"the raw block on line {raw.line} of {e.owner_ref} is not byte-identical to the source {e.path}")
    names = (e.diagram_id, *e.aliases)
    held = [b.start + 1 for n in names for p, b in regions(root).get(n, []) if p == e.owner_ref]
    if held:
        bad.append(f"{e.owner_ref} still shows the generated copy of {e.diagram_id} (line {', '.join(map(str, held))}): "
                   "technical-lead replaces it with the raw block first")
    plan.update(path=e.path, document=e.owner_ref, registry_sha256=_sha(_read(root, REGISTRY)))
    if not bad:
        plan["token"] = _token(_read(root, REGISTRY), _read(root, e.owner_ref), _read(root, e.path),
                               json.dumps([e.diagram_id, heading, ordinal]).encode("utf-8"))
    return plan


def revert(root: Path, ident: str, heading: str, ordinal: int | None, confirm: str) -> dict:
    """Carry out exactly the revert plan that printed `confirm` (same lock, guards, token and
    compare-and-swap as `extract`), so the registry never needs `git restore`."""
    from . import transactions
    root = Path(root).resolve()
    if not isinstance(confirm, str) or not confirm:
        raise DesignError("give the token the plan printed (--confirm TOKEN)")
    with lock(root):
        _tx_guard(root)
        transactions._git_ready(root)
        plan = plan_revert(root, ident, heading, ordinal)
        if plan["problems"]:
            raise DesignError("the revert was refused; nothing was changed:\n"
                              + "\n".join(f"  - {p}" for p in plan["problems"]))
        if plan["token"] != confirm:
            raise DesignError("the registry, the source or the document changed since the revert was planned; nothing "
                              "was changed. Plan it again (without --confirm)")
        reg = load(root)
        doc = _writable(reg)
        if reg.sha != plan["registry_sha256"]:
            raise DesignError("the registry changed while this command ran; nothing was written (E12)")
        item = _find_item(doc, plan["diagram_id"])
        item["format"] = "mermaid-embedded"
        item["path"] = plan["document"]
        at = list(item.keys()).index("path") + 1
        item.insert(at, "anchor", plan["heading"])
        item.insert(at + 1, "ordinal", plan["ordinal"])
        transactions._git_ready(root)
        save(root, doc, reg.sha)
        index = write_diagram_index(root)
    plan.update(done=True, token="", index=index)
    return plan


# --------------------------------------------------------------------------- the diagram index (V7)

DIAGRAM_INDEX_HEADER = ("<!-- GENERATED by `python -m tools.design index` from designs/diagrams/registry.yml, the "
                        "architecture catalog and the diagram blocks. Do not edit. -->")


def render_diagram_index(root: Path) -> str:
    from . import diagrams
    from .architecture import catalog, documents
    from .workspace import _cell, _link
    root = Path(root)
    reg = load(root)
    features, _ = discover(root)
    used: dict[str, list[str]] = {}
    for f in features:
        try:
            text = (root / f.path).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for did in diagrams.ids_in(text):
            used.setdefault(did, []).append(f.feature_id or f.path)
    here = posixpath.dirname(DIAGRAM_INDEX)

    def link(path):
        return f"[{_cell(path)}]({_link(posixpath.relpath(path, here))})"

    rows = []
    covered = set()
    for e in sorted(reg.entries, key=lambda x: (0 if x.diagram_id.startswith("AD-") else 1, x.diagram_id)):
        names = [e.diagram_id, *e.aliases]
        users = sorted({u for n in names for u in used.get(n, [])})
        owner = e.owner_ref if e.owner_kind == "feature" else link(e.owner_ref)
        where = link(e.path) + (f" #{e.anchor}" if e.format == "mermaid-embedded" and e.anchor not in ("", "top") else "")
        alias = f"<br>alias `{'`, `'.join(e.aliases)}`" if e.aliases else ""
        rows.append(f"| `{e.diagram_id}`{alias} | {_cell(e.title)} | {e.format} | {e.category} | {owner} | {e.status}"
                    f"{' ' + e.retired if e.retired else ''} | {where} | {', '.join(users) or '—'} |")
        covered.update(names)
    unregistered = [d for d in catalog(documents(root)) if d.diagram_id not in covered]
    lines = [DIAGRAM_INDEX_HEADER, "", "# Diagram index", "",
             "Every diagram in the [diagram registry](../diagrams/registry.yml), with its owner, format and source,",
             "and the features that show it. Design: [docs/architecture/diagram-library.md]"
             "(../../docs/architecture/diagram-library.md).", "",
             f"{len(reg.entries)} registered diagram{'s' if len(reg.entries) != 1 else ''}"
             + (f"; {len(unregistered)} architecture diagram{'s' if len(unregistered) != 1 else ''} not registered yet"
                if unregistered else "") + ".", ""]
    if rows:
        lines += ["| ID | Title | Format | Category | Owner | Status | Source | Used by |",
                  "|---|---|---|---|---|---|---|---|", *rows]
    else:
        lines.append("No registered diagrams.")
    if unregistered:
        lines += ["", "## Not registered yet", "",
                  "Architecture diagrams found in the catalog but not in the registry "
                  "(register them with `python -m tools.design registry adopt-architecture`):", ""]
        lines += [f"- `{d.diagram_id}` in {link(d.document)}" for d in unregistered]
    return "\n".join(lines) + "\n"


def _nothing_to_index(root: Path) -> bool:
    """No registry and no architecture documents (a project without diagrams): there is no
    diagram index, as there is no architecture index without docs/architecture/."""
    return not (Path(root) / REGISTRY).exists() and not (Path(root) / ARCHITECTURE).is_dir()


def diagram_index_is_fresh(root: Path) -> bool:
    path = Path(root) / DIAGRAM_INDEX
    if _nothing_to_index(root):
        return not path.exists()
    return path.is_file() and _same_text(path.read_bytes(), render_diagram_index(root))


def write_diagram_index(root: Path) -> str | None:
    """Write the index (only when it changed); None when there is nothing to index."""
    if _nothing_to_index(root):
        return None
    return write_generated(Path(root), DIAGRAM_INDEX, render_diagram_index(root))
