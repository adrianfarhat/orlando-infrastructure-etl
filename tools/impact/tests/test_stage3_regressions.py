"""Regression tests for the Stage 3 independent-QA findings D1-D5 and L1-L7 (2026-11-19).
Each test is named after the finding it closes."""

import copy
import json
import random
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.impact import gitfiles, regexsafe
from tools.impact.config import LoadError, Problem, check_files, parse_config, parse_registry, read_yaml
from tools.impact.findings import Report, from_problems, render_json, render_text
from tools.impact.resolve import ambiguities

from .support import REGISTRY, TempRepo, valid_repo  # noqa: F401  (TempRepo used below)
from .test_cli import run, snapshot

REPO_ROOT = Path(__file__).resolve().parents[3]


def run_module(*argv, cwd=REPO_ROOT, pre=""):
    """Run `python -m tools.impact` as a real process; returns (code, stdout bytes, stderr text)."""
    code = f"{pre}import runpy, sys; sys.argv = ['impact', *{list(argv)!r}]; runpy.run_module('tools.impact', run_name='__main__')"
    r = subprocess.run([sys.executable, "-B", "-c", code], cwd=cwd, capture_output=True, timeout=120)
    return r.returncode, r.stdout, r.stderr.decode("utf-8", "replace")


class D1MalformedScalarsAreFindings(unittest.TestCase):
    CASES = {
        "bad int tag": "version: !!int abc\nregistry: r.yml\n",
        "bad float tag": "version: !!float x\nregistry: r.yml\n",
        "bad timestamp tag": "version: !!timestamp 2020-99-99\nregistry: r.yml\n",
        "bad bool tag": "version: !!bool maybe\nregistry: r.yml\n",
        "invalid plain date": "version: 1\nregistry: r.yml\nnote: 2020-13-45\n",
        "huge integer": "version: " + "9" * 5000 + "\nregistry: r.yml\n",
    }

    def test_read_yaml_raises_non_operational_load_error(self):
        for label, text in self.CASES.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "impact.yml"
                path.write_text(text, "utf-8")
                with self.assertRaises(LoadError) as ctx:
                    read_yaml(path)
                self.assertFalse(ctx.exception.operational)
                self.assertIn("not valid YAML", str(ctx.exception))

    def test_cli_exit_1_with_finding(self):
        for label, text in self.CASES.items():
            with self.subTest(label), valid_repo() as repo:
                repo.write("impact.yml", text)
                code, out, err = run("validate", "--root", str(repo.root))
                self.assertEqual((code, err), (1, ""))
                self.assertRegex(out, r"ERROR    registry-invalid:[0-9a-f]{10}  impact.yml  \(file\)  "
                                      r"impact.yml: not valid YAML")


