import contextlib
import hashlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.impact import cli, gitfiles
from tools.impact.config import LoadError

from .support import IMPACT, REGISTRY, TempRepo, valid_repo

REPO_ROOT = Path(__file__).resolve().parents[3]
ID_RE = r"[a-z-]+:[0-9a-f]{10}"


def run(*argv):
    """Run the CLI in-process; returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        code = cli.main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def snapshot(root: Path) -> dict:
    """Content hash of every file under root, outside .git."""
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and ".git" not in p.relative_to(root).parts}


def registry_with(**changes):
    reg = json.loads(json.dumps(REGISTRY))
    for key, value in changes.items():
        reg[key] = value
    return reg


class ExitCodeTests(unittest.TestCase):
    def test_clean_repository_exit_0_and_no_files_written(self):
        with valid_repo() as repo:
            before = snapshot(repo.root)
            code, out, err = run("validate", "--root", str(repo.root))
            self.assertEqual((code, err), (0, ""))
            self.assertIn("Summary: 0 ERROR, 0 WARNING | exit code 0", out)
            self.assertEqual(snapshot(repo.root), before)          # without --out nothing is written
            self.assertFalse((repo.root / ".local").exists())

    def test_warnings_only_exit_0(self):
        reg = registry_with(components=REGISTRY["components"] + [{"id": "extra", "paths": ["nothing/**"], "docs": []}])
        with valid_repo(registry=reg) as repo:
            code, out, _ = run("validate", "--root", str(repo.root))
        self.assertEqual(code, 0)
        self.assertRegex(out, rf"WARNING  registry-incomplete:[0-9a-f]{{10}}  registry/components.yml  component extra.paths")

    def test_missing_doc_exit_1(self):
        reg = registry_with(components=[{"id": "app", "paths": ["app/**"], "docs": ["docs/missing.md"]}])
        with valid_repo(registry=reg) as repo:
            code, out, _ = run("validate", "--root", str(repo.root))
        self.assertEqual(code, 1)
        self.assertRegex(out, r"ERROR    registry-missing-path:[0-9a-f]{10}  .*doc does not exist: docs/missing.md")

    def test_unsafe_trigger_regex_exit_1(self):
        reg = registry_with(content_triggers=[{"id": "bad", "paths": ["**/*.py"], "match": "(a+)+$",
                                               "docs": ["docs/app.md"]}])
        with valid_repo(registry=reg) as repo:
            code, out, _ = run("validate", "--root", str(repo.root))
        self.assertEqual(code, 1)
        self.assertIn("unsafe or invalid content-trigger pattern", out)

    def test_malformed_impact_yml_is_a_finding_exit_1(self):
        with valid_repo() as repo:
            repo.write("impact.yml", "version: [1\n")
            code, out, err = run("validate", "--root", str(repo.root), "--format", "json")
        self.assertEqual((code, err), (1, ""))
        doc = json.loads(out)
        self.assertEqual(doc["sources"], [])
        self.assertEqual([(f["rule"], f["source"], f["location"]) for f in doc["findings"]],
                         [("registry-invalid", "impact.yml", "(file)")])
        self.assertIn("not valid YAML", doc["findings"][0]["message"])

    def test_missing_configuration_files_are_findings_exit_1(self):
        with valid_repo() as repo:
            (repo.root / "registry" / "components.yml").unlink()
            code, out, _ = run("validate", "--root", str(repo.root))
            self.assertEqual(code, 1)
            self.assertRegex(out, r"ERROR    registry-invalid:[0-9a-f]{10}  registry/components.yml  \(file\)  "
                                  r"components.yml: file not found")
            (repo.root / "impact.yml").unlink()
            code, out, _ = run("validate", "--root", str(repo.root))
            self.assertEqual(code, 1)
            self.assertIn("impact.yml: file not found", out)

    def test_deeply_nested_yaml_is_a_finding_exit_1(self):
        with valid_repo() as repo:
            repo.write("registry/components.yml", "a: " + "[" * 5000 + "]" * 5000 + "\n")
            code, out, _ = run("validate", "--root", str(repo.root))
        self.assertEqual(code, 1)
        self.assertIn("nested too deeply", out)

    def test_schema_problems_exit_1_and_files_still_checked(self):
        reg = registry_with(components=[{"id": "app", "paths": ["app/**"], "docs": ["docs/nope.md"], "kind": "x"}])
        with valid_repo(registry=reg) as repo:
            code, out, _ = run("validate", "--root", str(repo.root))
        self.assertEqual(code, 1)
        self.assertIn("unknown key 'kind'", out)

    def test_bad_arguments_exit_2(self):
        for argv in (["validate", "--format", "xml"], [], ["frobnicate"], ["validate", "--nope"]):
            with self.subTest(argv=argv):
                self.assertEqual(run(*argv)[0], 2)

    def test_help_exit_0(self):
        self.assertEqual(run("validate", "--help")[0], 0)

    def test_not_a_repository_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run("validate", "--root", tmp)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("impact: error:", err)

    def test_root_not_a_folder_exit_2(self):
        with valid_repo() as repo:
            code, _, err = run("validate", "--root", str(repo.root / "impact.yml"))
        self.assertEqual(code, 2)
        self.assertIn("--root is not a folder", err)

    def test_git_missing_or_hanging_exit_2(self):
        import subprocess
        with valid_repo() as repo:
            for effect in (FileNotFoundError(), subprocess.TimeoutExpired(["git"], 60)):
                with self.subTest(effect=type(effect).__name__):
                    with mock.patch("tools.impact.gitfiles.subprocess.run", side_effect=effect):
                        code, out, err = run("validate", "--root", str(repo.root))
                    self.assertEqual((code, out), (2, ""))
                    self.assertIn("impact: error:", err)

    def test_operational_read_failure_exit_2(self):
        with valid_repo() as repo:
            with mock.patch("tools.impact.config.read_yaml",
                            side_effect=LoadError("impact.yml: cannot read (Permission denied)", operational=True)):
                code, out, err = run("validate", "--root", str(repo.root))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("Permission denied", err)

    def test_internal_error_exit_2_not_1(self):
        with valid_repo() as repo:
            with mock.patch("tools.impact.cli.from_problems", side_effect=RuntimeError("boom")):
                code, out, err = run("validate", "--root", str(repo.root))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("internal error", err)
        self.assertIn("RuntimeError: boom", err)

    def test_unsupported_path_is_a_warning_not_a_crash(self):
        with valid_repo() as repo:
            real = gitfiles.list_files(repo.root)
            fake = gitfiles.Listing(real.files, (gitfiles.Unsupported("tab\\there.py", "control character in path"),))
            with mock.patch("tools.impact.cli.gitfiles.list_files", return_value=fake):
                code, out, _ = run("validate", "--root", str(repo.root))
        self.assertEqual(code, 0)
        self.assertRegex(out, r"WARNING  unsupported-path:[0-9a-f]{10}  \(working tree\)  file name  "
                              r"control character in path; the file is not analysed: tab\\there.py")

    def test_repository_without_commits(self):
        with valid_repo(commit=False) as repo:
            code, out, _ = run("validate", "--root", str(repo.root))
        self.assertEqual(code, 0)
        self.assertIn("HEAD no commits", out)


class FileSetTests(unittest.TestCase):
    """validate's file list: tracked + untracked-not-ignored, minus files deleted from disk."""

    def test_untracked_doc_counts_ignored_doc_does_not(self):
        reg = registry_with(components=[{"id": "app", "paths": ["app/**"], "docs": ["docs/new.md", "docs/hidden.md"]}])
        with valid_repo(registry=reg) as repo:
            repo.write("docs/new.md", "x")                    # untracked, not ignored
            repo.write("docs/hidden.md", "x")
            repo.write(".gitignore", ".local/\ndocs/hidden.md\n")
            code, out, _ = run("validate", "--root", str(repo.root))
        self.assertEqual(code, 1)
        self.assertNotIn("docs/new.md", out)
        self.assertIn("doc does not exist: docs/hidden.md", out)

    def test_doc_deleted_from_disk_is_missing(self):
        with valid_repo() as repo:
            (repo.root / "docs" / "app.md").unlink()           # still in the index
            code, out, _ = run("validate", "--root", str(repo.root))
        self.assertEqual(code, 1)
        self.assertIn("doc does not exist: docs/app.md", out)


