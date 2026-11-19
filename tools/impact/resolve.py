"""Resolve one repository path: ignored?, purpose, component, triggers, doc relationships.

Pure functions over a loaded Config and Registry. File text, when needed for
content triggers, is passed in by the caller; nothing is read from disk here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .config import Component, Config, Problem, Registry, Trigger
from .paths import matches, normalize, specificity

REVIEWED, GENERATED, TRIGGER = "reviewed", "generated", "trigger"


@dataclass(frozen=True, order=True)
class Relationship:
    doc: str
    kind: str      # "reviewed", "generated" or "trigger"
    source: str    # component or content-trigger id


@dataclass(frozen=True)
class Resolution:
    path: str
    ignored: bool
    purpose: str | None
    component: str | None             # best match, or None if unregistered or ambiguous
    ambiguous: tuple[str, ...]        # ids tied for best match (empty unless tied)
    triggers: tuple[str, ...]         # content triggers that fired (empty if no text given)
    relationships: frozenset[Relationship]
    doc_obligation: bool              # mapped docs exist and the purpose is not exempt

    @property
    def registered(self) -> bool:
        return self.component is not None or bool(self.ambiguous)

    def doc_pairs(self) -> frozenset[tuple[str, str]]:
        """Relationships as (doc, kind), without their source."""
        return frozenset((r.doc, r.kind) for r in self.relationships)


def is_ignored(path: str, config: Config) -> bool:
    return any(matches(path, p) for p in config.ignore)


def purpose_of(path: str, config: Config) -> str:
    """First matching purpose in config order; 'code' when none matches."""
    for name, patterns in config.purposes:
        if any(matches(path, p) for p in patterns):
            return name
    return "code"


def _component_score(path: str, comp: Component) -> tuple[int, bool] | None:
    hits = [p for p in comp.paths if matches(path, p)]
    if not hits or any(matches(path, x) for x in comp.exclude):
        return None
    return max(specificity(p) for p in hits)


def best_components(path: str, registry: Registry) -> tuple[Component, ...]:
    """Components tied for the most specific match (empty if unregistered)."""
    scored = [(s, c) for c in registry.components if (s := _component_score(path, c)) is not None]
    if not scored:
        return ()
    top = max(s for s, _ in scored)
    return tuple(sorted((c for s, c in scored if s == top), key=lambda c: c.id))


def triggers_for(path: str, text: str | None, registry: Registry) -> tuple[Trigger, ...]:
    """Content triggers whose paths match and whose regex is found in the text.

    With text=None (content unknown) no trigger fires.
    """
    if text is None:
        return ()
    out = []
    for t in registry.triggers:
        if any(matches(path, p) for p in t.paths) and not any(matches(path, x) for x in t.exclude):
            if t.regex.search(text):
                out.append(t)
    return tuple(sorted(out, key=lambda t: t.id))


def resolve(path: str, config: Config, registry: Registry, text: str | None = None) -> Resolution:
    p = normalize(path)
    if is_ignored(p, config):
        return Resolution(p, True, None, None, (), (), frozenset(), False)
    purpose = purpose_of(p, config)
    best = best_components(p, registry)
    # On a tie, relationships are the union of the tied components, so nothing is lost;
    # `impact validate` reports the tie so the registry can be fixed.
    rels: set[Relationship] = set()
    for comp in best:
        rels.update(Relationship(d, REVIEWED, comp.id) for d in comp.docs)
        rels.update(Relationship(d, GENERATED, comp.id) for d in comp.generated)
    fired = triggers_for(p, text, registry)
    for t in fired:
        rels.update(Relationship(d, TRIGGER, t.id) for d in t.docs)
    obligation = any(comp.docs for comp in best) and purpose not in config.exempt_purposes
    return Resolution(
        path=p,
        ignored=False,
        purpose=purpose,
        component=best[0].id if len(best) == 1 else None,
        ambiguous=tuple(c.id for c in best) if len(best) > 1 else (),
        triggers=tuple(t.id for t in fired),
        relationships=frozenset(rels),
        doc_obligation=obligation,
    )


def ambiguities(config: Config, registry: Registry, source: str, files: Iterable[str]) -> list[Problem]:
    """WARNING (registry-incomplete) for each file matched equally well by several components."""
    if config.validate_rules.get("registry-incomplete", "WARNING") == "off":
        return []
    out = []
    for f in sorted({normalize(x) for x in files}):
        if is_ignored(f, config):
            continue
        best = best_components(f, registry)
        if len(best) > 1:
            ids = ", ".join(c.id for c in best)
            out.append(Problem(source, f"path {f}", "registry-incomplete", "WARNING",
                               f"ambiguous: equally specific match in components {ids}"))
    return out
