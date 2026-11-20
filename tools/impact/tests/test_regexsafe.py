import random
import re
import time
import unittest

from tools.impact import regexsafe as rs
from tools.impact.regexsafe import UnsafeRegex, check, scan

ACCEPTED = {
    # pattern: (literal, choices)
    "DATABASE_URL": ("DATABASE_URL", 1),
    "a\\.b": ("a.b", 1),                           # escaped punctuation stays a literal
    "API_KEY\\b": (None, 1),
    "[A-Z_]{1,20}_URL": (None, 20),
    "foo.{0,20}bar": (None, 21),
    "colou?r": (None, 2),
    "(?:dev|prod)_DB": (None, 2),
    "^import psycopg$": (None, 1),
    "\\d{3}-\\d{4}": (None, 1),
    "[\\]a]x": (None, 1),
    "a{2,5}?b": (None, 4),                         # lazy bounded
    "((a|aa)(a|aa))((a|aa)(a|aa))((a|aa)(a|aa))b": (None, 64),
}

REJECTED = {
    # one or more per rule: pattern -> fragment of the reason
    "(a+)+$": "unbounded",
    "(a|aa)*": "quantified groups",
    "(\\w+\\s?)*": "unbounded",
    "(ab){2}": "quantified groups",
    "(a)\\1": "backreferences",
    "(?=x)": "only plain",
    "(?<!x)y": "only plain",
    "(?i)x": "only plain",
    "(?P<n>x)": "only plain",
    ".*": "unbounded",
    "a*b": "unbounded",
    "\\w+b": "unbounded",
    "a{2,}b": "unbounded",
    "a{1,1000}": "above 20",
    "a{0,21}": "above 20",
    "x" * 201: "longer than 200",
    "a{3}{2}": "stacked",
    "a?+": "stacked",
    "^?": "quantified assertions",
    "\\b{2}": "quantified assertions",
    "*a": "nothing to repeat",
    "(|?)": "nothing to repeat",
    "[a-z": "unterminated",
    "a)": "unbalanced ')'",
    "(a": "unbalanced '('",
    "\\n": "newline",
    "[\\n]": "not allowed in a class",
    "a\nb": "newlines",
    "[[a]]": "'[' inside a character class",
    "[a--b]": "set operators",
    "[a&&b]": "set operators",
    "\\": "lone backslash",
    "\\q": "escape \\q",
    "\\x41": "escape \\x",
    "a{x}": "must start a quantifier",
    "{": "must start a quantifier",
    "a{5,2}": "max below min",
    "(a|b)(a|b)(a|b)(a|b)(a|b)(a|b)(a|b)": "128 choices",
    "a?a?a?a?a?a?a?b": "128 choices",
    "": "non-empty",
}


class CheckTests(unittest.TestCase):
    def test_accepted_patterns_and_profiles(self):
        for pattern, (literal, choices) in ACCEPTED.items():
            with self.subTest(pattern=pattern):
                profile = check(pattern)
                self.assertEqual(profile.literal, literal)
                self.assertEqual(profile.branching, choices)
                re.compile(pattern)

    def test_rejected_patterns(self):
        for pattern, reason in REJECTED.items():
            with self.subTest(pattern=pattern):
                with self.assertRaises(UnsafeRegex) as ctx:
                    check(pattern)
                self.assertIn(reason, str(ctx.exception))

    def test_unbounded_message_suggests_bounded_form(self):
        with self.assertRaisesRegex(UnsafeRegex, "use a bounded form such as \\{1,20\\}"):
            check("[A-Z_]+_URL")

    def test_real_trigger_is_a_literal(self):
        self.assertEqual(check("DATABASE_URL").literal, "DATABASE_URL")


