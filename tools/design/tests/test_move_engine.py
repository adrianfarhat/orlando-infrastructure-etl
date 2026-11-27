"""T-97 PR B2b-2a S1: the transaction engine's version 2 records (registry moves).

The planner and the commands (`registry move`, `registry adopt-moves`) are stage S2; here the
engine is driven directly with a validated batch. Crash injection runs the engine in its own
process and ends it at every meaningful boundary; afterwards each source must be at exactly one of
its old, new or intermediate paths with its exact bytes, the registry must be its original or its
replacement, and Complete and Undo must each reach one consistent state, repeatably. Version 1
records written by the merged B2b-1 code (main 3524db7) must stay readable and recoverable."""

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path

from tools.design import designer_api, ownership, registry, transactions
from tools.design.tests.test_design import REPO_ROOT, Workspace, cmd
from tools.design.tests.test_transactions import (build, listing, only_record, rb_args, request, run, snapshot,
                                                  unlock)
from tools.design.workspace import DesignError, new_feature

PY = sys.executable
MERGED_B2B1 = "3524db7732d357c46818c7f518335ba920454288"
sha = transactions._sha

DRIVER = r"""
import json, sys
from pathlib import Path
from tools.design import registry, transactions
root = Path(sys.argv[1]); plan = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
with registry.lock(root):
    rec = transactions.prepare_move(root, plan["mode"], plan["renames"], Path(plan["before"]).read_bytes(),
                                    Path(plan["after"]).read_bytes())
    try:
        print(json.dumps(transactions.commit_move(root, rec)))
    except transactions.DesignError as exc:
        print("REFUSED", exc); sys.exit(3)
"""


def setup_sources(ws, n=2):
    """One feature with n registered mermaid-md sources."""
    new_feature(ws.root, "Feature A")
    return [ownership.new_diagram(ws.root, "FD-0001", f"Flow {i + 1}") for i in range(n)]


def plan_for(ws, made, mode="move", case_only=(), dest="designs/features/moved/diagrams"):
    """The batch S2's planner will produce: every source to `dest` (or, for the indexes in
    case_only, the same folder with a capitalised name through a hidden intermediate path), and the
    registry with exactly those `path` fields changed."""
    before = (ws.root / registry.REGISTRY).read_bytes()
    text = before.decode("utf-8")
    renames = []
    for i, m in enumerate(made):
        folder, name = m.path.rsplit("/", 1)
        if i in case_only:
            to, via = f"{folder}/{name[0].upper()}{name[1:]}", f"{folder}/.fd-move-{i}.md"
        else:
            to, via = f"{dest}/{name}", None
        old_line = f"path: {m.path}\n"
        assert text.count(old_line) == 1
        text = text.replace(old_line, f"path: {to}\n")
        renames.append({"diagram_id": m.diagram_id, "from": m.path, "to": to, "via": via,
                        "sha": sha((ws.root / m.path).read_bytes())})
    return {"mode": mode, "renames": renames, "before": before, "after": text.encode("utf-8")}


def write_plan(ws, plan):
    d = Path(tempfile.mkdtemp(prefix="move-plan-"))
    (d / "before").write_bytes(plan["before"])
    (d / "after").write_bytes(plan["after"])
    p = d / "plan.json"
    p.write_text(json.dumps({"mode": plan["mode"], "renames": plan["renames"], "before": str(d / "before"),
                             "after": str(d / "after")}), encoding="utf-8")
    return p


