import json
import unittest

from tools.impact.config import Problem
from tools.impact.findings import (DuplicateFindingError, Report, finding_id, from_problems, render_json,
                                   render_text)


def problem(subject="docs/a.md", message="doc does not exist: docs/a.md", rule="registry-missing-path",
            severity="ERROR", location="component app.docs", source="registry/components.yml"):
    return Problem(source, location, subject, rule, severity, message)


class FindingIdTests(unittest.TestCase):
    def test_format_and_stability(self):
        fid = finding_id("registry-missing-path", "registry/components.yml", "component app.docs", "docs/a.md")
        self.assertRegex(fid, r"\Aregistry-missing-path:[0-9a-f]{10}\Z")
        self.assertEqual(fid, finding_id("registry-missing-path", "registry/components.yml",
                                         "component app.docs", "docs/a.md"))

    def test_message_wording_does_not_change_the_id(self):
        a, = from_problems([problem(message="doc does not exist: docs/a.md")])
        b, = from_problems([problem(message="the doc docs/a.md is missing")])
        self.assertEqual(a.id, b.id)

    def test_each_identity_field_changes_the_id(self):
        base = from_problems([problem()])[0].id
        for changed in (problem(subject="docs/b.md"), problem(location="component other.docs"),
                        problem(source="other.yml"), problem(rule="registry-incomplete", severity="WARNING")):
            with self.subTest(changed=changed):
                self.assertNotEqual(from_problems([changed])[0].id, base)

    def test_different_problems_with_one_id_are_an_internal_error(self):
        with self.assertRaises(DuplicateFindingError):
            from_problems([problem(message="one"), problem(message="two")])

    def test_identical_problems_reported_twice_are_kept_once(self):
        self.assertEqual(len(from_problems([problem(), problem()])), 1)


class OrderingAndRenderingTests(unittest.TestCase):
    PROBLEMS = [
        problem(subject="z.md", message="doc does not exist: z.md"),
        Problem("registry/components.yml", "component web.paths", "web/x/**", "registry-incomplete",
                "WARNING", "pattern matches no file: web/x/**"),
        problem(subject="a.md", message="doc does not exist: a.md"),
        Problem("impact.yml", "(file)", "impact.yml", "registry-invalid", "ERROR",
                "impact.yml: not valid YAML (x)"),
        Problem("(working tree)", "file name", "tab\\there.py", "unsupported-path", "WARNING",
                "control character in path; the file is not analysed: tab\\there.py"),
    ]

    def report(self, problems=None):
        return Report("validate", "0123456789abcdef0123456789abcdef01234567", 12,
                      ("impact.yml", "registry/components.yml"), from_problems(problems or self.PROBLEMS))

    def test_fixed_order(self):
        rules = [(f.severity, f.rule, f.subject) for f in self.report().findings]
        self.assertEqual(rules, [
            ("ERROR", "registry-invalid", "impact.yml"),
            ("ERROR", "registry-missing-path", "a.md"),
            ("ERROR", "registry-missing-path", "z.md"),
            ("WARNING", "registry-incomplete", "web/x/**"),
            ("WARNING", "unsupported-path", "tab\\there.py"),
        ])

    def test_order_does_not_depend_on_input_order(self):
        self.assertEqual(self.report().findings, self.report(list(reversed(self.PROBLEMS))).findings)

    def test_summary_and_exit_code(self):
        r = self.report()
        self.assertEqual((r.errors, r.warnings, r.exit_code), (3, 2, 1))
        warnings_only = self.report([p for p in self.PROBLEMS if p.severity == "WARNING"])
        self.assertEqual(warnings_only.exit_code, 0)

    def test_json_document(self):
        text = render_json(self.report())
        self.assertTrue(text.endswith("}\n"))
        self.assertNotIn("\r", text)
        doc = json.loads(text)
        self.assertEqual(list(doc), sorted(doc))                       # sorted keys
        self.assertEqual(doc["schema_version"], 1)
        self.assertEqual(doc["summary"], {"errors": 3, "warnings": 2, "files": 12, "exit_code": 1})
        self.assertEqual([f["id"] for f in doc["findings"]], [f.id for f in self.report().findings])
        self.assertEqual(set(doc["findings"][0]), {"id", "rule", "severity", "source", "location",
                                                   "subject", "message"})
        self.assertNotIn("time", text.lower().replace("timeout", ""))  # no timestamps

    def test_json_is_byte_identical_across_runs(self):
        self.assertEqual(render_json(self.report()).encode(), render_json(self.report()).encode())

    def test_text_golden(self):
        r = self.report([problem(subject="a.md", message="doc does not exist: a.md")])
        fid = r.findings[0].id
        self.assertEqual(render_text(r),
                         "impact validate | HEAD 0123456 | 12 files | impact.yml + registry/components.yml\n"
                         f"ERROR    {fid}  registry/components.yml  component app.docs  doc does not exist: a.md\n"
                         "Summary: 1 ERROR, 0 WARNING | exit code 1\n")

    def test_text_without_commits_or_configuration(self):
        r = Report("validate", None, 0, (), ())
        self.assertEqual(render_text(r), "impact validate | HEAD no commits | 0 files | no configuration loaded\n"
                                         "Summary: 0 ERROR, 0 WARNING | exit code 0\n")
        self.assertIsNone(json.loads(render_json(r))["head"])

    def test_non_ascii_is_kept_in_json(self):
        r = self.report([problem(subject="docs/résumé.md", message="doc does not exist: docs/résumé.md")])
        self.assertIn("résumé", render_json(r))


if __name__ == "__main__":
    unittest.main()
