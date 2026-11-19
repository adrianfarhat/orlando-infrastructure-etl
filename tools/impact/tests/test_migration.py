"""Migration proof: docs/doc-map.yml (frozen at 565706f) -> registry/components.yml.

Three independent layers, so the proof does not rest on two implementations agreeing:

1. KnownResultTests: hand-computed relationship sets for the old doc-map rules
   (exclusions, overlapping entries, the content trigger, generated docs). Both the
   old re-implementation and the new resolver must reproduce them exactly.
2. MigrationProofTests: every one of the 50 files tracked at 565706f plus edge cases,
   resolved by the old rules (stdlib glob.translate) and by tools.impact.resolve.
   No old relationship may be missing from the new mapping.
3. Every relationship the new mapping ADDS must be listed in EXPECTED_ADDITIONS with a
   reason. These are proposed differences for owner review, not accepted changes; an
   unlisted addition fails the test.

A relationship is (path, doc, kind) with kind "reviewed", "generated" or "trigger"
(doc-map's `match` entries map to "trigger").
"""

import glob
import hashlib
import json
import re
import unittest
from pathlib import Path

from ruamel.yaml import YAML

from tools.impact.config import load
from tools.impact.resolve import resolve

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
DOCMAP_FIXTURE = FIXTURES / "docmap_565706f.yml"
TRACKED_FIXTURE = FIXTURES / "tracked_565706f.json"
TRIGGER_TEXT = "DATABASE_URL"

ETL = "docs/architecture/etl-workflow.md"
SA = "docs/architecture/system-architecture.md"
SO = "docs/architecture/system-overview.md"
DS = "docs/architecture/database-schema.md"
DC = "docs/architecture/data-contracts.md"
GEN = "docs/architecture/generated/schema.md"
CONV = "docs/architecture/conventions.md"
R, G, T = "reviewed", "generated", "trigger"

# Proposed differences (new relationships with no doc-map equivalent). Owner review pending.
EXPECTED_ADDITIONS = {
    ("requirements.txt", SO, R):
        "new component python-deps: system-overview.md states where Python dependencies are pinned "
        "(requirements.txt was added by T-59, after doc-map.yml was written)",
    ("impact.yml", CONV, R):
        "new component impact-tool: conventions.md section 5 describes the documentation workflow",
    ("registry/components.yml", CONV, R):
        "new component impact-tool: conventions.md section 5 describes the documentation workflow",
    ("tools/impact/x.py", CONV, R):
        "new component impact-tool (hypothetical tool file): conventions.md section 5",
}

# Paths beyond the 50 tracked files: (path, file contains DATABASE_URL).
EDGE_CASES = [
    ("database/migrations/0001_baseline.sql", False),   # planned entry 9; excluded from entry 2
    ("database/other.py", False),
    ("database/other.py", True),
    ("web/src/app/api/new/route.ts", False),            # entry 3, excluded from entry 5
    ("web/src/app/new/page.tsx", False),                # entry 5
    ("extractors/new loader.py", False),                # space in the name
    ("extractors/new loader.py", True),
    ("extractors/naïve.py", False),                # non-ASCII name
    ("extractors/naïve.py", True),
    ("web/src/lib/x.ts", False),
    ("web/src/lib/x.ts", True),                          # entries 4 and 8 overlap
    ("web/src/components/x.tsx", True),                  # entries 5 and 8 overlap
    ("docs/agents/x.md", False),                         # entry 10: no docs
    ("docs/architecture/generated/schema.md", False),
    ("tools/impact/x.py", False),
    ("tools/impact/x.py", True),
    ("impact.yml", False),
    ("registry/components.yml", False),
    ("foo/bar.txt", False),                              # unknown folder
    ("data/raw/orlando_manholes.geojson", False),        # ignored by the new config
    (".local/impact/report.md", False),                  # ignored by the new config
]

# Hand-computed from doc-map.yml's rules (not from either implementation).
KNOWN_OLD = {
    ("extractors/load_orlando_streets.py", True): {(ETL, R), (SA, R), (SO, R), (DS, R), (DC, R), (SA, T)},
    ("extractors/load_orlando_streets.py", False): {(ETL, R), (SA, R), (SO, R), (DS, R), (DC, R)},
    ("database/test_connection.py", True): {(DS, R), (DC, R), (ETL, R), (SA, T)},
    ("database/migrations/0001_baseline.sql", False): {(DS, R), (DC, R), (GEN, G)},   # not entry 2
    ("web/src/app/api/infrastructure/stats/route.ts", False): {(DC, R), (SA, R), (DS, R)},  # not entry 5
    ("web/src/app/page.tsx", False): {(SA, R)},
    ("web/src/lib/db.ts", True): {(SA, R), (SA, T)},
    ("web/src/lib/db.ts", False): {(SA, R)},
    ("web/src/components/x.tsx", True): {(SA, R), (SA, T)},
    ("web/package.json", False): {(SO, R), (SA, R)},
    ("web/public/maplibre-gl-worker.mjs", False): {(SO, R)},
    ("docs/agents/task-board.md", True): set(),     # entry 10 maps nothing; .md is not a trigger path
    ("CLAUDE.md", True): set(),                     # contains DATABASE_URL, but not a trigger path
    ("requirements.txt", False): set(),
    ("tools/impact/x.py", True): {(SA, T)},         # only the **/*.py trigger
    ("foo/bar.txt", False): set(),
}


# ----------------------------------------------------------------- old rules (independent)

def _old_match(path, pattern):
    return re.fullmatch(glob.translate(pattern, recursive=True, include_hidden=True), path) is not None


def load_docmap():
    return YAML(typ="safe", pure=True).load(DOCMAP_FIXTURE.read_bytes().decode("utf-8"))


