"""T-94 Phase 1: New Feature, the feature index and checks, on temporary workspaces."""

import ast
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.design import cli, workspace
from tools.design.workspace import DesignError, new_feature

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE = REPO_ROOT / "tools" / "design"
GIT = ["git", "-c", "init.defaultBranch=main", "-c", "core.autocrlf=false", "-c", "user.name=design-tests",
       "-c", "user.email=design-tests@example.invalid", "-c", "commit.gpgsign=false"]


class Workspace:
    """A temporary repository root with the real templates (and a .git marker or a real repo)."""

    def __init__(self, real_git: bool = False, folder_name: str = "repo"):
        self._tmp = tempfile.TemporaryDirectory(prefix="design-test-")
        self.root = Path(self._tmp.name) / folder_name
        (self.root / "designs").mkdir(parents=True)
        shutil.copytree(REPO_ROOT / "designs" / "templates", self.root / "designs" / "templates")
        if real_git:
            self.git("init", "-q")
        else:
            (self.root / ".git").mkdir()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()

    def git(self, *args):
        r = subprocess.run(GIT + ["-C", str(self.root), *args], capture_output=True, timeout=60)
        if r.returncode:
            raise AssertionError(r.stderr.decode("utf-8", "replace"))
        return r.stdout.decode("utf-8", "replace")

    def text(self, rel):
        return (self.root / rel).read_bytes().decode("utf-8")

    def meta(self, rel):
        front, _ = workspace.split_front_matter(self.text(rel))
        return workspace._yaml().load(front)


def cmd(root, *argv, **kw):
    """Run `python -m tools.design <argv> --root <root>` in-process."""
    out, err = io.StringIO(), io.StringIO()
    code = cli.main([*argv, "--root", str(root)], stdout=out, stderr=err, **kw)
    return code, out.getvalue(), err.getvalue()


class StandaloneFeatures(unittest.TestCase):
    def test_creates_a_fully_populated_specification(self):
        with Workspace() as ws:
            created = new_feature(ws.root, "Pipe road intersections")
            self.assertEqual((created.path, created.feature_id, created.moved),
                             ("designs/features/pipe-road-intersections.md", "FD-0001", None))
            meta = ws.meta(created.path)
            self.assertEqual({k: meta[k] for k in ("feature_id", "title", "design_status", "owner", "branch",
                                                   "architecture_refs", "depends_on")},
                             {"feature_id": "FD-0001", "title": "Pipe road intersections",
                              "design_status": "investigating", "owner": "", "branch": "",
                              "architecture_refs": [], "depends_on": []})
            text = ws.text(created.path)
            for heading in workspace.SECTIONS + tuple(workspace.TABLES) + tuple(workspace.TABLES.values()):
                self.assertIn(heading, text)
            self.assertIn("# Pipe road intersections", text)
            self.assertIn("(../../docs/architecture/system-architecture.md)", text)   # resolves from the file
            self.assertIn("(../README.md#evidence-classifications)", text)
            self.assertIn("../templates/diagram.md", text)
            self.assertNotIn("{{", text)
            self.assertEqual(workspace.check(ws.root), [])                         # valid, index fresh
            index = ws.text(workspace.INDEX)
            self.assertIn("| FD-0001 | Pipe road intersections | investigating | - | "
                          "[pipe-road-intersections.md](../features/pipe-road-intersections.md) |", index)

    def test_every_relative_link_resolves_from_the_generated_location(self):
        """S2: every relative link in a generated spec, standalone or nested, points to an
        existing file or folder in this repository when the spec sits at its path here."""
        import re
        link = re.compile(r"\]\(([^)\s#]+)(#[^)]*)?\)")
        with Workspace() as ws:
            for created in (new_feature(ws.root, "Links"), new_feature(ws.root, "Deep links", parent="a/b")):
                text = ws.text(created.path)
                targets = [m.group(1) for m in link.finditer(text)] + re.findall(r"from (\S+/diagram\.md)", text)
                self.assertGreaterEqual(len(targets), 9, created.path)        # 8 links + the diagram template
                here = (REPO_ROOT / created.path).parent                    # where the file would live in this repo
                for target in targets:
                    with self.subTest(file=created.path, target=target):
                        # Resolve ".." lexically first: the nested folder does not exist in this
                        # repository, and POSIX systems cannot walk through a missing folder.
                        resolved = Path(os.path.normpath(here / target))
                        self.assertTrue(resolved.exists(), f"{target} does not resolve from {created.path}")

    def test_sequential_ids_are_stable_when_files_move(self):
        with Workspace() as ws:
            a = new_feature(ws.root, "Alpha")
            b = new_feature(ws.root, "Beta")
            self.assertEqual((a.feature_id, b.feature_id), ("FD-0001", "FD-0002"))
            moved = ws.root / "designs/features/renamed-beta.md"
            os.replace(ws.root / b.path, moved)                                    # a rename keeps the ID
            self.assertEqual(ws.meta("designs/features/renamed-beta.md")["feature_id"], "FD-0002")
            self.assertEqual(new_feature(ws.root, "Gamma").feature_id, "FD-0003")
            index = ws.text(workspace.INDEX)
            self.assertIn("| FD-0002 | Beta | investigating | - | [renamed-beta.md]", index)

    def test_names_with_spaces_unicode_and_a_root_path_with_spaces(self):
        with Workspace(folder_name="my repo with spaces") as ws:
            created = new_feature(ws.root, "  Résumé   of  road  works ")
            self.assertEqual(created.path, "designs/features/resume-of-road-works.md")
            self.assertEqual(ws.meta(created.path)["title"], "Résumé of road works")
            self.assertEqual(workspace.check(ws.root), [])

    def test_titles_with_yaml_and_markdown_characters(self):
        with Workspace() as ws:
            created = new_feature(ws.root, 'Road: "pipes" | #1 & [maps]')
            self.assertEqual(ws.meta(created.path)["title"], 'Road: "pipes" | #1 & [maps]')
            self.assertIn("Road: \"pipes\" \\| #1 & \\[maps\\]", ws.text(workspace.INDEX))
            self.assertEqual(workspace.check(ws.root), [])


