"""T-97 PR A: the diagram registry, stable IDs, safe operations, fingerprints (U13) and stage M0.

Acceptance tests of the T-97 card (A1–A13, T1–T6) at the tooling level; design:
docs/architecture/diagram-library.md.
"""

import os
import re
import shutil
import unittest
from pathlib import Path
from unittest import mock

from tools.design import architecture, designer_api, diagrams, ownership, registry, workspace
from tools.design.tests.test_design import REPO_ROOT, Workspace, cmd
from tools.design.workspace import DesignError, new_feature

ETL = "etl-workflow/streets--road_segments"


def check(ws):
    return [f"{p.path}: {p.message}" for p in workspace.check(ws.root)]


def insert(ws, feature_rel, diagram_id, heading="## 3. Logic"):
    """Insert a block the way the Feature Designer does (designer interface), then save."""
    text = (ws.root / feature_rel).read_text(encoding="utf-8")
    lines = text.split("\n")
    at = lines.index(heading) + 2
    while lines[at].strip():
        at += 1
    r, code = designer_api.handle(ws.root, {"version": 1, "op": "insert", "path": feature_rel, "text": text, "at": at,
                                            "diagram_id": diagram_id})
    assert code == 0, r
    e = r["edits"][0]
    lines[e["start"]:e["end"]] = e["lines"]
    (ws.root / feature_rel).write_text("\n".join(lines), encoding="utf-8", newline="\n")


def marker_line(ws, rel, diagram_id):
    for i, line in enumerate((ws.root / rel).read_text(encoding="utf-8").split("\n"), 1):
        m = diagrams.START.match(line.strip())
        if m and m.group("id") == diagram_id:
            return i
    raise AssertionError(diagram_id)


class MakeNew(unittest.TestCase):
    def test_a1_a2_a3_standalone_source_name_and_stable_id(self):
        with Workspace() as ws:
            new_feature(ws.root, "test1")
            d = ownership.new_diagram(ws.root, "FD-0001", "One Map Pan", "system-architecture")
            self.assertEqual(d.path, "designs/features/diagrams/test1_system-architecture_one-map-pan.md")   # A1, A2
            self.assertTrue((ws.root / d.path).is_file())
            self.assertEqual(ws.meta(d.path)["diagram_id"], "FD-0001-D1")
            new = "designs/features/diagrams/renamed-anything.md"                       # A3: the name is not the ID
            os.rename(ws.root / d.path, ws.root / new)
            registry.relink(ws.root, "FD-0001-D1", path=new)
            e = registry.load(ws.root).by_id()["FD-0001-D1"]
            self.assertEqual((e.path, e.owner_ref), (new, "FD-0001"))
            self.assertEqual(check(ws), [])

    def test_a5_reuse_never_duplicates_and_never_changes_the_owner(self):
        with Workspace() as ws:
            a, b = new_feature(ws.root, "A"), new_feature(ws.root, "B")
            d = ownership.new_diagram(ws.root, "FD-0001", "Shared")
            insert(ws, a.path, d.diagram_id)
            insert(ws, b.path, d.diagram_id)
            cmd(ws.root, "index")
            self.assertEqual(check(ws), [])
            sources = sorted(p.name for p in (ws.root / "designs/features/diagrams").iterdir())
            self.assertEqual(sources, ["a_other_shared.md"])
            e = registry.load(ws.root).by_id()[d.diagram_id]
            self.assertEqual((e.owner_kind, e.owner_ref), ("feature", "FD-0001"))
            self.assertIn("| `FD-0001-D1` | Shared | mermaid-md | other | FD-0001 | active |",
                          ws.text(registry.DIAGRAM_INDEX))                                  # used by both
            self.assertIn("| FD-0001, FD-0002 |", ws.text(registry.DIAGRAM_INDEX))

    def test_e12_a_held_lock_refuses_and_creates_nothing(self):
        with Workspace() as ws:
            new_feature(ws.root, "A")
            lock = ws.root / registry.LOCK
            lock.parent.mkdir(parents=True, exist_ok=True)
            lock.write_text("{}")
            with self.assertRaisesRegex(DesignError, r"another diagram command is running .*\(E12\)"):
                ownership.new_diagram(ws.root, "FD-0001", "X")
            self.assertFalse((ws.root / "designs/features/diagrams").exists())
            old = lock.stat().st_mtime - 3600
            os.utime(lock, (old, old))
            with self.assertRaisesRegex(DesignError, "older than 10 minutes"):            # reported, never broken
                ownership.new_diagram(ws.root, "FD-0001", "X")
            self.assertTrue(lock.exists())

    def test_partial_failure_rolls_back_the_new_file(self):
        with Workspace() as ws:
            new_feature(ws.root, "A")
            before = (ws.root / registry.REGISTRY).read_bytes()
            with mock.patch.object(registry, "save", side_effect=DesignError("disk full (simulated)")):
                with self.assertRaisesRegex(DesignError, "disk full .*was not kept"):
                    ownership.new_diagram(ws.root, "FD-0001", "X")
            self.assertEqual(list((ws.root / "designs/features/diagrams").iterdir()), [])  # nothing left behind
            self.assertEqual((ws.root / registry.REGISTRY).read_bytes(), before)
            self.assertFalse((ws.root / registry.LOCK).exists())

    def test_compare_and_swap_refuses_a_registry_changed_meanwhile(self):
        with Workspace() as ws:
            reg = registry.load(ws.root)
            (ws.root / registry.REGISTRY).write_bytes((ws.root / registry.REGISTRY).read_bytes() + b"\n")
            with self.assertRaisesRegex(DesignError, r"the registry changed while this command ran.*\(E12\)"):
                registry.save(ws.root, reg.data, reg.sha)


