"""T-94 Phase 2, M2: depends_on, derived "used by", generated Related features rows and the
feature index columns."""

import os
import unittest

from tools.design import dependencies, workspace
from tools.design.tests.test_design import Workspace, cmd
from tools.design.workspace import new_feature


def set_depends(ws, rel, yaml_value):
    path = ws.root / rel
    text = path.read_bytes().decode("utf-8")
    assert "depends_on: []" in text
    path.write_bytes(text.replace("depends_on: []", "depends_on:" + yaml_value, 1).encode("utf-8"))


def related_block(ws, rel):
    text = ws.text(rel)
    start = text.index("<!-- related-features:start")
    return text[text.index("\n", start) + 1:text.index("<!-- related-features:end -->")]


def messages(ws):
    return "\n".join(f"{p.path}: {p.message}" for p in workspace.check(ws.root))


class Generation(unittest.TestCase):
    def three(self, ws):
        road = new_feature(ws.root, "Road ingestion")
        pipe = new_feature(ws.root, "Pipe ingestion")
        inter = new_feature(ws.root, "Pipe road intersections")
        set_depends(ws, inter.path, '\n  - FD-0001\n  - id: FD-0002\n    optional: true\n'
                                    '    condition: "only for the weekly batch"')
        return road, pipe, inter

    def test_rows_in_both_directions(self):
        with Workspace() as ws:
            road, pipe, inter = self.three(ws)
            self.assertEqual(cmd(ws.root, "index")[0], 0)
            self.assertEqual(related_block(ws, inter.path), "\n".join([
                "| Feature | Relationship | Reference | Evidence status |", "|---|---|---|---|",
                "| FD-0001 · Road ingestion | Depends on | [road-ingestion.md](road-ingestion.md) | 🔷 PROPOSED |",
                "| FD-0002 · Pipe ingestion | Depends on (optional: only for the weekly batch) | "
                "[pipe-ingestion.md](pipe-ingestion.md) | 🔷 PROPOSED |"]) + "\n")
            self.assertEqual(related_block(ws, road.path).splitlines()[2],
                             "| FD-0003 · Pipe road intersections | Used by | "
                             "[pipe-road-intersections.md](pipe-road-intersections.md) | 🔷 PROPOSED |")
            self.assertEqual(related_block(ws, pipe.path).splitlines()[2],
                             "| FD-0003 · Pipe road intersections | Used by (optional: only for the weekly batch) | "
                             "[pipe-road-intersections.md](pipe-road-intersections.md) | 🔷 PROPOSED |")
            self.assertEqual(workspace.check(ws.root), [])

    def test_feature_index_columns(self):
        with Workspace() as ws:
            self.three(ws)
            cmd(ws.root, "index")
            index = ws.text(workspace.INDEX)
            self.assertIn("| Feature ID | Title | Design status | Parent | Depends on | Used by | File |", index)
            self.assertIn("| FD-0001 | Road ingestion | investigating | - | - | "
                          "[FD-0003](../features/pipe-road-intersections.md) | [road-ingestion.md]", index)
            self.assertIn("| FD-0002 | Pipe ingestion | investigating | - | - | "
                          "[FD-0003](../features/pipe-road-intersections.md) (optional) |", index)
            self.assertIn("| FD-0003 | Pipe road intersections | investigating | - | "
                          "[FD-0001](../features/road-ingestion.md), [FD-0002](../features/pipe-ingestion.md) "
                          "(optional) | - |", index)

    def test_no_relationships_keeps_the_template_row(self):
        with Workspace() as ws:
            created = new_feature(ws.root, "Alone")
            self.assertEqual(related_block(ws, created.path).splitlines()[2], "| — | — | — | — |")
            self.assertEqual(dependencies.refresh_related(ws.root), [])               # nothing to rewrite

    def test_nested_links_are_relative_to_each_file(self):
        with Workspace() as ws:
            top = new_feature(ws.root, "Top")
            deep = new_feature(ws.root, "Deep", parent="grp/sub")
            set_depends(ws, deep.path, " [FD-0001]")
            cmd(ws.root, "index")
            self.assertIn("| FD-0001 · Top | Depends on | [top.md](../../top.md) |", related_block(ws, deep.path))
            self.assertIn("| FD-0002 · Deep | Used by | [grp/sub/deep.md](grp/sub/deep.md) |",
                          related_block(ws, top.path))

    def test_titles_are_escaped(self):
        with Workspace() as ws:
            new_feature(ws.root, "Pipes | roads [v2] *now*")
            b = new_feature(ws.root, "User")
            set_depends(ws, b.path, " [FD-0001]")
            cmd(ws.root, "index")
            self.assertIn("| FD-0001 · Pipes \\| roads \\[v2\\] \\*now\\* | Depends on |", related_block(ws, b.path))


