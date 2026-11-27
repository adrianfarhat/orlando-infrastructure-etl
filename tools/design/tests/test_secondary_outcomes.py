"""T-97 PR B2b-2a pre-PR review: once a primary operation (a registry move or adoption, Complete or
Undo of a move record, a refresh-blocks update or its recovery) is verified, the secondary steps
after it (regenerating diagram-index.md, removing the record) are reported as what they are.

- A failed index regeneration is never reported as done, and never reverses the move.
- A failed record removal is a successful operation with a cleanup warning (exit 0), listed by
  `transaction status` as pending cleanup, retried by later commands without repeating anything.
- A genuinely failed primary operation keeps its non-zero exit code and its message.

The failures are real file-system failures where practical (Windows): a file kept open inside the
record folder (Windows then refuses to rename or delete the folder) and a read-only
diagram-index.md (Windows refuses to replace it)."""

import json
import os
import stat
import sys
import unittest

from tools.design import moves, registry, transactions
from tools.design.tests.test_design import Workspace, cmd
from tools.design.tests.test_move_engine import drive, plan_for, setup_sources
from tools.design.tests.test_moves import DEST, move_args, paths, tree, wait_released
from tools.design.tests.test_transactions import build, listing, rb_args, run, unlock

INDEX = registry.DIAGRAM_INDEX


class RecordHeldOpen:
    """While active, the first record removal finds a file of the record kept open by another
    program (this test), so Windows really refuses to rename or delete the folder; `release()`
    closes it again, as when that program ends."""

    def __enter__(self):
        self.handles, self.real = [], transactions._finish

        def finish(root, rec):
            if not self.handles and rec.folder.is_dir():
                self.handles.append(open(rec.folder / "journal.json", "rb"))
            return self.real(root, rec)
        transactions._finish = finish
        return self

    def release(self):
        for h in self.handles:
            h.close()
        self.handles = []
        transactions._finish = self.real

    def __exit__(self, *exc):
        self.release()


class ReadOnlyIndex:
    """diagram-index.md made read-only: Windows refuses to replace it (a real write failure)."""

    def __init__(self, ws):
        self.p = ws.root / INDEX

    def __enter__(self):
        os.chmod(self.p, stat.S_IREAD)
        return self

    def __exit__(self, *exc):
        os.chmod(self.p, stat.S_IREAD | stat.S_IWRITE)


def status_json(ws):
    code, out, err = cmd(ws.root, "transaction", "status", "--json")
    return code, json.loads(out)


def move_one(ws, made, json_out=True):
    pairs = [(made.diagram_id, DEST + "/")]
    tok = moves.plan(ws.root, "move", pairs).token
    return cmd(ws.root, *move_args(pairs), "--confirm", tok, *(["--json"] if json_out else []))