class Sync(unittest.TestCase):
    def test_a6_t1_editing_one_source_refreshes_every_reference(self):
        with Workspace() as ws:
            feats = [new_feature(ws.root, n) for n in ("A", "B", "C")]
            d = ownership.new_diagram(ws.root, "FD-0001", "Shared")
            for f in feats:
                insert(ws, f.path, d.diagram_id)
            cmd(ws.root, "index")
            src = ws.root / d.path
            src.write_text(src.read_text(encoding="utf-8").replace("Existing step", "Changed step"), encoding="utf-8")
            found = check(ws)
            self.assertEqual(sum("is out of date with its source" in p for p in found), 3)   # case 1, each reference
            code, out, _ = cmd(ws.root, "index")
            self.assertEqual(out.count("refreshed 1 diagram block"), 3)
            for f in feats:
                self.assertIn("Changed step", ws.text(f.path))
            self.assertEqual(check(ws), [])

    def test_a9_an_unsaved_document_gets_proposed_edits_only_for_case_1(self):
        with Workspace() as ws:
            f = new_feature(ws.root, "A")
            insert(ws, f.path, ETL)
            cmd(ws.root, "index")
            saved = ws.text(f.path)
            unsaved = saved.replace("## 1. Objective", "## 1. Objective\n\nTyped but not saved.")
            r, _ = designer_api.handle(ws.root, {"version": 1, "op": "refresh", "path": f.path, "text": unsaved})
            self.assertEqual(r["edits"], [])                                          # nothing to change
            hand = unsaved.replace("S1 --> S2", "S1 --> S2 %% mine")
            r, _ = designer_api.handle(ws.root, {"version": 1, "op": "refresh", "path": f.path, "text": hand})
            self.assertEqual(r["edits"], [])                                          # a conflict is never edited
            self.assertIn("(E15)", r["conflicts"][0])
            self.assertEqual(ws.text(f.path), saved)                                  # nothing written to disk


