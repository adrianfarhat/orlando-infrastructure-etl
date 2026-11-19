import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.impact.config import (FIXED_RULES, LoadError, check_files, load, parse_config,
                                 parse_registry, read_yaml)

REPO_ROOT = Path(__file__).resolve().parents[3]

BASE_CONFIG = {"version": 1, "registry": "registry/components.yml"}
BASE_REGISTRY = {
    "version": 1,
    "components": [
        {"id": "alpha", "paths": ["a/**"], "docs": ["docs/a.md"]},
        {"id": "beta", "paths": ["b/**"], "docs": [],
         "depends_on": [{"id": "alpha", "basis": "code", "evidence": "b imports a"}]},
    ],
    "content_triggers": [
        {"id": "secret", "paths": ["**/*.py"], "match": "SECRET", "docs": ["docs/a.md"]},
    ],
}


def cfg(**changes):
    d = copy.deepcopy(BASE_CONFIG)
    d.update(changes)
    return d


def reg(mutate=None):
    d = copy.deepcopy(BASE_REGISTRY)
    if mutate:
        mutate(d)
    return d


def errors(problems):
    return [p for p in problems if p.severity == "ERROR"]


class ConfigSchemaTests(unittest.TestCase):
    def assert_config_error(self, data, fragment):
        _, problems = parse_config(data)
        errs = errors(problems)
        self.assertTrue(errs, f"expected an ERROR containing {fragment!r}, got none")
        self.assertTrue(any(fragment in f"{p.location} {p.message}" for p in errs),
                        f"no ERROR mentions {fragment!r}: {errs}")

    def test_minimal_config_is_valid_with_defaults(self):
        config, problems = parse_config(cfg())
        self.assertEqual(problems, [])
        self.assertEqual(config.registry, "registry/components.yml")
        self.assertEqual(config.exempt_purposes, frozenset({"test", "generated", "experimental"}))
        self.assertEqual(set(config.rules.values()), {"WARNING"})
        self.assertEqual(config.ack_min_reason_length, 15)

    def test_not_a_mapping(self):
        self.assert_config_error(["a"], "must be a mapping")

    def test_missing_required_keys(self):
        self.assert_config_error({"version": 1}, "missing required key 'registry'")
        self.assert_config_error({"registry": "r.yml"}, "missing required key 'version'")

    def test_unknown_key(self):
        self.assert_config_error(cfg(extra=1), "unknown key 'extra'")

    def test_bad_version(self):
        self.assert_config_error(cfg(version=2), "unsupported version")
        self.assert_config_error(cfg(version=True), "unsupported version")
        self.assert_config_error(cfg(version=1.0), "unsupported version")
        self.assert_config_error(cfg(version="1"), "unsupported version")
        _, problems = parse_registry(reg(lambda d: d.update(version=1.0)), "registry.yml")
        self.assertTrue(any("unsupported version" in p.message for p in errors(problems)))

    def test_registry_must_be_a_file_path(self):
        self.assert_config_error(cfg(registry="registry/*.yml"), "not a pattern")
        self.assert_config_error(cfg(registry="/abs.yml"), "absolute")

    def test_unknown_purpose(self):
        self.assert_config_error(cfg(purposes=[{"purpose": "magic", "paths": ["x/**"]}]), "unknown purpose")

    def test_purpose_needs_paths(self):
        self.assert_config_error(cfg(purposes=[{"purpose": "doc", "paths": []}]), "must not be empty")
        self.assert_config_error(cfg(purposes=[{"purpose": "doc"}]), "missing required key 'paths'")

    def test_bad_glob(self):
        self.assert_config_error(cfg(ignore=["a**b"]), "whole segment")
        self.assert_config_error(cfg(ignore=["../x"]), "'..'")

    def test_unknown_exempt_purpose(self):
        self.assert_config_error(cfg(doc_obligation={"exempt_purposes": ["nope"]}), "unknown purpose")

    def test_interface_kind_and_paths(self):
        self.assert_config_error(cfg(interfaces=[{"kind": "API Route", "paths": ["x/**"]}]), "lowercase")
        self.assert_config_error(cfg(interfaces=[{"kind": "api", "paths": []}]), "must not be empty")

    def test_every_fixed_rule_cannot_be_configured(self):
        for name in FIXED_RULES:
            for section in ("rules", "validate"):
                for value in ("WARNING", "off", "ERROR"):
                    with self.subTest(rule=name, section=section, value=value):
                        self.assert_config_error(cfg(**{section: {name: value}}), "fixed rule")

    def test_configurable_rule_values(self):
        config, problems = parse_config(cfg(rules={"unregistered-path": "off"}))
        self.assertEqual(problems, [])
        self.assertEqual(config.rules["unregistered-path"], "off")
        self.assert_config_error(cfg(rules={"unregistered-path": "ERROR"}), "ERROR is not allowed")
        self.assert_config_error(cfg(rules={"content-trigger": "ERROR"}), "ERROR is not allowed")
        self.assert_config_error(cfg(rules={"content-trigger": "INFO"}), "must be one of")

    def test_rule_in_wrong_section(self):
        self.assert_config_error(cfg(rules={"registry-incomplete": "off"}), "belongs under 'validate:'")
        self.assert_config_error(cfg(validate={"docs-not-updated": "off"}), "belongs under 'rules:'")

    def test_unknown_rule(self):
        self.assert_config_error(cfg(rules={"made-up": "WARNING"}), "unknown key 'made-up'")

    def test_acks(self):
        self.assert_config_error(cfg(acks={"min_reason_length": 0}), "at least 1")
        self.assert_config_error(cfg(acks={"min_reason_length": True}), "at least 1")
        self.assert_config_error(cfg(acks={"placeholders": [""]}), "non-empty string")
        config, _ = parse_config(cfg(acks={"placeholders": ["  N/A "]}))
        self.assertEqual(config.ack_placeholders, ("n/a",))

    def test_reference_scan(self):
        config, problems = parse_config(cfg(reference_scan={"include": ["**/*.md"], "exclude": ["x.md"]}))
        self.assertEqual(problems, [])
        self.assertEqual(config.reference_exclude, ("x.md",))
        self.assert_config_error(cfg(reference_scan={"other": []}), "unknown key 'other'")


