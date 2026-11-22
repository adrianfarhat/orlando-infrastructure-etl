"""The exit-code contract of `python -m tools.design` (T-97 Phase 1, before Q4 adds warnings).

Consumers (CI once T-85 runs `check`, scripts, the Feature Designer) rely on:
  0  success / nothing to report
  1  problems found (check, index --check) or a refused designer request
  2  a usage, file or workspace error (nothing was created or changed), or a malformed
     designer request
Any later change to this contract (for example warning-level diagnostics, Q4) must update
this test deliberately.
"""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.design import cli
from tools.design.workspace import new_feature
from tools.design.tests.test_design import Workspace, cmd


class ExitCodes(unittest.TestCase):
    def test_check(self):
        with Workspace() as ws:
            new_feature(ws.root, "A")
            self.assertEqual(cmd(ws.root, "check")[0], 0)
            path = ws.root / "designs/features/a.md"
            path.write_text(path.read_text(encoding="utf-8").replace("## 3. Logic", "## 3. Logik"), encoding="utf-8")
            self.assertEqual(cmd(ws.root, "check")[0], 1)
            self.assertEqual(cmd(ws.root, "check", "--no-such-option")[0], 2)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(cmd(Path(tmp), "check")[0], 2)                         # no workspace

    def test_index_check(self):
        with Workspace() as ws:
            new_feature(ws.root, "A")
            self.assertEqual(cmd(ws.root, "index", "--check")[0], 0)
            (ws.root / "designs/index/feature-index.md").write_text("stale\n", encoding="utf-8")
            self.assertEqual(cmd(ws.root, "index", "--check")[0], 1)
            self.assertEqual(cmd(ws.root, "index")[0], 0)

    def test_new(self):
        with Workspace() as ws:
            self.assertEqual(cmd(ws.root, "new", "feature", "--name", "A", interactive=False)[0], 0)
            self.assertEqual(cmd(ws.root, "new", "feature", "--name", "A", interactive=False)[0], 2)     # duplicate name
            self.assertEqual(cmd(ws.root, "new", "diagram", "--feature", "FD-0001", "--title", "D",
                                 interactive=False)[0], 0)
            self.assertEqual(cmd(ws.root, "new", "diagram", "--feature", "FD-0009", "--title", "D",
                                 interactive=False)[0], 2)

    def test_designer(self):
        with Workspace() as ws:
            new_feature(ws.root, "A")
            for stdin, code in ((json.dumps({"version": 1, "op": "library"}), 0),
                                (json.dumps({"version": 1, "op": "insert", "path": "designs/features/a.md",
                                             "text": "", "at": 0, "diagram_id": "x"}), 1),
                                (json.dumps({"version": 1, "op": "nope"}), 2)):
                with self.subTest(stdin=stdin), mock.patch("sys.stdin", io.StringIO(stdin)):
                    self.assertEqual(cmd(ws.root, "designer")[0], code)

    def test_help(self):
        out = io.StringIO()
        self.assertEqual(cli.main(["--help"], stdout=out, stderr=io.StringIO()), 0)


if __name__ == "__main__":
    unittest.main()
