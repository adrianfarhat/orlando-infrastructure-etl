import ast
import dataclasses
import json
import random
import unittest
from pathlib import Path

from tools.impact.config import check_files, load, parse_config, parse_registry
from tools.impact.resolve import ambiguities, resolve

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE = REPO_ROOT / "tools" / "impact"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

CONFIG = {
    "version": 1, "registry": "r.yml",
    "ignore": [".local/**"],
    "purposes": [
        {"purpose": "test", "paths": ["tests/**"]},
        {"purpose": "contract", "paths": ["docs/contract.md"]},
        {"purpose": "doc", "paths": ["docs/**", "**/*.md"]},
        {"purpose": "generated", "paths": ["gen/**"]},
    ],
}
REGISTRY = {
    "version": 1,
    "components": [
        {"id": "app", "paths": ["app/**"], "exclude": ["app/api/**"], "docs": ["docs/app.md"]},
        {"id": "api", "paths": ["app/api/**"], "docs": ["docs/contract.md", "docs/app.md"]},
        {"id": "exact", "paths": ["app/special.py"], "docs": ["docs/special.md"]},
        {"id": "nodocs", "paths": ["misc/**"], "docs": []},
        {"id": "gen", "paths": ["gen/**"], "docs": ["docs/app.md"], "generated": ["docs/gen.md"]},
        {"id": "tie-a", "paths": ["tie/**"], "docs": ["docs/a.md"]},
        {"id": "tie-b", "paths": ["tie/*.py"], "docs": ["docs/b.md"]},
        {"id": "tests", "paths": ["tests/**"], "docs": ["docs/app.md"]},
    ],
    "content_triggers": [
        {"id": "secret", "paths": ["**/*.py"], "exclude": ["tests/**"], "match": "SECRET_[A-Z]{1,20}",
         "docs": ["docs/security.md"]},
    ],
}