class RegistrySchemaTests(unittest.TestCase):
    def assert_registry_error(self, data, fragment):
        _, problems = parse_registry(data, "registry.yml")
        errs = errors(problems)
        self.assertTrue(errs, f"expected an ERROR containing {fragment!r}, got none")
        self.assertTrue(any(fragment in f"{p.location} {p.message}" for p in errs),
                        f"no ERROR mentions {fragment!r}: {errs}")
        for p in errs:
            self.assertEqual(p.rule, "registry-invalid")

    def test_base_registry_is_valid(self):
        registry, problems = parse_registry(reg(), "registry.yml")
        self.assertEqual(problems, [])
        self.assertEqual([c.id for c in registry.components], ["alpha", "beta"])
        self.assertEqual(registry.components[1].depends_on[0].basis, "code")

    def test_missing_required_component_keys(self):
        for key in ("id", "paths", "docs"):
            with self.subTest(key=key):
                self.assert_registry_error(reg(lambda d: d["components"][0].pop(key)),
                                           f"missing required key '{key}'")

    def test_docs_empty_list_is_allowed(self):
        registry, problems = parse_registry(
            {"version": 1, "components": [{"id": "solo", "paths": ["s/**"], "docs": []}]}, "registry.yml")
        self.assertEqual(problems, [])
        self.assertEqual(registry.components[0].docs, ())

    def test_bracketed_literal_paths_are_accepted(self):
        # Next.js dynamic routes use [id] in real file names (QA finding M1).
        route = "web/src/app/api/[id]/route.ts"
        data = {"version": 1, "components": [{
            "id": "api", "paths": ["web/src/app/api/**"], "docs": ["docs/[slug].md"],
            "interfaces": [{"path": route, "contract": "docs/contracts/[v1].md"}]}]}
        registry, problems = parse_registry(data, "registry.yml")
        self.assertEqual(problems, [])
        comp = registry.components[0]
        self.assertEqual(comp.docs, ("docs/[slug].md",))
        self.assertEqual((comp.interfaces[0].path, comp.interfaces[0].contract), (route, "docs/contracts/[v1].md"))

    def test_question_mark_and_star_still_rejected_in_literal_paths(self):
        self.assert_registry_error(reg(lambda d: d["components"][0].update(docs=["docs/a?.md"])), "not a pattern")
        self.assert_registry_error(reg(lambda d: d["components"][0].update(docs=["docs/*.md"])), "not a pattern")

    def test_unknown_component_key(self):
        self.assert_registry_error(reg(lambda d: d["components"][0].update(kind="etl")), "unknown key 'kind'")

    def test_duplicate_and_bad_ids(self):
        self.assert_registry_error(reg(lambda d: d["components"].append(
            {"id": "alpha", "paths": ["c/**"], "docs": []})), "duplicate component id")
        self.assert_registry_error(reg(lambda d: d["components"][0].update(id="Alpha")), "lowercase")
        self.assert_registry_error(reg(lambda d: d["components"][0].update(id="a--b")), "lowercase")

    def test_paths_rules(self):
        self.assert_registry_error(reg(lambda d: d["components"][0].update(paths=[])), "must not be empty")
        self.assert_registry_error(reg(lambda d: d["components"][0].update(paths="a/**")), "must be a list")

    def test_docs_must_be_literal_unique_paths(self):
        self.assert_registry_error(reg(lambda d: d["components"][0].update(docs=["docs/*.md"])), "not a pattern")
        self.assert_registry_error(reg(lambda d: d["components"][0].update(docs=["docs/a.md#x"])), "anchors")
        self.assert_registry_error(reg(lambda d: d["components"][0].update(docs=["docs/a.md", "docs/a.md"])),
                                   "listed twice")

    def test_planned_must_be_boolean(self):
        self.assert_registry_error(reg(lambda d: d["components"][0].update(planned="yes")), "true or false")

    def test_dependency_rules(self):
        def dep(**kw):
            return reg(lambda d: d["components"][1].update(depends_on=[kw]))
        self.assert_registry_error(dep(id="nobody", basis="code", evidence="x"), "unknown component 'nobody'")
        self.assert_registry_error(dep(id="beta", basis="code", evidence="x"), "cannot depend on itself")
        self.assert_registry_error(dep(id="alpha", basis="code"), "requires 'evidence'")
        self.assert_registry_error(dep(id="alpha", basis="inferred"), "requires a 'note'")
        self.assert_registry_error(dep(id="alpha", basis="verified", evidence="x"), "must be one of")
        self.assert_registry_error(dep(id="alpha", basis="code", evidence=""), "non-empty string")
        self.assert_registry_error(reg(lambda d: d["components"][1].update(depends_on=[
            {"id": "alpha", "basis": "code", "evidence": "x"},
            {"id": "alpha", "basis": "inferred", "note": "y"}])), "listed twice")

    def test_inferred_dependency_with_note_is_valid(self):
        data = reg(lambda d: d["components"][1].update(
            depends_on=[{"id": "alpha", "basis": "inferred", "note": "shared tables"}]))
        registry, problems = parse_registry(data, "registry.yml")
        self.assertEqual(problems, [])
        self.assertEqual(registry.components[1].depends_on[0].basis, "inferred")

    def test_interfaces_must_be_inside_own_paths(self):
        self.assert_registry_error(reg(lambda d: d["components"][0].update(
            interfaces=[{"path": "b/route.ts", "contract": "docs/a.md"}])), "not covered by component 'alpha'")
        self.assert_registry_error(reg(lambda d: d["components"][0].update(
            exclude=["a/x/**"], interfaces=[{"path": "a/x/route.ts", "contract": "docs/a.md"}])),
            "not covered")
        self.assert_registry_error(reg(lambda d: d["components"][0].update(
            interfaces=[{"path": "a/route.ts"}])), "missing required key 'contract'")

    def test_trigger_rules(self):
        self.assert_registry_error(reg(lambda d: d["content_triggers"][0].update(match="(")), "invalid regular")
        self.assert_registry_error(reg(lambda d: d["content_triggers"][0].update(docs=[])), "must not be empty")
        self.assert_registry_error(reg(lambda d: d["content_triggers"][0].update(severity="ERROR")),
                                   "unknown key 'severity'")
        self.assert_registry_error(reg(lambda d: d["content_triggers"].append(
            dict(d["content_triggers"][0]))), "duplicate content trigger id")
        self.assert_registry_error(reg(lambda d: d["content_triggers"][0].pop("match")),
                                   "missing required key 'match'")

    def test_all_problems_are_reported_not_just_the_first(self):
        def many(d):
            d["components"][0]["paths"] = []
            d["components"][1]["docs"] = ["*.md"]
            d["content_triggers"][0]["match"] = "("
        _, problems = parse_registry(reg(many), "registry.yml")
        self.assertEqual(len(errors(problems)), 3, "\n".join(map(str, problems)))
        self.assertEqual(sorted(p.location for p in problems),
                         ["components[0].paths", "components[1].docs[0]", "content_triggers[0].match"])


