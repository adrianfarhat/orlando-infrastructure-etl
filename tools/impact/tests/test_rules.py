"""Stage 83b-2: the change-impact rules, on throwaway Git repositories (collect -> analyse)."""

import hashlib
import unittest
import unittest.mock
from pathlib import Path

from tools.impact import changes, config, rules
from tools.impact.changes import collect
from tools.impact.rules import CHANGED, NO_CONTENT_CHANGE, NOT_MAPPED, InvalidConfiguration, find_references

from .support import TempRepo

IMPACT = {
    "version": 1,
    "registry": "registry/components.yml",
    "ignore": [".local/**", "data/raw/**"],
    "purposes": [
        {"purpose": "test", "paths": ["app/tests/**", "**/*.test.ts"]},
        {"purpose": "generated", "paths": ["docs/generated/**"]},
        {"purpose": "experimental", "paths": ["lab/**"]},
        {"purpose": "doc", "paths": ["docs/**", "**/*.md"]},
    ],
    "interfaces": [{"kind": "api-route", "paths": ["api/**/route.ts"]}],
    "rules": {"unregistered-path": "WARNING", "docs-not-updated": "WARNING", "content-trigger": "WARNING",
              "ack-problem": "WARNING"},
    "reference_scan": {"include": ["**/*.md", "registry/**", "impact.yml"], "exclude": ["docs/history.md"]},
}
REGISTRY = {
    "version": 1,
    "components": [
        {"id": "app", "paths": ["app/**"], "docs": ["docs/app.md", "docs/ops.md"],
         "depends_on": [{"id": "lib", "basis": "code", "evidence": "app/main.py imports lib"}]},
        {"id": "lib", "paths": ["lib/**"], "docs": ["docs/lib.md"],
         "depends_on": [{"id": "core", "basis": "inferred", "note": "assumed from the design"}]},
        {"id": "core", "paths": ["core/**"], "docs": ["docs/core.md"]},
        {"id": "api", "paths": ["api/**"], "docs": ["docs/api.md"],
         "interfaces": [{"path": "api/items/route.ts", "contract": "docs/api.md"}]},
        {"id": "notes", "paths": ["notes/**"], "docs": []},
        {"id": "lab", "paths": ["lab/**"], "docs": ["docs/app.md"]},
        {"id": "docs", "paths": ["docs/**", "README.md"], "docs": []},
        {"id": "tie-a", "paths": ["shared/*.py"], "docs": ["docs/app.md"]},
        {"id": "tie-b", "paths": ["shared/*.py"], "docs": ["docs/lib.md"]},
        {"id": "impact", "paths": ["impact.yml", "registry/**", "tools/impact/**"], "docs": []},
    ],
    "content_triggers": [{"id": "secret", "paths": ["**/*.py"], "match": "SECRET", "docs": ["docs/ops.md"]}],
}
LINES = "".join(f"line {i}\n" for i in range(30))


def rules_repo(impact=None, registry=None) -> TempRepo:
    repo = TempRepo()
    repo.write_json("impact.yml", impact or IMPACT)
    repo.write_json("registry/components.yml", registry or REGISTRY)
    for doc in ("app", "ops", "lib", "core", "api"):
        repo.write(f"docs/{doc}.md", f"# {doc}\n")
    repo.write("docs/refs.md", "# references\n")
    repo.write("docs/history.md", "# history: app/old.py\n")
    repo.write("README.md", "# readme\n")
    repo.write("app/main.py", LINES)
    repo.write("app/old.py", LINES)
    repo.write("app/tests/test_main.py", LINES)
    repo.write("lib/util.py", LINES)
    repo.write("core/base.py", LINES)
    repo.write("api/items/route.ts", "export {}\n")
    repo.write("notes/n.txt", "n\n")
    repo.write("lab/try.py", LINES)
    repo.write("shared/s.py", LINES)
    repo.write("tools/impact/config.py", "x = 1\n")
    repo.write("tools/impact/other.py", "y = 1\n")
    repo.write("misc/thing.txt", "t\n")
    repo.write(".gitignore", ".local/\n")
    repo.add_all()
    repo.commit("base")
    return repo


def run(repo: TempRepo, base=None) -> rules.Analysis:
    cfg, reg = rules.ready(config.load(repo.root))
    return rules.analyse(repo.root, cfg, reg, collect(repo.root, base=base))


