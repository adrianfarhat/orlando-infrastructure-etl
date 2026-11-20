"""Stage 83b-5: end-to-end acceptance of the T-83 workflow (plan -> change -> check -> acknowledge).

One realistic branch on a throwaway repository with every change origin (committed,
staged, unstaged, untracked), a rename, a deletion and an ignored file, checked through
the real command line. Each test starts from the same scenario.
"""

import json
import unittest
from pathlib import Path

from .test_check_cli import full_snapshot
from .test_cli import run
from .test_rules import LINES, rules_repo

PROPOSED = ("core/base.py", "lib/util.py", "api/orders/route.ts", "app/old.py", "app/main.py", "misc/new.txt",
            "data/raw/x.py")


def cli(repo, *args):
    return run(*args[:1], "--root", str(repo.root), *args[1:])


def as_json(repo, *args):
    code, out, err = cli(repo, *args, "--format", "json")
    return code, json.loads(out) if out else None, err


class Scenario(unittest.TestCase):
    def setUp(self):
        self.repo = rules_repo()
        r = self.repo
        r.write("docs/refs.md", "Utilities live in `lib/util.py`.\n"); r.add_all(); r.commit("refs")
        # Predict before changing anything (task start).
        code, self.plan, err = as_json(r, "plan", "--paths", *PROPOSED)
        self.assertEqual((code, err), (0, ""))
        r.git("checkout", "-q", "-b", "feature")
        # committed on the branch
        r.write("core/base.py", LINES + "key = SECRET\n")
        r.git("mv", "lib/util.py", "lib/moved.py")
        r.add_all(); r.commit("feature work")
        # staged
        r.write("api/orders/route.ts", "export {}\n"); r.git("add", "api/orders/route.ts")
        r.git("rm", "-q", "app/old.py")
        # unstaged
        r.write("app/main.py", LINES + "more\n")
        r.write("docs/app.md", "# app\nupdated for this change\n")
        # untracked
        r.write("misc/new.txt", "x\n")
        r.write("data/raw/x.py", "SECRET\n")                                   # ignored by impact.yml

    def tearDown(self):
        self.repo.__exit__(None, None, None)

    def findings(self, data):
        return sorted((f["severity"], f["rule"], f["source"], f["subject"]) for f in data["findings"])

    def test_check_reports_the_expected_findings_and_impact(self):
        code, data, err = as_json(self.repo, "check", "--base", "main")
        self.assertEqual((code, err), (1, ""))
        self.assertEqual(self.findings(data), [
            ("ERROR", "new-interface-without-contract", "api/orders/route.ts", "api/orders/route.ts"),
            ("ERROR", "stale-reference", "docs/refs.md", "lib/util.py"),
            ("WARNING", "content-trigger", "core/base.py", "secret"),
            ("WARNING", "docs-not-updated", "registry/components.yml", "api"),
            ("WARNING", "docs-not-updated", "registry/components.yml", "core"),
            ("WARNING", "docs-not-updated", "registry/components.yml", "lib"),
            ("WARNING", "unregistered-path", "misc/new.txt", "misc/new.txt"),
        ])                                              # app: docs/app.md changed in this change set
        impact = {e["path"]: e for e in data["impact"]}
        self.assertEqual({p: (e["kind"], tuple(e["origins"])) for p, e in impact.items()}, {
            "api/orders/route.ts": ("added", ("staged",)), "app/main.py": ("modified", ("unstaged",)),
            "app/old.py": ("deleted", ("staged",)), "core/base.py": ("modified", ("committed",)),
            "data/raw/x.py": ("added", ("untracked",)), "docs/app.md": ("modified", ("unstaged",)),
            "lib/moved.py": ("renamed", ("committed",)), "misc/new.txt": ("added", ("untracked",))})
        self.assertEqual(impact["lib/moved.py"]["old_path"], "lib/util.py")
        self.assertTrue(impact["data/raw/x.py"]["ignored"])
        self.assertEqual({(d["doc"], d["changed"]) for d in impact["app/main.py"]["docs"]},
                         {("docs/app.md", True), ("docs/ops.md", False)})   # all docs listed, changed flag only
        self.assertEqual([(d["component"], d["basis"]) for d in impact["core/base.py"]["dependents"]],
                         [("lib", "inferred")])

    def test_plan_predicted_every_finding_check_produced(self):
        _, data, _ = as_json(self.repo, "check", "--base", "main")
        predicted = {(p["path"], r["rule"]) for p in self.plan["predictions"] for r in p["rules"]}
        for f in data["findings"]:
            path = {"stale-reference": f["subject"], "docs-not-updated": None}.get(f["rule"], f["source"])
            if path is None:                                                     # per component
                comps = {c for p in self.plan["predictions"] for c in p["components"]
                         if ("docs-not-updated" in [r["rule"] for r in p["rules"]])}
                self.assertIn(f["subject"], comps)
            else:
                self.assertIn((path, f["rule"]), predicted)
        ignored = next(p for p in self.plan["predictions"] if p["path"] == "data/raw/x.py")
        self.assertEqual((ignored["ignored"], ignored["rules"]), (True, []))

    def test_acknowledgements(self):
        _, data, _ = as_json(self.repo, "check", "--base", "main")
        ids = {(f["rule"], f["subject"]): f["id"] for f in data["findings"]}
        acks = self.repo.root.parent / "pr.md"
        acks.write_text("## Documentation impact\n"
                        f"- ack {ids[('docs-not-updated', 'core')]}: reviewed docs/core.md, behaviour unchanged\n"
                        f"- ack {ids[('stale-reference', 'lib/util.py')]}: will fix the reference later\n"
                        f"- ack {ids[('unregistered-path', 'misc/new.txt')]}: ok\n"
                        "- ack docs-not-updated:0000000000: stale acknowledgement from an old run\n", encoding="utf-8")
        code, data, _ = as_json(self.repo, "check", "--base", "main", "--ack-file", str(acks))
        self.assertEqual(code, 1)                                                # the ERRORs still count
        by_id = {f["id"]: f for f in data["findings"]}
        self.assertTrue(by_id[ids[("docs-not-updated", "core")]]["acknowledged"])
        self.assertEqual(by_id[ids[("stale-reference", "lib/util.py")]]["severity"], "ERROR")
        self.assertFalse(by_id[ids[("unregistered-path", "misc/new.txt")]]["acknowledged"])
        self.assertEqual(sorted(f["subject"].split(":")[0] for f in data["findings"] if f["rule"] == "ack-problem"),
                         ["error", "reason", "unknown"])
        self.assertEqual(len(data["findings"]), 7 + 3)                           # nothing removed

    def test_fixing_the_errors_gives_exit_0(self):
        r = self.repo
        r.write("docs/refs.md", "Utilities live in `lib/moved.py`.\n")
        registry = json.loads((r.root / "registry" / "components.yml").read_text(encoding="utf-8"))
        api = next(c for c in registry["components"] if c["id"] == "api")
        api["interfaces"].append({"path": "api/orders/route.ts", "contract": "docs/api.md"})
        r.write_json("registry/components.yml", registry)
        code, data, _ = as_json(r, "check", "--base", "main")
        self.assertEqual(code, 0)
        self.assertEqual([f["rule"] for f in data["findings"] if f["severity"] == "ERROR"], [])
        self.assertIn(("WARNING", "config-changed", "registry/components.yml", "registry/components.yml"),
                      self.findings(data))

    def test_reports_out_determinism_and_read_only(self):
        r = self.repo
        before = full_snapshot(r.root)
        outputs = {fmt: cli(r, "check", "--base", "main", "--format", fmt) for fmt in ("text", "json", "md")}
        for fmt in ("text", "json", "md"):
            self.assertEqual(cli(r, "check", "--base", "main", "--format", fmt), outputs[fmt])
        cli(r, "plan", "--paths", *PROPOSED)
        cli(r, "validate")
        self.assertEqual(full_snapshot(r.root), before)                         # read-only without --out
        self.assertTrue(outputs["md"][1].startswith("## Documentation impact\n"))
        self.assertIn("| core | docs/core.md | no | Documentation review required: unacknowledged", outputs["md"][1])
        self.assertIn("Summary: 2 ERROR, 5 WARNING (0 acknowledged, 5 unacknowledged) | exit code 1",
                      outputs["text"][1])
        code, _, _ = cli(r, "check", "--base", "main", "--out")
        self.assertEqual(code, 1)
        folder = r.root / ".local" / "impact"
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["check.json", "check.md", "check.txt"])
        self.assertEqual((folder / "check.md").read_bytes().decode("utf-8"), outputs["md"][1])
        self.assertEqual(cli(r, "check", "--base", "main")[1], outputs["text"][1])  # .local/ is ignored: no new change


if __name__ == "__main__":
    unittest.main()