class CheckFilesTests(unittest.TestCase):
    def setUp(self):
        self.config, _ = parse_config(cfg())

    def run_check(self, data, files):
        registry, problems = parse_registry(data, "registry.yml")
        self.assertEqual(problems, [])
        return check_files(self.config, registry, "registry.yml", files)

    def test_clean(self):
        self.assertEqual(self.run_check(reg(), ["a/x.py", "b/y.py", "docs/a.md", "z.py"]), [])

    def test_missing_doc_is_error(self):
        out = self.run_check(reg(), ["a/x.py", "b/y.py", "z.py"])
        self.assertTrue(any(p.rule == "registry-missing-path" and p.severity == "ERROR"
                            and "docs/a.md" in p.message for p in out))

    def test_unmatched_pattern_is_warning(self):
        out = self.run_check(reg(), ["a/x.py", "docs/a.md", "z.py"])  # nothing under b/
        self.assertEqual([(p.rule, p.severity) for p in out], [("registry-incomplete", "WARNING")])

    def test_unmatched_warning_can_be_turned_off(self):
        config, _ = parse_config(cfg(validate={"registry-incomplete": "off"}))
        registry, _ = parse_registry(reg(), "registry.yml")
        self.assertEqual(check_files(config, registry, "registry.yml", ["a/x.py", "docs/a.md", "z.py"]), [])

    def test_trigger_pattern_and_docs(self):
        out = self.run_check(reg(), ["a/x.md", "b/y.md", "docs/a.md"])  # no .py file anywhere
        self.assertTrue(any("content trigger secret" in p.location and p.rule == "registry-incomplete"
                            for p in out))

    def test_missing_trigger_doc_is_error(self):
        data = reg(lambda d: d["content_triggers"][0].update(docs=["docs/security.md"]))
        out = self.run_check(data, ["a/x.py", "b/y.py", "docs/a.md", "z.py"])
        self.assertTrue(any(p.location == "content trigger secret.docs" and p.severity == "ERROR"
                            and p.rule == "registry-missing-path" and "docs/security.md" in p.message
                            for p in out), out)

    def test_bracketed_paths_found_by_exact_name(self):
        route = "a/api/[id]/route.ts"
        data = reg(lambda d: d["components"][0].update(
            docs=["docs/[slug].md"], interfaces=[{"path": route, "contract": "docs/[slug].md"}]))
        files = ["a/x.py", "b/y.py", "z.py", "docs/a.md", "docs/[slug].md", route]
        self.assertEqual(self.run_check(data, files), [])
        out = self.run_check(data, ["a/x.py", "b/y.py", "z.py", "docs/a.md", "docs/s.md", route])
        self.assertTrue(any("docs/[slug].md" in p.message and p.severity == "ERROR" for p in out))

    def test_planned_component(self):
        def planned(d):
            d["components"].append({"id": "mig", "planned": True, "paths": ["db/migrations/**"],
                                    "docs": ["docs/a.md"], "generated": ["docs/gen/schema.md"]})
        # Planned: paths and generated doc may be missing...
        self.assertEqual(self.run_check(reg(planned), ["a/x.py", "b/y.py", "docs/a.md", "z.py"]), [])
        # ...but its docs must exist.
        out = self.run_check(reg(planned), ["a/x.py", "b/y.py", "z.py"])
        self.assertTrue(any(p.location == "component mig.docs" and p.severity == "ERROR" for p in out))

    def test_generated_doc_of_built_component_must_exist(self):
        out = self.run_check(reg(lambda d: d["components"][0].update(generated=["docs/gen.md"])),
                             ["a/x.py", "b/y.py", "docs/a.md", "z.py"])
        self.assertTrue(any("generated doc does not exist" in p.message for p in out))

    def test_interface_and_contract_must_exist(self):
        data = reg(lambda d: d["components"][0].update(
            interfaces=[{"path": "a/route.ts", "contract": "docs/contract.md"}]))
        out = self.run_check(data, ["a/x.py", "b/y.py", "docs/a.md", "z.py"])
        messages = " ".join(p.message for p in out)
        self.assertIn("interface path does not exist: a/route.ts", messages)
        self.assertIn("contract does not exist: docs/contract.md", messages)