class D2NoFindingIdCollisions(unittest.TestCase):
    def assert_no_collision(self, problems):
        findings = from_problems(problems)            # raises DuplicateFindingError on a collision
        self.assertEqual(len({f.id for f in findings}), len(findings))
        self.assertTrue(any(p.severity == "ERROR" for p in problems))

    def test_two_unknown_exempt_purposes(self):
        _, problems = parse_config({"version": 1, "registry": "r.yml",
                                    "doc_obligation": {"exempt_purposes": ["tset", "docz"]}})
        self.assert_no_collision(problems)

    def test_two_unknown_dependencies(self):
        data = {"version": 1, "components": [{"id": "a", "paths": ["a/**"], "docs": [], "depends_on": [
            {"id": "x", "basis": "inferred", "note": "n"}, {"id": "y", "basis": "inferred", "note": "n"}]}]}
        _, problems = parse_registry(data, "r.yml")
        self.assert_no_collision(problems)

    def test_keys_that_print_the_same(self):
        for keys in ((1, "1"), (True, "True"), (None, "None")):
            with self.subTest(keys=keys):
                data = {"version": 1, "registry": "r.yml", keys[0]: 1, keys[1]: 2}
                _, problems = parse_config(data)
                self.assert_no_collision(problems)
                comp = {"id": "a", "paths": ["a/**"], "docs": [], keys[0]: 1, keys[1]: 2}
                _, problems = parse_registry({"version": 1, "components": [comp], keys[0]: 1, keys[1]: 2}, "r.yml")
                self.assert_no_collision(problems)

    def test_interface_path_equal_to_contract(self):
        config, _ = parse_config({"version": 1, "registry": "r.yml"})
        registry, problems = parse_registry({"version": 1, "components": [{
            "id": "a", "paths": ["a/**"], "docs": [],
            "interfaces": [{"path": "a/x.md", "contract": "a/x.md"}]}]}, "r.yml")
        self.assertEqual(problems, [])
        self.assert_no_collision(check_files(config, registry, "r.yml", ["a/y.md"]))

    def test_cli_exit_1_not_2(self):
        reg = json.loads(json.dumps(REGISTRY))
        reg["components"][0]["depends_on"] = [{"id": "x", "basis": "inferred", "note": "n"},
                                              {"id": "y", "basis": "inferred", "note": "n"}]
        with valid_repo(registry=reg) as repo:
            code, out, err = run("validate", "--root", str(repo.root))
        self.assertEqual((code, err), (1, ""))
        self.assertEqual(out.count("unknown component"), 2)

    def test_fuzzed_configurations_never_collide(self):
        """Seeded mutation fuzz of both files: any input must give findings, never a
        DuplicateFindingError (which would turn a bad configuration into exit 2)."""
        rng = random.Random(83)
        values = [None, True, False, 0, 1, -1, 1.5, "", "x", "1", "True", "None", "a/**", "../x", "/abs",
                  "**/**/**/**/x", "*a*b*c*d", "docs/a.md", "WARNING", "ERROR", "off", "code", "inferred",
                  [], [1, "1"], ["a", "a"], {}, {"1": 1, 1: 2}, {"id": "a"}, "(a+)+", "SECRET"]
        hashable_keys = [v for v in values if not isinstance(v, (list, dict))] + [
            "paths", "docs", "id", "exclude", "match", "kind", "version", "registry"]
        base_cfg = {"version": 1, "registry": "r.yml", "purposes": [{"purpose": "doc", "paths": ["docs/**"]}],
                    "rules": {"unregistered-path": "WARNING"}, "doc_obligation": {"exempt_purposes": ["test"]},
                    "interfaces": [{"kind": "api", "paths": ["a/**/route.ts"]}], "acks": {"min_reason_length": 5}}
        base_reg = copy.deepcopy(REGISTRY)
        base_reg["components"][0].update(depends_on=[], interfaces=[{"path": "app/r.ts", "contract": "docs/app.md"}])

        def mutate(node, depth=0):
            if isinstance(node, dict) and node:
                key = rng.choice(list(node))
                choice = rng.random()
                if choice < 0.3:
                    node[key] = rng.choice(values)
                elif choice < 0.5:
                    node[rng.choice(hashable_keys)] = copy.deepcopy(rng.choice(values))
                elif choice < 0.6:
                    node.pop(key)
                elif depth < 4:
                    mutate(node[key], depth + 1)
            elif isinstance(node, list):
                if node and rng.random() < 0.6 and depth < 4:
                    mutate(rng.choice(node), depth + 1)
                else:
                    node.append(copy.deepcopy(rng.choice(values + [node[0] if node else None])))

        files = ["app/main.py", "docs/app.md", "a/y.md", "app/r.ts"]
        for _ in range(3000):
            cfg, reg = copy.deepcopy(base_cfg), copy.deepcopy(base_reg)
            for _ in range(rng.randint(1, 4)):
                mutate(cfg if rng.random() < 0.4 else reg)
            config, problems = parse_config(cfg)
            registry, reg_problems = parse_registry(reg, "r.yml")
            problems += reg_problems
            problems += check_files(config, registry, "r.yml", files)
            problems += ambiguities(config, registry, "r.yml", files)
            from_problems(problems)                     # must not raise


