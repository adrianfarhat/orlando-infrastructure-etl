"""T-94 Phase 2, M3: link, architecture_refs and proposed-diagram reference checks, D1 and D2."""

import hashlib
import unittest

from tools.design import links, workspace
from tools.design.tests.test_design import Workspace, cmd
from tools.design.workspace import new_feature


def write(ws, rel, text):
    path = ws.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def problems(ws):
    return [f"{p.path}: {p.message}" for p in workspace.check(ws.root)]


def link_problems(ws):
    return [f"{p.path}: {p.message}" for p in links.link_problems(ws.root)]


def set_meta(ws, rel, old, new):
    path = ws.root / rel
    text = path.read_bytes().decode("utf-8")
    assert old in text, old
    path.write_bytes(text.replace(old, new, 1).encode("utf-8"))


class Links(unittest.TestCase):
    def test_a_fresh_workspace_is_clean(self):
        with Workspace() as ws:
            new_feature(ws.root, "A")
            new_feature(ws.root, "Deep", parent="grp/sub")
            self.assertEqual(problems(ws), [])

    def test_broken_targets_and_anchors(self):
        with Workspace() as ws:
            workspace.write_index(ws.root)                                              # designs/README.md links to it
            write(ws, "designs/features/evidence/data.csv", "a,b\n")
            write(ws, "designs/features/evidence/notes.md", "\n".join([
                "# Notes",                                                                # line 1
                "[ok](../../../docs/architecture/system-architecture.md#credential-boundary)",
                "[gone](../../../docs/architecture/no-such-doc.md)",
                "[case](../../../docs/architecture/System-Architecture.md)",
                "[anchor](../../../docs/architecture/system-architecture.md#credential-boundry)",
                "[self ok](#notes) [self bad](#nothing-here)",
                "[outside](../../../../elsewhere.md)",
                "[absolute](/docs/architecture/conventions.md) [drive](C:/x.md)",
                "[slash](..\\..\\README.md)",
                "[folder](../../../docs/architecture/) [space](<../../my folder/x.md>) [encoded](../../my%20folder/x.md)",
                "[web](https://example.invalid/x) [mail](mailto:a@example.invalid) [data](data.csv#L5)",  # #L: T-81
                "`[in code](missing.md)` and",
                "```", "[in a fence](missing.md)", "```",
                "[ref]: ../../nothing.md \"a reference definition\"",                    # line 16
                "[query](../../README.md?plain=1#create-a-feature)",
            ]))
            found = "\n".join(link_problems(ws))
            expected = [
                "line 3: broken link (../../../docs/architecture/no-such-doc.md): docs/architecture/no-such-doc.md "
                "does not exist",
                "line 4: broken link (../../../docs/architecture/System-Architecture.md): docs/architecture/"
                "System-Architecture.md does not exist (did you mean docs/architecture/system-architecture.md? "
                "letter case matters on GitHub)",
                "line 5: broken link (../../../docs/architecture/system-architecture.md#credential-boundry): "
                "docs/architecture/system-architecture.md has no heading with the anchor #credential-boundry "
                "(did you mean #credential-boundary?)",
                "line 6: broken link (#nothing-here): designs/features/evidence/notes.md has no heading with the "
                "anchor #nothing-here",
                "line 7: broken link (../../../../elsewhere.md): points outside the repository",
                "line 8: broken link (/docs/architecture/conventions.md): an absolute path",
                "line 8: broken link (C:/x.md): an absolute path",
                "line 9: broken link (..\\..\\README.md): uses '\\'",
                "line 10: broken link (<../../my folder/x.md>): designs/my folder/x.md does not exist",
                "line 10: broken link (../../my%20folder/x.md): designs/my folder/x.md does not exist",
                "line 16: broken link (../../nothing.md): designs/nothing.md does not exist",
            ]
            for e in expected:
                self.assertIn("designs/features/evidence/notes.md: " + e, found)
            self.assertEqual(len(found.splitlines()), len(expected), found)              # nothing else reported
            write(ws, "designs/my folder/x.md", "# X\n")
            self.assertNotIn("my folder", "\n".join(link_problems(ws)))                # now both resolve

    def test_comments_and_protocol_relative_links_are_not_checked(self):
        with Workspace() as ws:
            workspace.write_index(ws.root)
            write(ws, "designs/features/evidence/c.md", "\n".join([
                "# C", "<!-- [a](gone.md) -->", "<!-- a comment", "over [b](gone2.md) lines -->",
                "[web](//example.invalid/x.md)", "after <!-- x --> [real](gone3.md)"]))
            self.assertEqual([p for p in link_problems(ws) if "c.md" in p],
                             ["designs/features/evidence/c.md: line 6: broken link (gone3.md): "
                              "designs/features/evidence/gone3.md does not exist"])

    def test_line_numbers_count_the_metadata_block(self):
        with Workspace() as ws:
            created = new_feature(ws.root, "A")
            text = ws.text(created.path).replace("- **Problem:** [Describe the real problem to be solved]",
                                                 "- **Problem:** see [notes](missing-notes.md)")
            write(ws, created.path, text)
            line = text.split("\n").index("- **Problem:** see [notes](missing-notes.md)") + 1
            self.assertIn(f"{created.path}: line {line}: broken link (missing-notes.md): "
                          "designs/features/missing-notes.md does not exist", problems(ws))

    def test_a_moved_file_and_a_renamed_target_are_found(self):
        with Workspace() as ws:
            a = new_feature(ws.root, "A")
            b = new_feature(ws.root, "B")
            set_meta(ws, b.path, "- **Problem:** [Describe the real problem to be solved]",
                     "- **Problem:** builds on [A](a.md#1-objective)")
            self.assertEqual(problems(ws), [])
            (ws.root / a.path).rename(ws.root / "designs/features/a-renamed.md")
            cmd(ws.root, "index")                                    # generated rows and index follow the move
            line = ws.text(b.path).split("\n").index("- **Problem:** builds on [A](a.md#1-objective)") + 1
            broken = [p for p in problems(ws) if "broken link" in p]
            self.assertEqual(len(broken), 1, broken)
            self.assertTrue(broken[0].startswith(f"{b.path}: line {line}: broken link (a.md#1-objective): "
                                                 "designs/features/a.md does not exist"), broken)

    def test_generated_content_and_templates_are_not_checked(self):
        with Workspace() as ws:
            created = new_feature(ws.root, "A")
            set_meta(ws, created.path, "architecture_refs: []", "architecture_refs: [docs/architecture/gone.md]")
            cmd(ws.root, "index")
            found = problems(ws)
            self.assertEqual(len([p for p in found if "gone.md" in p]), 1)              # once, at its source
            self.assertIn(f"{created.path}: architecture_refs[0] ('docs/architecture/gone.md') "
                          "docs/architecture/gone.md does not exist", "\n".join(found))
            write(ws, "designs/templates/extra.md", "[x](missing.md)\n")
            write(ws, "designs/index/extra.md", "[x](missing.md)\n")
            self.assertFalse([p for p in link_problems(ws) if "extra.md" in p])

    def test_check_is_read_only(self):
        with Workspace() as ws:
            created = new_feature(ws.root, "A")
            set_meta(ws, created.path, "architecture_refs: []", "architecture_refs: ['', /abs.md]")
            write(ws, "designs/features/diagrams/d.md", "---\nsource_diagram: nope\nbase_commit: xyz\n---\n[x](y.md)\n")
            snapshot = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ws.root.rglob("*")) if p.is_file()}
            self.assertEqual(cmd(ws.root, "check")[0], 1)
            self.assertEqual(cmd(ws.root, "index", "--check")[0], 1)
            self.assertEqual({p: hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted(ws.root.rglob("*")) if p.is_file()}, snapshot)