def found(analysis, rule=None):
    return sorted((f.rule, f.source, f.subject) for f in analysis.findings if rule is None or f.rule == rule)


def entry(analysis, path):
    return next(e for e in analysis.impact if e.path == path)


class NewInterfaceWithoutContract(unittest.TestCase):
    def test_new_unlisted_interface_is_an_error(self):
        with rules_repo() as repo:
            repo.write("api/orders/route.ts", "export {}\n")
            a = run(repo)
            self.assertEqual(found(a, "new-interface-without-contract"),
                             [("new-interface-without-contract", "api/orders/route.ts", "api/orders/route.ts")])
            self.assertEqual(next(f for f in a.findings if f.rule == "new-interface-without-contract").severity,
                             "ERROR")
            self.assertEqual(a.exit_code, 1)

    def test_listed_interface_is_not_an_error(self):
        with rules_repo() as repo:
            repo.git("rm", "-q", "api/items/route.ts"); repo.commit("remove")
            repo.write("api/items/route.ts", "export {}\n")                      # new again, and listed
            a = run(repo)
            self.assertEqual(found(a, "new-interface-without-contract"), [])
            self.assertEqual(entry(a, "api/items/route.ts").contracts, (("api/items/route.ts", "docs/api.md"),))

    def test_modified_existing_interface_is_not_flagged(self):
        with rules_repo(registry={**REGISTRY, "components": [
                {**c, "interfaces": []} if c["id"] == "api" else c for c in REGISTRY["components"]]}) as repo:
            repo.write("api/items/route.ts", "export const x = 1\n")
            self.assertEqual(found(run(repo), "new-interface-without-contract"), [])

    def test_rename_to_an_unlisted_interface_path_is_an_error(self):
        with rules_repo() as repo:
            (repo.root / "api" / "things").mkdir()
            repo.git("mv", "api/items/route.ts", "api/things/route.ts")
            self.assertEqual(found(run(repo), "new-interface-without-contract"),
                             [("new-interface-without-contract", "api/things/route.ts", "api/things/route.ts")])

    def test_non_interface_file_and_ignored_paths(self):
        with rules_repo(impact={**IMPACT, "interfaces": [{"kind": "api-route", "paths": ["**/route.ts"]}]}) as repo:
            repo.write("api/orders/helper.ts", "x\n")
            repo.write(".local/x/route.ts", "x\n")                                # git-ignored
            repo.write("data/raw/route.ts", "x\n")                                # impact.yml ignore
            a = run(repo)
            self.assertEqual(found(a, "new-interface-without-contract"), [])
            self.assertTrue(entry(a, "data/raw/route.ts").ignored)


