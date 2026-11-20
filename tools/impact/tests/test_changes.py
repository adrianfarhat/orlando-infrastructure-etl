"""Stage 83b-1: Git change detection (tools/impact/changes.py), on throwaway repositories."""

import hashlib
import time
import unittest
import unittest.mock
from pathlib import Path

from tools.impact import changes
from tools.impact.changes import Change, ChangedLines, changed_lines, collect, parse_name_status, parse_unified_diff
from tools.impact.gitfiles import GitError

from .support import TempRepo


def lines(n: int, tag: str = "line") -> str:
    return "".join(f"{tag} {i}\n" for i in range(n))


def base_repo() -> TempRepo:
    repo = TempRepo()
    repo.write("a.txt", lines(40))
    repo.write("docs/readme.md", "# readme\n")
    repo.write("keep.txt", lines(40, "keep"))
    repo.write(".gitignore", "*.log\n")
    repo.add_all()
    repo.commit("base")
    return repo


def summary(cs) -> dict:
    return {c.path: (c.kind, c.origins, c.old_path) for c in cs.changes}


def snapshot(root: Path) -> dict:
    """Content hash of every file, including .git (to prove nothing is written)."""
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


class CollectTests(unittest.TestCase):
    def test_clean_tree_has_no_changes(self):
        with base_repo() as repo:
            self.assertEqual(collect(repo.root).changes, ())
            cs = collect(repo.root, base="main")
            self.assertEqual(cs.changes, ())
            self.assertEqual(cs.baseline, cs.head)

    def test_each_local_origin(self):
        with base_repo() as repo:
            repo.write("new_staged.txt", "s\n")
            repo.git("add", "new_staged.txt")
            repo.write("a.txt", lines(40) + "staged edit\n")
            repo.git("add", "a.txt")
            repo.write("keep.txt", lines(40, "keep") + "unstaged edit\n")
            repo.git("rm", "-q", "docs/readme.md")
            repo.write("brand/new/untracked.md", "u\n")
            repo.write("ignored.log", "ignored\n")
            self.assertEqual(summary(collect(repo.root)), {
                "a.txt": ("modified", ("staged",), None),
                "brand/new/untracked.md": ("added", ("untracked",), None),
                "docs/readme.md": ("deleted", ("staged",), None),
                "keep.txt": ("modified", ("unstaged",), None),
                "new_staged.txt": ("added", ("staged",), None),
            })

    def test_unstaged_deletion(self):
        with base_repo() as repo:
            (repo.root / "keep.txt").unlink()
            self.assertEqual(summary(collect(repo.root)), {"keep.txt": ("deleted", ("unstaged",), None)})

    def test_committed_changes_need_base_and_carry_all_origins(self):
        with base_repo() as repo:
            repo.git("checkout", "-q", "-b", "feature")
            repo.write("a.txt", lines(40) + "committed\n")
            repo.write("added_on_branch.txt", "x\n")
            repo.add_all()
            repo.commit("branch work")
            repo.write("a.txt", lines(40) + "committed\nand unstaged\n")
            self.assertEqual(summary(collect(repo.root)), {"a.txt": ("modified", ("unstaged",), None)})
            self.assertEqual(summary(collect(repo.root, base="main")), {
                "a.txt": ("modified", ("committed", "unstaged"), None),
                "added_on_branch.txt": ("added", ("committed",), None),
            })

    def test_base_uses_the_merge_base(self):
        with base_repo() as repo:
            repo.git("checkout", "-q", "-b", "feature")
            repo.write("f.txt", "f\n"); repo.add_all(); repo.commit("feature")
            repo.git("checkout", "-q", "main")
            repo.write("m.txt", "m\n"); repo.add_all(); repo.commit("main moves on")
            repo.git("checkout", "-q", "feature")
            cs = collect(repo.root, base="main")
            self.assertEqual(summary(cs), {"f.txt": ("added", ("committed",), None)})   # m.txt is not ours

    def test_renames_keep_old_and_new_paths(self):
        with base_repo() as repo:
            repo.git("checkout", "-q", "-b", "feature")
            (repo.root / "moved").mkdir()
            repo.git("mv", "a.txt", "moved/a2.txt")
            repo.commit("rename")
            cs = collect(repo.root, base="main")
            self.assertEqual(summary(cs), {"moved/a2.txt": ("renamed", ("committed",), "a.txt")})
            self.assertEqual(cs.changes[0].removed_paths, ("a.txt",))
            repo.git("mv", "keep.txt", "kept.txt")                         # a staged rename
            self.assertEqual(summary(collect(repo.root))["kept.txt"], ("renamed", ("staged",), "keep.txt"))

    def test_rename_chain_reports_the_baseline_path(self):
        with base_repo() as repo:
            repo.git("checkout", "-q", "-b", "feature")
            repo.git("mv", "a.txt", "b.txt"); repo.commit("a->b")
            repo.git("mv", "b.txt", "c.txt")                                # staged b -> c
            self.assertEqual(summary(collect(repo.root, base="main")),
                             {"c.txt": ("renamed", ("committed", "staged"), "a.txt")})

    def test_heavily_edited_rename_is_delete_plus_add(self):
        with base_repo() as repo:
            repo.git("mv", "a.txt", "z.txt")
            repo.write("z.txt", lines(40, "completely different"))
            repo.git("add", "z.txt")
            self.assertEqual(summary(collect(repo.root)), {
                "a.txt": ("deleted", ("staged",), None),
                "z.txt": ("added", ("staged",), None),
            })

    def test_copy_detection(self):
        with base_repo() as repo:
            repo.write("b.txt", lines(40))                                   # copy of a.txt
            repo.write("a.txt", lines(40) + "source edited\n")
            repo.add_all()
            self.assertEqual(summary(collect(repo.root)), {
                "a.txt": ("modified", ("staged",), None),
                "b.txt": ("copied", ("staged",), "a.txt"),
            })

    def test_removed_from_index_but_kept_on_disk_is_modified(self):
        with base_repo() as repo:
            repo.git("rm", "-q", "--cached", "keep.txt")
            self.assertEqual(summary(collect(repo.root)),
                             {"keep.txt": ("modified", ("staged", "untracked"), None)})

    def test_added_then_removed_again_is_no_change(self):
        with base_repo() as repo:
            repo.write("temp.txt", "t\n")
            repo.git("add", "temp.txt")
            (repo.root / "temp.txt").unlink()
            self.assertEqual(collect(repo.root).changes, ())

    def test_unusual_names(self):
        with base_repo() as repo:
            for name in ("with space.md", "résumé/日本.md", "web/app/api/[id]/route.ts"):
                repo.write(name, "x\n")
            repo.git("add", "with space.md")
            got = summary(collect(repo.root))
            self.assertEqual(got["with space.md"], ("added", ("staged",), None))
            self.assertEqual(got["résumé/日本.md"], ("added", ("untracked",), None))
            self.assertEqual(got["web/app/api/[id]/route.ts"], ("added", ("untracked",), None))

    def test_unborn_branch(self):
        with TempRepo() as repo:
            repo.write("first.txt", "1\n")
            repo.git("add", "first.txt")
            repo.write("loose.txt", "2\n")
            cs = collect(repo.root)
            self.assertIsNone(cs.head)
            self.assertEqual(summary(cs), {"first.txt": ("added", ("staged",), None),
                                           "loose.txt": ("added", ("untracked",), None)})
            with self.assertRaisesRegex(GitError, "at least one commit"):
                collect(repo.root, base="main")

    def test_bad_base_references(self):
        with base_repo() as repo:
            for bad in ("no-such-branch", "", "   ", "main~99"):
                with self.subTest(base=bad):
                    with self.assertRaises(GitError):
                        collect(repo.root, base=bad)
            for option_like in ("--output=pwned.txt", "-h"):
                with self.subTest(base=option_like):
                    with self.assertRaises(GitError):
                        collect(repo.root, base=option_like)
            self.assertFalse((repo.root / "pwned.txt").exists())

    def test_unrelated_history_has_no_merge_base(self):
        with base_repo() as repo:
            repo.git("checkout", "-q", "--orphan", "island")
            repo.git("rm", "-q", "-r", "--cached", ".")
            repo.write("island.txt", "i\n")
            repo.git("add", "island.txt")
            repo.commit("unrelated")
            with self.assertRaisesRegex(GitError, "no common ancestor"):
                collect(repo.root, base="main")

    def test_deterministic_and_read_only(self):
        with base_repo() as repo:
            repo.git("checkout", "-q", "-b", "feature")
            repo.git("mv", "a.txt", "b.txt"); repo.commit("r")
            repo.write("keep.txt", lines(40, "keep") + "x\n")
            repo.write("u.md", "u\n")
            before = snapshot(repo.root)
            first = collect(repo.root, base="main")
            for change in first.changes:
                changed_lines(first, change)
            second = collect(repo.root, base="main")
            self.assertEqual(first.changes, second.changes)
            self.assertEqual([c.path for c in first.changes], sorted(c.path for c in first.changes))
            self.assertEqual(snapshot(repo.root), before)                  # .git included: nothing written