class ArchitectureRefs(unittest.TestCase):
    def refs(self, ws, yaml_list):
        created = new_feature(ws.root, "A")
        set_meta(ws, created.path, "architecture_refs: []", "architecture_refs:" + yaml_list)
        return created

    def test_valid_references(self):
        with Workspace() as ws:
            self.refs(ws, "\n  - docs/architecture/system-architecture.md#1-current-state-the-big-picture"
                          "\n  - docs/architecture/data-contracts.md\n  - ./docs/architecture/conventions.md")
            cmd(ws.root, "index")
            self.assertEqual(problems(ws), [])

    def test_each_kind_of_bad_reference(self):
        with Workspace() as ws:
            created = self.refs(ws, "\n  - ''\n  - /docs/architecture/conventions.md\n  - docs/agents/task-board.md"
                                    "\n  - docs/architecture/missing.md\n  - docs/architecture/conventions.md#nope-x"
                                    "\n  - docs\\architecture\\conventions.md\n  - docs/architecture/conventions.md#2-diagram-type")
            cmd(ws.root, "index")
            found = "\n".join(problems(ws))
            for e in ("architecture_refs[0] ('') is empty",
                      "architecture_refs[1] ('/docs/architecture/conventions.md') must be a repository-relative path",
                      "architecture_refs[2] ('docs/agents/task-board.md') must be a Markdown document in docs/architecture/",
                      "architecture_refs[3] ('docs/architecture/missing.md') docs/architecture/missing.md does not exist",
                      "architecture_refs[4] ('docs/architecture/conventions.md#nope-x') docs/architecture/conventions.md "
                      "has no heading with the anchor #nope-x",
                      "architecture_refs[5] ('docs\\\\architecture\\\\conventions.md') uses '\\'",
                      "architecture_refs[6] ('docs/architecture/conventions.md#2-diagram-type') docs/architecture/"
                      "conventions.md has no heading with the anchor #2-diagram-type (did you mean #2-diagram-types?)"):
                self.assertIn(f"{created.path}: {e}", found)

    def test_a_renamed_heading_is_reported(self):
        with Workspace() as ws:
            self.refs(ws, " [docs/architecture/etl-workflow.md#safety-gates]")
            cmd(ws.root, "index")
            self.assertEqual(problems(ws), [])
            doc = ws.root / "docs/architecture/etl-workflow.md"
            doc.write_bytes(doc.read_bytes().replace(b"## Safety gates", b"## Safety checks"))
            cmd(ws.root, "index")                                    # the architecture index is regenerated
            self.assertIn("has no heading with the anchor #safety-gates (did you mean #safety-checks?)",
                          "\n".join(problems(ws)))


