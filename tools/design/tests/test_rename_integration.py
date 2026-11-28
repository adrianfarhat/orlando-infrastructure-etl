"""T-97 PR B2b-2b: the design-tooling side of Feature Designer's rename integration.

- `registry adopt-moves --sha256` (the checksum taken before VS Code renamed a source);
- `registry move-back` (mode `restore`, "Move the files back"): sources renamed while the registry
  still names their old paths are renamed back by the tooling, as a recorded version 2 move with
  renames only; the registry is never written. Validation (identity, unchanged bytes, the old path
  free, case-only through the intermediate path, links, held paths, open windows, Git,
  docs/architecture/), record validation, and crash injection at every boundary through the real
  commands in their own processes;
- the read-only designer operations `rename-preview` (the pre-rename snapshot), `move-plan` mode
  restore, and `transactions` with `cleanup`.
Testing runs on Windows only, as for B2b-2a."""

import json
import os
import shutil
import subprocess
import sys
import unittest

from tools.design import designer_api, moves, registry, transactions
from tools.design.tests.test_design import REPO_ROOT, Workspace, cmd
from tools.design.tests.test_move_engine import _upper_name, rewrite_journal, setup_sources
from tools.design.tests.test_moves import (DEST, cli_resolve, cli_status, entries_without_path, externally_move,
                                           junction, paths, registry_problems, token_of, tree, unlock, wait_released,
                                           with_block)
from tools.design.tests.test_transactions import OpenElsewhere, run, stop

sha = transactions._sha


def back_args(pairs, shas=None):
    """`registry move-back` for (now, registered) pairs (and their checksums)."""
    args = ["registry", "move-back"]
    for i, (now, to) in enumerate(pairs):
        args += ["--from", now, "--to", to] + (["--sha256", shas[i]] if shas else [])
    return args


def adopt_sha_args(triples):
    args = ["registry", "adopt-moves"]
    for old, new, h in triples:
        args += ["--from", old, "--to", new, "--sha256", h]
    return args


def preview_of(ws, moves_, window=None):
    req = {"version": 1, "op": "rename-preview", "moves": [{"from": a, "to": b} for a, b in moves_]}
    if window is not None:
        req["window"] = window
    r, code = designer_api.handle(ws.root, req)
    assert code == 0, r
    return r


def renamed(ws, n=2, case_only=()):
    """n registered sources, renamed by "another program" (VS Code, Git): the registry still names the
    old paths. Returns [(id, old, new, sha)]."""
    made = setup_sources(ws, n)
    out = []
    for i, m in enumerate(made):
        h = sha((ws.root / m.path).read_bytes())
        new = _upper_name(m.path) if i in case_only else f"{DEST}/{m.path.rsplit('/', 1)[1]}"
        externally_move(ws, m.path, new)
        out.append((m.diagram_id, m.path, new, h))
    return out