class MovesAndRetire(unittest.TestCase):
    def test_a7_t2_move_keeps_id_and_owner_and_reports_until_relinked(self):
        with Workspace() as ws:
            parent = new_feature(ws.root, "P")
            new_feature(ws.root, "Child", parent=parent.feature_id, convert_parent=True)
            a = new_feature(ws.root, "A")
            d = ownership.new_diagram(ws.root, "FD-0001", "Moving")
            insert(ws, a.path, d.diagram_id)
            cmd(ws.root, "index")
            elsewhere = "designs/features/diagrams/moved_other_moving.md"
            (ws.root / elsewhere).parent.mkdir(parents=True, exist_ok=True)
            os.rename(ws.root / d.path, ws.root / elsewhere)
            found = "\n".join(check(ws))
            self.assertIn(f"FD-0001-D1 moved to {elsewhere}: run `python -m tools.design registry relink FD-0001-D1 "
                          f"--path {elsewhere}` (E6)", found)
            outside = "designs/elsewhere.md"
            shutil.copy(ws.root / elsewhere, ws.root / outside)
            with self.assertRaisesRegex(DesignError, r"feature-owned sources belong in a diagrams/ folder .*\(U12\)"):
                registry.relink(ws.root, "FD-0001-D1", path=outside)
            os.unlink(ws.root / outside)
            registry.relink(ws.root, "FD-0001-D1", path=elsewhere)
            self.assertTrue(any("is out of date with its source" in p for p in check(ws)))   # E14: stale path
            moved = ws.root / elsewhere                                                     # the author fixes its own link
            moved.write_text(moved.read_text(encoding="utf-8").replace("](../README.md)", "](../p/README.md)"),
                             encoding="utf-8")
            cmd(ws.root, "index")
            self.assertIn("(diagrams/moved_other_moving.md)", ws.text(a.path))
            e = registry.load(ws.root).by_id()["FD-0001-D1"]
            self.assertEqual((e.diagram_id, e.owner_ref, e.path), ("FD-0001-D1", "FD-0001", elsewhere))
            self.assertEqual(check(ws), [])

    def test_retitle_writes_the_registry_and_the_front_matter(self):
        with Workspace() as ws:
            new_feature(ws.root, "A")
            d = ownership.new_diagram(ws.root, "FD-0001", "Old name")
            registry.relink(ws.root, "FD-0001-D1", title="New name")
            self.assertEqual(ws.meta(d.path)["title"], "New name")
            self.assertEqual(registry.load(ws.root).by_id()["FD-0001-D1"].title, "New name")
            self.assertEqual(check(ws), [])

    def test_a10_t3_retire_lists_references_needs_confirmation_and_never_reuses_the_id(self):
        with Workspace() as ws:
            a, b = new_feature(ws.root, "A"), new_feature(ws.root, "B")
            d = ownership.new_diagram(ws.root, "FD-0001", "Old")
            insert(ws, a.path, d.diagram_id)
            insert(ws, b.path, d.diagram_id)
            cmd(ws.root, "index")
            code, out, _ = cmd(ws.root, "registry", "retire", "FD-0001-D1")
            self.assertEqual(code, 1)
            self.assertEqual(out.count("diagram block FD-0001-D1"), 2)
            self.assertEqual(registry.load(ws.root).by_id()["FD-0001-D1"].status, "active")
            self.assertEqual(cmd(ws.root, "registry", "retire", "FD-0001-D1", "--confirm")[0], 0)
            found = check(ws)
            self.assertEqual(sum("was retired on" in p and "(E11)" in p for p in found), 2)
            os.unlink(ws.root / d.path)                                                 # deleting the file is optional
            self.assertFalse(any("does not exist" in p for p in check(ws)))
            self.assertEqual(ownership.new_diagram(ws.root, "FD-0001", "New").diagram_id, "FD-0001-D2")