def setup():
    config, p1 = parse_config(CONFIG)
    registry, p2 = parse_registry(REGISTRY, "r.yml")
    assert not p1 and not p2, (p1, p2)
    return config, registry


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.config, self.registry = setup()

    def r(self, path, text=None):
        return resolve(path, self.config, self.registry, text)

    def test_purpose_order_first_match_wins(self):
        self.assertEqual(self.r("docs/contract.md").purpose, "contract")  # before "doc"
        self.assertEqual(self.r("docs/other.md").purpose, "doc")
        self.assertEqual(self.r("README.md").purpose, "doc")
        self.assertEqual(self.r("tests/test_x.py").purpose, "test")
        self.assertEqual(self.r("app/x.py").purpose, "code")              # default

    def test_most_specific_component_and_exclude(self):
        self.assertEqual(self.r("app/x.py").component, "app")
        self.assertEqual(self.r("app/api/route.ts").component, "api")      # excluded from app
        self.assertEqual(self.r("app/special.py").component, "exact")      # exact file beats glob

    def test_component_exclude_decides_when_no_more_specific_component_exists(self):
        # In the shared REGISTRY, app's exclude is redundant (api is more specific anyway),
        # so it would not catch a broken exclude. Here the exclude alone decides.
        registry, problems = parse_registry({"version": 1, "components": [
            {"id": "app", "paths": ["app/**"], "exclude": ["app/api/**"], "docs": ["docs/app.md"]}]}, "r.yml")
        self.assertEqual(problems, [])
        self.assertEqual(resolve("app/x.py", self.config, registry).component, "app")
        excluded = resolve("app/api/route.ts", self.config, registry)
        self.assertIsNone(excluded.component)
        self.assertFalse(excluded.registered)
        self.assertEqual(excluded.relationships, frozenset())

    def test_exclude_can_remove_a_tie(self):
        registry, problems = parse_registry({"version": 1, "components": [
            {"id": "one", "paths": ["x/**"], "docs": ["docs/a.md"]},
            {"id": "two", "paths": ["x/*.py"], "exclude": ["x/gen_*.py"], "docs": ["docs/b.md"]}]}, "r.yml")
        self.assertEqual(problems, [])
        self.assertEqual(resolve("x/a.py", self.config, registry).ambiguous, ("one", "two"))
        self.assertEqual(resolve("x/gen_a.py", self.config, registry).component, "one")

    def test_unregistered(self):
        res = self.r("elsewhere/x.py")
        self.assertIsNone(res.component)
        self.assertFalse(res.registered)
        self.assertEqual(res.relationships, frozenset())
        self.assertFalse(res.doc_obligation)

    def test_relationship_kinds(self):
        self.assertEqual(self.r("app/api/route.ts").doc_pairs(),
                         {("docs/contract.md", "reviewed"), ("docs/app.md", "reviewed")})
        self.assertEqual(self.r("gen/x.sql").doc_pairs(),
                         {("docs/app.md", "reviewed"), ("docs/gen.md", "generated")})

    def test_triggers(self):
        self.assertEqual(self.r("app/x.py").triggers, ())                      # text unknown
        self.assertEqual(self.r("app/x.py", "nothing here").triggers, ())
        res = self.r("app/x.py", "uses SECRET_KEY")
        self.assertEqual(res.triggers, ("secret",))
        self.assertIn(("docs/security.md", "trigger"), res.doc_pairs())
        self.assertEqual(self.r("app/x.ts", "SECRET_KEY").triggers, ())      # path not matched
        self.assertEqual(self.r("tests/t.py", "SECRET_KEY").triggers, ())    # excluded
        self.assertEqual(self.r("elsewhere/x.py", "SECRET_KEY").component, None)
        self.assertEqual(self.r("elsewhere/x.py", "SECRET_KEY").triggers, ("secret",))  # unregistered still fires

    def test_ignored(self):
        res = self.r(".local/impact/report.md", "SECRET_X")
        self.assertTrue(res.ignored)
        self.assertEqual((res.purpose, res.component, res.triggers, res.relationships), (None, None, (), frozenset()))

    def test_doc_obligation(self):
        self.assertTrue(self.r("app/x.py").doc_obligation)
        self.assertFalse(self.r("misc/x.py").doc_obligation)        # docs: []
        self.assertFalse(self.r("tests/test_x.py").doc_obligation)  # exempt purpose (test)
        self.assertFalse(self.r("gen/x.sql").doc_obligation)        # exempt purpose (generated)

    def test_tie_is_ambiguous_and_loses_nothing(self):
        res = self.r("tie/x.py")
        self.assertIsNone(res.component)
        self.assertEqual(res.ambiguous, ("tie-a", "tie-b"))
        self.assertTrue(res.registered)
        self.assertEqual(res.doc_pairs(), {("docs/a.md", "reviewed"), ("docs/b.md", "reviewed")})
        self.assertEqual(self.r("tie/sub/x.py").component, "tie-a")  # tie/*.py does not match here

    def test_ambiguities_reported_by_validate(self):
        out = ambiguities(self.config, self.registry, "r.yml", ["tie/x.py", "app/x.py", ".local/x"])
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0].rule, out[0].severity), ("registry-incomplete", "WARNING"))
        self.assertIn("tie-a, tie-b", out[0].message)

    def test_git_paths_keep_literal_backslashes(self):
        name = "app\\weird name.py"                          # a real Linux file name
        git_res = resolve(name, self.config, self.registry, from_git=True)
        self.assertEqual(git_res.path, name)                 # not rewritten to app/weird name.py
        self.assertIsNone(git_res.component)                 # "app\..." is not inside app/
        typed = resolve(name, self.config, self.registry)    # a typed value: '\' is a separator
        self.assertEqual((typed.path, typed.component), ("app/weird name.py", "app"))
        inside = resolve("app/back\\slash.py", self.config, self.registry, "SECRET_KEY", from_git=True)
        self.assertEqual((inside.path, inside.component, inside.triggers),
                         ("app/back\\slash.py", "app", ("secret",)))

    def test_git_paths_with_control_characters_are_rejected(self):
        from tools.impact.paths import PathError
        with self.assertRaises(PathError):
            resolve("app/tab\there.py", self.config, self.registry, from_git=True)

    def test_unscanned_triggers_are_reported_not_treated_as_no_match(self):
        from tools.impact import regexsafe
        big = ("x" * 999 + "\n") * (regexsafe.MAX_SCAN_CHARS // 1000 + 10) + "SECRET_KEY\n"
        res = self.r("app/x.py", big)
        self.assertEqual(res.triggers, ())
        self.assertEqual(res.unscanned_triggers, ("secret",))
        self.assertEqual(self.r("app/x.py", "SECRET_KEY\n" + big).triggers, ("secret",))
        small = self.r("app/x.py", "no secrets here\n")
        self.assertEqual((small.triggers, small.unscanned_triggers), ((), ()))

    def test_path_normalized(self):
        self.assertEqual(self.r(".\\app\\x.py").path, "app/x.py")
        self.assertEqual(self.r("./app/x.py").component, "app")


class RealRegistryTests(unittest.TestCase):
    def setUp(self):
        loaded = load(REPO_ROOT)
        self.assertFalse(loaded.problems)
        self.config, self.registry = loaded.config, loaded.registry

    def r(self, path, text=None):
        return resolve(path, self.config, self.registry, text)

    def test_spot_checks(self):
        self.assertEqual(self.r("database/test_connection.py").purpose, "code")   # not a test
        self.assertEqual(self.r("docs/architecture/data-contracts.md").purpose, "contract")
        self.assertEqual(self.r("web/src/app/api/infrastructure/stats/route.ts").component, "api-routes")
        self.assertEqual(self.r("web/src/app/page.tsx").component, "web-ui")
        self.assertEqual(self.r("database/migrations/0001.sql").component, "db-migrations")
        self.assertEqual(self.r("requirements.txt").component, "python-deps")
        self.assertEqual(self.r("tools/impact/tests/test_x.py").purpose, "test")
        self.assertFalse(self.r("tools/impact/tests/test_x.py").doc_obligation)
        self.assertFalse(self.r("CLAUDE.md").doc_obligation)                     # agent-config: docs []
        self.assertTrue(self.r("data/raw/orlando_manholes.geojson").ignored)

    def test_registry_is_complete_for_current_files(self):
        tracked = [f["path"] for f in json.loads((FIXTURES / "tracked_565706f.json").read_text("utf-8"))["files"]]
        new = ["impact.yml", "registry/components.yml"] + [
            p.relative_to(REPO_ROOT).as_posix() for p in PACKAGE.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts]
        files = tracked + new
        problems = check_files(self.config, self.registry, "registry/components.yml", files)
        problems += ambiguities(self.config, self.registry, "registry/components.yml", files)
        self.assertEqual(problems, [], "\n".join(map(str, problems)))


class PurityAndDeterminismTests(unittest.TestCase):
    BANNED = {"subprocess", "socket", "http", "urllib", "requests", "psycopg", "psycopg2", "pg",
              "sqlite3", "ctypes", "multiprocessing", "importlib", "os", "shutil", "tempfile"}
    BANNED_NAMES = {"eval", "exec", "__import__", "compile", "open"}
    BANNED_ATTRS = {"system", "popen", "startfile", "execv", "spawnv", "write_text", "write_bytes",
                    "unlink", "rmdir", "mkdir", "touch", "chmod"}

    # Per-module exceptions. Every module in the package must be listed, so a new module
    # cannot escape the check. Only gitfiles.py may start a process (git); only cli.py may
    # write files (the two report files); nothing may use the network or a database.
    POLICY = {
        "__init__.py": {}, "__main__.py": {}, "paths.py": {}, "config.py": {}, "resolve.py": {},
        "regexsafe.py": {}, "findings.py": {},
        "gitfiles.py": {"imports": {"subprocess", "os", "tempfile", "shutil"}},  # tempfile/shutil: the private index copy, outside the repository
        "changes.py": {"imports": {"os"}},  # reads working-tree files; runs git only via gitfiles
        "cli.py": {"imports": {"os", "tempfile"}, "attrs": {"mkdir", "unlink", "rmdir"}},  # rmdir: remove only folders a failed --out created
    }

    def test_every_module_has_a_policy(self):
        modules = sorted(p.name for p in PACKAGE.glob("*.py"))
        self.assertEqual(modules, sorted(self.POLICY))

    def test_modules_do_not_run_processes_network_or_databases(self):
        for name, allowed in self.POLICY.items():
            banned_imports = self.BANNED - allowed.get("imports", set())
            banned_attrs = self.BANNED_ATTRS - allowed.get("attrs", set())
            tree = ast.parse((PACKAGE / name).read_text("utf-8"))
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    mods = [node.module or ""]
                for m in mods:
                    with self.subTest(module=name, imports=m):
                        self.assertNotIn(m.split(".")[0], banned_imports)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    with self.subTest(module=name, call=node.func.id):
                        self.assertNotIn(node.func.id, self.BANNED_NAMES)
                if isinstance(node, ast.Attribute):
                    with self.subTest(module=name, attr=node.attr):
                        self.assertNotIn(node.attr, banned_attrs)
                if isinstance(node, ast.keyword) and node.arg == "shell":
                    with self.subTest(module=name, keyword="shell"):
                        self.fail("subprocess shell=... is never allowed")

    def test_resolution_does_not_depend_on_registry_order(self):
        # QA: comparing dicts ignores insertion order, so shuffle what could matter:
        # the order of components and triggers in the registry.
        loaded = load(REPO_ROOT)
        tracked = [f["path"] for f in json.loads((FIXTURES / "tracked_565706f.json").read_text("utf-8"))["files"]]
        paths = tracked + ["tie/x.py", "foo/bar.txt", "database/migrations/0001.sql"]
        baseline = [resolve(p, loaded.config, loaded.registry, "DATABASE_URL") for p in paths]
        rng = random.Random(83)
        for _ in range(5):
            comps, trigs = list(loaded.registry.components), list(loaded.registry.triggers)
            rng.shuffle(comps)
            rng.shuffle(trigs)
            shuffled = dataclasses.replace(loaded.registry, components=tuple(comps), triggers=tuple(trigs))
            self.assertEqual([resolve(p, loaded.config, shuffled, "DATABASE_URL") for p in paths], baseline)

    def test_tie_resolution_does_not_depend_on_registry_order(self):
        config, registry = setup()
        base = resolve("tie/x.py", config, registry)
        reversed_reg = dataclasses.replace(registry, components=tuple(reversed(registry.components)))
        self.assertEqual(resolve("tie/x.py", config, reversed_reg), base)

    def test_loading_is_repeatable(self):
        self.assertEqual(load(REPO_ROOT).problems, load(REPO_ROOT).problems)
        self.assertEqual(load(REPO_ROOT).registry.components, load(REPO_ROOT).registry.components)


if __name__ == "__main__":
    unittest.main()
