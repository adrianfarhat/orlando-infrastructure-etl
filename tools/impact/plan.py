"""`impact plan --paths ...`: predict the impact of a proposed change (T-83, 83b-4).

A prediction is informational only: no findings, no IDs, no acknowledgements, and it
never affects the exit code (0, or 2 for a usage, configuration or Git failure). For
each proposed path it reports what a change to that path would involve: its purpose,
its components (several when tied), the docs to review (mapped docs; generated docs to
regenerate; content-trigger docs that apply only if the changed lines match), the
contract of a listed interface, test files in the same component (a component-level
suggestion, not a verified test mapping), one-hop dependent components, and which
`impact check` rules could apply and under what condition.

No change is inspected: Git is used only to find the repository root and HEAD, to list
the existing files (a path "exists" only if Git lists it exactly, so case or trailing-dot
aliases on Windows do not count; the listing also gives the test suggestions and the
current references for stale-reference), and to ask which proposed paths Git ignores
(one `git check-ignore` call). Nothing is diffed, no changed lines are read, and nothing
is written except the --out reports.

Predictions follow what `impact check` would do: rules switched off in impact.yml are
not predicted; files whose purpose is test, generated or experimental get no
content-trigger docs or rule (check does not scan them).

Paths are typed by people: they are normalised like configuration paths (a backslash is
a folder separator, a leading "./" is dropped). Absolute paths, "." or ".." segments,
empty or trailing-slash paths and control characters are usage errors (exit 2), and so
is an existing folder (give file paths). A path that does not exist is a proposed new
file. An ignored path is reported as ignored, with the reason: ".gitignore" (Git ignores
it, so check never sees it; a tracked file is never ignored by Git) or "impact.yml
ignore" (check skips it).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import re

from . import __version__, changes, gitfiles
from .checkreport import _md, _t
from .config import Config, Registry
from .findings import SCHEMA_VERSION
from .paths import PathError, matches, normalize
from .resolve import GENERATED, REVIEWED, TRIGGER, best_components, purpose_of, resolve
from . import rules as _rules
from .rules import NOT_MAPPED, TESTS_BASIS, Dependent, find_references


class PlanUsageError(Exception):
    """An invalid proposed path (exit code 2)."""


@dataclass(frozen=True)
class PredictedDoc:
    doc: str
    kind: str                     # "reviewed" (mapped doc), "generated" or "trigger"
    sources: tuple[str, ...]      # component or content-trigger ids
    condition: str                # when it needs attention


@dataclass(frozen=True)
class PredictedRule:
    rule: str
    severity: str
    condition: str


@dataclass(frozen=True)
class Prediction:
    path: str
    exists: bool
    ignored: bool
    ignored_by: str | None        # ".gitignore", "impact.yml ignore" or both; None when not ignored
    purpose: str | None
    components: tuple[str, ...]
    doc_obligation: bool
    docs: tuple[PredictedDoc, ...]
    contracts: tuple[tuple[str, str], ...]
    tests: tuple[str, ...]
    tests_basis: str
    dependents: tuple[Dependent, ...]
    rules: tuple[PredictedRule, ...]
    referenced_by: tuple[str, ...]        # reference_scan files that mention the path today


@dataclass(frozen=True)
class Plan:
    head: str | None
    sources: tuple[str, ...]
    predictions: tuple[Prediction, ...]


def normalise_paths(raw: Iterable[str], root: Path) -> tuple[str, ...]:
    out = set()
    for value in raw:
        try:
            path = normalize(value)
        except PathError as exc:
            raise PlanUsageError(f"--paths: {exc}") from None
        if (root / path).is_dir() and not (root / path).is_symlink():
            raise PlanUsageError(f"--paths: {_t(path)} is a folder; give file paths")
        out.add(path)
    return tuple(sorted(out))


_CHECK_IGNORE_MATCH = re.compile(r"(?P<source>.*?):(?P<line>[0-9]+):(?P<pattern>[^\t]*)\t")


def git_ignored(root: Path, paths: tuple[str, ...]) -> frozenset[str]:
    """The paths Git ignores, from one read-only `git check-ignore` call.

    --verbose --non-matching prints exactly one line per path, in order, so results are
    taken by position and file names are never parsed. A path matching a negated
    pattern ("!x") is not ignored. Tracked files are never reported as ignored (Git's
    default), matching what check sees. Each path is passed as "./path": pathspec magic
    such as ":(exclude)" is only recognised at the start, so every name stays literal
    (check-ignore does not accept --literal-pathspecs).
    """
    if not paths:
        return frozenset()
    result = gitfiles.git_status(root, "-c", "core.quotePath=false", "check-ignore", "--verbose", "--non-matching",
                                 "--", *("./" + p for p in paths))
    if result.returncode not in (0, 1):
        detail = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise gitfiles.GitError(f"'git check-ignore' failed: {_t(detail[0] if detail else 'no message')}")
    lines = result.stdout.decode("utf-8", "replace").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) != len(paths):
        raise gitfiles.GitError(f"'git check-ignore' returned {len(lines)} results for {len(paths)} paths")
    ignored = set()
    for path, line in zip(paths, lines):
        if line.startswith("::\t"):
            continue
        m = _CHECK_IGNORE_MATCH.match(line)
        if m is None:
            raise gitfiles.GitError("'git check-ignore' returned an unexpected line")
        if not m.group("pattern").startswith("!"):
            ignored.add(path)
    return frozenset(ignored)


def predict(root: Path, config: Config, registry: Registry, paths: Iterable[str],
            files: Iterable[str], gitignored: Iterable[str] = ()) -> tuple[Prediction, ...]:
    """Predictions for normalised paths, given Git's listing of the existing
    (non-ignored) files and the proposed paths Git ignores."""
    listing = tuple(sorted(set(files)))
    present = set(listing)
    gitignored = frozenset(gitignored)
    tests_by_component: dict[str, set[str]] = {}
    for f in listing:
        if purpose_of(f, config) == "test":
            for comp in best_components(f, registry):
                tests_by_component.setdefault(comp.id, set()).add(f)
    reference_files = _reference_texts(root, config, listing)
    engine = _rules.engine_folder(root)
    return tuple(_predict(p, p in present, p in gitignored, config, registry, tests_by_component, reference_files,
                          engine) for p in sorted(set(paths)))


def _predict(path: str, exists: bool, gitignored: bool, config: Config, registry: Registry,
             tests_by_component: dict[str, set[str]], reference_files: dict[str, str],
             engine: str | None) -> Prediction:
    res = resolve(path, config, registry)
    if res.ignored or gitignored:
        reasons = [r for r, on in ((".gitignore", gitignored), ("impact.yml ignore", res.ignored)) if on]
        # check never sees a Git-ignored path; an impact.yml-ignored one is still checked
        # for config-changed (impact.yml cannot suppress it).
        ignored_rules = (PredictedRule("config-changed", "WARNING", "on any content change, rename or deletion"),) \
            if not gitignored and _rules.is_config_input(path, config, engine) else ()
        return Prediction(path, exists, True, " and ".join(reasons), None, (), False, (), (), (), NOT_MAPPED,
                          (), ignored_rules, ())
    comps = best_components(path, registry)
    ids = {c.id for c in comps}
    exempt = res.purpose in config.exempt_purposes
    reg = config.registry or "registry"

    docs: dict[tuple[str, str], tuple[set[str], str]] = {}

    def add(doc: str, kind: str, source: str, condition: str) -> None:
        docs.setdefault((doc, kind), (set(), condition))[0].add(source)

    for comp in comps:
        for d in comp.docs:
            add(d, REVIEWED, comp.id, "no documentation obligation (purpose " + str(res.purpose) + ")" if exempt
                else "review when the file changes")
        for d in comp.generated:
            add(d, GENERATED, comp.id, "regenerate when the component changes")
    triggers = [t for t in registry.triggers
                if any(matches(path, p) for p in t.paths) and not any(matches(path, x) for x in t.exclude)]
    # check does not scan files with an exempt purpose for content triggers
    triggers = [] if exempt else triggers
    for t in triggers:
        for d in t.docs:
            add(d, TRIGGER, t.id, f"review if added or removed lines contain `{t.match}`")

    rules: list[PredictedRule] = []
    def rule_on(name: str) -> bool:                # configurable rules switched off are not predicted
        return config.rules.get(name, "WARNING") != "off"

    if not comps and rule_on("unregistered-path"):
        rules.append(PredictedRule("unregistered-path", "WARNING",
                                   f"when the file is added, modified, renamed or copied: it is in no component of {reg}"))
    if res.doc_obligation and rule_on("docs-not-updated"):
        names = ", ".join(sorted({d for c in comps for d in c.docs}))
        rules.append(PredictedRule("docs-not-updated", "WARNING",
                                   f"unless one of the component's docs changes in the same change set ({names})"))
    if rule_on("content-trigger"):
        for t in triggers:
            rules.append(PredictedRule("content-trigger", "WARNING",
                                       f"if added or removed lines contain `{t.match}` (trigger {t.id})"))
    listed = {i.path: i.contract for c in registry.components for i in c.interfaces}
    kinds = [k for k, pats in config.interfaces if any(matches(path, p) for p in pats)]
    if kinds and path not in listed:
        rules.append(PredictedRule("new-interface-without-contract", "ERROR",
                                   f"if the file is new (added, renamed or copied to this path) without being listed "
                                   f"in a component's `interfaces` with its contract ({kinds[0]})"))
    if _rules.is_config_input(path, config, engine):
        rules.append(PredictedRule("config-changed", "WARNING", "on any content change, rename or deletion"))
    referenced_by = tuple(sorted(f for f, text in reference_files.items() if f != path and find_references(text, path)))
    if exists:
        rules.append(PredictedRule(
            "stale-reference", "ERROR",
            ("if the file is deleted or renamed: currently referenced by " + ", ".join(referenced_by))
            if referenced_by else "if the file is deleted or renamed while a reference_scan file still refers to it "
                                  "(none does today)"))

    dependents = tuple(sorted(
        {Dependent(c.id, dep.id, dep.basis, dep.evidence or dep.note or "")
         for c in registry.components for dep in c.depends_on if dep.id in ids},
        key=lambda d: (d.depends_on, d.component)))
    tests = tuple(sorted(set().union(*(tests_by_component.get(i, set()) for i in ids))))
    return Prediction(
        path=path, exists=exists, ignored=False, ignored_by=None, purpose=res.purpose, components=tuple(c.id for c in comps),
        doc_obligation=res.doc_obligation,
        docs=tuple(PredictedDoc(d, k, tuple(sorted(src)), cond) for (d, k), (src, cond) in sorted(docs.items())),
        contracts=((path, listed[path]),) if path in listed else (),
        tests=tests, tests_basis=TESTS_BASIS if tests else NOT_MAPPED,
        dependents=dependents, rules=tuple(sorted(rules, key=lambda r: (r.rule, r.condition))),
        referenced_by=referenced_by)


def _reference_texts(root: Path, config: Config, listing: tuple[str, ...]) -> dict[str, str]:
    """Current text of the reference_scan files (for stale-reference predictions)."""
    out = {}
    for f in listing:
        if not any(matches(f, p) for p in config.reference_include) or any(
                matches(f, p) for p in config.reference_exclude) or any(matches(f, p) for p in config.ignore):
            continue
        file = root / f
        try:
            if file.is_symlink() or not file.is_file() or file.stat().st_size > changes.MAX_FILE_BYTES:
                continue
            out[f] = file.read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
    return out


# --------------------------------------------------------------------------- rendering

NOTE = "Prediction only: no findings, no acknowledgements; the exit code is not affected."


def render_json(plan: Plan) -> str:
    doc = {"schema_version": SCHEMA_VERSION, "tool": "impact", "version": __version__, "command": "plan",
           "head": plan.head, "sources": list(plan.sources), "note": NOTE,
           "summary": {"paths": len(plan.predictions), "exit_code": 0},
           "predictions": [asdict(p) for p in plan.predictions]}
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _lines(p: Prediction) -> list[str]:
    state = "exists" if p.exists else ("not listed by Git" if ".gitignore" in (p.ignored_by or "") else "new file")
    if p.ignored:
        return [f"{_t(p.path)} ({state}): ignored ({p.ignored_by}); check never analyses it"]
    comps = ", ".join(p.components) or "unregistered"
    out = [f"{_t(p.path)} ({state}): component {comps}; purpose {p.purpose}; documentation obligation "
           f"{'yes' if p.doc_obligation else 'no'}"]
    if p.docs:
        out.append("  docs: " + "; ".join(f"{_t(d.doc)} ({d.kind}: {_t(d.condition)})" for d in p.docs))
    if p.contracts:
        out.append("  contracts: " + "; ".join(f"{_t(a)} -> {_t(b)}" for a, b in p.contracts))
    out.append("  tests: " + ("; ".join(_t(t) for t in p.tests) + f" ({p.tests_basis})" if p.tests
                              else p.tests_basis))
    if p.dependents:
        out.append("  dependents (one hop): " + "; ".join(
            f"{d.component} depends on {d.depends_on} ({d.basis}: {_t(d.detail)})" for d in p.dependents))
    for r in p.rules:
        out.append(f"  would apply: {r.rule} ({r.severity}) {_t(r.condition)}")
    return out


def render_text(plan: Plan) -> str:
    head = plan.head[:7] if plan.head else "no commits"
    lines = [f"impact plan | HEAD {head} | {len(plan.predictions)} paths | {_t(' + '.join(plan.sources))}", NOTE]
    for p in plan.predictions:
        lines.extend("  " + x for x in _lines(p))
    lines.append(f"Summary: {len(plan.predictions)} paths | exit code 0")
    return "\n".join(lines) + "\n"


def render_markdown(plan: Plan) -> str:
    out = ["## Documentation impact (prediction)", "", f"`impact plan`: {len(plan.predictions)} proposed paths. "
           f"{_md(NOTE)}", "",
           "| Path | Components | Docs to review | Contracts | Tests (component-level suggestion) | Dependents (one hop) |",
           "|---|---|---|---|---|---|"]
    for p in plan.predictions:
        if p.ignored:
            out.append(f"| {_md(p.path)} | ignored ({_md(p.ignored_by or '')}) | - | - | - | - |")
            continue
        docs = "<br>".join(f"{_md(d.doc)} ({d.kind})" for d in p.docs) or "none"
        contracts = "<br>".join(_md(c) for _, c in p.contracts) or "-"
        tests = "<br>".join(_md(t) for t in p.tests) or NOT_MAPPED
        deps = "<br>".join(f"{_md(d.component)} ({d.basis})" for d in p.dependents) or "-"
        comps = _md(", ".join(p.components)) or "unregistered"
        out.append(f"| {_md(p.path)}{'' if p.exists else ' (new)'} | {comps} | {docs} | {contracts} | {tests} | {deps} |")
    out += ["", "### Rules that could apply", ""]
    rows = [(p.path, r) for p in plan.predictions for r in p.rules]
    if rows:
        out += ["| Path | Rule | Severity | Condition |", "|---|---|---|---|"]
        out += [f"| {_md(path)} | {_md(r.rule)} | {r.severity} | {_md(r.condition)} |" for path, r in rows]
    else:
        out.append("None.")
    out.append("")
    return "\n".join(out)