class OnlyTheBlockChanges(unittest.TestCase):
    def test_everything_outside_the_markers_is_byte_identical(self):
        with Workspace() as ws:
            a = new_feature(ws.root, "A")
            b = new_feature(ws.root, "B")
            set_depends(ws, b.path, " [FD-0001]")
            path = ws.root / a.path
            text = path.read_bytes().decode("utf-8").replace("\n", "\r\n")          # an autocrlf checkout
            text = text.replace("- **Problem:** [Describe", "- **Problem:** my own words  \t[Describe")
            path.write_bytes(text.encode("utf-8"))
            cmd(ws.root, "index")
            after = path.read_bytes().decode("utf-8")
            start, end = "<!-- related-features:start", "<!-- related-features:end -->"
            self.assertEqual(after[:after.index(start)], text[:text.index(start)])
            self.assertEqual(after[after.index(end):], text[text.index(end):])
            self.assertIn("| FD-0002 · B | Used by | [b.md](b.md) | 🔷 PROPOSED |\r\n", after)   # its own CRLF

    def test_idempotent_and_deterministic(self):
        with Workspace() as ws:
            for name in ("Zeta", "Alpha", "Mu"):
                new_feature(ws.root, name)
            set_depends(ws, "designs/features/alpha.md", " [FD-0003, FD-0001]")
            cmd(ws.root, "index")
            snapshot = {p: (ws.root / p).read_bytes() for p in ("designs/features/zeta.md", "designs/features/alpha.md",
                                                               "designs/features/mu.md", workspace.INDEX)}
            mtimes = {p: (ws.root / p).stat().st_mtime_ns for p in snapshot}
            self.assertEqual(cmd(ws.root, "index")[0], 0)
            self.assertEqual({p: (ws.root / p).read_bytes() for p in snapshot}, snapshot)
            self.assertEqual({p: (ws.root / p).stat().st_mtime_ns for p in snapshot}, mtimes)   # not rewritten
            self.assertEqual(workspace.render_index(ws.root), workspace.render_index(ws.root))
            # Depends on keeps the declared order; Used by is ordered by ID
            self.assertIn("| [FD-0003](../features/mu.md), [FD-0001](../features/zeta.md) |",
                          ws.text(workspace.INDEX))

    def test_invalid_metadata_is_never_touched(self):
        with Workspace() as ws:
            a = new_feature(ws.root, "A")
            b = new_feature(ws.root, "B")
            set_depends(ws, b.path, " [FD-0001]")
            path = ws.root / b.path
            path.write_bytes(path.read_bytes().replace(b"design_status: investigating", b"design_status: doing"))
            before = path.read_bytes()
            cmd(ws.root, "index")
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(related_block(ws, a.path).splitlines()[2], "| — | — | — | — |")  # no edge from bad metadata


class Staleness(unittest.TestCase):
    def test_check_and_index_check_report_stale_rows(self):
        with Workspace() as ws:
            new_feature(ws.root, "A")
            b = new_feature(ws.root, "B")
            set_depends(ws, b.path, " [FD-0001]")
            self.assertIn("designs/features/a.md: the Related features rows are out of date with depends_on", messages(ws))
            self.assertIn("designs/features/b.md: the Related features rows are out of date", messages(ws))
            code, out, _ = cmd(ws.root, "index", "--check")
            self.assertEqual(code, 1)
            self.assertIn("designs/features/b.md: the Related features rows are out of date", out)
            code, out, _ = cmd(ws.root, "index")
            self.assertIn("refreshed the Related features rows in designs/features/a.md", out)
            self.assertEqual(cmd(ws.root, "index", "--check")[0], 0)
            self.assertEqual(cmd(ws.root, "check")[0], 0)

    def test_hand_edited_rows_are_reported(self):
        with Workspace() as ws:
            a = new_feature(ws.root, "A")
            path = ws.root / a.path
            path.write_bytes(path.read_bytes().replace("| — | — | — | — |".encode(), b"| FD-0009 | typed | x | y |"))
            self.assertIn("a.md: the Related features rows are out of date", messages(ws))

    def test_missing_or_repeated_markers(self):
        with Workspace() as ws:
            a = new_feature(ws.root, "A")
            b = new_feature(ws.root, "B")
            pa, pb = ws.root / a.path, ws.root / b.path
            pa.write_bytes(pa.read_bytes().replace(b"<!-- related-features:end -->\n", b""))
            text = pb.read_bytes()
            start = text.index(b"<!-- related-features:start")
            block = text[start:text.index(b"<!-- related-features:end -->") + len(b"<!-- related-features:end -->\n")]
            pb.write_bytes(text + b"\n" + block)
            found = messages(ws)
            self.assertIn("a.md: the generated Related features block is not closed", found)
            self.assertIn("b.md: the generated Related features block is repeated", found)
            before = (pa.read_bytes(), pb.read_bytes())
            cmd(ws.root, "index")
            self.assertEqual((pa.read_bytes(), pb.read_bytes()), before)           # never rewritten