class StaleReference(unittest.TestCase):
    def test_deleted_path_still_referenced(self):
        with rules_repo() as repo:
            repo.write("docs/refs.md", "# refs\n\nSee `app/old.py` for details.\n")
            repo.add_all(); repo.commit("ref")
            repo.git("rm", "-q", "app/old.py")
            a = run(repo)
            f = next(f for f in a.findings if f.rule == "stale-reference")
            self.assertEqual((f.severity, f.source, f.subject), ("ERROR", "docs/refs.md", "app/old.py"))
            self.assertIn("(deleted) on line(s) 3", f.message)
            self.assertEqual(a.exit_code, 1)
            self.assertEqual(found(a, "stale-reference"), [("stale-reference", "docs/refs.md", "app/old.py")])

    def test_renamed_path_still_referenced_and_registry_references(self):
        with rules_repo() as repo:
            repo.write("docs/refs.md", "Uses app/old.py.\n")
            repo.add_all(); repo.commit("ref")
            repo.git("mv", "app/old.py", "app/new.py")
            repo.git("mv", "README.md", "README2.md")
            a = run(repo)
            self.assertEqual(found(a, "stale-reference"),
                             [("stale-reference", "docs/refs.md", "app/old.py"),
                              ("stale-reference", "registry/components.yml", "README.md")])
            msg = next(f.message for f in a.findings if f.source == "docs/refs.md")
            self.assertIn("renamed to app/new.py", msg)

    def test_updated_reference_is_clean_and_excluded_file_is_not_scanned(self):
        with rules_repo() as repo:
            repo.git("mv", "app/old.py", "app/new.py")
            repo.write("docs/refs.md", "Uses app/new.py.\n")                      # updated reference
            a = run(repo)                                                       # docs/history.md is excluded
            self.assertEqual(found(a, "stale-reference"), [])

    def test_ignored_removed_path_is_not_checked(self):
        with rules_repo() as repo:
            repo.write("data/raw/x.csv", "1\n"); repo.git("add", "-f", "data/raw/x.csv"); repo.commit("raw")
            repo.write("docs/refs.md", "data/raw/x.csv\n"); repo.add_all(); repo.commit("ref")
            repo.git("rm", "-q", "data/raw/x.csv")
            self.assertEqual(found(run(repo), "stale-reference"), [])

    def test_large_reference_file_is_reported_not_scanned(self):
        with rules_repo() as repo:
            repo.write("docs/refs.md", "app/old.py\n" + "x" * 300 + "\n"); repo.add_all(); repo.commit("ref")
            repo.git("rm", "-q", "app/old.py")
            with unittest.mock.patch.object(changes, "MAX_FILE_BYTES", 200):
                a = run(repo)
            self.assertEqual(found(a, "stale-reference"), [])
            self.assertIn(("docs/refs.md", "larger than 200 bytes"), a.references_not_scanned)

    def test_finding_id_does_not_depend_on_the_line_number(self):
        with rules_repo() as repo:
            repo.write("docs/refs.md", "app/old.py\n"); repo.add_all(); repo.commit("ref")
            repo.git("rm", "-q", "app/old.py")
            first = next(f for f in run(repo).findings if f.rule == "stale-reference")
            repo.write("docs/refs.md", "intro\n\n\napp/old.py\n")
            second = next(f for f in run(repo).findings if f.rule == "stale-reference")
            self.assertEqual(first.id, second.id)
            self.assertNotEqual(first.message, second.message)


class RenamesAndRemovedPaths(unittest.TestCase):
    def test_rename_into_an_ignored_path_keeps_the_old_path(self):
        with rules_repo() as repo:
            repo.write("docs/refs.md", "lib/util.py\n"); repo.add_all(); repo.commit("ref")
            (repo.root / "data" / "raw").mkdir(parents=True)
            repo.git("mv", "lib/util.py", "data/raw/util.py")
            a = run(repo)
            self.assertEqual(found(a, "stale-reference"), [("stale-reference", "docs/refs.md", "lib/util.py")])
            self.assertEqual([f[2] for f in found(a, "docs-not-updated")], ["lib"])
            self.assertEqual(found(a, "unregistered-path"), [])                  # the new path is ignored
            e = entry(a, "data/raw/util.py")
            self.assertEqual((e.kind, e.old_path, e.components, e.old_components),
                             ("renamed", "lib/util.py", ("lib",), ()))

    def test_a_removed_path_that_exists_again_is_not_stale(self):
        with rules_repo() as repo:
            repo.write("docs/refs.md", "app/old.py and lib/util.py\n")
            cfg, reg = rules.ready(config.load(repo.root))
            cs = changes.ChangeSet(repo.root, None, "x", None, (
                changes.Change("app/new.py", "renamed", ("staged",), "app/old.py"),
                changes.Change("lib/util.py", "deleted", ("staged",)),
            ), ())
            lines = lambda c: changes.ChangedLines(("x",), (), True)  # noqa: E731
            present = ["docs/refs.md", "app/new.py", "app/old.py"]               # app/old.py re-created
            a = rules.analyse(repo.root, cfg, reg, cs, lines_for=lines, files=present)
            self.assertEqual(found(a, "stale-reference"), [("stale-reference", "docs/refs.md", "lib/util.py")])


