"""Stage 83b-4: `python -m tools.impact plan --paths ...` (predictions only)."""

import json
import unittest
from unittest import mock

from .test_check_cli import full_snapshot
from .test_cli import run
from .test_rules import IMPACT, LINES, REGISTRY, rules_repo


def plan(repo, *args):
    return run("plan", "--root", str(repo.root), *args)


def plan_json(repo, *paths):
    code, out, err = plan(repo, "--format", "json", "--paths", *paths)
    return code, (json.loads(out) if out else None), err


def by_path(data):
    return {p["path"]: p for p in data["predictions"]}


def rules_of(prediction):
    return sorted((r["rule"], r["severity"]) for r in prediction["rules"])


class Predictions(unittest.TestCase):
    def test_registered_path(self):
        with rules_repo() as repo:
            code, data, err = plan_json(repo, "core/base.py")
            self.assertEqual((code, err), (0, ""))
            p = by_path(data)["core/base.py"]
            self.assertEqual((p["exists"], p["ignored"], p["purpose"], p["components"], p["doc_obligation"]),
                             (True, False, "code", ["core"], True))
            self.assertEqual([(d["doc"], d["kind"]) for d in p["docs"]],
                             [("docs/core.md", "reviewed"), ("docs/ops.md", "trigger")])
            self.assertEqual([(d["component"], d["depends_on"], d["basis"]) for d in p["dependents"]],
                             [("lib", "core", "inferred")])                  # one hop: app (-> lib) not listed
            self.assertEqual((p["tests"], p["tests_basis"]), ([], "not mapped"))
            self.assertEqual(rules_of(p), [("content-trigger", "WARNING"), ("docs-not-updated", "WARNING"),
                                           ("stale-reference", "ERROR")])

    def test_tests_are_component_level_suggestions(self):
        with rules_repo() as repo:
            p = by_path(plan_json(repo, "app/main.py")[1])["app/main.py"]
            self.assertEqual(p["tests"], ["app/tests/test_main.py"])
            self.assertIn("not a verified test mapping", p["tests_basis"])

    def test_multiple_paths_are_normalised_deduplicated_and_sorted(self):
        with rules_repo() as repo:
            code, data, _ = plan_json(repo, "lib/util.py", "./app/main.py", "app\\main.py", "app/main.py")
            self.assertEqual(code, 0)
            self.assertEqual([p["path"] for p in data["predictions"]], ["app/main.py", "lib/util.py"])
            self.assertEqual(data["summary"], {"paths": 2, "exit_code": 0})

    def test_unregistered_and_nonexistent_paths(self):
        with rules_repo() as repo:
            p = by_path(plan_json(repo, "misc/new.py")[1])["misc/new.py"]
            self.assertEqual((p["exists"], p["components"], p["doc_obligation"]), (False, [], False))
            self.assertEqual(rules_of(p), [("content-trigger", "WARNING"), ("unregistered-path", "WARNING")])
            self.assertEqual([d["doc"] for d in p["docs"]], ["docs/ops.md"])     # trigger docs still listed

    def test_ignored_path(self):
        with rules_repo() as repo:
            p = by_path(plan_json(repo, "data/raw/x.py")[1])["data/raw/x.py"]
            self.assertEqual((p["ignored"], p["components"], p["docs"], p["rules"]), (True, [], [], []))
            _, text, _ = plan(repo, "--paths", "data/raw/x.py")
            self.assertIn("data/raw/x.py (new file): ignored (impact.yml ignore); check never analyses it", text)

    def test_interfaces_and_contracts(self):
        with rules_repo() as repo:
            data = by_path(plan_json(repo, "api/items/route.ts", "api/orders/route.ts")[1])
            listed, new = data["api/items/route.ts"], data["api/orders/route.ts"]
            self.assertEqual(listed["contracts"], [["api/items/route.ts", "docs/api.md"]])
            self.assertNotIn("new-interface-without-contract", [r["rule"] for r in listed["rules"]])
            self.assertEqual((new["exists"], new["contracts"]), (False, []))
            self.assertIn(("new-interface-without-contract", "ERROR"), rules_of(new))

    def test_tied_components(self):
        with rules_repo() as repo:
            p = by_path(plan_json(repo, "shared/s.py")[1])["shared/s.py"]
            self.assertEqual(p["components"], ["tie-a", "tie-b"])
            self.assertEqual({(d["doc"], tuple(d["sources"])) for d in p["docs"] if d["kind"] == "reviewed"},
                             {("docs/app.md", ("tie-a",)), ("docs/lib.md", ("tie-b",))})

    def test_exempt_purpose_and_empty_docs(self):
        with rules_repo() as repo:
            data = by_path(plan_json(repo, "app/tests/test_x.py", "notes/n.txt", "lab/new.py")[1])
            test = data["app/tests/test_x.py"]
            self.assertEqual((test["purpose"], test["doc_obligation"]), ("test", False))
            self.assertEqual(rules_of(test), [])                                 # no doc or trigger rules
            self.assertTrue(all("no documentation obligation" in d["condition"] for d in test["docs"]
                                if d["kind"] == "reviewed"))
            self.assertEqual((data["notes/n.txt"]["docs"], data["notes/n.txt"]["doc_obligation"]), ([], False))
            self.assertEqual(data["lab/new.py"]["purpose"], "experimental")

    def test_config_changed_and_current_references(self):
        with rules_repo() as repo:
            repo.write("docs/refs.md", "See `app/old.py` and `README.md`.\n"); repo.add_all(); repo.commit("refs")
            data = by_path(plan_json(repo, "impact.yml", "app/old.py", "README.md", "app/main.py", "core/base.py")[1])
            self.assertIn(("config-changed", "WARNING"), rules_of(data["impact.yml"]))
            self.assertEqual(data["app/old.py"]["referenced_by"], ["docs/refs.md"])
            self.assertEqual(data["README.md"]["referenced_by"], ["docs/refs.md", "registry/components.yml"])
            # The registry's dependency evidence "app/main.py imports lib" is a real reference.
            self.assertEqual(data["app/main.py"]["referenced_by"], ["registry/components.yml"])
            self.assertEqual(data["core/base.py"]["referenced_by"], [])
            stale = next(r for r in data["app/old.py"]["rules"] if r["rule"] == "stale-reference")
            self.assertIn("currently referenced by docs/refs.md", stale["condition"])
            self.assertNotIn("stale-reference", [r["rule"] for r in by_path(plan_json(repo, "app/nope.py")[1])
                                                 ["app/nope.py"]["rules"]])        # a new file cannot be stale

    def test_predictions_are_not_findings(self):
        with rules_repo() as repo:
            code, data, _ = plan_json(repo, "api/orders/route.ts")              # an ERROR rule would apply
            self.assertEqual(code, 0)
            self.assertNotIn("findings", data)
            self.assertIn("no findings", data["note"])