class ParseTests(unittest.TestCase):
    def test_name_status_parsing(self):
        data = b"M\0a.txt\0R087\0old name.md\0new\\name.md\0C100\0src.py\0dst.py\0D\0gone.txt\0A\0[id].ts\0"
        parsed, bad = parse_name_status(data)
        self.assertEqual(parsed, [("M", "a.txt", None), ("R", "new\\name.md", "old name.md"),
                                  ("C", "dst.py", "src.py"), ("D", "gone.txt", None), ("A", "[id].ts", None)])
        self.assertEqual(bad, [])

    def test_unsupported_names_are_reported_not_fatal(self):
        data = b"A\0tab\there.py\0M\0bad\xff.py\0A\0ok.py\0R100\0ok_old.py\0new\nline.py\0"
        parsed, bad = parse_name_status(data)
        self.assertEqual(parsed, [("A", "ok.py", None)])
        self.assertEqual(len(bad), 3)

    def test_unusable_old_name_keeps_the_new_path_as_added(self):
        parsed, bad = parse_name_status(b"R100\0old\tname.py\0new.py\0")
        self.assertEqual(parsed, [("A", "new.py", None)])
        self.assertEqual(len(bad), 1)

    def test_truncated_output_is_a_git_error(self):
        for data in (b"M\0", b"R100\0only-old\0"):
            with self.subTest(data=data):
                with self.assertRaises(GitError):
                    parse_name_status(data)

    def test_unified_diff_parsing(self):
        data = (b"diff --git a/x b/x\nindex 1..2 100644\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\r\n+new\r\n"
                b"@@ -5,0 +6,2 @@\n+++plus\n+--dashes\n\\ No newline at end of file\n"
                b"diff --git a/y b/y\n--- a/y\n+++ b/y\n@@ -1 +0,0 @@\n---gone\n")
        self.assertEqual(parse_unified_diff(data),
                         ChangedLines(("new", "++plus", "--dashes"), ("old", "--gone"), True))

    def test_binary_markers(self):
        for data in (b"diff --git a/x b/x\nBinary files a/x and b/x differ\n",
                     b"diff --git a/x b/x\nGIT binary patch\nliteral 3\n"):
            with self.subTest(data=data[:40]):
                result = parse_unified_diff(data)
                self.assertEqual((result.scanned, result.reason), (False, "binary file"))