class ReferenceMatching(unittest.TestCase):
    def test_exact_repository_paths_only(self):
        cases = {
            "see app/old.py here": [1], "app/old.py": [1], "(app/old.py)": [1], "`app/old.py`": [1],
            "[x](/app/old.py)": [1], "End app/old.py.": [1], "app/old.py#L3": [1], "app/old.py:12": [1],
            "line\n\"app/old.py\"": [2], "a app/old.py b app/old.py\nc": [1],
            # not the same path
            "web/app/old.py": [], "../../app/old.py": [], "app/old.py.bak": [], "app/old.pyc": [],
            "app/old.py2": [], "myapp/old.py": [], "old.py": [], "app/old_py": [], "app/old.py/x": [],
            "https://example.com/blob/main/app/old.py": [],
        }
        for text, lines in cases.items():
            with self.subTest(text=text):
                self.assertEqual(find_references(text, "app/old.py"), lines)

    def test_root_level_names_need_a_quoted_or_backticked_value(self):
        cases = {"`README.md`": [1], '"README.md"': [1], "'README.md'": [1], "see README.md": [],
                 "web/README.md": [], "`web/README.md`": [], "`README.md.bak`": [], "[r](README.md)": [],
                 '"README.md\'': []}
        for text, lines in cases.items():
            with self.subTest(text=text):
                self.assertEqual(find_references(text, "README.md"), lines)

    def test_names_with_spaces_and_unicode(self):
        self.assertEqual(find_references("see `extractors/new loader.py`", "extractors/new loader.py"), [1])
        self.assertEqual(find_references("docs/résumé.md", "docs/résumé.md"), [1])
        self.assertEqual(find_references("docs/résumé.mdé", "docs/résumé.md"), [])


class UnregisteredPath(unittest.TestCase):
    def test_new_unregistered_file_with_suggestion(self):
        with rules_repo() as repo:
            repo.write("misc/new.txt", "x\n")
            repo.write("app2/x.py", "x\n")
            a = run(repo)
            self.assertEqual(found(a, "unregistered-path"),
                             [("unregistered-path", "app2/x.py", "app2/x.py"),
                              ("unregistered-path", "misc/new.txt", "misc/new.txt")])
            msgs = {f.source: f.message for f in a.findings if f.rule == "unregistered-path"}
            self.assertIn("register a new component", msgs["misc/new.txt"])
            self.assertTrue(all(f.severity == "WARNING" for f in a.findings if f.rule == "unregistered-path"))

    def test_suggests_the_component_sharing_the_longest_folder(self):
        with rules_repo(registry={**REGISTRY, "components": REGISTRY["components"] + [
                {"id": "deep", "paths": ["srv/a/b/**"], "docs": []},
                {"id": "shallow", "paths": ["srv/z/**"], "docs": []}]}) as repo:
            repo.write("srv/a/c/new.py", "x\n")                                   # deep shares srv/a, shallow srv
            repo.write("srv/q/new.py", "x\n")                                     # both share srv: tie -> by id
            a = run(repo)
            msgs = {f.source: f.message for f in a.findings if f.rule == "unregistered-path"}
            self.assertIn("component deep (shares the folder srv/a/)", msgs["srv/a/c/new.py"])
            self.assertIn("component deep (shares the folder srv/)", msgs["srv/q/new.py"])

    def test_deleted_and_modified_unregistered_paths(self):
        with rules_repo() as repo:
            repo.git("rm", "-q", "misc/thing.txt")
            self.assertEqual(found(run(repo), "unregistered-path"), [])          # deleted: not reported
        with rules_repo() as repo:
            repo.write("misc/thing.txt", "changed\n")
            self.assertEqual(found(run(repo), "unregistered-path"),
                             [("unregistered-path", "misc/thing.txt", "misc/thing.txt")])

    def test_rule_can_be_turned_off(self):
        with rules_repo(impact={**IMPACT, "rules": {**IMPACT["rules"], "unregistered-path": "off"}}) as repo:
            repo.write("misc/new.txt", "x\n")
            self.assertEqual(found(run(repo), "unregistered-path"), [])