class AdoptWithChecksum(unittest.TestCase):
    def test_the_checksum_from_before_the_rename_is_bound_and_checked(self):
        with Workspace() as ws:
            items = renamed(ws, 2)
            others, top = entries_without_path(ws)
            triples = [(old, new, h) for _id, old, new, h in items]
            code, out, err = cmd(ws.root, *adopt_sha_args(triples))
            self.assertEqual(code, 1, out + err)
            code, out, err = cmd(ws.root, *adopt_sha_args(triples), "--confirm", token_of(out))
            self.assertEqual(code, 0, out + err)
            self.assertEqual(paths(ws), {i: new for i, _o, new, _h in items})
            self.assertEqual(entries_without_path(ws), (others, top))        # ID, owner, title, category unchanged
            self.assertEqual(registry_problems(ws), [])

    def test_a_file_changed_by_the_rename_is_refused_and_nothing_changes(self):
        with Workspace() as ws:
            items = renamed(ws, 2)
            (ws.root / items[1][2]).write_bytes((ws.root / items[1][2]).read_bytes() + b"\nedited while moving\n")
            before = tree(ws)
            triples = [(old, new, h) for _id, old, new, h in items]
            code, out, err = cmd(ws.root, *adopt_sha_args(triples))
            self.assertEqual(code, 2, out + err)
            self.assertIn("does not have the content it had before the rename", err)
            self.assertEqual(tree(ws), before)
            # the unchanged one alone can be adopted (Feature Designer offers exactly that)
            code, out, err = cmd(ws.root, *adopt_sha_args(triples[:1]))
            self.assertEqual(code, 1, out + err)
            self.assertEqual(cmd(ws.root, *adopt_sha_args(triples[:1]), "--confirm", token_of(out))[0], 0)
            self.assertEqual(paths(ws)[items[0][0]], items[0][2])
            self.assertEqual(paths(ws)[items[1][0]], items[1][1])               # still E6

    def test_malformed_checksums_are_usage_errors(self):
        with Workspace() as ws:
            items = renamed(ws, 1)
            _id, old, new, h = items[0]
            before = tree(ws)
            for extra in (["--sha256", h.upper()], ["--sha256", "abc"], ["--sha256", h, "--sha256", h]):
                with self.subTest(extra=extra):
                    code, out, err = cmd(ws.root, "registry", "adopt-moves", "--from", old, "--to", new, *extra)
                    self.assertEqual(code, 2, out + err)
                    self.assertTrue("--sha256" in err, err)
            self.assertEqual(tree(ws), before)

    def test_the_json_plan_carries_the_checksum_and_the_cli_executes_it(self):
        with Workspace() as ws:
            items = renamed(ws, 1)
            _id, old, new, h = items[0]
            r, code = designer_api.handle(ws.root, {"version": 1, "op": "move-plan", "mode": "adopt",
                                                    "moves": [{"from": old, "to": new, "sha256": h}]})
            self.assertTrue(r["possible"], r)
            code, out, err = cmd(ws.root, *adopt_sha_args([(old, new, h)]), "--confirm", r["token"], "--json")
            self.assertEqual(code, 0, out + err)
            result = json.loads(out)
            self.assertEqual(result["renames"], [{"diagram_id": _id, "from": old, "to": new}])
            self.assertEqual(result["index"], {"regenerated": True, "problem": ""})