class QaRoundOneFixes(unittest.TestCase):
    """D1: rules switched off are not predicted; D2: Git-ignored paths and exact
    existence; D3: no content-trigger docs for exempt purposes. Each is compared with
    what `check` actually does."""

    def test_d1_rules_switched_off_are_not_predicted(self):
        off = {**IMPACT, "rules": {**IMPACT["rules"], "unregistered-path": "off", "docs-not-updated": "off",
                                   "content-trigger": "off"}}
        with rules_repo(impact=off) as repo:
            data = by_path(plan_json(repo, "core/base.py", "misc/new.py", "api/orders/route.ts", "impact.yml")[1])
            self.assertEqual(rules_of(data["core/base.py"]), [("stale-reference", "ERROR")])      # fixed rule kept
            self.assertEqual(rules_of(data["misc/new.py"]), [])
            self.assertEqual(rules_of(data["api/orders/route.ts"]), [("new-interface-without-contract", "ERROR")])
            self.assertEqual(rules_of(data["impact.yml"]), [("config-changed", "WARNING"), ("stale-reference", "ERROR")])
            self.assertIn("docs/ops.md", [d["doc"] for d in data["core/base.py"]["docs"]])  # INFO kept, as in check
            # check agrees: none of the switched-off rules produces a finding
            repo.write("core/base.py", LINES + "SECRET\n"); repo.write("misc/new.py", "SECRET\n")
            _, out, _ = run("check", "--root", str(repo.root), "--format", "json")
            self.assertEqual({f["rule"] for f in json.loads(out)["findings"]}, set())

    def test_d2_git_ignored_paths(self):
        with rules_repo() as repo:
            repo.write(".gitignore", ".local/\napp/gen/\n*.log\n!app/keep.log\n")
            repo.write("app/gen/tracked.py", "t\n"); repo.git("add", "-f", "app/gen/tracked.py")
            repo.git("add", ".gitignore"); repo.commit("ignore")
            repo.write("app/gen/untracked.py", "SECRET\n")                    # exists on disk, ignored by Git
            repo.write("app/keep.log", "k\n")
            data = by_path(plan_json(repo, "app/gen/untracked.py", "app/gen/new.py", "app/gen/tracked.py",
                                     "app/keep.log", "data/raw/x.log", "data/raw/x.py")[1])
            for path in ("app/gen/untracked.py", "app/gen/new.py"):
                with self.subTest(path=path):
                    p = data[path]
                    self.assertEqual((p["ignored"], p["ignored_by"], p["exists"], p["rules"], p["docs"]),
                                     (True, ".gitignore", False, [], []))
            tracked = data["app/gen/tracked.py"]                                # tracked: Git never ignores it
            self.assertEqual((tracked["ignored"], tracked["exists"], tracked["components"]), (False, True, ["app"]))
            self.assertEqual(data["app/keep.log"]["ignored"], False)            # negated pattern
            self.assertEqual(data["data/raw/x.log"]["ignored_by"], ".gitignore and impact.yml ignore")
            self.assertEqual(data["data/raw/x.py"]["ignored_by"], "impact.yml ignore")
            _, text, _ = plan(repo, "--paths", "app/gen/untracked.py")
            self.assertIn("app/gen/untracked.py (not listed by Git): ignored (.gitignore)", text)
            # check agrees: the ignored file is never seen; the tracked one is
            repo.write("app/gen/tracked.py", "t2\n")
            _, out, _ = run("check", "--root", str(repo.root), "--format", "json")
            self.assertEqual(sorted(e["path"] for e in json.loads(out)["impact"]), ["app/gen/tracked.py", "app/keep.log"])

    def test_d2_existence_is_git_exact_and_odd_names_are_literal(self):
        with rules_repo() as repo:
            data = by_path(plan_json(repo, "APP/MAIN.PY", "app/main.py", ":(exclude)x.py", "./-x.py", "*.py")[1])
            self.assertFalse(data["APP/MAIN.PY"]["exists"])                     # no case aliasing (Windows)
            self.assertNotIn("stale-reference", [r["rule"] for r in data["APP/MAIN.PY"]["rules"]])
            self.assertTrue(data["app/main.py"]["exists"])
            for name in (":(exclude)x.py", "-x.py", "*.py"):
                self.assertEqual((data[name]["ignored"], data[name]["exists"]), (False, False))

    def test_d2_git_calls_use_the_central_protections(self):
        import subprocess
        from tools.impact import gitfiles
        seen = []
        real = subprocess.run

        def spy(argv, **kwargs):
            seen.append((argv, kwargs.get("env", {}).get("GIT_NO_LAZY_FETCH")))
            return real(argv, **kwargs)
        with rules_repo() as repo:
            with mock.patch.object(gitfiles.subprocess, "run", side_effect=spy):
                self.assertEqual(plan(repo, "--paths", "app/x.py")[0], 0)
        commands = [next(a for a in argv[3:] if not a.startswith("-") and "=" not in a) for argv, _ in seen]
        self.assertIn("check-ignore", commands)
        self.assertNotIn("diff", commands)
        for argv, lazy in seen:
            self.assertTrue(any(a.startswith("core.hooksPath=") for a in argv))
            self.assertEqual(lazy, "1")

    def test_d3_no_trigger_docs_for_exempt_purposes(self):
        with rules_repo() as repo:
            data = by_path(plan_json(repo, "app/tests/test_x.py", "lab/new.py", "app/x.py")[1])
            for path in ("app/tests/test_x.py", "lab/new.py"):
                with self.subTest(path=path):
                    self.assertEqual([d["doc"] for d in data[path]["docs"] if d["kind"] == "trigger"], [])
                    self.assertNotIn("content-trigger", [r["rule"] for r in data[path]["rules"]])
            self.assertEqual([d["doc"] for d in data["app/x.py"]["docs"] if d["kind"] == "trigger"], ["docs/ops.md"])
            # check agrees: a test file with SECRET gets no trigger docs
            repo.write("app/tests/test_x.py", "SECRET\n")
            _, out, _ = run("check", "--root", str(repo.root), "--format", "json")
            entry = next(e for e in json.loads(out)["impact"] if e["path"] == "app/tests/test_x.py")
            self.assertEqual([d["doc"] for d in entry["docs"] if d["kind"] == "trigger"], [])

    def test_engine_modules_are_predicted_where_the_package_is(self):
        from tools.impact import rules
        hide = {**IMPACT, "ignore": [".local/**", "data/raw/**", "vendor/kit/hidden/**"]}
        with rules_repo(impact=hide) as repo:
            for engine, flagged in (("vendor/kit/impact", "vendor/kit/impact/cli.py"),
                                    ("vendor/kit/hidden", "vendor/kit/hidden/cli.py")):   # impact.yml-ignored
                with self.subTest(engine=engine), mock.patch.object(rules, "engine_folder", return_value=engine):
                    data = by_path(plan_json(repo, flagged, "vendor/kit/impact/tests/t.py", "tools/impact/cli.py")[1])
                    self.assertIn(("config-changed", "WARNING"), rules_of(data[flagged]))
                    self.assertNotIn(("config-changed", "WARNING"), rules_of(data["vendor/kit/impact/tests/t.py"]))
                    self.assertNotIn(("config-changed", "WARNING"), rules_of(data["tools/impact/cli.py"]))
            with mock.patch.object(rules, "engine_folder", return_value=None):          # package outside the repo
                data = by_path(plan_json(repo, "vendor/kit/impact/cli.py", "impact.yml")[1])
                self.assertNotIn(("config-changed", "WARNING"), rules_of(data["vendor/kit/impact/cli.py"]))
                self.assertIn(("config-changed", "WARNING"), rules_of(data["impact.yml"]))

    def test_reference_matching_respects_path_boundaries(self):
        with rules_repo() as repo:
            repo.write("docs/refs.md", "See app/old.py.bak and other/app/old.py.\n"); repo.add_all(); repo.commit("r")
            self.assertEqual(by_path(plan_json(repo, "app/old.py")[1])["app/old.py"]["referenced_by"], [])
            repo.write("docs/refs.md", "See app/old.py.\n")
            self.assertEqual(by_path(plan_json(repo, "app/old.py")[1])["app/old.py"]["referenced_by"], ["docs/refs.md"])

    def test_head_is_reported(self):
        with rules_repo() as repo:
            head = repo.git("rev-parse", "HEAD").strip()
            self.assertEqual(plan_json(repo, "a.py")[1]["head"], head)
            self.assertTrue(plan(repo, "--paths", "a.py")[1].startswith(f"impact plan | HEAD {head[:7]} | 1 paths"))