def drive(ws, plan, fault=None):
    """The engine in its own process (fault: a DESIGN_TEST_FAULT point)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("DESIGN_TEST_FAULT")}
    if fault:
        env.update(DESIGN_TEST_FAULT=fault, DESIGN_TEST_FAULT_ROOT=str(ws.root.resolve()))
    return subprocess.run([PY, "-B", "-c", DRIVER, str(ws.root), str(write_plan(ws, plan))], cwd=REPO_ROOT, env=env,
                          capture_output=True, timeout=120)


def commit_in_process(ws, plan):
    with registry.lock(ws.root):
        rec = transactions.prepare_move(ws.root, plan["mode"], plan["renames"], plan["before"], plan["after"])
        return transactions.commit_move(ws.root, rec)


def where(ws, plan):
    """For each rename: old, new or temp when the exact bytes are at exactly that path."""
    return [transactions.rename_state(ws.root, dict(r, observed=plan["mode"] == "adopt")) for r in plan["renames"]]


def reg_state(ws, plan):
    h = sha((ws.root / registry.REGISTRY).read_bytes())
    return "original" if h == sha(plan["before"]) else "replacement" if h == sha(plan["after"]) else "changed"


def resolve(ws, action):
    unlock(ws)
    rec = only_record(ws)
    return transactions.resolve(ws.root, rec["id"], action, rec["token"])


def rewrite_journal(folder, change):
    j = folder / "journal.json"
    data = json.loads(j.read_text(encoding="utf-8"))
    change(data)
    data.pop("checksum", None)
    data["checksum"] = sha(transactions._canonical(data))
    j.write_text(json.dumps(data, sort_keys=True, indent=1), encoding="ascii")


def _upper_name(rel):
    """The same path with the file name (not the .md extension) in capitals: equal ignoring case."""
    folder, name = rel.rsplit("/", 1)
    return f"{folder}/{name[:-3].upper()}.md"


def prepared_record(ws, plan):
    """A valid, prepared (untouched) version 2 record, as after a crash right after preparation."""
    r = drive(ws, plan, fault="move-after-prepare")
    assert r.returncode == 97, r.stderr
    unlock(ws)
    return Path(transactions._tx_root(ws.root, False)) / only_record(ws)["id"]


class Commit(unittest.TestCase):
    def test_a_move_renames_every_source_then_replaces_the_registry_and_removes_the_record(self):
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            plan = plan_for(ws, made)
            contents = [(ws.root / m.path).read_bytes() for m in made]
            r = commit_in_process(ws, plan)
            self.assertTrue(r["ok"])
            self.assertEqual(where(ws, plan), ["new", "new"])
            self.assertEqual([(ws.root / x["to"]).read_bytes() for x in plan["renames"]], contents)   # bytes kept
            self.assertEqual(reg_state(ws, plan), "replacement")
            self.assertEqual(transactions.status(ws.root), [])
            e = registry.load(ws.root).by_id()[made[0].diagram_id]
            self.assertEqual((e.diagram_id, e.owner_kind, e.owner_ref, e.title, e.category, tuple(e.aliases)),
                             (made[0].diagram_id, "feature", "FD-0001", "Flow 1", "other", ()))   # only the path changed
            code, out, err = cmd(ws.root, "index", "--check")
            self.assertEqual(code, 0, out + err)                                   # G4: the index was regenerated

    def test_a_case_only_rename_goes_through_its_recorded_intermediate_path(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            plan = plan_for(ws, made, case_only=(0,))
            self.assertTrue(commit_in_process(ws, plan)["ok"])
            folder, name = plan["renames"][0]["to"].rsplit("/", 1)
            self.assertIn(name, os.listdir(ws.root / folder))                     # exactly the new case
            self.assertNotIn(plan["renames"][0]["from"].rsplit("/", 1)[1], os.listdir(ws.root / folder))
            self.assertFalse((ws.root / plan["renames"][0]["via"]).exists())
            self.assertEqual(reg_state(ws, plan), "replacement")

    def test_an_observed_rename_only_changes_the_registry(self):
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            plan = plan_for(ws, made, mode="adopt")
            for x in plan["renames"]:                                              # another program moved them
                (ws.root / x["to"]).parent.mkdir(parents=True, exist_ok=True)
                os.rename(ws.root / x["from"], ws.root / x["to"])
            self.assertTrue(commit_in_process(ws, plan)["ok"])
            self.assertEqual(reg_state(ws, plan), "replacement")
            self.assertEqual(transactions.status(ws.root), [])

    def test_an_observed_rename_whose_file_is_not_where_it_was_found_is_refused_and_changes_nothing(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            plan = plan_for(ws, made, mode="adopt")                                # not actually moved
            with self.assertRaises(DesignError) as c:
                commit_in_process(ws, plan)
            self.assertIn("changed nothing", str(c.exception))
            self.assertEqual(reg_state(ws, plan), "original")
            self.assertEqual(transactions.status(ws.root), [])

    def test_an_occupied_destination_is_never_overwritten_and_the_done_renames_are_put_back(self):
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            plan = plan_for(ws, made)
            occupied = ws.root / plan["renames"][1]["to"]
            occupied.parent.mkdir(parents=True, exist_ok=True)
            occupied.write_bytes(b"an unrelated file\n")
            with self.assertRaises(DesignError) as c:
                commit_in_process(ws, plan)
            self.assertIn("changed nothing", str(c.exception))
            self.assertEqual(occupied.read_bytes(), b"an unrelated file\n")
            self.assertEqual([transactions._entry_sha(ws.root, x["from"]) for x in plan["renames"]],
                             [x["sha"] for x in plan["renames"]])
            self.assertEqual(reg_state(ws, plan), "original")
            self.assertEqual(transactions.status(ws.root), [])

    def test_a_registry_change_after_preparation_is_never_overwritten(self):
        # concurrent registry modification (by a program that does not take the lock)
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            plan = plan_for(ws, made)
            with registry.lock(ws.root):
                rec = transactions.prepare_move(ws.root, "move", plan["renames"], plan["before"], plan["after"])
                foreign = plan["before"] + b"# edited by another program\n"
                (ws.root / registry.REGISTRY).write_bytes(foreign)
                with self.assertRaises(DesignError) as c:
                    transactions.commit_move(ws.root, rec)
            self.assertIn("registry changed while the move ran", str(c.exception))
            self.assertEqual((ws.root / registry.REGISTRY).read_bytes(), foreign)
            self.assertEqual(where(ws, plan), ["old", "old"])
            self.assertEqual(transactions.status(ws.root), [])

    def test_a_link_on_the_way_is_refused(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            outside = Path(tempfile.mkdtemp(prefix="outside-"))
            target = ws.root / "designs/features/linked"
            if sys.platform == "win32":
                subprocess.run(["cmd", "/c", "mklink", "/J", str(target), str(outside)], capture_output=True, check=True)
            else:
                os.symlink(outside, target)
            plan = plan_for(ws, made, dest="designs/features/linked/diagrams")
            with self.assertRaises(DesignError):
                commit_in_process(ws, plan)
            self.assertEqual(os.listdir(outside), [])
            self.assertEqual(where(ws, plan), ["old"])

    def test_the_write_set_is_narrow(self):
        for bad in ("docs/architecture/diagrams/x.md", "designs/features/x.md", "designs/diagrams/registry.yml",
                    "designs/features/diagrams/x.drawio.svg", "designs/features/a/../diagrams/x.md", "tools/x.md"):
            with self.subTest(path=bad), self.assertRaises(DesignError):
                transactions._move_rel(bad)
        self.assertEqual(transactions._move_rel("designs/features/p/diagrams/x.md"), "designs/features/p/diagrams/x.md")


class Records(unittest.TestCase):
    """Version 2 validation; unknown versions and malformed records fail safely (A1)."""

    DEFECTS = {
        "unknown version 3": lambda d: d.update(version=3),
        "version as a string": lambda d: d.update(version="2"),
        "another tool": lambda d: d.update(tool="refresh-blocks"),
        "unknown mode": lambda d: d.update(mode="teleport"),
        "unknown operation": lambda d: d["ops"][0].update(kind="delete"),
        "registry not last": lambda d: d["ops"].reverse(),
        "a path under docs/architecture": lambda d: d["ops"][0].update(to="docs/architecture/diagrams/x.md"),
        "a path outside diagrams/": lambda d: d["ops"][0].update(to="designs/features/x.md"),
        "intermediate in another folder": lambda d: d["ops"][0].update(via="designs/features/other/diagrams/.t.md"),
        "duplicate destination ignoring case": lambda d: d["ops"][1].update(to=_upper_name(d["ops"][0]["to"])),
        "case-only without an intermediate": lambda d: d["ops"][0].update(to=_upper_name(d["ops"][0]["from"]), via=None),
        "observed in a move": lambda d: d["ops"][0].update(observed=True),
        "an extra field": lambda d: d["ops"][0].update(extra=1),
        "a malformed diagram ID": lambda d: d["ops"][0].update(diagram_id="../x"),
        "another registry file": lambda d: d["ops"][-1].update(path="designs/diagrams/other.yml"),
        "registry before equals after": lambda d: d["ops"][-1].update(after_sha=d["ops"][-1]["before_sha"]),
        "a malformed history": lambda d: d.update(history="x"),
    }

    def test_every_defect_makes_the_record_unusable_only_abandonable_and_blocking(self):
        for name, change in self.DEFECTS.items():
            with self.subTest(defect=name), Workspace() as ws:
                made = setup_sources(ws, 2)
                folder = prepared_record(ws, plan_for(ws, made))
                rewrite_journal(folder, change)
                rec = only_record(ws)
                self.assertFalse(rec["valid"], name)
                self.assertFalse(rec["complete"]["possible"] or rec["undo"]["possible"])
                with self.assertRaises(DesignError):
                    transactions.registry_guard(ws.root)                     # every registry writer
                with self.assertRaises(DesignError):
                    transactions.guard(ws.root)                              # every document writer
                for action in ("complete", "undo"):
                    with self.assertRaises(DesignError):
                        transactions.resolve(ws.root, rec["id"], action, rec["token"])
                self.assertTrue(transactions.resolve(ws.root, rec["id"], "abandon", rec["token"])["ok"])
                transactions.registry_guard(ws.root)                         # released

    def test_a_tampered_registry_copy_or_an_extra_file_is_detected(self):
        for what in ("registry.new", "extra"):
            with self.subTest(what=what), Workspace() as ws:
                made = setup_sources(ws, 1)
                folder = prepared_record(ws, plan_for(ws, made))
                if what == "extra":
                    (folder / "notes.txt").write_text("x", encoding="utf-8")
                else:
                    (folder / what).write_bytes(b"tampered")
                self.assertFalse(only_record(ws)["valid"])

    def test_version_1_and_version_2_records_are_listed_and_resolved_independently(self):
        with Workspace() as ws:
            docs, _ = build(ws, 3)
            reqs, token = listing(ws)
            self.assertEqual(run(ws, rb_args(reqs, token), fault="after-replace:1").returncode, 97)   # a version 1 record
            unlock(ws)
            v1 = only_record(ws)
            self.assertNotIn("tool", v1)                                      # the version 1 description, unchanged
            self.assertTrue(transactions.resolve(ws.root, v1["id"], "undo", v1["token"])["ok"])
            made = ownership.new_diagram(ws.root, "FD-0001", "Second flow")
            plan = plan_for(ws, [made])
            self.assertEqual(drive(ws, plan, fault="move-after-rename:1").returncode, 97)        # a version 2 record
            self.assertEqual(run(ws, rb_args(*listing(ws)), fault="after-replace:1").returncode, 2)  # refused: held
            unlock(ws)
            v2 = only_record(ws)
            self.assertEqual(v2["tool"], "registry-move")
            self.assertTrue(transactions.resolve(ws.root, v2["id"], "complete", v2["token"])["ok"])
            self.assertEqual(reg_state(ws, plan), "replacement")


class MergedVersion1(unittest.TestCase):
    """A version 1 record written by the merged B2b-1 code stays readable and recoverable."""

    def merged_package(self):
        tar = subprocess.run(["git", "-C", str(REPO_ROOT), "archive", "--format=tar", MERGED_B2B1, "tools/design"],
                             capture_output=True, check=True, timeout=60).stdout
        d = Path(tempfile.mkdtemp(prefix="b2b1-merged-"))
        with tarfile.open(fileobj=io.BytesIO(tar)) as t:
            t.extractall(d, filter="data")
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def test_a_record_written_by_main_3524db7_completes_and_undoes_with_this_code(self):
        old = self.merged_package()
        for action in ("complete", "undo"):
            with self.subTest(action=action), Workspace() as ws:
                docs, _ = build(ws, 3)
                before = snapshot(ws, docs)
                reqs, token = listing(ws)
                env = {k: v for k, v in os.environ.items() if not k.startswith("DESIGN_TEST_FAULT")}
                env.update(DESIGN_TEST_FAULT="after-replace:2", DESIGN_TEST_FAULT_ROOT=str(ws.root.resolve()))
                r = subprocess.run([PY, "-B", "-m", "tools.design", *rb_args(reqs, token), "--root", str(ws.root)],
                                   cwd=old, env=env, capture_output=True, timeout=120)
                self.assertEqual(r.returncode, 97, r.stderr)                  # the merged code, interrupted
                unlock(ws)
                rec = only_record(ws)                                         # read by this code
                self.assertTrue(rec["valid"], rec.get("problem"))
                self.assertEqual([f["state"] for f in rec["files"]], ["updated", "updated", "original"])
                out = transactions.resolve(ws.root, rec["id"], action, rec["token"])
                self.assertTrue(out["ok"], out)
                if action == "undo":
                    self.assertEqual(snapshot(ws, docs), before)
                else:
                    self.assertTrue(all(f["state"] == "updated" for f in out["files"]))
                again = transactions.resolve(ws.root, rec["id"], action, rec["token"])
                self.assertTrue(again.get("already"))


POINTS_NOTHING = ["move-after-orig", "move-after-new", "move-before-journal", "move-after-journal"]
POINTS_COMMIT = ["move-after-prepare", "move-after-committing-mark", "move-before-rename:1", "move-temp:1",
                 "move-after-rename:1", "move-before-rename:2", "move-after-rename:2", "move-before-registry",
                 "move-after-registry", "move-before-committed-mark"]
POINTS_DONE = ["move-after-committed-mark", "after-done-rename", "during-cleanup:1", "during-cleanup:3"]


class CrashInjection(unittest.TestCase):
    """A batch of two renames: the first case-only (through its intermediate path), the second to
    a new folder. The process ends at every boundary."""

    def batch(self, ws):
        made = setup_sources(ws, 2)
        return plan_for(ws, made, case_only=(0,))

    def assert_consistent(self, ws, plan):
        states, reg = where(ws, plan), reg_state(ws, plan)
        self.assertTrue(all(s in ("old", "new", "temp") for s in states), states)   # never lost, never duplicated
        self.assertIn(reg, ("original", "replacement"))
        if reg == "replacement":
            self.assertEqual(states, ["new", "new"])                                 # the registry never names a missing file
        return states, reg

    def test_before_the_record_exists_nothing_is_touched(self):
        for point in POINTS_NOTHING:
            with self.subTest(point=point), Workspace() as ws:
                plan = self.batch(ws)
                self.assertEqual(drive(ws, plan, fault=point).returncode, 97)
                self.assertEqual((where(ws, plan), reg_state(ws, plan)), (["old", "old"], "original"))
                unlock(ws)
                self.assertEqual(transactions.status(ws.root), [])             # .preparing is debris
                code, out, err = cmd(ws.root, "registry", "relink", plan["renames"][1]["diagram_id"], "--title", "T")
                self.assertEqual(code, 0, out + err)                          # nothing holds the registry

    def test_during_the_move_then_complete_then_complete_again(self):
        for point in POINTS_COMMIT:
            with self.subTest(point=point), Workspace() as ws:
                plan = self.batch(ws)
                self.assertEqual(drive(ws, plan, fault=point).returncode, 97)
                self.assert_consistent(ws, plan)
                with self.assertRaises(DesignError):                         # Q1: held meanwhile
                    transactions.registry_guard(ws.root)
                out = resolve(ws, "complete")
                self.assertTrue(out["ok"], out)
                self.assertEqual((where(ws, plan), reg_state(ws, plan)), (["new", "new"], "replacement"))
                self.assertEqual(transactions.status(ws.root), [])
                transactions.registry_guard(ws.root)                         # released
                code, out2, err = cmd(ws.root, "index", "--check")
                self.assertEqual(code, 0, out2 + err)

    def test_during_the_move_then_undo(self):
        for point in POINTS_COMMIT:
            with self.subTest(point=point), Workspace() as ws:
                plan = self.batch(ws)
                self.assertEqual(drive(ws, plan, fault=point).returncode, 97)
                out = resolve(ws, "undo")
                self.assertTrue(out["ok"], out)
                self.assertEqual((where(ws, plan), reg_state(ws, plan)), (["old", "old"], "original"))
                self.assertEqual((ws.root / registry.REGISTRY).read_bytes(), plan["before"])

    def test_after_the_move_was_verified_it_counts_as_done(self):
        for point in POINTS_DONE:
            with self.subTest(point=point), Workspace() as ws:
                plan = self.batch(ws)
                self.assertEqual(drive(ws, plan, fault=point).returncode, 97)
                self.assertEqual((where(ws, plan), reg_state(ws, plan)), (["new", "new"], "replacement"))
                unlock(ws)
                self.assertEqual(transactions.status(ws.root), [])
                with registry.lock(ws.root):
                    transactions._remove_debris(ws.root)                     # the next writer cleans up
                code, out, err = cmd(ws.root, "index", "--check")
                self.assertEqual(code, 0, out + err)

    def test_termination_from_outside(self):
        with Workspace() as ws:
            plan = self.batch(ws)
            env = {k: v for k, v in os.environ.items() if not k.startswith("DESIGN_TEST_FAULT")}
            env.update(DESIGN_TEST_FAULT="move-after-rename:1", DESIGN_TEST_FAULT_ROOT=str(ws.root.resolve()),
                       DESIGN_TEST_FAULT_MODE="sleep")
            proc = subprocess.Popen([PY, "-B", "-c", DRIVER, str(ws.root), str(write_plan(ws, plan))], cwd=REPO_ROOT,
                                    env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                for _ in range(600):
                    line = proc.stderr.readline().decode()
                    if line.startswith("FAULT"):
                        break
            finally:
                from tools.design.tests.test_transactions import stop
                stop(proc, ws)
            self.assert_consistent(ws, plan)
            self.assertTrue(resolve(ws, "undo")["ok"])
            self.assertEqual((where(ws, plan), reg_state(ws, plan)), (["old", "old"], "original"))


class InterruptedRecovery(unittest.TestCase):
    RECOVERY = r"""