class D3DotIsNeverALiteral(unittest.TestCase):
    def test_dot_is_any_character(self):
        self.assertIsNone(regexsafe.check("a.b").literal)
        self.assertIsNone(regexsafe.check("foo.bar").literal)
        self.assertEqual(regexsafe.check("a\\.b").literal, "a.b")
        rx = re.compile("a.b")
        self.assertTrue(regexsafe.scan(rx, regexsafe.check("a.b"), "xx aXb yy").matched)

    def test_scan_agrees_with_re_line_by_line(self):
        rng = random.Random(3)
        patterns = ["a.b", "foo.bar", "a\\.b", "x.{0,2}y", "[ab].c", "^a.", ".$", "(a|.)b", "DATABASE_URL",
                    "\\w.\\d", "a.?b"]
        for pattern in patterns:
            rx, profile = re.compile(pattern), regexsafe.check(pattern)
            for _ in range(200):
                text = "\n".join("".join(rng.choice("abcxyf.oXr19_ \t") for _ in range(rng.randint(0, 12)))
                                 for _ in range(rng.randint(1, 4)))
                expected = any(rx.search(line) for line in text.splitlines())
                with self.subTest(pattern=pattern, text=text):
                    self.assertEqual(regexsafe.scan(rx, profile, text).matched, expected)


class D4StartupFailuresExit2(unittest.TestCase):
    def test_missing_dependency_exits_2(self):
        code, out, err = run_module("validate", pre="import sys; sys.modules['ruamel'] = None; ")
        self.assertEqual(code, 2, err)
        self.assertEqual(out, b"")
        self.assertIn("impact: error: cannot start", err)

    def test_old_python_exits_2(self):
        pre = ("import sys, collections; V = collections.namedtuple('V', 'major minor micro releaselevel serial'); "
               "sys.version_info = V(3, 12, 0, 'final', 0); ")
        code, out, err = run_module("validate", pre=pre)
        self.assertEqual((code, out), (2, b""))
        self.assertIn("Python 3.13 or later is required (found 3.12)", err)


class D5StdoutIsLfAndMatchesOutFiles(unittest.TestCase):
    def test_stdout_bytes_equal_out_files(self):
        with valid_repo() as repo:
            for fmt, name in (("text", "validate.txt"), ("json", "validate.json")):
                with self.subTest(fmt=fmt):
                    code, out, err = run_module("validate", "--root", str(repo.root), "--format", fmt, "--out")
                    self.assertEqual((code, err), (0, ""))
                    self.assertNotIn(b"\r", out)
                    self.assertEqual(out, (repo.root / ".local" / "impact" / name).read_bytes())


