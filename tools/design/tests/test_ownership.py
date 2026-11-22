"""T-97 Phase 1: feature-owned diagrams — owner, title and ID rules, and `new diagram`."""

import unittest

from tools.design import ownership, workspace
from tools.design.workspace import DesignError, new_feature
from tools.design.tests.test_design import Workspace, cmd


def problems(ws):
    code, out, _ = cmd(ws.root, "check")
    return [l for l in out.splitlines() if "problem(s)" not in l]


def diagram_file(ws, rel, **meta):
    lines = ["---", *(f"{k}: {v}" for k, v in meta.items()), "---", "", "# D", "", "```mermaid", "flowchart LR", "  A --> B",
             "```", ""]
    path = ws.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


class NewDiagram(unittest.TestCase):
    def test_creates_an_owned_diagram_next_to_a_standalone_feature(self):
        with Workspace() as ws:
            new_feature(ws.root, "Road pipe intersections")
            code, out, _ = cmd(ws.root, "new", "diagram", "--feature", "fd-0001", "--title", "Road/Pipe Intersection Logic")
            self.assertEqual(code, 0, out)
            rel = "designs/features/diagrams/road-pipe-intersection-logic.md"
            self.assertIn(f"created {rel} (FD-0001-D1, owned by FD-0001)", out)
            meta = ws.meta(rel)
            self.assertEqual((meta["diagram_id"], meta["feature_id"], meta["title"]),
                             ("FD-0001-D1", "FD-0001", "Road/Pipe Intersection Logic"))
            text = ws.text(rel)
            self.assertIn("# Proposed Diagram — Road/Pipe Intersection Logic", text)
            self.assertIn("| **Feature** | [FD-0001](../road-pipe-intersections.md) |", text)
            self.assertIn("| **Diagram ID** | `FD-0001-D1` |", text)
            self.assertEqual(problems(ws), [])

    def test_a_folder_feature_keeps_its_diagrams_in_its_own_folder(self):
        with Workspace() as ws:
            parent = new_feature(ws.root, "Parent")
            new_feature(ws.root, "Child", parent=parent.feature_id, convert_parent=True)
            created = ownership.new_diagram(ws.root, "FD-0001", "Overview")
            self.assertEqual(created.path, "designs/features/parent/diagrams/overview.md")
            self.assertIn("[FD-0001](../README.md)", ws.text(created.path))
            self.assertEqual(problems(ws), [])

    def test_refusals_create_nothing(self):
        with Workspace() as ws:
            new_feature(ws.root, "A")
            ownership.new_diagram(ws.root, "FD-0001", "Same")
            for owner, title, message in (("FD-0009", "X", "no feature has the ID FD-0009"),
                                          ("A", "X", "must be a feature ID"),
                                          ("FD-0001", "  ", "title is empty"),
                                          ("FD-0001", "Same", "already exists; nothing was overwritten")):
                with self.subTest(owner=owner, title=title), self.assertRaisesRegex(DesignError, message):
                    ownership.new_diagram(ws.root, owner, title)
            self.assertEqual(sorted(p.name for p in (ws.root / "designs/features/diagrams").iterdir()), ["same.md"])
            code, _, err = cmd(ws.root, "new", "diagram", "--feature", "FD-0001", interactive=False)
            self.assertEqual(code, 2)
            self.assertIn("--title is required", err)


class OwnershipRules(unittest.TestCase):
    def setUp(self):
        self.ctx = Workspace(); self.ws = self.ctx.__enter__()
        new_feature(self.ws.root, "A"); new_feature(self.ws.root, "B")

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def expect(self, message, **meta):
        path = diagram_file(self.ws, "designs/features/diagrams/x.md", **meta)
        found = "\n".join(problems(self.ws))
        self.assertIn(message, found)
        before = path.read_bytes()
        cmd(self.ws.root, "index")
        self.assertEqual(path.read_bytes(), before)                     # check and index never rewrite it

    def test_owner_is_required(self):
        self.expect("feature_id is required: the ID of the feature that owns this diagram (for FD-0001-D1: FD-0001)",
                    diagram_id='"FD-0001-D1"', title='"T"')

    def test_owner_must_exist(self):
        self.expect("feature_id FD-0003 is not an existing feature (did you mean FD-0002?)",
                    diagram_id='"FD-0003-D1"', feature_id='"FD-0003"', title='"T"')

    def test_owner_format(self):
        self.expect("feature_id must look like FD-0001, found 'feature A'",
                    diagram_id='"FD-0001-D1"', feature_id='"feature A"', title='"T"')

    def test_id_must_start_with_its_owner(self):
        self.expect("diagram_id FD-0001-D1 does not belong to its owner FD-0002",
                    diagram_id='"FD-0001-D1"', feature_id='"FD-0002"', title='"T"')

    def test_id_format(self):
        self.expect("diagram_id 'overlap-model' must be the owning feature's ID plus -D and a number",
                    diagram_id='"overlap-model"', feature_id='"FD-0001"', title='"T"')

    def test_title_is_required(self):
        self.expect("title is required: the diagram's readable name", diagram_id='"FD-0001-D1"', feature_id='"FD-0001"')

    def test_duplicates_are_reported_on_both_files(self):
        diagram_file(self.ws, "designs/features/diagrams/one.md", diagram_id='"FD-0001-D1"', feature_id='"FD-0001"', title='"One"')
        diagram_file(self.ws, "designs/features/diagrams/two.md", diagram_id='"FD-0001-D1"', feature_id='"FD-0001"', title='"Two"')
        found = problems(self.ws)
        self.assertTrue(any(l.startswith("designs/features/diagrams/one.md: duplicate diagram_id FD-0001-D1 "
                                          "(also in designs/features/diagrams/two.md)") for l in found), found)
        self.assertTrue(any(l.startswith("designs/features/diagrams/two.md: duplicate diagram_id FD-0001-D1") for l in found))

    def test_a_file_without_a_diagram_id_is_not_checked(self):
        """As before Phase 1: a fresh template copy is not attachable and not an error."""
        diagram_file(self.ws, "designs/features/diagrams/draft.md", diagram_id='""', feature_id='""', title='""')
        self.assertEqual(problems(self.ws), [])

    def test_a_valid_owned_diagram_has_no_problem(self):
        diagram_file(self.ws, "designs/features/diagrams/ok.md", diagram_id='"FD-0002-D4"', feature_id='"FD-0002"', title='"Ok"')
        self.assertEqual(problems(self.ws), [])


if __name__ == "__main__":
    unittest.main()
