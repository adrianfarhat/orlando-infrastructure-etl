"""T-97 Phase 1: the Feature Designer interface (designer_api) — versioned, deterministic JSON
that proposes edits for unsaved text and never writes a file."""

import hashlib
import re
import io
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from tools.design import architecture, designer_api, ownership, workspace
from tools.design.workspace import new_feature
from tools.design.tests.test_design import Workspace, cmd

ETL = "etl-workflow/streets--road_segments"


def apply(text, response):
    """Apply a response's edits the way the editor will: lines split on '\\n', the document's newline."""
    lines = [l[:-1] if l.endswith("\r") else l for l in text.split("\n")]
    for e in reversed(response["edits"]):
        lines[e["start"]:e["end"]] = e["lines"]
    return response["newline"].join(lines)


def request(ws, **req):
    response, code = designer_api.handle(ws.root, {"version": 1, **req})
    return response, code


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(Path(root).rglob("*"))
            if p.is_file() and ".git" not in p.parts}


def after(lines, prefix):
    """Index of the blank line after the first line starting with `prefix` (a block boundary)."""
    i = next(n for n, l in enumerate(lines) if l.startswith(prefix))
    while lines[i].strip():
        i += 1
    return i


class Library(unittest.TestCase):
    def test_hierarchy_equals_the_catalog_and_the_diagram_files(self):
        with Workspace() as ws:
            new_feature(ws.root, "A"); new_feature(ws.root, "B")
            ownership.new_diagram(ws.root, "FD-0002", "Second of B")
            ownership.new_diagram(ws.root, "FD-0001", "Only of A")
            ownership.new_diagram(ws.root, "FD-0002", "First of B")    # D2, listed after D1
            orphan = ws.root / "designs/features/diagrams/orphan.md"
            orphan.write_text("---\ndiagram_id: \"FD-0007-D1\"\nfeature_id: \"FD-0007\"\ntitle: \"Orphan\"\n---\n\n"
                              "```mermaid\nflowchart LR\n  A --> B\n```\n", encoding="utf-8")
            r, code = request(ws, op="library")
            self.assertEqual((code, r["ok"], r["version"]), (0, True, 1))
            cat = architecture.catalog(architecture.documents(ws.root))
            flat = [d for g in r["architecture"] for d in g["diagrams"]]
            self.assertEqual([d["aliases"] for d in flat], [[c.diagram_id] for c in cat])   # one entry per diagram
            self.assertEqual([d["id"] for d in flat], [f"AD-{n:04d}" for n in range(1, 15)])  # stable IDs (M0)
            self.assertEqual({d["format"] for d in flat}, {"mermaid-embedded"})
            self.assertEqual(len(flat), 14)
            self.assertEqual([g["document"] for g in r["architecture"]], sorted({c.document for c in cat}))
            for d in flat:                                                              # Edit source lands on the fence
                with self.subTest(id=d["id"]):
                    line = (ws.root / d["path"]).read_text(encoding="utf-8").split("\n")[d["line"] - 1]
                    self.assertTrue(line.lstrip().startswith("```mermaid"), line)
                    self.assertEqual((d["kind"], d["owner"]), ("current", None))
            cred = next(d for d in flat if "system-architecture/credential-boundary" in d["aliases"])
            self.assertEqual(cred["id"], "AD-0011")
            self.assertEqual(cred["title"], "Credential boundary")
            feats = {g["feature_id"]: [(d["id"], d["title"]) for d in g["diagrams"]] for g in r["features"]}
            self.assertEqual(feats, {"FD-0001": [("FD-0001-D1", "Only of A")],
                                     "FD-0002": [("FD-0002-D1", "Second of B"), ("FD-0002-D2", "First of B")]})
            self.assertEqual([(d["id"], d["status"], "(E5)" in d["problem"]) for d in r["unowned"]],
                             [("FD-0007-D1", "unregistered", True)])
            for g in r["features"]:
                for d in g["diagrams"]:
                    line = (ws.root / d["path"]).read_text(encoding="utf-8").split("\n")[d["line"] - 1]
                    self.assertEqual(line, "```mermaid")
                    self.assertEqual((d["format"], d["category"], d["status"]), ("mermaid-md", "other", "active"))
            self.assertEqual(designer_api.dumps(r), designer_api.dumps(request(ws, op="library")[0]))  # deterministic