class LowerFindingRegressions(unittest.TestCase):
    def test_L1_empty_out_and_repository_root_are_refused(self):
        with valid_repo() as repo:
            for target in ("", ".", str(repo.root)):
                with self.subTest(target=target):
                    before = snapshot(repo.root)
                    code, out, err = run("validate", "--root", str(repo.root), "--out", target)
                    self.assertEqual((code, out), (2, ""))
                    self.assertIn("impact: error:", err)
                    self.assertEqual(snapshot(repo.root), before)

    def test_L2_folder_in_the_way_is_an_output_error_and_reports_stay_consistent(self):
        with valid_repo() as repo:
            folder = repo.root / "reports"
            folder.mkdir()
            (folder / "validate.txt").write_text("old\n", "utf-8")
            (folder / "validate.json").mkdir()
            code, out, err = run("validate", "--root", str(repo.root), "--out", "reports")
            self.assertEqual((code, out), (2, ""))
            self.assertIn("a folder is in the way", err)
            self.assertNotIn("internal error", err)
            self.assertEqual((folder / "validate.txt").read_text("utf-8"), "old\n")   # untouched
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ["validate.json", "validate.txt"])

    def test_L2_os_error_while_writing_is_an_output_error(self):
        with valid_repo() as repo:
            with mock.patch("tools.impact.cli.os.replace", side_effect=PermissionError(13, "Permission denied")):
                code, out, err = run("validate", "--root", str(repo.root), "--out")
            self.assertEqual((code, out), (2, ""))
            self.assertIn("could not write the reports", err)
            self.assertEqual([p.name for p in (repo.root / ".local" / "impact").iterdir()], [])  # temps removed

    def test_L3_brackets_in_out_are_literal(self):
        with valid_repo() as repo:
            repo.write("a1/validate.txt", "tracked\n")
            repo.add_all()
            repo.commit("a1")
            code, _, err = run("validate", "--root", str(repo.root), "--out", "a[1]")
            self.assertEqual((code, err), (0, ""))                               # no false refusal
            self.assertEqual((repo.root / "a1" / "validate.txt").read_text("utf-8"), "tracked\n")
            repo.write("b[1]/validate.txt", "tracked\n")
            repo.add_all()
            repo.commit("b")
            code, _, err = run("validate", "--root", str(repo.root), "--out", "b[1]")
            self.assertEqual(code, 2)                                            # real tracked file
            self.assertIn("refusing to overwrite a tracked file", err)

    def test_L4_text_report_escapes_format_characters(self):
        name = "tie/a‮b.md"
        problem = Problem("r.yml", f"path {name}", name, "registry-incomplete", "WARNING", f"ambiguous: {name}")
        report = Report("validate", None, 1, ("r.yml",), from_problems([problem]))
        text = render_text(report)
        self.assertNotIn("‮", text)
        self.assertIn("tie/a\\u202eb.md", text)
        self.assertIn("‮", json.loads(render_json(report))["findings"][0]["subject"])  # JSON exact

    def test_L4_already_escaped_names_are_not_escaped_twice(self):
        problem = Problem("(working tree)", "file name", "tab\\there.py", "unsupported-path", "WARNING",
                          "control character in path; the file is not analysed: tab\\there.py")
        text = render_text(Report("validate", None, 1, (), from_problems([problem])))
        self.assertIn("not analysed: tab\\there.py\n", text)
        self.assertNotIn("tab\\\\there", text)

    def test_L5_long_unsupported_names_are_truncated(self):
        listing = gitfiles.parse_listing(b"x\t" + b"y" * 5000 + b"\0")
        shown = listing.unsupported[0].shown
        self.assertLess(len(shown), 260)
        self.assertIn("(5002 characters)", shown)

    def test_L6_huge_config_values_do_not_flood_messages(self):
        value = [["x" * 100] * 100] * 100
        _, problems = parse_config({"version": value, "registry": "r.yml"})
        self.assertTrue(problems)
        self.assertTrue(all(len(p.message) < 300 for p in problems))

    def test_L7_head_reports_git_failures(self):
        failed = subprocess.CompletedProcess(["git"], 128, b"", b"fatal: bad object HEAD\n")
        with mock.patch("tools.impact.gitfiles.subprocess.run", return_value=failed):
            with self.assertRaisesRegex(gitfiles.GitError, "bad object HEAD"):
                gitfiles.head(Path("."))
        # An unborn branch, as real git reports it (measured): HEAD^{commit} does not resolve
        # (exit 1, silent), HEAD is a symbolic ref, and that ref does not exist (exit 1, silent).
        unborn = [subprocess.CompletedProcess(["git"], 1, b"", b""),
                  subprocess.CompletedProcess(["git"], 0, b"refs/heads/main\n", b""),
                  subprocess.CompletedProcess(["git"], 1, b"", b"")]
        with mock.patch("tools.impact.gitfiles.subprocess.run", side_effect=unborn):
            self.assertIsNone(gitfiles.head(Path(".")))
        # Silent exit 1 everywhere (HEAD not a symbolic ref) is NOT "no commits".
        silent = subprocess.CompletedProcess(["git"], 1, b"", b"")
        with mock.patch("tools.impact.gitfiles.subprocess.run", return_value=silent):
            with self.assertRaises(gitfiles.GitError):
                gitfiles.head(Path("."))


def fan_out(levels: int, field: str = "version") -> str:
    """A tiny YAML file whose `field` expands to 9**levels items through aliases."""
    lines = ["a0: &a0 [x, x, x, x, x, x, x, x, x]"]
    lines += [f"a{i}: &a{i} [" + ", ".join([f"*a{i - 1}"] * 9) + "]" for i in range(1, levels + 1)]
    return "\n".join(lines) + f"\n{field}: *a{levels}\n"