class MoveBack(unittest.TestCase):
    def test_a9_move_back_restores_the_old_paths_and_leaves_the_registry_byte_identical(self):
        with Workspace() as ws:
            items = renamed(ws, 2)
            reg = (ws.root / registry.REGISTRY).read_bytes()
            pairs = [(new, old) for _id, old, new, _h in items]
            code, out, err = cmd(ws.root, *back_args(pairs, [h for *_x, h in items]))
            self.assertEqual(code, 1, out + err)
            self.assertIn("registry move-back", out)
            self.assertIn("The registry is not changed", out)
            code, out, err = cmd(ws.root, *back_args(pairs, [h for *_x, h in items]), "--confirm", token_of(out))
            self.assertEqual(code, 0, out + err)
            self.assertIn("moved back", out)
            for _id, old, new, h in items:
                self.assertEqual(transactions._entry_sha(ws.root, old), h)
                self.assertIsNone(transactions._entry_sha(ws.root, new))
            self.assertEqual((ws.root / registry.REGISTRY).read_bytes(), reg)
            self.assertEqual(registry_problems(ws), [])
            self.assertEqual(transactions.status(ws.root), [])
            self.assertEqual(cmd(ws.root, "index", "--check")[0], 0)

    def test_move_back_by_id_and_case_only_through_the_intermediate_path(self):
        with Workspace() as ws:
            items = renamed(ws, 1, case_only=(0,))
            did, old, new, h = items[0]
            p = moves.plan(ws.root, "restore", [(new, did, h)])
            self.assertEqual(p.problems, [])
            self.assertEqual(p.renames[0]["to"], old)
            self.assertIsNotNone(p.renames[0]["via"])
            self.assertEqual(cmd(ws.root, *back_args([(new, did)]), "--confirm", p.token)[0], 0)
            self.assertEqual(os.listdir(ws.root / old.rsplit("/", 1)[0]).count(old.rsplit("/", 1)[1]), 1)
            self.assertEqual(cmd(ws.root, "check")[0], 0)

    def test_refusals_change_nothing(self):
        with Workspace() as ws:
            items = renamed(ws, 2)
            did, old, new, h = items[0]
            cases = {}
            def refused(name, args, needle, prepare=None, undo=None):
                with self.subTest(name=name):
                    if prepare:
                        prepare()
                    before = tree(ws)
                    code, out, err = cmd(ws.root, *args)
                    self.assertEqual(code, 2, out + err)
                    self.assertIn(needle, err)
                    self.assertEqual(tree(ws), before)
                    if undo:
                        undo()
            refused("old path taken", back_args([(new, old)]), "the old path is not free",
                    lambda: (ws.root / old).write_bytes(b"someone else's file\n"), lambda: (ws.root / old).unlink())
            refused("old path taken ignoring case", back_args([(new, old)]), "the old path is not free",
                    lambda: (ws.root / _upper_name(old)).write_bytes(b"x\n"), lambda: (ws.root / _upper_name(old)).unlink())
            refused("changed since the rename", back_args([(new, old)], ["0" * 64]), "does not have the content it had")
            good = (ws.root / new).read_bytes()
            refused("another identity", back_args([(new, old)]), "does not hold",
                    lambda: (ws.root / new).write_bytes(good.replace(did.encode(), b"FD-0001-D9")),
                    lambda: (ws.root / new).write_bytes(good))
            refused("not registered", back_args([(new, "FD-0009-D1")]), "not a registered diagram")
            refused("already there", back_args([(old, old)]), "already at its registered path")
            refused("into docs/architecture", back_args([(new, "AD-0011")]), "technical-lead")
            refused("outside the approved folders", back_args([("designs/features/x.md", old)]),
                    "not a feature-owned diagram source")
            copy = "designs/features/second/diagrams/copy.md"
            refused("ambiguous identity", back_args([(new, old)]), "is at 2 unregistered paths",
                    lambda: ((ws.root / copy).parent.mkdir(parents=True, exist_ok=True),
                             shutil.copyfile(ws.root / new, ws.root / copy)),
                    lambda: (ws.root / copy).unlink())
            w = OpenElsewhere.window(None, ws, [new], age=3600.0)              # C3: a window that stopped responding
            refused("open in a Feature Designer window", back_args([(new, old)]), "is open in a VS Code window")
            w.unlink()
            (ws.root / ".git" / "MERGE_HEAD").write_bytes(b"")                  # C4
            refused("Git operation", back_args([(new, old)]), "Git operation is in progress")
            (ws.root / ".git" / "MERGE_HEAD").unlink()
            code, out, err = cmd(ws.root, *back_args([(new, old)]))
            self.assertEqual(code, 1, out + err)

    def test_links_and_junctions_are_refused(self):
        with Workspace() as ws:
            items = renamed(ws, 1)
            did, old, new, h = items[0]
            real = ws.root / "designs/features/elsewhere"
            real.mkdir(parents=True)
            shutil.move(str(ws.root / new.rsplit("/", 1)[0]), str(real / "diagrams"))
            junction(real / "diagrams", ws.root / new.rsplit("/", 1)[0])
            before = tree(ws)
            code, out, err = cmd(ws.root, *back_args([(new, old)]))
            self.assertEqual(code, 2, out + err)
            self.assertIn("A7", err)
            self.assertEqual(tree(ws), before)

    def test_a_held_path_or_an_unresolved_record_refuses_the_move_back(self):
        with Workspace() as ws:
            items = renamed(ws, 2)
            # an interrupted adoption of the second one holds the registry
            _i2, old2, new2, h2 = items[1]
            p = moves.plan(ws.root, "adopt", [(old2, new2, h2)])
            r = run(ws, [*adopt_sha_args([(old2, new2, h2)]), "--confirm", p.token], fault="move-after-prepare")
            self.assertEqual(r.returncode, 97)
            unlock(ws)
            did, old, new, h = items[0]
            code, out, err = cmd(ws.root, *back_args([(new, old)]))
            self.assertEqual(code, 2, out + err)
            self.assertIn("registry move is unresolved", err)

    def test_the_token_binds_the_bytes_and_the_registry(self):
        with Workspace() as ws:
            items = renamed(ws, 1)
            did, old, new, h = items[0]
            tok = moves.plan(ws.root, "restore", [(new, old)]).token
            (ws.root / new).write_bytes((ws.root / new).read_bytes() + b"\n")
            code, out, err = cmd(ws.root, *back_args([(new, old)]), "--confirm", tok)
            self.assertEqual(code, 2, out + err)
            self.assertIn("changed since the move was planned", err)
            self.assertEqual(transactions._entry_sha(ws.root, old), None)