class Insert(unittest.TestCase):
    def setUp(self):
        self.ctx = Workspace(); self.ws = self.ctx.__enter__()
        self.f = new_feature(self.ws.root, "A")
        self.path = self.ws.root / self.f.path
        self.text = self.path.read_text(encoding="utf-8")
        self.lines = self.text.split("\n")

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_edits_give_exactly_what_index_would_write(self):
        at = after(self.lines, "- **Desired outcome:**")
        r, code = request(self.ws, op="insert", path=self.f.path, text=self.text, at=at, diagram_id=ETL)
        self.assertEqual(code, 0, r)
        self.assertEqual(r["base"], {"sha256": hashlib.sha256(self.text.encode()).hexdigest(),
                                     "line_count": len(self.lines)})
        self.assertEqual(r["edits"][0]["start"], at)
        inserted = r["edits"][0]["lines"]
        self.assertEqual(inserted[0], "")                                    # separates it from the list above
        self.assertRegex(inserted[1], rf"^<!-- diagram:start {re.escape(ETL)} sha256:[0-9a-f]{{16}} -->$")
        self.assertEqual(inserted[-1], "<!-- diagram:end -->")              # the following line is already blank
        new = apply(self.text, r)
        self.assertEqual(new.split("\n")[:at], self.lines[:at])                                 # unrelated text kept
        self.assertEqual(new.split("\n")[at + len(r["edits"][0]["lines"]):], self.lines[at:])
        self.path.write_text(new, encoding="utf-8")
        before = self.path.read_bytes()
        cmd(self.ws.root, "index")                                                              # index changes nothing
        self.assertEqual(self.path.read_bytes(), before)
        code, out, _ = cmd(self.ws.root, "check")
        self.assertEqual(code, 0, out)

    def test_unsaved_text_and_crlf(self):
        unsaved = self.text.replace("- **Problem:**", "Unsaved paragraph.\n\n- **Problem:**").replace("\n", "\r\n")
        lines = unsaved.split("\r\n")
        at = after(lines, "- **Desired outcome:**")
        r, code = request(self.ws, op="insert", path=self.f.path, text=unsaved, at=at, diagram_id=ETL)
        self.assertEqual((code, r["newline"]), (0, "\r\n"))
        self.assertTrue(all("\r" not in l for l in r["edits"][0]["lines"]))
        new = apply(unsaved, r)
        self.assertIn("Unsaved paragraph.", new)
        self.assertNotIn("\n", new.replace("\r\n", ""))                                          # still CRLF throughout
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.text)                     # disk untouched

    def test_unsafe_positions_are_refused(self):
        L = self.lines
        fenced = self.text.replace("## 2. Data contract", "```text\ncode\n\nmore\n```\n\n## 2. Data contract")
        details = self.text.index("<details open>")
        cases = {
            "before section 1": (self.text, L.index("## 1. Objective"), "only inside the six sections"),
            "after section 6": (self.text, len(L) - 1, "only inside the six sections"),
            "inside a paragraph or list": (self.text, L.index(next(l for l in L if l.startswith("- **Users:**"))),
                                           "not at a block boundary"),
            "inside a table": (self.text, L.index("|---|---|---|---|---|") + 1, "not inside a table"),
            "inside a details group": (self.text, self.text[:details].count("\n") + 2, "not inside a <details> group"),
            "inside a code block": (fenced, fenced.split("\n").index("more") - 1, "not inside a code block"),
            "inside the Related block": (self.text, L.index("| Feature | Relationship | Reference | Evidence status |"),
                                         "generated summary or Related features block"),
            "out of range": (self.text, len(L) + 5, "line index between 0 and"),
        }
        for name, (text, at, message) in cases.items():
            with self.subTest(name):
                r, code = request(self.ws, op="insert", path=self.f.path, text=text, at=at, diagram_id=ETL)
                self.assertEqual((code, r["ok"], r["error"]["code"]), (1, False, "refused"), r)
                self.assertIn(message, r["error"]["message"])

    def test_inside_an_existing_diagram_block_is_refused(self):
        at = after(self.lines, "- **Desired outcome:**")
        first = apply(self.text, request(self.ws, op="insert", path=self.f.path, text=self.text, at=at, diagram_id=ETL)[0])
        inside = next(i for i, l in enumerate(first.split("\n")) if l.startswith(f"<!-- diagram:start {ETL} ")) + 2
        r, code = request(self.ws, op="insert", path=self.f.path, text=first, at=inside, diagram_id=ETL)
        self.assertEqual(code, 1)
        self.assertIn("not inside a generated diagram block", r["error"]["message"])

    def test_unknown_or_unusable_diagrams_are_refused(self):
        at = after(self.lines, "- **Desired outcome:**")
        r, code = request(self.ws, op="insert", path=self.f.path, text=self.text, at=at, diagram_id="nope/nothing")
        self.assertEqual(code, 1)
        self.assertIn("unknown diagram ID 'nope/nothing'", r["error"]["message"])

    def test_a_cross_feature_diagram_keeps_its_owner(self):
        b = new_feature(self.ws.root, "B")
        d = ownership.new_diagram(self.ws.root, "FD-0002", "Owned by B")
        at = after(self.lines, "- **Desired outcome:**")
        r, code = request(self.ws, op="insert", path=self.f.path, text=self.text, at=at, diagram_id=d.diagram_id)
        self.assertEqual(code, 0, r)
        self.assertIn("**🔷 Proposed: [Owned by B](diagrams/b_other_owned-by-b.md)** · `FD-0002-D1`",
                      "\n".join(r["edits"][0]["lines"]))
        lib = request(self.ws, op="library")[0]
        owners = {d["id"]: g["feature_id"] for g in lib["features"] for d in g["diagrams"]}
        self.assertEqual(owners, {"FD-0002-D1": "FD-0002"})                                   # listed only under its owner