class SummaryLinks(unittest.TestCase):
    """D2: the summary never contains a broken link. D1: no stray backslashes in the branch cell."""

    def summary(self, ws, rel):
        text = ws.text(rel)
        return text[text.index("<!-- summary:start"):text.index("<!-- summary:end -->")]

    def test_valid_references_link_and_resolve(self):
        with Workspace() as ws:
            created = new_feature(ws.root, "Deep", parent="grp")
            set_meta(ws, created.path, "architecture_refs: []",
                     "architecture_refs: [./docs/architecture/system-architecture.md#credential-boundary]")
            cmd(ws.root, "index")
            self.assertIn("[./docs/architecture/system-architecture.md#credential-boundary]"
                          "(../../../docs/architecture/system-architecture.md#credential-boundary)",
                          self.summary(ws, created.path))
            reason = links.check_link(links._Repo(ws.root), created.path,
                                      "../../../docs/architecture/system-architecture.md#credential-boundary")
            self.assertIsNone(reason)

    def test_invalid_references_are_plain_text(self):
        with Workspace() as ws:
            created = new_feature(ws.root, "A")
            set_meta(ws, created.path, "architecture_refs: []",
                     "architecture_refs: ['', /etc/x.md, 'C:/x.md', docs/agents/x.md, 'docs/architecture/a b.md#x y']")
            cmd(ws.root, "index")
            summary = self.summary(ws, created.path)
            self.assertIn("*(empty)* *(not a valid reference: run check)*", summary)
            self.assertIn("/etc/x.md *(not a valid reference: run check)*", summary)
            self.assertIn("C:/x.md *(not a valid reference: run check)*", summary)
            self.assertIn("docs/agents/x.md *(not a valid reference: run check)*", summary)
            self.assertNotIn("]()", summary)
            # syntactically valid, so it is linked, with the space quoted (check reports it as missing)
            self.assertIn("(../../docs/architecture/a%20b.md#x%20y)", summary)

    def test_branch_cell_has_no_stray_backslashes(self):
        with Workspace() as ws:
            created = new_feature(ws.root, "A")
            set_meta(ws, created.path, 'branch: ""', 'branch: "design/pipe_road|v2*`x`"')
            cmd(ws.root, "index")
            self.assertIn("| **Branch** | `design/pipe_road\\|v2*x` |", self.summary(ws, created.path))
            self.assertEqual(problems(ws), [])