class MoveBackRecords(unittest.TestCase):
    def prepared(self, ws):
        items = renamed(ws, 1)
        did, old, new, h = items[0]
        p = moves.plan(ws.root, "restore", [(new, old)])
        r = run(ws, [*back_args([(new, old)]), "--confirm", p.token], fault="move-after-prepare")
        self.assertEqual(r.returncode, 97)
        wait_released(ws)
        unlock(ws)
        (rec,) = transactions.records(ws.root)
        return rec, items[0]

    def test_a_move_back_record_has_renames_only_and_validates(self):
        with Workspace() as ws:
            rec, _ = self.prepared(ws)
            self.assertEqual(rec.problem, "")
            self.assertTrue(rec.restores)
            self.assertIsNone(rec.registry_op)
            self.assertEqual(sorted(os.listdir(rec.folder)), ["journal.json"])
            self.assertEqual(rec.data["registry_sha"], sha((ws.root / registry.REGISTRY).read_bytes()))
            d = transactions.describe(ws.root, rec, live=False)
            self.assertEqual(d["mode"], "restore")
            self.assertEqual(d["files"][-1]["state"], "unchanged")
            self.assertTrue(d["complete"]["possible"] and d["undo"]["possible"])
            self.assertIn("no", d["abandon"]["effect"].lower())

    def test_damaged_move_back_records_are_never_used(self):
        def add_registry_op(data):
            data["ops"].append({"kind": "registry", "path": registry.REGISTRY, "before_sha": "0" * 64,
                                "after_sha": "1" * 64, "orig": "registry.orig", "new": "registry.new"})
        damage = {
            "a registry operation": add_registry_op,
            "no registry revision": lambda d: d.pop("registry_sha"),
            "a malformed registry revision": lambda d: d.__setitem__("registry_sha", "x"),
            "observed renames": lambda d: d["ops"][0].__setitem__("observed", True),
            "no operations": lambda d: d.__setitem__("ops", []),
        }
        for name, change in damage.items():
            with self.subTest(name=name), Workspace() as ws:
                rec, _ = self.prepared(ws)
                rewrite_journal(rec.folder, change)
                (bad,) = transactions.records(ws.root)
                self.assertTrue(bad.problem, name)
                self.assertFalse(transactions.describe(ws.root, bad, live=False)["complete"]["possible"])
        with Workspace() as ws:                                                # an extra file in the folder
            rec, _ = self.prepared(ws)
            (rec.folder / "registry.orig").write_bytes(b"x")
            self.assertIn("unexpected files", transactions.records(ws.root)[0].problem)

    def test_complete_is_refused_when_the_registry_changed_undo_is_not(self):
        with Workspace() as ws:
            rec, (did, old, new, h) = self.prepared(ws)
            reg = ws.root / registry.REGISTRY
            original = reg.read_bytes()
            reg.write_bytes(original + b"# changed by hand\n")
            d = transactions.describe(ws.root, rec, live=False)
            self.assertEqual(d["files"][-1]["state"], "changed")
            self.assertFalse(d["complete"]["possible"])
            self.assertIn("registry changed since this move back was prepared", d["complete"]["reason"])
            r, _ = cli_resolve(ws, "undo")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("back where it was found", json.loads(r.stdout)["message"])
            self.assertEqual(transactions._entry_sha(ws.root, new), h)
            self.assertEqual(reg.read_bytes(), original + b"# changed by hand\n")     # never written

    def test_status_and_check_report_it(self):
        with Workspace() as ws:
            rec, (did, old, new, h) = self.prepared(ws)
            code, out, err = cmd(ws.root, "transaction", "status")
            self.assertEqual(code, 1)
            self.assertIn("tool-initiated move back", out)
            self.assertTrue(any("registry move was interrupted" in p for p in registry_problems(ws)))
            r, code = designer_api.handle(ws.root, {"version": 1, "op": "transactions"})
            self.assertEqual(r["records"][0]["mode"], "restore")
            self.assertEqual(r["cleanup"], [])


S_NOTHING = ["moves-after-lock", "moves-before-prepare", "move-before-journal", "move-after-journal"]
S_COMMIT = ["move-after-prepare", "move-after-committing-mark", "move-before-rename:1", "move-temp:1",
            "move-after-rename:1", "move-before-rename:2", "move-after-rename:2", "move-before-committed-mark"]