class Refresh(unittest.TestCase):
    def test_stale_blocks_in_unsaved_text_are_brought_up_to_date(self):
        with Workspace() as ws:
            f = new_feature(ws.root, "A")
            text = (ws.root / f.path).read_text(encoding="utf-8")
            at = after(text.split("\n"), "- **Desired outcome:**")
            fresh = apply(text, request(ws, op="insert", path=f.path, text=text, at=at, diagram_id=ETL)[0])
            hand = fresh.replace("flowchart", "flowchart  ", 1)                                 # a hand edit in the copy
            r, code = request(ws, op="refresh", path=f.path, text=hand)
            self.assertEqual((code, r["blocking"], r["edits"]), (0, [], []))                     # U13: never overwritten
            self.assertTrue(r["conflicts"] and "(E15)" in r["conflicts"][0], r)
            old = re.sub(r" sha256:[0-9a-f]{16} -->", " -->", fresh)
            r, code = request(ws, op="refresh", path=f.path, text=old.replace("flowchart", "flowchart  ", 1))
            self.assertEqual((code, r["edits"]), (0, []))                                     # old marker, differs: kept
            self.assertIn("generated before fingerprints", r["conflicts"][0])
            r, code = request(ws, op="refresh", path=f.path, text=old)                       # old marker, exact
            self.assertEqual((code, r["blocking"], len(r["edits"])), (0, [], 1))
            self.assertEqual(apply(old, r), fresh)                                             # marker gains its fingerprint
            self.assertEqual(request(ws, op="refresh", path=f.path, text=fresh)[0]["edits"], [])   # nothing to do

    def test_a_file_index_would_refuse_gets_no_edits(self):
        with Workspace() as ws:
            f = new_feature(ws.root, "A")
            text = (ws.root / f.path).read_text(encoding="utf-8").replace(
                "## 3. Logic\n", f"## 3. Logic\n\n<!-- diagram:start {ETL} -->\n")          # no end marker
            r, code = request(ws, op="refresh", path=f.path, text=text)
            self.assertEqual(code, 0)
            self.assertEqual(r["edits"], [])
            self.assertTrue(any("no matching" in b or "end" in b for b in r["blocking"]), r["blocking"])


