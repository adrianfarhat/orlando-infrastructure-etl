"""Stage 83b-3: acknowledgement parsing and checking (unit tests, no Git)."""

import unittest

from tools.impact import acks
from tools.impact.acks import AckFileError, decode, parse
from tools.impact.config import Problem, parse_config
from tools.impact.findings import from_problems

CONFIG, _ = parse_config({"version": 1, "registry": "registry/components.yml"})


def findings():
    return from_problems([
        Problem("app/a.py", "change", "app/a.py", "unregistered-path", "WARNING", "w1"),
        Problem("registry/components.yml", "component app", "app", "docs-not-updated", "WARNING", "w2"),
        Problem("docs/x.md", "reference", "app/old.py", "stale-reference", "ERROR", "e1"),
    ])


def ids():
    by_rule = {f.rule: f.id for f in findings()}
    return by_rule["unregistered-path"], by_rule["docs-not-updated"], by_rule["stale-reference"]


REASON = "reviewed; no change needed because the API is unchanged"


class Parsing(unittest.TestCase):
    def test_only_ack_lines_are_read(self):
        w1, w2, _ = ids()
        text = (f"## PR\nSome text mentioning - ack in prose.\n- ack {w1}: {REASON}\n  -   ack {w2} :  spaced  \n"
                f"* ack {w1}: star bullets are not acks\n-ack {w1}: no space\n- acknowledge {w1}: other word\n")
        p = parse(text)
        self.assertEqual([(a.id, a.reason, a.line) for a in p.acks], [(w1, REASON, 3), (w2, "spaced", 4)])
        self.assertEqual(p.malformed, ())

    def test_malformed_ack_lines(self):
        p = parse("- ack\n- ack xyz: reason here long enough\n- ack docs-not-updated:12345: short id\n"
                  "- ack docs-not-updated:abcdef0123 missing colon\n- ack DOCS:abcdef0123: upper case\n")
        self.assertEqual([n for n, _ in p.malformed], [1, 2, 3, 4, 5])
        self.assertEqual(p.acks, ())

    def test_decoding(self):
        self.assertEqual(decode("﻿- ack x".encode("utf-8")), "- ack x")
        self.assertEqual(parse(decode(b"- ack a:0123456789: reason\r\n")).acks[0].reason, "reason")
        with self.assertRaisesRegex(AckFileError, "not valid UTF-8"):
            decode(b"\xff\xfe- ack")
        with self.assertRaisesRegex(AckFileError, "larger than"):
            decode(b"x" * (acks.MAX_ACK_BYTES + 1))


class Applying(unittest.TestCase):
    def apply(self, text, config=CONFIG):
        return acks.apply(findings(), parse(text), config)

    def test_valid_ack_applies_to_a_warning(self):
        w1, w2, _ = ids()
        got = self.apply(f"- ack {w1}: {REASON}\n")
        self.assertEqual((got.acknowledged, got.problems), ({w1: REASON}, ()))

    def test_ack_on_an_error_is_rejected(self):
        _, _, e1 = ids()
        got = self.apply(f"- ack {e1}: {REASON}\n")
        self.assertEqual(got.acknowledged, {})
        self.assertEqual([(p.rule, p.severity, p.subject) for p in got.problems],
                         [("ack-problem", "WARNING", f"error: {e1}")])
        self.assertIn("the ERROR still counts", got.problems[0].message)

    def test_unknown_or_stale_id(self):
        got = self.apply(f"- ack docs-not-updated:0000000000: {REASON}\n")
        self.assertEqual([p.subject for p in got.problems], ["unknown: docs-not-updated:0000000000"])
        self.assertEqual(got.acknowledged, {})

    def test_bad_reasons(self):
        w1, _, _ = ids()
        cases = {"": "empty", "OK": "placeholder", "  Not needed. ": "placeholder", "No change!": "placeholder",
                 "too short": "too short (9 < 15"}
        for reason, expected in cases.items():
            with self.subTest(reason=reason):
                got = self.apply(f"- ack {w1}: {reason}\n")
                self.assertEqual(got.acknowledged, {})
                self.assertEqual(len(got.problems), 1)
                self.assertIn(expected, got.problems[0].message)
                self.assertIn("stays unacknowledged", got.problems[0].message)
        exact = "x" * CONFIG.ack_min_reason_length                         # boundary: exactly the minimum
        self.assertEqual(self.apply(f"- ack {w1}: {exact}\n").acknowledged, {w1: exact})

    def test_duplicates_use_the_first_valid_ack(self):
        w1, _, _ = ids()
        got = self.apply(f"- ack {w1}: ok\n- ack {w1}: {REASON}\n- ack {w1}: another valid reason here\n")
        self.assertEqual(got.acknowledged, {w1: REASON})
        subjects = sorted(p.subject for p in got.problems)
        self.assertEqual(subjects, [f"duplicate: {w1}", f"reason: {w1}"])
        dup = next(p for p in got.problems if p.subject.startswith("duplicate"))
        self.assertIn("line 2, 3", dup.message)

    def test_ack_problem_ids_do_not_depend_on_line_numbers(self):
        a = from_problems(self.apply("- ack docs-not-updated:0000000000: some reason here\n").problems)
        b = from_problems(self.apply("\n\n\nintro\n- ack docs-not-updated:0000000000: some reason here\n").problems)
        self.assertEqual([f.id for f in a], [f.id for f in b])
        self.assertNotEqual(a[0].message, b[0].message)

    def test_repeated_malformed_lines_are_one_problem(self):
        got = self.apply("- ack broken\nfiller\n- ack broken\n")
        self.assertEqual(len(got.problems), 1)
        self.assertIn("line 1, 3", got.problems[0].message)
        from_problems(got.problems)                                       # no duplicate-ID error

    def test_rule_off_hides_problems_but_still_rejects_bad_acks(self):
        cfg, _ = parse_config({"version": 1, "registry": "registry/components.yml",
                               "rules": {"ack-problem": "off"}})
        _, _, e1 = ids()
        got = self.apply(f"- ack {e1}: {REASON}\n- ack nonsense\n", cfg)
        self.assertEqual((got.acknowledged, got.problems), ({}, ()))

    def test_configured_threshold_and_placeholders(self):
        cfg, _ = parse_config({"version": 1, "registry": "registry/components.yml",
                               "acks": {"min_reason_length": 3, "placeholders": ["meh"]}})
        w1, _, _ = ids()
        self.assertEqual(self.apply(f"- ack {w1}: fine\n", cfg).acknowledged, {w1: "fine"})
        self.assertEqual(self.apply(f"- ack {w1}: MEH\n", cfg).acknowledged, {})


if __name__ == "__main__":
    unittest.main()