S_DONE = ["move-after-committed-mark", "after-done-rename", "during-cleanup:1"]


class MoveBackCrashes(unittest.TestCase):
    """`registry move-back` in its own process, ended at every boundary; recovery through the
    `transaction` commands in their own processes. A batch: one case-only move back (through its
    intermediate path) and one across folders. The registry is never written at any point."""

    def setup(self, ws):
        items = renamed(ws, 2, case_only=(0,))
        pairs = [(new, old) for _id, old, new, _h in items]
        shas = [h for *_x, h in items]
        p = moves.plan(ws.root, "restore", [(a, b, h) for (a, b), h in zip(pairs, shas)])
        assert not p.problems, p.problems
        assert p.renames[0]["via"] is not None or p.renames[1]["via"] is not None
        return pairs, shas, p

    def where(self, ws, p):
        return [transactions.rename_state(ws.root, dict(r, observed=False)) for r in p.renames]

    def assert_consistent(self, ws, p):
        self.assertTrue(all(s in ("old", "new", "temp") for s in self.where(ws, p)), self.where(ws, p))
        self.assertEqual((ws.root / registry.REGISTRY).read_bytes(), p.before)     # never written

    def crash(self, ws, pairs, shas, p, point, mode=None):
        r = run(ws, [*back_args(pairs, shas), "--confirm", p.token], fault=point, mode=mode)
        self.assertEqual(r.returncode, 97, r.stdout + r.stderr)

    def test_before_the_record_exists_nothing_is_touched(self):
        for point in S_NOTHING:
            with self.subTest(point=point), Workspace() as ws:
                pairs, shas, p = self.setup(ws)
                before = {k: v for k, v in tree(ws).items() if not k.startswith(transactions.TX_ROOT)}
                self.crash(ws, pairs, shas, p, point)
                wait_released(ws)
                unlock(ws)
                self.assertEqual(self.where(ws, p), ["old", "old"])           # "old" = where they were found
                self.assertEqual(cli_status(ws), [])
                self.assertEqual({k: v for k, v in tree(ws).items() if not k.startswith(transactions.TX_ROOT)}, before)

    def test_during_the_move_back_then_complete_then_complete_again(self):
        for point in S_COMMIT:
            with self.subTest(point=point), Workspace() as ws:
                pairs, shas, p = self.setup(ws)
                self.crash(ws, pairs, shas, p, point)
                self.assert_consistent(ws, p)
                r, rec = cli_resolve(ws, "complete")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.where(ws, p), ["new", "new"])           # "new" = the registered paths
                self.assertEqual((ws.root / registry.REGISTRY).read_bytes(), p.before)
                again = run(ws, ["transaction", "complete", rec["id"], "--confirm", rec["token"], "--json"])
                self.assertEqual(again.returncode, 0)
                self.assertTrue(json.loads(again.stdout)["already"])
                self.assertEqual(registry_problems(ws), [])

    def test_during_the_move_back_then_undo(self):
        for point in S_COMMIT:
            with self.subTest(point=point), Workspace() as ws:
                pairs, shas, p = self.setup(ws)
                self.crash(ws, pairs, shas, p, point)
                r, _ = cli_resolve(ws, "undo")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.where(ws, p), ["old", "old"])
                self.assertEqual((ws.root / registry.REGISTRY).read_bytes(), p.before)
                self.assertEqual(len([x for x in registry_problems(ws) if "(E6)" in x]), 2)   # moved again, as found

    def test_after_it_was_verified_it_counts_as_done(self):
        for point in S_DONE:
            with self.subTest(point=point), Workspace() as ws:
                pairs, shas, p = self.setup(ws)
                self.crash(ws, pairs, shas, p, point)
                self.assertEqual(self.where(ws, p), ["new", "new"])
                self.assertEqual(cli_status(ws), [])
                unlock(ws)
                self.assertEqual(cmd(ws.root, "index")[0], 0)
                self.assertEqual(registry_problems(ws), [])

    def test_an_interrupted_complete_and_undo_are_repeated(self):
        for action, points in (("complete", ["move-complete-after-mark", "move-complete-temp:1", "move-complete-after:1",
                                             "move-complete-after:2"]),
                               ("undo", ["move-undo-after-mark", "move-undo-after:2", "move-undo-temp:1",
                                         "move-undo-after:1"])):
            for point in points:
                with self.subTest(action=action, point=point), Workspace() as ws:
                    pairs, shas, p = self.setup(ws)
                    self.crash(ws, pairs, shas, p, "move-before-rename:1" if action == "complete" else
                               "move-before-committed-mark")
                    recs = cli_status(ws)
                    r = run(ws, ["transaction", action, recs[0]["id"], "--confirm", recs[0]["token"]], fault=point)
                    self.assertEqual(r.returncode, 97, r.stdout + r.stderr)
                    self.assert_consistent(ws, p)
                    r, _ = cli_resolve(ws, action)
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                    self.assertEqual(self.where(ws, p), ["new", "new"] if action == "complete" else ["old", "old"])

    def test_termination_from_outside(self):
        for point in ("move-temp:1", "move-after-rename:1", "move-before-committed-mark"):
            with self.subTest(point=point), Workspace() as ws:
                pairs, shas, p = self.setup(ws)
                env = {k: v for k, v in os.environ.items() if not k.startswith("DESIGN_TEST_FAULT")}
                env.update(DESIGN_TEST_FAULT=point, DESIGN_TEST_FAULT_ROOT=str(ws.root.resolve()),
                           DESIGN_TEST_FAULT_MODE="sleep")
                proc = subprocess.Popen([sys.executable, "-B", "-m", "tools.design", *back_args(pairs, shas), "--confirm",
                                         p.token, "--root", str(ws.root)], cwd=REPO_ROOT, env=env,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertIn(b"FAULT", proc.stderr.readline())
                stop(proc, ws)
                self.assert_consistent(ws, p)
                r, _ = cli_resolve(ws, "complete")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.where(ws, p), ["new", "new"])

    def test_a_file_changed_after_the_interruption_is_left_alone(self):
        with Workspace() as ws:
            pairs, shas, p = self.setup(ws)
            self.crash(ws, pairs, shas, p, "move-after-rename:1")
            second = p.renames[1]
            edited = (ws.root / second["from"]).read_bytes() + b"\nedited after the interruption\n"
            (ws.root / second["from"]).write_bytes(edited)
            (rec,) = cli_status(ws)
            self.assertEqual(rec["files"][1]["state"], "changed")
            r, _ = cli_resolve(ws, "complete")
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("partly done", json.loads(r.stdout)["message"])
            self.assertEqual((ws.root / second["from"]).read_bytes(), edited)    # never overwritten or moved