class Formats(unittest.TestCase):
    PATHS = ("core/base.py", "api/orders/route.ts", "misc/new.py", "data/raw/x.py", "shared/s.py")

    def test_text_and_markdown(self):
        with rules_repo() as repo:
            code, text, _ = plan(repo, "--paths", *self.PATHS)
            self.assertEqual(code, 0)
            self.assertTrue(text.startswith("impact plan | HEAD "))
            self.assertIn("would apply: new-interface-without-contract (ERROR) if the file is new", text)
            self.assertIn("dependents (one hop): lib depends on core (inferred: assumed from the design)", text)
            self.assertTrue(text.endswith("Summary: 5 paths | exit code 0\n"))
            _, md, _ = plan(repo, "--format", "md", "--paths", *self.PATHS)
            self.assertTrue(md.startswith("## Documentation impact (prediction)\n"))
            self.assertIn("| core/base.py | core | docs/core.md (reviewed)<br>docs/ops.md (trigger) | - | not mapped "
                          "| lib (inferred) |", md)
            self.assertIn("| data/raw/x.py | ignored (impact.yml ignore) | - | - | - | - |", md)
            self.assertIn("| api/orders/route.ts (new) | api |", md)
            self.assertIn("### Rules that could apply", md)

    def test_markdown_escapes_names(self):
        with rules_repo() as repo:
            _, md, _ = plan(repo, "--format", "md", "--paths", "app/[x](y)|z.py")
            self.assertIn("app/\\[x\\](y)\\|z.py", md)
            self.assertNotIn("[x](y)", md)

    def test_deterministic_and_independent_of_argument_order(self):
        with rules_repo() as repo:
            for fmt in ("text", "json", "md"):
                with self.subTest(fmt=fmt):
                    first = plan(repo, "--format", fmt, "--paths", *self.PATHS)
                    self.assertEqual(first, plan(repo, "--format", fmt, "--paths", *self.PATHS))
                    self.assertEqual(first, plan(repo, "--format", fmt, "--paths", *reversed(self.PATHS)))

    def test_out_writes_three_reports_matching_stdout(self):
        with rules_repo() as repo:
            outputs = {fmt: plan(repo, "--format", fmt, "--out", ".local/p", "--paths", "core/base.py")[1]
                       for fmt in ("text", "json", "md")}
            folder = repo.root / ".local" / "p"
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ["plan.json", "plan.md", "plan.txt"])
            for fmt, name in (("text", "plan.txt"), ("json", "plan.json"), ("md", "plan.md")):
                self.assertEqual((folder / name).read_bytes().decode("utf-8"), outputs[fmt])
            code, out, err = plan(repo, "--out", "..", "--paths", "core/base.py")
            self.assertEqual((code, out), (2, ""))
            self.assertIn("inside the repository", err)


