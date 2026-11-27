"""T-98: blank source lines in generated Mermaid copies (feature documents).

T-96 wrote each blank source line as a bare `%%`. Mermaid's comment pre-processing removes only
`%%` lines with at least one character after `%%`, so flowcharts and class diagrams drew the
line as a node labelled `%%` and ER diagrams failed to parse. The copy now writes
diagrams.BLANK_LINE (`%% (blank line)`). Evidence (three Mermaid bundles, all 7 registered
diagrams with blank lines): t97-completion-evidence/t98/repro/results.json.

Fingerprints are unchanged (U13: exact comparison, line endings the only normalisation), so the
new text is a source change for every existing copy: an untouched copy is case 1 and refreshed;
a hand-edited one stays a conflict (E15).
"""

import re
import unittest
from pathlib import Path
from unittest import mock

from tools.design import designer_api, diagrams, ownership, registry
from tools.design.tests.test_design import Workspace, cmd
from tools.design.tests.test_registry import check, insert, marker_line
from tools.design.workspace import new_feature

BLANK = diagrams.BLANK_LINE
BIG = "system-architecture/1-current-state-the-big-picture"     # AD-0010, six blank lines
ER = "database-schema/2-target-model-proposed-not-built"        # AD-0003, an ER diagram with a blank line
WITH_BLANKS = {"AD-0001", "AD-0003", "AD-0010", "AD-0011", "AD-0012", "AD-0013", "AD-0014"}


def t96_form():
    """Generate exactly as before T-98 (the real render() and start_marker(), with the T-96 placeholder)."""
    return mock.patch.object(diagrams, "BLANK_LINE", diagrams.LEGACY_BLANK_LINE)


def block_lines(ws, rel, diagram_id):
    text = ws.text(rel).replace("\r\n", "\n")
    lines = text.split("\n")
    b = next(b for b in diagrams.scan(text)[0] if b.diagram_id == diagram_id)
    return b, lines[b.start + 1:b.end]


def state(ws, rel, diagram_id):
    b, current = block_lines(ws, rel, diagram_id)
    return diagrams.classify(b, current, diagrams.render(diagrams.sources(ws.root)[diagram_id], rel))


class Placeholder(unittest.TestCase):
    def test_the_placeholder_is_an_inert_comment_that_survives_trimming(self):
        self.assertEqual(BLANK, "%% (blank line)")
        self.assertTrue(BLANK.startswith("%%") and BLANK[2:].strip())        # text after %%: removed by Mermaid
        self.assertFalse(BLANK.startswith("%%{"))                             # not directive syntax
        self.assertEqual(BLANK, BLANK.strip())                                # no leading/trailing whitespace
        self.assertNotRegex(BLANK, r"diagram-type:|<!--")                     # not a type marker, not a marker
        self.assertEqual(diagrams.LEGACY_BLANK_LINE, "%%")

    def test_render_replaces_only_blank_lines_and_keeps_indentation(self):
        lines = ("flowchart TB", "  subgraph S[\"Group\"]", "    A --> B", "", "    B --> C", "  end", "   ",
                 "\tC --> D", "  %% a comment", "%%")
        src = diagrams.Source("X", "proposed", "T", "designs/features/diagrams/x.md", "", lines, False)
        out = diagrams.render(src, "designs/features/a.md")
        self.assertEqual(out[1], "```mermaid")
        self.assertEqual(out[-1], "```")
        self.assertEqual(out[2:-1], ["flowchart TB", "  subgraph S[\"Group\"]", "    A --> B", BLANK, "    B --> C",
                                     "  end", BLANK, "\tC --> D", "  %% a comment", "%%"])
        self.assertNotIn("", out)                                             # one contiguous block (Mark Sharp)
        self.assertEqual(diagrams.render(src, "designs/features/a.md"), out)  # deterministic

    def test_reverse_mapping_reads_the_new_and_the_t96_form(self):
        cap, fence = "caption", "```mermaid"
        for form in (BLANK, "%%"):
            with self.subTest(form=form):
                body = ["flowchart LR", "  A --> B", form, "  B --> C", form, form, "  C --> D"]
                self.assertEqual(diagrams._body_from_block([cap, fence, *body, "```"]),
                                 ["flowchart LR", "  A --> B", "", "  B --> C", "", "", "  C --> D"])
        mixed = ["flowchart LR", BLANK, "  A --> B", "%%", "  B --> C"]
        self.assertEqual(diagrams._body_from_block([cap, fence, *mixed, "```"]),
                         ["flowchart LR", "", "  A --> B", "", "  B --> C"])
        # only exact lines are placeholders: an indented or annotated comment is Mermaid content
        kept = ["flowchart LR", "  " + BLANK, BLANK + " x", "%% x", " %%"]
        self.assertEqual(diagrams._body_from_block([cap, fence, *kept, "```"]), kept)