class IndexWarnings(unittest.TestCase):
    """`index` says which files it left alone, once per file, and still changes nothing in them."""

    @staticmethod
    def warnings(err):
        return [line for line in err.splitlines() if line.startswith("design: warning: ")]

    def test_valid_workspace_has_no_warnings(self):
        with Workspace() as ws:
            new_feature(ws.root, "A")
            code, _, err = cmd(ws.root, "index")
            self.assertEqual((code, err), (0, ""))

    def test_one_warning_per_file_and_nothing_rewritten(self):
        with Workspace() as ws:
            new_feature(ws.root, "Good")
            bad_meta = new_feature(ws.root, "Bad meta")
            no_related = new_feature(ws.root, "No related")
            two_problems = new_feature(ws.root, "Two problems")
            user = new_feature(ws.root, "User")
            set_depends(ws, user.path, " [FD-0001, FD-0002, FD-0003, FD-0004]")   # every block is now stale
            p = {f: ws.root / f.path for f in (bad_meta, no_related, two_problems)}
            p[bad_meta].write_bytes(p[bad_meta].read_bytes().replace(b"design_status: investigating",
                                                                     b"design_status: doing"))
            p[no_related].write_bytes(p[no_related].read_bytes().replace(b"<!-- related-features:end -->\n", b""))
            text = p[two_problems].read_bytes()
            text = text.replace(b"<!-- summary:end -->\n", b"")
            start = text.index(b"<!-- related-features:start")
            end = text.index(b"<!-- related-features:end -->") + len(b"<!-- related-features:end -->\n")
            p[two_problems].write_bytes(text + b"\n" + text[start:end])
            before = {f: path.read_bytes() for f, path in p.items()}
            (ws.root / "designs/features/diagrams").mkdir()
            (ws.root / "designs/features/diagrams/sketch.md").write_text("# not a feature\n", encoding="utf-8")

            code, out, err = cmd(ws.root, "index")
            self.assertEqual(code, 0)
            self.assertEqual(self.warnings(err), [
                "design: warning: designs/features/bad-meta.md: its metadata has a problem, so its summary table "
                "and Related features rows were not refreshed; run `python -m tools.design check`",
                "design: warning: designs/features/no-related.md: the Related features markers are not closed, "
                "so that block was not refreshed; run `python -m tools.design check`",
                "design: warning: designs/features/two-problems.md: the summary table markers are not closed; the "
                "Related features markers are repeated, so those blocks were not refreshed; run "
                "`python -m tools.design check`"])
            self.assertEqual(err.count("two-problems.md"), 1)                         # no duplicate lines
            self.assertEqual({f: path.read_bytes() for f, path in p.items()}, before)  # never rewritten or repaired
            self.assertIn("refreshed the Related features rows in designs/features/good.md", out)
            self.assertIn("refreshed the Related features rows in designs/features/user.md", out)

            code, out, err = cmd(ws.root, "index")                                    # the same warnings again,
            self.assertEqual(len(self.warnings(err)), 3)                              # no other output changes
            self.assertNotIn("refreshed", out)

    def test_a_missing_block_and_unreadable_metadata(self):
        with Workspace() as ws:
            a = new_feature(ws.root, "A")
            path = ws.root / a.path
            text = path.read_bytes()
            start = text.index(b"<!-- summary:start")
            end = text.index(b"<!-- summary:end -->") + len(b"<!-- summary:end -->\n")
            path.write_bytes(text[:start] + text[end:])
            (ws.root / "designs/features/no-meta.md").write_text("# no metadata\n", encoding="utf-8")
            _, _, err = cmd(ws.root, "index")
            self.assertIn("design: warning: designs/features/a.md: the summary table markers are missing, so that "
                          "block was not refreshed", err)
            self.assertIn("design: warning: designs/features/no-meta.md: its metadata has a problem", err)

    def test_check_and_index_check_are_unchanged(self):
        with Workspace() as ws:
            a = new_feature(ws.root, "A")
            path = ws.root / a.path
            path.write_bytes(path.read_bytes().replace(b"<!-- related-features:end -->\n", b""))
            for argv in (("check",), ("index", "--check")):
                with self.subTest(argv=argv):
                    self.assertNotIn("design: warning:", cmd(ws.root, *argv)[2])


