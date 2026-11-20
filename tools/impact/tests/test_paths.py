import glob
import re
import time
import unittest
from pathlib import Path

from tools.impact.config import load
from tools.impact.paths import (MAX_DOUBLE_STAR_SEGMENTS, MAX_STARS_PER_SEGMENT, PathError, is_literal,
                                matches, normalize, normalize_pattern, specificity, star_operators)

REPO_ROOT = Path(__file__).resolve().parents[3]

# (pattern, path, expected). Verified on Python 3.15.2 against both
# PurePosixPath.full_match and glob.translate before Stage 2 (0 mismatches).
MATCH_CASES = [
    ("extractors/**", "extractors/load.py", True),
    ("extractors/**", "extractors/a/b.py", True),
    ("extractors/**", "extractors/new loader.py", True),
    ("extractors/**", "extractors/na\u00efve.py", True),
    ("extractors/**", "extractorsx/a.py", False),
    ("**/*.py", "x.py", True),
    ("**/*.py", "a/b/x.py", True),
    ("**/*.py", "x.pyc", False),
    ("web/src/**/*.ts", "web/src/x.ts", True),
    ("web/src/**/*.ts", "web/src/lib/db.ts", True),
    ("web/src/**/*.ts", "web/src/lib/db.tsx", False),
    (".claude/**", ".claude/agents/x.md", True),
    ("**/*.md", ".claude/agents/x.md", True),
    ("**/*.md", "CLAUDE.md", True),
    ("docs/**", "docs/doc-map.yml", True),
    ("*.md", "docs/a.md", False),
    ("web/next.config.ts", "web/next.config.ts", True),
    ("Web/next.config.ts", "web/next.config.ts", False),
    ("web/src/app/**", "web/src/app/api/x/route.ts", True),
    ("web/src/app/api/**/route.ts", "web/src/app/api/route.ts", True),
    ("web/src/app/api/**/route.ts", "web/src/app/api/a/b/route.ts", True),
]


class MatchTests(unittest.TestCase):
    def test_verified_cases(self):
        for pattern, path, expected in MATCH_CASES:
            with self.subTest(pattern=pattern, path=path):
                self.assertEqual(matches(path, pattern), expected)

    def test_extra_edge_cases(self):
        cases = [
            ("web/src/app/**", "web/src/app", False),         # trailing ** needs >= 1 segment
            ("a/**/b", "a/b", True),                           # middle ** matches zero segments
            ("a/*/c", "a/b/c", True),
            ("a/*/c", "a/b/x/c", False),                       # * never crosses /
            ("a/?.py", "a/b.py", True),
            ("a/?.py", "a/bb.py", False),
            ("a/[bc].py", "a/c.py", True),
            ("requirements.txt", "web/requirements.txt", False),  # literal is anchored at the root
            ("**", "anything/at/all.txt", True),
        ]
        for pattern, path, expected in cases:
            with self.subTest(pattern=pattern, path=path):
                self.assertEqual(matches(path, pattern), expected)

    def test_agrees_with_glob_translate(self):
        """The migration test's old side uses glob.translate; both matchers must agree."""
        extra = [("web/src/app/**", "web/src/app"), ("a/**/b", "a/b"), ("a/b/**", "a/b"),
                 ("a/*/c", "a/b/x/c"), ("**", "x")]
        for pattern, path in [(p, q) for p, q, _ in MATCH_CASES] + extra:
            with self.subTest(pattern=pattern, path=path):
                translated = re.fullmatch(glob.translate(pattern, recursive=True, include_hidden=True), path)
                self.assertEqual(matches(path, pattern), translated is not None)