class Failures(unittest.TestCase):
    def test_invalid_paths_and_arguments_exit_2(self):
        with rules_repo() as repo:
            cases = {"absolute": ("C:/x.py", "absolute"), "parent": ("../x.py", "'..' segment"),
                     "empty": ("", "empty path"), "trailing slash": ("app/", "empty segment"),
                     "folder": ("app", "is a folder"), "control": ("a\x01.py", "control character"),
                     "dot segment": ("app/./x.py", "'.' segment")}
            for name, (value, message) in cases.items():
                with self.subTest(case=name):
                    code, out, err = plan(repo, "--paths", value)
                    self.assertEqual((code, out), (2, ""))
                    self.assertIn(message, err)
            for args in ((), ("--paths",), ("--paths", "a.py", "--format", "pdf"), ("--base", "main")):
                with self.subTest(args=args):
                    self.assertEqual(plan(repo, *args)[0], 2)

    def test_configuration_and_repository_failures_exit_2(self):
        with rules_repo(registry={"version": 1, "components": [{"id": "x"}]}) as repo:
            code, out, err = plan(repo, "--paths", "a.py")
            self.assertEqual((code, out), (2, ""))
            self.assertIn("run `python -m tools.impact validate`", err)
        with rules_repo() as repo:
            (repo.root / "impact.yml").unlink()
            self.assertEqual(plan(repo, "--paths", "a.py")[0], 2)
            code, _, err = run("plan", "--root", str(repo.root.parent), "--paths", "a.py")   # not a repository
            self.assertEqual(code, 2)
        with rules_repo() as repo:
            with mock.patch("tools.impact.plan.predict", side_effect=RuntimeError("boom")):
                code, out, err = plan(repo, "--paths", "a.py")
            self.assertEqual((code, out), (2, ""))
            self.assertIn("the plan did not complete", err)