class ChangedLinesTests(unittest.TestCase):
    def lines_of(self, repo, path, base=None) -> ChangedLines:
        cs = collect(repo.root, base=base)
        return changed_lines(cs, cs.by_path()[path])

    def test_modified_file_added_and_removed_lines(self):
        with base_repo() as repo:
            text = lines(40).replace("line 3\n", "line three DATABASE_URL\n") + "appended\n"
            repo.write("a.txt", text)
            got = self.lines_of(repo, "a.txt")
            self.assertTrue(got.scanned)
            self.assertEqual(got.added, ("line three DATABASE_URL", "appended"))
            self.assertEqual(got.removed, ("line 3",))
            self.assertIn("DATABASE_URL", got.text)

    def test_crlf_is_stripped(self):
        with base_repo() as repo:
            # The tool follows git's own line-ending settings; with core.autocrlf=true git
            # treats a CRLF copy as unchanged. Turn it off here to create a real CRLF change.
            repo.git("config", "core.autocrlf", "false")
            repo.write("a.txt", lines(40).replace("\n", "\r\n") + "new\r\n")
            got = self.lines_of(repo, "a.txt")
            self.assertTrue(got.scanned)
            self.assertIn("new", got.added)
            self.assertTrue(all(not line.endswith("\r") for line in got.added + got.removed))

    def test_line_endings_follow_git_settings(self):
        with base_repo() as repo:
            repo.git("config", "core.autocrlf", "true")
            repo.write("a.txt", lines(40).replace("\n", "\r\n"))             # only line endings differ
            self.assertNotIn("a.txt", collect(repo.root).by_path())

    def test_deleted_file_lines_are_removed_lines(self):
        with base_repo() as repo:
            (repo.root / "docs" / "readme.md").unlink()
            got = self.lines_of(repo, "docs/readme.md")
            self.assertEqual((got.added, got.removed), ((), ("# readme",)))

    def test_untracked_file_lines_are_added_lines(self):
        with base_repo() as repo:
            repo.write("new.py", "import os\nURL = os.environ['DATABASE_URL']\n")
            got = self.lines_of(repo, "new.py")
            self.assertEqual(got.added, ("import os", "URL = os.environ['DATABASE_URL']"))

    def test_rename_reports_only_the_edited_lines(self):
        with base_repo() as repo:
            repo.git("mv", "a.txt", "renamed.txt")
            repo.write("renamed.txt", lines(40) + "one more\n")
            got = self.lines_of(repo, "renamed.txt")
            self.assertEqual((got.added, got.removed), (("one more",), ()))

    def test_copy_lines_are_relative_to_the_source(self):
        with base_repo() as repo:
            repo.write("b.txt", lines(40) + "copy extra\n")
            repo.write("a.txt", lines(40) + "source edited\n")
            repo.add_all()
            got = self.lines_of(repo, "b.txt")
            self.assertEqual(got.added, ("copy extra",))                    # not "source edited"

    def test_removed_from_index_but_edited_on_disk(self):
        with base_repo() as repo:
            repo.git("rm", "-q", "--cached", "keep.txt")
            repo.write("keep.txt", lines(40, "keep") + "edited\n")
            got = self.lines_of(repo, "keep.txt")
            self.assertEqual((got.added, got.removed), (("edited",), ()))

    def test_binary_files_are_not_scanned(self):
        with base_repo() as repo:
            repo.write("blob.bin", b"\x00\x01binary DATABASE_URL")
            got = self.lines_of(repo, "blob.bin")                            # untracked
            self.assertEqual((got.scanned, got.reason, got.added), (False, "binary file", ()))
            repo.git("add", "blob.bin")
            got = self.lines_of(repo, "blob.bin")                            # tracked: git says binary
            self.assertEqual((got.scanned, got.reason), (False, "binary file"))

    def test_gitattributes_binary_text_is_not_scanned(self):
        with base_repo() as repo:
            repo.write(".gitattributes", "*.dat binary\n")
            repo.write("x.dat", "plain text DATABASE_URL\n")
            repo.add_all()
            got = self.lines_of(repo, "x.dat")
            self.assertFalse(got.scanned)

    def test_large_files_are_not_scanned(self):
        with base_repo() as repo:
            repo.write("huge.txt", "x" * (changes.MAX_FILE_BYTES + 1))
            got = self.lines_of(repo, "huge.txt")
            self.assertFalse(got.scanned)
            self.assertIn("larger than", got.reason)
            repo.git("add", "huge.txt"); repo.commit("huge")
            (repo.root / "huge.txt").unlink()                               # previous version too large
            got = self.lines_of(repo, "huge.txt")
            self.assertFalse(got.scanned)
            self.assertIn("previous version is larger", got.reason)

    def test_copy_comparison_of_a_40000_line_file_finishes_quickly(self):
        with base_repo() as repo:
            big = lines(40_000)
            repo.write("a.txt", big); repo.add_all(); repo.commit("big")
            repo.write("copy.txt", big.replace("line 20000\n", "changed\n"))
            repo.write("a.txt", big + "x\n")
            repo.add_all()
            cs = collect(repo.root)
            self.assertEqual(cs.by_path()["copy.txt"].kind, "copied")
            start = time.perf_counter()
            got = changed_lines(cs, cs.by_path()["copy.txt"])
            self.assertLess(time.perf_counter() - start, 10.0)
            self.assertIn("changed", got.added)


