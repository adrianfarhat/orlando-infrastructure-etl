"""T-97 PR B2b-2a S2: `registry move`, `registry adopt-moves` and the read-only designer operations
`move-plan` and `moved` (decisions G1-G12; docs/architecture/diagram-library.md section 7.5).

Acceptance A2-A9 (command-line part), recovery R1-R5 through the real commands in their own
processes (ended at every boundary, also from outside), concurrency C2-C4, stale confirmation
tokens, malformed and ambiguous requests, and the S1 QA follow-ups. Testing runs on Windows only:
the POSIX rename path (link, then unlink) is exercised only through a simulated hard link."""

import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tools.design import designer_api, moves, ownership, registry, transactions
from tools.design.tests.test_design import REPO_ROOT, Workspace, cmd
from tools.design.tests.test_move_engine import _upper_name, drive, plan_for, setup_sources
from tools.design.tests.test_transactions import (OpenElsewhere, after, apply, build, listing, rb_args, request, run,
                                                  stop, unlock)
from tools.design.workspace import DesignError, new_feature

sha = transactions._sha
DEST = "designs/features/moved/diagrams"


# --------------------------------------------------------------------------- helpers

def tree(ws, mtimes=False):
    """Every file under the workspace (not .git), with its bytes (and modification time)."""
    out = {}
    for p in sorted(ws.root.rglob("*")):
        rel = p.relative_to(ws.root).as_posix()
        if rel == ".git" or rel.startswith(".git/"):
            continue
        if p.is_file():
            out[rel] = (p.read_bytes(), p.stat().st_mtime_ns) if mtimes else p.read_bytes()
        elif p.is_dir():
            out[rel + "/"] = b""
    return out


def token_of(out):
    m = re.search(r"--confirm (\w+)", out)
    assert m, out
    return m.group(1)


def move_args(pairs):
    return ["registry", "move", *[s for s, _ in pairs], *[a for _, d in pairs for a in ("--to", d)]]


def adopt_args(pairs):
    return ["registry", "adopt-moves", *[a for s, d in pairs for a in ("--from", s, "--to", d)]]


def preview(test, ws, args):
    code, out, err = cmd(ws.root, *args)
    test.assertEqual(code, 1, out + err)
    return token_of(out)


def entries_without_path(ws):
    """Every registry entry as plain data, without `path` (what a move must keep byte for byte)."""
    data = transactions._plain(registry._rt_yaml().load((ws.root / registry.REGISTRY).read_bytes().decode("utf-8")))
    return [{k: v for k, v in item.items() if k != "path"} for item in data["diagrams"]], \
           {k: v for k, v in data.items() if k != "diagrams"}


def paths(ws):
    """Feature-owned entries only (the copied architecture entries never move)."""
    return {e.diagram_id: e.path for e in registry.load(ws.root).entries if e.owner_kind == "feature"}


def registry_problems(ws):
    """`check`'s registry and transaction problems (link problems of moved sources are G6, reported)."""
    return [p.message for p in registry.problems(ws.root) + transactions.problems(ws.root)]


def externally_move(ws, src, dst):
    (ws.root / dst).parent.mkdir(parents=True, exist_ok=True)
    os.rename(ws.root / src, ws.root / dst)


def with_block(ws, made):
    """A feature document showing `made` in a current diagram block."""
    d = new_feature(ws.root, "Reader").path
    text = ws.text(d)
    r, code = request(ws, op="insert", path=d, text=text, at=after(text.split("\n"), "- **Desired outcome:**"),
                      diagram_id=made.diagram_id)
    assert code == 0, r
    (ws.root / d).write_bytes(apply(text, r).encode("utf-8"))
    code, out, err = cmd(ws.root, "index")
    assert code == 0, err
    return d


def wait_released(ws):
    for _ in range(100):
        if not transactions._other_holds_lock(ws.root):
            return
        time.sleep(0.1)


def cli_status(ws):
    wait_released(ws)
    r = run(ws, ["transaction", "status", "--json"])
    return json.loads(r.stdout.decode("utf-8"))["records"]


def cli_resolve(ws, action):
    recs = cli_status(ws)
    assert len(recs) == 1, recs
    r = run(ws, ["transaction", action, recs[0]["id"], "--confirm", recs[0]["token"], "--json"])
    return r, recs[0]


def junction(target, link):
    if sys.platform == "win32":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=True)
    else:
        os.symlink(target, link)


# --------------------------------------------------------------------------- acceptance

