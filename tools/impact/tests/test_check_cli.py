"""Stage 83b-3: `python -m tools.impact check` end to end on throwaway repositories."""

import hashlib
import json
import unittest
from pathlib import Path
from unittest import mock

from .test_cli import run
from .test_rules import IMPACT, LINES, REGISTRY, rules_repo


def check(repo, *args):
    return run("check", "--root", str(repo.root), *args)


def full_snapshot(root: Path) -> dict:
    """Content hash of every file under root, including .git."""
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def as_json(repo, *args):
    code, out, err = check(repo, "--format", "json", *args)
    return code, json.loads(out) if out else None, err


def with_stale_reference(repo):
    repo.write("docs/refs.md", "See app/old.py.\n"); repo.add_all(); repo.commit("ref")
    repo.git("rm", "-q", "app/old.py")


class ExitCodes(unittest.TestCase):
    def test_no_changes_exit_0(self):
        with rules_repo() as repo:
            code, out, err = check(repo)
            self.assertEqual((code, err), (0, ""))
            self.assertIn("Summary: 0 ERROR, 0 WARNING (0 acknowledged, 0 unacknowledged) | exit code 0", out)
            self.assertIn("  no changes", out)

    def test_warnings_never_fail_the_check(self):
        with rules_repo() as repo:
            repo.write("app/main.py", LINES + "SECRET\n"); repo.write("misc/new.txt", "x\n")
            code, data, _ = as_json(repo)
            self.assertEqual(code, 0)
            self.assertEqual(data["summary"]["errors"], 0)
            self.assertGreaterEqual(data["summary"]["warnings"], 3)

    def test_error_exit_1(self):
        with rules_repo() as repo:
            with_stale_reference(repo)
            code, out, _ = check(repo)
            self.assertEqual(code, 1)
            self.assertRegex(out, r"ERROR    stale-reference:[0-9a-f]{10}  docs/refs\.md  reference")

    def test_operational_and_configuration_failures_exit_2(self):
        with rules_repo() as repo:
            cases = {
                "bad base": (("--base", "no-such-ref"), "--base is not a commit"),
                "missing ack file": (("--ack-file", str(repo.root / "nope.txt")), "cannot read --ack-file"),
                "bad root": (("--format", "json"), None),
            }
            for name, (args, message) in cases.items():
                if name == "bad root":
                    code, out, err = run("check", "--root", str(repo.root / "missing"))
                    self.assertEqual((code, out), (2, ""))
                    self.assertIn("--root is not a folder", err)
                    continue
                with self.subTest(case=name):
                    code, out, err = check(repo, *args)
                    self.assertEqual((code, out), (2, ""))
                    self.assertIn(message, err)
            bad = repo.root.parent / "acks.txt"
            bad.write_bytes(b"\xff\xfe- ack")
            code, out, err = check(repo, "--ack-file", str(bad))
            self.assertEqual((code, out), (2, ""))
            self.assertIn("not valid UTF-8", err)
            code, _, err = run("check", "--root", str(repo.root), "--format", "pdf")
            self.assertEqual(code, 2)

    def test_invalid_or_missing_configuration_exit_2(self):
        with rules_repo(registry={"version": 1, "components": [{"id": "x"}]}) as repo:
            code, out, err = check(repo)
            self.assertEqual((code, out), (2, ""))
            self.assertIn("run `python -m tools.impact validate`", err)
        with rules_repo() as repo:
            (repo.root / "impact.yml").unlink()
            code, out, err = check(repo)
            self.assertEqual((code, out), (2, ""))
            self.assertIn("could not be loaded", err)
            self.assertEqual(run("validate", "--root", str(repo.root))[0], 1)   # validate's contract unchanged

    def test_not_a_git_repository_and_internal_errors_exit_2(self):
        with rules_repo() as repo:
            with mock.patch("tools.impact.rules.analyse", side_effect=RuntimeError("boom")):
                code, out, err = check(repo)
            self.assertEqual((code, out), (2, ""))
            self.assertIn("the check did not complete", err)