class MovesAndRenames(unittest.TestCase):
    def test_a_rename_keeps_the_relationship_and_index_fixes_the_links(self):
        with Workspace() as ws:
            new_feature(ws.root, "A")
            b = new_feature(ws.root, "B")
            set_depends(ws, b.path, " [FD-0001]")
            cmd(ws.root, "index")
            (ws.root / "designs/features/archive").mkdir()
            os.replace(ws.root / "designs/features/a.md", ws.root / "designs/features/archive/a-renamed.md")
            self.assertIn("b.md: the Related features rows are out of date", messages(ws))
            cmd(ws.root, "index")
            self.assertIn("| FD-0001 · A | Depends on | [archive/a-renamed.md](archive/a-renamed.md) |",
                          related_block(ws, b.path))
            self.assertIn("| FD-0002 · B | Used by | [b.md](../b.md) |",
                          related_block(ws, "designs/features/archive/a-renamed.md"))
            self.assertEqual(workspace.check(ws.root), [])

    def test_convert_parent_refreshes_only_the_rows_that_mention_it(self):
        with Workspace() as ws:
            new_feature(ws.root, "Parent")
            user = new_feature(ws.root, "User")
            set_depends(ws, user.path, " [FD-0001]")
            cmd(ws.root, "index")
            other_a = new_feature(ws.root, "Other A")
            other_b = new_feature(ws.root, "Other B")
            set_depends(ws, other_b.path, " [FD-0003]")                              # stale, unrelated to the move
            stale_before = (ws.root / other_a.path).read_bytes()
            code, out, err = cmd(ws.root, "new", "feature", "--name", "Child", "--parent", "FD-0001",
                                 "--convert-parent")
            self.assertEqual(code, 0, err)
            self.assertIn("refreshed the Related features rows in designs/features/user.md", out)
            self.assertIn("| FD-0001 · Parent | Depends on | [parent/README.md](parent/README.md) |",
                          related_block(ws, user.path))
            self.assertIn("| FD-0002 · User | Used by | [user.md](../user.md) |",
                          related_block(ws, "designs/features/parent/README.md"))
            self.assertEqual((ws.root / other_a.path).read_bytes(), stale_before)    # untouched
            self.assertNotIn("other-a.md", out)