class NormalizeTests(unittest.TestCase):
    def test_normalizes(self):
        self.assertEqual(normalize("a\\b\\c.py"), "a/b/c.py")
        self.assertEqual(normalize("./a/b"), "a/b")
        self.assertEqual(normalize("././a"), "a")
        self.assertEqual(normalize("extractors/new loader.py"), "extractors/new loader.py")
        self.assertEqual(normalize("extractors/na\u00efve.py"), "extractors/na\u00efve.py")
        self.assertEqual(normalize("CLAUDE.md"), "CLAUDE.md")  # case is preserved

    def test_rejects(self):
        for bad in ["", "./", "/abs/path", "C:/x", "C:\\x", "C:", "c:/x", "a/../b", "..", "a/./b", "a//b",
                    "a/", ".//a", "a/b\x00c", "a\tb", "a\nb", "a\x7fb", None, 3, ["a"]]:
            with self.subTest(bad=bad):
                with self.assertRaises(PathError):
                    normalize(bad)

    def test_rejection_messages(self):
        with self.assertRaisesRegex(PathError, "double '/'"):
            normalize(".//a")
        with self.assertRaisesRegex(PathError, "control character"):
            normalize("a/b\x00c")
        with self.assertRaisesRegex(PathError, "absolute"):
            normalize("C:/x")

    def test_drive_path_behind_dot_slash_is_still_absolute(self):
        # Regression: the absolute check ran before "./" was stripped, so "./C:/x" passed as "C:/x".
        backslashed = ["." + chr(92) + "C:" + chr(92) + "x", "./c:" + chr(92) + "x"]
        for bad in ["./C:/x", "./C:", "././c:/x"] + backslashed:
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(PathError, "absolute"):
                    normalize(bad)
        for pattern in ["./C:/**", "./c:/x/*"]:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(PathError, "absolute"):
                    normalize_pattern(pattern)
        self.assertEqual(normalize("./a:b"), "a:b")  # a colon that is not a drive stays valid

    def test_c1_control_characters_are_rejected(self):
        for code in (0x80, 0x85, 0x9F):
            with self.subTest(code=hex(code)):
                with self.assertRaisesRegex(PathError, "control character"):
                    normalize("a/b" + chr(code) + "c")
                with self.assertRaisesRegex(PathError, "control character"):
                    normalize_pattern("a/*" + chr(code))
        self.assertEqual(normalize("a/" + chr(0xA0) + "b"), "a/" + chr(0xA0) + "b")  # no-break space is not a control

    def test_colon_that_is_not_a_drive_is_allowed(self):
        self.assertEqual(normalize("a:b"), "a:b")
        self.assertEqual(normalize("x:y/z"), "x:y/z")

    def test_nextjs_dynamic_route_path(self):
        route = "web/src/app/api/[id]/route.ts"
        self.assertEqual(normalize(route), route)
        self.assertTrue(matches(route, "web/src/app/api/**/route.ts"))
        self.assertFalse(matches(route, "web/src/app/api/[id]/route.ts"))  # [id] is a class in a glob
        self.assertTrue(matches(route, "web/src/app/api/[[]id]/route.ts"))  # documented literal form

    def test_pattern_rules(self):
        self.assertEqual(normalize_pattern("web\\src\\**"), "web/src/**")
        for bad in ["a**b/c", "a/b**", "**x", "/a/**", "a/../**"]:
            with self.subTest(bad=bad):
                with self.assertRaises(PathError):
                    normalize_pattern(bad)

    def test_is_literal(self):
        self.assertTrue(is_literal("web/next.config.ts"))
        for pat in ["a/*", "a/?", "a/[x]", "**"]:
            self.assertFalse(is_literal(pat))


class SpecificityTests(unittest.TestCase):
    def test_values(self):
        self.assertEqual(specificity("web/src/app/api/**"), (4, False))
        self.assertEqual(specificity("web/src/app/**"), (3, False))
        self.assertEqual(specificity("**/*.py"), (0, False))
        self.assertEqual(specificity("web/next.config.ts"), (2, True))
        self.assertEqual(specificity("a/*/c"), (1, False))  # only LEADING literal segments count

    def test_ordering(self):
        self.assertGreater(specificity("web/src/app/api/**"), specificity("web/src/app/**"))
        self.assertGreater(specificity("extractors/**"), specificity("**/*.py"))

    def test_exact_path_beats_glob_on_same_path(self):
        # The closest a glob can get: a middle ** matching zero segments.
        self.assertTrue(matches("a/b/c", "a/b/**/c"))
        self.assertGreater(specificity("a/b/c"), specificity("a/b/**/c"))
        # A trailing ** never matches the folder itself, so it cannot compete with it.
        self.assertFalse(matches("a/b", "a/b/**"))
        self.assertGreater(specificity("a/b"), specificity("a/b/**"))


class DoubleStarLimitTests(unittest.TestCase):
    def test_limit_value_and_enforcement(self):
        self.assertEqual(MAX_DOUBLE_STAR_SEGMENTS, 3)
        self.assertEqual(normalize_pattern("a/**/b/**/c/**/d"), "a/**/b/**/c/**/d")  # exactly 3
        with self.assertRaisesRegex(PathError, "more than 3"):
            normalize_pattern("a/**/b/**/c/**/d/**/e")                              # 4

    def test_worst_allowed_pattern_is_fast(self):
        # Measured before setting the limit (Python 3.15.2): 3 x '**/*' ~0.0001 s,
        # 4 x ~0.0014 s, 8 x ~1.8 s on a 40-segment non-matching path. The bound is
        # generous to avoid timing noise while still catching the slow class.
        pattern = normalize_pattern("**/*/**/*/**/*.ts")
        path = "/".join(["d"] * 40) + "/x.py"
        start = time.perf_counter()
        self.assertFalse(matches(path, pattern))
        self.assertLess(time.perf_counter() - start, 0.5)

    def test_every_real_pattern_is_within_the_limit(self):
        loaded = load(REPO_ROOT)
        self.assertEqual(loaded.problems, ())
        c, r = loaded.config, loaded.registry
        patterns = list(c.ignore) + list(c.reference_include) + list(c.reference_exclude)
        patterns += [p for _, pats in c.purposes + c.interfaces for p in pats]
        patterns += [p for comp in r.components for p in comp.paths + comp.exclude]
        patterns += [p for t in r.triggers for p in t.paths + t.exclude]
        self.assertGreater(len(patterns), 40)
        for p in patterns:
            with self.subTest(pattern=p):
                self.assertLessEqual(p.split("/").count("**"), MAX_DOUBLE_STAR_SEGMENTS)
                self.assertTrue(all(star_operators(s) <= 1 for s in p.split("/")),
                                "real patterns use at most one '*' per segment")
                self.assertEqual(normalize_pattern(p), p)