class NestedFeatures(unittest.TestCase):
    def test_subfeature_in_a_new_group_folder(self):
        with Workspace() as ws:
            created = new_feature(ws.root, "Pipe road intersections", parent="road-pipe-coordination")
            self.assertEqual(created.path, "designs/features/road-pipe-coordination/pipe-road-intersections.md")
            self.assertIn("(../../../docs/architecture/system-architecture.md)", ws.text(created.path))
            self.assertIn("| FD-0001 | Pipe road intersections | investigating | group road-pipe-coordination/ |",
                          ws.text(workspace.INDEX))

    def test_subfeature_under_a_folder_feature(self):
        with Workspace() as ws:
            parent = new_feature(ws.root, "Coordination", parent="coordination-group")
            os.makedirs(ws.root / "designs/features/coord")
            os.replace(ws.root / parent.path, ws.root / "designs/features/coord/README.md")
            child = new_feature(ws.root, "Child", parent=parent.feature_id)
            self.assertEqual(child.path, "designs/features/coord/child.md")
            self.assertIn("| FD-0002 | Child | investigating | FD-0001 |", ws.text(workspace.INDEX))

    def test_standalone_parent_needs_explicit_conversion(self):
        with Workspace() as ws:
            parent = new_feature(ws.root, "Road pipe coordination")
            before = ws.text(parent.path)
            with self.assertRaisesRegex(DesignError, "--convert-parent"):
                new_feature(ws.root, "Pipe road intersections", parent=parent.feature_id)
            self.assertEqual(ws.text(parent.path), before)                         # nothing moved
            self.assertFalse((ws.root / "designs/features/pipe-road-intersections.md").exists())
            child = new_feature(ws.root, "Pipe road intersections", parent=parent.feature_id, convert_parent=True)
            self.assertEqual(child.moved, ("designs/features/road-pipe-coordination.md",
                                           "designs/features/road-pipe-coordination/README.md"))
            self.assertEqual(child.path, "designs/features/road-pipe-coordination/pipe-road-intersections.md")
            self.assertFalse((ws.root / parent.path).exists())
            converted = ws.text("designs/features/road-pipe-coordination/README.md")
            self.assertEqual(ws.meta("designs/features/road-pipe-coordination/README.md")["feature_id"], "FD-0001")
            self.assertIn("(../../../docs/architecture/system-architecture.md)", converted)   # links adjusted
            self.assertIn("(../../README.md#evidence-classifications)", converted)
            self.assertIn("| FD-0002 | Pipe road intersections | investigating | FD-0001 |", ws.text(workspace.INDEX))
            self.assertEqual(workspace.check(ws.root), [])

    def test_conversion_flag_misuse_and_unknown_parent(self):
        with Workspace() as ws:
            with self.assertRaisesRegex(DesignError, "must be a feature ID such as FD-0003; 'group' is a folder"):
                new_feature(ws.root, "X", parent="group", convert_parent=True)
            with self.assertRaisesRegex(DesignError, "no parent was given. Run again without --convert-parent"):
                new_feature(ws.root, "X", convert_parent=True)
            with self.assertRaisesRegex(DesignError, "no feature has the ID FD-0042"):
                new_feature(ws.root, "Y", parent="FD-0042")
            self.assertFalse((ws.root / "designs/features").exists() and any((ws.root / "designs/features").rglob("*.md")))


