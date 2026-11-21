"""T-96: generated diagram blocks — placement, generation, validation, preservation."""

import shutil
import unittest
from pathlib import Path

from tools.design import architecture, diagrams, links, markdown, workspace
from tools.design.tests.marksharp_port import transform
from tools.design.tests.test_design import REPO_ROOT, Workspace, cmd
from tools.design.workspace import SECTIONS, new_feature

START = "<!-- diagram:start {} -->"
END = "<!-- diagram:end -->"
BIG = "system-architecture/1-current-state-the-big-picture"     # an architecture diagram with blank lines
ETL = "etl-workflow/streets--road_segments"                       # a process diagram
ER = "database-schema/2-target-model-proposed-not-built"


def block(diagram_id):
    return f"\n{START.format(diagram_id)}\n{END}\n"


def put(ws, rel, after, text, count=1):
    path = ws.root / rel
    body = path.read_bytes().decode("utf-8")
    assert body.count(after) == 1, after
    path.write_bytes(body.replace(after, after + text * count).encode("utf-8"))


def problems(ws):
    return [p.message for p in workspace.check(ws.root)]


def outside(text):
    """The text with every diagram block's generated lines removed (what people wrote)."""
    lines = text.replace("\r\n", "\n").split("\n")
    for start, end in reversed(diagrams.spans(text)):
        del lines[start + 1:end]
    return "\n".join(lines)


class Placement(unittest.TestCase):
    def test_every_section_several_per_section_and_repeated_ids(self):
        with Workspace() as ws:
            f = new_feature(ws.root, "A")
            for heading in SECTIONS:
                put(ws, f.path, heading + "\n", block(ETL))
            put(ws, f.path, "## 3. Logic\n", block(BIG) + block(ER) + block(BIG))
            self.assertEqual(cmd(ws.root, "index")[0], 0)
            text = ws.text(f.path)
            self.assertEqual(text.count("<!-- diagram:start"), 9)
            self.assertEqual(problems(ws), [])
            self.assertEqual(diagrams.ids_in(text), [ETL, BIG, ER])
            doc = markdown.parse(workspace.split_front_matter(text)[1])
            self.assertEqual([h.text for h in doc.headings if h.level == 2],
                             [s[3:] for s in SECTIONS])                                    # six sections intact
            self.assertEqual(len(doc.diagrams), 10)                                      # 9 copies + the template's own
            self.assertTrue(all(d.closed for d in doc.diagrams))

    def test_files_without_markers_are_unchanged(self):
        with Workspace() as ws:
            f = new_feature(ws.root, "A")
            before = (ws.root / f.path).read_bytes()
            mtime = (ws.root / f.path).stat().st_mtime_ns
            cmd(ws.root, "index")
            self.assertEqual(((ws.root / f.path).read_bytes(), (ws.root / f.path).stat().st_mtime_ns), (before, mtime))
            self.assertEqual(problems(ws), [])