class DocsNotUpdated(unittest.TestCase):
    def test_component_change_without_doc_change(self):
        with rules_repo() as repo:
            repo.write("app/main.py", LINES + "more\n")
            a = run(repo)
            f = next(f for f in a.findings if f.rule == "docs-not-updated")
            self.assertEqual((f.severity, f.source, f.location, f.subject),
                             ("WARNING", "registry/components.yml", "component app", "app"))
            self.assertTrue(f.message.startswith("Documentation review required"))
            self.assertIn("docs/app.md, docs/ops.md", f.message)
            self.assertEqual(a.exit_code, 0)

    def test_one_changed_doc_clears_the_warning_but_all_docs_stay_listed(self):
        with rules_repo() as repo:
            repo.write("app/main.py", LINES + "more\n")
            repo.write("docs/ops.md", "# ops\nupdated\n")
            a = run(repo)
            self.assertEqual(found(a, "docs-not-updated"), [])
            docs = {(d.doc, d.kind, d.changed) for d in entry(a, "app/main.py").docs}
            self.assertEqual(docs, {("docs/app.md", "reviewed", False), ("docs/ops.md", "reviewed", True)})

    def test_phantom_doc_change_does_not_count_as_updated(self):
        with rules_repo() as repo:
            repo.write("app/main.py", LINES + "more\n")
            repo.git("rm", "-q", "--cached", "docs/app.md")                     # phantom: content unchanged
            a = run(repo)
            self.assertEqual(found(a, "docs-not-updated"), [("docs-not-updated", "registry/components.yml", "app")])
            self.assertEqual(entry(a, "docs/app.md").content, NO_CONTENT_CHANGE)

    def test_exempt_purposes_and_empty_docs_create_no_obligation(self):
        with rules_repo() as repo:
            repo.write("app/tests/test_main.py", LINES + "more\n")               # test
            repo.write("lab/try.py", LINES + "more\n")                          # experimental
            repo.write("notes/n.txt", "changed\n")                              # docs: []
            a = run(repo)
            self.assertEqual(found(a, "docs-not-updated"), [])
            self.assertFalse(any(e.doc_obligation for e in a.impact))
            self.assertEqual({d.doc for d in entry(a, "app/tests/test_main.py").docs},
                             {"docs/app.md", "docs/ops.md"})                    # still listed (INFO)

    def test_deletion_and_rename_across_components(self):
        with rules_repo() as repo:
            repo.git("rm", "-q", "core/base.py")
            repo.git("mv", "lib/util.py", "app/util.py")
            a = run(repo)
            self.assertEqual([f[2] for f in found(a, "docs-not-updated")], ["app", "core", "lib"])
            e = entry(a, "app/util.py")
            self.assertEqual((e.kind, e.old_path, e.components, e.old_components),
                             ("renamed", "lib/util.py", ("app",), ("lib",)))
            self.assertEqual({d.doc for d in e.docs}, {"docs/app.md", "docs/ops.md", "docs/lib.md"})

    def test_tied_components_are_checked_separately(self):
        with rules_repo() as repo:
            repo.write("shared/s.py", LINES + "more\n")
            repo.write("docs/app.md", "# app\nupdated\n")                       # satisfies tie-a only
            a = run(repo)
            self.assertEqual([f[2] for f in found(a, "docs-not-updated")], ["tie-b"])
            self.assertEqual(entry(a, "shared/s.py").components, ("tie-a", "tie-b"))

    def test_rule_can_be_turned_off(self):
        with rules_repo(impact={**IMPACT, "rules": {**IMPACT["rules"], "docs-not-updated": "off"}}) as repo:
            repo.write("app/main.py", LINES + "more\n")
            a = run(repo)
            self.assertEqual(found(a, "docs-not-updated"), [])
            self.assertTrue(entry(a, "app/main.py").doc_obligation)             # INFO unchanged