class QaRoundOneRegressions(unittest.TestCase):
    """Independent QA of stage 83b-1: defects and missing cases."""

    def lines_of(self, repo, path, base=None) -> ChangedLines:
        cs = collect(repo.root, base=base)
        return changed_lines(cs, cs.by_path()[path])

    def test_gitattributes_binary_applies_to_untracked_and_copied_files(self):
        with base_repo() as repo:
            repo.write(".gitattributes", "*.dat binary\n*.nd -diff\n")
            repo.git("add", ".gitattributes"); repo.commit("attributes")
            repo.write("untracked.dat", "plain text DATABASE_URL\n")
            repo.write("untracked.nd", "plain text DATABASE_URL\n")
            for name in ("untracked.dat", "untracked.nd"):
                with self.subTest(name=name):
                    got = self.lines_of(repo, name)
                    self.assertEqual((got.scanned, got.reason, got.added),
                                     (False, "binary file (.gitattributes)", ()))
            repo.write("plain.txt", "plain text\n")                          # control: still scanned
            self.assertTrue(self.lines_of(repo, "plain.txt").scanned)

    def test_rename_then_delete_keeps_every_origin(self):
        with base_repo() as repo:
            repo.git("mv", "keep.txt", "moved.txt")                          # staged rename
            (repo.root / "moved.txt").unlink()                               # unstaged delete
            self.assertEqual(summary(collect(repo.root)),
                             {"keep.txt": ("deleted", ("staged", "unstaged"), None)})

    def test_nested_repository_is_reported_with_a_clear_reason(self):
        import subprocess
        with base_repo() as repo:
            (repo.root / "inner").mkdir()
            subprocess.run(["git", "-C", str(repo.root / "inner"), "init", "-q"], check=True, capture_output=True)
            (repo.root / "inner" / "f.txt").write_text("x")
            cs = collect(repo.root)
            self.assertEqual([(u.shown, u.reason) for u in cs.unsupported],
                             [("inner/", "nested Git repository (its files are not analysed)")])
            self.assertNotIn("inner/", cs.by_path())

    def test_size_limit_boundaries(self):
        with base_repo() as repo:
            repo.write("exact.txt", "x" * changes.MAX_FILE_BYTES)
            repo.write("over.txt", "x" * (changes.MAX_FILE_BYTES + 1))
            self.assertTrue(self.lines_of(repo, "exact.txt").scanned)
            self.assertFalse(self.lines_of(repo, "over.txt").scanned)

    def test_diff_output_limit(self):
        with base_repo() as repo:
            repo.write("a.txt", lines(40) + "more\n")
            with unittest.mock.patch.object(changes, "MAX_DIFF_BYTES", 10):
                got = self.lines_of(repo, "a.txt")
            self.assertEqual((got.scanned, got.added), (False, ()))
            self.assertIn("diff is larger than 10 bytes", got.reason)

    def test_invalid_utf8_content_is_decoded_with_replacement(self):
        with base_repo() as repo:
            repo.write("a.txt", lines(40).encode() + b"bad \xff byte\n")
            got = self.lines_of(repo, "a.txt")
            self.assertEqual(got.added, ("bad � byte",))

    def test_option_like_file_names(self):
        with base_repo() as repo:
            for name in ("--output=x", "-h"):
                repo.write(name, "x\n")
            repo.add_all()
            got = summary(collect(repo.root))
            self.assertEqual(got["--output=x"], ("added", ("staged",), None))
            self.assertEqual(self.lines_of(repo, "--output=x").added, ("x",))
            self.assertFalse((repo.root / "x").exists())

    def test_detached_head(self):
        with base_repo() as repo:
            repo.git("checkout", "-q", "--detach", "HEAD")
            repo.write("a.txt", lines(40) + "x\n")
            self.assertEqual(summary(collect(repo.root)), {"a.txt": ("modified", ("unstaged",), None)})
            self.assertEqual(collect(repo.root, base="main").changes, collect(repo.root).changes)

    def test_merge_conflict_is_modified_and_does_not_crash(self):
        with base_repo() as repo:
            repo.git("checkout", "-q", "-b", "other")
            repo.write("a.txt", "other side\n"); repo.add_all(); repo.commit("other")
            repo.git("checkout", "-q", "main")
            repo.write("a.txt", "main side\n"); repo.add_all(); repo.commit("main")
            import subprocess
            subprocess.run(["git", "-C", str(repo.root), "merge", "-q", "other"], capture_output=True)
            cs = collect(repo.root)
            self.assertEqual(cs.by_path()["a.txt"].kind, "modified")
            self.assertTrue(any("<<<<<<<" in line for line in changed_lines(cs, cs.by_path()["a.txt"]).added))

    def test_repository_configured_diff_programs_are_not_run(self):
        """diff.external, textconv and an fsmonitor hook must not run. Control: a plain
        `git diff` in the same repository DOES run diff.external."""
        import subprocess
        with base_repo() as repo:
            markers = {k: repo.root.parent / f"marker-{k}" for k in ("external", "textconv", "fsmonitor", "control")}
            hook = repo.root.parent / "fsmonitor-hook.sh"
            hook.write_text(f"#!/bin/sh\ntouch '{markers['fsmonitor'].as_posix()}'\n")
            hook.chmod(0o755)
            repo.git("config", "diff.external", f"touch '{markers['external'].as_posix()}' #")
            repo.git("config", "diff.ev.textconv", f"touch '{markers['textconv'].as_posix()}'; cat")
            repo.git("config", "core.fsmonitor", hook.as_posix())
            repo.write(".gitattributes", "*.txt diff=ev\n")
            repo.write("a.txt", lines(40) + "edit\n")
            repo.write("new.txt", "n\n")
            cs = collect(repo.root, base=None)
            for change in cs.changes:
                changed_lines(cs, change)
            for kind in ("external", "textconv", "fsmonitor"):
                with self.subTest(program=kind):
                    self.assertFalse(markers[kind].exists())
            # Control: plain git does run the configured external diff program.
            subprocess.run(["git", "-C", str(repo.root), "-c",
                            f"diff.external=touch '{markers['control'].as_posix()}' #", "diff"],
                           capture_output=True, timeout=60)
            self.assertTrue(markers["control"].exists())