class RenamePreview(unittest.TestCase):
    def test_a_single_source_and_its_checksum_before_the_rename(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            doc = with_block(ws, made[0])
            new = made[0].path.replace(".md", "-renamed.md")
            before = tree(ws)
            r = preview_of(ws, [(made[0].path, new)])
            self.assertEqual(tree(ws), before)                                  # read only
            (s,) = r["sources"]
            self.assertEqual((s["diagram_id"], s["from"], s["to"], s["problem"]), (made[0].diagram_id, made[0].path, new, ""))
            self.assertEqual(s["sha256"], sha((ws.root / made[0].path).read_bytes()))
            self.assertEqual(s["format"], "mermaid-md")
            self.assertEqual(r["registry_sha"], sha((ws.root / registry.REGISTRY).read_bytes()))
            self.assertTrue(any(x.startswith(doc) for x in r["references"][made[0].diagram_id]))
            self.assertEqual((r["architecture"], r["held"], r["warnings"]), ([], [], []))

    def test_folders_are_expanded_diagrams_folders_and_parent_feature_folders(self):
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            folder = made[0].path.rsplit("/", 1)[0]                              # designs/features/diagrams
            r = preview_of(ws, [(folder, "designs/features/moved/diagrams")])
            self.assertEqual(sorted(s["to"] for s in r["sources"]),
                             sorted(f"designs/features/moved/diagrams/{m.path.rsplit('/', 1)[1]}" for m in made))
            self.assertTrue(all(s["problem"] == "" for s in r["sources"]))
            r = preview_of(ws, [("designs/features", "designs/renamed")])        # out of the approved folders
            self.assertEqual(len(r["sources"]), 2)
            self.assertTrue(all("not a feature-owned diagram source" in s["problem"] for s in r["sources"]))
            r = preview_of(ws, [("designs/features/unrelated.md", "designs/features/other.md")])
            self.assertEqual(r["sources"], [])

    def test_architecture_sources_and_paths_give_the_g5_notice_only(self):
        with Workspace() as ws:
            setup_sources(ws, 1)
            r = preview_of(ws, [("docs/architecture/diagrams", "docs/architecture/pictures")])
            self.assertEqual(r["sources"], [])
            self.assertTrue(r["architecture"])
            r = preview_of(ws, [("designs/features/diagrams/x.md", "docs/architecture/diagrams/x.md")])
            self.assertTrue(r["architecture"])

    def test_collisions_links_and_hidden_names_are_warned(self):
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            a, b = made[0].path, made[1].path
            r = preview_of(ws, [(a, b)])                                         # onto another registered source
            self.assertIn("already exists", r["sources"][0]["problem"])
            r = preview_of(ws, [(a, f"{DEST}/x.md"), (b, f"{DEST}/X.md")])        # equal ignoring case
            self.assertIn("same path ignoring letter case", r["sources"][1]["problem"])
            r = preview_of(ws, [(a, "designs/features/.hidden/diagrams/a.md")])
            self.assertIn("hidden name", r["sources"][0]["problem"])
            r = preview_of(ws, [(a, _upper_name(a))])                            # case-only: the file itself
            self.assertEqual(r["sources"][0]["problem"], "")

    def test_held_paths_unsaved_windows_and_git_are_warned(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            w = OpenElsewhere.window(None, ws, [made[0].path], age=3600.0, name="00000000000000aa")
            r = preview_of(ws, [(made[0].path, f"{DEST}/a.md")])
            self.assertTrue(any("unsaved changes" in x and "saving it there" in x for x in r["warnings"]), r["warnings"])
            r = preview_of(ws, [(made[0].path, f"{DEST}/a.md")], window="00000000000000aa")   # this window itself
            self.assertFalse(any("unsaved changes" in x for x in r["warnings"]), r["warnings"])
            w.unlink()
            (ws.root / ".git" / "MERGE_HEAD").write_bytes(b"")
            r = preview_of(ws, [(made[0].path, f"{DEST}/a.md")])
            self.assertTrue(any("Git operation is in progress" in x for x in r["warnings"]), r["warnings"])
            (ws.root / ".git" / "MERGE_HEAD").unlink()
            # G9: a path held by an unresolved record
            items_old, items_new = made[0].path, f"{DEST}/a.md"
            externally_move(ws, items_old, items_new)
            p = moves.plan(ws.root, "adopt", [(items_old, items_new)])
            self.assertEqual(run(ws, ["registry", "adopt-moves", "--from", items_old, "--to", items_new, "--confirm",
                                      p.token], fault="move-after-prepare").returncode, 97)
            unlock(ws)
            r = preview_of(ws, [(DEST, "designs/features/again/diagrams")])
            self.assertTrue(r["held"] and r["held"][0]["record"].startswith("tx-"), r)
            self.assertTrue(any("registry move is unresolved" in x for x in r["warnings"]), r["warnings"])

    def test_malformed_requests(self):
        with Workspace() as ws:
            for req in ({"moves": []}, {"moves": [{"from": "a"}]}, {"moves": [{"from": "a", "to": "b", "x": 1}]},
                        {"moves": [{"from": "a", "to": "b"}], "window": "nothex"}, {"moves": "a"}):
                with self.subTest(req=req):
                    r, code = designer_api.handle(ws.root, {"version": 1, "op": "rename-preview", **req})
                    self.assertEqual(code, designer_api.EXIT_BAD, r)

    def test_move_plan_restore_through_the_designer_interface(self):
        with Workspace() as ws:
            items = renamed(ws, 1)
            did, old, new, h = items[0]
            r, code = designer_api.handle(ws.root, {"version": 1, "op": "move-plan", "mode": "restore",
                                                    "moves": [{"from": new, "to": old, "sha256": h}]})
            self.assertEqual(code, 0, r)
            self.assertTrue(r["possible"], r)
            self.assertEqual(r["registry"]["before_sha"], r["registry"]["after_sha"])
            self.assertEqual(r["renames"][0]["from"], new)
            r, code = designer_api.handle(ws.root, {"version": 1, "op": "move-plan", "mode": "nope", "moves": []})
            self.assertEqual(code, designer_api.EXIT_BAD)


if __name__ == "__main__":
    unittest.main()
