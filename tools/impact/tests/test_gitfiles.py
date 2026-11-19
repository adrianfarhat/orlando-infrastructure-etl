import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.impact import gitfiles
from tools.impact.gitfiles import GitError, Unsupported, parse_listing
from tools.impact.paths import MAX_PATH_BYTES, MAX_SEGMENT_BYTES

from .support import TempRepo


class ParseListingTests(unittest.TestCase):
    """Synthetic NUL-delimited output, so every case runs on every platform
    (Windows cannot create some of these names)."""

    def test_plain_names_spaces_brackets_and_unicode(self):
        data = "a.txt\0dir/b c.md\0web/src/app/api/[id]/route.ts\0résumé/日本.md\0".encode()
        listing = parse_listing(data)
        self.assertEqual(listing.files, ("a.txt", "dir/b c.md", "résumé/日本.md",
                                         "web/src/app/api/[id]/route.ts"))
        self.assertEqual(listing.unsupported, ())

    def test_backslash_is_kept_literally(self):
        listing = parse_listing(b"extractors/back\\slash.py\0")
        self.assertEqual(listing.files, ("extractors/back\\slash.py",))   # not rewritten to '/'

    def test_unsupported_names_are_reported_not_fatal(self):
        long_segment = "s" * (MAX_SEGMENT_BYTES + 1)
        long_path = "/".join(["d" * 200] * (MAX_PATH_BYTES // 200 + 1))
        data = b"\0".join([b"ok.txt", b"tab\there.py", b"new\nline.py", b"del\x7f.py", b"bad\xff.py",
                           long_segment.encode(), long_path.encode(), b"c1\xc2\x85.py"]) + b"\0"
        listing = parse_listing(data)
        self.assertEqual(listing.files, ("ok.txt",))
        reasons = {u.reason for u in listing.unsupported}
        self.assertEqual(len(listing.unsupported), 7)
        self.assertIn("file name is not valid UTF-8", reasons)
        self.assertIn("control character in path", reasons)
        self.assertIn(f"path segment longer than {MAX_SEGMENT_BYTES} bytes", reasons)
        self.assertIn(f"path longer than {MAX_PATH_BYTES} bytes", reasons)

    def test_shown_names_are_printable_and_unambiguous(self):
        listing = parse_listing(b"tab\there.py\0bad\xff.py\0")
        shown = sorted(u.shown for u in listing.unsupported)
        self.assertEqual(shown, ["bad\\xff.py", "tab\\there.py"])
        self.assertTrue(all(s.isprintable() for s in shown))

    def test_empty_duplicates_and_order(self):
        self.assertEqual(parse_listing(b""), gitfiles.Listing((), ()))
        self.assertEqual(parse_listing(b"\0\0").files, ())
        self.assertEqual(parse_listing(b"b\0a\0b\0").files, ("a", "b"))


class GitCommandTests(unittest.TestCase):
    def test_not_a_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(GitError):
                gitfiles.toplevel(Path(tmp))

    def test_git_missing(self):
        with mock.patch("tools.impact.gitfiles.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(GitError, "not found"):
                gitfiles.run_git(Path("."), "status")

    def test_git_timeout(self):
        with mock.patch("tools.impact.gitfiles.subprocess.run",
                        side_effect=subprocess.TimeoutExpired(["git"], 60)):
            with self.assertRaisesRegex(GitError, "did not finish"):
                gitfiles.run_git(Path("."), "ls-files")

    def test_git_failure_message(self):
        failed = subprocess.CompletedProcess(["git"], 128, b"", b"fatal: something broke\nmore\n")
        with mock.patch("tools.impact.gitfiles.subprocess.run", return_value=failed):
            with self.assertRaisesRegex(GitError, "fatal: something broke"):
                gitfiles.run_git(Path("."), "ls-files")

    def test_run_git_uses_fixed_arguments_and_no_shell(self):
        ok = subprocess.CompletedProcess(["git"], 0, b"", b"")
        with mock.patch("tools.impact.gitfiles.subprocess.run", return_value=ok) as run:
            gitfiles.run_git(Path("repo"), "ls-files", "-z")
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["git", "-C", "repo", "ls-files", "-z"])
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["timeout"], gitfiles.GIT_TIMEOUT_SECONDS)


class RealRepositoryListingTests(unittest.TestCase):
    def test_working_tree_listing(self):
        with TempRepo() as repo:
            repo.write("tracked file.txt", "a")
            repo.write("résumé.md", "b")
            repo.write("web/app/api/[id]/route.ts", "c")
            repo.write("deleted.txt", "d")
            repo.write(".gitignore", "ignored.log\n")
            repo.add_all()
            repo.commit()
            repo.write("untracked.md", "e")            # untracked, not ignored: included
            repo.write("ignored.log", "f")             # ignored: left out
            (repo.root / "deleted.txt").unlink()       # deleted from disk only: dropped
            listing = gitfiles.list_files(repo.root)
        self.assertEqual(listing.files, (".gitignore", "résumé.md", "tracked file.txt",
                                         "untracked.md", "web/app/api/[id]/route.ts"))
        self.assertEqual(listing.unsupported, ())

    def test_head_and_tracking(self):
        with TempRepo() as repo:
            self.assertIsNone(gitfiles.head(repo.root))     # no commits yet
            repo.write("a.txt", "a")
            repo.add_all()
            repo.commit()
            sha = gitfiles.head(repo.root)
            self.assertRegex(sha, r"\A[0-9a-f]{40}\Z")
            self.assertTrue(gitfiles.is_tracked(repo.root, "a.txt"))
            self.assertFalse(gitfiles.is_tracked(repo.root, "b.txt"))
            self.assertEqual(gitfiles.toplevel(repo.root / ".").resolve(), repo.root.resolve())


if __name__ == "__main__":
    unittest.main()