class Generation(unittest.TestCase):
    def test_caption_link_legend_and_exact_source(self):
        with Workspace() as ws:
            f = new_feature(ws.root, "Deep", parent="grp")
            put(ws, f.path, "## 3. Logic\n", block(BIG) + block(ETL))
            cmd(ws.root, "index")
            lines = ws.text(f.path).split("\n")
            known = diagrams.sources(ws.root)
            for diagram_id in (BIG, ETL):
                i = lines.index(START.format(diagram_id))
                caption, fence = lines[i + 1], lines[i + 2]
                src = known[diagram_id]
                end = lines.index(END, i)
                self.assertTrue(caption.startswith("**✅ Current architecture: ["))
                self.assertIn(f"`{diagram_id}`", caption)
                self.assertIn("generated copy; edit the source", caption)
                self.assertEqual(fence, "```mermaid")
                self.assertEqual(lines[end - 1], "```")                                  # closed before the end marker
                self.assertEqual(lines[i + 3:end - 1], [l if l.strip() else "%%" for l in src.lines])
                self.assertNotIn("", lines[i + 1:end])                                  # one contiguous block
                link = caption.split("](", 1)[1].split(")", 1)[0]
                self.assertIsNone(links.check_link(links._Repo(ws.root), f.path, link), link)   # link resolves
                self.assertEqual("legend](" in caption, src.legend)
            self.assertTrue(known[BIG].legend and not known[ETL].legend)               # architecture only
            self.assertIn("", known[BIG].lines)                                          # BIG really has blank lines

    def test_the_copy_is_the_authoritative_block_even_with_several_per_document(self):
        with Workspace(architecture=False) as ws:
            doc = ws.root / "docs/architecture/sample.md"
            doc.parent.mkdir(parents=True)
            doc.write_text("# Sample\n\n## Part\n\n```mermaid\nflowchart LR\n  A --> B\n```\n\ntext\n\n"
                           "```mermaid\nflowchart LR\n  C --> D\n\n  D --> E\n```\n\n## Other\n\n"
                           "````mermaid\nflowchart LR\n```\n  X --> Y\n````\n", encoding="utf-8")
            architecture.write_architecture_index(ws.root)
            shutil.copytree(REPO_ROOT / "designs/templates", ws.root / "designs/templates", dirs_exist_ok=True)
            f = new_feature(ws.root, "A")
            put(ws, f.path, "## 1. Objective\n", block("sample/part") + block("sample/part~2") + block("sample/other"))
            cmd(ws.root, "index")
            text = ws.text(f.path)
            self.assertIn("```mermaid\nflowchart LR\n  A --> B\n```", text)
            self.assertIn("```mermaid\nflowchart LR\n  C --> D\n%%\n  D --> E\n```", text)
            # a source line that starts with ``` would close a ``` fence early: the copy uses ````
            self.assertIn("````mermaid\nflowchart LR\n```\n  X --> Y\n````", text)
            self.assertTrue(all(d.closed for d in markdown.parse(workspace.split_front_matter(text)[1]).diagrams))
            self.assertEqual([p for p in problems(ws) if "diagram" in p], [])

    def test_deterministic_idempotent_and_nothing_outside_changes(self):
        with Workspace() as ws:
            a = new_feature(ws.root, "A")
            b = new_feature(ws.root, "B")
            a_before = ws.text(a.path)
            path = ws.root / b.path
            path.write_bytes(path.read_bytes().replace(b"depends_on: []", b"depends_on: [FD-0001]"))
            put(ws, b.path, "## 2. Data contract\n", block(ER))
            put(ws, b.path, "## 5. Downstream impact\n", block(BIG))
            cmd(ws.root, "index")
            first = path.read_bytes()
            mtime = path.stat().st_mtime_ns
            self.assertEqual(cmd(ws.root, "index")[0], 0)
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), (first, mtime))   # idempotent
            known = diagrams.sources(ws.root)
            self.assertEqual(diagrams.apply(first.decode("utf-8"), b.path, known), first.decode("utf-8"))
            # everything people wrote, the summary and the Related rows, is untouched by the blocks
            text = first.decode("utf-8")
            self.assertIn("| FD-0001 · A | Depends on |", text)
            self.assertEqual(problems(ws), [])
            # A (no markers) only got its generated "Used by" row; nothing else changed
            changed = [(x, y) for x, y in zip(a_before.split("\n"), ws.text(a.path).split("\n")) if x != y]
            self.assertEqual(changed, [("| — | — | — | — |", "| FD-0002 · B | Used by | [b.md](b.md) | 🔷 PROPOSED |")])

    def test_crlf_files_keep_their_line_endings(self):
        with Workspace() as ws:
            f = new_feature(ws.root, "A")
            path = ws.root / f.path
            text = path.read_bytes().decode("utf-8").replace("## 3. Logic\n", "## 3. Logic\n" + block(ETL))
            path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
            before = path.read_bytes().decode("utf-8")
            cmd(ws.root, "index")
            after = path.read_bytes().decode("utf-8")
            self.assertNotIn("\n", after.replace("\r\n", ""))                           # every line CRLF
            self.assertEqual(outside(after), outside(before))
            self.assertEqual(problems(ws), [])


