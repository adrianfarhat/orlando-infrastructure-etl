"""T-95: the design checks accept what a formatting editor (Mark Sharp) writes, and still reject
real column mistakes. See tools/design/tests/marksharp_port.py for the port's provenance."""

import unittest

from tools.design import workspace
from tools.design.tests.marksharp_port import transform
from tools.design.tests.test_design import Workspace, cmd
from tools.design.workspace import new_feature, table_cells

HEADER = "| Component | Relationship | Reference | Evidence status |"


def section_problems(ws):
    return [p.message for p in workspace.check(ws.root) if "must have the columns" in p.message]


def fill(ws, rel):
    """A realistic feature: wide System components rows and two dependencies."""
    path = ws.root / rel
    text = path.read_bytes().decode("utf-8")
    text = text.replace(
        "| Component | Relationship | Reference | Evidence status |\n|---|---|---|---|\n| — | — | — | — |",
        "| Component | Relationship | Reference | Evidence status |\n|---|---|---|---|\n"
        "| `public.road_segments` (14,943 rows) | reads_from | [data contracts](../../docs/architecture/data-contracts.md) | ✅ VERIFIED |\n"
        "| `analysis.road_pipe_overlap` | writes_to | proposed table | 🔷 PROPOSED |")
    text = text.replace("| [source field] | [database field] | [type] | [path or URL] | ❔ UNKNOWN |",
                        "| `OBJECTID` | `road_segments.source_objectid` | integer, unique | ArcGIS layer | ✅ VERIFIED |")
    path.write_bytes(text.encode("utf-8"))


class TableCells(unittest.TestCase):
    def test_padding_and_outer_pipes_do_not_matter(self):
        for row in (HEADER, "|Component|Relationship|Reference|Evidence status|",
                    "| Component              | Relationship | Reference   | Evidence status |",
                    "  | Component | Relationship | Reference | Evidence status |  "):
            with self.subTest(row=row):
                self.assertEqual(table_cells(row), ["Component", "Relationship", "Reference", "Evidence status"])

    def test_escaped_pipes_stay_in_the_cell(self):
        self.assertEqual(table_cells(r"| a \| b | c |"), [r"a \| b", "c"])

    def test_real_column_mistakes_are_still_rejected(self):
        """Names, order, count and case must match exactly; only padding is ignored."""
        cases = {
            "renamed": "| Component | Relation | Reference | Evidence status |",
            "reordered": "| Relationship | Component | Reference | Evidence status |",
            "missing": "| Component | Relationship | Reference |",
            "extra": "| Component | Relationship | Reference | Evidence status | Notes |",
            "case": "| component | Relationship | Reference | Evidence status |",
            "merged by an escaped pipe": r"| Component \| Relationship | Reference | Evidence status |",
        }
        with Workspace() as ws:
            created = new_feature(ws.root, "A")
            original = (ws.root / created.path).read_bytes().decode("utf-8")
            for name, header in cases.items():
                with self.subTest(name):
                    (ws.root / created.path).write_bytes(original.replace(HEADER, header).encode("utf-8"))
                    self.assertEqual(section_problems(ws),
                                     [f"the table under '### System components' must have the columns {HEADER}"])
            no_table = original.replace(HEADER + "\n|---|---|---|---|\n| — | — | — | — |", "No table here.")
            (ws.root / created.path).write_bytes(no_table.encode("utf-8"))
            self.assertEqual(len(section_problems(ws)), 1)


class MarkSharpRoundTrip(unittest.TestCase):
    """What Mark Sharp writes on save (ported exporter) keeps every check passing."""

    def round_trip(self, mode):
        with Workspace() as ws:
            new_feature(ws.root, "Road ingestion")
            created = new_feature(ws.root, "Pipe road intersections")
            fill(ws, created.path)
            path = ws.root / created.path
            path.write_bytes(path.read_bytes().replace(b"depends_on: []", b"depends_on: [FD-0001]"))
            cmd(ws.root, "index")
            self.assertEqual(workspace.check(ws.root), [])
            before = path.read_bytes().decode("utf-8")
            after = transform(before, mode)
            self.assertNotEqual(after, before)                                     # tables really re-formatted
            path.write_bytes(after.encode("utf-8"))
            self.assertEqual(workspace.check(ws.root), [], mode)                   # nothing to fix
            self.assertEqual(cmd(ws.root, "index", "--check")[0], 0)
            for start, end in (("<!-- summary:start", "<!-- summary:end -->"),
                               ("<!-- related-features:start", "<!-- related-features:end -->")):
                self.assertEqual(after[after.index(start):after.index(end)], before[before.index(start):before.index(end)])
            self.assertEqual(workspace.split_front_matter(after)[0], workspace.split_front_matter(before)[0])
            changed = [(a, b) for a, b in zip(before.split("\n"), after.split("\n")) if a != b]
            self.assertTrue(all(a.lstrip().startswith("|") for a, _ in changed), changed)   # only table rows
            self.assertEqual(transform(after, mode), after)                         # a second save changes nothing
            mtime = path.stat().st_mtime_ns
            cmd(ws.root, "index")
            self.assertEqual(path.stat().st_mtime_ns, mtime)                        # index leaves it alone

    def test_align_columns(self):
        self.round_trip("alignColumns")

    def test_condensed(self):
        self.round_trip("condensed")


if __name__ == "__main__":
    unittest.main()