class Validation(unittest.TestCase):
    def setUp(self):
        self.ctx = Workspace(); self.ws = self.ctx.__enter__()
        new_feature(self.ws.root, "A"); new_feature(self.ws.root, "B")
        self.d = ownership.new_diagram(self.ws.root, "FD-0001", "One")

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def edit_registry(self, old, new):
        path = self.ws.root / registry.REGISTRY
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def test_e2_e8_duplicates_and_collisions(self):
        self.edit_registry("aliases: [conventions/1-implementation-status-legend]",
                           "aliases: [conventions/1-implementation-status-legend, FD-0001-D1, "
                           "database-schema/a-the-team-workflow]")
        found = "\n".join(check(self.ws))
        self.assertIn("FD-0001-D1 is both a registry ID and an alias of AD-0001 (E8)", found)
        self.assertIn("database-schema/a-the-team-workflow is an alias of more than one entry", found)

    def test_e9_owner_and_prefix(self):
        self.edit_registry("owner: {kind: feature, ref: FD-0001}", "owner: {kind: feature, ref: FD-0002}")
        found = "\n".join(check(self.ws))
        self.assertIn("is owned by FD-0002 in the registry: the ID prefix must be the owner's (E9)", found)
        self.assertIn("feature_id is FD-0001 but the registry's owner of FD-0001-D1 is FD-0002; reuse never changes the "
                      "owner (E3, U10)", found)

    def test_formats_categories_and_reserved_formats(self):
        self.edit_registry("format: mermaid-md", "format: drawio-svg")
        self.assertIn("format drawio-svg is not accepted yet (visual diagrams arrive with the draw.io integration (PR C))",
                      "\n".join(check(self.ws)))
        self.edit_registry("format: drawio-svg", "format: mermaid-md")
        self.edit_registry("category: other", "category: architecture")
        self.assertIn("category must be one of system-architecture, data-model, process, sequence, state, ui, legend, "
                      "other, found 'architecture'", "\n".join(check(self.ws)))

    def test_e3_in_file_identity_and_title(self):
        src = self.ws.root / self.d.path
        src.write_text(src.read_text(encoding="utf-8").replace('title: "One"', 'title: "Other"'), encoding="utf-8")
        self.assertIn("title 'Other' differs from the registry's 'One'", "\n".join(check(self.ws)))

    def test_e1_unknown_and_resolve(self):
        r, code = designer_api.handle(self.ws.root, {"version": 1, "op": "resolve", "diagram_id": "AD-0099"})
        self.assertEqual(code, 1)
        self.assertIn("(E1)", r["error"]["message"])
        r, _ = designer_api.handle(self.ws.root, {"version": 1, "op": "resolve", "diagram_id": ETL})   # an alias
        self.assertEqual((r["id"], r["format"], r["editor"], r["path"]),
                         ("AD-0006", "mermaid-embedded", "architecture-docs", "docs/architecture/etl-workflow.md"))
        line = (self.ws.root / r["path"]).read_text(encoding="utf-8").split("\n")[r["line"] - 1]
        self.assertTrue(line.startswith("```mermaid"))
        r, _ = designer_api.handle(self.ws.root, {"version": 1, "op": "resolve", "diagram_id": "FD-0001-D1"})
        self.assertEqual((r["path"], r["editor"], r["owner"]), (self.d.path, "text", {"kind": "feature", "ref": "FD-0001"}))

    def test_writers_refuse_duplicate_or_colliding_ids(self):
        """QA D2: E2/E8 problems block every writer, not only schema problems."""
        self.edit_registry("aliases: [conventions/1-implementation-status-legend]",
                           "aliases: [conventions/1-implementation-status-legend, FD-0001-D1]")
        before = (self.ws.root / registry.REGISTRY).read_bytes()
        for call in (lambda: ownership.new_diagram(self.ws.root, "FD-0001", "Two"),
                     lambda: registry.relink(self.ws.root, "FD-0001-D1", title="Other"),
                     lambda: registry.retire(self.ws.root, "FD-0001-D1", True)):
            with self.assertRaisesRegex(DesignError, r"the registry has problems.*\(E8\)"):
                call()
        self.assertEqual((self.ws.root / registry.REGISTRY).read_bytes(), before)

    def test_the_registry_is_never_rewritten_while_invalid(self):
        self.edit_registry("version: 1", "version: 2")
        with self.assertRaisesRegex(DesignError, "the registry has problems"):
            ownership.new_diagram(self.ws.root, "FD-0001", "Two")
        self.assertEqual(len(list((self.ws.root / "designs/features/diagrams").iterdir())), 1)


class Fingerprints(unittest.TestCase):
    """U13: exact comparison; only line endings are normalised."""

    def b(self, fp):
        return diagrams.Block(0, 9, "X", fp)

    def test_classification(self):
        gen = ["cap", "```mermaid", "flowchart LR", "  A --> B", "```"]
        fp = diagrams.fingerprint(gen)
        new = gen[:3] + ["  A --> C", "```"]
        hand = gen[:3] + ["  A --> Z", "```"]
        self.assertEqual(diagrams.classify(self.b(fp), gen, gen), "current")
        self.assertEqual(diagrams.classify(self.b(fp), gen, new), "case1")                 # source changed only
        self.assertEqual(diagrams.classify(self.b(fp), hand, gen), "case2")                # hand edit only
        self.assertEqual(diagrams.classify(self.b(fp), hand, new), "case3")                # both changed
        self.assertEqual(diagrams.classify(self.b(fp), new, new), "fp-only")               # edited to the new output
        self.assertEqual(diagrams.classify(self.b(fp), [], new), "empty")
        self.assertEqual(diagrams.classify(self.b(None), hand, gen), "legacy")             # old marker, differs: kept
        self.assertEqual(diagrams.classify(self.b(None), gen, gen), "fp-only")             # old marker, exact: migrated
        self.assertEqual(diagrams.classify(self.b(None), [], gen), "empty")

    def test_only_line_endings_are_normalised(self):
        gen = ["cap", "```mermaid", "mindmap", "  root", "    child", "```"]
        fp = diagrams.fingerprint(gen)
        self.assertEqual(diagrams.classify(self.b(fp), [l + "\r" for l in gen], gen), "current")     # CRLF: same
        dedent = gen[:3] + ["  root", "  child", "```"]                                             # indentation
        self.assertEqual(diagrams.classify(self.b(fp), dedent, gen), "case2")
        blank = gen[:4] + ["", "    child", "```"]                                                  # a blank line
        self.assertEqual(diagrams.classify(self.b(fp), blank, gen), "case2")
        trailing = gen[:3] + ["  root ", "    child", "```"]                                        # trailing space
        self.assertEqual(diagrams.classify(self.b(fp), trailing, gen), "case2")


