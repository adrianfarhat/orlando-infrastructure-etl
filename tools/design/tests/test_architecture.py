"""T-94 Phase 2, M1: heading anchors, Mermaid diagram detection and the architecture index."""

import os
import posixpath
import re
import subprocess
import unittest
from pathlib import Path

from tools.design import architecture, markdown, workspace
from tools.design.tests.test_design import REPO_ROOT, Workspace, cmd


def anchors(text):
    return [h.anchor for h in markdown.parse(text).headings]


class Anchors(unittest.TestCase):
    """GitHub's anchor algorithm (github-slugger) on the heading shapes these docs use."""

    CASES = {
        "# Hello World": "hello-world",
        "## 1. Current state: the big picture": "1-current-state-the-big-picture",
        "### Streets → `road_segments`": "streets--road_segments",                   # arrow dropped, both spaces kept
        "### `GET /features?layer=<layer>&bbox=<west,south,east,north>`": "get-featureslayerlayerbboxwestsoutheastnorth",
        "#### Q3. Length in degrees vs metres (beginner–intermediate)": "q3-length-in-degrees-vs-metres-beginnerintermediate",
        "#### Q4. Nearest road to a manhole with KNN `<->` (intermediate)": "q4-nearest-road-to-a-manhole-with-knn---intermediate",
        '#### Q5. "Within N metres" with `ST_DWithin`': "q5-within-n-metres-with-st_dwithin",
        "### (a) The team workflow": "a-the-team-workflow",
        "## 2. Target model: PROPOSED, NOT BUILT": "2-target-model-proposed-not-built",
        "## **Bold** and *em* and _under_ and snake_case": "bold-and-em-and-under-and-snake_case",
        "## A [link](other.md#x) and [ref][r] text": "a-link-and-ref-text",
        "## Trailing tag <br>": "trailing-tag-",                                    # the space before it stays
        "## Escaped \\_underscores\\_ and \\*stars\\*": "escaped-_underscores_-and-stars",
        "## __strong__ and _a b_": "strong-and-a-b",
        "## _foo_bar": "_foo_bar",                                                   # no closing '_': literal
        "## foo_ bar_": "foo_-bar_",                                                 # cannot open after a letter
        "## Closing hashes ##": "closing-hashes",
        "## Привет мир": "привет-мир",
        "## Émoji 🚀 rocket": "émoji--rocket",
        "## Tom &amp; Jerry": "tom--jerry",
        "## <kbd>Key</kbd> press": "key-press",
        "##    Extra   spaces   ": "extra---spaces",
        "## Dots.and-hyphens_ok": "dotsand-hyphens_ok",
    }

    def test_known_shapes(self):
        for source, expected in self.CASES.items():
            with self.subTest(source=source):
                self.assertEqual(anchors(source), [expected])

    def test_repeated_headings_are_numbered_like_github(self):
        self.assertEqual(anchors("# Foo\n## Foo\n### Foo\n"), ["foo", "foo-1", "foo-2"])
        # a heading whose own anchor is a numbered one does not collide (github-slugger)
        self.assertEqual(anchors("# Foo\n# Foo\n# Foo 1\n"), ["foo", "foo-1", "foo-1-1"])
        self.assertEqual(anchors("# Foo 1\n# Foo\n# Foo\n"), ["foo-1", "foo", "foo-2"])

    def test_what_is_not_a_heading(self):
        text = "\n".join([
            "#hashtag without a space",
            "####### seven hashes",
            "    # indented four spaces (code)",
            "```", "# inside a fence", "```",
            "~~~~", "```", "# inside a longer tilde fence that contains ```", "```", "~~~~",
            "````markdown", "```mermaid", "flowchart LR", "```", "# still inside the four-backtick fence", "````",
            "   # three spaces is a heading",
        ])
        self.assertEqual([h.text for h in markdown.parse(text).headings], ["three spaces is a heading"])

    def test_setext_headings(self):
        doc = markdown.parse("Title\n=====\n\ntext\n\nTwo line\nheading\n---\n\n- item\n---\n\n| a |\n|---|\n")
        self.assertEqual([(h.level, h.text, h.anchor) for h in doc.headings],
                         [(1, "Title", "title"), (2, "Two line heading", "two-line-heading")])

    def test_empty_heading_has_no_anchor(self):
        self.assertEqual(anchors("#\n## \n## Real\n"), ["", "", "real"])

    def test_crlf_and_bom(self):
        self.assertEqual(markdown.parse("﻿# A\r\n## B\r\n"), markdown.parse("# A\n## B\n"))
        self.assertEqual(anchors("﻿# A b\r\n"), ["a-b"])