class Acknowledgements(unittest.TestCase):
    def ack_file(self, repo, text):
        path = repo.root.parent / "acks.md"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_acknowledged_warning_is_kept_and_labelled_in_every_format(self):
        with rules_repo() as repo:
            repo.write("app/main.py", LINES + "more\n")
            _, data, _ = as_json(repo)
            wid = next(f["id"] for f in data["findings"] if f["rule"] == "docs-not-updated")
            acks = self.ack_file(repo, f"## Docs\n- ack {wid}: reviewed docs/app.md, no change needed\n")
            code, data, _ = as_json(repo, "--ack-file", acks)
            self.assertEqual(code, 0)
            f = next(f for f in data["findings"] if f["id"] == wid)
            self.assertEqual((f["severity"], f["acknowledged"], f["ack_reason"]),
                             ("WARNING", True, "reviewed docs/app.md, no change needed"))
            self.assertEqual((data["summary"]["acknowledged_warnings"], data["summary"]["unacknowledged_warnings"]),
                             (1, data["summary"]["warnings"] - 1))
            _, text, _ = check(repo, "--ack-file", acks)
            self.assertIn(f"{wid}  registry/components.yml", text)
            self.assertIn("[acknowledged: reviewed docs/app.md, no change needed]", text)
            _, md, _ = check(repo, "--ack-file", acks, "--format", "md")
            self.assertIn("Documentation review required: acknowledged (reviewed docs/app.md, no change needed)", md)

    def test_ack_on_an_error_does_not_change_the_exit_code(self):
        with rules_repo() as repo:
            with_stale_reference(repo)
            _, data, _ = as_json(repo)
            eid = next(f["id"] for f in data["findings"] if f["severity"] == "ERROR")
            code, data, _ = as_json(repo, "--ack-file", self.ack_file(repo, f"- ack {eid}: this is a valid reason\n"))
            self.assertEqual(code, 1)
            error = next(f for f in data["findings"] if f["id"] == eid)
            self.assertEqual((error["severity"], error["acknowledged"]), ("ERROR", False))
            problems = [f for f in data["findings"] if f["rule"] == "ack-problem"]
            self.assertEqual([(p["severity"], p["subject"]) for p in problems], [("WARNING", f"error: {eid}")])

    def test_problem_acks_are_reported(self):
        with rules_repo() as repo:
            repo.write("misc/new.txt", "x\n")
            _, data, _ = as_json(repo)
            wid = data["findings"][0]["id"]
            text = (f"- ack {wid}: ok\n- ack docs-not-updated:0123456789: a stale acknowledgement\n"
                    f"- ack garbage\n- ack {wid}: a perfectly good reason\n")
            code, data, _ = as_json(repo, "--ack-file", self.ack_file(repo, text))
            self.assertEqual(code, 0)                                         # ack-problem is a WARNING
            subjects = sorted(f["subject"] for f in data["findings"] if f["rule"] == "ack-problem")
            self.assertEqual(subjects, ["duplicate: " + wid, "malformed: - ack garbage",
                                        "reason: " + wid, "unknown: docs-not-updated:0123456789"])
            self.assertTrue(next(f for f in data["findings"] if f["id"] == wid)["acknowledged"])

    def test_ack_survives_line_shifts(self):
        with rules_repo() as repo:
            repo.write("app/main.py", LINES + "SECRET\n")
            _, data, _ = as_json(repo)
            tid = next(f["id"] for f in data["findings"] if f["rule"] == "content-trigger")
            acks = self.ack_file(repo, f"- ack {tid}: credential handling unchanged, reviewed\n")
            repo.write("app/main.py", "new first line\n" + LINES + "padding\nSECRET\n")
            _, data, _ = as_json(repo, "--ack-file", acks)
            f = next(f for f in data["findings"] if f["rule"] == "content-trigger")
            self.assertEqual((f["id"], f["acknowledged"]), (tid, True))

    def test_empty_ack_file_is_fine(self):
        with rules_repo() as repo:
            self.assertEqual(check(repo, "--ack-file", self.ack_file(repo, ""))[0], 0)


class Formats(unittest.TestCase):
    def scenario(self, repo):
        repo.write("docs/refs.md", "See app/old.py.\n")
        repo.write("app/old.py", "unique content of the old file\n" * 5)  # not similar to any other file
        repo.add_all(); repo.commit("ref")
        repo.git("rm", "-q", "app/old.py")                                   # deletion + stale reference
        repo.git("mv", "lib/util.py", "lib/moved.py")                        # rename
        repo.write("data/raw/x.py", "SECRET\n")                              # ignored
        repo.write("core/bin.py", b"SECRET\x00")                             # unscanned
        repo.write("app/[link](x).py", "y\n")                                # Markdown-hostile name
        repo.write("app/main.py", LINES + "more\n")

    def test_text_json_and_markdown(self):
        with rules_repo() as repo:
            self.scenario(repo)
            code, text, _ = check(repo)
            self.assertEqual(code, 1)
            self.assertIn("renamed lib/util.py -> lib/moved.py [staged]", text)
            self.assertIn("deleted app/old.py [staged]", text)
            self.assertIn("data/raw/x.py [untracked]: ignored (impact.yml ignore)", text)
            self.assertIn("core/bin.py [untracked]: component core; purpose code; content not scanned", text)
            self.assertIn("secret (not scanned)", text)
            self.assertIn("dependents (one hop): lib depends on core (inferred: assumed from the design)", text)
            self.assertIn("tests: app/tests/test_main.py (test files in the same component", text)

            _, data, _ = as_json(repo)
            self.assertEqual((data["command"], data["schema_version"], data["base"]), ("check", 1, None))
            moved = next(e for e in data["impact"] if e["path"] == "lib/moved.py")
            self.assertEqual((moved["kind"], moved["old_path"]), ("renamed", "lib/util.py"))
            self.assertEqual(data["summary"]["exit_code"], 1)
            self.assertEqual(sorted(data["summary"]),
                             ["acknowledged_warnings", "changes", "errors", "exit_code", "unacknowledged_warnings",
                              "warnings"])

            _, md, _ = check(repo, "--format", "md")
            self.assertTrue(md.startswith("## Documentation impact\n"))
            self.assertIn("| app | docs/app.md<br>docs/ops.md | no<br>no | Documentation review required: "
                          "unacknowledged", md)
            self.assertIn("| core | docs/core.md | no |", md)
            self.assertIn("n/a (ERRORs cannot be acknowledged)", md)
            self.assertIn("app/\\[link\\](x).py", md)                             # escaped, not a link
            self.assertNotIn("[link](x)", md)

    def test_component_with_a_changed_doc_is_not_called_reviewed(self):
        with rules_repo() as repo:
            repo.write("app/main.py", LINES + "more\n"); repo.write("docs/ops.md", "# ops\nnew\n")
            _, md, _ = check(repo, "--format", "md")
            self.assertIn("| app | docs/app.md<br>docs/ops.md | no<br>yes | A mapped doc changed in this change set "
                          "(not a record of review) |", md)

    def test_output_is_deterministic(self):
        with rules_repo() as repo:
            self.scenario(repo)
            for fmt in ("text", "json", "md"):
                with self.subTest(fmt=fmt):
                    self.assertEqual(check(repo, "--format", fmt), check(repo, "--format", fmt))

    def test_base_mode_header(self):
        with rules_repo() as repo:
            repo.git("checkout", "-q", "-b", "feature")
            repo.write("core/base.py", LINES + "x\n"); repo.add_all(); repo.commit("f")
            _, text, _ = check(repo, "--base", "main")
            self.assertRegex(text.splitlines()[0], r"\| base main \(merge-base [0-9a-f]{7}\) \| 1 changes \|")
            self.assertIn("modified core/base.py [committed]", text)