class GateTwoFixes(unittest.TestCase):
    """Fixes approved at Gate 2: D2 (cancel), D4 (lowercase IDs, messages, index wording),
    S1 (ID gaps, deferred status, determinism across separate runs), S3 (empty parent)."""

    def test_lowercase_parent_id_is_a_feature_id(self):
        with Workspace() as ws:
            parent = new_feature(ws.root, "Parent", parent="grp")
            os.makedirs(ws.root / "designs/features/par")
            os.replace(ws.root / parent.path, ws.root / "designs/features/par/README.md")
            child = new_feature(ws.root, "Child", parent=" fd-0001 ")
            self.assertEqual(child.path, "designs/features/par/child.md")
            self.assertFalse((ws.root / "designs/features/fd-0001").exists())          # no folder named after it
            with self.assertRaisesRegex(DesignError, "FD-0001 is already a folder feature .* nothing to convert"):
                new_feature(ws.root, "Other", parent="fd-0001", convert_parent=True)
            standalone = new_feature(ws.root, "Solo")
            with self.assertRaisesRegex(DesignError, "cannot hold subfeatures yet.*--convert-parent.*nothing was changed"):
                new_feature(ws.root, "Under solo", parent=standalone.feature_id.lower())

    def test_ids_continue_after_gaps_and_the_highest_id(self):
        with Workspace() as ws:
            first = new_feature(ws.root, "One")
            text = ws.text(first.path).replace("FD-0001", "FD-0005").replace('"One"', '"Five"')
            (ws.root / "designs/features/five.md").write_bytes(text.encode("utf-8"))
            self.assertEqual(new_feature(ws.root, "Next").feature_id, "FD-0006")      # max + 1, gaps not reused
            (ws.root / "designs/features/five.md").unlink()                          # deleting the highest ...
            self.assertEqual(new_feature(ws.root, "After delete").feature_id, "FD-0007")  # ... FD-0006 is still highest

    def test_deferred_and_every_design_status_are_accepted(self):
        required = ("investigating", "proposed", "approved", "implementing", "verified", "deferred")
        self.assertEqual(workspace.STATUSES, required)                 # the brief's six values, exactly
        with Workspace() as ws:
            created = new_feature(ws.root, "Status")
            for status in required:
                with self.subTest(status=status):
                    text = ws.text(created.path).replace("design_status: investigating", f"design_status: {status}", 1)
                    path = ws.root / created.path
                    path.write_bytes(text.encode("utf-8"))
                    workspace.write_index(ws.root)
                    self.assertEqual(workspace.check(ws.root), [])
                    self.assertIn(f"| FD-0001 | Status | {status} |", ws.text(workspace.INDEX))
                    path.write_bytes(text.replace(f"design_status: {status}", "design_status: investigating", 1)
                                     .encode("utf-8"))

    def test_index_is_byte_identical_across_separate_processes_and_workspaces(self):
        outputs = []
        for _ in range(2):
            with Workspace() as ws:
                for name, parent in (("Zeta", None), ("Alpha", "grp"), ("Mu", None)):
                    r = subprocess.run([sys.executable, "-B", "-m", "tools.design", "new", "feature", "--name", name,
                                        *(["--parent", parent] if parent else []), "--root", str(ws.root)],
                                       cwd=REPO_ROOT, capture_output=True, timeout=120)
                    self.assertEqual(r.returncode, 0, r.stderr)
                first = (ws.root / workspace.INDEX).read_bytes()
                r = subprocess.run([sys.executable, "-B", "-m", "tools.design", "index", "--root", str(ws.root)],
                                   cwd=REPO_ROOT, capture_output=True, timeout=120)
                self.assertIn(b"already up to date", r.stdout)
                self.assertEqual((ws.root / workspace.INDEX).read_bytes(), first)
                outputs.append(first)
        self.assertEqual(outputs[0], outputs[1])

    def test_index_command_reports_up_to_date_or_written(self):
        with Workspace() as ws:
            new_feature(ws.root, "A")
            self.assertIn("is already up to date", cmd(ws.root, "index")[1])
            (ws.root / workspace.INDEX).unlink()
            self.assertIn("wrote designs/index/feature-index.md", cmd(ws.root, "index")[1])

    def test_cancelling_a_prompt(self):
        for exc in (KeyboardInterrupt, EOFError):
            with self.subTest(exc=exc.__name__), Workspace() as ws:
                def ask(question, exc=exc):
                    raise exc
                code, out, err = cmd(ws.root, "new", "feature", ask=ask, interactive=True)
                self.assertEqual((code, out), (2, ""))
                self.assertEqual(err, "design: cancelled; nothing was created or changed\n")
                self.assertNotIn("internal error", err)
                self.assertFalse((ws.root / "designs/features").exists())
                self.assertFalse((ws.root / workspace.INDEX).exists())

    def test_closed_stdin_is_not_interactive(self):
        """Limitation 1: with stdin closed (sys.stdin is None) the command reports a clear
        error instead of an internal error, and creates nothing."""
        from unittest import mock
        with Workspace() as ws, mock.patch.object(sys, "stdin", None):
            code, out, err = cmd(ws.root, "new", "feature")
            self.assertEqual((code, out), (2, ""))
            self.assertIn("--name is required when not running interactively", err)
            self.assertNotIn("internal error", err)
            self.assertFalse((ws.root / "designs/features").exists())
        with Workspace() as ws:                                            # an empty null-device stdin
            r = subprocess.run([sys.executable, "-B", "-m", "tools.design", "new", "feature", "--root", str(ws.root)],
                               cwd=REPO_ROOT, capture_output=True, stdin=subprocess.DEVNULL, timeout=120)
            # Windows reports the NUL device as a terminal, so the command prompts and reads
            # end of input (cancelled); elsewhere it is not interactive (--name required).
            self.assertEqual(r.returncode, 2)
            self.assertRegex(r.stderr, rb"design: (cancelled; nothing was created|error: --name is required)")
            self.assertNotIn(b"internal error", r.stderr)
            self.assertFalse((ws.root / "designs/features").exists())

    def test_cancel_after_the_name_creates_nothing(self):
        with Workspace() as ws:
            answers = iter(["Named"])

            def ask(question):
                try:
                    return next(answers)
                except StopIteration:
                    raise KeyboardInterrupt from None
            code, _, err = cmd(ws.root, "new", "feature", ask=ask, interactive=True)
            self.assertEqual(code, 2)
            self.assertIn("cancelled", err)
            self.assertFalse((ws.root / "designs/features").exists())

    def test_empty_or_dropped_parent_gives_a_standalone_feature(self):
        """S3: the VS Code task sends --parent "" when the input is empty; an editor might
        also drop the empty argument, leaving a bare --parent. Both mean standalone."""
        task_variants = {
            "empty value": ["--parent", ""],
            "dropped value": ["--parent"],
            "dropped value before another flag": ["--parent", "--convert-parent"],
            "no parent option": [],
        }
        for label, extra in task_variants.items():
            with self.subTest(variant=label), Workspace() as ws:
                r = subprocess.run([sys.executable, "-B", "-m", "tools.design", "new", "feature", "--name",
                                    "Task feature", *extra, "--root", str(ws.root)],
                                   cwd=REPO_ROOT, capture_output=True, timeout=120)
                if "--convert-parent" in extra:
                    self.assertEqual(r.returncode, 2)
                    self.assertIn(b"no parent was given", r.stderr)
                    continue
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue((ws.root / "designs/features/task-feature.md").is_file())
                self.assertIn("| FD-0001 | Task feature | investigating | - |", ws.text(workspace.INDEX))