@unittest.skipUnless(sys.platform == "win32", "the real file-system failures used here are Windows behaviour")
class MoveSecondarySteps(unittest.TestCase):
    def test_a_failed_index_regeneration_is_reported_and_never_reverses_the_move(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)[0]
            with ReadOnlyIndex(ws):
                code, out, err = move_one(ws, made, json_out=False)
                self.assertEqual(code, 0, out + err)
                self.assertIn("the move is complete: the registry names the new paths.", out)
                self.assertNotIn("was regenerated", out)
                self.assertIn(f"warning: {INDEX} could not be regenerated (PermissionError", out)
                self.assertIn("`python -m tools.design index`", out)
                self.assertEqual(paths(ws)[made.diagram_id], f"{DEST}/{made.path.rsplit('/', 1)[1]}")   # not reversed
                self.assertEqual(cmd(ws.root, "index", "--check")[0], 1)          # reported as out of date
                self.assertEqual(status_json(ws)[1], {"records": [], "cleanup": []})
            self.assertEqual(cmd(ws.root, "index")[0], 0)                           # the recovery command works
            self.assertEqual(cmd(ws.root, "index", "--check")[0], 0)

    def test_the_json_result_states_the_index_outcome(self):
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            code, out, err = move_one(ws, made[0])
            self.assertEqual(code, 0, err)
            r = json.loads(out)
            self.assertEqual((r["ok"], r["index"], r["warnings"]), (True, {"regenerated": True, "problem": ""}, []))
            with ReadOnlyIndex(ws):
                code, out, err = move_one(ws, made[1])
            r = json.loads(out)
            self.assertEqual(code, 0, err)
            self.assertEqual((r["ok"], r["index"]["regenerated"]), (True, False))
            self.assertIn("PermissionError", r["index"]["problem"])
            self.assertEqual(len(r["warnings"]), 1)

    def test_a_failed_record_removal_is_a_completed_move_with_pending_cleanup(self):
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            with RecordHeldOpen() as held:
                code, out, err = move_one(ws, made[0], json_out=False)
                self.assertEqual(code, 0, out + err)
                self.assertNotIn("internal error", err)
                self.assertIn("the move is complete", out)
                self.assertIn("It is marked as completed: it holds nothing and is never carried out again", out)
                self.assertIn("may stay pending until the cause", out)
                self.assertNotIn("the next diagram command removes", out)
                code, st = status_json(ws)
                self.assertEqual((code, st["records"]), (0, []))                   # not an unresolved operation
                self.assertEqual([c["kind"] for c in st["cleanup"]], ["completed and verified; its removal is unfinished"])
                code, text, _ = cmd(ws.root, "transaction", "status")
                self.assertEqual(code, 0)
                self.assertIn("cleanup pending:", text)
                # persistent: later commands keep working, retry the removal and repeat nothing
                moved_bytes = (ws.root / paths(ws)[made[0].diagram_id]).read_bytes()
                reg = (ws.root / registry.REGISTRY).read_bytes()
                for _ in range(2):
                    self.assertEqual(cmd(ws.root, "index")[0], 0)
                    self.assertEqual((ws.root / registry.REGISTRY).read_bytes(), reg)
                    self.assertFalse((ws.root / made[0].path).exists())
                    self.assertEqual((ws.root / paths(ws)[made[0].diagram_id]).read_bytes(), moved_bytes)
                    self.assertEqual(len(status_json(ws)[1]["cleanup"]), 1)
                code, out, err = move_one(ws, made[1], json_out=False)             # another move runs beside it
                self.assertEqual(code, 0, out + err)
                self.assertEqual(len(status_json(ws)[1]["cleanup"]), 1)
                reg = (ws.root / registry.REGISTRY).read_bytes()
                held.release()                                                     # the other program ends
            before = tree(ws)
            self.assertEqual(cmd(ws.root, "index")[0], 0)                          # the retry now succeeds
            self.assertEqual(status_json(ws)[1], {"records": [], "cleanup": []})
            self.assertEqual({k: v for k, v in tree(ws).items() if not k.startswith(transactions.TX_ROOT)},
                             {k: v for k, v in before.items() if not k.startswith(transactions.TX_ROOT)})
            self.assertEqual((ws.root / registry.REGISTRY).read_bytes(), reg)      # nothing was carried out again

    def test_both_secondary_steps_failing_together(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)[0]
            with ReadOnlyIndex(ws), RecordHeldOpen():
                code, out, err = move_one(ws, made)
                self.assertEqual(code, 0, err)
                r = json.loads(out)
                self.assertTrue(r["ok"])
                self.assertFalse(r["index"]["regenerated"])
                self.assertEqual(len(r["warnings"]), 2)
                self.assertIn("could not be regenerated", r["warnings"][0])
                self.assertIn("removing the record", r["warnings"][1])
            self.assertEqual(cmd(ws.root, "index")[0], 0)                          # both are retried and done
            self.assertEqual(status_json(ws)[1]["cleanup"], [])
            self.assertEqual(cmd(ws.root, "index", "--check")[0], 0)

    def test_an_adoption_with_pending_cleanup(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)[0]
            new = f"{DEST}/{made.path.rsplit('/', 1)[1]}"
            (ws.root / DEST).mkdir(parents=True)
            os.rename(ws.root / made.path, ws.root / new)
            tok = moves.plan(ws.root, "adopt", None).token
            with RecordHeldOpen():
                code, out, err = cmd(ws.root, "registry", "adopt-moves", "--confirm", tok)
                self.assertEqual(code, 0, out + err)
                self.assertIn("adopted", out)
                self.assertIn("warning: removing the record", out)
            self.assertEqual(paths(ws)[made.diagram_id], new)

    def test_a_genuine_failure_keeps_its_exit_code_even_when_cleanup_also_fails(self):
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            pairs = [(made[0].diagram_id, DEST + "/"), (made[1].diagram_id, DEST + "/")]
            tok = moves.plan(ws.root, "move", pairs).token
            real, calls = os.rename, []

            def locked(src, dst, *a, **k):                                         # the second source is locked
                calls.append(1)
                if len(calls) == 2:
                    raise PermissionError(13, "locked by another program", str(src))
                return real(src, dst, *a, **k)
            transactions.os.rename = locked
            try:
                with RecordHeldOpen():
                    code, out, err = cmd(ws.root, *move_args(pairs), "--confirm", tok)
            finally:
                transactions.os.rename = real
            self.assertEqual(code, 2, out + err)
            self.assertIn("so this move changed nothing", err)
            self.assertIn("It is still listed by", err)                           # the record could not be removed
            self.assertEqual(paths(ws)[made[0].diagram_id], made[0].path)
            rec = transactions.status(ws.root)[0]                                  # discoverable, and clean to resolve
            out = transactions.resolve(ws.root, rec["id"], "undo", rec["token"])
            self.assertTrue(out["ok"], out)
            self.assertEqual(transactions.status(ws.root), [])