class ContentFilterException(unittest.TestCase):
    """The documented exception to the no-external-programs statement: Git content
    filters (as used by Git LFS) defined in Git configuration run when the file's
    attributes select them, exactly as for `git diff`. Nothing else runs."""

    def setup_filter(self, repo, attributes: str):
        marker = repo.root.parent / "marker-clean-filter"
        repo.git("config", "filter.mark.clean", f"touch '{marker.as_posix()}'; cat")
        repo.git("config", "filter.mark.smudge", "cat")
        repo.write(".gitattributes", attributes)
        repo.git("add", ".gitattributes"); repo.commit("attributes")
        return marker

    def run_tool(self, repo):
        cs = collect(repo.root)
        return cs, {c.path: changed_lines(cs, c) for c in cs.changes}

    def test_a_configured_filter_selected_by_attributes_runs_and_results_stay_correct(self):
        with base_repo() as repo:
            marker = self.setup_filter(repo, "*.f filter=mark\n")
            repo.write("data.f", "one\n"); repo.git("add", "data.f"); repo.commit("data")
            marker.unlink(missing_ok=True)                                    # ignore the setup's own runs
            repo.write("data.f", "one\ntwo\n")
            cs, got = self.run_tool(repo)
            self.assertTrue(marker.exists())                                  # documented exception
            self.assertEqual(cs.by_path()["data.f"].kind, "modified")
            self.assertEqual(got["data.f"].added, ("two",))                  # results as git sees them

    def test_a_configured_filter_not_selected_by_attributes_does_not_run(self):
        with base_repo() as repo:
            marker = self.setup_filter(repo, "*.other filter=mark\n")
            marker.unlink(missing_ok=True)
            repo.write("a.txt", lines(40) + "edit\n")
            repo.write("new.txt", "n\n")
            self.run_tool(repo)
            self.assertFalse(marker.exists())

    def test_an_attribute_naming_an_undefined_filter_runs_nothing(self):
        with base_repo() as repo:
            repo.write(".gitattributes", "*.txt filter=nosuchdriver\n")
            repo.git("add", ".gitattributes"); repo.commit("attributes")
            repo.write("a.txt", lines(40) + "edit\n")
            cs, got = self.run_tool(repo)
            self.assertEqual(got["a.txt"].added, ("edit",))


class PartialCloneSafety(unittest.TestCase):
    """Lazy fetching is disabled: in a blob-less partial clone a missing old version is
    reported as not scanned, and no transport or credential program starts. Uses only a
    local file:// remote (no network)."""

    @classmethod
    def setUpClass(cls):
        import subprocess
        import tempfile
        from .support import GIT
        cls._tmp = tempfile.TemporaryDirectory(prefix="impact-partial-")
        tmp = Path(cls._tmp.name)
        cls.src, cls.dst = tmp / "src", tmp / "dst"
        cls.transport_marker = tmp / "marker-transport"
        cls.credential_marker = tmp / "marker-credential"

        def git(root, *args):
            subprocess.run(GIT + ["-C", str(root), *args], check=True, capture_output=True, timeout=60)

        cls.src.mkdir()
        git(cls.src, "init", "-q")
        git(cls.src, "config", "uploadpack.allowFilter", "true")
        (cls.src / "a.txt").write_text("v1\n" + "same\n" * 20)
        (cls.src / "b.txt").write_text("rename me\n" + "body\n" * 20)
        git(cls.src, "add", "-A"); git(cls.src, "commit", "-q", "-m", "one"); git(cls.src, "tag", "old")
        (cls.src / "a.txt").write_text("v2\n" + "same\n" * 20)
        git(cls.src, "mv", "b.txt", "c.txt"); git(cls.src, "commit", "-q", "-am", "two")
        subprocess.run(GIT + ["clone", "-q", "--filter=blob:none", f"file:///{cls.src.as_posix()}", str(cls.dst)],
                       check=True, capture_output=True, timeout=60)
        git(cls.dst, "config", "remote.origin.uploadpack", f"touch '{cls.transport_marker.as_posix()}' && git-upload-pack")
        git(cls.dst, "config", "credential.helper", f"!touch '{cls.credential_marker.as_posix()}' #")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        for marker in (self.transport_marker, self.credential_marker):
            marker.unlink(missing_ok=True)

    def test_missing_objects_are_not_scanned_and_nothing_is_fetched(self):
        cs = collect(self.dst, base="old")
        got = {c.path: (c.kind, c.old_path) for c in cs.changes}
        self.assertEqual(got, {"a.txt": ("modified", None), "c.txt": ("renamed", "b.txt")})
        # a.txt: its old version is a missing object -> not scanned, never "no change".
        missing = changed_lines(cs, cs.by_path()["a.txt"])
        self.assertEqual((missing.scanned, missing.added, missing.removed, missing.reason),
                         (False, (), (), changes.MISSING_OBJECT))
        # c.txt: an identical-content rename; its old version is the same object as the
        # checked-out file, which IS present, so it is genuinely scanned (no changed lines).
        present = changed_lines(cs, cs.by_path()["c.txt"])
        self.assertEqual((present.scanned, present.added, present.removed), (True, (), ()))
        self.assertFalse(self.transport_marker.exists())                      # no transport program
        self.assertFalse(self.credential_marker.exists())                     # no credential helper

    def test_the_missing_object_was_really_missing_and_is_still_missing(self):
        from tools.impact import gitfiles
        r = gitfiles.git_status(self.dst, "cat-file", "-e", "old:a.txt")
        self.assertNotEqual(r.returncode, 0)                                  # never fetched by the tool
        self.assertFalse(self.transport_marker.exists())

    def test_control_plain_git_would_fetch(self):
        """Without GIT_NO_LAZY_FETCH, plain git starts the transport for the same object,
        so the tests above prove the protection, not an absent mechanism. Runs last-safe:
        it uses a fresh clone so the fetched object cannot affect the other tests."""
        import subprocess
        import tempfile
        from .support import GIT
        with tempfile.TemporaryDirectory(prefix="impact-partial-control-") as tmp:
            dst = Path(tmp) / "dst"
            subprocess.run(GIT + ["clone", "-q", "--filter=blob:none", f"file:///{self.src.as_posix()}", str(dst)],
                           check=True, capture_output=True, timeout=60)
            marker = Path(tmp) / "marker"
            subprocess.run(GIT + ["-C", str(dst), "config", "remote.origin.uploadpack",
                                  f"touch '{marker.as_posix()}' && git-upload-pack"], check=True, capture_output=True)
            subprocess.run(GIT + ["-C", str(dst), "cat-file", "-s", "old:a.txt"], capture_output=True, timeout=60)
            self.assertTrue(marker.exists())

    def test_every_git_call_carries_the_setting(self):
        import subprocess
        from tools.impact import gitfiles
        ok = subprocess.CompletedProcess(["git"], 0, b"", b"")
        with unittest.mock.patch("tools.impact.gitfiles.subprocess.run", return_value=ok) as run:
            gitfiles.run_git(Path("repo"), "status")
            gitfiles.git_status(Path("repo"), "rev-parse", "HEAD")
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["env"]["GIT_NO_LAZY_FETCH"], "1")