class FinalQaRegressions(unittest.TestCase):
    """Second independent QA round: residuals of L2, L5, L6 and a start-up gap."""

    def test_L6_alias_fan_out_cannot_hang(self):
        # QA: 10 levels took 66.6 s through repr(); each level ~9x more.
        import time
        cases = {
            "version": fan_out(12) + "registry: r.yml\n",
            "exempt_purposes": fan_out(12, "x") + "version: 1\nregistry: r.yml\n"
                               "doc_obligation: {exempt_purposes: [*a12, *a12]}\n",
            "rule value": fan_out(12, "x") + "version: 1\nregistry: r.yml\nrules: {content-trigger: *a12}\n",
            "ack length": fan_out(12, "x") + "version: 1\nregistry: r.yml\nacks: {min_reason_length: *a12}\n",
        }
        for label, text in cases.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "impact.yml"
                path.write_text(text, "utf-8")
                start = time.perf_counter()
                _, problems = parse_config(read_yaml(path))
                self.assertLess(time.perf_counter() - start, 2.0)
                self.assertTrue(problems)
                self.assertTrue(all(len(p.message) < 300 for p in problems))
        data = {"version": 1, "components": [{"id": "a", "paths": ["a/**"], "docs": [], "depends_on": [
            {"id": "b", "basis": [[["x"] * 9] * 9] * 9, "evidence": "e"}]}]}
        _, problems = parse_registry(data, "r.yml")
        self.assertTrue(all(len(p.message) < 300 for p in problems))

    def test_L6_bounded_repr_never_reprs_containers(self):
        from tools.impact.paths import bounded_repr
        big = [[["x"] * 9] * 9] * 9
        self.assertEqual(bounded_repr(big), "<list of 9 items>")
        self.assertEqual(bounded_repr({"a": big}), "<dict of 1 items>")
        self.assertEqual(bounded_repr("y" * 500), repr("y" * 80) + "... (500 characters)")
        self.assertEqual(bounded_repr(None), "None")
        self.assertTrue(bounded_repr(10 ** 200).endswith("(201 digits)"))

    def test_L5_config_values_cannot_make_report_fields_unbounded(self):
        long_path = "docs/" + "d" * 100_000 + ".md"
        long_pattern = "app/" + "p" * 100_000 + "/**"
        reg = json.loads(json.dumps(REGISTRY))
        reg["components"][0]["docs"] = ["docs/app.md", long_path]
        reg["components"].append({"id": "x" * 100_000, "paths": ["x/**"], "docs": []})
        reg["components"].append({"id": "pat", "paths": [long_pattern], "docs": [], "depends_on": [
            {"id": "q" * 100_000, "basis": "inferred", "note": "n"}]})
        reg["content_triggers"][0]["paths"] = ["**/*.py", long_pattern]
        with valid_repo(registry=reg) as repo:
            for fmt in ("json", "text"):
                with self.subTest(fmt=fmt):
                    code, out, err = run("validate", "--root", str(repo.root), "--format", fmt)
                    self.assertEqual((code, err), (1, ""))
                    if fmt == "json":
                        fields = [v for f in json.loads(out)["findings"] for v in f.values()]
                        self.assertLess(max(len(v) for v in fields), 1000)
                    self.assertLess(max(len(line) for line in out.splitlines()), 1500)

    def test_L5_long_config_paths_ids_and_patterns_are_rejected(self):
        from tools.impact.paths import PathError, normalize, normalize_pattern
        with self.assertRaisesRegex(PathError, "longer than 4096 bytes"):
            normalize("d/" * 3000)
        with self.assertRaisesRegex(PathError, "segment longer than 255 bytes"):
            normalize("d/" + "x" * 256)
        with self.assertRaisesRegex(PathError, "longer than 4096 bytes"):
            normalize_pattern("a/" * 2100 + "**")
        _, problems = parse_registry({"version": 1, "components": [
            {"id": "a" * 101, "paths": ["a/**"], "docs": []}]}, "r.yml")
        self.assertTrue(any("longer than 100 characters" in p.message for p in problems))

    def test_findings_fields_are_capped_but_ids_use_full_values(self):
        long_a, long_b = "s" * 10_000 + "a", "s" * 10_000 + "b"
        findings = from_problems([Problem("r.yml", "loc", long_a, "registry-incomplete", "WARNING", long_a),
                                  Problem("r.yml", "loc", long_b, "registry-incomplete", "WARNING", long_b)])
        self.assertEqual(len({f.id for f in findings}), 2)                  # distinct despite the cut
        self.assertTrue(all(len(f.subject) < 6100 and len(f.message) < 6100 for f in findings))

    def _two_runs(self, repo, patch):
        """A successful --out run, then a second run under `patch`; returns the folder."""
        self.assertEqual(run("validate", "--root", str(repo.root), "--out", "r")[0], 0)
        folder = repo.root / "r"
        for name in ("validate.txt", "validate.json"):
            (folder / name).write_text(f"old {name}\n", "utf-8")
        with patch:
            code, out, err = run("validate", "--root", str(repo.root), "--out", "r")
        return folder, code, out, err

    def test_L2_second_replace_failure_restores_both_old_reports(self):
        real_replace = __import__("os").replace

        def failing(src, dst):
            if str(src).endswith(".tmp") and str(dst).endswith("validate.json"):
                raise PermissionError(13, "The process cannot access the file")
            return real_replace(src, dst)

        with valid_repo() as repo:
            folder, code, out, err = self._two_runs(repo, mock.patch("tools.impact.cli.os.replace", side_effect=failing))
            self.assertEqual((code, out), (2, ""))
            self.assertIn("could not write the reports", err)
            self.assertNotIn("inconsistent", err)
            self.assertEqual((folder / "validate.txt").read_text("utf-8"), "old validate.txt\n")
            self.assertEqual((folder / "validate.json").read_text("utf-8"), "old validate.json\n")
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ["validate.json", "validate.txt"])

    def test_L2_read_only_report_is_refused_before_any_change(self):
        import os
        import stat
        with valid_repo() as repo:
            self.assertEqual(run("validate", "--root", str(repo.root), "--out", "r")[0], 0)
            folder = repo.root / "r"
            for name in ("validate.txt", "validate.json"):
                (folder / name).write_text(f"old {name}\n", "utf-8")
            os.chmod(folder / "validate.json", stat.S_IREAD)
            try:
                code, out, err = run("validate", "--root", str(repo.root), "--out", "r")
                self.assertEqual((code, out), (2, ""))
                self.assertIn("read-only", err)
                self.assertEqual((folder / "validate.txt").read_text("utf-8"), "old validate.txt\n")
                self.assertEqual((folder / "validate.json").read_text("utf-8"), "old validate.json\n")
            finally:
                os.chmod(folder / "validate.json", stat.S_IREAD | stat.S_IWRITE)

    def test_L2_failed_restore_keeps_the_old_report_and_says_so(self):
        real_replace = __import__("os").replace

        def failing(src, dst):
            if str(src).endswith(".tmp") and str(dst).endswith("validate.json"):
                raise PermissionError(13, "locked")
            if str(src).endswith(".old") and str(dst).endswith("validate.txt"):
                raise PermissionError(13, "locked")
            return real_replace(src, dst)

        with valid_repo() as repo:
            folder, code, out, err = self._two_runs(repo, mock.patch("tools.impact.cli.os.replace", side_effect=failing))
            self.assertEqual((code, out), (2, ""))
            self.assertIn("may be inconsistent", err)
            kept = [p for p in folder.iterdir() if p.name.endswith(".old")]
            self.assertEqual(len(kept), 1)                                  # the old validate.txt survives
            self.assertEqual(kept[0].read_text("utf-8"), "old validate.txt\n")
            self.assertIn(kept[0].name, err)

    def test_startup_failure_other_than_import_error_exits_2(self):
        pre = ("import sys, types, tools.impact; m = types.ModuleType('tools.impact.cli'); "
               "m.__getattr__ = lambda name: (_ for _ in ()).throw(RuntimeError('broken at import')); "
               "sys.modules['tools.impact.cli'] = m; ")
        code, out, err = run_module("validate", pre=pre)
        self.assertEqual((code, out), (2, b""))
        self.assertIn("internal error while starting: RuntimeError: broken at import", err)

    def test_head_with_empty_output_is_an_error(self):
        empty = subprocess.CompletedProcess(["git"], 0, b"", b"")
        with mock.patch("tools.impact.gitfiles.subprocess.run", return_value=empty):
            with self.assertRaises(gitfiles.GitError):
                gitfiles.head(Path("."))