@unittest.skipUnless(sys.platform == "win32", "the real file-system failures used here are Windows behaviour")
class RecoverySecondarySteps(unittest.TestCase):
    def crashed(self, ws, point):
        made = setup_sources(ws, 1)
        plan = plan_for(ws, made)
        self.assertEqual(drive(ws, plan, fault=point).returncode, 97)
        wait_released(ws)
        unlock(ws)
        return plan

    def test_complete_with_pending_cleanup_and_a_failed_index(self):
        with Workspace() as ws:
            plan = self.crashed(ws, "move-before-registry")
            rec = transactions.status(ws.root)[0]
            with ReadOnlyIndex(ws), RecordHeldOpen():
                code, out, err = cmd(ws.root, "transaction", "complete", rec["id"], "--confirm", rec["token"], "--json")
                self.assertEqual(code, 0, out + err)
                r = json.loads(out)
                self.assertTrue(r["ok"])
                self.assertFalse(r["index"]["regenerated"])
                self.assertEqual(len(r["warnings"]), 2)
                self.assertIn("warning:", r["message"])                           # shown by the recovery panel
                self.assertEqual(transactions.status(ws.root), [])                 # marked completed: not unresolved
                transactions.registry_guard(ws.root)                               # the hold is released
            after = (ws.root / registry.REGISTRY).read_bytes()
            self.assertEqual(after, plan["after"])
            self.assertEqual(cmd(ws.root, "index")[0], 0)                          # the retry finishes the cleanup
            self.assertEqual(status_json(ws)[1]["cleanup"], [])
            self.assertEqual((ws.root / registry.REGISTRY).read_bytes(), after)    # nothing carried out again

    def test_undo_with_pending_cleanup_keeps_the_record_listed_until_it_is_removed(self):
        with Workspace() as ws:
            plan = self.crashed(ws, "move-after-rename:1")
            rec = transactions.status(ws.root)[0]
            with RecordHeldOpen() as held:
                code, out, err = cmd(ws.root, "transaction", "undo", rec["id"], "--confirm", rec["token"])
                self.assertEqual(code, 0, out + err)
                self.assertIn("undone", out)
                self.assertIn("It is still listed by `python -m tools.design transaction status` and holds the registry", out)
                self.assertIn("repeating Undo changes nothing more", out)
                again = transactions.status(ws.root)[0]                            # Undo was not durably marked
                self.assertEqual(again["undo"]["restores"], [])                    # nothing left to put back
                with self.assertRaises(transactions.DesignError):
                    transactions.registry_guard(ws.root)                           # conservative: still held
                reg = (ws.root / registry.REGISTRY).read_bytes()
                # repeated while the cause persists (here even the journal cannot be rewritten): a result, not a
                # crash; the state is already reached, nothing is written, and the record stays listed
                out = transactions.resolve(ws.root, again["id"], "undo", again["token"])
                self.assertFalse(out["ok"])
                self.assertTrue(out["effectively_done"])
                self.assertIn("PermissionError", out["message"])
                self.assertEqual((ws.root / registry.REGISTRY).read_bytes(), reg)
                self.assertEqual(len(transactions.status(ws.root)), 1)
                held.release()
            again = transactions.status(ws.root)[0]
            out = transactions.resolve(ws.root, again["id"], "undo", again["token"])
            self.assertTrue(out["ok"], out)
            self.assertEqual(out["warnings"], [])
            self.assertEqual((ws.root / registry.REGISTRY).read_bytes(), reg)      # nothing written again
            self.assertEqual(transactions.rename_state(ws.root, dict(plan["renames"][0], observed=False)), "old")
            self.assertEqual(transactions.status(ws.root), [])