class ContentTrigger(unittest.TestCase):
    def test_added_and_removed_lines(self):
        with rules_repo() as repo:
            repo.write("lib/util.py", "x = SECRET\n" + LINES); repo.add_all(); repo.commit("secret")
            repo.write("lib/util.py", LINES)                                    # removes the SECRET line
            repo.write("core/base.py", LINES + "key = SECRET\n")               # adds one
            a = run(repo)
            self.assertEqual(found(a, "content-trigger"), [("content-trigger", "core/base.py", "secret"),
                                                           ("content-trigger", "lib/util.py", "secret")])
            msgs = {f.source: f.message for f in a.findings if f.rule == "content-trigger"}
            self.assertIn("in added lines", msgs["core/base.py"])
            self.assertIn("in removed lines", msgs["lib/util.py"])
            self.assertIn("docs/ops.md", msgs["core/base.py"])
            self.assertEqual(entry(a, "core/base.py").triggers, ("secret",))

    def test_match_outside_the_changed_lines_is_ignored(self):
        with rules_repo() as repo:
            repo.write("core/base.py", "x = SECRET\n" + LINES); repo.add_all(); repo.commit("secret")
            repo.write("core/base.py", "x = SECRET\n" + LINES + "unrelated\n")
            self.assertEqual(found(run(repo), "content-trigger"), [])

    def test_unregistered_file_still_triggers_but_test_files_do_not(self):
        with rules_repo() as repo:
            repo.write("misc/new.py", "SECRET\n")
            repo.write("app/tests/test_x.py", "SECRET\n")
            repo.write("lab/try.py", LINES + "SECRET\n")
            self.assertEqual(found(run(repo), "content-trigger"), [("content-trigger", "misc/new.py", "secret")])

    def test_unscanned_lines_are_reported_never_no_match(self):
        with rules_repo() as repo:
            repo.write("core/bin.py", b"SECRET\x00binary")
            a = run(repo)
            f = next(f for f in a.findings if f.rule == "content-trigger")
            self.assertEqual((f.subject, f.severity), ("secret (not scanned)", "WARNING"))
            self.assertIn("manually", f.message)
            self.assertEqual(entry(a, "core/bin.py").unscanned_triggers, ("secret",))
            self.assertTrue(entry(a, "core/bin.py").content.startswith("not scanned"))

    def test_deleted_file_lines_are_scanned(self):
        with rules_repo() as repo:
            repo.write("core/gone.py", "SECRET\n"); repo.add_all(); repo.commit("x")
            repo.git("rm", "-q", "core/gone.py")
            self.assertEqual(found(run(repo), "content-trigger"), [("content-trigger", "core/gone.py", "secret")])

    def test_rule_can_be_turned_off(self):
        with rules_repo(impact={**IMPACT, "rules": {**IMPACT["rules"], "content-trigger": "off"}}) as repo:
            repo.write("core/base.py", LINES + "SECRET\n")
            a = run(repo)
            self.assertEqual(found(a, "content-trigger"), [])
            self.assertEqual(entry(a, "core/base.py").triggers, ("secret",))    # INFO still shows it


class ConfigChanged(unittest.TestCase):
    def test_configuration_and_rule_engine_files(self):
        with rules_repo() as repo:
            repo.write_json("impact.yml", {**IMPACT, "ignore": [".local/**", "data/raw/**", "misc/**"]})
            repo.write("tools/impact/config.py", "x = 2\n")
            repo.write("tools/impact/rules.py", "z = 1\n")
            repo.write("tools/impact/other.py", "y = 2\n")                       # not on the list
            a = run(repo)
            self.assertEqual(found(a, "config-changed"), [("config-changed", "impact.yml", "impact.yml"),
                                                          ("config-changed", "tools/impact/config.py",
                                                           "tools/impact/config.py"),
                                                          ("config-changed", "tools/impact/rules.py",
                                                           "tools/impact/rules.py")])
            self.assertTrue(all(f.severity == "WARNING" for f in a.findings if f.rule == "config-changed"))

    def test_registry_change_rename_and_phantom(self):
        with rules_repo() as repo:
            reg = {**REGISTRY, "components": REGISTRY["components"] + [{"id": "misc", "paths": ["misc/**"],
                                                                         "docs": []}]}
            repo.write_json("registry/components.yml", reg)
            a = run(repo)
            self.assertEqual(found(a, "config-changed"),
                             [("config-changed", "registry/components.yml", "registry/components.yml")])
        with rules_repo() as repo:
            repo.git("rm", "-q", "--cached", "impact.yml")                       # phantom: no content change
            self.assertEqual(found(run(repo), "config-changed"), [])

    def test_fixed_rule_cannot_be_configured(self):
        with rules_repo(impact={**IMPACT, "rules": {**IMPACT["rules"], "config-changed": "off"}}) as repo:
            with self.assertRaises(InvalidConfiguration):
                rules.ready(config.load(repo.root))


class PhantomChanges(unittest.TestCase):
    def test_staged_edit_reverted_on_disk_creates_no_finding(self):
        with rules_repo() as repo:
            repo.write("misc/thing.txt", "edited\n"); repo.git("add", "misc/thing.txt")
            repo.write("misc/thing.txt", "t\n")                                 # back to HEAD content
            repo.write("app/main.py", LINES + "SECRET\n"); repo.git("add", "app/main.py")
            repo.write("app/main.py", LINES)
            a = run(repo)
            self.assertEqual(a.findings, ())
            e = entry(a, "app/main.py")
            self.assertEqual((e.kind, e.content, e.doc_obligation), ("modified", NO_CONTENT_CHANGE, False))

    def test_identical_rename_still_counts(self):
        with rules_repo() as repo:
            repo.git("mv", "core/base.py", "core/moved.py")
            a = run(repo)
            self.assertEqual(found(a, "docs-not-updated"), [("docs-not-updated", "registry/components.yml", "core")])
            self.assertEqual(entry(a, "core/moved.py").content, NO_CONTENT_CHANGE)