class DiagramReferences(unittest.TestCase):
    def diagram(self, ws, meta):
        write(ws, "designs/features/grp/diagrams/proposed.md", "---\n" + meta + "\n---\n\n# Proposed\n")
        return [p for p in problems(ws) if "proposed.md" in p]

    def test_a_correct_copy(self):
        with Workspace() as ws:
            self.assertEqual(self.diagram(ws, "source_diagram: system-architecture/credential-boundary\n"
                                              "source_document: docs/architecture/system-architecture.md\n"
                                              "source_heading: credential-boundary\nbase_commit: e38b6ea"), [])
            self.assertEqual(self.diagram(ws, 'source_diagram: ""\nsource_document: ""\nbase_commit: ""'), [])

    def test_the_template_itself_passes(self):
        with Workspace() as ws:
            write(ws, "designs/features/grp/diagrams/proposed.md", ws.text("designs/templates/diagram.md"))
            self.assertEqual([p for p in problems(ws) if "proposed.md" in p], [])

    def test_each_kind_of_bad_reference(self):
        with Workspace() as ws:
            rel = "designs/features/grp/diagrams/proposed.md"
            cases = {
                "source_diagram: system-architecture/credential-boundry":
                    "source_diagram 'system-architecture/credential-boundry' is not a diagram ID in the architecture "
                    "index (did you mean system-architecture/credential-boundary?)",
                "source_diagram: system-architecture/credential-boundary\nsource_document: docs/architecture/etl-workflow.md":
                    "source_document 'docs/architecture/etl-workflow.md' does not match source_diagram "
                    "'system-architecture/credential-boundary', which is in docs/architecture/system-architecture.md",
                "source_diagram: etl-workflow/safety-gates\nsource_document: docs/architecture/etl-workflow.md\n"
                "source_heading: the-common-pattern":
                    "source_heading 'the-common-pattern' does not match source_diagram 'etl-workflow/safety-gates', "
                    "which is under #safety-gates",
                "source_document: docs/architecture/etl-workflow.md\nsource_heading: safety-gate":
                    "source_document/source_heading (docs/architecture/etl-workflow.md#safety-gate) docs/architecture/"
                    "etl-workflow.md has no heading with the anchor #safety-gate (did you mean #safety-gates?)",
                "source_heading: safety-gates": "source_heading is set but source_document is empty",
                "source_diagram: etl-workflow/safety-gates\nsource_heading: the-common-pattern":
                    "source_heading is set but source_document is empty",                # one problem, not two
                "base_commit: HEAD~1": "base_commit 'HEAD~1' does not look like a commit hash (7 to 40 lower-case "
                                       "hex characters, from `git rev-parse --short HEAD`)",
                "source_diagram: [unclosed": "the diagram metadata is not valid YAML",
            }
            for meta, expected in cases.items():
                with self.subTest(meta=meta):
                    self.assertEqual(self.diagram(ws, meta), [f"{rel}: {expected}"])    # exactly one problem

    def test_a_renamed_heading_breaks_the_diagram_id(self):
        with Workspace() as ws:
            self.assertEqual(self.diagram(ws, "source_diagram: etl-workflow/safety-gates"), [])
            doc = ws.root / "docs/architecture/etl-workflow.md"
            doc.write_bytes(doc.read_bytes().replace(b"## Safety gates", b"## Safety checks"))
            found = self.diagram(ws, "source_diagram: etl-workflow/safety-gates")
            self.assertIn("source_diagram 'etl-workflow/safety-gates' is not a diagram ID in the architecture index "
                          "(did you mean etl-workflow/safety-checks?)", "\n".join(found))

    def test_no_metadata_is_not_checked(self):
        with Workspace() as ws:
            write(ws, "designs/features/grp/diagrams/sketch.md", "# Just a sketch\n")
            self.assertEqual([p for p in problems(ws) if "sketch.md" in p], [])


if __name__ == "__main__":
    unittest.main()