class OutFiles(unittest.TestCase):
    def test_out_writes_the_three_reports_matching_stdout(self):
        with rules_repo() as repo:
            repo.write("app/main.py", LINES + "more\n")
            # A git-ignored folder (.local/ in .gitignore), so earlier reports are not new changes.
            outputs = {fmt: check(repo, "--format", fmt, "--out", ".local/r")[1] for fmt in ("text", "json", "md")}
            folder = repo.root / ".local" / "r"
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ["check.json", "check.md", "check.txt"])
            for fmt, name in (("text", "check.txt"), ("json", "check.json"), ("md", "check.md")):
                self.assertEqual((folder / name).read_bytes().decode("utf-8"), outputs[fmt])

    def test_default_out_and_refusals(self):
        with rules_repo() as repo:
            self.assertEqual(check(repo, "--out")[0], 0)
            self.assertTrue((repo.root / ".local" / "impact" / "check.md").is_file())
            for target, message in (("..", "inside the repository"), (".", "not its root"),
                                    (".git/x", "inside .git")):
                with self.subTest(target=target):
                    code, out, err = check(repo, "--out", target)
                    self.assertEqual((code, out), (2, ""))
                    self.assertIn(message, err)
            repo.write("tracked/check.md", "mine\n"); repo.git("add", "tracked/check.md"); repo.commit("t")
            code, _, err = check(repo, "--out", "tracked")
            self.assertEqual(code, 2)
            self.assertIn("refusing to overwrite a tracked file", err)
            self.assertEqual((repo.root / "tracked" / "check.md").read_text(), "mine\n")

    def test_failed_write_leaves_no_new_folder(self):
        with rules_repo() as repo:
            with mock.patch("tools.impact.cli.os.replace", side_effect=PermissionError(13, "locked")):
                code, out, err = check(repo, "--out", "new/deeper")
            self.assertEqual((code, out), (2, ""))
            self.assertIn("could not write the reports", err)
            self.assertFalse((repo.root / "new").exists())


class MkdirRace(unittest.TestCase):
    """83a QA suggestion 1: when mkdir(parents=True) creates a parent and then fails
    deeper, the cleanup must skip the folders that were never created and still remove
    the new parent (it used to stop at the first missing folder)."""

    def test_new_parent_is_removed_when_a_deeper_mkdir_fails(self):
        real_mkdir = Path.mkdir

        def partial(self, mode=0o777, parents=False, exist_ok=False):
            if self.name == "deepest":
                real_mkdir(self.parent.parent, exist_ok=True)               # "new" is created ...
                raise OSError(28, "No space left on device")                 # ... then the rest fails
            return real_mkdir(self, mode, parents, exist_ok)

        with rules_repo() as repo:
            with mock.patch.object(Path, "mkdir", partial):
                code, _, err = check(repo, "--out", "new/middle/deepest")
            self.assertEqual(code, 2)
            self.assertIn("No space left", err)
            self.assertFalse((repo.root / "new").exists())


class ReadOnly(unittest.TestCase):
    def test_check_without_out_writes_nothing(self):
        with rules_repo() as repo:
            Formats().scenario(repo)
            before = full_snapshot(repo.root)
            for fmt in ("text", "json", "md"):
                check(repo, "--format", fmt)
            check(repo, "--base", "main")
            self.assertEqual(full_snapshot(repo.root), before)


if __name__ == "__main__":
    unittest.main()