class Placement(unittest.TestCase):
    """PR B1: block states for source-based rendering, the Make New name preview, Remove reference."""

    def setUp(self):
        from tools.design import registry
        self.registry = registry
        self.ctx = Workspace(); self.ws = self.ctx.__enter__()
        self.f = new_feature(self.ws.root, "A")
        self.made = ownership.new_diagram(self.ws.root, "FD-0001", "Pipe flow", "process")
        self.plain = (self.ws.root / self.f.path).read_text(encoding="utf-8")
        text = self.plain
        for prefix, ident in (("- **Desired outcome:**", ETL), ("## 3. Logic", self.made.diagram_id)):
            at = after(text.split("\n"), prefix)
            text = apply(text, request(self.ws, op="insert", path=self.f.path, text=text, at=at, diagram_id=ident)[0])
        self.text = text

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def states(self, text=None):
        r, code = request(self.ws, op="blocks", path=self.f.path, text=self.text if text is None else text)
        self.assertEqual(code, 0, r)
        return r, {b["id"]: b for b in r["blocks"]}

    def test_current_blocks_resolve_to_their_sources_and_nothing_is_written(self):
        before = snapshot(self.ws.root)
        r, by = self.states()
        self.assertEqual((r["stale"], r["conflicts"], r["blocking"]), (0, [], []))
        arch, own = by[ETL], by[self.made.diagram_id]
        self.assertEqual((arch["state"], own["state"]), ("current", "current"))
        self.assertEqual(arch["generated"], arch["embedded"])
        self.assertEqual((arch["source"]["id"], arch["source"]["editor"]), ("AD-0006", "architecture-docs"))
        self.assertEqual((own["source"]["path"], own["source"]["editor"]), (self.made.path, "text"))
        self.assertEqual(own["source"]["owner"], {"kind": "feature", "ref": "FD-0001"})
        self.assertEqual(snapshot(self.ws.root), before)                                   # read only

    def test_a_changed_source_is_outdated_and_rendered_from_the_source(self):
        src = self.ws.root / self.made.path
        src.write_text(src.read_text(encoding="utf-8").replace("```\n", "  Z[Added in the source]\n```\n", 1), encoding="utf-8")
        r, by = self.states()
        b = by[self.made.diagram_id]
        self.assertEqual((b["state"], r["stale"]), ("outdated", 1))
        self.assertTrue(any("Added in the source" in l for l in b["generated"]))
        self.assertFalse(any("Added in the source" in l for l in b["embedded"]))                   # the copy is shown as it is
        self.assertTrue(any(l.startswith("+") and "Added in the source" in l for l in b["diff"]))

    def test_conflicts_keep_both_versions_and_say_which_case(self):
        hand = self.text.replace("S1 --> S2", "S1 --> S2 %% mine")
        r, by = self.states(hand)
        b = by[ETL]
        self.assertEqual((b["state"], b["conflict"]), ("conflict", "case2"))
        self.assertIn("(E15)", b["message"])
        self.assertNotEqual(b["embedded"], b["generated"])
        self.assertTrue(any("%% mine" in l and l.startswith("-") for l in b["diff"]))
        legacy = re.sub(r" sha256:[0-9a-f]{16} -->", " -->", hand)
        self.assertEqual(self.states(legacy)[1][ETL]["conflict"], "legacy")

    def test_retired_missing_and_unknown_blocks(self):
        self.registry.retire(self.ws.root, self.made.diagram_id, True)
        b = self.states()[1][self.made.diagram_id]
        self.assertEqual((b["state"], b["generated"]), ("retired", []))
        self.assertIn("(E11)", b["message"])
        unknown = self.text.replace(f"diagram:start {ETL} ", "diagram:start FD-0001-D9 ")
        self.assertEqual(self.states(unknown)[1]["FD-0001-D9"]["state"], "unknown")
        self.assertIsNone(self.states(unknown)[1]["FD-0001-D9"]["source"])

    def test_a_missing_source_is_reported(self):
        (self.ws.root / self.made.path).unlink()
        b = self.states()[1][self.made.diagram_id]
        self.assertEqual(b["state"], "missing")
        self.assertIn("(E7)", b["message"])

    def test_diagram_name_previews_the_path_without_creating_anything(self):
        before = snapshot(self.ws.root)
        r, code = request(self.ws, op="diagram-name", owner="FD-0001", title="Pipe  flow 2", category="data-model")
        self.assertEqual((code, r["problem"]), (0, ""))
        self.assertEqual(r["path"], "designs/features/diagrams/a_data-model_pipe-flow-2.md")
        self.assertEqual(snapshot(self.ws.root), before)
        taken = request(self.ws, op="diagram-name", owner="FD-0001", title="Pipe flow", category="process")[0]
        self.assertIn("already exists", taken["problem"])
        for owner, title, category, why in (("FD-0099", "X", "process", "no feature has the ID FD-0099"),
                                            ("FD-1", "X", "process", "feature ID"), ("FD-0001", " ", "process", "empty"),
                                            ("FD-0001", "X", "drawing", "category"),
                                            ("FD-0001", "a\u202eb", "process", "invisible")):
            with self.subTest(why):
                r, code = request(self.ws, op="diagram-name", owner=owner, title=title, category=category)
                self.assertEqual((code, r["path"]), (0, ""))
                self.assertIn(why, r["problem"])

    def test_remove_reference_only_for_a_retired_diagram(self):
        start = next(b["start"] for b in self.states()[0]["blocks"] if b["id"] == self.made.diagram_id)
        r, code = request(self.ws, op="remove-block", path=self.f.path, text=self.text, line=start)
        self.assertEqual(code, 1)
        self.assertIn("is not retired", r["error"]["message"])
        self.registry.retire(self.ws.root, self.made.diagram_id, True)
        r, code = request(self.ws, op="remove-block", path=self.f.path, text=self.text, line=start)
        self.assertEqual(code, 0, r)
        removed = apply(self.text, r)
        self.assertNotIn(self.made.diagram_id, removed)
        self.assertIn(f"diagram:start {ETL} ", removed)
        without_etl = removed
        self.assertEqual(without_etl.count("\n\n\n"), self.text.count("\n\n\n"))         # no blank line left behind
        self.assertEqual(request(self.ws, op="remove-block", path=self.f.path, text=self.text, line=start + 1)[1], 1)
        self.assertEqual(request(self.ws, op="remove-block", path=self.f.path, text=self.text, line=True)[1], 2)

    def test_new_diagram_json_output(self):
        code, out, _ = cmd(self.ws.root, "new", "diagram", "--feature=FD-0001", "--title=--root elsewhere",
                           "--category=state", "--json")
        self.assertEqual(code, 0)
        made = json.loads(out)
        self.assertEqual(made["diagram_id"], "FD-0001-D2")
        self.assertEqual(made["path"], "designs/features/diagrams/a_state_root-elsewhere.md")
        self.assertTrue((self.ws.root / made["path"]).is_file())
        self.assertIn("FD-0001-D2", self.registry.load(self.ws.root).lookup())