class Diagrams(unittest.TestCase):
    def test_detection_and_types(self):
        text = "\n".join([
            "```mermaid", "flowchart LR", "  %% diagram-type: process", "```",          # before any heading
            "# Doc",
            "## One",
            "```Mermaid title=x", "  %% a comment", "  %% diagram-type: er", "%% diagram-type: ignored", "```",
            "~~~mermaid", "sequenceDiagram", "~~~",                                      # no marker
            "## Not diagrams",
            "```mermaidjs", "x", "```",
            "```text", "```mermaid", "```",              # ```mermaid has an info string, so it cannot close: text
            "````markdown", "```mermaid", "flowchart LR", "```", "````",                # an example inside a fence
            "- list item:", "  ```mermaid", "  flowchart TB", "  %% diagram-type: architecture", "  ```",
        ])
        doc = markdown.parse(text)
        got = [(d.line, doc.headings[d.heading].text if d.heading is not None else None, d.diagram_type)
               for d in doc.diagrams]
        self.assertEqual(got, [(1, None, "process"), (7, "One", "er"), (12, "One", None),
                               (28, "Not diagrams", "architecture")])

    def test_unclosed_fence_runs_to_the_end(self):
        doc = markdown.parse("# A\n```mermaid\nflowchart LR\n# not a heading\n")
        self.assertEqual(([h.text for h in doc.headings], len(doc.diagrams)), (["A"], 1))


def write(root, rel, text):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


SAMPLE = {
    "docs/architecture/alpha.md": ("# Alpha\n\n```mermaid\nflowchart LR\n%% diagram-type: architecture\n```\n\n"
                                   "## Part | one\n\n```mermaid\nflowchart LR\n```\n\n```mermaid\nflowchart LR\n"
                                   "%% diagram-type: process\n```\n\n### Deep\n\n## Part | one\n"),
    "docs/architecture/beta.md": "```mermaid\nerDiagram\n%% diagram-type: er\n```\n\nNo headings here.\n",
    "docs/architecture/sub/gamma.md": "# Gamma\n\n#### Skips levels\n\n## Back\n",
    "docs/architecture/.hidden.md": "# Hidden\n",
    "docs/architecture/notes.txt": "# not markdown\n",
}


