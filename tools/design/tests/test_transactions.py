"""T-97 PR B2b-1: closed-document updates as recoverable transactions (decisions D1-D8).

Crash injection runs the real command in a separate process and ends it at every meaningful
transaction boundary (os._exit at the point, or termination from outside while it waits there);
afterwards every document must be exactly its original or exactly its replacement, and Complete
and Undo must each reach a single consistent state, repeatably."""

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unittest
from pathlib import Path

from tools.design import designer_api, diagrams, ownership, registry, transactions
from tools.design.tests.test_design import REPO_ROOT, Workspace, cmd
from tools.design.tests.test_designer_api import after, apply, request
from tools.design.workspace import DesignError, new_feature

PY = sys.executable
sha = lambda b: hashlib.sha256(b).hexdigest()


def build(ws, n=3):
    """n features, each with a block of one feature-owned diagram, all current; then the source
    changes, so every block is out of date (case 1). Returns (documents, source path)."""
    docs = [new_feature(ws.root, f"Feature {chr(65 + i)}").path for i in range(n)]
    made = ownership.new_diagram(ws.root, "FD-0001", "Shared flow")
    for d in docs:
        text = ws.text(d)
        at = after(text.split("\n"), "- **Desired outcome:**")
        r, code = request(ws, op="insert", path=d, text=text, at=at, diagram_id=made.diagram_id)
        assert code == 0, r
        (ws.root / d).write_bytes(apply(text, r).encode("utf-8"))
    code, out, err = cmd(ws.root, "index")
    assert code == 0, err
    edit_source(ws, made.path, "New step (planned)", "Changed step")
    return docs, made.path


def edit_source(ws, rel, old, new):
    p = ws.root / rel
    text = p.read_bytes().decode("utf-8")
    assert old in text
    p.write_bytes(text.replace(old, new, 1).encode("utf-8"))


def listing(ws):
    a = transactions.affected(ws.root)
    return [(d["path"], d["sha256"]) for d in a["documents"] if not d["excluded"]], a["sources_token"]


def rb_args(reqs, token=None):
    args = ["refresh-blocks"]
    for p, h in reqs:
        args += ["--file", p, "--expect", h]
    return args + (["--sources-token", token] if token else []) + ["--json"]