@unittest.skipUnless(sys.platform == "win32", "the real file-system failures used here are Windows behaviour")
class Version1SecondarySteps(unittest.TestCase):
    def test_refresh_blocks_with_pending_cleanup_is_a_success(self):
        with Workspace() as ws:
            docs, _ = build(ws, 2)
            reqs, token = listing(ws)
            with RecordHeldOpen() as held:
                code, out, err = cmd(ws.root, *rb_args(reqs, token))
                self.assertEqual(code, 0, out + err)
                r = json.loads(out)
                self.assertTrue(r["ok"])
                self.assertEqual([f["state"] for f in r["files"]], ["updated", "updated"])
                self.assertEqual(len(r["warnings"]), 1)
                self.assertIn("marked as completed", r["warnings"][0])
                written = {d: (ws.root / d).read_bytes() for d in docs}
                code, st = status_json(ws)
                self.assertEqual((code, st["records"], len(st["cleanup"])), (0, [], 1))
                self.assertEqual(cmd(ws.root, "index")[0], 0)                      # persistent; nothing repeated
                self.assertEqual({d: (ws.root / d).read_bytes() for d in docs}, written)
                self.assertEqual(len(status_json(ws)[1]["cleanup"]), 1)
                held.release()
            self.assertEqual(cmd(ws.root, "index")[0], 0)
            self.assertEqual(status_json(ws)[1]["cleanup"], [])
            self.assertEqual({d: (ws.root / d).read_bytes() for d in docs}, written)

    def test_refresh_blocks_recovery_with_pending_cleanup(self):
        for action in ("complete", "undo"):
            with self.subTest(action=action), Workspace() as ws:
                docs, _ = build(ws, 2)
                reqs, token = listing(ws)
                self.assertEqual(run(ws, rb_args(reqs, token), fault="after-replace:1").returncode, 97)
                wait_released(ws)
                unlock(ws)
                rec = transactions.status(ws.root)[0]
                with RecordHeldOpen():
                    code, out, err = cmd(ws.root, "transaction", action, rec["id"], "--confirm", rec["token"], "--json")
                self.assertEqual(code, 0, out + err)
                r = json.loads(out)
                self.assertTrue(r["ok"])
                self.assertIn("warning: removing the record", r["message"])
                listed = transactions.status(ws.root)
                self.assertEqual(len(listed), 0 if action == "complete" else 1)    # Complete is durably marked
                if action == "undo":
                    self.assertIn("still listed", r["warnings"][0])
                    out = transactions.resolve(ws.root, listed[0]["id"], "undo", listed[0]["token"])
                    self.assertTrue(out["ok"])
                    self.assertEqual(out["warnings"], [])
                else:
                    self.assertEqual(cmd(ws.root, "index")[0], 0)
                self.assertEqual(status_json(ws)[1], {"records": [], "cleanup": []})

    def test_a_genuine_refresh_failure_keeps_its_exit_code(self):
        with Workspace() as ws:
            docs, _ = build(ws, 2)
            reqs, token = listing(ws)
            before = {d: (ws.root / d).read_bytes() for d in docs}
            r = run(ws, rb_args(reqs, token), fault="change-before-replace:2")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn(b"changed nothing", r.stderr)
            self.assertEqual((ws.root / docs[0]).read_bytes(), before[docs[0]])


if __name__ == "__main__":
    unittest.main()