class Reconcile(unittest.TestCase):
    def setUp(self):
        self.ctx = Workspace(); self.ws = self.ctx.__enter__()
        self.a = new_feature(self.ws.root, "A")
        self.d = ownership.new_diagram(self.ws.root, "FD-0001", "Mine")
        insert(self.ws, self.a.path, self.d.diagram_id)
        insert(self.ws, self.a.path, ETL, heading="## 1. Objective")
        cmd(self.ws.root, "index")

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def hand_edit(self, old, new):
        p = self.ws.root / self.a.path
        p.write_text(p.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")

    def test_a13_apply_to_source_with_preview_token_and_source_check(self):
        self.hand_edit("New step (planned)", "New step (from the block)")
        line = marker_line(self.ws, self.a.path, "FD-0001-D1")
        code, out, _ = cmd(self.ws.root, "reconcile", "--file", self.a.path, "--line", str(line), "--apply-to-source")
        self.assertEqual(code, 0)
        self.assertIn(f"+++ {self.d.path} (after)", out)
        self.assertNotIn("from the block", self.ws.text(self.d.path))                      # preview writes nothing
        token = out.strip().split()[-1]
        src = self.ws.root / self.d.path                                                    # the source changes after the preview
        src.write_text(src.read_text(encoding="utf-8").replace("Existing step", "Existing step 2"), encoding="utf-8")
        code, out, _ = cmd(self.ws.root, "reconcile", "--file", self.a.path, "--line", str(line), "--apply-to-source",
                           "--confirm", token)
        self.assertEqual(code, 1)
        self.assertIn("changed since the preview", out)
        self.assertNotIn("from the block", self.ws.text(self.d.path))
        plan = diagrams.plan_reconcile(self.ws.root, self.a.path, line, "apply-to-source")
        self.assertEqual(plan.state, "case3")
        code, _, _ = cmd(self.ws.root, "reconcile", "--file", self.a.path, "--line", str(line), "--apply-to-source",
                         "--confirm", plan.token)
        self.assertEqual(code, 0)
        self.assertIn("New step (from the block)", self.ws.text(self.d.path))
        self.assertEqual(check(self.ws), [])

    def test_reconcile_rewrites_only_feature_documents_inside_the_repository(self):
        """QA D1: never docs/architecture/, never outside the repository, never a non-feature file."""
        block = (self.ws.root / self.a.path).read_text(encoding="utf-8")
        for rel in ("docs/architecture/evil.md", "../outside.md", "designs/notes.md"):
            with self.subTest(rel=rel):
                target = (self.ws.root / rel).resolve()
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(block, encoding="utf-8")
                before = target.read_bytes()
                line = marker_line(self.ws, self.a.path, "FD-0001-D1")
                with self.assertRaisesRegex(ValueError, "outside the repository|not a feature specification"):
                    diagrams.plan_reconcile(self.ws.root, rel, line, "discard")
                code, _, err = cmd(self.ws.root, "reconcile", "--file", rel, "--line", str(line), "--discard",
                                   "--confirm", "0123456789abcdef")
                self.assertEqual(code, 2, err)
                self.assertEqual(target.read_bytes(), before)
                target.unlink()

    def test_apply_to_source_refuses_marker_lines_and_warns_when_both_changed(self):
        """QA D3 and N4."""
        self.hand_edit("New step (planned)", "New step <!-- diagram:start AD-0010 -->")
        line = marker_line(self.ws, self.a.path, "FD-0001-D1")
        with self.assertRaisesRegex(ValueError, "would make the source impossible to embed"):
            diagrams.plan_reconcile(self.ws.root, self.a.path, line, "apply-to-source")
        self.hand_edit("New step <!-- diagram:start AD-0010 -->", "New step (mine)")
        src = self.ws.root / self.d.path
        src.write_text(src.read_text(encoding="utf-8").replace("Existing step", "Existing step 2"), encoding="utf-8")
        code, out, _ = cmd(self.ws.root, "reconcile", "--file", self.a.path, "--line", str(line), "--apply-to-source")
        self.assertEqual(code, 0)
        self.assertIn("Warning: the source has also changed since this block was generated", out)

    def test_architecture_sources_change_only_through_the_documentation_workflow(self):
        self.hand_edit("S1 --> S2", "S1 --> S2X")
        line = marker_line(self.ws, self.a.path, ETL)
        with self.assertRaisesRegex(ValueError, "technical-lead's documentation workflow"):
            diagrams.plan_reconcile(self.ws.root, self.a.path, line, "apply-to-source")
        code, _, err = cmd(self.ws.root, "reconcile", "--file", self.a.path, "--line", str(line), "--apply-to-source")
        self.assertEqual(code, 2)
        self.assertIn("technical-lead's documentation workflow", err)


class ArchitectureM0(unittest.TestCase):
    def test_m0_is_idempotent_preserves_documents_and_existing_references(self):
        with Workspace() as ws:
            cmd(ws.root, "index")
            before = {p: p.read_bytes() for p in (ws.root / "docs/architecture").rglob("*.md")}
            self.assertEqual(registry.adopt_architecture(ws.root), [])                        # already registered
            self.assertEqual({p: p.read_bytes() for p in (ws.root / "docs/architecture").rglob("*.md")}, before)
            entries = registry.load(ws.root).entries
            cat = architecture.catalog(architecture.documents(ws.root))
            self.assertEqual([(e.diagram_id, e.aliases) for e in entries],
                             [(f"AD-{n:04d}", (c.diagram_id,)) for n, c in enumerate(cat, 1)])
            self.assertEqual(check(ws), [])

    def test_a8_every_architecture_diagram_renders_byte_identically_through_its_alias(self):
        """A block that names a former catalog ID generates exactly the same lines after M0."""
        with Workspace() as ws, Workspace() as pre:
            os.unlink(pre.root / registry.REGISTRY)                                           # the state before M0
            for w in (ws, pre):
                cmd(w.root, "index")
            known, known_pre = diagrams.sources(ws.root), diagrams.sources(pre.root)
            cat = architecture.catalog(architecture.documents(ws.root))
            self.assertEqual(len(cat), 14)
            for c in cat:
                with self.subTest(c.diagram_id):
                    self.assertEqual(diagrams.render(known[c.diagram_id], "designs/features/a.md"),
                                     diagrams.render(known_pre[c.diagram_id], "designs/features/a.md"))
                    self.assertEqual(tuple(known[c.diagram_id].lines), tuple(c.source))     # exact Mermaid content

    def test_u9_standalone_sources_are_not_read_as_documents(self):
        with Workspace() as ws:
            folder = ws.root / "docs/architecture/diagrams"
            folder.mkdir()
            (folder / "system-architecture_sequence_x.md").write_text(
                "---\ndiagram_id: AD-0099\ntitle: X\nowner_document: docs/architecture/system-architecture.md\n---\n\n"
                "```mermaid\nsequenceDiagram\n  A->>B: hi\n```\n", encoding="utf-8")
            docs = architecture.documents(ws.root)
            self.assertFalse(any(d.path.startswith("docs/architecture/diagrams/") for d in docs))
            self.assertEqual(len(architecture.catalog(docs)), 14)                            # never counted twice
            self.assertIn("AD-0099 is not registered", "\n".join(check(ws)))                 # but still accounted for

    def test_u11_a_renamed_heading_needs_an_explicit_relink(self):
        with Workspace() as ws:
            doc = ws.root / "docs/architecture/etl-workflow.md"
            doc.write_bytes(doc.read_bytes().replace("### Streets → `road_segments`".encode(), b"### Streets loader"))
            found = "\n".join(check(ws))
            self.assertIn("AD-0006: no Mermaid diagram 1 under #streets--road_segments in docs/architecture/etl-workflow.md",
                          found)
            self.assertIn("(E7, U11)", found)
            with self.assertRaisesRegex(DesignError, "no Mermaid diagram 1 under #nowhere"):
                registry.relink(ws.root, "AD-0006", heading="nowhere")
            registry.relink(ws.root, "AD-0006", heading="streets-loader")
            cmd(ws.root, "index")
            self.assertEqual(check(ws), [])
            r, _ = designer_api.handle(ws.root, {"version": 1, "op": "resolve", "diagram_id": ETL})   # alias kept
            self.assertEqual(r["id"], "AD-0006")


class LegacyMarkers(unittest.TestCase):
    """Safeguard S1: a block made before fingerprints is never overwritten unless that is lossless."""

    def setUp(self):
        self.ctx = Workspace(); self.ws = self.ctx.__enter__()
        self.f = new_feature(self.ws.root, "A")
        insert(self.ws, self.f.path, ETL)
        cmd(self.ws.root, "index")
        self.path = self.ws.root / self.f.path
        self.generated = self.path.read_text(encoding="utf-8")
        self.legacy = re.sub(r" sha256:[0-9a-f]{16} -->", " -->", self.generated)       # as T-96 wrote it

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_an_exact_legacy_block_only_gains_its_fingerprint(self):
        self.path.write_text(self.legacy, encoding="utf-8")
        self.assertTrue(any("fingerprint is missing" in p for p in check(self.ws)))
        cmd(self.ws.root, "index")
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.generated)         # only the marker changed
        self.assertEqual(check(self.ws), [])

    def test_a_differing_legacy_block_is_preserved_and_needs_reconciliation(self):
        for name, text in (("hand edit", self.legacy.replace("S1 --> S2", "S1 --> S2 %% mine")),
                           ("caption edit", self.legacy.replace("generated copy;", "copy;"))):
            with self.subTest(name):
                self.path.write_text(text, encoding="utf-8")
                found = "\n".join(check(self.ws))
                self.assertIn("was generated before fingerprints", found)
                self.assertIn("cannot be established, so it is never overwritten automatically (E15)", found)
                code, _, err = cmd(self.ws.root, "index")
                self.assertEqual(self.path.read_text(encoding="utf-8"), text)           # preserved by index
                self.assertIn("(E15)", err)
                r, _ = designer_api.handle(self.ws.root, {"version": 1, "op": "refresh", "path": self.f.path,
                                                          "text": text})
                self.assertEqual(r["edits"], [])                                        # and by the Feature Designer
                line = marker_line(self.ws, self.f.path, ETL)
                plan = diagrams.plan_reconcile(self.ws.root, self.f.path, line, "discard")
                self.assertEqual(plan.state, "legacy")
                self.assertEqual(cmd(self.ws.root, "reconcile", "--file", self.f.path, "--line", str(line), "--discard",
                                     "--confirm", plan.token)[0], 0)
                self.assertEqual(self.path.read_text(encoding="utf-8"), self.generated)