class ArchitectureIndex(unittest.TestCase):
    def sample(self, ws):
        for rel, text in SAMPLE.items():
            write(ws.root, rel, text)

    def test_catalog_ids_types_and_order(self):
        with Workspace(architecture=False) as ws:
            self.sample(ws)
            got = [(d.diagram_id, d.diagram_type) for d in architecture.catalog(architecture.documents(ws.root))]
            self.assertEqual(got, [("alpha/alpha", "architecture"),       # under the title
                                   ("alpha/part--one", None),             # '|' dropped, both spaces kept
                                   ("alpha/part--one~2", "process"),      # second diagram, same heading
                                   ("beta/top", "er")])                   # before any heading
            self.assertEqual([d.path for d in architecture.documents(ws.root)],
                             ["docs/architecture/alpha.md", "docs/architecture/beta.md",
                              "docs/architecture/sub/gamma.md"])           # no hidden or non-Markdown files

    def test_rendered_index(self):
        with Workspace(architecture=False) as ws:
            self.sample(ws)
            text = architecture.render_architecture_index(ws.root)
            self.assertTrue(text.startswith("<!-- GENERATED by `python -m tools.design index` from docs/architecture/."))
            self.assertIn("3 documents, 7 headings, 4 diagrams (1 architecture, 1 er, 1 not marked, 1 process).", text)
            self.assertIn("| `alpha/part--one~2` | not registered | process | [alpha.md](../../docs/architecture/alpha.md) | "
                          "[Part \\| one](../../docs/architecture/alpha.md#part--one) |", text)
            self.assertIn("| `beta/top` | not registered | er | [beta.md](../../docs/architecture/beta.md) | "
                          "(before the first heading) |", text)
            self.assertIn("| `alpha/part--one` | not registered | *not marked* |", text)
            self.assertIn("### [alpha.md](../../docs/architecture/alpha.md): Alpha", text)
            self.assertIn("Under the title: diagram `alpha/alpha` (architecture)", text)
            self.assertIn("- [Part \\| one](../../docs/architecture/alpha.md#part--one) · diagram `alpha/part--one` "
                          "(not marked); diagram `alpha/part--one~2` (process)", text)
            self.assertIn("  - [Deep](../../docs/architecture/alpha.md#deep)", text)
            self.assertIn("- [Part \\| one](../../docs/architecture/alpha.md#part--one-1)", text)   # repeated heading
            self.assertIn("Before the first heading: diagram `beta/top` (er)", text)
            self.assertIn("### [sub/gamma.md](../../docs/architecture/sub/gamma.md): Gamma", text)
            # a skipped level (# then ####) is indented one step, not three
            self.assertIn("- [Skips levels](../../docs/architecture/sub/gamma.md#skips-levels)\n- [Back]", text)
            self.assertNotRegex(text, r"20\d\d-\d\d-\d\d")                   # no timestamps
            self.assertNotIn("\r", text)

    def test_deterministic_idempotent_and_fresh(self):
        with Workspace(architecture=False) as ws:
            self.sample(ws)
            self.assertFalse(architecture.architecture_index_is_fresh(ws.root))     # not written yet
            first = architecture.render_architecture_index(ws.root)
            self.assertEqual(architecture.render_architecture_index(ws.root), first)
            path = ws.root / architecture.write_architecture_index(ws.root)
            self.assertEqual(path.read_bytes().decode("utf-8"), first)
            self.assertTrue(architecture.architecture_index_is_fresh(ws.root))
            mtime = path.stat().st_mtime_ns
            architecture.write_architecture_index(ws.root)
            self.assertEqual(path.stat().st_mtime_ns, mtime)                        # unchanged file not rewritten
            path.write_bytes(first.replace("\n", "\r\n").encode("utf-8"))           # an autocrlf checkout
            self.assertTrue(architecture.architecture_index_is_fresh(ws.root))
            write(ws.root, "docs/architecture/alpha.md", SAMPLE["docs/architecture/alpha.md"].replace("\n", "\r\n"))
            self.assertTrue(architecture.architecture_index_is_fresh(ws.root))      # CRLF sources: same index

    def test_what_makes_it_stale(self):
        with Workspace(architecture=False) as ws:
            self.sample(ws)
            architecture.write_architecture_index(ws.root)
            alpha = SAMPLE["docs/architecture/alpha.md"]
            changes = {
                "rename a heading": alpha.replace("### Deep", "### Deeper"),
                "add a diagram": alpha + "\n```mermaid\nflowchart LR\n```\n",
                "change a diagram type": alpha.replace("diagram-type: process", "diagram-type: sequence"),
                "add a heading": alpha + "\n## New\n",
            }
            for what, text in changes.items():
                with self.subTest(what):
                    write(ws.root, "docs/architecture/alpha.md", text)
                    self.assertFalse(architecture.architecture_index_is_fresh(ws.root))
            write(ws.root, "docs/architecture/alpha.md", alpha.replace("No headings", "x") + "\nMore prose.\n")
            self.assertTrue(architecture.architecture_index_is_fresh(ws.root))      # prose only: still fresh
            write(ws.root, "docs/architecture/delta.md", "# Delta\n")
            self.assertFalse(architecture.architecture_index_is_fresh(ws.root))     # a new document

    def test_unreadable_document_is_listed(self):
        with Workspace(architecture=False) as ws:
            write(ws.root, "docs/architecture/ok.md", "# Ok\n")
            (ws.root / "docs/architecture/bad.md").write_bytes(b"# Bad \xff\n")
            text = architecture.render_architecture_index(ws.root)
            self.assertIn("### bad.md\n\nCould not be read: not valid UTF-8.", text)
            self.assertIn("2 documents, 1 heading, 0 diagrams.", text)

    def test_no_architecture_folder(self):
        with Workspace(architecture=False) as ws:                                 # no docs/architecture/
            self.assertTrue(architecture.architecture_index_is_fresh(ws.root))
            self.assertIsNone(architecture.write_architecture_index(ws.root))
            self.assertFalse((ws.root / architecture.ARCHITECTURE_INDEX).exists())
            write(ws.root, architecture.ARCHITECTURE_INDEX, "left over\n")
            self.assertFalse(architecture.architecture_index_is_fresh(ws.root))     # an index of nothing is stale

    def test_architecture_documents_are_never_changed(self):
        with Workspace(architecture=False) as ws:
            self.sample(ws)
            before = {p: (ws.root / p).read_bytes() for p in SAMPLE}
            cmd(ws.root, "index")
            cmd(ws.root, "check")
            self.assertEqual({p: (ws.root / p).read_bytes() for p in SAMPLE}, before)