import sys
from pathlib import Path
from tools.design import transactions
root = Path(sys.argv[1])
rec = transactions.status(root)[0]
print(transactions.resolve(root, rec["id"], sys.argv[2], rec["token"]))
"""

    def recover(self, ws, action, fault):
        env = {k: v for k, v in os.environ.items() if not k.startswith("DESIGN_TEST_FAULT")}
        env.update(DESIGN_TEST_FAULT=fault, DESIGN_TEST_FAULT_ROOT=str(ws.root.resolve()))
        unlock(ws)
        return subprocess.run([PY, "-B", "-c", self.RECOVERY, str(ws.root), action], cwd=REPO_ROOT, env=env,
                              capture_output=True, timeout=120)

    def test_complete_interrupted_at_every_point_then_repeated(self):
        for point in ("move-complete-after-mark", "move-complete-temp:1", "move-complete-after:1",
                      "move-complete-after:2", "move-complete-after-registry", "after-done-rename"):
            with self.subTest(point=point), Workspace() as ws:
                plan = CrashInjection().batch(ws)
                self.assertEqual(drive(ws, plan, fault="move-after-committing-mark").returncode, 97)
                self.assertEqual(self.recover(ws, "complete", point).returncode, 97)
                CrashInjection.assert_consistent(self, ws, plan)
                if transactions.status(ws.root):
                    self.assertTrue(resolve(ws, "complete")["ok"])
                self.assertEqual((where(ws, plan), reg_state(ws, plan)), (["new", "new"], "replacement"))

    def test_undo_interrupted_at_every_point_then_repeated(self):
        for point in ("move-undo-after-mark", "move-undo-after-registry", "move-undo-temp:1", "move-undo-after:2",
                      "move-undo-after:1"):
            with self.subTest(point=point), Workspace() as ws:
                plan = CrashInjection().batch(ws)
                self.assertEqual(drive(ws, plan, fault="move-after-registry").returncode, 97)   # fully moved, not finished
                self.assertEqual(self.recover(ws, "undo", point).returncode, 97)
                states = where(ws, plan)
                self.assertTrue(all(s in ("old", "new", "temp") for s in states), states)
                self.assertIn(reg_state(ws, plan), ("original", "replacement"))
                self.assertTrue(resolve(ws, "undo")["ok"])
                self.assertEqual((where(ws, plan), reg_state(ws, plan)), (["old", "old"], "original"))

    def test_undo_after_a_partial_complete_and_complete_after_a_partial_undo(self):
        with Workspace() as ws:
            plan = CrashInjection().batch(ws)
            self.assertEqual(drive(ws, plan, fault="move-after-committing-mark").returncode, 97)
            self.assertEqual(self.recover(ws, "complete", "move-complete-after:1").returncode, 97)
            self.assertTrue(resolve(ws, "undo")["ok"])
            self.assertEqual((where(ws, plan), reg_state(ws, plan)), (["old", "old"], "original"))


class RecoveryStates(unittest.TestCase):
    """both, neither, changed and a foreign registry change are never overwritten or deleted."""

    def interrupted(self, ws, point="move-after-rename:1"):
        made = setup_sources(ws, 2)
        plan = plan_for(ws, made)
        self.assertEqual(drive(ws, plan, fault=point).returncode, 97)
        unlock(ws)
        return plan

    def test_a_source_at_both_paths_neither_path_or_changed_is_left_alone(self):
        for case in ("both", "neither", "changed"):
            with self.subTest(case=case), Workspace() as ws:
                plan = self.interrupted(ws)
                first = plan["renames"][0]                                    # moved to its new path
                data = (ws.root / first["to"]).read_bytes()
                if case == "both":
                    (ws.root / first["from"]).write_bytes(data)
                elif case == "neither":
                    (ws.root / first["to"]).unlink()
                else:
                    (ws.root / first["to"]).write_bytes(data + b"\nedited\n")
                snap = {p: (ws.root / p).read_bytes() for p in (first["from"], first["to"]) if (ws.root / p).exists()}
                rec = only_record(ws)
                self.assertEqual(rec["files"][0]["state"], case)
                self.assertIn(rec["files"][0]["path"], rec["complete"]["left_alone"])
                out = transactions.resolve(ws.root, rec["id"], "complete", rec["token"])
                self.assertFalse(out["ok"])
                self.assertEqual(reg_state(ws, plan), "original")            # never names a missing or changed file
                self.assertEqual({p: (ws.root / p).read_bytes() for p in snap}, snap)
                rec = only_record(ws)                                         # kept
                out = transactions.resolve(ws.root, rec["id"], "undo", rec["token"])
                self.assertFalse(out["ok"])
                self.assertEqual({p: (ws.root / p).read_bytes() for p in snap}, snap)
                self.assertEqual(where(ws, plan)[1], "old")                   # the other one was put back
                self.assertEqual(len(transactions.status(ws.root)), 1)

    def test_a_registry_changed_by_another_program_is_never_overwritten(self):
        with Workspace() as ws:
            plan = self.interrupted(ws)
            foreign = plan["before"] + b"# another program\n"
            (ws.root / registry.REGISTRY).write_bytes(foreign)
            rec = only_record(ws)
            self.assertEqual(rec["registry"], "changed")
            self.assertFalse(rec["complete"]["possible"])
            with self.assertRaises(DesignError):
                transactions.resolve(ws.root, rec["id"], "complete", rec["token"])
            out = transactions.resolve(ws.root, rec["id"], "undo", rec["token"])
            self.assertFalse(out["ok"])                                       # files put back, registry left alone
            self.assertEqual((ws.root / registry.REGISTRY).read_bytes(), foreign)
            self.assertEqual(where(ws, plan), ["old", "old"])

    def test_undo_never_overwrites_an_occupied_old_path(self):
        with Workspace() as ws:
            plan = self.interrupted(ws)
            first = plan["renames"][0]
            (ws.root / first["from"]).write_bytes(b"a new, unrelated file\n")
            rec = only_record(ws)
            self.assertEqual(rec["files"][0]["state"], "new")                 # the source itself is at its new path
            self.assertEqual(rec["files"][0]["occupied"], [first["from"]])     # and something unrelated is in the way
            out = transactions.resolve(ws.root, rec["id"], "undo", rec["token"])
            self.assertFalse(out["ok"])                                       # partly done, record kept
            self.assertEqual((ws.root / first["from"]).read_bytes(), b"a new, unrelated file\n")
            self.assertEqual(transactions._entry_sha(ws.root, first["to"]), first["sha"])
            self.assertEqual(len(transactions.status(ws.root)), 1)


class RegistryHold(unittest.TestCase):
    """Q1: while a move is unresolved every registry writer and every refresh of generated text is
    refused; read-only diagnostics and the recovery of that move stay available (no deadlock)."""

    def test_writers_are_refused_diagnostics_and_recovery_are_not(self):
        with Workspace() as ws:
            docs, src = build(ws, 2)                                          # documents with out-of-date blocks
            made = ownership.new_diagram(ws.root, "FD-0002", "Moving flow")
            plan = plan_for(ws, [made])
            self.assertEqual(drive(ws, plan, fault="move-after-rename:1").returncode, 97)
            unlock(ws)
            first_doc = snapshot(ws, docs)
            held_source = plan["renames"][0]["to"]
            source_before = (ws.root / held_source).read_bytes()
            refused = {
                "relink --title (rewrites the source)": lambda: registry.relink(ws.root, made.diagram_id, title="New title"),
                "relink --path": lambda: registry.relink(ws.root, made.diagram_id, path=held_source),
                "retire": lambda: registry.retire(ws.root, made.diagram_id, True),
                "new diagram": lambda: ownership.new_diagram(ws.root, "FD-0001", "Another"),
                "refresh-blocks": lambda: transactions.update(ws.root, [(d, transactions._sha((ws.root / d).read_bytes()))
                                                                        for d in docs]),
            }
            for name, call in refused.items():
                with self.subTest(writer=name):
                    with self.assertRaises(DesignError) as c:
                        call()
                    self.assertIn("registry move is unresolved", str(c.exception))
            self.assertEqual((ws.root / held_source).read_bytes(), source_before)   # the held source was not rewritten
            for argv in (["index"], ["registry", "adopt", "designs/features/diagrams/none.md", "--category", "other"],
                         ["new", "feature", "--name", "Blocked"]):
                with self.subTest(command=argv):
                    code, out, err = cmd(ws.root, *argv)
                    self.assertNotEqual(code, 0)
                    self.assertIn("unresolved", out + err)
            text = ws.text(docs[0])
            for op, fields in (("refresh", {}), ("insert", {"at": 1, "diagram_id": made.diagram_id})):
                with self.subTest(designer_op=op):                          # B2a's refresh and the editor's insert
                    r, code = request(ws, op=op, path=docs[0], text=text, **fields)
                    self.assertNotEqual(code, 0)
                    self.assertIn("registry move is unresolved", json.dumps(r))
            r, code = request(ws, op="blocks", path=docs[0], text=text)        # read only: still answers
            self.assertEqual(code, 0, r)
            a = transactions.affected(ws.root)                               # nothing offered for refresh
            self.assertTrue(a["documents"] and all("registry move is unresolved" in d["excluded"] for d in a["documents"]))
            self.assertEqual(snapshot(ws, docs), first_doc)
            # read only: check reports E16, status lists it, the designer library still answers
            code, out, err = cmd(ws.root, "check")
            self.assertIn("a registry move was interrupted", out + err)
            code, out, _ = cmd(ws.root, "transaction", "status")
            self.assertIn("tool-initiated move", out)
            r, code = request(ws, op="library")
            self.assertEqual(code, 0, r)
            # recovery releases its own hold
            rec = only_record(ws)
            self.assertTrue(transactions.resolve(ws.root, rec["id"], "complete", rec["token"])["ok"])
            registry.relink(ws.root, made.diagram_id, title="New title")       # writers work again
            self.assertEqual(registry.load(ws.root).by_id()[made.diagram_id].path, held_source)

    def test_recovery_is_refused_while_a_source_is_open_in_a_window_even_a_silent_one(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            plan = plan_for(ws, made)
            self.assertEqual(drive(ws, plan, fault="move-after-rename:1").returncode, 97)
            unlock(ws)
            folder = ws.root / transactions.WINDOWS
            folder.mkdir(parents=True, exist_ok=True)
            old = time.time() - 3600                                          # suspended for an hour
            (folder / "0123456789abcdef.json").write_text(json.dumps(
                {"format": "feature-designer-window", "version": 1, "window": "0123456789abcdef", "pid": 4242,
                 "host": __import__("platform").node(), "heartbeat": old,
                 "documents": [{"path": plan["renames"][0]["to"], "dirty": True}]}), encoding="utf-8")
            os.utime(folder / "0123456789abcdef.json", (old, old))
            rec = only_record(ws)
            self.assertFalse(rec["complete"]["possible"] or rec["undo"]["possible"])
            self.assertIn("close", rec["undo"]["reason"])
            for action in ("complete", "undo"):
                with self.assertRaises(DesignError):
                    transactions.resolve(ws.root, rec["id"], action, rec["token"])
            transactions.forget_window(ws.root, "0123456789abcdef", True)
            rec = only_record(ws)
            self.assertTrue(transactions.resolve(ws.root, rec["id"], "undo", rec["token"])["ok"])



class QAFollowUps(unittest.TestCase):
    """Cases added after the independent QA review of S1 (findings M1, M2, m1-m5 and its list of
    missing tests)."""

    def test_a_second_move_is_never_prepared_beside_an_unresolved_one(self):        # M1
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            prepared_record(ws, plan_for(ws, made[:1]))
            second = plan_for(ws, made[1:])
            with registry.lock(ws.root), self.assertRaises(DesignError) as c:
                transactions.prepare_move(ws.root, "move", second["renames"], second["before"], second["after"])
            self.assertIn("registry move is unresolved", str(c.exception))
            self.assertEqual(len(transactions.status(ws.root)), 1)

    def test_one_file_at_two_paths_is_an_interrupted_rename_and_is_resolved(self):  # M2 (simulated with a hard link)
        for action in ("complete", "undo"):
            with self.subTest(action=action), Workspace() as ws:
                made = setup_sources(ws, 1)
                plan = plan_for(ws, made)
                self.assertEqual(drive(ws, plan, fault="move-after-rename:1").returncode, 97)
                op = plan["renames"][0]
                os.link(ws.root / op["to"], ws.root / op["from"])            # as if unlink never ran after link
                unlock(ws)
                rec = only_record(ws)
                self.assertEqual(rec["files"][0]["state"], "both")
                self.assertNotIn(rec["files"][0]["path"], rec[action]["left_alone"])
                out = transactions.resolve(ws.root, rec["id"], action, rec["token"])
                self.assertTrue(out["ok"], out)
                goal = "new" if action == "complete" else "old"
                self.assertEqual(where(ws, plan), [goal])
                self.assertEqual(transactions._entry_sha(ws.root, op["to" if goal == "new" else "from"]), op["sha"])

    def test_real_copies_at_two_paths_are_never_removed(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            plan = plan_for(ws, made)
            self.assertEqual(drive(ws, plan, fault="move-after-rename:1").returncode, 97)
            op = plan["renames"][0]
            shutil.copyfile(ws.root / op["to"], ws.root / op["from"])        # a separate copy, same bytes
            unlock(ws)
            rec = only_record(ws)
            self.assertIn(rec["files"][0]["path"], rec["complete"]["left_alone"])
            self.assertNotIn(registry.REGISTRY, rec["complete"]["writes"])   # m1: no registry write promised
            out = transactions.resolve(ws.root, rec["id"], "complete", rec["token"])
            self.assertFalse(out["ok"])
            self.assertTrue((ws.root / op["from"]).exists() and (ws.root / op["to"]).exists())

    def test_the_description_never_promises_a_registry_write_that_cannot_happen(self):   # m1
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            plan = plan_for(ws, made)
            self.assertEqual(drive(ws, plan, fault="move-after-rename:1").returncode, 97)
            blocker = ws.root / plan["renames"][1]["to"]
            blocker.write_bytes(b"in the way\n")                            # the second rename's destination
            unlock(ws)
            rec = only_record(ws)
            self.assertEqual(rec["files"][1]["state"], "old")
            self.assertIn(rec["files"][1]["path"], rec["complete"]["left_alone"])
            self.assertNotIn(registry.REGISTRY, rec["complete"]["writes"])
            out = transactions.resolve(ws.root, rec["id"], "complete", rec["token"])
            self.assertFalse(out["ok"])
            self.assertEqual(blocker.read_bytes(), b"in the way\n")
            self.assertEqual(reg_state(ws, plan), "original")

    def test_an_operating_system_error_during_recovery_is_a_result_and_can_be_repeated(self):   # m2
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            plan = plan_for(ws, made)
            self.assertEqual(drive(ws, plan, fault="move-after-committing-mark").returncode, 97)
            unlock(ws)
            rec = only_record(ws)
            real, calls = os.rename, []

            def locked(src, dst, *a, **k):
                calls.append(1)
                if len(calls) == 2:
                    raise PermissionError(13, "locked by another program", str(src))
                return real(src, dst, *a, **k)
            transactions.os.rename = locked
            try:
                out = transactions.resolve(ws.root, rec["id"], "complete", rec["token"])
            finally:
                transactions.os.rename = real
            self.assertFalse(out["ok"])
            self.assertIn("PermissionError", out["message"])
            self.assertTrue(resolve(ws, "complete")["ok"])                   # repeated: finishes
            self.assertEqual((where(ws, plan), reg_state(ws, plan)), (["new", "new"], "replacement"))

    def test_an_operating_system_error_during_the_move_rolls_back(self):
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            plan = plan_for(ws, made)
            real, calls = os.rename, []

            def locked(src, dst, *a, **k):
                calls.append(1)
                if len(calls) == 2:
                    raise PermissionError(13, "locked by another program", str(src))
                return real(src, dst, *a, **k)
            transactions.os.rename = locked
            try:
                with self.assertRaises(DesignError) as c:
                    commit_in_process(ws, plan)
            finally:
                transactions.os.rename = real
            self.assertIn("changed nothing", str(c.exception))
            self.assertEqual((where(ws, plan), reg_state(ws, plan)), (["old", "old"], "original"))

    def test_a_crash_during_the_rollback_is_recoverable(self):
        for point in ("move-rollback-after:2", "move-rollback-after:1", "move-rollback-temp:1"):
            with self.subTest(point=point), Workspace() as ws:
                made = setup_sources(ws, 2)
                plan = plan_for(ws, made, case_only=(0,))
                occupied = ws.root / plan["renames"][1]["to"]                  # the second rename fails
                occupied.parent.mkdir(parents=True, exist_ok=True)
                occupied.write_bytes(b"unrelated\n")
                self.assertEqual(drive(ws, plan, fault=point).returncode, 97)
                CrashInjection.assert_consistent(self, ws, plan)
                self.assertTrue(resolve(ws, "undo")["ok"])
                self.assertEqual((where(ws, plan), reg_state(ws, plan)), (["old", "old"], "original"))
                self.assertEqual(occupied.read_bytes(), b"unrelated\n")

    def test_recovery_removes_a_lock_left_by_the_crashed_move_itself(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            plan = plan_for(ws, made)
            self.assertEqual(drive(ws, plan, fault="move-after-rename:1").returncode, 97)
            self.assertTrue((ws.root / registry.LOCK).exists())               # left behind, as by a crash
            for _ in range(50):                                               # until Windows releases the process's handle
                rec = only_record(ws)
                if not rec["live"]:
                    break
                time.sleep(0.2)
            out = transactions.resolve(ws.root, rec["id"], "undo", rec["token"])   # no `registry unlock` first
            self.assertTrue(out["ok"], out)
            self.assertIn("removed the registry lock", out["note"])
            self.assertEqual(where(ws, plan), ["old"])

    def test_a_junction_appearing_after_preparation_makes_the_record_unusable_and_nothing_is_written_through_it(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            plan = plan_for(ws, made, dest="designs/features/later/diagrams")
            prepared_record(ws, plan)
            outside = Path(tempfile.mkdtemp(prefix="outside-"))
            target = ws.root / "designs/features/later"
            if sys.platform == "win32":
                subprocess.run(["cmd", "/c", "mklink", "/J", str(target), str(outside)], capture_output=True, check=True)
            else:
                os.symlink(outside, target)
            rec = only_record(ws)
            self.assertFalse(rec["valid"])
            for action in ("complete", "undo"):
                with self.assertRaises(DesignError):
                    transactions.resolve(ws.root, rec["id"], action, rec["token"])
            self.assertEqual(os.listdir(outside), [])
            with self.assertRaises(DesignError):
                transactions.registry_guard(ws.root)

    def test_a_forged_registry_replacement_is_never_used(self):                     # m3
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            folder = prepared_record(ws, plan_for(ws, made))
            forged = (folder / "registry.new").read_bytes().replace(b"title: Flow 1", b"title: Forged")
            (folder / "registry.new").write_bytes(forged)
            rewrite_journal(folder, lambda d: d["ops"][-1].update(after_sha=sha(forged)))
            rec = only_record(ws)
            self.assertFalse(rec["valid"])
            self.assertIn("beyond its path", rec["problem"])

    def test_an_unreadable_version_1_record_also_holds_the_registry(self):
        with Workspace() as ws:
            docs, _ = build(ws, 2)
            reqs, token = listing(ws)
            self.assertEqual(run(ws, rb_args(reqs, token), fault="after-replace:1").returncode, 97)
            unlock(ws)
            folder = Path(transactions._tx_root(ws.root, False)) / only_record(ws)["id"]
            (folder / "0.orig").write_bytes(b"damaged")
            made = registry.load(ws.root).entries[-1]
            with self.assertRaises(DesignError) as c:
                registry.relink(ws.root, made.diagram_id, title="Blocked")
            self.assertIn("cannot be read", str(c.exception))

    def test_malformed_input_never_leaves_anything_behind(self):                    # m5
        with Workspace() as ws:
            setup_sources(ws, 1)
            before = (ws.root / registry.REGISTRY).read_bytes()
            for bad in ([], [{"diagram_id": "FD-0001-D1"}], [{"diagram_id": "FD-0001-D1", "from": 1, "to": "x", "sha": "y"}]):
                with self.subTest(renames=bad), registry.lock(ws.root), self.assertRaises(DesignError):
                    transactions.prepare_move(ws.root, "move", bad, before, before + b"#")
            tx = transactions._tx_root(ws.root, False)
            self.assertTrue(tx is None or not [n for n in os.listdir(tx) if n != "windows"])


if __name__ == "__main__":
    unittest.main()