class SubmoduleWording(unittest.TestCase):
    def test_submodule_change_is_reported_as_a_submodule(self):
        import subprocess
        from .support import GIT
        with base_repo() as repo:
            inner = repo.root.parent / "inner"
            inner.mkdir()
            run = lambda root, *a: subprocess.run(GIT + ["-C", str(root), *a], check=True, capture_output=True,
                                                  timeout=60)
            run(inner, "init", "-q")
            (inner / "x.txt").write_text("x\n"); run(inner, "add", "-A"); run(inner, "commit", "-q", "-m", "x")
            run(repo.root, "-c", "protocol.file.allow=always", "submodule", "add", "-q", inner.as_posix(), "sub")
            run(repo.root, "commit", "-q", "-m", "add submodule")
            (repo.root / "sub" / "x.txt").write_text("y\n")
            run(repo.root / "sub", "commit", "-q", "-am", "move submodule")
            cs = collect(repo.root)
            self.assertEqual(cs.by_path()["sub"].kind, "modified")
            got = changed_lines(cs, cs.by_path()["sub"])
            self.assertEqual((got.scanned, got.reason), (False, changes.SUBMODULE))


class PrivateIndex(unittest.TestCase):
    """The repository's index and index.lock are never written by change analysis, even
    in a stat-dirty working tree; one private copy per operation, always cleaned up."""

    @staticmethod
    def make_stat_dirty(repo):
        import os
        later = time.time() + 300
        for path in repo.root.rglob("*"):
            if path.is_file() and ".git" not in path.relative_to(repo.root).parts:
                os.utime(path, (later, later))

    def test_real_index_untouched_in_a_stat_dirty_tree_with_control(self):
        import subprocess
        with base_repo() as repo:
            repo.write("staged.txt", "s\n"); repo.git("add", "staged.txt")
            repo.write("a.txt", lines(40) + "edit\n")
            self.make_stat_dirty(repo)
            index, lock = repo.root / ".git" / "index", repo.root / ".git" / "index.lock"
            before = index.read_bytes()
            with changes.analysis(repo.root):
                cs = collect(repo.root, base="main")
                for change in cs.changes:
                    changed_lines(cs, change)
            self.assertEqual(index.read_bytes(), before)                     # real index untouched
            self.assertFalse(lock.exists())
            self.assertEqual(summary(cs), {"a.txt": ("modified", ("unstaged",), None),
                                           "staged.txt": ("added", ("staged",), None)})
            # Control: plain git diff in the same stat-dirty tree DOES rewrite the index.
            subprocess.run(["git", "-C", str(repo.root), "--no-optional-locks", "diff", "--name-status"],
                           capture_output=True, timeout=60)
            self.assertNotEqual(index.read_bytes(), before)

    def test_split_index_writes_nothing_into_git(self):
        with base_repo() as repo:
            repo.git("config", "core.splitIndex", "true")
            repo.git("update-index", "--split-index")
            repo.write("a.txt", lines(40) + "edit\n")
            self.make_stat_dirty(repo)
            git_dir = repo.root / ".git"
            before = {p.relative_to(git_dir).as_posix(): p.read_bytes() for p in git_dir.rglob("*") if p.is_file()}
            cs = collect(repo.root)
            changed_lines(cs, cs.by_path()["a.txt"])
            after = {p.relative_to(git_dir).as_posix(): p.read_bytes() for p in git_dir.rglob("*") if p.is_file()}
            self.assertEqual(after, before)                                   # no file added or changed

    def test_split_index_configured_but_not_yet_split(self):
        """The case that needs core.splitIndex=false: with splitIndex configured and the
        index not yet split, a git call that writes an index would create a new
        sharedindex.* file inside .git. The control shows that happens without the safeguard."""
        import os
        import shutil
        import subprocess
        import tempfile
        from .support import GIT
        with base_repo() as repo:
            repo.git("config", "core.splitIndex", "true")
            git_dir = repo.root / ".git"
            self.assertEqual(list(git_dir.glob("sharedindex.*")), [])          # not split yet
            repo.write("a.txt", lines(40) + "edit\n")
            self.make_stat_dirty_past(repo)
            before = {p.relative_to(git_dir).as_posix(): p.read_bytes() for p in git_dir.rglob("*") if p.is_file()}
            cs = collect(repo.root)
            changed_lines(cs, cs.by_path()["a.txt"])
            after = {p.relative_to(git_dir).as_posix(): p.read_bytes() for p in git_dir.rglob("*") if p.is_file()}
            self.assertEqual(list(git_dir.glob("sharedindex.*")), [])          # no shared index created
            self.assertEqual(after, before)
            # Control: the same private-copy call WITHOUT core.splitIndex=false writes a
            # shared index file into .git.
            with tempfile.TemporaryDirectory(prefix="impact-control-") as tmp:
                copy = os.path.join(tmp, "index")
                shutil.copyfile(git_dir / "index", copy)
                subprocess.run(GIT + ["-C", str(repo.root), "diff", "--name-status"], capture_output=True,
                               timeout=60, env={**os.environ, "GIT_INDEX_FILE": copy})
            self.assertNotEqual(list(git_dir.glob("sharedindex.*")), [])

    @staticmethod
    def make_stat_dirty_past(repo):
        """Timestamps one hour in the past, unchanged content: what git sees after a
        checkout, copy or touch (future timestamps make git treat entries as racy)."""
        import os
        earlier = time.time() - 3600
        for path in repo.root.rglob("*"):
            if path.is_file() and ".git" not in path.relative_to(repo.root).parts:
                os.utime(path, (earlier, earlier))

    def test_hooks_do_not_run(self):
        """A post-index-change hook (in .git/hooks, or in a configured core.hooksPath) does
        not run during change analysis; the control shows plain git would run it."""
        import subprocess
        from .support import GIT
        for variant in ("dot-git-hooks", "configured-hooksPath"):
            with self.subTest(variant=variant), base_repo() as repo:
                marker = repo.root.parent / f"marker-hook-{variant}"
                hooks = repo.root / ".git" / "hooks" if variant == "dot-git-hooks" else repo.root.parent / f"hooks-{variant}"
                hooks.mkdir(exist_ok=True)
                hook = hooks / "post-index-change"
                hook.write_bytes(b"#!/bin/sh\necho ran > '" + marker.as_posix().encode() + b"'\n")
                hook.chmod(0o755)
                if variant == "configured-hooksPath":
                    repo.git("config", "core.hooksPath", hooks.as_posix())
                repo.write("staged.txt", "s\n"); repo.git("add", "staged.txt")
                repo.write("a.txt", lines(40) + "edit\n")
                marker.unlink(missing_ok=True)
                self.make_stat_dirty_past(repo)
                with changes.analysis(repo.root):
                    cs = collect(repo.root, base="main")
                    got = {c.path: len(changed_lines(cs, c).added) for c in cs.changes}
                self.assertFalse(marker.exists())                             # no hook ran
                self.assertEqual(summary(cs), {"a.txt": ("modified", ("unstaged",), None),
                                               "staged.txt": ("added", ("staged",), None)})
                self.assertEqual(got, {"a.txt": 1, "staged.txt": 1})          # accuracy unaffected
                # Control: plain git diff in the same stat-dirty tree runs the hook.
                subprocess.run(GIT + ["-C", str(repo.root), "diff", "--name-status"], capture_output=True, timeout=60)
                self.assertTrue(marker.exists())
                marker.unlink()

    def test_hooks_folders_are_removed(self):
        import tempfile
        from tools.impact import gitfiles
        temp = Path(tempfile.gettempdir())
        before = set(temp.glob(gitfiles.HOOKS_FOLDER_PREFIX + "*"))
        with base_repo() as repo:
            repo.write("a.txt", lines(40) + "edit\n")
            cs = collect(repo.root)
            changed_lines(cs, cs.by_path()["a.txt"])
            import subprocess
            failures = {
                "timeout": {"side_effect": subprocess.TimeoutExpired("git", 1)},
                "git not found": {"side_effect": FileNotFoundError("git")},
                "git command failed": {"return_value": subprocess.CompletedProcess(["git"], 128, b"", b"fatal: x")},
            }
            for name, behaviour in failures.items():
                with self.subTest(failure=name):
                    created = []

                    def watch(prefix, real=tempfile.mkdtemp):
                        created.append(real(prefix=prefix))
                        return created[-1]
                    with unittest.mock.patch("tools.impact.gitfiles.tempfile.mkdtemp", side_effect=watch), \
                            unittest.mock.patch("tools.impact.gitfiles.subprocess.run", **behaviour):
                        with self.assertRaises(GitError):
                            gitfiles.run_git(repo.root, "status")
                    self.assertEqual(len(created), 1)                         # a hooks folder was made ...
                    self.assertFalse(Path(created[0]).exists())               # ... and removed despite the error
        self.assertEqual(set(temp.glob(gitfiles.HOOKS_FOLDER_PREFIX + "*")) - before, set())

    def test_same_size_edit_in_the_same_second_as_the_index_is_detected(self):
        """Git checks "racily clean" entries (file timestamp not older than the index file)
        by content. The private copy must keep the index timestamp, or a same-size edit made
        in the same second as staging looks unchanged. Timestamps are set explicitly to one
        whole second, so the case is deterministic (no timing luck)."""
        import hashlib
        import os
        import shutil
        from tools.impact import gitfiles
        with base_repo() as repo:
            moment = int(time.time()) - 600                                   # one whole second, in the past
            repo.write("racy.txt", "aaaa\n")
            os.utime(repo.root / "racy.txt", (moment, moment))
            repo.git("add", "racy.txt")                                       # entry records mtime = moment
            repo.write("racy.txt", "bbbb\n")                                  # same size, new content
            os.utime(repo.root / "racy.txt", (moment, moment))                # same timestamp as recorded
            index = repo.root / ".git" / "index"
            os.utime(index, (moment, moment))                                 # index written in that second
            snapshot_ = (hashlib.sha256(index.read_bytes()).hexdigest(), index.stat().st_mtime_ns)
            expected = {"racy.txt": ("added", ("staged", "unstaged"), None)}

            cs = collect(repo.root)                                           # copy keeps the index timestamp
            self.assertEqual({p: v for p, v in summary(cs).items() if p == "racy.txt"}, expected)
            self.assertEqual(changed_lines(cs, cs.by_path()["racy.txt"]).added, ("bbbb",))
            # Control: a private copy with a fresh timestamp misses the unstaged edit.
            with unittest.mock.patch.object(gitfiles.shutil, "copy2", side_effect=shutil.copyfile):
                fresh = collect(repo.root)
            self.assertEqual(summary(fresh)["racy.txt"], ("added", ("staged",), None))
            # The real index is untouched (content and timestamp).
            self.assertEqual((hashlib.sha256(index.read_bytes()).hexdigest(), index.stat().st_mtime_ns), snapshot_)

    def spy(self):
        from tools.impact import gitfiles
        seen = []
        real = gitfiles._run

        def recording(root, args, timeout):
            active = gitfiles._PRIVATE_INDEX.get()
            seen.append((args, active[1] if active else None))
            return real(root, args, timeout)
        return seen, unittest.mock.patch.object(gitfiles, "_run", side_effect=recording)

    def test_one_private_index_per_operation_and_it_is_removed(self):
        import os
        with base_repo() as repo:
            repo.write("a.txt", lines(40) + "edit\n")
            seen, patch = self.spy()
            with patch:
                with changes.analysis(repo.root):
                    cs = collect(repo.root)
                    changed_lines(cs, cs.by_path()["a.txt"])
            private = {idx for _, idx in seen if idx is not None}
            self.assertEqual(len(private), 1)                                 # one copy for the whole operation
            path = private.pop()
            self.assertFalse(os.path.exists(path))
            self.assertFalse(os.path.exists(os.path.dirname(path)))           # temp folder removed
            self.assertFalse(Path(path).resolve().is_relative_to(repo.root.resolve()))  # outside the repo
            diffs = [idx for args, idx in seen if "diff" in args]
            self.assertTrue(diffs and all(idx == path for idx in diffs))      # every diff used the copy

    def test_private_index_removed_on_errors(self):
        import os
        from tools.impact import gitfiles
        with base_repo() as repo:
            captured = []
            with self.assertRaises(RuntimeError):
                with gitfiles.private_index(repo.root) as path:
                    captured.append(path)
                    raise RuntimeError("boom")
            self.assertFalse(os.path.exists(os.path.dirname(captured[0])))
            self.assertIsNone(gitfiles._PRIVATE_INDEX.get())
            with unittest.mock.patch.object(changes, "_merge", side_effect=RuntimeError("boom")):
                seen, patch = self.spy()
                with patch, self.assertRaises(RuntimeError):
                    collect(repo.root)
            paths = {idx for _, idx in seen if idx}
            self.assertTrue(paths)
            self.assertFalse(any(os.path.exists(os.path.dirname(p)) for p in paths))

    def test_repository_without_an_index_yet(self):
        with TempRepo() as repo:
            repo.write("loose.txt", "x\n")
            self.assertFalse((repo.root / ".git" / "index").exists())
            self.assertEqual(summary(collect(repo.root)), {"loose.txt": ("added", ("untracked",), None)})
            self.assertFalse((repo.root / ".git" / "index").exists())        # still none

    def test_validate_listing_does_not_use_a_private_index(self):
        from tools.impact import gitfiles
        with base_repo() as repo:
            seen, patch = self.spy()
            with patch:
                gitfiles.list_files(repo.root)
            self.assertTrue(seen and all(idx is None for _, idx in seen))