class StarPerSegmentLimitTests(unittest.TestCase):
    def test_boundary(self):
        self.assertEqual(MAX_STARS_PER_SEGMENT, 3)
        self.assertEqual(normalize_pattern("a*b*c*d"), "a*b*c*d")                    # exactly 3
        with self.assertRaisesRegex(PathError, "more than 3 '\\*' wildcards in one segment"):
            normalize_pattern("a*b*c*d*")                                             # 4
        with self.assertRaisesRegex(PathError, "'x\\*y\\*z\\*w\\*'"):
            normalize_pattern("dir/x*y*z*w*/f")                                       # names the segment

    def test_limit_is_per_segment_and_ignores_double_star(self):
        self.assertEqual(normalize_pattern("a*b*c*/d*e*f*/g*h*i*"), "a*b*c*/d*e*f*/g*h*i*")
        self.assertEqual(normalize_pattern("**/a*b*c*/**/x"), "**/a*b*c*/**/x")
        self.assertEqual(star_operators("**"), 0)

    def test_stars_inside_character_classes_are_literal(self):
        cases = {
            "*": 1, "a*b": 1, "?*?": 1,
            "[*]": 0, "[*]a*b*c*": 3, "[!*]x": 0, "[]*]x": 0, "[!]*]x": 0,
            "[*][*][*][*]": 0, "a[*]*": 1,
            "[*x": 1,            # unclosed '[' is literal; the '*' after it is an operator
            "x[": 0, "[": 0, "[]": 0,
        }
        for segment, expected in cases.items():
            with self.subTest(segment=segment):
                self.assertEqual(star_operators(segment), expected)
        self.assertEqual(normalize_pattern("[*][*][*][*]a*b*c*"), "[*][*][*][*]a*b*c*")   # 3 operators
        self.assertEqual(star_operators("[*x*y*z"), 3)                                    # unclosed '['
        self.assertEqual(normalize_pattern("[*x*y*z"), "[*x*y*z")                         # 3: allowed
        with self.assertRaises(PathError):
            normalize_pattern("[*x*y*z*")                                                 # 4 operators

    def test_backslash_splits_segments_before_counting(self):
        # Backslashes become '/' first, so "a*b*\c*d*" is two segments of 2 stars each.
        self.assertEqual(normalize_pattern("a*b*" + chr(92) + "c*d*"), "a*b*/c*d*")
        self.assertEqual(normalize_pattern("a*b*c*" + chr(92) + "d*e*f*"), "a*b*c*/d*e*f*")
        with self.assertRaises(PathError):
            normalize_pattern("x/a*b*c*d*" + chr(92) + "e")

    def test_class_parsing_agrees_with_the_glob_engine(self):
        # The counting rules must describe what full_match actually does. Independent QA
        # (2026-11-19) also compared star_operators with the star count of the stdlib
        # translator for 279,280 exhaustive segments (length <= 6 over "[]!*?a-\\") and
        # 254,735 random ones: 0 undercounts, 0 overcounts. That comparison used a private
        # stdlib function, so it is recorded here rather than run as a test.
        self.assertTrue(matches("*x", "[*]x"))
        self.assertFalse(matches("ax", "[*]x"))           # '*' in a class is literal
        self.assertTrue(matches("]x", "[]*]x"))
        self.assertTrue(matches("*x", "[]*]x"))
        self.assertFalse(matches("ax", "[]*]x"))          # ']' first is literal; class is {']', '*'}
        self.assertTrue(matches("ax", "[!*]x"))
        self.assertFalse(matches("*x", "[!*]x"))
        self.assertTrue(matches("[abcx", "[*x"))          # unclosed '[' literal, then '*' operator

    def test_worst_allowed_segment_is_fast(self):
        # Measured (Python 3.15.2), non-matching name: 3 stars at 200 chars 0.012 s,
        # 1000 chars 0.56 s; 4 stars (now rejected) at 1000 chars > 25 s.
        # Names are at most ~255 bytes on common file systems.
        pattern = normalize_pattern("*a*a*ab")
        start = time.perf_counter()
        self.assertFalse(matches("a" * 255 + "c", pattern))
        self.assertLess(time.perf_counter() - start, 0.5)

    def test_worst_allowed_combination_is_fast(self):
        # 3 '**' segments each followed by a 3-star segment, 40 segments of 60 chars:
        # measured 0.013 s.
        pattern = normalize_pattern("/".join(["**", "*a*a*ab"] * 3))
        path = "/".join(["a" * 60] * 40) + "/x"
        start = time.perf_counter()
        self.assertFalse(matches(path, pattern))
        self.assertLess(time.perf_counter() - start, 0.5)


if __name__ == "__main__":
    unittest.main()