class Refusals(unittest.TestCase):
    def test_duplicates_are_refused_and_nothing_is_overwritten(self):
        with Workspace() as ws:
            first = new_feature(ws.root, "Pavement condition")
            original = ws.text(first.path)
            for name in ("Pavement condition", "pavement   CONDITION", "Pavement-condition"):
                with self.subTest(name=name), self.assertRaises(DesignError):
                    new_feature(ws.root, name)
            self.assertEqual(ws.text(first.path), original)
            (ws.root / "designs/features/x-y.md").write_bytes(b"manual\n")
            with self.assertRaisesRegex(DesignError, "already exists"):
                new_feature(ws.root, "X y")
            self.assertEqual(ws.text("designs/features/x-y.md"), "manual\n")

    def test_invalid_names(self):
        with Workspace() as ws:
            for name, message in (("", "empty"), ("   ", "empty"), ("a\nb", "control"), ("tab\there", "control"),
                                  ("zero\u200bwidth", "invisible"), ("!!!", "letters or digits"),
                                  ("Diagrams", "reserved"), ("con", "reserved"), ("x" * 121, "longer")):
                with self.subTest(name=name), self.assertRaisesRegex(DesignError, message):
                    new_feature(ws.root, name)

    def test_invalid_destinations(self):
        with Workspace() as ws:
            new_feature(ws.root, "Base")
            for parent, message in (("../outside", "stay inside"), ("C:/x", "absolute"), ("/abs", "absolute"),
                                    ("group/../../x", "stay inside"), ("New Group", "lower-case"),
                                    ("base.md", "is a file"), ("g/diagrams", "diagrams/ or evidence/")):
                with self.subTest(parent=parent), self.assertRaisesRegex(DesignError, message):
                    new_feature(ws.root, "Child " + parent.replace("/", " "), parent=parent)

    def test_existing_folder_with_spaces_is_a_valid_parent(self):
        with Workspace() as ws:
            (ws.root / "designs/features/My Group").mkdir(parents=True)
            created = new_feature(ws.root, "Inside", parent="My Group")
            self.assertEqual(created.path, "designs/features/My Group/inside.md")
            self.assertIn("(../features/My%20Group/inside.md)", ws.text(workspace.INDEX))

    def test_duplicate_ids_block_new_features(self):
        with Workspace() as ws:
            a = new_feature(ws.root, "A")
            shutil.copy(ws.root / a.path, ws.root / "designs/features/copy.md")
            with self.assertRaisesRegex(DesignError, "duplicate feature IDs"):
                new_feature(ws.root, "B")


