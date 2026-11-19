"""Post-83a cleanup (2026-11-19): the two maintenance items deferred from Stage 3 QA.

1. Start-up edge cases in __main__.py that could exit 0 or 1 instead of 2: an
   exception whose message cannot be produced, and SystemExit raised while the CLI is
   being imported (with a message, or with code 0).
2. A failed --out into a folder that did not exist left that empty folder behind.
"""

import os
import unittest
from unittest import mock

from .support import valid_repo
from .test_cli import run
from .test_stage3_regressions import run_module

FAKE_CLI = ("import sys, types, tools.impact; m = types.ModuleType('tools.impact.cli'); "
            "m.__getattr__ = lambda name: (_ for _ in ()).throw({exc}); "
            "sys.modules['tools.impact.cli'] = m; ")


class StartupEdgeCases(unittest.TestCase):
    def test_exception_whose_message_cannot_be_produced(self):
        exc = "type('Bad', (RuntimeError,), {'__str__': lambda self: 1 / 0})()"
        code, out, err = run_module("validate", pre=FAKE_CLI.format(exc=exc))
        self.assertEqual((code, out), (2, b""))
        self.assertIn("internal error while starting: Bad: <the error message could not be produced>", err)
        self.assertNotIn("Traceback", err)

    def test_import_error_whose_message_cannot_be_produced(self):
        exc = "type('BadImport', (ImportError,), {'__str__': lambda self: 1 / 0})()"
        code, out, err = run_module("validate", pre=FAKE_CLI.format(exc=exc))
        self.assertEqual((code, out), (2, b""))
        self.assertIn("cannot start: <the error message could not be produced>", err)

    def test_system_exit_with_a_message_while_importing(self):
        code, out, err = run_module("validate", pre=FAKE_CLI.format(exc="SystemExit('stop\\u202e here')"))
        self.assertEqual((code, out), (2, b""))
        self.assertIn("internal error while starting: SystemExit: stop\\u202e here", err)
        self.assertNotIn("‮", err)

    def test_system_exit_0_while_importing(self):
        code, out, err = run_module("validate", pre=FAKE_CLI.format(exc="SystemExit(0)"))
        self.assertEqual((code, out), (2, b""))
        self.assertIn("internal error while starting: SystemExit: 0", err)

    def test_system_exit_1_while_importing(self):
        code, out, err = run_module("validate", pre=FAKE_CLI.format(exc="SystemExit(1)"))
        self.assertEqual((code, out), (2, b""))

    def test_keyboard_interrupt_is_not_turned_into_a_result(self):
        code, out, err = run_module("validate", pre=FAKE_CLI.format(exc="KeyboardInterrupt()"))
        self.assertNotIn(code, (0, 1, 2))          # Python's own interrupt exit, never a tool result
        self.assertNotIn("internal error while starting", err)


class FailedOutLeavesNoEmptyFolder(unittest.TestCase):
    @staticmethod
    def failing_replace(*args, **kwargs):
        raise PermissionError(13, "The process cannot access the file")

    def test_new_nested_folders_are_removed(self):
        with valid_repo() as repo:
            with mock.patch("tools.impact.cli.os.replace", side_effect=self.failing_replace):
                code, out, err = run("validate", "--root", str(repo.root), "--out", "new/deeper/reports")
            self.assertEqual((code, out), (2, ""))
            self.assertIn("could not write the reports", err)
            self.assertFalse((repo.root / "new").exists())

    def test_failure_while_writing_temp_files_also_cleans_up(self):
        with valid_repo() as repo:
            with mock.patch("tools.impact.cli.tempfile.mkstemp", side_effect=OSError(28, "No space left")):
                code, _, err = run("validate", "--root", str(repo.root), "--out", "fresh")
            self.assertEqual(code, 2)
            self.assertFalse((repo.root / "fresh").exists())

    def test_existing_folders_are_never_removed(self):
        with valid_repo() as repo:
            (repo.root / "existing").mkdir()
            with mock.patch("tools.impact.cli.os.replace", side_effect=self.failing_replace):
                code, _, _ = run("validate", "--root", str(repo.root), "--out", "existing/sub")
            self.assertEqual(code, 2)
            self.assertTrue((repo.root / "existing").is_dir())       # was there before: kept
            self.assertFalse((repo.root / "existing" / "sub").exists())  # created by the run: removed

    def test_default_out_folder_is_removed_after_a_failure(self):
        with valid_repo() as repo:
            with mock.patch("tools.impact.cli.os.replace", side_effect=self.failing_replace):
                code, _, _ = run("validate", "--root", str(repo.root), "--out")
            self.assertEqual(code, 2)
            self.assertFalse((repo.root / ".local").exists())

    def test_folder_holding_a_kept_backup_is_not_removed(self):
        real_replace = os.replace

        def failing(src, dst):
            if str(src).endswith(".tmp") and str(dst).endswith("validate.json"):
                raise PermissionError(13, "locked")
            if str(src).endswith(".old"):
                raise PermissionError(13, "locked")
            return real_replace(src, dst)

        with valid_repo() as repo:
            self.assertEqual(run("validate", "--root", str(repo.root), "--out", "r")[0], 0)
            with mock.patch("tools.impact.cli.os.replace", side_effect=failing):
                code, _, err = run("validate", "--root", str(repo.root), "--out", "r")
            self.assertEqual(code, 2)
            self.assertIn("may be inconsistent", err)
            self.assertTrue((repo.root / "r").is_dir())               # existed, and holds a kept backup

    def test_success_keeps_the_new_folder(self):
        with valid_repo() as repo:
            code, _, _ = run("validate", "--root", str(repo.root), "--out", "new/deeper")
            self.assertEqual(code, 0)
            self.assertEqual(sorted(p.name for p in (repo.root / "new" / "deeper").iterdir()),
                             ["validate.json", "validate.txt"])


if __name__ == "__main__":
    unittest.main()
