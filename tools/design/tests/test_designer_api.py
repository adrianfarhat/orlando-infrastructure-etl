"""T-97 Phase 1: the Feature Designer interface (designer_api) — versioned, deterministic JSON
that proposes edits for unsaved text and never writes a file."""

import hashlib
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
            self.assertEqual([d["id"] for d in flat], [c.diagram_id for c in cat])          # no second catalog
            self.assertEqual(len(flat), 14)
            self.assertEqual([g["document"] for g in r["architecture"]], sorted({c.document for c in cat}))
            for d in flat:                                                              # Edit source lands on the fence
                with self.subTest(id=d["id"]):
                    line = (ws.root / d["path"]).read_text(encoding="utf-8").split("\n")[d["line"] - 1]
                    self.assertTrue(line.lstrip().startswith("```mermaid"), line)
                    self.assertEqual((d["kind"], d["owner"]), ("current", None))
            cred = next(d for d in flat if d["id"] == "system-architecture/credential-boundary")
            self.assertEqual(cred["title"], "Credential boundary")
            feats = {g["feature_id"]: [(d["id"], d["title"]) for d in g["diagrams"]] for g in r["features"]}
            self.assertEqual(feats, {"FD-0001": [("FD-0001-D1", "Only of A")],
                                     "FD-0002": [("FD-0002-D1", "Second of B"), ("FD-0002-D2", "First of B")]})
            self.assertEqual([(d["id"], "not an existing feature" in d["problem"]) for d in r["unowned"]],
                             [("FD-0007-D1", True)])
            for g in r["features"]:
                for d in g["diagrams"]:
                    line = (ws.root / d["path"]).read_text(encoding="utf-8").split("\n")[d["line"] - 1]
                    self.assertEqual(line, "```mermaid")
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
        self.assertEqual(inserted[1], f"<!-- diagram:start {ETL} -->")
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
        inside = first.split("\n").index(f"<!-- diagram:start {ETL} -->") + 2
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
        self.assertIn("**🔷 Proposed: [Owned by B](diagrams/owned-by-b.md)** · `FD-0002-D1`", "\n".join(r["edits"][0]["lines"]))
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
            stale = fresh.replace("flowchart", "flowchart  ", 1)                               # a hand edit in the copy
            r, code = request(ws, op="refresh", path=f.path, text=stale)
            self.assertEqual((code, r["blocking"]), (0, []))
            self.assertEqual(len(r["edits"]), 1)
            self.assertEqual(apply(stale, r), fresh)
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

    def test_no_workspace_still_answers_in_json(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:                                         # no .git, no template
            code, out, _ = cmd(Path(tmp), "designer")
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["error"]["code"], "workspace")


if __name__ == "__main__":
    unittest.main()
