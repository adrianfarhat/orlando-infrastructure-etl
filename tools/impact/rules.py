"""Change-impact rules: findings and an informational impact report for a change set (T-83, 83b-2).

Input: a loaded, valid configuration and registry, and a ChangeSet with its changed
lines (changes.py). Output: ERROR and WARNING findings, plus an INFO change-impact
report that is never a finding (no IDs, no acknowledgements, no effect on the exit code).
Read-only and deterministic: git runs only through changes.py/gitfiles.py; reference
files are read from the working tree; nothing is written.

Rules (severities are fixed unless noted; configurable ones are WARNING or off in impact.yml):
- new-interface-without-contract (ERROR, fixed): a NEW file (added, renamed to, copied
  to) matching an impact.yml `interfaces` pattern that no component lists in its
  `interfaces` (each listed interface names its contract).
- stale-reference (ERROR, fixed): a file selected by `reference_scan` still contains the
  exact repository path of a deleted file, or of the old path of a renamed file. One
  finding per referencing file and removed path. See "Reference matching" below.
- unregistered-path (WARNING, configurable): a changed, non-deleted path that no
  component matches, with a suggested component (the one sharing the longest leading
  folder path) or a new one. Deleted paths are not reported (approved decision 6).
- docs-not-updated (WARNING, configurable; "Documentation review required"): one per
  component with a documentation obligation whose mapped docs did not change in this
  change set. The INFO report lists all of the component's docs either way; a doc that
  changed is shown as changed, never as reviewed.
- content-trigger (WARNING, configurable): a trigger's `match` found in the ADDED or
  REMOVED lines of a matching changed file (never the whole file). Changed lines that
  could not be scanned give a "not scanned" WARNING, never "no match".
- config-changed (WARNING, fixed; impact.yml cannot switch it off or narrow it): a change
  to impact.yml, the registry (registry/** and the configured registry file), or one of
  the engine's own top-level Python modules. The engine's folder is derived at run time
  from where this package is, relative to the repository root (never hardcoded, so the
  tool stays portable); every *.py file directly in that folder counts, including added,
  deleted and renamed ones, but not its tests/ or other subfolders and not other files.
  When the package is outside the repository (installed or run from elsewhere), no
  engine path can change in that repository and only impact.yml and the registry count.
- ack-problem is not produced here: acks.py checks acknowledgements after the analysis.

Exclusions:
- Paths matching impact.yml `ignore` are skipped entirely (listed in the report as ignored),
  except for config-changed, which impact.yml cannot suppress.
- Files whose purpose is test, generated or experimental (doc_obligation.exempt_purposes)
  create no documentation obligation and no content-trigger WARNING; components with
  `docs: []` create no obligation either.
- Phantom changes (a "modified" file whose changed lines were scanned and are empty, see
  changes.py limitation 1) create no finding; the report shows "no content change".
  Content that could not be scanned counts as changed (conservative).

Reference matching (stale-reference): the removed path must appear exactly, as a
repository-relative path, not as part of a longer path or name: the characters around
it must not be path characters (letters, digits, _ - . / ~ % +), except that a
trailing "." before a non-path character (end of a sentence) is allowed, and so is a
leading "/" (repository-root form) when the character before it is not a path
character. A root-level path with no folder (for example README.md) is a bare file name,
so it matches only as a whole quoted or backticked value (`README.md`, "README.md"),
never in prose. Not matched: links relative to the referencing document (for example
../../extractors/x.py; T-81, the link checker), URL-encoded paths (%20) and folder
references. Files larger than changes.MAX_FILE_BYTES are not scanned and are listed in
the report.

Tests (INFO only): there is no registry `tests` field. The report lists the test files
(purpose `test`) that belong to the same component as the change, labelled as derived
from component paths and purposes, not a verified test mapping; "not mapped" otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable

from . import changes, regexsafe
from .changes import Change, ChangedLines, ChangeSet
from .config import Component, Config, Loaded, Problem, Registry, Trigger
from .findings import Finding, from_problems
from .gitfiles import list_files
from .paths import matches
from .resolve import GENERATED, REVIEWED, TRIGGER, Resolution, best_components, purpose_of, resolve

# Fixed config-changed inputs; the configured registry file and the engine's own modules
# (engine_folder) are added at run time.
CONFIG_CHANGE_PATTERNS = ("impact.yml", "registry/**")
_PACKAGE_DIR = Path(__file__).resolve().parent
NOT_MAPPED = "not mapped"
TESTS_BASIS = "test files in the same component (component paths + impact.yml purposes); not a verified test mapping"
CHANGED, NO_CONTENT_CHANGE = "changed", "no content change"

_PATH_CHARS = frozenset("_-./~%+")
_QUOTES = frozenset("`\"'")


class InvalidConfiguration(Exception):
    """impact.yml or the registry has ERROR problems: run `impact validate` (exit code 2)."""


def engine_folder(root: Path) -> str | None:
    """The folder of this package relative to the repository root, as a Git-style path
    ("" for the root itself), or None when the package is outside the repository."""
    try:
        rel = _PACKAGE_DIR.relative_to(Path(root).resolve())
    except ValueError:
        return None
    return rel.as_posix() if rel.parts else ""


def is_config_input(path: str, config: Config, engine: str | None) -> bool:
    """config-changed applies to this repository path (fixed; not configurable)."""
    patterns = CONFIG_CHANGE_PATTERNS + ((config.registry,) if config.registry else ())
    if any(matches(path, p) for p in patterns):
        return True
    if engine is None:
        return False
    folder, _, name = path.rpartition("/")
    return folder == engine and name.endswith(".py")


def ready(loaded: Loaded) -> tuple[Config, Registry]:
    """The configuration and registry, or InvalidConfiguration when they are not valid."""
    if loaded.has_errors or loaded.registry is None:
        raise InvalidConfiguration("the impact configuration or registry is invalid; run `python -m tools.impact validate`")
    return loaded.config, loaded.registry


# --------------------------------------------------------------------------- report model

@dataclass(frozen=True)
class DocImpact:
    doc: str
    kind: str                       # "reviewed" (mapped doc), "generated" or "trigger"
    sources: tuple[str, ...]        # component or trigger ids
    changed: bool                   # changed in this change set (not a claim that it was reviewed)


@dataclass(frozen=True)
class Dependent:
    component: str                  # the component that depends on the changed one
    depends_on: str                 # the changed component
    basis: str                      # "code" or "inferred"
    detail: str                     # evidence (code) or note (inferred)


@dataclass(frozen=True)
class ImpactEntry:
    path: str
    old_path: str | None
    kind: str
    origins: tuple[str, ...]
    ignored: bool
    purpose: str | None
    components: tuple[str, ...]     # best match; several when tied
    old_components: tuple[str, ...]  # for renames: the old path's components
    content: str                    # CHANGED, NO_CONTENT_CHANGE or "not scanned: <reason>"
    doc_obligation: bool
    docs: tuple[DocImpact, ...]
    contracts: tuple[tuple[str, str], ...]   # (interface path, contract)
    tests: tuple[str, ...]
    tests_basis: str
    dependents: tuple[Dependent, ...]
    triggers: tuple[str, ...]       # content triggers that matched changed lines
    unscanned_triggers: tuple[str, ...]


@dataclass(frozen=True)
class Analysis:
    findings: tuple[Finding, ...]
    impact: tuple[ImpactEntry, ...]
    unsupported: tuple[str, ...]            # names Git reported that the tool cannot analyse
    references_not_scanned: tuple[tuple[str, str], ...]   # (file, reason)

    @property
    def exit_code(self) -> int:
        return 1 if any(f.severity == "ERROR" for f in self.findings) else 0


# --------------------------------------------------------------------------- analysis

def analyse(root: Path, config: Config, registry: Registry, change_set: ChangeSet,
            lines_for: Callable[[Change], ChangedLines] | None = None,
            files: Iterable[str] | None = None) -> Analysis:
    """Apply the rules to a change set. `lines_for` and `files` (the working-tree file
    listing) default to reading them through changes.py and gitfiles.py."""
    root = Path(root)
    with changes.analysis(root):
        if lines_for is None:
            lines_for = lambda c: changes.changed_lines(change_set, c)  # noqa: E731
        listing = tuple(sorted(set(files))) if files is not None else list_files(root).files
        return _analyse(root, config, registry, change_set, lines_for, listing)

def _analyse(root: Path, config: Config, registry: Registry, change_set: ChangeSet,
             lines_for: Callable[[Change], ChangedLines], listing: tuple[str, ...]) -> Analysis:
    problems: list[Problem] = []
    reg_source = config.registry or "registry"
    listed_interfaces = {i.path for c in registry.components for i in c.interfaces}
    engine = engine_folder(root)

    def rule_on(name: str) -> bool:
        return config.rules.get(name, "WARNING") != "off"

    entries: list[ImpactEntry] = []
    present = set(listing)
    tests_by_component: dict[str, set[str]] = {}   # test files (purpose test) per component, computed once
    for f in listing:
        if purpose_of(f, config) == "test":
            for comp in best_components(f, registry):
                tests_by_component.setdefault(comp.id, set()).add(f)
    obligations: dict[str, set[str]] = {}       # component id -> changed paths creating the obligation
    changed_docs: set[str] = set()              # paths whose content changed in this change set
    removed: dict[str, Change] = {}             # removed path -> its change (for stale-reference)

    for change in change_set.changes:
        # The change's own paths: the path, plus the old path of a rename (a copy's
        # source still exists unchanged, so it is not part of the change).
        own = (change.path,) + ((change.old_path,) if change.kind == "renamed" and change.old_path else ())
        res = {p: resolve(p, config, registry, from_git=True) for p in own}
        live = {p: r for p, r in res.items() if not r.ignored}
        # config-changed (fixed WARNING) is decided before impact.yml `ignore` applies, so
        # the configuration cannot hide changes to itself, the registry or the engine.
        config_hit = any(is_config_input(p, config, engine) for p in own)
        if not live:
            phantom_ignored = change.kind == "modified" and config_hit and \
                _content(change, lines_for(change)) == NO_CONTENT_CHANGE
            if config_hit and not phantom_ignored:
                problems.append(Problem(change.path, "impact configuration", change.path, "config-changed",
                                        "WARNING", _config_message(change)))
            entries.append(_ignored_entry(change))
            continue
        for p in change.removed_paths:
            if p in live and p not in present:      # re-created paths are not stale
                removed[p] = change
        cur = live.get(change.path) if change.kind != "deleted" else None
        gone = [live[p] for p in change.removed_paths if p in live]
        lines = lines_for(change)
        content = _content(change, lines)
        phantom = change.kind == "modified" and content == NO_CONTENT_CHANGE
        if cur is not None and content != NO_CONTENT_CHANGE:
            changed_docs.add(cur.path)
        main = cur or gone[0]
        fired: list[str] = []
        unscanned: list[str] = []

        if not phantom:
            # config-changed (fixed WARNING)
            if config_hit:
                problems.append(Problem(change.path, "impact configuration", change.path, "config-changed",
                                        "WARNING", _config_message(change)))
            # new-interface-without-contract (fixed ERROR)
            if cur is not None and change.kind in ("added", "renamed", "copied"):
                kinds = [k for k, pats in config.interfaces if any(matches(cur.path, p) for p in pats)]
                if kinds and cur.path not in listed_interfaces:
                    problems.append(Problem(cur.path, f"interface {kinds[0]}", cur.path,
                                            "new-interface-without-contract", "ERROR",
                                            f"new {kinds[0]} file is not listed in any component's `interfaces` "
                                            f"with its contract ({reg_source})"))
            # unregistered-path (WARNING); deleted paths are not reported
            if cur is not None and not cur.registered and rule_on("unregistered-path"):
                problems.append(Problem(cur.path, "change", cur.path, "unregistered-path", "WARNING",
                                        _unregistered_message(cur.path, registry, reg_source)))
            # documentation obligations: per component (each tied component), never for
            # exempt purposes or components with docs: []
            for r in ([cur] if cur else []) + gone:
                if r.purpose in config.exempt_purposes:
                    continue
                for comp in best_components(r.path, registry):
                    if comp.docs:
                        obligations.setdefault(comp.id, set()).add(r.path)
            # content-trigger (WARNING): added and removed lines only
            if main.purpose not in config.exempt_purposes:
                for t in registry.triggers:
                    if not any(_trigger_applies(p, t) for p in live):
                        continue
                    status = _scan_lines(t, lines)
                    if status is None:
                        continue
                    found, detail = status
                    (fired if found else unscanned).append(t.id)
                    if rule_on("content-trigger"):
                        docs = ", ".join(t.docs)
                        if found:
                            problems.append(Problem(change.path, f"content trigger {t.id}", t.id, "content-trigger",
                                                    "WARNING", f"`{t.match}` in {detail}: review {docs}; "
                                                               "significance cannot be determined automatically"))
                        else:
                            problems.append(Problem(change.path, f"content trigger {t.id}", f"{t.id} (not scanned)",
                                                    "content-trigger", "WARNING",
                                                    f"changed lines not scanned ({detail}): review {docs} "
                                                    f"manually for `{t.match}`"))

        # The old path of a rename, shown separately (unless it is already `main`, when
        # the new path is ignored).
        old = (live.get(change.old_path) if change.kind == "renamed" and change.old_path and cur is not None
               else None)
        entries.append(_entry(change, main, old, content, phantom, registry, config, tests_by_component,
                              tuple(sorted(fired)), tuple(sorted(unscanned))))

    # docs-not-updated (WARNING): once every changed doc is known
    if rule_on("docs-not-updated"):
        for cid in sorted(obligations):
            comp = _component(registry, cid)
            if any(d in changed_docs for d in comp.docs):
                continue
            problems.append(Problem(reg_source, f"component {cid}", cid, "docs-not-updated", "WARNING",
                                    f"Documentation review required: {len(obligations[cid])} changed file(s) in "
                                    f"component {cid}; none of its docs changed in this change set: "
                                    f"{', '.join(comp.docs)}"))

    # stale-reference (fixed ERROR)
    ref_problems, not_scanned = _stale_references(root, config, removed, listing)
    problems.extend(ref_problems)

    entries = [_with_changed_docs(e, changed_docs) for e in entries]
    return Analysis(findings=from_problems(problems),
                    impact=tuple(sorted(entries, key=lambda e: (e.path, e.old_path or ""))),
                    unsupported=tuple(sorted(u.shown for u in change_set.unsupported)),
                    references_not_scanned=tuple(sorted(not_scanned)))


# --------------------------------------------------------------------------- helpers

def _content(change: Change, lines: ChangedLines) -> str:
    if not lines.scanned:
        return f"not scanned: {lines.reason}"
    if lines.added or lines.removed or change.kind in ("added", "deleted"):
        return CHANGED
    return NO_CONTENT_CHANGE


def _trigger_applies(path: str, trigger: Trigger) -> bool:
    return any(matches(path, p) for p in trigger.paths) and not any(matches(path, x) for x in trigger.exclude)


def _scan_lines(trigger: Trigger, lines: ChangedLines) -> tuple[bool, str] | None:
    """(True, where) if the trigger matched the added or removed lines; (False, reason)
    if they could not be (fully) scanned without a match; None for a clean "no match"."""
    if not lines.scanned:
        return False, lines.reason or "not readable as text"
    found, incomplete = [], []
    for name, part in (("added", lines.added), ("removed", lines.removed)):
        if not part:
            continue
        result = regexsafe.scan(trigger.regex, trigger.profile, "\n".join(part))
        if result.matched:
            found.append(name)
        elif not result.complete:
            incomplete.append(name)
    if found:
        return True, " and ".join(found) + " lines"
    if incomplete:
        return False, " and ".join(incomplete) + " lines too long to scan fully"
    return None


def _component(registry: Registry, cid: str) -> Component:
    return next(c for c in registry.components if c.id == cid)


def _config_message(change: Change) -> str:
    what = {"deleted": "deleted", "renamed": f"renamed from {change.old_path}", "copied": "copied",
            "added": "added"}.get(change.kind, "modified")
    return (f"Impact configuration changed ({what}): review changes to rules, ignore and exclude "
            "patterns, interfaces and component mappings")


def _literal_prefix(pattern: str) -> list[str]:
    out = []
    for seg in pattern.split("/"):
        if any(ch in seg for ch in "*?["):
            break
        out.append(seg)
    return out


def _unregistered_message(path: str, registry: Registry, reg_source: str) -> str:
    folders = path.split("/")[:-1]
    best: tuple[int, str] | None = None
    for comp in registry.components:
        for pat in comp.paths:
            shared = 0
            for a, b in zip(folders, _literal_prefix(pat)):
                if a != b:
                    break
                shared += 1
            if shared and (best is None or shared > best[0] or (shared == best[0] and comp.id < best[1])):
                best = (shared, comp.id)
    if best:
        return (f"not in any component of {reg_source}; suggestion: add it to component {best[1]} "
                f"(shares the folder {'/'.join(folders[:best[0]])}/) or register a new component")
    return f"not in any component of {reg_source}; suggestion: register a new component"


def _ignored_entry(change: Change) -> ImpactEntry:
    return ImpactEntry(change.path, change.old_path, change.kind, change.origins, True, None, (), (),
                       "ignored (impact.yml ignore)", False, (), (), (), NOT_MAPPED, (), (), ())


def _entry(change: Change, main: Resolution, old: Resolution | None, content: str, phantom: bool,
           registry: Registry, config: Config, tests_by_component: dict[str, set[str]],
           fired: tuple[str, ...], unscanned: tuple[str, ...]) -> ImpactEntry:
    comps = best_components(main.path, registry)
    old_comps = best_components(old.path, registry) if old is not None else ()
    docs: dict[tuple[str, str], set[str]] = {}
    for comp in comps + old_comps:
        for d in comp.docs:
            docs.setdefault((d, REVIEWED), set()).add(comp.id)
        for d in comp.generated:
            docs.setdefault((d, GENERATED), set()).add(comp.id)
    for t in registry.triggers:
        if t.id in fired or t.id in unscanned:
            for d in t.docs:
                docs.setdefault((d, TRIGGER), set()).add(t.id)
    contracts = tuple(sorted({(i.path, i.contract) for c in comps for i in c.interfaces if i.path == main.path}))
    ids = {c.id for c in comps + old_comps}
    dependents = tuple(sorted(
        {Dependent(c.id, dep.id, dep.basis, dep.evidence or dep.note or "")
         for c in registry.components for dep in c.depends_on if dep.id in ids},
        key=lambda d: (d.depends_on, d.component)))
    tests = tuple(sorted(set().union(*(tests_by_component.get(i, set()) for i in ids))))
    obligation = not phantom and any(
        comp.docs and r.purpose not in config.exempt_purposes
        for r, cs in ((main, comps), (old, old_comps)) if r is not None for comp in cs)
    return ImpactEntry(
        path=change.path, old_path=change.old_path, kind=change.kind, origins=change.origins, ignored=False,
        purpose=main.purpose, components=tuple(c.id for c in comps), old_components=tuple(c.id for c in old_comps),
        content=content, doc_obligation=obligation,
        docs=tuple(DocImpact(d, k, tuple(sorted(src)), False) for (d, k), src in sorted(docs.items())),
        contracts=contracts, tests=tests, tests_basis=TESTS_BASIS if tests else NOT_MAPPED,
        dependents=dependents, triggers=fired, unscanned_triggers=unscanned)


def _with_changed_docs(entry: ImpactEntry, changed_docs: set[str]) -> ImpactEntry:
    if not entry.docs:
        return entry
    docs = tuple(DocImpact(d.doc, d.kind, d.sources, d.doc in changed_docs) for d in entry.docs)
    return replace(entry, docs=docs)


# --------------------------------------------------------------------------- stale references

def _is_path_char(ch: str) -> bool:
    return ch.isalnum() or ch in _PATH_CHARS


def find_references(text: str, path: str) -> list[int]:
    """Line numbers (1-based) where `path` appears as an exact repository path (see the
    module docstring, "Reference matching")."""
    out: list[int] = []
    bare = "/" not in path
    start = 0
    while (i := text.find(path, start)) != -1:
        start = i + 1
        j = i + len(path)
        before = text[i - 1] if i else ""
        after = text[j] if j < len(text) else ""
        if bare:
            ok = before in _QUOTES and after == before
        else:
            if before == "/":                              # repository-root form "/path"
                before = text[i - 2] if i >= 2 else ""
            after_ok = after == "" or not _is_path_char(after) or (
                after == "." and (j + 1 >= len(text) or not _is_path_char(text[j + 1])))
            ok = (before == "" or not _is_path_char(before)) and after_ok
        if ok:
            line = text.count("\n", 0, i) + 1
            if not out or out[-1] != line:
                out.append(line)
    return out


def _stale_references(root: Path, config: Config, removed: dict[str, Change],
                      listing: tuple[str, ...]) -> tuple[list[Problem], list[tuple[str, str]]]:
    if not removed:
        return [], []
    problems: list[Problem] = []
    not_scanned: list[tuple[str, str]] = []
    for f in listing:
        if not any(matches(f, p) for p in config.reference_include) or any(
                matches(f, p) for p in config.reference_exclude) or any(matches(f, p) for p in config.ignore):
            continue
        file = root / f
        try:
            if file.is_symlink() or not file.is_file():
                continue
            if file.stat().st_size > changes.MAX_FILE_BYTES:
                not_scanned.append((f, f"larger than {changes.MAX_FILE_BYTES} bytes"))
                continue
            text = file.read_bytes().decode("utf-8", "replace")
        except OSError as exc:
            not_scanned.append((f, f"could not be read ({type(exc).__name__})"))
            continue
        for path in sorted(removed):
            found = find_references(text, path)
            if not found:
                continue
            change = removed[path]
            how = f"renamed to {change.path}" if change.kind == "renamed" else "deleted"
            shown = ", ".join(map(str, found[:10])) + (f" (+{len(found) - 10} more)" if len(found) > 10 else "")
            problems.append(Problem(f, "reference", path, "stale-reference", "ERROR",
                                    f"still refers to {path} ({how}) on line(s) {shown}"))
    return problems, not_scanned