class OutputTests(unittest.TestCase):
    def test_json_format_and_determinism(self):
        with valid_repo() as repo:
            first = run("validate", "--root", str(repo.root), "--format", "json")
            second = run("validate", "--root", str(repo.root), "--format", "json")
        self.assertEqual(first, second)
        doc = json.loads(first[1])
        self.assertEqual(doc["summary"]["exit_code"], first[0])
        self.assertEqual(doc["command"], "validate")
        self.assertRegex(doc["head"], r"\A[0-9a-f]{40}\Z")

    def test_out_default_writes_both_reports(self):
        with valid_repo() as repo:
            code, out, _ = run("validate", "--root", str(repo.root), "--out")
            folder = repo.root / ".local" / "impact"
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ["validate.json", "validate.txt"])
            self.assertEqual((folder / "validate.txt").read_bytes(), out.encode("utf-8"))  # exact bytes, LF
            json.loads((folder / "validate.json").read_text("utf-8"))
            self.assertEqual(repo.git("status", "--porcelain", "--untracked-files=all"), "")  # ignored
        self.assertEqual(code, 0)

    def test_out_with_folder_and_json_stdout(self):
        with valid_repo() as repo:
            code, out, _ = run("validate", "--root", str(repo.root), "--out", "reports", "--format", "json")
            self.assertEqual((repo.root / "reports" / "validate.json").read_text("utf-8"), out)
            self.assertTrue((repo.root / "reports" / "validate.txt").exists())

    def test_out_rejections_exit_2_and_write_nothing(self):
        with valid_repo() as repo:
            repo.write("tracked/validate.txt", "keep me\n")
            repo.add_all()
            repo.commit("tracked report")
            outside = Path(tempfile.mkdtemp(prefix="impact-outside-"))
            cases = {
                "outside the repository": str(outside),
                "parent folder": "..",
                "inside .git": ".git/reports",
                "a file, not a folder": "impact.yml",
                "a tracked report file": "tracked",
            }
            for label, target in cases.items():
                with self.subTest(label):
                    before = snapshot(repo.root)
                    code, out, err = run("validate", "--root", str(repo.root), "--out", target)
                    self.assertEqual((code, out), (2, ""))
                    self.assertIn("impact: error:", err)
                    self.assertEqual(snapshot(repo.root), before)
            self.assertEqual(list(outside.iterdir()), [])
            outside.rmdir()
            self.assertEqual((repo.root / "tracked" / "validate.txt").read_text("utf-8"), "keep me\n")

    def test_tracked_files_never_modified(self):
        with valid_repo() as repo:
            tracked = repo.git("ls-files", "-z").split("\0")[:-1]
            before = {path: digest for path, digest in snapshot(repo.root).items() if path in tracked}
            for argv in (["--format", "json"], ["--out"], ["--out", "r"]):
                run("validate", "--root", str(repo.root), *argv)
            after = {path: digest for path, digest in snapshot(repo.root).items() if path in tracked}
            self.assertEqual(after, before)                     # byte-identical tracked files
            self.assertEqual(repo.git("diff", "--name-only"), "")
            self.assertEqual(repo.git("diff", "--cached", "--name-only"), "")
            new = sorted(set(snapshot(repo.root)) - set(tracked))
            self.assertEqual(new, [".local/impact/validate.json", ".local/impact/validate.txt",
                                   "r/validate.json", "r/validate.txt"])  # only the report files


class RealRepositoryTests(unittest.TestCase):
    def test_this_repository_validates_with_no_errors(self):
        code, out, err = run("validate", "--root", str(REPO_ROOT), "--format", "json")
        self.assertEqual(err, "")
        doc = json.loads(out)
        self.assertEqual(doc["summary"]["errors"], 0, json.dumps(doc["findings"], indent=2))
        self.assertEqual(code, 0)
        self.assertEqual(doc["sources"], ["impact.yml", "registry/components.yml"])
        for f in doc["findings"]:
            self.assertRegex(f["id"], rf"\A{ID_RE}\Z")


if __name__ == "__main__":
    unittest.main()