class Reconcile(unittest.TestCase):
    """PR B2a: reconciliation planned on unsaved text; the editor applies it (nothing written here)."""

    def setUp(self):
        self.ctx = Workspace(); self.ws = self.ctx.__enter__()
        self.f = new_feature(self.ws.root, "A")
        self.made = ownership.new_diagram(self.ws.root, "FD-0001", "Pipe flow", "process")
        text = (self.ws.root / self.f.path).read_text(encoding="utf-8")
        for prefix, ident in (("- **Desired outcome:**", ETL), ("## 3. Logic", self.made.diagram_id)):
            at = after(text.split("\n"), prefix)
            text = apply(text, request(self.ws, op="insert", path=self.f.path, text=text, at=at, diagram_id=ident)[0])
        self.fresh = text
        self.hand = text.replace('B["New step (planned)"]', 'B["Edited by hand"]')
        self.src = self.ws.root / self.made.path

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def start(self, text, ident):
        r, _ = request(self.ws, op="blocks", path=self.f.path, text=text)
        return next(b["start"] for b in r["blocks"] if b["id"] == ident)

    def plan(self, text, ident, action):
        return request(self.ws, op="reconcile", path=self.f.path, text=text, line=self.start(text, ident), action=action)

    def test_discard_restores_the_generated_copy_in_unsaved_text_and_writes_nothing(self):
        before = snapshot(self.ws.root)
        r, code = self.plan(self.hand, self.made.diagram_id, "discard")
        self.assertEqual((code, r["state"], r["source"]), (0, "case2", None))
        self.assertEqual(apply(self.hand, r), self.fresh)
        self.assertIn("Edited by hand", r["diff"])
        self.assertEqual(snapshot(self.ws.root), before)

    def test_apply_to_source_returns_the_new_source_and_the_revision_it_was_computed_from(self):
        r, code = self.plan(self.hand, self.made.diagram_id, "apply-to-source")
        self.assertEqual((code, r["replaces_source_changes"], r["warning"]), (0, False, ""))
        src = self.src.read_bytes()
        self.assertEqual(r["source"]["path"], self.made.path)
        self.assertEqual(r["source"]["sha256"], hashlib.sha256(src).hexdigest())
        self.assertIn('B["Edited by hand"]', r["source"]["text"])
        self.assertNotIn('B["Edited by hand"]', src.decode("utf-8"))                  # nothing written
        after_text = apply(self.hand, r)
        self.assertIn('B["Edited by hand"]', after_text)
        self.src.write_text(r["source"]["text"], encoding="utf-8")                   # as the editor would save it
        self.assertEqual(self.states(after_text)[self.made.diagram_id], "current")

    def states(self, text):
        r, _ = request(self.ws, op="blocks", path=self.f.path, text=text)
        return {b["id"]: b["state"] for b in r["blocks"]}

    def test_replacing_changes_made_in_the_source_is_flagged(self):
        self.src.write_text(self.src.read_text(encoding="utf-8").replace('A["Existing step"]', 'A["Changed in source"]'),
                            encoding="utf-8")
        r, _ = self.plan(self.hand, self.made.diagram_id, "apply-to-source")
        self.assertEqual((r["state"], r["replaces_source_changes"]), ("case3", True))
        self.assertIn("replaces those source changes", r["warning"])
        legacy = re.sub(r" sha256:[0-9a-f]{16} -->", " -->", self.hand)
        r, _ = self.plan(legacy, self.made.diagram_id, "apply-to-source")
        self.assertEqual((r["state"], r["replaces_source_changes"]), ("legacy", True))
        self.assertIn("cannot be established", r["warning"])
        self.assertFalse(self.plan(legacy, self.made.diagram_id, "discard")[0]["replaces_source_changes"])

    def test_the_token_changes_with_the_text_and_with_the_source(self):
        t1 = self.plan(self.hand, self.made.diagram_id, "discard")[0]["token"]
        t2 = self.plan(self.hand + "\nmore", self.made.diagram_id, "discard")[0]["token"]
        self.src.write_text(self.src.read_text(encoding="utf-8") + "\n", encoding="utf-8")  # outside the diagram
        self.assertEqual(self.plan(self.hand, self.made.diagram_id, "discard")[0]["token"], t1)
        self.src.write_text(self.src.read_text(encoding="utf-8").replace('A["Existing step"]', 'A["Changed"]'),
                            encoding="utf-8")                                          # what Discard would write
        t3 = self.plan(self.hand, self.made.diagram_id, "discard")[0]["token"]
        self.assertEqual(len({t1, t2, t3}), 3)

    def test_refusals(self):
        hand_arch = self.fresh.replace("S1 --> S2", "S1 --> S2 %% mine")
        r, code = self.plan(hand_arch, ETL, "apply-to-source")
        self.assertEqual(code, 1)
        self.assertIn("technical-lead's documentation workflow", r["error"]["message"])
        self.assertEqual(self.plan(hand_arch, ETL, "discard")[1], 0)                    # discard is fine for any
        self.assertEqual(request(self.ws, op="reconcile", path=self.f.path, text=self.hand, line=0, action="discard")[1], 1)
        self.assertEqual(request(self.ws, op="reconcile", path=self.f.path, text=self.hand, line=True, action="discard")[1], 2)
        self.assertEqual(self.plan(self.hand, self.made.diagram_id, "both")[1], 2)
        self.src.write_text(self.src.read_text(encoding="utf-8").replace('A["Existing step"]', 'A["Changed"]'),
                            encoding="utf-8")                                          # QA M2: an out-of-date block
        for action in ("apply-to-source", "discard"):                                 # is not a conflict: refused
            r, code = self.plan(self.fresh, self.made.diagram_id, action)
            self.assertEqual(code, 1, action)
            self.assertIn("not in conflict", r["error"]["message"])