def old_relationships(entries, path, has_trigger_text):
    """doc-map.yml semantics: the union of every matching entry."""
    text = TRIGGER_TEXT if has_trigger_text else ""
    rels = set()
    for e in entries:
        if not any(_old_match(path, p) for p in e["paths"]):
            continue
        if any(_old_match(path, x) for x in e.get("exclude") or []):
            continue
        if "match" in e and not re.search(e["match"], text):
            continue
        kind = T if "match" in e else R
        rels |= {(d, kind) for d in e.get("reviewed") or []}
        rels |= {(d, G) for d in e.get("generated") or []}
    return rels


def new_relationships(loaded, path, has_trigger_text):
    text = TRIGGER_TEXT if has_trigger_text else ""
    return set(resolve(path, loaded.config, loaded.registry, text).doc_pairs())


def tracked_cases():
    data = json.loads(TRACKED_FIXTURE.read_text("utf-8"))
    return [(f["path"], f["contains_database_url"]) for f in data["files"]], data


def git_blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


# ----------------------------------------------------------------- tests

class FixtureIntegrityTests(unittest.TestCase):
    def test_docmap_fixture_is_the_565706f_blob(self):
        _, data = tracked_cases()
        raw = DOCMAP_FIXTURE.read_bytes()
        # Git's clean filter turns CRLF into LF when autocrlf is on; compare like Git does.
        self.assertEqual(git_blob_id(raw.replace(b"\r\n", b"\n")), data["docmap_blob"])
        self.assertEqual(data["commit"], "565706f36af58a0759b692a8777e6bdd3310c9ee")

    def test_tracked_fixture_counts(self):
        cases, _ = tracked_cases()
        self.assertEqual(len(cases), 50)
        self.assertEqual(len({p for p, _ in cases}), 50)
        self.assertEqual(sum(flag for _, flag in cases), 17)

    def test_trigger_shortcut_is_valid(self):
        """The fixture stores only 'contains DATABASE_URL'. That stands in for file text only
        because both the old and the new trigger regex are exactly that literal."""
        old = [e for e in load_docmap() if "match" in e]
        self.assertEqual([e["match"] for e in old], [TRIGGER_TEXT])
        new = load(REPO_ROOT).registry.triggers
        self.assertEqual([t.match for t in new], [TRIGGER_TEXT])
        self.assertEqual(re.escape(TRIGGER_TEXT), TRIGGER_TEXT)  # no regex metacharacters

    def test_docmap_has_the_ten_known_entries(self):
        entries = load_docmap()
        self.assertEqual(len(entries), 10)
        self.assertEqual([e["paths"] for e in entries], [
            ["extractors/**"], ["database/**"], ["web/src/app/api/**"], ["web/src/lib/**"],
            ["web/src/components/**", "web/src/app/**"], ["web/public/**"],
            ["web/next.config.ts", "web/package.json"],
            ["**/*.py", "web/src/**/*.ts", "web/src/**/*.tsx"], ["database/migrations/**"], ["docs/agents/**"]])


class KnownResultTests(unittest.TestCase):
    def setUp(self):
        self.entries = load_docmap()
        self.loaded = load(REPO_ROOT)

    def test_old_rules_reproduce_hand_computed_results(self):
        for (path, flag), expected in KNOWN_OLD.items():
            with self.subTest(path=path, database_url=flag):
                self.assertEqual(old_relationships(self.entries, path, flag), expected)

    def test_new_registry_reproduces_hand_computed_results(self):
        for (path, flag), expected in KNOWN_OLD.items():
            added = {(d, k) for (p, d, k) in EXPECTED_ADDITIONS if p == path}
            with self.subTest(path=path, database_url=flag):
                self.assertEqual(new_relationships(self.loaded, path, flag), expected | added)


class MigrationProofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        entries = load_docmap()
        loaded = load(REPO_ROOT)
        tracked, _ = tracked_cases()
        cls.cases = tracked + EDGE_CASES
        cls.lost, cls.added = set(), set()
        cls.old_total = cls.new_total = 0
        for path, flag in cls.cases:
            old = old_relationships(entries, path, flag)
            new = new_relationships(loaded, path, flag)
            cls.old_total += len(old)
            cls.new_total += len(new)
            cls.lost |= {(path, d, k) for d, k in old - new}
            cls.added |= {(path, d, k) for d, k in new - old}

    def test_case_count(self):
        self.assertEqual(len(self.cases), 50 + len(EDGE_CASES))

    def test_no_relationship_is_lost(self):
        self.assertEqual(self.lost, set(), "relationships lost in the migration:\n" +
                         "\n".join(map(str, sorted(self.lost))))

    def test_every_addition_is_listed_for_review(self):
        unexpected = self.added - set(EXPECTED_ADDITIONS)
        self.assertEqual(unexpected, set(), "unlisted additions:\n" + "\n".join(map(str, sorted(unexpected))))

    def test_every_listed_addition_actually_occurs(self):
        self.assertEqual(set(EXPECTED_ADDITIONS) - self.added, set())

    def test_report_difference_table(self):
        lines = ["", "Migration difference table (doc-map.yml @565706f -> registry/components.yml)",
                 f"cases: {len(self.cases)} (50 tracked + {len(EDGE_CASES)} edge) | "
                 f"relationships old: {self.old_total}, new: {self.new_total} | "
                 f"lost: {len(self.lost)} | added: {len(self.added)}",
                 "change | path | doc | kind | reason"]
        for path, doc, kind in sorted(self.lost):
            lines.append(f"LOST | {path} | {doc} | {kind} | -")
        for key in sorted(self.added):
            lines.append(f"ADDED | {key[0]} | {key[1]} | {key[2]} | {EXPECTED_ADDITIONS.get(key, 'UNEXPECTED')}")
        print("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