class InformationalImpact(unittest.TestCase):
    def test_one_hop_dependents_tests_and_no_findings_from_info(self):
        with rules_repo() as repo:
            repo.write("core/base.py", LINES + "more\n")
            repo.write("docs/core.md", "# core\nupdated\n")
            a = run(repo)
            self.assertEqual(a.findings, ())
            e = entry(a, "core/base.py")
            self.assertEqual([(d.component, d.depends_on, d.basis, d.detail) for d in e.dependents],
                             [("lib", "core", "inferred", "assumed from the design")])   # one hop: not app
            self.assertEqual((e.tests, e.tests_basis), ((), NOT_MAPPED))
            self.assertEqual(e.content, CHANGED)

    def test_tests_listed_from_the_same_component(self):
        with rules_repo() as repo:
            repo.write("app/main.py", LINES + "more\n")
            e = entry(run(repo), "app/main.py")
            self.assertEqual(e.tests, ("app/tests/test_main.py",))
            self.assertIn("not a verified test mapping", e.tests_basis)
            self.assertEqual([(d.component, d.basis) for d in e.dependents], [])  # nothing depends on app

    def test_ignored_changes_are_listed_but_not_analysed(self):
        with rules_repo() as repo:
            repo.write("data/raw/new.py", "SECRET\n")
            a = run(repo)
            self.assertEqual(a.findings, ())
            e = entry(a, "data/raw/new.py")
            self.assertEqual((e.ignored, e.docs, e.doc_obligation), (True, (), False))

    def test_unsupported_names_are_reported(self):
        cs = changes.ChangeSet(Path("."), None, "x", None, (), (changes.Unsupported("bad\\x01", "why"),))
        with rules_repo() as repo:
            cfg, reg = rules.ready(config.load(repo.root))
            a = rules.analyse(repo.root, cfg, reg, cs, lines_for=lambda c: None, files=[])
            self.assertEqual(a.unsupported, ("bad\\x01",))


class EngineProperties(unittest.TestCase):
    def test_invalid_configuration_is_refused(self):
        with rules_repo(registry={"version": 1, "components": [{"id": "x"}]}) as repo:
            with self.assertRaises(InvalidConfiguration):
                rules.ready(config.load(repo.root))

    def test_ack_problem_is_not_produced_in_this_stage(self):
        with rules_repo() as repo:
            repo.write("misc/new.txt", "x\n"); repo.write("app/main.py", LINES + "SECRET\n")
            self.assertFalse(any(f.rule == "ack-problem" for f in run(repo).findings))

    def test_deterministic_and_read_only(self):
        def snapshot(root: Path):
            return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in root.rglob("*") if p.is_file()}
        with rules_repo() as repo:
            repo.write("docs/refs.md", "app/old.py\n"); repo.add_all(); repo.commit("ref")
            repo.git("rm", "-q", "app/old.py")
            repo.git("mv", "lib/util.py", "lib/util2.py")
            repo.write("misc/new.py", "SECRET\n")
            repo.write("api/orders/route.ts", "x\n")
            repo.write("app/main.py", LINES + "more\n"); repo.git("add", "app/main.py")
            before = snapshot(repo.root)
            first, second = run(repo), run(repo)
            self.assertEqual(first, second)
            self.assertEqual(snapshot(repo.root), before)
            self.assertEqual({f.rule for f in first.findings},
                             {"stale-reference", "unregistered-path", "content-trigger", "docs-not-updated",
                              "new-interface-without-contract"})

    def test_base_mode_includes_committed_changes(self):
        with rules_repo() as repo:
            repo.git("checkout", "-q", "-b", "feature")
            repo.write("core/base.py", LINES + "SECRET\n"); repo.add_all(); repo.commit("feature")
            self.assertEqual(found(run(repo), "content-trigger"), [])            # local mode: nothing
            a = run(repo, base="main")
            self.assertEqual(found(a, "content-trigger"), [("content-trigger", "core/base.py", "secret")])
            self.assertEqual(entry(a, "core/base.py").origins, ("committed",))


if __name__ == "__main__":
    unittest.main()