class LockRecovery(unittest.TestCase):
    """Safeguard S2: a stale lock is removed only after verifying that no process holds it."""

    HOLD = ("import sys, time; sys.path.insert(0, {repo!r}); from pathlib import Path; "
            "from tools.design import registry\nwith registry.lock(Path({root!r})):\n    print('held', flush=True); "
            "time.sleep(30)")

    def holder(self, root):
        import subprocess, sys
        p = subprocess.Popen([sys.executable, "-c", self.HOLD.format(repo=str(REPO_ROOT), root=str(root))],
                             stdout=subprocess.PIPE, text=True)
        self.assertEqual(p.stdout.readline().strip(), "held")
        return p

    def test_an_active_lock_is_never_removed_and_a_dead_one_only_with_confirm(self):
        with Workspace() as ws:
            p = self.holder(ws.root)
            try:
                state = registry.unlock(ws.root, confirm=True)
                self.assertFalse(state.removable)
                self.assertIn("still holds the lock", state.reason)
                self.assertTrue((ws.root / registry.LOCK).exists())
                code, out, _ = cmd(ws.root, "registry", "unlock", "--confirm")
                self.assertEqual(code, 1)
                self.assertIn("the lock was kept", out)
            finally:
                p.kill(); p.wait(); p.stdout.close()
            code, out, _ = cmd(ws.root, "registry", "unlock")                                # preview only
            self.assertEqual(code, 1)
            self.assertIn("no process holds the lock", out)
            self.assertTrue((ws.root / registry.LOCK).exists())
            code, out, _ = cmd(ws.root, "registry", "unlock", "--confirm")
            self.assertEqual(code, 0, out)
            self.assertFalse((ws.root / registry.LOCK).exists())
            new_feature(ws.root, "A")
            ownership.new_diagram(ws.root, "FD-0001", "After recovery")                     # the registry works again

    def test_unverifiable_locks_are_kept(self):
        with Workspace() as ws:
            lock = ws.root / registry.LOCK
            lock.parent.mkdir(parents=True, exist_ok=True)
            for content, why in (("not json", "cannot be read"), ("{}", "does not record its process"),
                                 ('{"pid": 1, "host": "another-computer", "time": 0}', "another computer")):
                with self.subTest(why):
                    lock.write_text(content, encoding="utf-8")
                    state = registry.unlock(ws.root, confirm=True)
                    self.assertFalse(state.removable)
                    self.assertIn(why, state.reason)
                    self.assertTrue(lock.exists())