class IndexAndCheck(unittest.TestCase):
    def test_index_is_deterministic_and_idempotent(self):
        with Workspace() as ws:
            for name in ("Zeta", "Alpha", "Mu"):
                new_feature(ws.root, name)
            first = ws.text(workspace.INDEX)
            self.assertEqual(workspace.render_index(ws.root), first)
            mtime = (ws.root / workspace.INDEX).stat().st_mtime_ns
            workspace.write_index(ws.root)
            self.assertEqual((ws.root / workspace.INDEX).stat().st_mtime_ns, mtime)   # unchanged file not rewritten
            ids = [line.split(" | ")[0][2:] for line in first.splitlines() if line.startswith("| FD-")]
            self.assertEqual(ids, ["FD-0001", "FD-0002", "FD-0003"])                 # ordered by ID
            self.assertTrue(first.startswith("<!-- GENERATED"))
            self.assertNotRegex(first, r"20\d\d-\d\d-\d\d")                          # no timestamps

    def test_check_reports_each_problem(self):
        with Workspace() as ws:
            good = new_feature(ws.root, "Good")
            text = ws.text(good.path)
            cases = {
                "no-meta.md": "# no metadata\n",
                "bad-yaml.md": "---\nfeature_id: [\n---\n",
                "bad-id.md": text.replace("FD-0001", "FD-12").replace('"Good"', '"Bad id"'),
                "bad-status.md": text.replace("FD-0001", "FD-0010").replace("investigating", "doing"),
                "no-section.md": text.replace("FD-0001", "FD-0011").replace("## 5. Downstream impact", "## 5. Impact"),
                "bad-table.md": text.replace("FD-0001", "FD-0012").replace(
                    "| Feature | Relationship | Reference | Evidence status |", "| Feature | Reference |"),
                "bad-deps.md": text.replace("FD-0001", "FD-0013").replace("depends_on: []", "depends_on: [FD-1, {id: FD-0001, x: 1}]"),
                "dupe.md": text,
            }
            for name, content in cases.items():
                (ws.root / "designs/features" / name).write_text(content, encoding="utf-8")
            messages = "\n".join(f"{p.path}: {p.message}" for p in workspace.check(ws.root))
            for expected in ("no-meta.md: no metadata block", "bad-yaml.md: metadata is not valid YAML",
                             "bad-id.md: feature_id must look like FD-0001", "bad-status.md: design_status must be one of",
                             "no-section.md: missing section heading '## 5. Downstream impact'",
                             "bad-table.md: the table under '### Related features'",
                             "bad-deps.md: depends_on[0] must be a feature ID", "bad-deps.md: depends_on[1] has unknown keys: x",
                             "dupe.md: duplicate feature_id FD-0001", "good.md: duplicate feature_id FD-0001",
                             "designs/index/feature-index.md: out of date"):
                self.assertIn(expected, messages)

    def test_diagram_and_evidence_folders_are_not_features(self):
        with Workspace() as ws:
            created = new_feature(ws.root, "Group feature", parent="grp")
            (ws.root / "designs/features/grp/diagrams").mkdir()
            shutil.copy(ws.root / "designs/templates/diagram.md", ws.root / "designs/features/grp/diagrams/proposed.md")
            (ws.root / "designs/features/grp/evidence").mkdir()
            (ws.root / "designs/features/grp/evidence/notes.md").write_text("notes\n", encoding="utf-8")
            self.assertEqual(workspace.check(ws.root), [])
            self.assertEqual([f.path for f in workspace.discover(ws.root)[0]], [created.path])

    def test_headings_inside_code_blocks_do_not_count(self):
        with Workspace() as ws:
            created = new_feature(ws.root, "Code")
            text = ws.text(created.path).replace("## 6. Acceptance criteria", "```\n## 6. Acceptance criteria\n```")
            (ws.root / created.path).write_text(text, encoding="utf-8")
            workspace.write_index(ws.root)
            self.assertIn("missing section heading '## 6. Acceptance criteria'",
                          "\n".join(p.message for p in workspace.check(ws.root)))


