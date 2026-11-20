"""Load and check `impact.yml` and the component registry.

Two kinds of failure are kept apart:

- LoadError: a file is missing, unreadable, not UTF-8 or not valid YAML. The
  tool cannot run (exit code 2).
- Problem: the file parsed but breaks the schema (ERROR) or is incomplete
  (WARNING). These are reported as findings by `impact validate`.

Parsing never stops at the first problem: invalid entries are skipped and every
problem is reported. Nothing here runs Git, touches the network or a database,
or executes repository code; file lists are passed in by the caller.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from . import regexsafe
from .paths import PathError, bounded_repr, matches, normalize, normalize_pattern, repo_path

CONFIG_FILE = "impact.yml"

PURPOSES = ("code", "test", "doc", "data", "contract", "config", "ci", "dependency", "generated", "experimental")
DEFAULT_EXEMPT_PURPOSES = ("test", "generated", "experimental")

# Fixed rules: built into the engine, never configurable.
FIXED_ERROR_RULES = ("registry-invalid", "registry-missing-path", "stale-reference", "new-interface-without-contract")
FIXED_WARNING_RULES = ("config-changed",)
FIXED_RULES = FIXED_ERROR_RULES + FIXED_WARNING_RULES
# Configurable WARNING rules (value WARNING or off).
CHECK_RULES = ("unregistered-path", "docs-not-updated", "content-trigger", "ack-problem")
VALIDATE_RULES = ("registry-incomplete",)
RULE_VALUES = ("WARNING", "off")

DEPENDENCY_BASES = ("code", "inferred")
ID_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
MAX_ID_LENGTH = 100

DEFAULT_MIN_REASON_LENGTH = 15
DEFAULT_PLACEHOLDERS = ("n/a", "na", "none", "ok", "tbd", "todo", "-", "fine", "no change", "not needed")

CONFIG_KEYS = ("version", "registry", "ignore", "purposes", "doc_obligation", "interfaces",
               "rules", "validate", "reference_scan", "acks")
REGISTRY_KEYS = ("version", "components", "content_triggers")
COMPONENT_KEYS = ("id", "paths", "exclude", "docs", "generated", "interfaces", "depends_on", "planned", "note")
TRIGGER_KEYS = ("id", "paths", "exclude", "match", "docs", "note")


class LoadError(Exception):
    """A configuration file could not be loaded.

    operational=False: the file is missing or its content cannot be parsed (not
    UTF-8, not valid YAML, nested too deeply). That is a configuration problem,
    reportable as a registry-invalid ERROR finding (exit code 1).
    operational=True: the file exists but could not be read (permissions, I/O),
    which prevents reliable validation (exit code 2).
    """

    def __init__(self, message: str, operational: bool = False):
        super().__init__(message)
        self.operational = operational


@dataclass(frozen=True, order=True)
class Problem:
    source: str      # file the problem is in, e.g. "impact.yml"
    location: str    # e.g. "components[3].docs[1]"
    subject: str     # what the problem is about (path, pattern, key); part of the finding ID
    rule: str        # e.g. "registry-invalid"
    severity: str    # "ERROR" or "WARNING"
    message: str


@dataclass(frozen=True)
class Config:
    version: int
    registry: str | None
    ignore: tuple[str, ...]
    purposes: tuple[tuple[str, tuple[str, ...]], ...]
    exempt_purposes: frozenset[str]
    interfaces: tuple[tuple[str, tuple[str, ...]], ...]
    rules: dict[str, str]
    validate_rules: dict[str, str]
    reference_include: tuple[str, ...]
    reference_exclude: tuple[str, ...]
    ack_min_reason_length: int
    ack_placeholders: tuple[str, ...]


@dataclass(frozen=True)
class Dependency:
    id: str
    basis: str             # "code" (observed in source) or "inferred"
    evidence: str | None
    note: str | None


@dataclass(frozen=True)
class Interface:
    path: str
    contract: str


@dataclass(frozen=True)
class Component:
    id: str
    paths: tuple[str, ...]
    exclude: tuple[str, ...]
    docs: tuple[str, ...]
    generated: tuple[str, ...]
    interfaces: tuple[Interface, ...]
    depends_on: tuple[Dependency, ...]
    planned: bool
    note: str | None


@dataclass(frozen=True)
class Trigger:
    id: str
    paths: tuple[str, ...]
    exclude: tuple[str, ...]
    match: str
    regex: re.Pattern
    profile: regexsafe.RegexProfile   # proven within the safe subset
    docs: tuple[str, ...]
    note: str | None


@dataclass(frozen=True)
class Registry:
    version: int
    components: tuple[Component, ...]
    triggers: tuple[Trigger, ...]


@dataclass(frozen=True)
class Loaded:
    config: Config
    registry: Registry | None
    problems: tuple[Problem, ...]

    @property
    def has_errors(self) -> bool:
        return any(p.severity == "ERROR" for p in self.problems)


# --------------------------------------------------------------------------- reading

def read_yaml(path: Path) -> Any:
    """Read one YAML file with the safe, pure-Python loader."""
    try:
        text = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        raise LoadError(f"{path.name}: file not found") from None
    except OSError as exc:
        raise LoadError(f"{path.name}: cannot read ({exc.strerror})", operational=True) from None
    except UnicodeDecodeError:
        raise LoadError(f"{path.name}: not valid UTF-8") from None
    try:
        return YAML(typ="safe", pure=True).load(text)
    except YAMLError as exc:
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        raise LoadError(f"{path.name}: not valid YAML ({first})") from None
    except RecursionError:
        raise LoadError(f"{path.name}: nested too deeply to load") from None
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        raise LoadError(f"{path.name}: not valid YAML ({type(exc).__name__}: {_r(str(exc), 120)})") from None


# --------------------------------------------------------------------------- checker

class _Checker:
    """Collects schema problems for one source file."""

    def __init__(self, source: str):
        self.source = source
        self.problems: list[Problem] = []

    def error(self, loc: str, msg: str, rule: str = "registry-invalid", subject: str | None = None) -> None:
        loc = loc or "(top level)"
        # The location identifies the problem in almost every case; checks that can
        # report several problems at one location pass a distinguishing subject.
        self.problems.append(Problem(self.source, loc, subject or loc, rule, "ERROR", msg))

    def mapping(self, value: Any, loc: str, allowed: Iterable[str], required: Iterable[str] = ()) -> dict | None:
        if not isinstance(value, dict):
            self.error(loc, f"must be a mapping, not {_kind(value)}")
            return None
        allowed = tuple(allowed)
        for key in value:
            if not isinstance(key, str) or key not in allowed:
                self.error(_join(loc, key), f"unknown key {_r(key)}",
                           subject=f"{_join(loc, key)} {_identity(key)}")
        for key in required:
            if key not in value:
                self.error(loc, f"missing required key {_r(key)}", subject=f"{loc or '(top level)'} missing {key}")
        return value

    def string(self, value: Any, loc: str) -> str | None:
        if not isinstance(value, str) or not value.strip():
            self.error(loc, f"must be a non-empty string, not {_kind(value)}")
            return None
        return value

    def boolean(self, value: Any, loc: str) -> bool | None:
        if not isinstance(value, bool):
            self.error(loc, f"must be true or false, not {_kind(value)}")
            return None
        return value

    def items(self, value: Any, loc: str, allow_empty: bool = True) -> list | None:
        if not isinstance(value, list):
            self.error(loc, f"must be a list, not {_kind(value)}")
            return None
        if not value and not allow_empty:
            self.error(loc, "must not be empty")
            return None
        return value

    def patterns(self, value: Any, loc: str, allow_empty: bool = True) -> tuple[str, ...]:
        out: list[str] = []
        for i, item in enumerate(self.items(value, loc, allow_empty) or []):
            try:
                out.append(normalize_pattern(item))
            except PathError as exc:
                self.error(f"{loc}[{i}]", str(exc))
        return tuple(out)

    def file_path(self, value: Any, loc: str) -> str | None:
        """A literal repository file path (no '*' or '?', no '#anchor').

        Square brackets are allowed: these fields are compared as exact paths,
        never as globs, and frameworks use them in real file names (Next.js
        dynamic routes such as `app/api/[id]/route.ts`).
        """
        try:
            p = normalize(value)
        except PathError as exc:
            self.error(loc, str(exc))
            return None
        if "*" in p or "?" in p:
            self.error(loc, f"must be a file path, not a pattern: {_r(value)}")
            return None
        if "#" in p:
            self.error(loc, f"anchors are not accepted here (anchor checks belong to T-81): {_r(value)}")
            return None
        return p

    def file_paths(self, value: Any, loc: str, allow_empty: bool = True) -> tuple[str, ...]:
        out: list[str] = []
        for i, item in enumerate(self.items(value, loc, allow_empty) or []):
            p = self.file_path(item, f"{loc}[{i}]")
            if p is None:
                continue
            if p in out:
                self.error(f"{loc}[{i}]", f"listed twice: {p}")
                continue
            out.append(p)
        return tuple(out)

    def identifier(self, value: Any, loc: str) -> str | None:
        s = self.string(value, loc)
        if s is not None and len(s) > MAX_ID_LENGTH:
            self.error(loc, f"longer than {MAX_ID_LENGTH} characters: {_r(s)}")
            return None
        if s is not None and not ID_RE.match(s):
            self.error(loc, f"must use lowercase letters, digits and single hyphens: {_r(s)}")
            return None
        return s

    def version(self, data: dict, loc: str = "version") -> int:
        v = data.get("version")
        if "version" in data and (isinstance(v, bool) or not isinstance(v, int) or v != 1):
            self.error(loc, f"unsupported version {_r(v)} (expected 1)")
        return 1


def _r(value: Any, limit: int = 80) -> str:
    """A bounded description of a value for messages; never repr() of a whole container
    (see paths.bounded_repr: YAML alias fan-out)."""
    return bounded_repr(value, limit)


def _identity(value: Any) -> str:
    """A short, collision-resistant identity for a scalar config value, used in finding
    subjects: type plus the value, or plus a hash when the value is long."""
    text = bounded_repr(value, 100)
    if isinstance(value, (str, int)) and text.endswith(")"):        # the value was cut
        digest = hashlib.sha256(f"{type(value).__name__}:{value}".encode("utf-8", "surrogatepass")).hexdigest()
        text = f"{text[:60]}#{digest[:16]}"
    return f"{type(value).__name__} {text}"


def _kind(value: Any) -> str:
    return "null" if value is None else type(value).__name__


def _join(loc: str, key: Any) -> str:
    return f"{loc}.{key}" if loc else str(key)


# --------------------------------------------------------------------------- impact.yml

def parse_config(data: Any, source: str = CONFIG_FILE) -> tuple[Config, list[Problem]]:
    """Check `impact.yml` data. Always returns a Config (defaults where invalid)."""
    ck = _Checker(source)
    d = ck.mapping(data, "", CONFIG_KEYS, required=("version", "registry")) or {}
    version = ck.version(d)

    registry = ck.file_path(d["registry"], "registry") if "registry" in d else None

    ignore = ck.patterns(d.get("ignore", []), "ignore")

    purposes: list[tuple[str, tuple[str, ...]]] = []
    for i, entry in enumerate(ck.items(d.get("purposes", []), "purposes") or []):
        loc = f"purposes[{i}]"
        e = ck.mapping(entry, loc, ("purpose", "paths"), required=("purpose", "paths"))
        if e is None or "purpose" not in e or "paths" not in e:
            continue
        name = e["purpose"]
        if name not in PURPOSES:
            ck.error(f"{loc}.purpose", f"unknown purpose {_r(name)} (allowed: {', '.join(PURPOSES)})")
            continue
        pats = ck.patterns(e["paths"], f"{loc}.paths", allow_empty=False)
        if pats:
            purposes.append((name, pats))

    exempt = DEFAULT_EXEMPT_PURPOSES
    if "doc_obligation" in d:
        ob = ck.mapping(d["doc_obligation"], "doc_obligation", ("exempt_purposes",)) or {}
        if "exempt_purposes" in ob:
            vals = ck.items(ob["exempt_purposes"], "doc_obligation.exempt_purposes") or []
            for i, v in enumerate(vals):
                if v not in PURPOSES:
                    # The index keeps findings distinct even for equal-looking or container values.
                    ck.error(f"doc_obligation.exempt_purposes[{i}]", f"unknown purpose {_r(v)}")
            exempt = tuple(v for v in vals if v in PURPOSES)

    interfaces: list[tuple[str, tuple[str, ...]]] = []
    for i, entry in enumerate(ck.items(d.get("interfaces", []), "interfaces") or []):
        loc = f"interfaces[{i}]"
        e = ck.mapping(entry, loc, ("kind", "paths"), required=("kind", "paths"))
        if e is None or "kind" not in e or "paths" not in e:
            continue
        kind = ck.identifier(e["kind"], f"{loc}.kind")
        pats = ck.patterns(e["paths"], f"{loc}.paths", allow_empty=False)
        if kind and pats:
            interfaces.append((kind, pats))

    rules = _rule_section(ck, d.get("rules", {}), "rules", CHECK_RULES)
    validate_rules = _rule_section(ck, d.get("validate", {}), "validate", VALIDATE_RULES)

    include: tuple[str, ...] = ("**/*.md",)
    exclude: tuple[str, ...] = ()
    if "reference_scan" in d:
        rs = ck.mapping(d["reference_scan"], "reference_scan", ("include", "exclude")) or {}
        if "include" in rs:
            include = ck.patterns(rs["include"], "reference_scan.include")
        if "exclude" in rs:
            exclude = ck.patterns(rs["exclude"], "reference_scan.exclude")

    min_len, placeholders = DEFAULT_MIN_REASON_LENGTH, DEFAULT_PLACEHOLDERS
    if "acks" in d:
        ac = ck.mapping(d["acks"], "acks", ("min_reason_length", "placeholders")) or {}
        if "min_reason_length" in ac:
            v = ac["min_reason_length"]
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                ck.error("acks.min_reason_length", f"must be a whole number of at least 1, not {_r(v)}")
            else:
                min_len = v
        if "placeholders" in ac:
            vals = []
            for i, v in enumerate(ck.items(ac["placeholders"], "acks.placeholders") or []):
                s = ck.string(v, f"acks.placeholders[{i}]")
                if s is not None:
                    vals.append(s.strip().lower())
            placeholders = tuple(vals)

    config = Config(
        version=version, registry=registry, ignore=ignore, purposes=tuple(purposes),
        exempt_purposes=frozenset(exempt), interfaces=tuple(interfaces), rules=rules,
        validate_rules=validate_rules, reference_include=include, reference_exclude=exclude,
        ack_min_reason_length=min_len, ack_placeholders=placeholders,
    )
    return config, ck.problems


def _rule_section(ck: _Checker, value: Any, loc: str, allowed: tuple[str, ...]) -> dict[str, str]:
    """Configurable rules default to WARNING; fixed rules may not appear at all."""
    result = {name: "WARNING" for name in allowed}
    section = ck.mapping(value, loc, allowed + FIXED_RULES + CHECK_RULES + VALIDATE_RULES)
    if section is None:
        return result
    for name, val in section.items():
        key = _join(loc, name)
        if name in FIXED_RULES:
            ck.error(key, f"{_r(name)} is a fixed rule and cannot be configured")
        elif name not in allowed:
            if name in CHECK_RULES + VALIDATE_RULES:
                ck.error(key, f"{_r(name)} belongs under '{'validate' if name in VALIDATE_RULES else 'rules'}:'")
            # unknown names were already reported by mapping()
        elif val not in RULE_VALUES:
            ck.error(key, f"must be one of {', '.join(RULE_VALUES)} (ERROR is not allowed), not {_r(val)}")
        else:
            result[name] = val
    return result


# --------------------------------------------------------------------------- registry

def parse_registry(data: Any, source: str) -> tuple[Registry, list[Problem]]:
    """Check registry data. Invalid entries are skipped; every problem is reported."""
    ck = _Checker(source)
    d = ck.mapping(data, "", REGISTRY_KEYS, required=("version", "components")) or {}
    version = ck.version(d)

    components: list[Component] = []
    seen: set[str] = set()
    raw_deps: list[tuple[str, int, int, Any]] = []
    for i, entry in enumerate(ck.items(d.get("components", []), "components") or []):
        loc = f"components[{i}]"
        e = ck.mapping(entry, loc, COMPONENT_KEYS, required=("id", "paths", "docs"))
        if e is None or any(k not in e for k in ("id", "paths", "docs")):
            continue
        cid = ck.identifier(e["id"], f"{loc}.id")
        if cid is None:
            continue
        if cid in seen:
            ck.error(f"{loc}.id", f"duplicate component id {_r(cid)}")
            continue
        n_before = len(ck.problems)
        paths = ck.patterns(e["paths"], f"{loc}.paths", allow_empty=False)
        exclude = ck.patterns(e.get("exclude", []), f"{loc}.exclude")
        docs = ck.file_paths(e["docs"], f"{loc}.docs")
        generated = ck.file_paths(e.get("generated", []), f"{loc}.generated")
        planned = ck.boolean(e["planned"], f"{loc}.planned") if "planned" in e else False
        note = ck.string(e["note"], f"{loc}.note") if "note" in e else None
        interfaces = _interfaces(ck, e.get("interfaces", []), f"{loc}.interfaces", paths, exclude, cid)
        deps = _dependencies(ck, e.get("depends_on", []), f"{loc}.depends_on", cid)
        if len(ck.problems) != n_before or not paths:
            seen.add(cid)  # keep the id reserved so duplicates are still caught
            continue
        seen.add(cid)
        components.append(Component(cid, paths, exclude, docs, generated, interfaces, deps, bool(planned), note))

    known = {c.id for c in components} | seen
    for c_index, comp in enumerate(components):
        for dep in comp.depends_on:
            if dep.id not in known:
                ck.error(f"component {comp.id}.depends_on", f"unknown component {_r(dep.id)}",
                         subject=f"depends_on {dep.id}")

    triggers: list[Trigger] = []
    tseen: set[str] = set()
    for i, entry in enumerate(ck.items(d.get("content_triggers", []), "content_triggers") or []):
        loc = f"content_triggers[{i}]"
        e = ck.mapping(entry, loc, TRIGGER_KEYS, required=("id", "paths", "match", "docs"))
        if e is None or any(k not in e for k in ("id", "paths", "match", "docs")):
            continue
        tid = ck.identifier(e["id"], f"{loc}.id")
        if tid is None:
            continue
        if tid in tseen:
            ck.error(f"{loc}.id", f"duplicate content trigger id {_r(tid)}")
            continue
        tseen.add(tid)
        n_before = len(ck.problems)
        paths = ck.patterns(e["paths"], f"{loc}.paths", allow_empty=False)
        exclude = ck.patterns(e.get("exclude", []), f"{loc}.exclude")
        docs = ck.file_paths(e["docs"], f"{loc}.docs", allow_empty=False)
        note = ck.string(e["note"], f"{loc}.note") if "note" in e else None
        match = ck.string(e["match"], f"{loc}.match")
        regex = profile = None
        if match is not None:
            try:
                profile = regexsafe.check(match)
                regex = re.compile(match)
            except regexsafe.UnsafeRegex as exc:
                ck.error(f"{loc}.match", f"unsafe or invalid content-trigger pattern: {exc}")
        if len(ck.problems) != n_before or regex is None or not paths or not docs:
            continue
        triggers.append(Trigger(tid, paths, exclude, match, regex, profile, docs, note))

    return Registry(version, tuple(components), tuple(triggers)), ck.problems


def _interfaces(ck: _Checker, value: Any, loc: str, paths: tuple[str, ...],
                exclude: tuple[str, ...], cid: str) -> tuple[Interface, ...]:
    out: list[Interface] = []
    for i, entry in enumerate(ck.items(value, loc) or []):
        iloc = f"{loc}[{i}]"
        e = ck.mapping(entry, iloc, ("path", "contract"), required=("path", "contract"))
        if e is None or "path" not in e or "contract" not in e:
            continue
        path = ck.file_path(e["path"], f"{iloc}.path")
        contract = ck.file_path(e["contract"], f"{iloc}.contract")
        if path is None or contract is None:
            continue
        inside = any(matches(path, p) for p in paths) and not any(matches(path, x) for x in exclude)
        if not inside:
            ck.error(f"{iloc}.path", f"{path} is not covered by component {_r(cid)}'s own paths")
            continue
        out.append(Interface(path, contract))
    return tuple(out)


def _dependencies(ck: _Checker, value: Any, loc: str, cid: str) -> tuple[Dependency, ...]:
    out: list[Dependency] = []
    for i, entry in enumerate(ck.items(value, loc) or []):
        dloc = f"{loc}[{i}]"
        e = ck.mapping(entry, dloc, ("id", "basis", "evidence", "note"), required=("id", "basis"))
        if e is None or "id" not in e or "basis" not in e:
            continue
        did = ck.identifier(e["id"], f"{dloc}.id")
        basis = e["basis"]
        if basis not in DEPENDENCY_BASES:
            ck.error(f"{dloc}.basis", f"must be one of {', '.join(DEPENDENCY_BASES)}, not {_r(basis)}")
            continue
        evidence = ck.string(e["evidence"], f"{dloc}.evidence") if "evidence" in e else None
        note = ck.string(e["note"], f"{dloc}.note") if "note" in e else None
        if basis == "code" and "evidence" not in e:
            ck.error(dloc, "basis 'code' requires 'evidence' (where in the source the link is seen)")
            continue
        if basis == "inferred" and "note" not in e:
            ck.error(dloc, "basis 'inferred' requires a 'note' explaining the assumption")
            continue
        if did is None:
            continue
        if did == cid:
            ck.error(f"{dloc}.id", "a component cannot depend on itself")
            continue
        if any(d.id == did for d in out):
            ck.error(f"{dloc}.id", f"dependency on {_r(did)} listed twice")
            continue
        out.append(Dependency(did, basis, evidence, note))
    return tuple(out)


# --------------------------------------------------------------------------- loading

def load(root: Path) -> Loaded:
    """Load `impact.yml` and its registry from a repository root.

    Raises LoadError when a file cannot be read or parsed; schema problems are
    returned in `Loaded.problems`.
    """
    config, problems = parse_config(read_yaml(root / CONFIG_FILE), CONFIG_FILE)
    registry = None
    if config.registry is not None:
        registry, reg_problems = parse_registry(read_yaml(root / config.registry), config.registry)
        problems = problems + reg_problems
    return Loaded(config, registry, tuple(sorted(problems)))


def load_for_report(root: Path) -> tuple[Config | None, Registry | None, list[Problem], list[str]]:
    """Like `load`, but a configuration file that is missing or cannot be parsed
    becomes a registry-invalid ERROR problem instead of an exception, so that
    `impact validate` can report it (exit code 1). Operational read failures still
    raise LoadError(operational=True) (exit code 2).

    Returns (config or None, registry or None, problems, configuration files read).
    """
    def as_problem(source: str, exc: LoadError) -> Problem:
        return Problem(source, "(file)", source, "registry-invalid", "ERROR", str(exc))

    try:
        data = read_yaml(root / CONFIG_FILE)
    except LoadError as exc:
        if exc.operational:
            raise
        return None, None, [as_problem(CONFIG_FILE, exc)], []
    config, problems = parse_config(data, CONFIG_FILE)
    sources = [CONFIG_FILE]
    if config.registry is None:
        return config, None, problems, sources
    try:
        reg_data = read_yaml(root / config.registry)
    except LoadError as exc:
        if exc.operational:
            raise
        return config, None, problems + [as_problem(config.registry, exc)], sources
    registry, reg_problems = parse_registry(reg_data, config.registry)
    return config, registry, problems + reg_problems, sources + [config.registry]


# --------------------------------------------------------------------------- file checks

def check_files(config: Config, registry: Registry, source: str, files: Iterable[str]) -> list[Problem]:
    """Existence and completeness checks against a list of repository files.

    ERROR (registry-missing-path): a listed doc, generated doc, interface path or
    contract does not exist. Planned components may lack their `paths`,
    `generated` docs and interface paths, but their docs and contracts must exist.
    WARNING (registry-incomplete): a pattern of a non-planned component, or of a
    content trigger, matches no file.
    """
    # Files come from Git (or tests) already in repository form; repo_path validates
    # them without rewriting backslashes.
    fileset = {repo_path(f) for f in files}
    out: list[Problem] = []
    incomplete = config.validate_rules.get("registry-incomplete", "WARNING")

    def missing(loc: str, path: str, what: str) -> None:
        out.append(Problem(source, loc, f"{what}: {path}", "registry-missing-path", "ERROR",
                           f"{what} does not exist: {path}"))

    def unmatched(loc: str, pattern: str) -> None:
        if incomplete != "off":
            out.append(Problem(source, loc, pattern, "registry-incomplete", "WARNING",
                               f"pattern matches no file: {pattern}"))

    for comp in registry.components:
        loc = f"component {comp.id}"
        for doc in comp.docs:
            if doc not in fileset:
                missing(f"{loc}.docs", doc, "doc")
        for iface in comp.interfaces:
            if iface.contract not in fileset:
                missing(f"{loc}.interfaces", iface.contract, "contract")
            if not comp.planned and iface.path not in fileset:
                missing(f"{loc}.interfaces", iface.path, "interface path")
        if not comp.planned:
            for doc in comp.generated:
                if doc not in fileset:
                    missing(f"{loc}.generated", doc, "generated doc")
            for pat in comp.paths:
                if not any(matches(f, pat) for f in fileset):
                    unmatched(f"{loc}.paths", pat)
    for trig in registry.triggers:
        loc = f"content trigger {trig.id}"
        for doc in trig.docs:
            if doc not in fileset:
                missing(f"{loc}.docs", doc, "doc")
        for pat in trig.paths:
            if not any(matches(f, pat) for f in fileset):
                unmatched(f"{loc}.paths", pat)
    return sorted(out)
