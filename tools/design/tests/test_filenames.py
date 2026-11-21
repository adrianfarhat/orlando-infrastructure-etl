"""File names from feature names: Unicode dashes become hyphens; ASCII behaviour is unchanged."""

import unittest

from tools.design import workspace
from tools.design.tests.test_design import Workspace, cmd
from tools.design.workspace import DesignError, new_feature, slugify


class UnicodeDashes(unittest.TestCase):
    def test_each_dash_and_the_minus_sign_separate_words(self):
        for name, ch in (("hyphen", "‐"), ("non-breaking hyphen", "‑"), ("figure dash", "‒"),
                         ("en dash", "–"), ("em dash", "—"), ("horizontal bar", "―"),
                         ("minus sign", "−"), ("small hyphen-minus", "﹣"),
                         ("fullwidth hyphen-minus", "－")):
            with self.subTest(name):
                self.assertEqual(slugify(f"Pipe{ch}Road Intersection Analysis"), "pipe-road-intersection-analysis")

    def test_runs_spaces_and_edges(self):
        cases = {
            "Pipe – Road": "pipe-road",                   # spaced en dash
            "Pipe——Road": "pipe-road",               # repeated dashes collapse
            "Pipe —–- Road": "pipe-road",            # mixed with an ASCII hyphen and spaces
            "–Leading and trailing—": "leading-and-trailing",
            "Phase 2–3 rollout": "phase-2-3-rollout",
            "Temperature −5": "temperature-5",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(slugify(name), expected)

    def test_only_dashes_is_still_refused(self):
        with self.assertRaises(DesignError):
            slugify("–—−")


class AsciiBehaviourIsUnchanged(unittest.TestCase):
    CASES = {
        "Pipe road intersections": "pipe-road-intersections",
        "Pipe-Road Intersection Analysis": "pipe-road-intersection-analysis",
        "  Many   spaces  ": "many-spaces",
        "Road/Pipe & #1 (v2)": "road-pipe-1-v2",
        "O'Brien Street": "o-brien-street",
        "snake_case name": "snake-case-name",
        "Résumé of road works": "resume-of-road-works",       # accents removed
        "日本語 roads": "roads",                            # no ASCII equivalent: dropped
        "O’Brien Street": "obrien-street",                          # other Unicode punctuation: unchanged
    }

    def test_known_names(self):
        for name, expected in self.CASES.items():
            with self.subTest(name=name):
                self.assertEqual(slugify(name), expected)

    def test_reserved_and_empty_names_are_still_refused(self):
        for name in ("Index", "Templates", "CON", "日本語", "!!!"):
            with self.subTest(name=name):
                with self.assertRaises(DesignError):
                    slugify(name)

    def test_length_limit(self):
        self.assertEqual(len(slugify("a" * 200)), workspace.MAX_SLUG)
        self.assertFalse(slugify("a" * 79 + "–b").endswith("-"))            # cut at the limit, no trailing hyphen


class NewFeatureFileNames(unittest.TestCase):
    def test_the_title_keeps_the_dash_and_the_file_name_has_a_hyphen(self):
        with Workspace() as ws:
            created = new_feature(ws.root, "Pipe–Road Intersection Analysis")
            self.assertEqual(created.path, "designs/features/pipe-road-intersection-analysis.md")
            self.assertEqual(ws.meta(created.path)["title"], "Pipe–Road Intersection Analysis")
            self.assertIn("# Feature Specification — Pipe–Road Intersection Analysis\n", ws.text(created.path))
            self.assertEqual(workspace.check(ws.root), [])

    def test_a_name_that_now_gives_an_existing_file_name_is_refused(self):
        with Workspace() as ws:
            new_feature(ws.root, "Pipe-Road Intersection Analysis")
            before = ws.text("designs/features/pipe-road-intersection-analysis.md")
            code, _, err = cmd(ws.root, "new", "feature", "--name", "Pipe—Road Intersection Analysis")
            self.assertEqual(code, 2)
            self.assertIn("already exists; nothing was overwritten", err)
            self.assertEqual(ws.text("designs/features/pipe-road-intersection-analysis.md"), before)

    def test_existing_files_with_old_names_are_not_renamed(self):
        """A file made before this fix (piperoad-...) keeps its name; index and check leave it there."""
        with Workspace() as ws:
            old = new_feature(ws.root, "Placeholder")
            legacy = ws.root / "designs/features/piperoad-intersection-analysis.md"
            (ws.root / old.path).rename(legacy)
            text = legacy.read_bytes().decode("utf-8").replace('title: "Placeholder"',
                                                               'title: "Pipe–Road Intersection Analysis"')
            legacy.write_bytes(text.encode("utf-8"))
            self.assertEqual(cmd(ws.root, "index")[0], 0)
            self.assertEqual(workspace.check(ws.root), [])
            self.assertTrue(legacy.is_file())
            self.assertFalse((ws.root / "designs/features/pipe-road-intersection-analysis.md").exists())
            # and a new feature with the same title is refused by title, not created next to it
            code, _, err = cmd(ws.root, "new", "feature", "--name", "Pipe–Road Intersection Analysis")
            self.assertEqual(code, 2)
            self.assertIn("already exists", err)


if __name__ == "__main__":
    unittest.main()