class ArchitectureOwnership(unittest.TestCase):
    """Safeguard S3: nothing the diagram commands do writes under docs/architecture/."""

    def test_no_operation_writes_under_docs_architecture(self):
        with Workspace() as ws:
            f = new_feature(ws.root, "A")
            folder = ws.root / "docs/architecture/diagrams"
            folder.mkdir()
            src = folder / "system-architecture_sequence_x.md"
            src.write_text("---\ndiagram_id: AD-0015\ntitle: X\nowner_document: docs/architecture/system-architecture.md\n"
                           "---\n\n```mermaid\nsequenceDiagram\n  A->>B: hi\n```\n", encoding="utf-8")
            registry.adopt(ws.root, "docs/architecture/diagrams/system-architecture_sequence_x.md", "sequence")
            before = {p: p.read_bytes() for p in (ws.root / "docs/architecture").rglob("*") if p.is_file()}
            with self.assertRaisesRegex(DesignError, "technical-lead's documentation workflow"):
                registry.relink(ws.root, "AD-0015", title="Renamed here")              # would edit its front matter
            insert(ws, f.path, "AD-0015")
            insert(ws, f.path, ETL, heading="## 1. Objective")
            cmd(ws.root, "index")
            registry.relink(ws.root, "AD-0006", title="Streets loader (registry title)")   # embedded: registry only
            text = (ws.root / f.path).read_text(encoding="utf-8")
            (ws.root / f.path).write_text(text.replace("A->>B: hi", "A->>B: edited"), encoding="utf-8")
            line = marker_line(ws, f.path, "AD-0015")
            with self.assertRaisesRegex(ValueError, "technical-lead's documentation workflow"):
                diagrams.plan_reconcile(ws.root, f.path, line, "apply-to-source")
            for target in ("docs/architecture/x.md", "docs/architecture/diagrams/y.md"):
                with self.subTest(target=target):
                    with self.assertRaisesRegex(DesignError, "under docs/architecture/"):
                        ownership.write_atomically(ws.root / target, "x", root=ws.root)
                    with self.assertRaisesRegex(DesignError, "under docs/architecture/"):
                        ownership.create_exclusively(ws.root / target, "x", target, root=ws.root)
            registry.retire(ws.root, "AD-0015", True)
            cmd(ws.root, "index")
            after = {p: p.read_bytes() for p in (ws.root / "docs/architecture").rglob("*") if p.is_file()}
            self.assertEqual(after, before)                                              # byte-identical throughout

    def test_a_document_owned_title_follows_the_file_changed_by_technical_lead(self):
        with Workspace() as ws:
            folder = ws.root / "docs/architecture/diagrams"
            folder.mkdir()
            src = folder / "system-architecture_sequence_x.md"
            src.write_text("---\ndiagram_id: AD-0015\ntitle: X\nowner_document: docs/architecture/system-architecture.md\n"
                           "---\n\n```mermaid\nsequenceDiagram\n  A->>B: hi\n```\n", encoding="utf-8")
            registry.adopt(ws.root, "docs/architecture/diagrams/system-architecture_sequence_x.md", "sequence")
            src.write_text(src.read_text(encoding="utf-8").replace("title: X", "title: Y"), encoding="utf-8")  # technical-lead
            before = src.read_bytes()
            e = registry.relink(ws.root, "AD-0015", title="Y")                        # the registry follows the file
            self.assertEqual(e.title, "Y")
            self.assertEqual(src.read_bytes(), before)


class RealRepository(unittest.TestCase):
    def test_the_committed_registry_and_indexes_are_consistent(self):
        reg = registry.load(REPO_ROOT)
        self.assertEqual(reg.problems, [])
        self.assertEqual([e.diagram_id for e in reg.entries if e.owner_kind == "document"],
                         [f"AD-{n:04d}" for n in range(1, 15)])
        self.assertTrue(registry.diagram_index_is_fresh(REPO_ROOT))


if __name__ == "__main__":
    unittest.main()