class FeatureIndex(unittest.TestCase):
    def test_unsaved_texts_give_what_index_writes_after_saving(self):
        with Workspace() as ws:
            f = new_feature(ws.root, "A")
            path = ws.root / f.path
            text = path.read_text(encoding="utf-8")
            at = after(text.split("\n"), "- **Desired outcome:**")
            unsaved = apply(text, request(ws, op="insert", path=f.path, text=text, at=at, diagram_id=ETL)[0])
            before = snapshot(ws.root)
            r, code = request(ws, op="feature-index", texts={f.path: unsaved})
            self.assertEqual((code, r["changed"], r["path"]), (0, True, "designs/index/feature-index.md"))
            self.assertIn(f"`{ETL}`", r["content"])
            self.assertEqual(snapshot(ws.root), before)                                         # nothing written
            path.write_text(unsaved, encoding="utf-8")
            cmd(ws.root, "index")
            self.assertEqual((ws.root / workspace.INDEX).read_text(encoding="utf-8"), r["content"])
            self.assertFalse(request(ws, op="feature-index")[0]["changed"])


class Requests(unittest.TestCase):
    def test_malformed_requests(self):
        with Workspace() as ws:
            f = new_feature(ws.root, "A")
            cases = [({"op": "library"}, "unsupported request version None"),
                     ({"version": 2, "op": "library"}, "unsupported request version 2"),
                     ({"version": 1, "op": "write"}, "unknown op 'write'"),
                     ({"version": 1, "op": "refresh", "path": "../outside.md", "text": ""}, "must be a feature file"),
                     ({"version": 1, "op": "refresh", "path": "designs/templates/feature-spec.md", "text": ""},
                      "must be a feature file"),
                     ({"version": 1, "op": "refresh", "path": "designs/features/missing.md", "text": ""},
                      "is not a feature specification"),
                     ({"version": 1, "op": "refresh", "path": f.path, "text": 3}, "must be the document text"),
                     ({"version": 1, "op": "insert", "path": f.path, "text": "", "at": True, "diagram_id": ETL},
                      "`at` must be a line index"),
                     ([], "must be a JSON object")]
            for req, message in cases:
                with self.subTest(req=req):
                    r, code = designer_api.handle(ws.root, req)
                    self.assertEqual((code, r["ok"], r["error"]["code"]), (2, False, "bad-request"))
                    self.assertIn(message, r["error"]["message"])

    def test_the_command_line_never_writes_and_answers_in_json(self):
        with Workspace() as ws:
            f = new_feature(ws.root, "A")
            text = (ws.root / f.path).read_text(encoding="utf-8")
            before = snapshot(ws.root)
            for stdin, expected in ((json.dumps({"version": 1, "op": "library"}), 0),
                                    (json.dumps({"version": 1, "op": "insert", "path": f.path, "text": text, "at": 0,
                                                 "diagram_id": ETL}), 1),
                                    ("{not json", 2)):
                with self.subTest(stdin=stdin[:30]), mock.patch("sys.stdin", io.StringIO(stdin)):
                    code, out, _ = cmd(ws.root, "designer")
                    self.assertEqual(code, expected)
                    response = json.loads(out)
                    self.assertEqual(response["version"], 1)
                    self.assertEqual(out, designer_api.dumps(response) + "\n")                 # canonical bytes
            self.assertEqual(snapshot(ws.root), before)

    def test_serve_answers_one_line_per_request_until_end_of_input(self):
        """T-97 Phase 2: the extension keeps one process; responses echo request_id."""
        with Workspace() as ws:
            f = new_feature(ws.root, "A")
            text = (ws.root / f.path).read_text(encoding="utf-8")
            at = after(text.split("\n"), "- **Desired outcome:**")
            lines = [json.dumps({"version": 1, "op": "library", "request_id": 1}), "",
                     "{broken", json.dumps({"version": 1, "op": "insert", "path": f.path, "text": text, "at": at,
                                            "diagram_id": ETL, "request_id": "two"}),
                     json.dumps({"version": 1, "op": "insert", "path": f.path, "text": text, "at": 0,
                                 "diagram_id": ETL, "request_id": 3})]
            before = snapshot(ws.root)
            with mock.patch("sys.stdin", io.StringIO("\n".join(lines) + "\n")):
                code, out, err = cmd(ws.root, "designer", "--serve")
            self.assertEqual((code, err), (0, ""))
            responses = [json.loads(l) for l in out.splitlines()]
            self.assertEqual([(r.get("request_id"), r["ok"]) for r in responses],
                             [(1, True), (None, False), ("two", True), (3, False)])
            self.assertEqual(responses[1]["error"]["code"], "bad-request")
            self.assertEqual(responses[2]["edits"], request(ws, op="insert", path=f.path, text=text, at=at,
                                                            diagram_id=ETL)[0]["edits"])
            self.assertEqual(snapshot(ws.root), before)                                   # serve writes nothing

    def test_unexpected_input_still_answers_in_json(self):
        """QA D2: a lone surrogate from an editor buffer, or absurdly deep JSON, never gives a traceback."""
        with Workspace() as ws:
            f = new_feature(ws.root, "A")
            for stdin in ('{"version":1,"op":"refresh","path":"%s","text":"\\ud800"}' % f.path,
                          "[" * 100000):
                with self.subTest(stdin=stdin[:40]), mock.patch("sys.stdin", io.StringIO(stdin)):
                    code, out, err = cmd(ws.root, "designer")
                    self.assertEqual(code, 2)
                    self.assertEqual(err, "")
                    response = json.loads(out)
                    self.assertFalse(response["ok"])
                    self.assertIn(response["error"]["code"], ("internal", "bad-request"))
            r, code = designer_api.handle(ws.root, {"version": 1, "op": "refresh", "path": f.path, "text": "\ud800"})
            self.assertEqual((code, r["error"]["code"]), (2, "bad-request"))
            self.assertIn("lone surrogate", r["error"]["message"])
            with mock.patch.object(designer_api, "library", side_effect=OSError("disk gone")):
                r, code = designer_api.handle(ws.root, {"version": 1, "op": "library"})
            self.assertEqual((code, r["error"]["code"]), (2, "internal"))           # any other error: still JSON

    def test_no_workspace_still_answers_in_json(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:                                         # no .git, no template
            code, out, _ = cmd(Path(tmp), "designer")
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["error"]["code"], "workspace")


if __name__ == "__main__":
    unittest.main()