def run(ws, args, fault=None, mode=None, timeout=120):
    """The real command in its own process (fault: a DESIGN_TEST_FAULT point)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("DESIGN_TEST_FAULT")}
    if fault:
        env.update(DESIGN_TEST_FAULT=fault, DESIGN_TEST_FAULT_ROOT=str(ws.root.resolve()))
        if mode:
            env["DESIGN_TEST_FAULT_MODE"] = mode
    return subprocess.run([PY, "-B", "-m", "tools.design", *args, "--root", str(ws.root)], cwd=REPO_ROOT, env=env,
                          capture_output=True, timeout=timeout)


def stop(proc, ws):
    """End a test process, then wait until Windows has released its handle on the registry lock
    (it does so a moment after the process ends), leaving the lock file as a crash would."""
    proc.kill()
    proc.wait()
    for stream in (proc.stdout, proc.stderr):
        if stream:
            stream.close()
    lock = ws.root / registry.LOCK
    for _ in range(200):                     # released when it can be renamed (opening it would succeed earlier)
        try:
            os.rename(lock, str(lock) + ".probe")
            os.rename(str(lock) + ".probe", lock)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            time.sleep(0.1)


def snapshot(ws, docs):
    return {d: (ws.root / d).read_bytes() for d in docs}


def unlock(ws):
    if (ws.root / registry.LOCK).exists():
        code, out, err = cmd(ws.root, "registry", "unlock", "--confirm")
        assert code == 0, out + err


def only_record(ws):
    found = transactions.status(ws.root)
    assert len(found) == 1, found
    return found[0]


class Update(unittest.TestCase):
    def test_all_listed_documents_are_updated_and_no_record_is_left(self):
        with Workspace() as ws:
            docs, src = build(ws)
            before = snapshot(ws, docs)
            reqs, token = listing(ws)
            self.assertEqual(sorted(p for p, _ in reqs), sorted(docs))
            known = diagrams.sources(ws.root)
            want = {d: diagrams.apply(before[d].decode("utf-8"), d, known).encode("utf-8") for d in docs}
            code, out, err = cmd(ws.root, *rb_args(reqs, token))
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["ok"], True)
            self.assertEqual(snapshot(ws, docs), want)
            self.assertEqual(transactions.status(ws.root), [])
            self.assertEqual(sorted(os.listdir(ws.root / transactions.TX_ROOT)), [])
            self.assertFalse((ws.root / registry.LOCK).exists())
            self.assertEqual(listing(ws)[0], [])                       # nothing out of date any more
            code, out, _ = cmd(ws.root, "check")
            self.assertNotIn("E16", out)

    def test_a_document_changed_since_listing_means_nothing_is_written(self):
        with Workspace() as ws:
            docs, _ = build(ws)
            reqs, token = listing(ws)
            p = ws.root / docs[1]
            p.write_bytes(p.read_bytes() + b"\nmine\n")
            before = snapshot(ws, docs)
            code, _, err = cmd(ws.root, *rb_args(reqs, token))
            self.assertEqual(code, 2)
            self.assertIn("changed since it was listed", err)
            self.assertEqual(snapshot(ws, docs), before)
            self.assertEqual(transactions.status(ws.root), [])

    def test_a_source_changed_since_listing_means_nothing_is_written(self):
        with Workspace() as ws:
            docs, src = build(ws)
            reqs, token = listing(ws)
            edit_source(ws, src, "Changed step", "Changed again")
            before = snapshot(ws, docs)
            code, _, err = cmd(ws.root, *rb_args(reqs, token))
            self.assertEqual(code, 2)
            self.assertIn("changed since the documents were listed", err)
            self.assertEqual(snapshot(ws, docs), before)

    def test_conflicts_are_left_alone_and_listed(self):
        with Workspace() as ws:
            docs, _ = build(ws, 2)
            p = ws.root / docs[0]
            p.write_bytes(p.read_bytes().replace(b"Existing step", b"Hand edit", 1))     # a conflict (case 3)
            a = transactions.affected(ws.root)
            self.assertEqual([d["path"] for d in a["documents"]], [docs[1]])

    def test_documents_with_architecture_diagrams_are_updated_and_recovered(self):
        """QA M1: an architecture source under docs/architecture/ is read (never written)."""
        with Workspace() as ws:
            docs = [new_feature(ws.root, f"Arch {i}").path for i in range(2)]
            for d in docs:
                text = ws.text(d)
                at = after(text.split("\n"), "- **Desired outcome:**")
                r, code = request(ws, op="insert", path=d, text=text, at=at, diagram_id="AD-0001")
                self.assertEqual(code, 0, r)
                (ws.root / d).write_bytes(apply(text, r).encode("utf-8"))
            self.assertEqual(cmd(ws.root, "index")[0], 0)
            src = diagrams.sources(ws.root)["AD-0001"].path
            self.assertTrue(src.startswith("docs/architecture/"))
            p = ws.root / src
            text = p.read_bytes().decode("utf-8")
            first = next(l for l in diagrams.sources(ws.root)["AD-0001"].lines if "-->" in l)
            p.write_bytes(text.replace(first, first + " %% changed in this test copy", 1).encode("utf-8"))
            before = snapshot(ws, docs)
            reqs, token = listing(ws)
            self.assertEqual(sorted(x for x, _ in reqs), sorted(docs))
            self.assertEqual(run(ws, rb_args(reqs, token), fault="after-replace:1").returncode, 97)
            rec = only_record(ws)
            self.assertIn(src, transactions._read_record(ws.root, ws.root / transactions.TX_ROOT / rec["id"]).data["sources"])
            self.assertEqual(rec["source_changes"], [])                         # read correctly: unchanged
            self.assertTrue(rec["complete"]["possible"], rec["complete"])
            self.assertTrue(transactions.resolve(ws.root, rec["id"], "complete", rec["token"])["ok"])
            self.assertTrue(all(snapshot(ws, docs)[d] != before[d] for d in docs))
            self.assertEqual(p.read_bytes().decode("utf-8"), text.replace(first, first + " %% changed in this test copy", 1))

    def test_refused_targets(self):
        with Workspace() as ws:
            docs, _ = build(ws, 1)
            reqs, token = listing(ws)
            h = reqs[0][1]
            outside = Path(ws._tmp.name) / "outside.md"
            outside.write_bytes(b"x")
            for bad in ["docs/architecture/system-overview.md", "../outside.md", "designs/features/../../outside.md",
                        "designs/README.md", "C:/x.md", "/etc/x.md", "designs\\features\\a.md", "designs/features/./a.md"]:
                with self.subTest(path=bad):
                    code, _, err = cmd(ws.root, *rb_args([(bad, h)], token))
                    self.assertEqual(code, 2, err)
            self.assertEqual(transactions.status(ws.root), [])

    def test_a_symbolic_link_or_junction_on_the_way_is_refused(self):
        with Workspace() as ws:
            docs, _ = build(ws, 1)
            outside = Path(ws._tmp.name) / "elsewhere"
            outside.mkdir()
            (outside / "x.md").write_bytes((ws.root / docs[0]).read_bytes())
            link = ws.root / "designs/features/link"
            if sys.platform == "win32":
                r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
                self.assertEqual(r.returncode, 0, r.stderr)
            else:
                os.symlink(outside, link)
            with self.assertRaises(DesignError) as c:
                transactions.safe_path(ws.root, "designs/features/link/x.md")
            self.assertIn("symbolic link or junction", str(c.exception))
            code, _, err = cmd(ws.root, *rb_args([("designs/features/link/x.md", sha((outside / "x.md").read_bytes()))]))
            self.assertEqual(code, 2)
            os.rmdir(link) if sys.platform == "win32" else os.unlink(link)

    def test_the_registry_lock_held_by_another_command_gives_E12(self):
        with Workspace() as ws:
            docs, _ = build(ws, 1)
            reqs, token = listing(ws)
            holder = subprocess.Popen([PY, "-c", "import sys,time\nfrom pathlib import Path\nfrom tools.design import "
                                       "registry\nwith registry.lock(Path(sys.argv[1])):\n print('held', flush=True)\n"
                                       " time.sleep(30)", str(ws.root)], cwd=REPO_ROOT, stdout=subprocess.PIPE)
            try:
                self.assertEqual(holder.stdout.readline().strip(), b"held")
                before = snapshot(ws, docs)
                code, _, err = cmd(ws.root, *rb_args(reqs, token))
                self.assertEqual(code, 2)
                self.assertIn("E12", err)
                self.assertEqual(snapshot(ws, docs), before)
            finally:
                stop(holder, ws)

    def test_a_git_operation_in_progress_is_refused(self):
        with Workspace() as ws:
            docs, _ = build(ws, 1)
            reqs, token = listing(ws)
            gitdir = ws.root / ".git"
            for marker in ("MERGE_HEAD", "rebase-merge", "index.lock"):
                with self.subTest(marker=marker):
                    target = gitdir / marker
                    target.mkdir() if marker == "rebase-merge" else target.write_bytes(b"")
                    code, _, err = cmd(ws.root, *rb_args(reqs, token))
                    self.assertEqual(code, 2)
                    self.assertIn("Git operation is in progress", err)
                    target.rmdir() if marker == "rebase-merge" else target.unlink()
            self.assertEqual(cmd(ws.root, *rb_args(reqs, token))[0], 0)


class OpenElsewhere(unittest.TestCase):
    """D6: documents another Feature Designer window lists as open are never written on disk."""

    def window(self, ws, docs, age=0.0, name="0123456789abcdef", raw=None):
        folder = ws.root / transactions.WINDOWS
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / f"{name}.json"
        now = time.time() - age
        p.write_bytes(raw if raw is not None else json.dumps(
            {"format": "feature-designer-window", "version": 1, "window": name, "pid": 4242, "host": __import__("platform").node(),
             "heartbeat": now, "documents": [{"path": d, "dirty": True} for d in docs]}).encode())
        os.utime(p, (now, now))
        return p

    def test_a_document_open_in_a_live_window_is_refused(self):
        with Workspace() as ws:
            docs, _ = build(ws, 2)
            reqs, token = listing(ws)
            self.window(ws, [docs[0]])
            a = transactions.affected(ws.root)
            self.assertIn("open in a VS Code window", [d for d in a["documents"] if d["path"] == docs[0]][0]["excluded"])
            before = snapshot(ws, docs)
            code, _, err = cmd(ws.root, *rb_args(reqs, token))
            self.assertEqual(code, 2)
            self.assertIn("unsaved changes", err)
            self.assertEqual(snapshot(ws, docs), before)
            # the caller's own window is checked too (it may have opened the document since it listed it: QA m2)
            with self.assertRaises(DesignError):
                transactions.update(ws.root, reqs, token)
            (ws.root / transactions.WINDOWS / "0123456789abcdef.json").unlink()
            self.assertEqual(transactions.update(ws.root, reqs, token)["ok"], True)

    def test_a_window_silent_too_long_no_longer_counts(self):
        with Workspace() as ws:
            docs, _ = build(ws, 1)
            reqs, token = listing(ws)
            self.window(ws, docs, age=transactions.WINDOW_LIVE + 5)
            self.assertEqual(transactions.update(ws.root, reqs, token)["ok"], True)

    def test_an_unreadable_recent_window_file_blocks_every_update(self):
        with Workspace() as ws:
            docs, _ = build(ws, 1)
            reqs, token = listing(ws)
            p = self.window(ws, docs, raw=b"{not json")
            with self.assertRaises(DesignError) as c:
                transactions.update(ws.root, reqs, token)
            self.assertIn("cannot be read", str(c.exception))
            old = time.time() - 60
            os.utime(p, (old, old))                                    # an old unreadable file is not a live window
            self.assertEqual(transactions.update(ws.root, reqs, token)["ok"], True)


POINTS_BEFORE = ["after-orig:1", "after-new:3", "before-journal", "after-journal"]          # no document touched
POINTS_DURING = ["after-prepare", "after-committing-mark", "before-replace:1", "after-replace:1", "before-replace:2",
                 "after-replace:2", "after-replace:3", "before-committed-mark"]
POINTS_AFTER = ["after-committed-mark", "after-done-rename", "during-cleanup:1", "during-cleanup:4"]


class CrashRecovery(unittest.TestCase):
    """Requirement 7: the process ends at every meaningful boundary."""

    def crash(self, ws, docs, point, mode=None):
        reqs, token = listing(ws)
        before = snapshot(ws, docs)
        known = diagrams.sources(ws.root)
        want = {d: diagrams.apply(before[d].decode("utf-8"), d, known).encode("utf-8") for d in docs}
        if mode == "sleep":                      # terminated from outside while it waits at the point
            env = {k: v for k, v in os.environ.items() if not k.startswith("DESIGN_TEST_FAULT")}
            env.update(DESIGN_TEST_FAULT=point, DESIGN_TEST_FAULT_ROOT=str(ws.root.resolve()), DESIGN_TEST_FAULT_MODE="sleep")
            proc = subprocess.Popen([PY, "-B", "-m", "tools.design", *rb_args(reqs, token), "--root", str(ws.root)],
                                    cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            line = proc.stderr.readline()
            self.assertIn(b"FAULT " + point.encode(), line)
            stop(proc, ws)                       # TerminateProcess on Windows
        else:
            r = run(ws, rb_args(reqs, token), fault=point)
            self.assertEqual(r.returncode, 97, r.stderr.decode())
        now = snapshot(ws, docs)
        for d in docs:                           # never anything but the original or the replacement
            self.assertIn(now[d], (before[d], want[d]), (point, d))
        return before, want

    def test_crash_before_any_document_is_touched(self):
        for point in POINTS_BEFORE:
            with self.subTest(point=point), Workspace() as ws:
                docs, _ = build(ws)
                before, want = self.crash(ws, docs, point)
                self.assertEqual(snapshot(ws, docs), before)
                self.assertEqual(transactions.status(ws.root), [])      # only a .preparing folder
                unlock(ws)                                              # the ended process's lock
                reqs, token = listing(ws)
                self.assertEqual(transactions.update(ws.root, reqs, token)["ok"], True)
                self.assertEqual(snapshot(ws, docs), want)
                self.assertEqual(os.listdir(ws.root / transactions.TX_ROOT), [])   # the debris was removed

    def test_crash_during_the_update_then_complete(self):
        for point in POINTS_DURING:
            with self.subTest(point=point), Workspace() as ws:
                docs, _ = build(ws)
                before, want = self.crash(ws, docs, point)
                rec = only_record(ws)
                self.assertTrue(rec["valid"], rec)
                self.assertFalse(rec["live"])
                self.assertTrue(rec["complete"]["possible"] and rec["undo"]["possible"])
                code, out, _ = cmd(ws.root, "check")
                self.assertIn("(E16)", out)
                code, out, err = cmd(ws.root, "transaction", "complete", rec["id"], "--confirm", rec["token"])
                self.assertEqual(code, 0, out + err)
                self.assertEqual(snapshot(ws, docs), want)
                self.assertEqual(transactions.status(ws.root), [])
                self.assertFalse((ws.root / registry.LOCK).exists())
                code, out, _ = cmd(ws.root, "transaction", "complete", rec["id"], "--confirm", rec["token"])
                self.assertEqual(code, 0)                               # repeated: already resolved
                self.assertIn("already resolved", out)
                self.assertEqual(snapshot(ws, docs), want)

    def test_crash_during_the_update_then_undo(self):
        for point in POINTS_DURING:
            with self.subTest(point=point), Workspace() as ws:
                docs, _ = build(ws)
                before, want = self.crash(ws, docs, point)
                rec = only_record(ws)
                r = transactions.resolve(ws.root, rec["id"], "undo", rec["token"])
                self.assertTrue(r["ok"], r)
                self.assertEqual(snapshot(ws, docs), before)
                self.assertEqual(transactions.status(ws.root), [])
                self.assertTrue(transactions.resolve(ws.root, rec["id"], "undo", rec["token"]).get("already"))

    def test_crash_after_the_update_was_verified(self):
        for point in POINTS_AFTER:
            with self.subTest(point=point), Workspace() as ws:
                docs, _ = build(ws)
                before, want = self.crash(ws, docs, point)
                self.assertEqual(snapshot(ws, docs), want)
                self.assertEqual(transactions.status(ws.root), [])      # committed: only clean-up was left
                unlock(ws)
                self.assertEqual(cmd(ws.root, "index")[0], 0)            # the next writer removes the debris
                self.assertEqual(os.listdir(ws.root / transactions.TX_ROOT), [])

    def test_termination_from_outside(self):
        for point in ("after-journal", "after-replace:1", "after-replace:2", "before-committed-mark"):
            with self.subTest(point=point), Workspace() as ws:
                docs, _ = build(ws)
                before, want = self.crash(ws, docs, point, mode="sleep")
                found = transactions.status(ws.root)
                if point == "after-journal":
                    self.assertEqual(found, [])
                    continue
                rec = found[0]
                self.assertTrue(transactions.resolve(ws.root, rec["id"], "complete", rec["token"])["ok"])
                self.assertEqual(snapshot(ws, docs), want)


class InterruptedRecovery(unittest.TestCase):
    """Requirement 6: Complete and Undo are idempotent, also after an interruption during recovery."""

    def start(self, ws):
        docs, src = build(ws)
        reqs, token = listing(ws)
        before = snapshot(ws, docs)
        known = diagrams.sources(ws.root)
        want = {d: diagrams.apply(before[d].decode("utf-8"), d, known).encode("utf-8") for d in docs}
        self.assertEqual(run(ws, rb_args(reqs, token), fault="after-replace:1").returncode, 97)
        return docs, src, before, want

    def test_complete_interrupted_then_repeated(self):
        for point in ("complete-after-mark", "complete-after:2", "complete-after:3", "after-done-rename",
                      "during-cleanup:2"):
            with self.subTest(point=point), Workspace() as ws:
                docs, _, before, want = self.start(ws)
                rec = only_record(ws)
                r = run(ws, ["transaction", "complete", rec["id"], "--confirm", rec["token"]], fault=point)
                self.assertEqual(r.returncode, 97, r.stderr.decode())
                for d in docs:
                    self.assertIn((ws.root / d).read_bytes(), (before[d], want[d]))
                found = transactions.status(ws.root)
                if found:
                    rec = found[0]
                    r = run(ws, ["transaction", "complete", rec["id"], "--confirm", rec["token"]])
                    self.assertEqual(r.returncode, 0, r.stdout.decode() + r.stderr.decode())
                else:
                    unlock(ws)
                self.assertEqual(snapshot(ws, docs), want)
                self.assertEqual(transactions.status(ws.root), [])

    def test_undo_interrupted_then_repeated(self):
        for point in ("undo-after-mark", "undo-after:1", "undo-after:2"):
            with self.subTest(point=point), Workspace() as ws:
                docs, _, before, want = self.start(ws)
                rec = only_record(ws)
                self.assertEqual(run(ws, ["transaction", "undo", rec["id"], "--confirm", rec["token"]],
                                     fault=point).returncode, 97)
                rec = only_record(ws)
                self.assertTrue(transactions.resolve(ws.root, rec["id"], "undo", rec["token"])["ok"])
                self.assertEqual(snapshot(ws, docs), before)

    def test_undo_after_a_partial_complete_and_complete_after_a_partial_undo(self):
        with Workspace() as ws:
            docs, _, before, want = self.start(ws)
            rec = only_record(ws)
            self.assertEqual(run(ws, ["transaction", "complete", rec["id"], "--confirm", rec["token"]],
                                 fault="complete-after:2").returncode, 97)
            rec = only_record(ws)
            self.assertEqual(rec["action"], "complete")
            self.assertEqual(run(ws, ["transaction", "undo", rec["id"], "--confirm", rec["token"]],
                                 fault="undo-after:1").returncode, 97)
            rec = only_record(ws)
            self.assertTrue(transactions.resolve(ws.root, rec["id"], "complete", rec["token"])["ok"])
            self.assertEqual(snapshot(ws, docs), want)


class UnexpectedChanges(unittest.TestCase):
    """Requirements 4 and 5: recovery never overwrites unexpected changes; Complete revalidates."""

    def interrupted(self, ws, point="after-replace:1"):
        docs, src = build(ws)
        reqs, token = listing(ws)
        before = snapshot(ws, docs)
        self.assertEqual(run(ws, rb_args(reqs, token), fault=point).returncode, 97)
        return docs, src, before

    def test_a_document_edited_after_the_crash_is_left_alone(self):
        with Workspace() as ws:
            docs, _, before = self.interrupted(ws)
            mine = (ws.root / docs[2]).read_bytes() + b"\nmy later edit\n"
            (ws.root / docs[2]).write_bytes(mine)
            rec = only_record(ws)
            self.assertEqual([f["state"] for f in rec["files"]], ["updated", "original", "changed"])
            r = transactions.resolve(ws.root, rec["id"], "complete", rec["token"])
            self.assertFalse(r["ok"])
            self.assertEqual((ws.root / docs[2]).read_bytes(), mine)            # never overwritten
            rec = only_record(ws)                                             # the record is kept
            self.assertEqual(rec["state"], "needs-attention")
            r = transactions.resolve(ws.root, rec["id"], "undo", rec["token"])
            self.assertFalse(r["ok"])
            self.assertEqual([(ws.root / d).read_bytes() for d in docs[:2]], [before[docs[0]], before[docs[1]]])
            self.assertEqual((ws.root / docs[2]).read_bytes(), mine)
            rec = only_record(ws)
            self.assertIn("every document stays exactly as it is now", rec["abandon"]["effect"])
            r = transactions.resolve(ws.root, rec["id"], "abandon", rec["token"])
            self.assertTrue(r["ok"])
            self.assertEqual(transactions.status(ws.root), [])
            self.assertEqual((ws.root / docs[2]).read_bytes(), mine)

    def test_a_deleted_document_is_reported_missing_and_left_alone(self):
        with Workspace() as ws:
            docs, _, _ = self.interrupted(ws)
            (ws.root / docs[1]).unlink()
            rec = only_record(ws)
            self.assertEqual(rec["files"][1]["state"], "missing")
            self.assertFalse(transactions.resolve(ws.root, rec["id"], "complete", rec["token"])["ok"])
            self.assertFalse((ws.root / docs[1]).exists())

    def test_complete_is_refused_when_a_source_or_the_registry_changed(self):
        with Workspace() as ws:
            docs, src, before = self.interrupted(ws)
            edit_source(ws, src, "Changed step", "Changed after the crash")
            rec = only_record(ws)
            self.assertFalse(rec["complete"]["possible"])
            self.assertIn(src, rec["complete"]["reason"])
            with self.assertRaises(DesignError):
                transactions.resolve(ws.root, rec["id"], "complete", rec["token"])
            self.assertTrue(transactions.resolve(ws.root, rec["id"], "undo", rec["token"])["ok"])
            self.assertEqual(snapshot(ws, docs), before)
        with Workspace() as ws:
            docs, src, before = self.interrupted(ws)
            unlock(ws)
            ownership.new_diagram(ws.root, "FD-0002", "Another")                # the registry changes
            rec = only_record(ws)
            self.assertIn("the diagram registry", rec["source_changes"])
            self.assertFalse(rec["complete"]["possible"])

    def test_a_decision_on_a_state_that_changed_since_it_was_shown_is_refused(self):
        with Workspace() as ws:
            docs, _, before = self.interrupted(ws)
            rec = only_record(ws)
            (ws.root / docs[1]).write_bytes(b"changed meanwhile")
            with self.assertRaises(DesignError) as c:
                transactions.resolve(ws.root, rec["id"], "undo", rec["token"])
            self.assertIn("changed since they were shown", str(c.exception))
            self.assertNotEqual((ws.root / docs[0]).read_bytes(), before[docs[0]])   # nothing was done

    def test_recovery_never_writes_a_document_open_in_a_window(self):
        with Workspace() as ws:
            docs, _, before = self.interrupted(ws)
            folder = ws.root / transactions.WINDOWS
            folder.mkdir(parents=True, exist_ok=True)
            w = folder / "00000000000000aa.json"
            w.write_text(json.dumps({"format": "feature-designer-window", "version": 1, "window": "00000000000000aa", "pid": 7,
                                     "host": __import__("platform").node(), "heartbeat": time.time(),
                                     "documents": [{"path": docs[1], "dirty": True}]}), encoding="utf-8")
            rec = only_record(ws)
            self.assertFalse(rec["complete"]["possible"] or rec["undo"]["possible"])
            self.assertIn(f"close {docs[1]} first", rec["complete"]["reason"])
            self.assertTrue(rec["files"][1]["open"])
            for action in ("complete", "undo"):
                with self.assertRaises(DesignError):
                    transactions.resolve(ws.root, rec["id"], action, rec["token"])
            self.assertEqual((ws.root / docs[1]).read_bytes(), before[docs[1]])
            w.unlink()                                                    # the window closed the document
            rec = only_record(ws)
            self.assertTrue(transactions.resolve(ws.root, rec["id"], "undo", rec["token"])["ok"])
            self.assertEqual(snapshot(ws, docs), before)

    def test_an_external_edit_during_the_update_rolls_back_what_it_wrote(self):
        with Workspace() as ws:
            docs, _ = build(ws)
            reqs, token = listing(ws)
            before = snapshot(ws, docs)
            r = run(ws, rb_args(reqs, token), fault="change-before-replace:2")
            self.assertEqual(r.returncode, 2)
            self.assertIn("changed during the update", r.stderr.decode())
            self.assertEqual((ws.root / docs[0]).read_bytes(), before[docs[0]])        # put back
            self.assertEqual((ws.root / docs[1]).read_bytes(), before[docs[1]] + b"\nexternal edit\n")   # theirs
            self.assertEqual((ws.root / docs[2]).read_bytes(), before[docs[2]])
            self.assertEqual(transactions.status(ws.root), [])

    def test_a_crash_during_the_automatic_rollback_is_recoverable(self):
        """The third file changes during the update; while the first two are being put back the
        process ends. Nothing of this update may stay applied after Undo, and the external edit
        is never overwritten."""
        with Workspace() as ws:
            docs, _ = build(ws)
            reqs, token = listing(ws)
            before = snapshot(ws, docs)
            env = {k: v for k, v in os.environ.items() if not k.startswith("DESIGN_TEST_FAULT")}
            env.update(DESIGN_TEST_FAULT_ROOT=str(ws.root.resolve()))
            # change-before-replace:3 makes the commit fail at the third file; rollback-after:1 then ends the process
            script = ("import os, sys\nfrom tools.design import transactions, cli\nreal = transactions._fault\n"
                      "def fault(root, point):\n    if point == 'before-replace:3':\n        with open(os.path.join(sys.argv[1], sys.argv[2]), 'ab') as h:\n"
                      "            h.write(b'\\nexternal edit\\n')\n    if point == 'rollback-after:1':\n        os._exit(97)\n"
                      "transactions._fault = fault\nsys.exit(cli.main(sys.argv[3:]))")
            r = subprocess.run([PY, "-B", "-c", script, str(ws.root), docs[2], *rb_args(reqs, token), "--root", str(ws.root)],
                               cwd=REPO_ROOT, env=env, capture_output=True, timeout=120)
            self.assertEqual(r.returncode, 97, r.stderr.decode())
            ext = before[docs[2]] + b"\nexternal edit\n"
            known = diagrams.sources(ws.root)
            want = {d: diagrams.apply(before[d].decode("utf-8"), d, known).encode("utf-8") for d in docs}
            self.assertIn((ws.root / docs[0]).read_bytes(), (before[docs[0]], want[docs[0]]))
            self.assertIn((ws.root / docs[1]).read_bytes(), (before[docs[1]], want[docs[1]]))
            self.assertEqual((ws.root / docs[2]).read_bytes(), ext)
            rec = only_record(ws)
            self.assertEqual(rec["state"], "rolling-back")
            r = transactions.resolve(ws.root, rec["id"], "undo", rec["token"])
            self.assertEqual([(ws.root / d).read_bytes() for d in docs[:2]], [before[docs[0]], before[docs[1]]])
            self.assertEqual((ws.root / docs[2]).read_bytes(), ext)                       # never overwritten
            self.assertFalse(r["ok"])                                                      # the external edit needs a decision
            rec = only_record(ws)
            self.assertTrue(transactions.resolve(ws.root, rec["id"], "abandon", rec["token"])["ok"])
            self.assertEqual((ws.root / docs[2]).read_bytes(), ext)

    def test_a_replacement_that_does_not_verify_keeps_the_record(self):
        """QA M2: the file was replaced, then something else changed it before it was read back."""
        with Workspace() as ws:
            docs, _ = build(ws)
            reqs, token = listing(ws)
            before = snapshot(ws, docs)
            real = transactions._replace
            calls = []

            def meddling(target, data, prefix=".feature."):
                real(target, data, prefix)
                calls.append(target)
                if len(calls) == 2:                                             # a sync client rewrites it at once
                    target.write_bytes(data + b"\nrewritten by another program\n")
            transactions._replace = meddling
            try:
                with self.assertRaises(DesignError) as c:
                    transactions.update(ws.root, reqs, token)
            finally:
                transactions._replace = real
            self.assertIn("PARTLY DONE", str(c.exception))
            self.assertNotIn("back to its original", str(c.exception))
            rec = only_record(ws)                                                # the originals are kept
            self.assertEqual(rec["state"], "needs-attention")
            self.assertEqual((ws.root / docs[0]).read_bytes(), before[docs[0]])   # the first was put back
            self.assertEqual([f["state"] for f in rec["files"]], ["original", "changed", "original"])
            folder = ws.root / transactions.TX_ROOT / rec["id"]
            self.assertEqual((folder / "1.orig").read_bytes(), before[docs[1]])

    def test_a_folder_this_tooling_did_not_make_is_ignored(self):
        """QA m1: a stray folder is neither a record nor a reason to refuse every writer."""
        with Workspace() as ws:
            docs, _ = build(ws, 1)
            stray = ws.root / transactions.TX_ROOT / "stray"
            stray.mkdir(parents=True)
            (stray / "x.txt").write_bytes(b"x")
            self.assertEqual(transactions.status(ws.root), [])
            self.assertEqual(cmd(ws.root, "index")[0], 0)
            self.assertTrue((stray / "x.txt").exists())

    def test_the_live_update_cannot_be_resolved(self):
        with Workspace() as ws:
            docs, _ = build(ws)
            reqs, token = listing(ws)
            env = {k: v for k, v in os.environ.items() if not k.startswith("DESIGN_TEST_FAULT")}
            env.update(DESIGN_TEST_FAULT="after-replace:1", DESIGN_TEST_FAULT_ROOT=str(ws.root.resolve()),
                       DESIGN_TEST_FAULT_MODE="sleep")
            proc = subprocess.Popen([PY, "-B", "-m", "tools.design", *rb_args(reqs, token), "--root", str(ws.root)],
                                    cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                self.assertIn(b"FAULT", proc.stderr.readline())
                rec = only_record(ws)
                self.assertTrue(rec["live"])
                self.assertFalse(rec["complete"]["possible"] or rec["undo"]["possible"])
                with self.assertRaises(DesignError) as c:
                    transactions.resolve(ws.root, rec["id"], "undo", rec["token"])
                self.assertIn("E12", str(c.exception))
            finally:
                stop(proc, ws)


class Corrupted(unittest.TestCase):
    """Requirement 2: a record is validated before it is used; one that is not valid is never
    used to write a document, and blocks every writer until it is explicitly abandoned."""

    def corrupt(self, ws, how):
        folder = ws.root / transactions.TX_ROOT / only_record(ws)["id"]
        j = folder / "journal.json"
        data = json.loads(j.read_bytes())

        def resign(d):
            d["checksum"] = transactions._sha(transactions._canonical(d))
            j.write_bytes(json.dumps(d).encode())
        if how == "byte":
            j.write_bytes(j.read_bytes().replace(b'"state"', b'"stat\\u0065"', 1)[:-3] + b"}\n")
        elif how == "checksum":
            data["state"] = "prepared"
            j.write_bytes(json.dumps(data).encode())
        elif how == "blob":
            (folder / "1.orig").write_bytes(b"tampered")
        elif how == "traversal":
            data["files"][0]["path"] = "designs/features/../../outside.md"
            resign(data)
        elif how == "architecture":
            data["files"][0]["path"] = "docs/architecture/system-overview.md"
            resign(data)
        elif how == "extra":
            (folder / "evil.md").write_bytes(b"x")
        elif how == "missing":
            j.unlink()
        elif how == "blobname":
            data["files"][0]["orig"] = "../../../x"
            resign(data)
        elif how == "version":
            data["version"] = 2
            resign(data)
        return folder

    def test_every_kind_of_damage_is_detected_and_only_abandon_is_possible(self):
        for how in ("byte", "checksum", "blob", "traversal", "architecture", "extra", "missing", "blobname", "version"):
            with self.subTest(damage=how), Workspace() as ws:
                docs, _ = build(ws)
                reqs, token = listing(ws)
                self.assertEqual(run(ws, rb_args(reqs, token), fault="after-replace:2").returncode, 97)
                self.corrupt(ws, how)
                now = snapshot(ws, docs)
                rec = only_record(ws)
                self.assertFalse(rec["valid"], rec)
                self.assertFalse(rec["complete"]["possible"] or rec["undo"]["possible"])
                for action in ("complete", "undo"):
                    with self.assertRaises(DesignError):
                        transactions.resolve(ws.root, rec["id"], action, rec["token"])
                unlock(ws)
                code, _, err = cmd(ws.root, "index")                          # every writer refuses
                self.assertEqual(code, 2)
                self.assertIn("cannot be read", err)
                r, code = request(ws, op="refresh", path=docs[0], text=ws.text(docs[0]))
                self.assertFalse(r["ok"])
                self.assertEqual(snapshot(ws, docs), now)                      # nothing was written
                r = transactions.resolve(ws.root, rec["id"], "abandon", rec["token"])
                self.assertTrue(r["ok"])
                self.assertEqual(snapshot(ws, docs), now)
                self.assertEqual(transactions.status(ws.root), [])

    def test_a_record_folder_that_is_a_junction_is_not_followed(self):
        with Workspace() as ws:
            docs, _ = build(ws, 1)
            outside = Path(ws._tmp.name) / "fake"
            outside.mkdir()
            link = ws.root / transactions.TX_ROOT / "tx-20260101T000000Z-0123abcd"
            link.parent.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                self.assertEqual(subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                                                capture_output=True).returncode, 0)
            else:
                os.symlink(outside, link)
            (outside / "keep.txt").write_bytes(b"outside the repository")
            rec = only_record(ws)
            self.assertFalse(rec["valid"])
            self.assertIn("symbolic link or junction", rec["problem"])
            r = transactions.resolve(ws.root, rec["id"], "abandon", rec["token"])   # removes the link only
            self.assertTrue(r["ok"])
            self.assertFalse(os.path.lexists(link))
            self.assertEqual((outside / "keep.txt").read_bytes(), b"outside the repository")

    def test_the_transaction_folder_itself_may_not_be_a_junction(self):
        with Workspace() as ws:
            docs, _ = build(ws, 1)
            reqs, token = listing(ws)
            outside = Path(ws._tmp.name) / "fake-tx"
            outside.mkdir()
            tx = ws.root / transactions.TX_ROOT
            if tx.exists():
                tx.rmdir()
            if sys.platform == "win32":
                self.assertEqual(subprocess.run(["cmd", "/c", "mklink", "/J", str(tx), str(outside)],
                                                capture_output=True).returncode, 0)
            else:
                os.symlink(outside, tx)
            with self.assertRaises(DesignError):
                transactions.update(ws.root, reqs, token)
            self.assertEqual(os.listdir(outside), [])


class Writers(unittest.TestCase):
    """D3 and requirement 10: every cooperating writer respects an unresolved record."""

    def test_writers_refuse_documents_held_by_an_unresolved_update(self):
        with Workspace() as ws:
            docs, _ = build(ws)
            reqs, token = listing(ws)
            self.assertEqual(run(ws, rb_args(reqs, token), fault="after-replace:1").returncode, 97)
            unlock(ws)
            now = snapshot(ws, docs)
            code, _, err = cmd(ws.root, "index")
            self.assertEqual(code, 2)
            self.assertIn("E16", err)
            code, _, err = cmd(ws.root, "new", "feature", "--name", "Another one")
            self.assertEqual(code, 2)
            self.assertIn("E16", err)
            code, _, err = cmd(ws.root, *rb_args([(docs[1], sha(now[docs[1]]))]))
            self.assertEqual(code, 2)
            self.assertIn("E16", err)
            for op in ("refresh", "insert", "remove-block", "reconcile"):
                r, _ = request(ws, op=op, path=docs[1], text=ws.text(docs[1]), at=0, line=0, diagram_id="FD-0001-D1",
                               action="discard")
                self.assertFalse(r["ok"], op)
                self.assertIn("E16", r["error"]["message"])
            r, code = request(ws, op="blocks", path=docs[1], text=ws.text(docs[1]))
            self.assertTrue(r["ok"])                                          # reading is still possible
            self.assertEqual(snapshot(ws, docs), now)
            rec = only_record(ws)
            self.assertTrue(transactions.resolve(ws.root, rec["id"], "complete", rec["token"])["ok"])
            self.assertEqual(cmd(ws.root, "index")[0], 0)

    def test_the_lock_can_be_taken_again_in_the_same_process_only(self):
        with Workspace() as ws:
            with registry.lock(ws.root):
                with registry.lock(ws.root):
                    self.assertTrue(registry.holds_lock(ws.root))
                self.assertTrue((ws.root / registry.LOCK).exists())
            self.assertFalse((ws.root / registry.LOCK).exists())
            self.assertFalse(registry.holds_lock(ws.root))

    def test_every_writer_takes_the_lock_and_writes_nothing_while_another_holds_it(self):
        """D3 audit: each design-tool command that writes is refused (E12) while the lock is held."""
        with Workspace() as ws:
            docs, src = build(ws, 2)
            reqs, token = listing(ws)
            text = ws.text(docs[0]).replace("Existing step", "Hand edit", 1)            # a conflict to reconcile
            (ws.root / docs[0]).write_bytes(text.encode("utf-8"))
            line = next(i for i, l in enumerate(text.splitlines()) if l.startswith("<!-- diagram:start")) + 1
            code, out, _ = cmd(ws.root, "reconcile", "--file", docs[0], "--line", str(line), "--discard")
            token_r = out.strip().split()[-1]
            (ws.root / registry.LOCK).write_text('{"pid": 1, "host": "another-computer", "time": 0}', encoding="utf-8")
            tree = lambda: {str(p): p.read_bytes() for p in ws.root.rglob("*") if p.is_file() and ".git" not in p.parts}
            before = tree()
            writers = [["index"], ["new", "feature", "--name", "Locked out"], ["new", "diagram", "--feature", "FD-0001", "--title", "Locked"],
                       ["registry", "relink", "FD-0001-D1", "--title", "Renamed"], ["registry", "retire", "FD-0001-D1", "--confirm"],
                       ["reconcile", "--file", docs[0], "--line", str(line), "--discard", "--confirm", token_r],
                       rb_args(reqs[1:], None)]
            for argv in writers:
                with self.subTest(command=argv[0:2]):
                    code, out, err = cmd(ws.root, *argv)
                    self.assertEqual(code, 2, out + err)
                    self.assertIn("E12", err)
                    self.assertEqual(tree(), before)

    def test_a_liveness_check_never_leaves_the_lock_behind(self):
        """Found in a GUI run: a status check had the lock file open as the writer finished; Windows
        refused the writer's delete and the stale file then refused every command (E12)."""
        import threading
        with Workspace() as ws:
            lock = ws.root / registry.LOCK
            opened = threading.Event()

            def probe():
                while not lock.exists():
                    time.sleep(0.005)
                fd = os.open(lock, os.O_RDWR)          # what a liveness check does
                opened.set()
                time.sleep(0.6)
                os.close(fd)
            t = threading.Thread(target=probe)
            t.start()
            with registry.lock(ws.root):
                opened.wait(5)
            t.join()
            self.assertFalse(lock.exists())
            self.assertFalse(transactions._other_holds_lock(ws.root))
            with registry.lock(ws.root):                # the next command is not refused
                pass

    def test_index_runs_under_the_registry_lock(self):
        with Workspace() as ws:
            build(ws, 1)
            (ws.root / registry.LOCK).write_text('{"pid": 1, "host": "elsewhere", "time": 0}', encoding="utf-8")
            code, _, err = cmd(ws.root, "index")
            self.assertEqual(code, 2)
            self.assertIn("E12", err)


class Api(unittest.TestCase):
    def test_affected_and_transactions_are_read_only(self):
        with Workspace() as ws:
            docs, _ = build(ws)
            reqs, token = listing(ws)
            self.assertEqual(run(ws, rb_args(reqs, token), fault="after-replace:2").returncode, 97)
            tree = {str(p): p.read_bytes() for p in ws.root.rglob("*") if p.is_file() and ".git" not in p.parts}
            r, code = request(ws, op="transactions")
            self.assertEqual((code, len(r["records"])), (0, 1))
            self.assertEqual([f["state"] for f in r["records"][0]["files"]], ["updated", "updated", "original"])
            r, code = request(ws, op="affected")
            self.assertEqual(code, 0)
            self.assertTrue(all(d["excluded"] for d in r["documents"]))
            self.assertEqual({str(p): p.read_bytes() for p in ws.root.rglob("*") if p.is_file() and ".git" not in p.parts},
                             tree)
            r, code = request(ws, op="affected", window="../x")
            self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main()