class GitVersionRequirement(unittest.TestCase):
    def fake_version(self, text):
        import subprocess
        from tools.impact import gitfiles
        gitfiles._VERSION_CACHE.clear()
        out = subprocess.CompletedProcess(["git"], 0, text.encode(), b"")
        return unittest.mock.patch("tools.impact.gitfiles.subprocess.run", return_value=out)

    def tearDown(self):
        from tools.impact import gitfiles
        gitfiles._VERSION_CACHE.clear()

    def test_versions(self):
        from tools.impact import gitfiles
        cases = {"git version 2.43.9": False, "git version 2.44.0": True, "git version 2.56.0.windows.4": True,
                 "git version 1.99.0": False, "git version 3.0.0": True}
        for text, ok in cases.items():
            with self.subTest(text=text), self.fake_version(text):
                if ok:
                    gitfiles.require_git_for_change_analysis(Path("."))
                else:
                    with self.assertRaisesRegex(GitError, "needs git 2.44 or later"):
                        gitfiles.require_git_for_change_analysis(Path("."))

    def test_unparseable_version_is_an_error(self):
        from tools.impact import gitfiles
        with self.fake_version("something else"):
            with self.assertRaisesRegex(GitError, "could not determine the git version"):
                gitfiles.require_git_for_change_analysis(Path("."))

    def test_old_git_stops_collect_before_any_analysis(self):
        with base_repo() as repo, self.fake_version("git version 2.40.1"):
            with self.assertRaisesRegex(GitError, "needs git 2.44 or later"):
                collect(repo.root)


class CopyLimitation(unittest.TestCase):
    def test_copy_of_an_unmodified_file_is_added_and_scanned(self):
        with base_repo() as repo:
            repo.write("copy_of_keep.txt", lines(40, "keep"))                 # source keep.txt unchanged
            repo.git("add", "copy_of_keep.txt")
            cs = collect(repo.root)
            self.assertEqual(cs.by_path()["copy_of_keep.txt"].kind, "added")  # documented limitation 5
            self.assertEqual(len(changed_lines(cs, cs.by_path()["copy_of_keep.txt"]).added), 40)


class ChangeModelTests(unittest.TestCase):
    def test_removed_paths(self):
        self.assertEqual(Change("a", "deleted", ("staged",)).removed_paths, ("a",))
        self.assertEqual(Change("b", "renamed", ("staged",), "a").removed_paths, ("a",))
        self.assertEqual(Change("b", "copied", ("staged",), "a").removed_paths, ())
        self.assertEqual(Change("b", "modified", ("staged",)).removed_paths, ())


if __name__ == "__main__":
    unittest.main()