class CommandLine(unittest.TestCase):
    def test_new_feature_and_exit_codes(self):
        with Workspace() as ws:
            code, out, err = cmd(ws.root, "new", "feature", "--name", "Pipe road intersections")
            self.assertEqual((code, err), (0, ""))
            self.assertIn("created designs/features/pipe-road-intersections.md (FD-0001)", out)
            self.assertIn("nothing was staged, committed or pushed", out)
            self.assertEqual(cmd(ws.root, "check")[0], 0)
            self.assertEqual(cmd(ws.root, "index", "--check")[0], 0)
            code, _, err = cmd(ws.root, "new", "feature", "--name", "Pipe road intersections")
            self.assertEqual(code, 2)
            self.assertIn("already exists", err)
            (ws.root / "designs/features/broken.md").write_text("# x\n", encoding="utf-8")
            self.assertEqual(cmd(ws.root, "check")[0], 1)
            self.assertEqual(cmd(ws.root, "index", "--check")[0], 1)
            self.assertEqual(cmd(ws.root, "index")[0], 0)
            self.assertEqual(cmd(ws.root, "index", "--check")[0], 0)

    def test_prompts_when_interactive(self):
        with Workspace() as ws:
            answers = iter(["Prompted feature", ""])
            code, out, _ = cmd(ws.root, "new", "feature", ask=lambda q: next(answers), interactive=True)
            self.assertEqual(code, 0)
            self.assertIn("created designs/features/prompted-feature.md (FD-0001)", out)
            answers = iter(["Sub", "FD-0001"])
            code, out, err = cmd(ws.root, "new", "feature", "--convert-parent", ask=lambda q: next(answers),
                                 interactive=True)
            self.assertEqual(code, 0, err)
            self.assertIn("moved designs/features/prompted-feature.md -> designs/features/prompted-feature/README.md", out)

    def test_non_interactive_without_name_and_bad_usage(self):
        with Workspace() as ws:
            code, _, err = cmd(ws.root, "new", "feature", interactive=False)
            self.assertEqual(code, 2)
            self.assertIn("--name is required", err)
            self.assertEqual(cmd(ws.root, "new", "thing")[0], 2)
            self.assertEqual(cli.main(["check", "--root", str(ws.root.parent)], stdout=io.StringIO(),
                                      stderr=io.StringIO()), 2)                       # not a workspace

    def test_vs_code_task_passes_an_empty_parent(self):
        with Workspace() as ws:
            code, out, _ = cmd(ws.root, "new", "feature", "--name", "From task", "--parent", "")
            self.assertEqual(code, 0)
            self.assertIn("designs/features/from-task.md", out)