class AllArchitectureDiagrams(unittest.TestCase):
    def test_all_14_render_deterministic_copies_that_map_back_exactly(self):
        with Workspace() as ws:
            known = diagrams.sources(ws.root)
            ids = [e.diagram_id for e in registry.load(ws.root).entries if e.diagram_id.startswith("AD-")]
            self.assertEqual(len(ids), 14)
            seen_blanks = set()
            for diagram_id in ids:
                with self.subTest(diagram_id):
                    src = known[diagram_id]
                    out = diagrams.render(src, "designs/features/a.md")
                    self.assertEqual(out, diagrams.render(src, "designs/features/a.md"))
                    body = out[2:-1]
                    self.assertEqual(len(body), len(src.lines))
                    for line, original in zip(body, src.lines):
                        self.assertEqual(line, original if original.strip() else BLANK)   # nothing else changes
                    self.assertNotIn("", body)
                    self.assertNotIn("%%", body)                                          # no bare %% line
                    self.assertEqual(diagrams._body_from_block(out), list(src.lines))      # exact round trip
                    if "" in src.lines:
                        seen_blanks.add(diagram_id)
            self.assertEqual(seen_blanks, WITH_BLANKS)


class U13Upgrade(unittest.TestCase):
    """A block generated before T-98 compared with what is generated now (fingerprints unchanged)."""

    def setUp(self):
        self.ctx = Workspace(); self.ws = self.ctx.__enter__()
        self.f = new_feature(self.ws.root, "A")
        insert(self.ws, self.f.path, BIG)
        insert(self.ws, self.f.path, ER, heading="## 1. Objective")
        with t96_form():
            self.assertEqual(cmd(self.ws.root, "index")[0], 0)
        self.path = self.ws.root / self.f.path
        self.t96 = self.ws.text(self.f.path)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_the_fixture_really_is_the_t96_form(self):
        _, lines = block_lines(self.ws, self.f.path, BIG)
        self.assertEqual(lines.count("%%"), 6)
        self.assertNotIn(BLANK, self.t96)

    def test_an_untouched_t96_block_is_case_1_and_index_refreshes_it(self):
        for diagram_id in (BIG, ER):
            self.assertEqual(state(self.ws, self.f.path, diagram_id), "case1")
        found = "\n".join(check(self.ws))
        self.assertIn(f"the diagram block for {BIG} is out of date with its source", found)
        self.assertNotIn("E15", found)
        # the Feature Designer proposes the refresh for an open document without unsaved changes (U5)
        r, code = designer_api.handle(self.ws.root, {"version": 1, "op": "refresh", "path": self.f.path,
                                                     "text": self.t96})
        self.assertEqual(code, 0)
        self.assertEqual(len(r["edits"]), 2)
        self.assertEqual(r["conflicts"], [])
        code, _, _ = cmd(self.ws.root, "index")
        self.assertEqual(code, 0)
        after = self.ws.text(self.f.path)
        for diagram_id in (BIG, ER):
            self.assertEqual(state(self.ws, self.f.path, diagram_id), "current")
        _, lines = block_lines(self.ws, self.f.path, BIG)
        self.assertEqual(lines.count(BLANK), 6)
        self.assertNotIn("%%", lines)
        self.assertEqual(check(self.ws), [])
        # only the placeholder lines and the start markers' fingerprints changed
        strip = lambda t: re.sub(r" sha256:[0-9a-f]{16} -->", " -->", t).replace("\n" + BLANK + "\n", "\n%%\n")
        self.assertEqual(strip(strip(after)), strip(self.t96))
        self.assertEqual(cmd(self.ws.root, "index", "--check")[0], 0)

    def test_a_hand_edited_t96_block_stays_a_conflict(self):
        edited = self.t96.replace('BROWSER(["Your browser"])', 'BROWSER(["My browser"])', 1)
        self.assertNotEqual(edited, self.t96)
        self.path.write_bytes(edited.encode("utf-8"))
        # B differs from F (hand edit) and G differs from F (the new placeholder): case 3, never overwritten
        self.assertEqual(state(self.ws, self.f.path, BIG), "case3")
        self.assertEqual(state(self.ws, self.f.path, ER), "case1")
        self.assertIn("(E15)", "\n".join(check(self.ws)))
        code, _, err = cmd(self.ws.root, "index")
        self.assertIn("(E15)", err)
        _, lines = block_lines(self.ws, self.f.path, BIG)
        self.assertIn('  BROWSER(["My browser"])', lines)                    # the conflict is preserved as it was
        self.assertEqual(lines.count("%%"), 6)
        self.assertEqual(state(self.ws, self.f.path, ER), "current")         # the untouched block was refreshed
        r, _ = designer_api.handle(self.ws.root, {"version": 1, "op": "refresh", "path": self.f.path,
                                                  "text": self.ws.text(self.f.path)})
        self.assertEqual(r["edits"], [])
        # Discard manual change restores the generated content, in the new form
        line = marker_line(self.ws, self.f.path, BIG)
        plan = diagrams.plan_reconcile(self.ws.root, self.f.path, line, "discard")
        self.assertEqual(plan.state, "case3")
        self.assertEqual(cmd(self.ws.root, "reconcile", "--file", self.f.path, "--line", str(line), "--discard",
                             "--confirm", plan.token)[0], 0)
        self.assertEqual(state(self.ws, self.f.path, BIG), "current")
        self.assertEqual(check(self.ws), [])

    def test_a_t96_block_without_a_fingerprint_is_preserved_not_migrated(self):
        """Before U13 (no fingerprint) the content is not provably what was generated, and it now differs
        from the new output, so it is kept and reported (E15), as for any other difference."""
        legacy = re.sub(r" sha256:[0-9a-f]{16} -->", " -->", self.t96)
        self.path.write_bytes(legacy.encode("utf-8"))
        self.assertEqual(state(self.ws, self.f.path, BIG), "legacy")
        cmd(self.ws.root, "index")
        self.assertEqual(self.ws.text(self.f.path), legacy)