class CommandLine(unittest.TestCase):
    def test_index_check_and_check_report_the_architecture_index(self):
        with Workspace(architecture=False) as ws:
            write(ws.root, "docs/architecture/a.md", "# A\n## B\n")
            workspace.write_index(ws.root)
            code, out, _ = cmd(ws.root, "index", "--check")
            self.assertEqual(code, 1)
            self.assertIn("designs/index/architecture-index.md is out of date", out)
            code, out, _ = cmd(ws.root, "check")
            self.assertEqual(code, 1)
            self.assertIn("designs/index/architecture-index.md: out of date with docs/architecture/ or missing", out)
            code, out, _ = cmd(ws.root, "index")
            self.assertEqual(code, 0)
            self.assertIn("wrote designs/index/architecture-index.md", out)
            self.assertEqual(cmd(ws.root, "index", "--check")[0], 0)
            self.assertEqual(cmd(ws.root, "check")[0], 0)
            self.assertIn("designs/index/architecture-index.md is already up to date", cmd(ws.root, "index")[1])

    def test_without_architecture_folder(self):
        with Workspace(architecture=False) as ws:
            code, out, _ = cmd(ws.root, "index")
            self.assertEqual(code, 0)
            self.assertIn("no docs/architecture/ folder, so there is no architecture index", out)


class RealRepository(unittest.TestCase):
    """Read-only checks against this repository's own docs/architecture/."""

    def test_the_real_catalog(self):
        # T-97 M1: counted by registry identity, so this holds in every M1 state (embedded or extracted)
        diagrams = architecture.architecture_diagrams(REPO_ROOT)
        counts = {}
        for d in diagrams:
            counts[d.diagram_type] = counts.get(d.diagram_type, 0) + 1
        # the same 14 diagrams and types as the hand-kept inventory in conventions.md section 7
        self.assertEqual(len(diagrams), 14)
        self.assertEqual(counts, {"architecture": 4, "sequence": 1, "process": 6, "er": 2, "example": 1})
        self.assertEqual(len({d.diagram_id for d in diagrams}), 14)
        self.assertEqual(len({d.alias for d in diagrams}), 14)
        self.assertIn("system-architecture/1-current-state-the-big-picture", {d.alias for d in diagrams})
        self.assertEqual({d.problem for d in diagrams}, {""})

    def test_existing_anchor_links_resolve(self):
        """Every link in the repository's tracked Markdown to a heading in docs/ or designs/
        (written and previewed by people) resolves with this anchor algorithm."""
        files = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "*.md"], capture_output=True,
                               text=True, timeout=60, check=True).stdout.split()
        link = re.compile(r"\]\(<?([^)\s>#]+\.md)#([^)\s>]+)>?\)")
        cache, checked = {}, 0
        for rel in files:
            text = (REPO_ROOT / rel).read_bytes().decode("utf-8")
            body = "\n".join(workspace._outside_code(text))
            for path, anchor in link.findall(body):
                if "{{" in path:                                                    # a template placeholder
                    continue
                target = posixpath.normpath(posixpath.join(posixpath.dirname(rel), path))
                if not target.startswith(("docs/", "designs/")):
                    continue
                if target not in cache:
                    cache[target] = {h.anchor for h in markdown.parse(
                        (REPO_ROOT / target).read_bytes().decode("utf-8")).headings}
                with self.subTest(source=rel, target=f"{target}#{anchor}"):
                    self.assertIn(anchor, cache[target])
                checked += 1
        self.assertGreaterEqual(checked, 20)


if __name__ == "__main__":
    unittest.main()
