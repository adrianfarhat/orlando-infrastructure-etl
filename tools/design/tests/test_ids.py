"""T-97 Phase 1, decision P1-A: IDs come from the working tree and the committed Git history,
so a retired ID is never reused; without a complete history nothing is allocated."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.design import ids, ownership, workspace
from tools.design.workspace import DesignError, new_feature
from tools.design.tests.test_design import GIT, Workspace, cmd


def commit(ws, message="c"):
    ws.git("add", "-A")
    ws.git("commit", "-q", "-m", message)


class FeatureIds(unittest.TestCase):
    def test_an_empty_repository_starts_at_FD_0001(self):
        """Existing T-94 behaviour: no commit yet, nothing retired."""
        with Workspace() as ws:
            self.assertEqual(new_feature(ws.root, "A").feature_id, "FD-0001")
            self.assertEqual(new_feature(ws.root, "B").feature_id, "FD-0002")

    def test_a_committed_and_deleted_highest_id_is_never_reused(self):
        with Workspace() as ws:
            new_feature(ws.root, "A"); b = new_feature(ws.root, "B")
            commit(ws)
            (ws.root / b.path).unlink(); commit(ws, "delete B")
            self.assertEqual(new_feature(ws.root, "C").feature_id, "FD-0003")

    def test_a_deleted_but_uncommitted_removal_still_counts(self):
        with Workspace() as ws:
            new_feature(ws.root, "A"); b = new_feature(ws.root, "B")
            commit(ws)
            (ws.root / b.path).unlink()                                  # deleted in the working tree only
            self.assertEqual(new_feature(ws.root, "C").feature_id, "FD-0003")

    def test_limitation_an_id_never_committed_can_be_allocated_again(self):
        """Documented limit: created and deleted without a commit, the ID left no record."""
        with Workspace() as ws:
            new_feature(ws.root, "A"); commit(ws)
            b = new_feature(ws.root, "B")
            (ws.root / b.path).unlink()
            self.assertEqual(new_feature(ws.root, "C").feature_id, "FD-0002")

    def test_an_id_committed_on_another_branch_is_not_reused(self):
        """Concurrent work that Git can see (local or fetched branches) is respected."""
        with Workspace() as ws:
            new_feature(ws.root, "A"); commit(ws)
            ws.git("checkout", "-q", "-b", "other")
            new_feature(ws.root, "On other branch"); commit(ws, "other")
            ws.git("checkout", "-q", "main")
            self.assertFalse((ws.root / "designs/features/on-other-branch.md").exists())
            self.assertEqual(new_feature(ws.root, "C").feature_id, "FD-0003")

    def test_concurrent_allocations_that_cannot_see_each_other_are_reported_as_duplicates(self):
        """Documented limit: two clones allocate the same number; check reports it when they meet."""
        with Workspace() as ws:
            new_feature(ws.root, "A"); commit(ws)
            ws.git("checkout", "-q", "-b", "left"); new_feature(ws.root, "Left"); commit(ws, "left")
            ws.git("checkout", "-q", "main"); ws.git("branch", "-D", "left")      # gone before the other side allocates
            ws.git("reflog", "expire", "--expire=now", "--all"); ws.git("gc", "-q", "--prune=now")
            right = new_feature(ws.root, "Right")
            self.assertEqual(right.feature_id, "FD-0002")                          # could not see "left"
            (ws.root / "designs/features/left.md").write_text(
                (ws.root / right.path).read_text(encoding="utf-8").replace("Right", "Left"), encoding="utf-8")
            code, out, _ = cmd(ws.root, "check")
            self.assertEqual(code, 1)
            self.assertIn("duplicate feature_id FD-0002", out)

    def test_existing_ids_are_never_renumbered(self):
        with Workspace() as ws:
            a = new_feature(ws.root, "A")
            text = (ws.root / a.path).read_text(encoding="utf-8").replace("FD-0001", "FD-0007")
            (ws.root / a.path).write_text(text, encoding="utf-8")
            dup = ws.root / "designs/features/dup.md"
            dup.write_text(text.replace('"A"', '"Dup"'), encoding="utf-8")
            before = {p: p.read_bytes() for p in (ws.root / a.path, dup)}
            cmd(ws.root, "index"); cmd(ws.root, "check")
            self.assertEqual({p: p.read_bytes() for p in before}, before)            # nothing renumbered
            with self.assertRaisesRegex(DesignError, "duplicate feature IDs must be fixed first"):
                new_feature(ws.root, "B")


class IncompleteHistory(unittest.TestCase):
    def test_not_a_git_repository_creates_nothing(self):
        with Workspace() as ws:
            shutil.rmtree(ws.root / ".git"); (ws.root / ".git").mkdir()          # a marker, not a repository
            code, _, err = cmd(ws.root, "new", "feature", "--name", "A", interactive=False)
            self.assertEqual(code, 2)
            self.assertIn("cannot allocate a new ID safely", err)
            self.assertIn("not a Git working tree", err)
            self.assertFalse((ws.root / "designs/features").exists())

    def test_a_shallow_clone_creates_nothing(self):
        with Workspace() as ws:
            new_feature(ws.root, "A"); commit(ws, "one")
            new_feature(ws.root, "B"); commit(ws, "two")
            with tempfile.TemporaryDirectory() as tmp:
                clone = Path(tmp) / "clone"
                subprocess.run(GIT + ["clone", "-q", "--depth", "1", (ws.root).as_uri(), str(clone)],
                               check=True, capture_output=True, timeout=60)
                before = sorted(p.name for p in (clone / "designs/features").iterdir())
                with self.assertRaisesRegex(DesignError, "shallow.*git fetch --unshallow"):
                    new_feature(clone, "C")
                self.assertEqual(sorted(p.name for p in (clone / "designs/features").iterdir()), before)

    def test_git_not_installed_creates_nothing(self):
        with Workspace() as ws:
            with mock.patch("tools.design.ids.subprocess.run", side_effect=FileNotFoundError):
                with self.assertRaisesRegex(DesignError, "Git is not installed"):
                    new_feature(ws.root, "A")
            self.assertFalse((ws.root / "designs/features").exists())

    def test_a_failing_git_log_creates_nothing(self):
        with Workspace() as ws:
            new_feature(ws.root, "A"); commit(ws)
            real = subprocess.run

            def fail_log(args, **kw):
                if "log" in args:
                    return subprocess.CompletedProcess(args, 128, b"", b"fatal: bad object")
                return real(args, **kw)
            with mock.patch("tools.design.ids.subprocess.run", side_effect=fail_log):
                with self.assertRaisesRegex(DesignError, "`git log` failed"):
                    new_feature(ws.root, "B")
            self.assertFalse((ws.root / "designs/features/b.md").exists())


class DiagramIds(unittest.TestCase):
    def test_numbers_are_per_owner_and_never_reused(self):
        with Workspace() as ws:
            new_feature(ws.root, "A"); new_feature(ws.root, "B")
            d1 = ownership.new_diagram(ws.root, "FD-0001", "First")
            d2 = ownership.new_diagram(ws.root, "FD-0001", "Second")
            other = ownership.new_diagram(ws.root, "FD-0002", "Other")
            self.assertEqual((d1.diagram_id, d2.diagram_id, other.diagram_id), ("FD-0001-D1", "FD-0001-D2", "FD-0002-D1"))
            commit(ws)
            (ws.root / d2.path).unlink(); commit(ws, "retire D2")
            self.assertEqual(ownership.new_diagram(ws.root, "FD-0001", "Third").diagram_id, "FD-0001-D3")

    def test_a_retired_diagram_id_proves_its_feature_number_was_used(self):
        self.assertEqual(ids.next_feature_id(["FD-0001"], {"FD-0004-D2"}), "FD-0005")


class MergedSideBranches(unittest.TestCase):
    """QA D1: IDs that only ever existed on a merged side branch are retired too."""

    def test_an_id_added_and_removed_on_a_merged_pr_branch(self):
        with Workspace() as ws:
            new_feature(ws.root, "A"); commit(ws, "A")
            ws.git("checkout", "-q", "-b", "pr")
            b = new_feature(ws.root, "B"); commit(ws, "add B")                       # FD-0002 on the branch only
            (ws.root / b.path).unlink(); cmd(ws.root, "index"); commit(ws, "drop B")
            ws.git("checkout", "-q", "main")
            (ws.root / "designs/other.md").write_text("main moved on\n", encoding="utf-8"); commit(ws, "main")
            ws.git("merge", "-q", "--no-ff", "-m", "Merge pull request", "pr"); ws.git("branch", "-D", "pr")
            self.assertIn("FD-0002", ids.committed_ids(ws.root))
            self.assertEqual(new_feature(ws.root, "C").feature_id, "FD-0003")

    def test_an_id_on_a_branch_merged_with_strategy_ours(self):
        with Workspace() as ws:
            new_feature(ws.root, "A"); commit(ws, "A")
            ws.git("checkout", "-q", "-b", "side")
            new_feature(ws.root, "B"); commit(ws, "add B")
            ws.git("checkout", "-q", "main")
            ws.git("merge", "-q", "-s", "ours", "-m", "keep main", "side"); ws.git("branch", "-D", "side")
            self.assertFalse((ws.root / "designs/features/b.md").exists())
            self.assertIn("FD-0002", ids.committed_ids(ws.root))
            self.assertEqual(new_feature(ws.root, "C").feature_id, "FD-0003")


class GitEnvironment(unittest.TestCase):
    def test_inherited_git_variables_cannot_redirect_the_scan(self):
        with Workspace() as ws, tempfile.TemporaryDirectory() as other:
            new_feature(ws.root, "A"); commit(ws)
            subprocess.run(GIT + ["init", "-q", other], check=True, capture_output=True)
            with mock.patch.dict("os.environ", {"GIT_DIR": str(Path(other) / ".git"), "GIT_WORK_TREE": other}):
                self.assertEqual(ids.committed_ids(ws.root), {"FD-0001"})


class HistoryParsing(unittest.TestCase):
    def test_metadata_lines_in_any_quoting_with_comments(self):
        with Workspace() as ws:
            d = ws.root / "designs/features/diagrams"; d.mkdir(parents=True)
            (d / "x.md").write_text('---\ndiagram_id: "FD-0002-D3"   # note\nfeature_id: \'FD-0002\'\n---\n', encoding="utf-8")
            (ws.root / "designs/features/y.md").write_text("---\nfeature_id: FD-0005\n---\n", encoding="utf-8")
            commit(ws)
            self.assertEqual(ids.committed_ids(ws.root), {"FD-0002-D3", "FD-0002", "FD-0005"})

    def test_ids_in_prose_are_not_allocations(self):
        with Workspace() as ws:
            (ws.root / "designs/notes.md").write_text("See FD-0042 and feature_id FD-0043 in text.\n", encoding="utf-8")
            commit(ws)
            self.assertEqual(ids.committed_ids(ws.root), set())


if __name__ == "__main__":
    unittest.main()