class Validation(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace()
        self.f = new_feature(self.ws.root, "A")
        self.path = self.ws.root / self.f.path

    def tearDown(self):
        self.ws.__exit__(None, None, None)

    def write(self, text):
        self.path.write_bytes(text.encode("utf-8"))

    def generated(self, diagram_id=ETL):
        put(self.ws, self.f.path, "## 3. Logic\n", block(diagram_id))
        cmd(self.ws.root, "index")
        return self.path.read_bytes().decode("utf-8")

    def expect(self, fragment, rewritten=False):
        found = problems(self.ws)
        self.assertTrue(any(fragment in p for p in found), found)
        before = self.path.read_bytes()
        code, _, err = cmd(self.ws.root, "index")
        self.assertEqual(code, 0)
        if not rewritten:
            self.assertEqual(self.path.read_bytes(), before)                           # never rewritten silently
            self.assertIn("a diagram block has a problem", err)
        self.assertEqual(cmd(self.ws.root, "check")[0], 1 if not rewritten else 0)

    def test_unknown_empty_and_renamed_ids(self):
        put(self.ws, self.f.path, "## 3. Logic\n", block("etl-workflow/streets-road-segments"))
        self.expect("unknown diagram ID 'etl-workflow/streets-road-segments' (did you mean etl-workflow/streets--road_segments?)")
        self.write(self.path.read_text(encoding="utf-8").replace("etl-workflow/streets-road-segments", ""))
        self.expect("diagram:start has no diagram ID")

    def test_a_renamed_heading_or_missing_source_breaks_the_id(self):
        self.generated(ETL)
        doc = self.ws.root / "docs/architecture/etl-workflow.md"
        doc.write_bytes(doc.read_bytes().replace("### Streets → `road_segments`".encode(), "### Streets loader".encode()))
        self.expect("unknown diagram ID 'etl-workflow/streets--road_segments' (did you mean etl-workflow/streets-loader?)")
        doc.unlink()
        self.expect("unknown diagram ID 'etl-workflow/streets--road_segments'")

    def test_missing_unmatched_nested_and_malformed_markers(self):
        cases = {
            "missing end": (f"{START.format(ETL)}\n", f"diagram:start {ETL} has no matching"),
            "end without start": (f"{END}\n", "without a matching <!-- diagram:start"),
            "nested": (f"{START.format(ETL)}\n{START.format(BIG)}\n{END}\n", "blocks cannot be nested"),
            "spaced keyword": ("<!-- diagram: start x -->\n", "malformed diagram marker"),
            "end with an ID": (f"{START.format(ETL)}\n<!-- diagram:end x -->\n{END}\n", "malformed diagram marker"),
            "wrong case": ("<!-- Diagram:start x -->\n", "malformed diagram marker"),
        }
        original = self.path.read_text(encoding="utf-8")
        for name, (text, fragment) in cases.items():
            with self.subTest(name):
                self.write(original.replace("## 3. Logic\n", "## 3. Logic\n\n" + text))
                self.expect(fragment)

    def test_stale_and_hand_edited_content(self):
        text = self.generated(ETL)
        self.write(text.replace("S1 --> S2", "S1 --> S2X"))                             # Mermaid edited by hand
        self.expect(f"the diagram block for {ETL} differs from the authoritative Mermaid source", rewritten=True)
        doc = self.ws.root / "docs/architecture/etl-workflow.md"                      # source changed: stale
        doc.write_bytes(doc.read_bytes().replace(b"S1 --> S2", b"S1 --> S2b"))
        architecture.write_architecture_index(self.ws.root)
        self.expect("differs from the authoritative Mermaid source in docs/architecture/etl-workflow.md#streets--road_segments",
                    rewritten=True)
        self.assertIn("S1 --> S2b", self.path.read_text(encoding="utf-8"))            # index brought it up to date

    def test_edited_caption_or_source_link(self):
        text = self.generated(ETL)
        self.write(text.replace("etl-workflow.md#streets--road_segments)", "etl-workflow.md#elsewhere)"))
        self.expect("has a caption or source link that differs from the generated one", rewritten=True)

    def test_an_unclosed_fence_is_reported_not_swallowed(self):
        text = self.generated(ETL)
        lines = text.split("\n")
        end = lines.index(END)
        del lines[end - 1]                                                               # remove the closing fence
        self.write("\n".join(lines))
        self.expect("is not closed before <!-- diagram:end -->")

    def test_markers_in_code_and_in_generated_blocks(self):
        original = self.path.read_text(encoding="utf-8")
        self.write(original.replace("## 3. Logic\n", "## 3. Logic\n\n```text\n" + START.format("nope") + "\n" + END + "\n```\n"))
        self.assertEqual(problems(self.ws), [])                                         # an example, ignored
        self.write(original.replace("<!-- summary:end -->", START.format(ETL) + "\n<!-- summary:end -->"))
        self.assertTrue(any("inside a generated summary" in p for p in problems(self.ws)))

    def test_mermaid_content_is_not_read_as_markers(self):
        with Workspace(architecture=False) as ws:
            doc = ws.root / "docs/architecture/sample.md"
            doc.parent.mkdir(parents=True)
            doc.write_text("# S\n\n## P\n\n```mermaid\nflowchart LR\n  %% <!-- diagram:start other -->\n"
                           "  A --> B\n```\n", encoding="utf-8")
            architecture.write_architecture_index(ws.root)
            f = new_feature(ws.root, "A")
            put(ws, f.path, "## 1. Objective\n", block("sample/p"))
            cmd(ws.root, "index")
            self.assertEqual([p for p in problems(ws) if "diagram" in p], [])


class Integration(unittest.TestCase):
    def test_links_catalog_index_and_editor(self):
        with Workspace() as ws:
            f = new_feature(ws.root, "A")
            put(ws, f.path, "## 4. Dependencies\n", block(BIG) + block(ER))
            cmd(ws.root, "index")
            self.assertEqual(problems(ws), [])
            self.assertEqual(links.link_problems(ws.root), [])                         # blocks not double-checked
            self.assertEqual(len(architecture.catalog(architecture.documents(ws.root))), 14)   # no new catalog IDs
            self.assertTrue(architecture.architecture_index_is_fresh(ws.root))
            self.assertEqual(cmd(ws.root, "index", "--check")[0], 0)
            # Mark Sharp (ported exporter): the blocks are kept verbatim and check still passes
            for mode in ("alignColumns", "condensed"):
                with self.subTest(mode=mode):
                    path = ws.root / f.path
                    before = path.read_bytes().decode("utf-8")
                    after = transform(before, mode)
                    for start, end in diagrams.spans(before):
                        self.assertEqual(after.split("\n")[start:end + 1], before.split("\n")[start:end + 1])
                    path.write_bytes(after.encode("utf-8"))
                    self.assertEqual(problems(ws), [])
                    path.write_bytes(before.encode("utf-8"))

    def test_index_check_reports_stale_blocks(self):
        with Workspace() as ws:
            f = new_feature(ws.root, "A")
            put(ws, f.path, "## 3. Logic\n", block(ETL))
            code, out, _ = cmd(ws.root, "index", "--check")
            self.assertEqual(code, 1)
            self.assertIn(f"the diagram block for {ETL} is empty", out)


if __name__ == "__main__":
    unittest.main()