class GitSafety(unittest.TestCase):
    """The command never stages, commits, branches or pushes: everything under .git is
    byte-identical afterwards, and the new file is only an untracked working-tree change."""

    @staticmethod
    def snapshot(git_dir: Path):
        return {p.relative_to(git_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(git_dir.rglob("*")) if p.is_file()}

    def test_real_repository_state_is_unchanged(self):
        with Workspace(real_git=True) as ws:
            workspace.write_index(ws.root)
            ws.git("add", "-A"); ws.git("commit", "-q", "-m", "base")
            ws.git("remote", "add", "origin", "https://example.invalid/never-used.git")
            before = self.snapshot(ws.root / ".git")
            env = {**os.environ, "GIT_TRACE": "0"}
            r = subprocess.run([sys.executable, "-B", "-m", "tools.design", "new", "feature", "--name", "Safe one",
                                "--root", str(ws.root)], cwd=REPO_ROOT, capture_output=True, timeout=120, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            r = subprocess.run([sys.executable, "-B", "-m", "tools.design", "new", "feature", "--name", "Child",
                                "--parent", "FD-0001", "--convert-parent", "--root", str(ws.root)],
                               cwd=REPO_ROOT, capture_output=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(self.snapshot(ws.root / ".git"), before)                # nothing under .git changed
            status = ws.git("status", "--porcelain", "--untracked-files=all")
            self.assertEqual(sorted(status.splitlines()), [" M designs/index/feature-index.md",
                                                            "?? designs/features/safe-one/README.md",
                                                            "?? designs/features/safe-one/child.md"])
            self.assertEqual(ws.git("diff", "--cached", "--name-only"), "")         # nothing staged
            self.assertEqual(ws.git("branch", "--format=%(refname:short)").split(), ["main"])


class Purity(unittest.TestCase):
    BANNED_IMPORTS = {"subprocess", "socket", "http", "requests", "multiprocessing", "ctypes", "importlib", "shutil"}
    BANNED_ATTRS = {"system", "popen", "startfile", "execv", "spawnv"}

    def test_the_package_cannot_run_programs_or_use_the_network(self):
        for path in sorted(PACKAGE.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module or ""]
                else:
                    names = []
                for name in names:
                    with self.subTest(file=path.name, imports=name):
                        self.assertNotIn(name.split(".")[0], self.BANNED_IMPORTS)
                        self.assertNotEqual(name, "urllib.request")
                if isinstance(node, ast.Attribute):
                    with self.subTest(file=path.name, attr=node.attr):
                        self.assertNotIn(node.attr, self.BANNED_ATTRS)


class LinkRewriting(unittest.TestCase):
    def test_relative_targets_move_others_stay(self):
        text = ("[a](../../docs/x.md) [b](../README.md#ev) [c](https://e.x/y) [d](#local) [e](/root.md) "
                "[f](<../My Folder/z.md>) [g](./same.md \"title\")\n```\n[h](../../docs/x.md)\n```")
        got = workspace.rewrite_relative_links(text, "designs/features", "designs/features/grp")
        self.assertIn("[a](../../../docs/x.md)", got)
        self.assertIn("[b](../../README.md#ev)", got)
        self.assertIn("[c](https://e.x/y)", got)
        self.assertIn("[d](#local)", got)
        self.assertIn("[e](/root.md)", got)
        self.assertIn("[f](<../../My Folder/z.md>)", got)
        self.assertIn("[g](../same.md \"title\")", got)
        self.assertIn("```\n[h](../../docs/x.md)\n```", got)                      # code untouched


if __name__ == "__main__":
    unittest.main()