class ApplyToSource(unittest.TestCase):
    """Reconciliation "Apply to source" with a feature-owned source that has a blank line."""

    ORIGINAL = '  A["Existing step"] --> B["New step (planned)"]'

    def setUp(self):
        self.ctx = Workspace(); self.ws = self.ctx.__enter__()
        self.a = new_feature(self.ws.root, "A")
        self.d = ownership.new_diagram(self.ws.root, "FD-0001", "Mine")
        self.src = self.ws.root / self.d.path

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def write_source(self, extra_lines):
        text = self.src.read_bytes().decode("utf-8")
        assert text.count(self.ORIGINAL + "\n") == 1
        self.src.write_bytes(text.replace(self.ORIGINAL + "\n", self.ORIGINAL + "\n" + "".join(
            x + "\n" for x in extra_lines)).encode("utf-8"))
        return self.src.read_bytes().decode("utf-8")

    def place(self, old_form=False):
        insert(self.ws, self.a.path, self.d.diagram_id)
        if old_form:
            with t96_form():
                cmd(self.ws.root, "index")
        else:
            cmd(self.ws.root, "index")

    def hand_edit(self, old, new):
        p = self.ws.root / self.a.path
        text = p.read_bytes().decode("utf-8")
        assert text.count(old) == 1, old
        p.write_bytes(text.replace(old, new).encode("utf-8"))

    def apply(self, expect_state):
        line = marker_line(self.ws, self.a.path, self.d.diagram_id)
        plan = diagrams.plan_reconcile(self.ws.root, self.a.path, line, "apply-to-source")
        self.assertEqual(plan.state, expect_state)
        code, out, err = cmd(self.ws.root, "reconcile", "--file", self.a.path, "--line", str(line),
                             "--apply-to-source", "--confirm", plan.token)
        self.assertEqual(code, 0, out + err)

    def test_new_form_block_keeps_the_blank_line_in_the_source(self):
        before = self.write_source(["", '  B --> C["Next step"]'])
        self.place()
        _, lines = block_lines(self.ws, self.a.path, self.d.diagram_id)
        self.assertIn(BLANK, lines)
        self.hand_edit('C["Next step"]', 'C["Next step (from the block)"]')
        self.apply("case2")
        self.assertEqual(self.src.read_bytes().decode("utf-8"),
                         before.replace('C["Next step"]', 'C["Next step (from the block)"]'))
        self.assertEqual(state(self.ws, self.a.path, self.d.diagram_id), "current")
        self.assertEqual(check(self.ws), [])

    def test_t96_form_conflicted_block_keeps_the_blank_line_in_the_source(self):
        before = self.write_source(["", '  B --> C["Next step"]'])
        self.place(old_form=True)
        _, lines = block_lines(self.ws, self.a.path, self.d.diagram_id)
        self.assertIn("%%", lines)
        self.hand_edit('C["Next step"]', 'C["Next step (from the block)"]')
        # the generated output changed too (new placeholder), so the block is case 3 (both changed)
        self.apply("case3")
        self.assertEqual(self.src.read_bytes().decode("utf-8"),
                         before.replace('C["Next step"]', 'C["Next step (from the block)"]'))
        _, lines = block_lines(self.ws, self.a.path, self.d.diagram_id)
        self.assertIn(BLANK, lines)
        self.assertNotIn("%%", lines)
        self.assertEqual(check(self.ws), [])

    def test_a_source_that_contains_the_placeholder_line_is_refused(self):
        """The copy cannot tell such a line from a blank line, so Apply to source would silently turn
        it into one: it is refused (the copy itself renders the same, and Discard still works)."""
        self.write_source([BLANK, '  B --> C["Next step"]'])
        self.place()
        _, lines = block_lines(self.ws, self.a.path, self.d.diagram_id)
        self.assertIn(BLANK, lines)                                           # copied as it is
        self.assertEqual(check(self.ws), [])
        self.hand_edit('C["Next step"]', 'C["Next step (from the block)"]')
        line = marker_line(self.ws, self.a.path, self.d.diagram_id)
        source_before = self.src.read_bytes()
        with self.assertRaisesRegex(ValueError, "cannot tell apart from a blank line"):
            diagrams.plan_reconcile(self.ws.root, self.a.path, line, "apply-to-source")
        code, _, err = cmd(self.ws.root, "reconcile", "--file", self.a.path, "--line", str(line), "--apply-to-source")
        self.assertEqual(code, 2)
        self.assertIn("cannot tell apart from a blank line", err)
        self.assertEqual(self.src.read_bytes(), source_before)
        plan = diagrams.plan_reconcile(self.ws.root, self.a.path, line, "discard")
        self.assertEqual(cmd(self.ws.root, "reconcile", "--file", self.a.path, "--line", str(line), "--discard",
                             "--confirm", plan.token)[0], 0)
        self.assertEqual(check(self.ws), [])

    def test_a_crlf_source_that_contains_the_placeholder_line_is_refused(self):
        """QA T-98 minor 3: the same refusal when the source is written with CRLF line endings."""
        self.write_source([BLANK, '  B --> C["Next step"]'])
        self.src.write_bytes(self.src.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        self.place()
        self.hand_edit('C["Next step"]', 'C["Next step (from the block)"]')
        line = marker_line(self.ws, self.a.path, self.d.diagram_id)
        source_before = self.src.read_bytes()
        with self.assertRaisesRegex(ValueError, "cannot tell apart from a blank line"):
            diagrams.plan_reconcile(self.ws.root, self.a.path, line, "apply-to-source")
        self.assertEqual(self.src.read_bytes(), source_before)

    def test_a_whitespace_only_source_line_comes_back_as_an_empty_line(self):
        """QA T-98 minor 1 (unchanged since T-96, documented): a whitespace-only line is written as the
        placeholder, so Apply to source writes it back as an empty line (its spaces are not kept)."""
        before = self.write_source(["   ", '  B --> C["Next step"]'])
        self.place()
        _, lines = block_lines(self.ws, self.a.path, self.d.diagram_id)
        self.assertIn(BLANK, lines)
        self.hand_edit('C["Next step"]', 'C["Next step (from the block)"]')
        self.apply("case2")
        self.assertEqual(self.src.read_bytes().decode("utf-8"),
                         before.replace('C["Next step"]', 'C["Next step (from the block)"]')
                               .replace("\n   \n", "\n\n"))

    def test_an_indented_placeholder_like_comment_round_trips(self):
        before = self.write_source(["  " + BLANK, '  B --> C["Next step"]'])
        self.place()
        self.hand_edit('C["Next step"]', 'C["Next step (from the block)"]')
        self.apply("case2")
        self.assertEqual(self.src.read_bytes().decode("utf-8"),
                         before.replace('C["Next step"]', 'C["Next step (from the block)"]'))

    def test_a_source_line_that_is_a_bare_percent_pair_comes_back_blank(self):
        """Unchanged T-96 ambiguity, documented: a bare `%%` line in a source is copied as it is, and
        Apply to source reads every bare `%%` line of a block as a blank line (the T-96 form)."""
        before = self.write_source(["%%", '  B --> C["Next step"]'])
        self.place()
        _, lines = block_lines(self.ws, self.a.path, self.d.diagram_id)
        self.assertIn("%%", lines)
        self.hand_edit('C["Next step"]', 'C["Next step (from the block)"]')
        self.apply("case2")
        self.assertEqual(self.src.read_bytes().decode("utf-8"),
                         before.replace('C["Next step"]', 'C["Next step (from the block)"]')
                               .replace("\n%%\n", "\n\n"))


if __name__ == "__main__":
    unittest.main()