class LoadTests(unittest.TestCase):
    def write(self, root, name, text):
        p = Path(root) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)

    def test_load_from_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "impact.yml", json.dumps(cfg()))
            self.write(tmp, "registry/components.yml", json.dumps(reg()))
            loaded = load(Path(tmp))
        self.assertEqual(loaded.problems, ())
        self.assertFalse(loaded.has_errors)

    def test_deeply_nested_yaml_is_a_load_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "impact.yml", "a: " + "[" * 5000 + "]" * 5000 + "\n")
            with self.assertRaises(LoadError):
                load(Path(tmp))

    def test_unreadable_or_unparseable_files_raise_load_error(self):
        # LoadError is what Stage 3's CLI maps to exit code 2; that mapping is not built yet.
        cases = {
            "missing": None,
            "invalid YAML": "version: [1\n",
            "duplicate key": "version: 1\nversion: 1\nregistry: r.yml\n",
            "not UTF-8": b"version: 1\nregistry: \xff\n",
        }
        for label, text in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                if text is not None:
                    self.write(tmp, "impact.yml", text)
                with self.assertRaises(LoadError):
                    load(Path(tmp))

    def test_missing_registry_file_is_load_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "impact.yml", json.dumps(cfg()))
            with self.assertRaises(LoadError):
                load(Path(tmp))

    def test_yaml_is_loaded_safely(self):
        # A Python object tag must not be constructed by the safe loader.
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "x.yml", "a: !!python/object/apply:os.system ['echo hi']\n")
            with self.assertRaises(LoadError):
                read_yaml(Path(tmp) / "x.yml")


class RealRepositoryConfigTests(unittest.TestCase):
    """The committed impact.yml and registry must load with no problems."""

    def test_real_files_load_cleanly(self):
        loaded = load(REPO_ROOT)
        self.assertEqual(loaded.problems, (), "\n".join(map(str, loaded.problems)))
        ids = [c.id for c in loaded.registry.components]
        self.assertEqual(len(ids), 14)
        self.assertEqual(len(loaded.registry.triggers), 1)

    def test_real_dependencies_are_labelled(self):
        loaded = load(REPO_ROOT)
        deps = {(c.id, d.id): d.basis for c in loaded.registry.components for d in c.depends_on}
        self.assertEqual(deps, {
            ("api-routes", "web-lib"): "code",
            ("api-routes", "etl-loaders"): "inferred",
            ("web-lib", "web-config"): "code",
            ("web-ui", "api-routes"): "code",
            ("web-ui", "web-public"): "code",
        })


if __name__ == "__main__":
    unittest.main()
