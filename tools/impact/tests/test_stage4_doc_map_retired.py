"""T-83 Stage 4: docs/doc-map.yml is retired and nothing scanned still points at it.

The registry (registry/components.yml) replaced the doc map in Stage 2; the migration
proof (test_migration.py) runs on the frozen copy, which must stay. The future
stale-reference rule (impact check, phase 83b) scans the files selected by impact.yml's
reference_scan for literal references to deleted paths, so the retired path must not
appear in any of them, or that rule would report an ERROR against this repository's own
configuration and docs.
"""

import unittest
from pathlib import Path

from tools.impact import gitfiles
from tools.impact.config import load
from tools.impact.paths import matches

REPO_ROOT = Path(__file__).resolve().parents[3]
RETIRED = "docs/doc-map.yml"
FROZEN_COPY = "tools/impact/tests/fixtures/docmap_565706f.yml"


class DocMapRetiredTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loaded = load(REPO_ROOT)
        cls.listing = gitfiles.list_files(REPO_ROOT)

    def test_retired_file_is_gone(self):
        self.assertFalse((REPO_ROOT / RETIRED).exists())
        self.assertNotIn(RETIRED, self.listing.files)

    def test_frozen_copy_is_kept_for_the_migration_proof(self):
        self.assertIn(FROZEN_COPY, self.listing.files)

    def test_no_scanned_file_references_the_retired_path(self):
        config = self.loaded.config
        self.assertEqual(self.loaded.problems, ())
        scanned = [f for f in self.listing.files
                   if any(matches(f, p) for p in config.reference_include)
                   and not any(matches(f, p) for p in config.reference_exclude)]
        self.assertIn("docs/architecture/conventions.md", scanned)    # the scan really covers docs
        self.assertIn("registry/components.yml", scanned)
        offenders = [f for f in scanned
                     if RETIRED in (REPO_ROOT / f).read_text("utf-8", errors="replace")]
        self.assertEqual(offenders, [], f"still referencing {RETIRED}: {offenders}")

    def test_registry_header_points_at_the_frozen_copy(self):
        header = (REPO_ROOT / "registry" / "components.yml").read_text("utf-8").splitlines()[1]
        self.assertIn(FROZEN_COPY, header)
        self.assertTrue((REPO_ROOT / FROZEN_COPY).exists())

    def test_conventions_point_to_the_registry(self):
        text = (REPO_ROOT / "docs" / "architecture" / "conventions.md").read_text("utf-8")
        self.assertIn("(../../registry/components.yml)", text)
        self.assertIn("(../../impact.yml)", text)
        self.assertIn("## 5. Branch docs workflow", text)            # target of #5-branch-docs-workflow
        self.assertIn("most specific matching component", text)       # the matching rule is documented
        self.assertIn("leading path segments with no wildcard", text)   # how specificity is measured
        self.assertIn("tie for the highest score", text)               # ties combine docs...
        self.assertIn("registry-incomplete", text)                      # ...and validate warns
        self.assertIn("`test`, `generated` or `experimental`", text)    # obligation exemptions
        self.assertNotIn("doc-map.yml", text)


if __name__ == "__main__":
    unittest.main()