class ScanTests(unittest.TestCase):
    def test_literal_scans_whole_text_without_limit(self):
        profile = check("NEEDLE")
        text = "x" * (rs.MAX_SCAN_CHARS * 3) + "NEEDLE"
        self.assertEqual(scan(re.compile("NEEDLE"), profile, text), rs.ScanResult(True, True))
        self.assertEqual(scan(re.compile("NEEDLE"), profile, "x" * (rs.MAX_SCAN_CHARS * 3)),
                         rs.ScanResult(False, True))

    def test_non_literal_matches_within_lines(self):
        rx, profile = re.compile("^import [a-z]{1,10}$"), check("^import [a-z]{1,10}$")
        self.assertTrue(scan(rx, profile, "x = 1\nimport psycopg\n").matched)
        self.assertFalse(scan(rx, profile, "x = 1 import psycopg\n").matched)  # anchors are per line
        self.assertTrue(scan(rx, profile, "x = 1 import psycopg\n").complete)

    def test_text_beyond_the_cap_is_reported_not_scanned(self):
        rx, profile = re.compile("SECRET_[A-Z]{1,5}"), check("SECRET_[A-Z]{1,5}")
        line = "y" * 999
        lines = [line] * (rs.MAX_SCAN_CHARS // 999 + 5)
        # Match only past the cap: not "no match", but "not scanned".
        result = scan(rx, profile, "\n".join(lines + ["SECRET_KEY"]))
        self.assertEqual(result, rs.ScanResult(False, False))
        # Match before the cap: found.
        self.assertEqual(scan(rx, profile, "\n".join(["SECRET_KEY"] + lines)), rs.ScanResult(True, True))
        # Short text, no match: complete "no match".
        self.assertEqual(scan(rx, profile, "nothing here\n"), rs.ScanResult(False, True))

    def test_single_line_longer_than_the_cap(self):
        rx, profile = re.compile("[A-Z]{3}"), check("[A-Z]{3}")
        self.assertEqual(scan(rx, profile, "a" * (rs.MAX_SCAN_CHARS + 1)), rs.ScanResult(False, False))


class AdversarialTimingTests(unittest.TestCase):
    """Accepted patterns on worst-case input. Measured on Python 3.15.2 at the full
    MAX_SCAN_CHARS cap (non-matching text of "a"): worst 0.51 s for 64 nested alternation
    choices; unbounded forms (rejected) took up to 7.2 s on 256 KB."""

    WORST = ["((a|aa)(a|aa))((a|aa)(a|aa))((a|aa)(a|aa))b", "(a|aa)(a|aa)(a|aa)(a|aa)(a|aa)(a|aa)b",
             "(aaaa|aaa|aa|a)(aaaa|aaa|aa|a)(aaaa|aaa|aa|a)b", "a?a?a?a?a?a?b", "\\w{0,20}\\w{0,2}b",
             "[a-z]{1,20}[a-z]{1,2}b", "a{20}" * 9 + "b", ".{20}" * 30 + "b"]

    def time_scan(self, pattern, text):
        rx, profile = re.compile(pattern), check(pattern)
        start = time.perf_counter()
        result = scan(rx, profile, text)
        return time.perf_counter() - start, result

    def test_worst_accepted_patterns_at_the_cap(self):
        text = "\n".join(["a" * 1000] * (rs.MAX_SCAN_CHARS // 1001))
        for pattern in self.WORST[:2]:
            with self.subTest(pattern=pattern):
                elapsed, result = self.time_scan(pattern, text)
                self.assertFalse(result.matched)
                self.assertLess(elapsed, 2.5)          # measured ~0.45-0.51 s

    def test_worst_accepted_patterns_on_long_and_short_lines(self):
        texts = {"long line": "a" * 100_000, "short lines": "\n".join(["a" * 50] * 2000)}
        for pattern in self.WORST:
            for label, text in texts.items():
                with self.subTest(pattern=pattern, text=label):
                    elapsed, _ = self.time_scan(pattern, text)
                    self.assertLess(elapsed, 0.5)

    def test_fuzzed_accepted_patterns_stay_fast(self):
        """Random patterns from the allowed alphabet: every one the checker accepts must
        scan a 20,000-character adversarial text quickly. Deterministic seed."""
        rng = random.Random(83)
        atoms = ["a", "b", ".", "\\w", "[ab]", "[^b]", "(a|aa)", "(?:a|b|ab)"]
        quants = ["", "", "?", "{0,3}", "{1,20}", "{2}", "*", "+", "{2,}"]
        text = "\n".join(["a" * 1000] * 20)
        accepted = 0
        for _ in range(400):
            pattern = "".join(rng.choice(atoms) + rng.choice(quants) for _ in range(rng.randint(1, 8))) + "c"
            try:
                profile = check(pattern)
            except UnsafeRegex:
                continue
            accepted += 1
            start = time.perf_counter()
            scan(re.compile(pattern), profile, text)
            with self.subTest(pattern=pattern):
                self.assertLess(time.perf_counter() - start, 0.25)
        self.assertGreater(accepted, 30)

    def test_literal_profile_agrees_with_re(self):
        rng = random.Random(7)
        for pattern in ["DATABASE_URL", "a\\.b", "x\\-y", "\\$HOME"]:
            profile = check(pattern)
            self.assertIsNotNone(profile.literal)
            for _ in range(50):
                text = "".join(rng.choice("ab.-$HOMEx_DATABASE_URLy\n") for _ in range(40))
                self.assertEqual(profile.literal in text, re.search(pattern, text) is not None,
                                 (pattern, text))


if __name__ == "__main__":
    unittest.main()