class ThirdQaRoundRegressions(unittest.TestCase):
    """Second independent QA pass (2026-11-19): three low-severity residuals."""

    def test_failed_move_aside_leaves_no_stray_backup_file(self):
        real_replace = __import__("os").replace

        def failing(src, dst):
            if str(src).endswith("validate.json") and str(dst).endswith(".old"):   # moving aside fails
                raise PermissionError(13, "The process cannot access the file")
            return real_replace(src, dst)

        with valid_repo() as repo:
            self.assertEqual(run("validate", "--root", str(repo.root), "--out", "r")[0], 0)
            folder = repo.root / "r"
            for name in ("validate.txt", "validate.json"):
                (folder / name).write_text(f"old {name}\n", "utf-8")
            with mock.patch("tools.impact.cli.os.replace", side_effect=failing):
                code, out, err = run("validate", "--root", str(repo.root), "--out", "r")
            self.assertEqual((code, out), (2, ""))
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ["validate.json", "validate.txt"])
            self.assertEqual((folder / "validate.txt").read_text("utf-8"), "old validate.txt\n")
            self.assertEqual((folder / "validate.json").read_text("utf-8"), "old validate.json\n")

    def test_text_header_escapes_and_bounds_source_names(self):
        sources = ("impact.yml", "registry/‮c​.yml")
        text = render_text(Report("validate", None, 1, sources, ()))
        header = text.splitlines()[0]
        self.assertNotIn("‮", header)
        self.assertNotIn("​", header)
        self.assertIn("registry/\\u202ec\\u200b.yml", header)
        long = render_text(Report("validate", None, 1, ("x" * 50_000,), ())).splitlines()[0]
        self.assertLess(len(long), 1200)

    def test_head_distinguishes_no_commits_from_a_corrupt_head(self):
        with TempRepo() as repo:                                     # fresh: no commits
            self.assertIsNone(gitfiles.head(repo.root))
        with TempRepo() as repo:                                     # orphan branch
            repo.write("a.txt", "a"); repo.add_all(); repo.commit()
            repo.git("checkout", "-q", "--orphan", "other")
            self.assertIsNone(gitfiles.head(repo.root))
        corruptions = {
            "branch ref with garbage content": lambda r: (r.root / ".git/refs/heads/main").write_text("not-a-sha\n"),
            "branch ref to a missing object": lambda r: (r.root / ".git/refs/heads/main").write_text(
                "0123456789abcdef0123456789abcdef01234567\n"),
            "HEAD to a ref name with a control character": lambda r: (r.root / ".git/HEAD").write_text(
                "ref: refs/heads/ma\x01in\n"),
        }
        for label, corrupt in corruptions.items():
            with self.subTest(label), TempRepo() as repo:
                repo.write("a.txt", "a"); repo.add_all(); repo.commit()
                corrupt(repo)
                with self.assertRaises(gitfiles.GitError):
                    gitfiles.head(repo.root)

    def test_corrupt_head_is_exit_2_not_no_commits(self):
        with valid_repo() as repo:
            (repo.root / ".git/refs/heads/main").write_text("not-a-sha\n")
            code, out, err = run("validate", "--root", str(repo.root))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("HEAD does not point to a valid commit", err)

    def test_echoed_arguments_on_stderr_are_escaped_and_bounded(self):
        code, out, err = run("validate", "--root", "no‮such" + "z" * 30_000)
        self.assertEqual((code, out), (2, ""))
        self.assertNotIn("‮", err)
        self.assertLess(len(err), 2500)
        with valid_repo() as repo:
            code, out, err = run("validate", "--root", str(repo.root), "--out", "..\\out‮")
            self.assertEqual(code, 2)
            self.assertNotIn("‮", err)