class NoChangeInspection(unittest.TestCase):
    def test_no_git_diff_no_changed_lines_and_no_writes(self):
        with rules_repo() as repo:
            repo.write("app/main.py", LINES + "SECRET\n")                       # local changes are not inspected
            before = full_snapshot(repo.root)
            boom = mock.Mock(side_effect=AssertionError("change detection must not run"))
            with mock.patch("tools.impact.changes.collect", boom), \
                    mock.patch("tools.impact.changes.changed_lines", boom), \
                    mock.patch("tools.impact.changes.analysis", boom):
                for fmt in ("text", "json", "md"):
                    self.assertEqual(plan(repo, "--format", fmt, "--paths", "app/main.py", "x/new.py")[0], 0)
            self.assertEqual(full_snapshot(repo.root), before)

    def test_validate_and_check_are_unaffected_by_plan(self):
        with rules_repo() as repo:
            repo.write("app/main.py", LINES + "SECRET\n")
            check_before = run("check", "--root", str(repo.root), "--format", "json")
            validate_before = run("validate", "--root", str(repo.root), "--format", "json")
            plan(repo, "--paths", "app/main.py")
            self.assertEqual(run("check", "--root", str(repo.root), "--format", "json"), check_before)
            self.assertEqual(run("validate", "--root", str(repo.root), "--format", "json"), validate_before)


if __name__ == "__main__":
    unittest.main()