class GraphProblems(unittest.TestCase):
    def test_unknown_self_and_repeated(self):
        with Workspace() as ws:
            a = new_feature(ws.root, "A")
            b = new_feature(ws.root, "B")
            set_depends(ws, b.path, " [FD-0002, FD-0099, FD-0001, FD-0001]")
            cmd(ws.root, "index")
            found = messages(ws)
            self.assertIn("b.md: depends_on[0]: a feature cannot depend on itself (FD-0002)", found)
            self.assertIn("b.md: depends_on[1]: FD-0099 is not the ID of any feature", found)
            self.assertIn("b.md: depends_on[3]: FD-0001 is listed more than once", found)
            rows = related_block(ws, b.path).splitlines()[2:]
            self.assertEqual(rows, ["| FD-0099 · *no feature has this ID* | Depends on | — | 🔷 PROPOSED |",
                                    "| FD-0001 · A | Depends on | [a.md](a.md) | 🔷 PROPOSED |"])
            self.assertIn("| FD-0099 (unknown), [FD-0001](../features/a.md) |", ws.text(workspace.INDEX))
            self.assertEqual(len(related_block(ws, a.path).splitlines()), 3)          # one Used by row, not two
            self.assertEqual(cmd(ws.root, "check")[0], 1)

    def test_cycles_are_reported_not_resolved(self):
        with Workspace() as ws:
            for name in ("A", "B", "C", "D"):
                new_feature(ws.root, name)
            set_depends(ws, "designs/features/a.md", " [FD-0002]")
            set_depends(ws, "designs/features/b.md", " [FD-0003]")
            set_depends(ws, "designs/features/c.md", " [FD-0001, FD-0004]")
            set_depends(ws, "designs/features/d.md", " [FD-0003]")
            cmd(ws.root, "index")
            cycles = [p for p in workspace.check(ws.root) if "cycle" in p.message]
            self.assertEqual(len(cycles), 1)                                          # one group, reported once
            self.assertEqual(cycles[0].path, "designs/features/a.md")                 # at its lowest ID
            # C and D also depend on each other, so all four are one group
            self.assertEqual("dependency cycle among FD-0001, FD-0002, FD-0003, FD-0004 (review their depends_on lists; "
                             "nothing was changed), for example: FD-0001 → FD-0002 → FD-0003 → FD-0001",
                             cycles[0].message)
            self.assertIn("| FD-0002 · B | Depends on |", related_block(ws, "designs/features/a.md"))  # rows kept
            self.assertEqual(ws.meta("designs/features/c.md")["depends_on"], ["FD-0001", "FD-0004"])
            self.assertEqual(cmd(ws.root, "check")[0], 1)

    def test_two_separate_cycles_and_an_optional_edge(self):
        with Workspace() as ws:
            for name in ("A", "B", "C", "D"):
                new_feature(ws.root, name)
            set_depends(ws, "designs/features/a.md", " [FD-0002]")
            set_depends(ws, "designs/features/b.md", "\n  - id: FD-0001\n    optional: true")
            set_depends(ws, "designs/features/c.md", " [FD-0004]")
            set_depends(ws, "designs/features/d.md", " [FD-0003]")
            found = [p.message.split("for example: ", 1)[1] for p in workspace.check(ws.root) if "cycle" in p.message]
            self.assertEqual(found, ["FD-0001 → FD-0002 → FD-0001", "FD-0003 → FD-0004 → FD-0003"])

    def test_every_member_of_a_tangled_cycle_is_named(self):
        """1→2, 1→3, 2→1, 3→1: one group; the example path shows one loop, the message names all."""
        with Workspace() as ws:
            for name in ("A", "B", "C"):
                new_feature(ws.root, name)
            set_depends(ws, "designs/features/a.md", " [FD-0002, FD-0003]")
            set_depends(ws, "designs/features/b.md", " [FD-0001]")
            set_depends(ws, "designs/features/c.md", " [FD-0001]")
            cycles = [p.message for p in workspace.check(ws.root) if "cycle" in p.message]
            self.assertEqual(len(cycles), 1)
            self.assertIn("dependency cycle among FD-0001, FD-0002, FD-0003", cycles[0])
            self.assertIn("for example: FD-0001 → FD-0002 → FD-0001", cycles[0])

    def test_a_chain_is_not_a_cycle(self):
        with Workspace() as ws:
            for name in ("A", "B", "C"):
                new_feature(ws.root, name)
            set_depends(ws, "designs/features/a.md", " [FD-0002, FD-0003]")
            set_depends(ws, "designs/features/b.md", " [FD-0003]")
            cmd(ws.root, "index")
            self.assertEqual(workspace.check(ws.root), [])

    def test_a_duplicate_id_target(self):
        with Workspace() as ws:
            a = new_feature(ws.root, "A")
            b = new_feature(ws.root, "B")
            copy = ws.root / "designs/features/a-copy.md"
            copy.write_bytes((ws.root / a.path).read_bytes().replace(b'title: "A"', b'title: "A copy"'))
            set_depends(ws, b.path, " [FD-0001]")
            cmd(ws.root, "index")
            self.assertIn("| FD-0001 · *2 files share this ID* | Depends on | [a-copy.md](a-copy.md)<br>[a.md](a.md) |",
                          related_block(ws, b.path))
            self.assertIn("| FD-0001 (duplicate ID) |", ws.text(workspace.INDEX))
            self.assertIn("duplicate feature_id FD-0001", messages(ws))


if __name__ == "__main__":
    unittest.main()