class ToolInitiatedMoves(unittest.TestCase):
    def test_a3_a_move_renames_the_files_and_only_the_registry_paths_change(self):
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            contents = {m.diagram_id: (ws.root / m.path).read_bytes() for m in made}
            others, top = entries_without_path(ws)
            pairs = [(made[0].diagram_id, f"{DEST}/"), (made[1].path, f"{DEST}/renamed.md")]
            code, out, err = cmd(ws.root, *move_args(pairs))
            self.assertEqual(code, 1, out + err)
            self.assertIn("Nothing was changed", out)
            self.assertFalse((ws.root / DEST).exists())                           # the preview writes nothing
            code, out, err = cmd(ws.root, *move_args(pairs), "--confirm", token_of(out))
            self.assertEqual(code, 0, out + err)
            new = paths(ws)
            self.assertEqual(new[made[0].diagram_id], f"{DEST}/{made[0].path.rsplit('/', 1)[1]}")
            self.assertEqual(new[made[1].diagram_id], f"{DEST}/renamed.md")
            for m in made:
                self.assertEqual((ws.root / new[m.diagram_id]).read_bytes(), contents[m.diagram_id])   # bytes kept
                self.assertFalse((ws.root / m.path).exists())
            self.assertEqual(entries_without_path(ws), (others, top))          # IDs, owners, titles, aliases kept
            self.assertTrue((ws.root / made[0].path).parent.is_dir())          # Q2: the old folder is kept
            self.assertEqual(transactions.status(ws.root), [])
            self.assertEqual(registry_problems(ws), [])
            self.assertEqual(cmd(ws.root, "index", "--check")[0], 0)             # G4: diagram-index regenerated

    def test_aliases_and_created_from_are_preserved(self):
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            p = ws.root / registry.REGISTRY
            text = p.read_bytes().decode("utf-8")
            item = text.index(f"diagram_id: {made[1].diagram_id}")
            seg = text[item:]
            seg = seg.replace("aliases: []", "aliases: [former-flow-two]", 1)
            seg = seg.replace("created_from:", f"created_from: {{diagram: {made[0].diagram_id}}}\n    # was:", 1)
            p.write_bytes((text[:item] + seg).encode("utf-8"))
            self.assertEqual(registry.load(ws.root).problems, [])
            before = entries_without_path(ws)
            tok = preview(self, ws, move_args([(made[1].diagram_id, f"{DEST}/")]))
            self.assertEqual(cmd(ws.root, *move_args([(made[1].diagram_id, f"{DEST}/")]), "--confirm", tok)[0], 0)
            self.assertEqual(entries_without_path(ws), before)
            self.assertIn("former-flow-two", registry.load(ws.root).by_id()[made[1].diagram_id].aliases)
            self.assertIn("# was:", p.read_bytes().decode("utf-8"))           # comments kept

    def test_a2_a_folder_move_moves_every_registered_source_in_one_record(self):
        with Workspace() as ws:
            made = setup_sources(ws, 3)
            folder = made[0].path.rsplit("/", 1)[0]
            args = move_args([(folder, DEST)])
            plan = moves.plan(ws.root, "move", [(folder, DEST)])
            self.assertEqual(len(plan.renames), 3)
            # one record holds all three: interrupt it after the second rename
            r = run(ws, [*args, "--confirm", plan.token], fault="move-after-rename:2")
            self.assertEqual(r.returncode, 97, r.stderr)
            recs = cli_status(ws)
            self.assertEqual(len(recs), 1)
            self.assertEqual(len(recs[0]["files"]), 4)                          # three renames and the registry
            r, _ = cli_resolve(ws, "complete")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(sorted(paths(ws).values()),
                             sorted(f"{DEST}/{m.path.rsplit('/', 1)[1]}" for m in made))
            self.assertTrue((ws.root / folder).is_dir())                         # never removed (Q2)

    def test_g8_a_folder_holding_anything_else_is_refused_and_nothing_is_touched(self):
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            folder = made[0].path.rsplit("/", 1)[0]
            cases = {"an unregistered file": lambda: (ws.root / folder / "notes.txt").write_bytes(b"mine\n"),
                     "another folder": lambda: (ws.root / folder / "sub").mkdir(),
                     "a retired entry's file": lambda: registry.retire(ws.root, made[1].diagram_id, True)}
            for name, make in cases.items():
                with self.subTest(name=name):
                    make()
                    before = tree(ws)
                    code, out, err = cmd(ws.root, *move_args([(folder, DEST)]))
                    self.assertEqual(code, 2, out + err)
                    self.assertIn("nothing was changed", err)
                    self.assertTrue("G8" in err or "retired" in err, err)
                    self.assertEqual(tree(ws), before)

    def test_a4_a_case_only_rename_gives_the_exact_new_case_and_a_clean_check(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            new = _upper_name(made[0].path)
            plan = moves.plan(ws.root, "move", [(made[0].path, new)])
            self.assertEqual(plan.problems, [])
            self.assertTrue(plan.renames[0]["via"].rsplit("/", 1)[1].startswith("."))
            code, out, err = cmd(ws.root, *move_args([(made[0].path, new)]), "--confirm", plan.token)
            self.assertEqual(code, 0, out + err)
            self.assertEqual(paths(ws)[made[0].diagram_id], new)
            self.assertIn(new.rsplit("/", 1)[1], os.listdir(ws.root / new.rsplit("/", 1)[0]))
            self.assertNotIn(made[0].path.rsplit("/", 1)[1], os.listdir(ws.root / new.rsplit("/", 1)[0]))
            self.assertEqual(registry_problems(ws), [])
            code, out, err = cmd(ws.root, "check")
            self.assertEqual(code, 0, out + err)                                # same folder: links still resolve

    def test_a5_collisions_are_refused_before_anything_is_written(self):
        with Workspace() as ws:
            made = setup_sources(ws, 3)
            occupied = f"{DEST}/occupied.md"
            (ws.root / DEST).mkdir(parents=True)
            (ws.root / occupied).write_bytes(b"unrelated\n")
            cases = {
                "an existing destination": [(made[0].diagram_id, occupied)],
                "an existing destination in other letter case": [(made[0].diagram_id, f"{DEST}/OCCUPIED.md")],
                "two equal destinations": [(made[0].diagram_id, f"{DEST}/same.md"), (made[1].diagram_id, f"{DEST}/same.md")],
                "destinations equal ignoring case": [(made[0].diagram_id, f"{DEST}/same.md"),
                                                     (made[1].diagram_id, f"{DEST}/SAME.md")],
                "another entry's registered path": [(made[0].diagram_id, made[2].path)],
                "swapped moves": [(made[0].diagram_id, made[1].path), (made[1].diagram_id, made[0].path)],
                "the same diagram twice": [(made[0].diagram_id, f"{DEST}/a.md"), (made[0].path, f"{DEST}/b.md")],
                "a folder that exists in other letter case": [(made[0].diagram_id, "designs/features/MOVED/diagrams/x.md")],
                "a destination outside diagrams/": [(made[0].diagram_id, "designs/features/x.md")],
                "a destination that is not .md": [(made[0].diagram_id, f"{DEST}/x.txt")],
                "a hidden destination name": [(made[0].diagram_id, f"{DEST}/.x.md")],
                "a hidden destination folder": [(made[0].diagram_id, "designs/features/x/.h/diagrams/a.md")],
                "a reserved device name": [(made[0].diagram_id, f"{DEST}/con.md")],
                "a reserved device folder": [(made[0].diagram_id, "designs/features/LPT1/diagrams/a.md")],
                "a destination outside the repository": [(made[0].diagram_id, "../x/diagrams/x.md")],
            }
            before = tree(ws)
            for name, pairs in cases.items():
                with self.subTest(name=name):
                    code, out, err = cmd(ws.root, *move_args(pairs))
                    self.assertEqual(code, 2, out + err)
                    self.assertIn("nothing was changed", err)
                    self.assertEqual(tree(ws), before)
                    with self.assertRaises(DesignError):
                        moves.execute(ws.root, "move", pairs, "0" * 16)
                    self.assertEqual(tree(ws), before)

    def test_overlapping_folder_moves_are_refused(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            new_feature(ws.root, "Other")
            other = ownership.new_diagram(ws.root, "FD-0002", "Other flow")
            fa, fb = made[0].path.rsplit("/", 1)[0], other.path.rsplit("/", 1)[0]
            for pairs in ([(fa, fa + "/inner/diagrams")], [(fa, DEST), (fb, fa)]):
                with self.subTest(pairs=pairs):
                    p = moves.plan(ws.root, "move", pairs)
                    self.assertTrue(any("into itself" in x or "overlap" in x or "old path" in x or "occupied" in x
                                        or "registered path" in x for x in p.problems), p.problems)

    def test_a6_architecture_sources_and_folders_are_never_moved(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            folder = ws.root / "docs/architecture/diagrams"
            folder.mkdir()
            (folder / "system-architecture_sequence_x.md").write_text(
                "---\ndiagram_id: AD-0015\ntitle: X\nowner_document: docs/architecture/system-architecture.md\n---\n\n"
                "```mermaid\nsequenceDiagram\n  A->>B: hi\n```\n", encoding="utf-8")
            registry.adopt(ws.root, "docs/architecture/diagrams/system-architecture_sequence_x.md", "sequence")
            arch = {p: p.read_bytes() for p in (ws.root / "docs/architecture").rglob("*") if p.is_file()}
            cases = [[("AD-0015", f"{DEST}/x.md")], [("AD-0006", f"{DEST}/x.md")],
                     [(made[0].diagram_id, "docs/architecture/diagrams/x.md")],
                     [("docs/architecture/diagrams", DEST)], [("docs/architecture/diagrams/system-architecture_sequence_x.md",
                                                               "docs/architecture/diagrams/y.md")]]
            reg = (ws.root / registry.REGISTRY).read_bytes()
            for pairs in cases:
                with self.subTest(pairs=pairs):
                    code, out, err = cmd(ws.root, *move_args(pairs))
                    self.assertEqual(code, 2, out + err)
                    self.assertTrue("G5" in err or "docs/architecture" in err, err)
            # a rename made by hand inside docs/architecture/ is never adopted (technical-lead's workflow)
            os.rename(folder / "system-architecture_sequence_x.md", folder / "system-architecture_sequence_y.md")
            m = moves.moved(ws.root)
            self.assertEqual([x["diagram_id"] for x in m["architecture"]], ["AD-0015"])
            self.assertIn("technical-lead", m["architecture"][0]["problem"])
            code, out, err = cmd(ws.root, *adopt_args([("AD-0015", "docs/architecture/diagrams/system-architecture_sequence_y.md")]))
            self.assertEqual(code, 2, out + err)
            self.assertEqual(cmd(ws.root, "registry", "adopt-moves")[0], 2)
            os.rename(folder / "system-architecture_sequence_y.md", folder / "system-architecture_sequence_x.md")
            self.assertEqual({p: p.read_bytes() for p in (ws.root / "docs/architecture").rglob("*") if p.is_file()}, arch)
            self.assertEqual((ws.root / registry.REGISTRY).read_bytes(), reg)

    def test_a7_links_and_junctions_are_refused(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            outside = Path(tempfile.mkdtemp(prefix="outside-"))
            try:
                junction(outside, ws.root / "designs/features/far")
                p = moves.plan(ws.root, "move", [(made[0].diagram_id, "designs/features/far/diagrams/x.md")])
                self.assertTrue(any("link or junction" in x for x in p.problems), p.problems)
                inside = ws.root / made[0].path.rsplit("/", 1)[0] / "sub"
                junction(outside, inside)                                    # a junction inside a folder to move
                p = moves.plan(ws.root, "move", [(made[0].path.rsplit("/", 1)[0], DEST)])
                self.assertTrue(any("link or junction" in x for x in p.problems), p.problems)
                os.rmdir(inside)
                # the source's own folder replaced by a junction (the moved item reached through a link)
                src_folder = ws.root / made[0].path.rsplit("/", 1)[0]
                real = ws.root / "designs/features/real-diagrams"
                os.rename(src_folder, real)
                junction(real, src_folder)
                p = moves.plan(ws.root, "move", [(made[0].diagram_id, f"{DEST}/x.md")])
                self.assertTrue(any("link or junction" in x for x in p.problems), p.problems)
                self.assertEqual(os.listdir(outside), [])
            finally:
                for link in (ws.root / "designs/features/far", ws.root / made[0].path.rsplit("/", 1)[0]):
                    if transactions._is_link(link):
                        os.rmdir(link)
                shutil.rmtree(outside, ignore_errors=True)

    def test_a9_move_back_restores_the_old_path_only_when_it_is_free(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            old = made[0].path
            new = f"{DEST}/{old.rsplit('/', 1)[1]}"
            externally_move(ws, old, new)                                     # VS Code moved it; adopted
            tok = preview(self, ws, adopt_args([(old, new)]))
            self.assertEqual(cmd(ws.root, *adopt_args([(old, new)]), "--confirm", tok)[0], 0)
            (ws.root / old).write_bytes(b"someone else's file\n")              # the old path is taken
            self.assertEqual(cmd(ws.root, *move_args([(made[0].diagram_id, old)]))[0], 2)
            (ws.root / old).unlink()
            tok = preview(self, ws, move_args([(made[0].diagram_id, old)]))      # Move back
            self.assertEqual(cmd(ws.root, *move_args([(made[0].diagram_id, old)]), "--confirm", tok)[0], 0)
            self.assertEqual(paths(ws)[made[0].diagram_id], old)
            self.assertEqual(registry_problems(ws), [])

    def test_relink_keeps_its_behaviour(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            new = f"{DEST}/{made[0].path.rsplit('/', 1)[1]}"
            externally_move(ws, made[0].path, new)
            problems = registry_problems(ws)
            self.assertTrue(any(f"registry relink {made[0].diagram_id} --path {new}` (E6)" in p for p in problems), problems)
            self.assertTrue(any("registry adopt-moves" in p for p in problems), problems)
            e = registry.relink(ws.root, made[0].diagram_id, path=new)
            self.assertEqual(e.path, new)
            self.assertEqual(registry_problems(ws), [])
            self.assertEqual(transactions.status(ws.root), [])                # relink writes no record

    def test_a_move_into_another_features_folder_keeps_the_owner_and_check_reports_only_links(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            other = new_feature(ws.root, "Other", "FD-0001", convert_parent=True)                  # a child feature in its own folder
            dest = posixpath.join(posixpath.dirname(other.path), "diagrams/")
            tok = preview(self, ws, move_args([(made[0].diagram_id, dest)]))
            self.assertEqual(cmd(ws.root, *move_args([(made[0].diagram_id, dest)]), "--confirm", tok)[0], 0)
            e = registry.load(ws.root).by_id()[made[0].diagram_id]
            self.assertEqual((e.owner_ref, e.path.startswith(dest)), ("FD-0001", True))
            self.assertEqual(registry_problems(ws), [])                       # identity consistent everywhere
            code, out, err = cmd(ws.root, "check")
            bad = [l for l in out.splitlines() if l.startswith("designs/") and "broken link" not in l]
            self.assertEqual(bad, [], out)                                    # only G6 link reports, if any

    def test_the_relative_links_a_move_breaks_are_reported_never_rewritten(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            data = (ws.root / made[0].path).read_bytes()
            plan = moves.plan(ws.root, "move", [(made[0].diagram_id, "designs/features/far/away/diagrams/x.md")])
            self.assertEqual(plan.problems, [])
            self.assertTrue(any("never rewritten (G6)" in w for w in plan.warnings), plan.warnings)
            moves.execute(ws.root, "move", [(made[0].diagram_id, "designs/features/far/away/diagrams/x.md")], plan.token)
            self.assertEqual((ws.root / "designs/features/far/away/diagrams/x.md").read_bytes(), data)


class ObservedMoves(unittest.TestCase):
    def test_a8_an_external_move_is_reported_as_e6_and_adopted(self):
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            moved_to = {}
            for m in made:
                moved_to[m.diagram_id] = f"{DEST}/{m.path.rsplit('/', 1)[1]}"
                externally_move(ws, m.path, moved_to[m.diagram_id])
            self.assertEqual(len([p for p in registry_problems(ws) if "(E6)" in p]), 2)
            found = moves.moved(ws.root)
            self.assertEqual(sorted((x["diagram_id"], x["to"], x["problem"]) for x in found["matches"]),
                             sorted((d, t, "") for d, t in moved_to.items()))
            others, top = entries_without_path(ws)
            code, out, err = cmd(ws.root, "registry", "adopt-moves")
            self.assertEqual(code, 1, out + err)
            code, out, err = cmd(ws.root, "registry", "adopt-moves", "--confirm", token_of(out))
            self.assertEqual(code, 0, out + err)
            self.assertEqual(paths(ws), moved_to)
            self.assertEqual(entries_without_path(ws), (others, top))
            self.assertEqual(registry_problems(ws), [])

    def test_a2_an_adopted_folder_rename_updates_every_entry(self):
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            folder = made[0].path.rsplit("/", 1)[0]
            new_feature(ws.root, "Target")
            target = "designs/features/target-folder/diagrams"
            (ws.root / target).parent.mkdir(parents=True)
            os.rename(ws.root / folder, ws.root / target)
            tok = preview(self, ws, adopt_args([(folder, target)]))
            self.assertEqual(cmd(ws.root, *adopt_args([(folder, target)]), "--confirm", tok)[0], 0)
            self.assertEqual(sorted(paths(ws)[m.diagram_id] for m in made),
                             sorted(f"{target}/{m.path.rsplit('/', 1)[1]}" for m in made))

    def test_a4_an_external_case_only_rename_is_adopted_with_the_exact_case(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            new = _upper_name(made[0].path)
            os.rename(ws.root / made[0].path, ws.root / new)
            tok = preview(self, ws, ["registry", "adopt-moves"])
            self.assertEqual(cmd(ws.root, "registry", "adopt-moves", "--confirm", tok)[0], 0)
            self.assertEqual(paths(ws)[made[0].diagram_id], new)
            self.assertEqual(cmd(ws.root, "check")[0], 0)

    def test_ambiguous_and_missing_sources_are_never_guessed(self):
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            a, b = f"{DEST}/a.md", f"designs/features/second/diagrams/b.md"
            externally_move(ws, made[0].path, a)
            (ws.root / b).parent.mkdir(parents=True)
            shutil.copyfile(ws.root / a, ws.root / b)                          # the ID at two unregistered paths
            (ws.root / made[1].path).unlink()                                  # E7: no candidate at all
            problems = registry_problems(ws)
            self.assertTrue(any("is at 2 unregistered paths" in p and a in p and b in p for p in problems), problems)
            found = moves.moved(ws.root)
            self.assertEqual([x["diagram_id"] for x in found["ambiguous"]], [made[0].diagram_id])
            self.assertEqual(found["ambiguous"][0]["candidates"], sorted([a, b]))
            self.assertEqual([x["diagram_id"] for x in found["missing"]], [made[1].diagram_id])
            before = tree(ws)
            code, out, err = cmd(ws.root, "registry", "adopt-moves")
            self.assertEqual(code, 2, out + err)
            self.assertIn("no moved source can be adopted", err)
            code, out, err = cmd(ws.root, *adopt_args([(made[0].diagram_id, a)]))   # explicit: still refused
            self.assertEqual(code, 2, out + err)
            self.assertIn("2 unregistered paths", err)
            self.assertEqual(tree(ws), before)

    def test_the_destination_identity_and_content_are_validated(self):
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            new = f"{DEST}/{made[0].path.rsplit('/', 1)[1]}"
            externally_move(ws, made[0].path, new)
            good = (ws.root / new).read_bytes()
            text = good.decode("utf-8")
            variants = {
                "another ID": text.replace(made[0].diagram_id, "FD-0001-D9"),
                "another owner": text.replace('feature_id: "FD-0001"', 'feature_id: "FD-0002"'),
                "two Mermaid blocks": text + "\n```mermaid\nflowchart LR\n  X --> Y\n```\n",
                "no Mermaid block closed": text.replace("```\n\n## What this", "\n\n## What this"),
            }
            for name, body in variants.items():
                with self.subTest(name=name):
                    (ws.root / new).write_bytes(body.encode("utf-8"))
                    p = moves.plan(ws.root, "adopt", [(made[0].path, new)])
                    self.assertTrue(p.problems, name)
                    self.assertEqual(p.renames, [])
            (ws.root / new).write_bytes(good)
            r, code = designer_api.handle(ws.root, {"version": 1, "op": "move-plan", "mode": "adopt",
                                                    "moves": [{"from": made[0].path, "to": new, "sha256": "0" * 64}]})
            self.assertEqual(code, 0, r)
            self.assertFalse(r["possible"])
            self.assertIn("does not have the content it had before the rename", " ".join(r["problems"]))
            r, code = designer_api.handle(ws.root, {"version": 1, "op": "move-plan", "mode": "adopt",
                                                    "moves": [{"from": made[0].path, "to": new, "sha256": sha(good)}]})
            self.assertTrue(r["possible"], r)
            # a source that is still at its registered path is not adopted (a copy is not a move)
            p = moves.plan(ws.root, "adopt", [(made[1].path, f"{DEST}/copy.md")])
            self.assertTrue(p.problems)

    def test_a_source_moved_into_a_hidden_folder_is_never_adopted(self):          # QA S2 M1
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            hidden = "designs/features/x/.h/diagrams/" + made[0].path.rsplit("/", 1)[1]
            externally_move(ws, made[0].path, hidden)
            p = moves.plan(ws.root, "adopt", [(made[0].path, hidden)])
            self.assertTrue(any("hidden name" in x for x in p.problems), p.problems)
            self.assertEqual(moves.plan(ws.root, "adopt", None).renames, [])   # not even found as a candidate

    def test_r1_an_interrupted_adoption_is_recoverable(self):
        points = ["move-after-prepare", "move-after-committing-mark", "move-before-registry", "move-after-registry",
                  "move-before-committed-mark"]
        for point in points:
            for action in ("complete", "undo"):
                with self.subTest(point=point, action=action), Workspace() as ws:
                    made = setup_sources(ws, 2)
                    for m in made:
                        externally_move(ws, m.path, f"{DEST}/{m.path.rsplit('/', 1)[1]}")
                    before = (ws.root / registry.REGISTRY).read_bytes()
                    plan = moves.plan(ws.root, "adopt", None)
                    r = run(ws, ["registry", "adopt-moves", "--confirm", plan.token], fault=point)
                    self.assertEqual(r.returncode, 97, r.stderr)
                    self.assertIn(sha((ws.root / registry.REGISTRY).read_bytes()), (sha(before), sha(plan.after)))
                    r, _ = cli_resolve(ws, action)
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                    want = plan.after if action == "complete" else before
                    self.assertEqual((ws.root / registry.REGISTRY).read_bytes(), want)
                    for x in plan.renames:                                    # the files stay where they were put
                        self.assertEqual(transactions._entry_sha(ws.root, x["to"]), x["sha"])
                    self.assertEqual(transactions.status(ws.root), [])


# --------------------------------------------------------------------------- tokens and requests

class Tokens(unittest.TestCase):
    def test_changes_between_planning_and_execution_refuse_the_move(self):
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            pairs = [(made[0].diagram_id, f"{DEST}/a.md")]
            changes = {
                "the source's bytes": lambda: (ws.root / made[0].path).write_bytes(
                    (ws.root / made[0].path).read_bytes() + b"\nedited\n"),
                "the registry": lambda: registry.relink(ws.root, made[1].diagram_id, title="Retitled"),
                "the destination folder": lambda: (ws.root / DEST).mkdir(parents=True),
                "the destination file": lambda: ((ws.root / DEST).mkdir(parents=True, exist_ok=True),
                                                 (ws.root / f"{DEST}/a.md").write_bytes(b"x\n")),
            }
            for name, change in changes.items():
                with self.subTest(name=name):
                    tok = moves.plan(ws.root, "move", pairs).token
                    change()
                    before = tree(ws)
                    code, out, err = cmd(ws.root, *move_args(pairs), "--confirm", tok)
                    self.assertEqual(code, 2, out + err)
                    self.assertIn("nothing was changed", err)
                    self.assertEqual(tree(ws), before)
                    self.assertEqual(transactions.status(ws.root), [])
                    if (ws.root / f"{DEST}/a.md").exists():
                        (ws.root / f"{DEST}/a.md").unlink()
            tok = moves.plan(ws.root, "move", pairs).token
            self.assertEqual(cmd(ws.root, *move_args(pairs), "--confirm", tok)[0], 0)   # a fresh token works

    def test_an_adoption_token_is_bound_to_the_destination_content(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            new = f"{DEST}/{made[0].path.rsplit('/', 1)[1]}"
            externally_move(ws, made[0].path, new)
            tok = moves.plan(ws.root, "adopt", None).token
            (ws.root / new).write_bytes((ws.root / new).read_bytes().replace(b"New step", b"Edited step"))
            code, out, err = cmd(ws.root, "registry", "adopt-moves", "--confirm", tok)
            self.assertEqual(code, 2, out + err)
            self.assertIn("changed since the move was planned", err)

    def test_a_wrong_token_changes_nothing(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            before = tree(ws)
            for tok in ("0" * 16, "nonsense"):
                code, out, err = cmd(ws.root, *move_args([(made[0].diagram_id, f"{DEST}/a.md")]), "--confirm", tok)
                self.assertEqual(code, 2)
            self.assertEqual(tree(ws), before)


class Requests(unittest.TestCase):
    def test_malformed_requests_are_refused(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            before = tree(ws)
            for args in (["registry", "move", made[0].diagram_id, "--to", "a", "--to", "b"],
                         ["registry", "move", "FD-0001-D7", "--to", f"{DEST}/x.md"],
                         ["registry", "move", "designs/features/nowhere.md", "--to", f"{DEST}/x.md"],
                         ["registry", "move", made[0].diagram_id, "--to", "C:/elsewhere/diagrams/x.md"],
                         ["registry", "move", made[0].diagram_id, "--to", made[0].path],
                         ["registry", "adopt-moves", "--from", made[0].path],
                         ["registry", "adopt-moves", "--from", made[0].path, "--to", f"{DEST}/x.md"],
                         ["registry", "move", "--to", f"{DEST}/x.md"]):
                with self.subTest(args=args):
                    code, out, err = cmd(ws.root, *args)
                    self.assertEqual(code, 2, out + err)
            self.assertEqual(tree(ws), before)
            for bad in ({"op": "move-plan"}, {"op": "move-plan", "mode": "move"},
                        {"op": "move-plan", "mode": "move", "moves": [{"from": made[0].diagram_id}]},
                        {"op": "move-plan", "mode": "move", "moves": [{"from": 1, "to": "x"}]},
                        {"op": "move-plan", "mode": "adopt", "moves": [{"from": "a", "to": "b", "sha256": "xyz"}]},
                        {"op": "move-plan", "mode": "move", "moves": [{"from": "a", "to": "b", "extra": 1}]}):
                with self.subTest(request=bad):
                    r, code = designer_api.handle(ws.root, {"version": 1, **bad})
                    self.assertEqual(code, 2, r)
                    self.assertEqual(r["error"]["code"], "bad-request")
            self.assertEqual(tree(ws), before)

    def test_move_plan_and_moved_are_read_only(self):
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            externally_move(ws, made[1].path, f"{DEST}/b.md")
            (ws.root / f"{DEST}/occupied.md").write_bytes(b"x\n")
            before = tree(ws, mtimes=True)
            reqs = [{"version": 1, "op": "moved"},
                    {"version": 1, "op": "move-plan", "mode": "adopt"},
                    {"version": 1, "op": "move-plan", "mode": "move",
                     "moves": [{"from": made[0].diagram_id, "to": f"{DEST}/a.md"}]},
                    {"version": 1, "op": "move-plan", "mode": "move",
                     "moves": [{"from": made[0].diagram_id, "to": f"{DEST}/occupied.md"}]},
                    {"version": 1, "op": "move-plan", "mode": "move",
                     "moves": [{"from": made[0].diagram_id, "to": "designs/features/new/deep/diagrams/a.md"}]}]
            results = [designer_api.handle(ws.root, r) for r in reqs]
            with registry.lock(ws.root):                                     # also while another command runs
                results += [designer_api.handle(ws.root, r) for r in reqs]
            self.assertEqual(tree(ws, mtimes=True), before)
            self.assertTrue(all(code == 0 for _r, code in results), results)
            self.assertEqual([x["diagram_id"] for x in results[0][0]["matches"]], [made[1].diagram_id])
            self.assertTrue(results[1][0]["possible"] and results[2][0]["possible"] and results[4][0]["possible"])
            self.assertFalse(results[3][0]["possible"])
            self.assertEqual(results[3][0]["token"], "")
            self.assertFalse((ws.root / "designs/features/new").exists())


# --------------------------------------------------------------------------- holds, concurrency, Git

class Holds(unittest.TestCase):
    def test_an_unresolved_move_refuses_every_registry_writer_and_refresh(self):
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            doc = with_block(ws, made[1])
            tok = moves.plan(ws.root, "move", [(made[0].diagram_id, f"{DEST}/")]).token
            r = run(ws, [*move_args([(made[0].diagram_id, f"{DEST}/")]), "--confirm", tok], fault="move-after-rename:1")
            self.assertEqual(r.returncode, 97, r.stderr)
            wait_released(ws)
            unlock(ws)
            before = tree(ws)
            text = ws.text(doc)
            writers = {
                "registry move": lambda: cmd(ws.root, *move_args([(made[1].diagram_id, f"{DEST}/")])),
                "registry adopt-moves": lambda: cmd(ws.root, "registry", "adopt-moves"),
                "relink": lambda: cmd(ws.root, "registry", "relink", made[1].diagram_id, "--title", "T"),
                "retire": lambda: cmd(ws.root, "registry", "retire", made[1].diagram_id, "--confirm"),
                "new diagram": lambda: cmd(ws.root, "new", "diagram", "--feature", "FD-0001", "--title", "Z"),
                "index": lambda: cmd(ws.root, "index"),
            }
            for name, call in writers.items():
                with self.subTest(name=name):
                    code, out, err = call()
                    self.assertEqual(code, 2, out + err)
                    self.assertIn("registry move is unresolved", err)
            r, code = designer_api.handle(ws.root, {"version": 1, "op": "refresh", "path": doc, "text": text})
            self.assertEqual(code, 1, r)
            self.assertIn("registry move is unresolved", r["error"]["message"])
            p = moves.plan(ws.root, "move", [(made[1].diagram_id, f"{DEST}/")])
            self.assertTrue(any("registry move is unresolved" in x for x in p.problems))
            self.assertEqual(tree(ws), before)
            r, _ = cli_resolve(ws, "complete")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(cmd(ws.root, "index")[0], 0)                       # released

    def test_an_unresolved_update_of_closed_documents_refuses_a_move_until_resolved(self):
        with Workspace() as ws:
            docs, src = build(ws, 2)
            reqs, token = listing(ws)
            self.assertEqual(run(ws, rb_args(reqs, token), fault="after-replace:1").returncode, 97)
            wait_released(ws)
            unlock(ws)
            entry = [e for e in registry.load(ws.root).entries if e.path == src][0]
            p = moves.plan(ws.root, "move", [(entry.diagram_id, f"{DEST}/")])
            self.assertTrue(any("update of closed documents is unresolved" in x for x in p.problems), p.problems)
            r, _ = cli_resolve(ws, "complete")                                # version 1, written by the same code
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            p = moves.plan(ws.root, "move", [(entry.diagram_id, f"{DEST}/")])
            self.assertEqual(p.problems, [])


class Concurrency(unittest.TestCase):
    def test_c2_a_move_while_another_command_holds_the_lock_is_refused(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            pairs = [(made[0].diagram_id, f"{DEST}/")]
            tok = moves.plan(ws.root, "move", pairs).token
            holder = subprocess.Popen([sys.executable, "-B", "-c",
                                       "import sys, time; from pathlib import Path; from tools.design import registry\n"
                                       "with registry.lock(Path(sys.argv[1])):\n    print('held', flush=True); time.sleep(60)",
                                       str(ws.root)], cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                self.assertEqual(holder.stdout.readline().strip(), b"held")
                before = tree(ws)
                code, out, err = cmd(ws.root, *move_args(pairs), "--confirm", tok)
                self.assertEqual(code, 2, out + err)
                self.assertIn("E12", err)
                self.assertEqual({k: v for k, v in tree(ws).items() if k != registry.LOCK},
                                 {k: v for k, v in before.items() if k != registry.LOCK})
            finally:
                stop(holder, ws)
            unlock(ws)
            self.assertEqual(cmd(ws.root, *move_args(pairs), "--confirm", tok)[0], 0)

    def test_c3_a_source_open_in_a_window_even_a_suspended_one_cannot_be_moved(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            pairs = [(made[0].diagram_id, f"{DEST}/")]
            win = OpenElsewhere.window
            for age in (0.0, transactions.WINDOW_LIVE + 5, 3600.0):
                with self.subTest(age=age):
                    w = win(None, ws, [made[0].path], age=age)
                    p = moves.plan(ws.root, "move", pairs)
                    self.assertTrue(any("is open in a VS Code window" in x for x in p.problems), p.problems)
                    self.assertEqual(cmd(ws.root, *move_args(pairs))[0], 2)
                    w.unlink()
            w = win(None, ws, [], raw=b"{damaged")                              # an unreadable window record
            p = moves.plan(ws.root, "move", pairs)
            self.assertTrue(any("cannot be read" in x for x in p.problems), p.problems)
            w.unlink()
            tok = moves.plan(ws.root, "move", pairs).token
            w = win(None, ws, [f"{DEST}/{made[0].path.rsplit('/', 1)[1]}"], age=3600.0)   # the destination is open
            self.assertEqual(cmd(ws.root, *move_args(pairs), "--confirm", tok)[0], 2)
            w.unlink()
            self.assertEqual(cmd(ws.root, *move_args(pairs), "--confirm", tok)[0], 0)

    def test_c4_a_git_operation_refuses_the_move_and_the_adoption(self):
        with Workspace() as ws:
            made = setup_sources(ws, 2)
            externally_move(ws, made[1].path, f"{DEST}/b.md")
            pairs = [(made[0].diagram_id, f"{DEST}/")]
            toks = {"move": moves.plan(ws.root, "move", pairs).token, "adopt": moves.plan(ws.root, "adopt", None).token}
            gitdir = ws.root / ".git"
            for marker in ("MERGE_HEAD", "rebase-merge"):
                with self.subTest(marker=marker):
                    target = gitdir / marker
                    target.mkdir() if marker == "rebase-merge" else target.write_bytes(b"")
                    before = tree(ws)
                    for args in ([*move_args(pairs), "--confirm", toks["move"]],
                                 ["registry", "adopt-moves", "--confirm", toks["adopt"]], move_args(pairs)):
                        code, out, err = cmd(ws.root, *args)
                        self.assertEqual(code, 2, out + err)
                        self.assertIn("Git operation is in progress", err)
                    self.assertEqual(tree(ws), before)
                    target.rmdir() if marker == "rebase-merge" else target.unlink()
            self.assertEqual(cmd(ws.root, *move_args(pairs), "--confirm", toks["move"])[0], 0)


# --------------------------------------------------------------------------- crash injection through the commands

S2_NOTHING = ["moves-after-lock", "moves-before-prepare", "move-after-orig", "move-after-new", "move-before-journal",
              "move-after-journal"]
S2_COMMIT = ["move-after-prepare", "move-after-committing-mark", "move-before-rename:1", "move-temp:1",
             "move-after-rename:1", "move-before-rename:2", "move-after-rename:2", "move-before-registry",
             "move-after-registry", "move-before-committed-mark"]
S2_DONE = ["move-after-committed-mark", "after-done-rename", "during-cleanup:1"]


class CommandCrashes(unittest.TestCase):
    """`registry move` in its own process, ended at every boundary; recovery through the
    `transaction` commands in their own processes. A batch: one case-only rename (through its
    intermediate path) and one to a new folder."""

    def setup(self, ws):
        made = setup_sources(ws, 2)
        pairs = [(made[0].path, _upper_name(made[0].path)), (made[1].diagram_id, f"{DEST}/")]
        plan = moves.plan(ws.root, "move", pairs)
        assert not plan.problems, plan.problems
        assert plan.renames[0]["via"] is not None
        return pairs, plan

    def states(self, ws, plan):
        where = [transactions.rename_state(ws.root, dict(r, observed=False)) for r in plan.renames]
        h = sha((ws.root / registry.REGISTRY).read_bytes())
        reg = "original" if h == sha(plan.before) else "replacement" if h == sha(plan.after) else "changed"
        return where, reg

    def assert_consistent(self, ws, plan):
        where, reg = self.states(ws, plan)
        self.assertTrue(all(s in ("old", "new", "temp") for s in where), where)    # never lost or duplicated
        self.assertIn(reg, ("original", "replacement"))
        if reg == "replacement":
            self.assertEqual(where, ["new", "new"])                                 # never names a missing file

    def crash(self, ws, pairs, plan, point, mode=None):
        r = run(ws, [*move_args(pairs), "--confirm", plan.token], fault=point, mode=mode)
        self.assertEqual(r.returncode, 97, r.stdout + r.stderr)

    def test_r2_before_the_record_exists_nothing_is_touched(self):
        for point in S2_NOTHING:
            with self.subTest(point=point), Workspace() as ws:
                pairs, plan = self.setup(ws)
                before = tree(ws)
                self.crash(ws, pairs, plan, point)
                wait_released(ws)
                unlock(ws)
                self.assertEqual(self.states(ws, plan), (["old", "old"], "original"))
                self.assertEqual(cli_status(ws), [])
                after_ = {k: v for k, v in tree(ws).items() if not k.startswith(transactions.TX_ROOT)}
                self.assertEqual(after_, {k: v for k, v in before.items() if not k.startswith(transactions.TX_ROOT)})
                tok = moves.plan(ws.root, "move", pairs).token               # the move can simply run again
                self.assertEqual(cmd(ws.root, *move_args(pairs), "--confirm", tok)[0], 0)

    def test_r2_r4_during_the_move_then_complete_then_complete_again(self):
        for point in S2_COMMIT:
            with self.subTest(point=point), Workspace() as ws:
                pairs, plan = self.setup(ws)
                self.crash(ws, pairs, plan, point)
                self.assert_consistent(ws, plan)
                r, rec = cli_resolve(ws, "complete")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.states(ws, plan), (["new", "new"], "replacement"))
                again = run(ws, ["transaction", "complete", rec["id"], "--confirm", rec["token"], "--json"])
                self.assertEqual(again.returncode, 0)
                self.assertTrue(json.loads(again.stdout)["already"])              # A3: a repeat changes nothing
                self.assertEqual(self.states(ws, plan), (["new", "new"], "replacement"))
                self.assertEqual(registry_problems(ws), [])
                self.assertEqual(cmd(ws.root, "index", "--check")[0], 0)

    def test_r2_r4_during_the_move_then_undo(self):
        for point in S2_COMMIT:
            with self.subTest(point=point), Workspace() as ws:
                pairs, plan = self.setup(ws)
                self.crash(ws, pairs, plan, point)
                r, _ = cli_resolve(ws, "undo")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.states(ws, plan), (["old", "old"], "original"))
                self.assertEqual((ws.root / registry.REGISTRY).read_bytes(), plan.before)
                self.assertEqual(registry_problems(ws), [])

    def test_after_the_move_was_verified_it_counts_as_done(self):
        for point in S2_DONE:
            with self.subTest(point=point), Workspace() as ws:
                pairs, plan = self.setup(ws)
                self.crash(ws, pairs, plan, point)
                self.assertEqual(self.states(ws, plan), (["new", "new"], "replacement"))
                self.assertEqual(cli_status(ws), [])
                unlock(ws)
                self.assertEqual(cmd(ws.root, "index")[0], 0)                   # the next writer cleans up
                self.assertEqual(cmd(ws.root, "index", "--check")[0], 0)

    def test_r3_an_interrupted_complete_and_undo_are_repeated(self):
        for action, points in (("complete", ["move-complete-after-mark", "move-complete-temp:1", "move-complete-after:1",
                                             "move-complete-after:2", "move-complete-after-registry"]),
                               ("undo", ["move-undo-after-mark", "move-undo-after-registry", "move-undo-after:2",
                                         "move-undo-temp:1", "move-undo-after:1"])):
            for point in points:
                with self.subTest(action=action, point=point), Workspace() as ws:
                    pairs, plan = self.setup(ws)
                    self.crash(ws, pairs, plan, "move-before-rename:1" if action == "complete" else "move-after-registry")
                    recs = cli_status(ws)
                    r = run(ws, ["transaction", action, recs[0]["id"], "--confirm", recs[0]["token"]], fault=point)
                    self.assertEqual(r.returncode, 97, r.stdout + r.stderr)
                    self.assert_consistent(ws, plan)
                    r, _ = cli_resolve(ws, action)
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                    goal = (["new", "new"], "replacement") if action == "complete" else (["old", "old"], "original")
                    self.assertEqual(self.states(ws, plan), goal)

    def test_termination_from_outside(self):
        for point in ("move-temp:1", "move-after-rename:2", "move-after-registry"):
            with self.subTest(point=point), Workspace() as ws:
                pairs, plan = self.setup(ws)
                env = {k: v for k, v in os.environ.items() if not k.startswith("DESIGN_TEST_FAULT")}
                env.update(DESIGN_TEST_FAULT=point, DESIGN_TEST_FAULT_ROOT=str(ws.root.resolve()),
                           DESIGN_TEST_FAULT_MODE="sleep")
                proc = subprocess.Popen([sys.executable, "-B", "-m", "tools.design", *move_args(pairs), "--confirm",
                                         plan.token, "--root", str(ws.root)], cwd=REPO_ROOT, env=env,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                line = proc.stderr.readline()
                self.assertIn(b"FAULT", line)
                stop(proc, ws)                                               # killed, as by the task manager
                self.assert_consistent(ws, plan)
                r, _ = cli_resolve(ws, "complete")                           # removes the dead process's lock itself
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.states(ws, plan), (["new", "new"], "replacement"))


class GeneratedText(unittest.TestCase):
    """G1 / requirement 12: the generated text follows separately and never reverses the move."""

    def test_r5_the_blocks_follow_separately_and_a_failed_refresh_never_reverses_the_move(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            doc = with_block(ws, made[0])
            new = f"{DEST}/{made[0].path.rsplit('/', 1)[1]}"
            tok = moves.plan(ws.root, "move", [(made[0].diagram_id, f"{DEST}/")]).token
            code, out, err = cmd(ws.root, *move_args([(made[0].diagram_id, f"{DEST}/")]), "--confirm", tok)
            self.assertEqual(code, 0, out + err)
            self.assertIn("refresh-blocks", out)                              # the next step is offered, not taken
            self.assertTrue(any(doc == p.path for p in __import__("tools.design.diagrams", fromlist=["x"]).stale(ws.root)))
            moved_registry = (ws.root / registry.REGISTRY).read_bytes()
            # the refresh is refused (the document is open in a window): the move stays
            w = OpenElsewhere.window(None, ws, [doc])
            reqs, token = listing(ws)
            self.assertEqual(reqs, [])
            w.unlink()
            # the refresh is interrupted: two independent layers; the move is not reversed
            reqs, token = listing(ws)
            self.assertEqual(run(ws, rb_args(reqs, token), fault="after-replace:1").returncode, 97)
            self.assertEqual((ws.root / registry.REGISTRY).read_bytes(), moved_registry)
            self.assertEqual(transactions.rename_state(ws.root, {"from": made[0].path, "to": new, "via": None,
                                                                 "sha": sha((ws.root / new).read_bytes())}), "new")
            r, rec = cli_resolve(ws, "undo")                                  # undo the refresh only
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("tool", rec)                                     # a version 1 record
            self.assertEqual((ws.root / registry.REGISTRY).read_bytes(), moved_registry)
            self.assertEqual(paths(ws)[made[0].diagram_id], new)
            reqs, token = listing(ws)
            self.assertEqual(cmd(ws.root, *rb_args(reqs, token))[0], 0)       # then it is simply done again
            self.assertEqual(cmd(ws.root, "index", "--check")[0], 0)


# --------------------------------------------------------------------------- S1 QA follow-ups

class QAFollowUpsS1(unittest.TestCase):
    def _two_paths(self, ws):
        """A move interrupted after a rename, with the source also at its old path as the same file (the
        interrupted link-then-unlink of a POSIX rename, simulated with a hard link on NTFS)."""
        made = setup_sources(ws, 1)
        plan = plan_for(ws, made)
        self.assertEqual(drive(ws, plan, fault="move-after-rename:1").returncode, 97)
        op = plan["renames"][0]
        os.link(ws.root / op["to"], ws.root / op["from"])
        wait_released(ws)
        unlock(ws)
        return plan, op

    def test_the_same_file_unlink_is_refused_while_a_git_operation_starts(self):
        with Workspace() as ws:
            plan, op = self._two_paths(ws)
            rec = transactions.status(ws.root)[0]
            self.assertEqual(rec["files"][0]["state"], "both")
            real = transactions._drive

            def git_starts(*a, **k):                                       # Git begins just before the unlink
                (ws.root / ".git" / "MERGE_HEAD").write_bytes(b"")
                return real(*a, **k)
            transactions._drive = git_starts
            try:
                out = transactions.resolve(ws.root, rec["id"], "complete", rec["token"])
            finally:
                transactions._drive = real
            self.assertFalse(out["ok"])
            self.assertIn("Git operation started while this ran (MERGE_HEAD", out["message"])
            self.assertTrue((ws.root / op["from"]).exists() and (ws.root / op["to"]).exists())   # nothing unlinked
            self.assertTrue(os.path.samefile(ws.root / op["from"], ws.root / op["to"]))
            (ws.root / ".git" / "MERGE_HEAD").unlink()
            rec = transactions.status(ws.root)[0]
            out = transactions.resolve(ws.root, rec["id"], "complete", rec["token"])
            self.assertTrue(out["ok"], out)
            self.assertFalse((ws.root / op["from"]).exists())

    def test_an_error_after_the_last_step_says_the_state_is_already_reached(self):
        with Workspace() as ws:
            made = setup_sources(ws, 1)
            plan = plan_for(ws, made)
            self.assertEqual(drive(ws, plan, fault="move-before-registry").returncode, 97)
            wait_released(ws)
            unlock(ws)
            rec = transactions.status(ws.root)[0]
            real = transactions._write_registry

            def written_then_error(*a, **k):                               # written, then the OS reports an error
                real(*a, **k)
                raise PermissionError(13, "the indexer held the file", "registry.yml")
            transactions._write_registry = written_then_error
            try:
                out = transactions.resolve(ws.root, rec["id"], "complete", rec["token"])
            finally:
                transactions._write_registry = real
            self.assertFalse(out["ok"])
            self.assertTrue(out["effectively_done"])
            self.assertIn("are now exactly as Complete leaves them", out["message"])
            self.assertIn(f"transaction complete {rec['id']}", out["message"])
            code, text, err = cmd(ws.root, "transaction", "complete", rec["id"], "--confirm",
                                  transactions.status(ws.root)[0]["token"])
            self.assertEqual(code, 0, text + err)                               # repeated: changes nothing more
            self.assertEqual(transactions.status(ws.root), [])


if __name__ == "__main__":
    unittest.main()