class FourthQaRoundRegressions(unittest.TestCase):
    """Third independent QA pass (2026-11-19): internal-error and start-up stderr."""

    EVIL = "x\u202e\u200b\x1b[31m" + "A" * 30_000

    # A stderr line holds at most 2,000 characters of escaped variable text (plus a
    # "... (N characters)" suffix) inside fixed wording of under 120 characters.
    MAX_LINE = 2000 + 40 + 120

    def assert_safe_stderr(self, err: str):
        self.assertNotIn("\u202e", err)
        self.assertNotIn("\u200b", err)
        self.assertNotIn("\x1b", err)
        self.assertLess(max(len(line) for line in err.splitlines()), self.MAX_LINE)

    def test_internal_error_traceback_is_escaped_and_bounded(self):
        with valid_repo() as repo:
            with mock.patch("tools.impact.cli.from_problems", side_effect=ValueError(self.EVIL)):
                code, out, err = run("validate", "--root", str(repo.root))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("internal error", err)
        self.assertIn("ValueError: x\\u202e\\u200b\\x1b[31m", err)
        self.assert_safe_stderr(err)

    def test_long_traceback_keeps_only_the_last_lines(self):
        # Python collapses identical repeated frames, so build 100 DISTINCT functions
        # (f0 calls f1 ... f99 raises) to get a genuinely long traceback.
        namespace = {}
        source = "\n".join(f"def f{i}():\n    return f{i + 1}()" for i in range(99))
        source += "\ndef f99():\n    raise RuntimeError('bottom')\n"
        exec(compile(source, "<generated>", "exec"), namespace)
        with valid_repo() as repo:
            with mock.patch("tools.impact.cli.from_problems", side_effect=lambda _: namespace["f0"]()):
                code, out, err = run("validate", "--root", str(repo.root))
        self.assertEqual(code, 2)
        self.assertIn("earlier traceback lines omitted", err)
        self.assertIn("RuntimeError: bottom", err)
        self.assertLess(len(err.splitlines()), 70)

    def test_startup_messages_are_escaped_and_bounded(self):
        evil = repr(self.EVIL)
        for kind, pre in {
            "ImportError": f"import sys, types, tools.impact; m = types.ModuleType('tools.impact.cli'); "
                           f"m.__getattr__ = lambda name: (_ for _ in ()).throw(ImportError({evil})); "
                           f"sys.modules['tools.impact.cli'] = m; ",
            "RuntimeError": f"import sys, types, tools.impact; m = types.ModuleType('tools.impact.cli'); "
                            f"m.__getattr__ = lambda name: (_ for _ in ()).throw(RuntimeError({evil})); "
                            f"sys.modules['tools.impact.cli'] = m; ",
        }.items():
            with self.subTest(kind):
                code, out, err = run_module("validate", pre=pre)
                self.assertEqual((code, out), (2, b""))
                self.assertIn("\\u202e", err)
                self.assert_safe_stderr(err)

    def test_argparse_errors_are_escaped_and_bounded(self):
        for argv in (["validate", "--format", self.EVIL], [self.EVIL], ["validate", "--" + self.EVIL]):
            with self.subTest(argv=argv[-1][:5]):
                code, out, err = run(*argv)
                self.assertEqual((code, out), (2, ""))
                self.assertIn("impact: error:", err)
                self.assertIn("usage:", err)
                self.assert_safe_stderr(err)

    def test_echoed_windows_paths_keep_single_backslashes(self):
        code, _, err = run("validate", "--root", "C:\\no\\such\\folder")
        self.assertEqual(code, 2)
        self.assertIn("C:\\no\\such\\folder", err)
        self.assertNotIn("C:\\\\no", err)


if __name__ == "__main__":
    unittest.main()
