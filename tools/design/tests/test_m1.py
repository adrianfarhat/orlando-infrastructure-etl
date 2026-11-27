"""T-97 M1 (architecture diagram extraction) tooling: registry-backed counting (U9), generated
copies in docs/architecture/ documents (report-and-apply, C1), `registry extract` and its
guarded revert, `architecture snapshot | copy | verify`, and a complete synthetic M1 of copies
of the four real documents. Every test runs on a temporary workspace: the repository's own
documents and registry are only read."""

import hashlib
import inspect
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from tools.design import (architecture, architecture_copies, cli, designer_api, diagrams, ownership, registry,
                          transactions, workspace)
from tools.design.tests.test_design import REPO_ROOT, Workspace, cmd
from tools.design.workspace import DesignError, new_feature

PY = sys.executable
DOCS = ("docs/architecture/conventions.md", "docs/architecture/database-schema.md",
        "docs/architecture/etl-workflow.md", "docs/architecture/system-architecture.md")
LEGEND = ('Legend ([conventions.md](../conventions.md#1-implementation-status-legend)): thick solid border = verified · '
          'thin solid border + "(unverified)" = built, no recorded verification · dashed border + "(planned)" = not '
          'built · grey, in an "External" group = not ours.')
# The cross-check fingerprints of the M1 execution specification, section 3.1.
FINGERPRINTS = {"AD-0001": "6ff62f4dd7084d61", "AD-0002": "ef121b47802616d0", "AD-0003": "15667a76b4671522",
                "AD-0004": "6c8e58a3393facfe", "AD-0005": "d16381984395a06d", "AD-0006": "6b70484d68dec2c8",
                "AD-0007": "2508b8aec5c25b20", "AD-0008": "8c33c0e033cac62e", "AD-0009": "706c98936e99f8fd",
                "AD-0010": "320dd06ef4b28b05", "AD-0011": "d4010cdbfbacf012", "AD-0012": "7e878d0faa3bd186",
                "AD-0013": "12c7eed790707fe5", "AD-0014": "62de7b07c843f9df"}
BLANK_LINE_DIAGRAMS = {"AD-0001", "AD-0003", "AD-0010", "AD-0011", "AD-0012", "AD-0013", "AD-0014"}


def tree_hashes(root: Path, sub: str = "docs/architecture") -> dict:
    base = Path(root) / sub
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(base.rglob("*")) if p.is_file()}


def lines_of(code_out):
    return [x for x in code_out.split("\n") if x and not re.match(r"\d+ feature file\(s\), \d+ problem\(s\)", x)]


def source_text(d: dict) -> str:
    """A standalone source exactly as section 2.2 of the specification has technical-lead write it."""
    did, alias, doc = d["diagram_id"], d["aliases"][0], d["document"].rsplit("/", 1)[1]
    lines = ["---", f"diagram_id: {did}", f"title: {json.dumps(d['title'], ensure_ascii=False)}",
             f"owner_document: {d['document']}", "---", "", f"# {d['title']}", "",
             f"Authoritative source of diagram `{did}` (former catalog ID `{alias}`), owned by and shown in",
             f"[{doc}](../{doc}#{d['heading_anchor']}). Edit the diagram here. The copy in that",
             "document is generated from this file and is never edited by hand (see",
             "[conventions.md section 5](../conventions.md#5-branch-docs-workflow)).", ""]
    if d["diagram_type"] == "architecture":
        extra = " The hexagon is an open question, not a component." if did == "AD-0014" else ""
        lines += [LEGEND + extra, ""]
    lines += [d["opening_fence"], *d["mermaid_lines"], d["closing_fence"], ""]
    return "\n".join(lines)


def source_path(did: str) -> str:
    return f"docs/architecture/diagrams/{architecture_copies.M1_SOURCES[did]}"


def write_source(ws, d: dict, text: str | None = None, crlf: bool = True):
    """Technical-lead's step 1 (the test writes the file directly, as the documentation workflow does)."""
    path = ws.root / source_path(d["diagram_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    body = source_text(d) if text is None else text
    path.write_bytes((body.replace("\n", "\r\n") if crlf else body).encode("utf-8"))


def apply_printed_copy(ws, document: str):
    """Technical-lead's step 3: the Edit tool replaces each exact, unique old text with the printed text."""
    code, out, err = cmd(ws.root, "architecture", "copy", "--document", document, "--json")
    assert code == 0, err
    plan = json.loads(out)
    path = ws.root / document
    raw = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    for doc in plan["documents"]:
        for r in doc["replacements"]:
            assert r["old_unique"], r
            assert text.count(r["old_text"]) == 1
            text = text.replace(r["old_text"], r["new_text"])
        assert hashlib.sha256(text.encode("utf-8")).hexdigest() == doc["sha256_after"]
    path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    return plan


def take_snapshot(ws, folder: Path) -> Path:
    out = folder / "snapshot.json"
    code, stdout, err = cmd(ws.root, "architecture", "snapshot", "--out", str(out))
    assert code == 0, err
    return out


def by_document(snap: dict, document: str) -> list[dict]:
    return [d for d in snap["diagrams"] if d["document"] == document]


def extract_args(ds: list[dict], snapshot: Path) -> list[str]:
    args = ["registry", "extract"]
    for d in ds:
        args += [d["diagram_id"], "--path", source_path(d["diagram_id"])]
    return args + ["--snapshot", str(snapshot)]


def extract(ws, ds, snapshot, expect_ok=True):
    code, out, err = cmd(ws.root, *extract_args(ds, snapshot), "--json")
    plan = json.loads(out) if out.strip() else {}
    if not expect_ok:
        return code, plan, err
    assert code == 1 and not plan["problems"], (code, plan.get("problems"), err)
    code, out, err = cmd(ws.root, *extract_args(ds, snapshot), "--confirm", plan["token"])
    assert code == 0, err
    return code, plan, out


class Fixture(unittest.TestCase):
    """A workspace copied from this repository, indexed, with its snapshot outside the workspace."""

    def setUp(self):
        self.ws = Workspace()
        self.ws.__enter__()
        self.tmp = Path(tempfile.mkdtemp(prefix="m1-snap-"))
        self.assertEqual(cmd(self.ws.root, "index")[0], 0)
        self.snapshot = take_snapshot(self.ws, self.tmp)
        self.snap = json.loads(self.snapshot.read_text(encoding="utf-8"))

    def tearDown(self):
        self.ws.__exit__(None, None, None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def check(self):
        code, out, _ = cmd(self.ws.root, "check")
        return code, lines_of(out)

    def rows(self):
        return architecture.architecture_diagrams(self.ws.root)

    def d(self, did):
        return next(x for x in self.snap["diagrams"] if x["diagram_id"] == did)


# --------------------------------------------------------------------------- U9 and scanning

class Counting(unittest.TestCase):
    def test_a_generated_copy_is_never_counted_and_markers_in_code_are_ignored(self):
        text = ("# T\n\n## A\n\n<!-- diagram:start AD-0001 sha256:0123456789abcdef -->\n"
                "<!-- generated copy of AD-0001 from diagrams/x.md: edit the source, not this copy -->\n"
                "```mermaid\nflowchart LR\n  A --> B\n```\n<!-- diagram:end -->\n\n## B\n\n```mermaid\nflowchart LR\n  C\n```\n\n"
                "```text\n<!-- diagram:start AD-0002 -->\n<!-- diagram:end -->\n```\n\nSee `<!-- diagram:end -->` here.\n")
        blocks, problems = architecture_copies.scan(text)
        self.assertEqual(problems, [])
        self.assertEqual([(b.diagram_id, b.start, b.end) for b in blocks], [("AD-0001", 4, 10)])
        doc = architecture.ArchitectureDocument("docs/architecture/t.md", architecture.markdown.parse(text), None, text)
        self.assertEqual([c.diagram_id for c in architecture.catalog([doc])], ["t/b"])   # only the raw block

    def test_structural_problems(self):
        cases = {
            "<!-- diagram:start AD-0001 -->\n<!-- diagram:start AD-0002 -->\n<!-- diagram:end -->\n": "nested",
            "<!-- diagram:end -->\n": "without a matching",
            "<!-- diagram:start AD-0001 -->\n": "has no matching",
            "<!-- diagram:start AD-0001 -->\n```mermaid\nA\n<!-- diagram:end -->\n": "not closed before",
            "<!-- diagram: start x -->\n": "malformed",
            "- <!-- diagram:start AD-0001 -->\n": "stand alone",
            "<!-- diagram:start -->\n<!-- diagram:end -->\n": "no diagram ID",
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                problems = architecture_copies.scan(text)[1]
                self.assertTrue(any(want in m for _, m in problems), problems)

    def test_the_real_documents_have_no_marker_problem_and_14_diagrams(self):
        for doc in architecture.documents(REPO_ROOT):
            self.assertEqual(architecture_copies.scan(doc.text)[1], [], doc.path)
        rows = architecture.architecture_diagrams(REPO_ROOT)
        self.assertEqual(len(rows), 14)
        types = {}
        for r in rows:
            types[r.diagram_type] = types.get(r.diagram_type, 0) + 1
        self.assertEqual(types, {"architecture": 4, "sequence": 1, "process": 6, "er": 2, "example": 1})
        self.assertEqual(architecture_copies.problems(REPO_ROOT), [])

    def test_the_index_changed_only_by_the_source_column(self):
        """The committed index differs from its pre-M1 form (18919f8) only by the Source column."""
        try:
            old = subprocess.run(["git", "-C", str(REPO_ROOT), "show", "18919f8:designs/index/architecture-index.md"],
                                 capture_output=True, timeout=60, check=True).stdout.decode("utf-8")
        except (subprocess.CalledProcessError, OSError):
            self.skipTest("commit 18919f8 is not available")
        new = architecture.render_architecture_index(REPO_ROOT)
        old_rows = [x for x in old.split("\n") if x.startswith("| `")]
        new_rows = [x for x in new.split("\n") if x.startswith("| `")]
        self.assertEqual(len(new_rows), 14)
        self.assertEqual([x[:x.rindex(" | ")] + " |" for x in new_rows], old_rows)
        self.assertTrue(all(x.endswith(" | embedded |") for x in new_rows))
        self.assertEqual([x for x in new.split("\n") if not x.startswith("|")][:9],
                         [x for x in old.split("\n") if not x.startswith("|")][:9])


class NoWrites(unittest.TestCase):
    def test_the_module_writes_no_file(self):
        """architecture_copies never writes (the snapshot file is written by the command line, outside
        docs/architecture/): no write call in its source, and none happens when it runs."""
        source = inspect.getsource(architecture_copies)
        for pattern in (r"\bopen\(", r"write_bytes", r"write_text", r"os\.replace", r"os\.rename", r"mkstemp",
                        r"\.unlink\(", r"write_generated", r"write_feature_text", r"write_atomically"):
            self.assertIsNone(re.search(pattern, source), pattern)
        with Workspace() as ws:
            cmd(ws.root, "index")
            before = tree_hashes(ws.root, ".")

            def refuse(*a, **k):
                raise AssertionError("a write was attempted")
            with mock.patch("os.replace", refuse), mock.patch("tempfile.mkstemp", refuse), \
                    mock.patch.object(Path, "write_bytes", refuse), mock.patch.object(Path, "write_text", refuse):
                architecture_copies.problems(ws.root)
                architecture_copies.stale(ws.root)
                architecture_copies.snapshot(ws.root)
                with self.assertRaises(DesignError):
                    architecture_copies.plan_copies(ws.root, ["AD-0001"])       # not extracted: refused
            self.assertEqual(tree_hashes(ws.root, "."), before)

    def test_the_write_guard_is_unchanged(self):
        with Workspace() as ws:
            for rel in ("docs/architecture/x.md", "docs/architecture/diagrams/x.md", "docs/architecture"):
                with self.subTest(rel):
                    with self.assertRaises(DesignError):
                        ownership.guard_write(ws.root, ws.root / rel)
            with self.assertRaises(DesignError):                               # relink still refuses an embedded entry
                registry.relink(ws.root, "AD-0001", path="docs/architecture/diagrams/x.md")

    def test_a_snapshot_is_never_written_under_docs_architecture_or_over_a_file(self):
        with Workspace() as ws:
            cmd(ws.root, "index")
            before = tree_hashes(ws.root)
            code, _, err = cmd(ws.root, "architecture", "snapshot", "--out", str(ws.root / "docs/architecture/s.json"))
            self.assertEqual(code, 2)
            self.assertIn("docs/architecture/", err)
            self.assertEqual(tree_hashes(ws.root), before)
            existing = ws.root.parent / "taken.json"
            existing.write_text("keep", encoding="utf-8")
            self.assertEqual(cmd(ws.root, "architecture", "snapshot", "--out", str(existing))[0], 2)
            self.assertEqual(existing.read_text(encoding="utf-8"), "keep")


# --------------------------------------------------------------------------- the snapshot

class Snapshot(Fixture):
    def test_records_the_14_diagrams_and_the_inventory_hashes(self):
        self.assertEqual([d["diagram_id"] for d in self.snap["diagrams"]], [f"AD-{n:04d}" for n in range(1, 15)])
        self.assertEqual(len(self.snap["documents"]), 7)
        inventory = {"AD-0001": "942159441c0113f2e473b6d4f71552d62070058543d2e38a5be50027e89f638e",
                     "AD-0010": "6a78abd5f79868b8a03c2b49e3d4efa0f0fe443bca24a7e20f8cb9b23710d69a",
                     "AD-0014": "e7aaec3222ef45444d58e2f516011caf4ca273e236368695339e5330fce7431d"}
        for did, sha in inventory.items():
            self.assertEqual(self.d(did)["mermaid_sha256"], sha)
        self.assertEqual({d["diagram_id"] for d in self.snap["diagrams"] if d["blank_lines"]}, BLANK_LINE_DIAGRAMS)
        self.assertEqual(self.d("AD-0010")["blank_lines"], [34, 39, 45, 51, 53, 66])
        self.assertEqual((self.d("AD-0013")["opening_line"], self.d("AD-0013")["opening_fence"]), (181, "```mermaid"))
        code, out, _ = cmd(self.ws.root, "architecture", "verify", "--snapshot", str(self.snapshot))
        self.assertEqual(code, 0, out)

    def test_refused_after_an_extraction_and_damaged_snapshots_are_refused(self):
        d = self.d("AD-0001")
        write_source(self.ws, d)
        extract(self.ws, [d], self.snapshot)
        with self.assertRaises(DesignError):
            architecture_copies.snapshot(self.ws.root)
        damaged = json.loads(self.snapshot.read_text(encoding="utf-8"))
        damaged["documents"]["docs/architecture/conventions.md"]["text"] += "x"
        bad = self.tmp / "bad.json"
        bad.write_text(json.dumps(damaged), encoding="utf-8")
        code, _, err = cmd(self.ws.root, "architecture", "verify", "--snapshot", str(bad))
        self.assertEqual(code, 2)
        self.assertIn("damaged", err)


# --------------------------------------------------------------------------- registry extract

class ExtractRefusals(Fixture):
    def refused(self, ds, want, paths=None):
        args = ["registry", "extract"]
        for i, d in enumerate(ds):
            args += [d["diagram_id"] if isinstance(d, dict) else d, "--path",
                     (paths or {}).get(i) or source_path(d["diagram_id"] if isinstance(d, dict) else "AD-0001")]
        before = tree_hashes(self.ws.root, ".")
        code, out, err = cmd(self.ws.root, *args, "--snapshot", str(self.snapshot), "--json")
        self.assertEqual(code, 2, out + err)
        plan = json.loads(out)
        self.assertEqual(plan["token"], "")
        self.assertTrue(any(want in p for p in plan["problems"]), plan["problems"])
        self.assertEqual(tree_hashes(self.ws.root, "."), before)            # nothing written, anywhere
        code, _, err = cmd(self.ws.root, *args, "--snapshot", str(self.snapshot))
        self.assertEqual(code, 2)
        self.assertIn(want, err)
        return plan

    def test_identity_and_ownership(self):
        d1, d2 = self.d("AD-0001"), self.d("AD-0002")
        write_source(self.ws, d1)
        write_source(self.ws, d2)
        self.refused(["AD-9999"], "not in the registry")
        self.refused([d1, d2], "one document per run")
        self.refused([d1, d1], "named twice")
        self.refused([d1], "document-owned sources belong in", {0: "docs/architecture/x.md"})
        self.refused([d1], "document-owned sources belong in", {0: "designs/diagrams/x.md"})
        self.refused([d1], "exactly this letter case", {0: source_path("AD-0001").replace("conventions_", "Conventions_")})
        self.refused([d1], "exactly this letter case", {0: "docs/architecture/diagrams/nothing.md"})
        wrong = source_text(d1).replace("diagram_id: AD-0001", "diagram_id: AD-0002")
        write_source(self.ws, d1, wrong)
        self.refused([d1], "holds diagram_id AD-0002")
        write_source(self.ws, d1, source_text(d1).replace("owner_document: docs/architecture/conventions.md",
                                                          "owner_document: docs/architecture/etl-workflow.md"))
        self.refused([d1], "owner_document is docs/architecture/etl-workflow.md")
        write_source(self.ws, d1, source_text(d1).replace('title: "1. Implementation-status legend"',
                                                          'title: "Legend"'))
        self.refused([d1], "differs from the registry")
        write_source(self.ws, d1, source_text(d1).replace("owner_document:", "feature_id: FD-0001\nowner_document:"))
        self.refused([d1], "has a feature_id")
        write_source(self.ws, d1, source_text(d1).replace("owner_document:", "status: active\nowner_document:"))
        self.refused([d1], "exactly diagram_id, title, owner_document")

    def test_content(self):
        d1 = self.d("AD-0001")
        text = source_text(d1)
        write_source(self.ws, d1, text + "\n```mermaid\nflowchart LR\n  X\n```\n")
        self.refused([d1], "exactly one Mermaid block")
        write_source(self.ws, d1, text + "\n```text\nnot Mermaid\n```\n")
        self.refused([d1], "exactly one fenced block")
        write_source(self.ws, d1, text.replace("flowchart LR", "flowchart  LR", 1))
        self.refused([d1], "not byte-identical")
        write_source(self.ws, d1, text.replace("```mermaid\n", "````mermaid\n").replace("\n```\n", "\n````\n"))
        self.refused([d1], "fence lines")
        write_source(self.ws, d1, text.replace("Edit the diagram here.", "Edit <!-- diagram:end --> here."))
        self.refused([d1], "'<!-- diagram:' text")
        write_source(self.ws, d1, text.replace("\n```\n", "\n"))
        self.refused([d1], "no closing fence")

    def test_snapshot_mismatch_and_unreadable_snapshot(self):
        d1 = self.d("AD-0001")
        write_source(self.ws, d1)
        other = json.loads(self.snapshot.read_text(encoding="utf-8"))
        rec = next(x for x in other["diagrams"] if x["diagram_id"] == "AD-0001")
        rec["mermaid_lines"][0] = "flowchart TB"
        rec["mermaid_sha256"] = hashlib.sha256("\n".join(rec["mermaid_lines"]).encode()).hexdigest()
        self.snapshot.write_text(json.dumps(other), encoding="utf-8")
        self.refused([d1], "differ from the snapshot")
        self.snapshot.write_text("{", encoding="utf-8")
        self.refused([d1], "cannot be read")

    def test_a_link_is_refused(self):
        d1 = self.d("AD-0001")
        real = self.ws.root / "docs/architecture/diagrams/real.md"
        real.parent.mkdir(parents=True, exist_ok=True)
        real.write_text(source_text(d1), encoding="utf-8")
        try:
            os.symlink(real, self.ws.root / source_path("AD-0001"))
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links cannot be created here")
        self.refused([d1], "links are refused")

    def test_a_hard_link_is_refused(self):
        d1 = self.d("AD-0001")
        real = self.ws.root / "docs/architecture/diagrams/real.md"
        real.parent.mkdir(parents=True, exist_ok=True)
        real.write_text(source_text(d1), encoding="utf-8")
        os.link(real, self.ws.root / source_path("AD-0001"))
        self.refused([d1], "hard link")

    def test_not_embedded_and_registered_elsewhere(self):
        d1, d2 = self.d("AD-0002"), self.d("AD-0003")
        write_source(self.ws, d1)
        extract(self.ws, [d1], self.snapshot)
        self.refused([d1], "is not an active embedded")
        write_source(self.ws, d2)
        self.refused([d2], "already registered for AD-0002", {0: source_path("AD-0002")})

    def test_token_lock_git_and_move_records(self):
        d1 = self.d("AD-0001")
        write_source(self.ws, d1)
        code, plan, _ = extract(self.ws, [d1], self.snapshot, expect_ok=False)
        self.assertEqual(code, 1)
        token = plan["token"]
        args = extract_args([d1], self.snapshot)
        reg_before = (self.ws.root / registry.REGISTRY).read_bytes()

        def refused_confirm(want):
            code, _, err = cmd(self.ws.root, *args, "--confirm", token)
            self.assertEqual(code, 2, err)
            self.assertIn(want, err)
            self.assertEqual((self.ws.root / registry.REGISTRY).read_bytes(), reg_before)

        path = self.ws.root / source_path("AD-0001")
        original = path.read_bytes()
        path.write_bytes(original + b"\r\n")                                # a source changed after the plan
        refused_confirm("changed since the extraction was planned")
        path.write_bytes(original)
        lock = self.ws.root / registry.LOCK
        lock.write_text("{}", encoding="utf-8")                              # another command holds the lock
        refused_confirm("another diagram command is running")
        lock.unlink()
        git = self.ws.root / ".git" / "MERGE_HEAD"
        git.write_text("0" * 40, encoding="utf-8")                           # a Git operation is in progress
        refused_confirm("a Git operation is in progress")
        git.unlink()
        record = self.ws.root / transactions.TX_ROOT / "tx-20261127T000000Z-0123abcd"
        record.mkdir(parents=True)                                           # a record that cannot be read
        refused_confirm("transaction status")
        shutil.rmtree(record)
        reg = self.ws.root / registry.REGISTRY                                # the registry changed after the plan
        reg.write_bytes(reg_before + b"# edited\n")
        code, _, err = cmd(self.ws.root, *args, "--confirm", token)
        self.assertEqual(code, 2)
        self.assertIn("changed since the extraction was planned", err)
        reg.write_bytes(reg_before)
        self.assertEqual(cmd(self.ws.root, *args, "--confirm", token)[0], 0)  # exactly the plan: now it runs

    def test_compare_and_swap_when_the_registry_changes_during_the_command(self):
        d1 = self.d("AD-0001")
        write_source(self.ws, d1)
        _, plan, _ = extract(self.ws, [d1], self.snapshot, expect_ok=False)
        reg = self.ws.root / registry.REGISTRY
        real_ready, calls = transactions._git_ready, []

        def sneaky(root):
            calls.append(1)
            if len(calls) == 2:                                              # just before the replacement
                reg.write_bytes(reg.read_bytes() + b"# someone else\n")
            return real_ready(root)
        with mock.patch.object(transactions, "_git_ready", sneaky):
            with self.assertRaises(DesignError) as ctx:
                registry.extract(self.ws.root, [("AD-0001", source_path("AD-0001"))], self.snapshot, plan["token"])
        self.assertIn("E12", str(ctx.exception))
        self.assertTrue(reg.read_bytes().endswith(b"# someone else\n"))       # theirs kept, ours not written
        self.assertEqual(registry.load(self.ws.root).by_id()["AD-0001"].format, "mermaid-embedded")
        self.assertFalse((self.ws.root / registry.LOCK).exists())


class Extraction(Fixture):
    def test_the_switch_changes_only_format_and_path_and_writes_the_diagram_index_in_the_lock(self):
        d = self.d("AD-0013")
        write_source(self.ws, d)
        before = (self.ws.root / registry.REGISTRY).read_text(encoding="utf-8")
        docs_before = tree_hashes(self.ws.root)
        written = []
        real = registry.write_diagram_index

        def spy(root):
            written.append(registry.holds_lock(root))
            return real(root)
        _, plan, _ = extract(self.ws, [d], self.snapshot, expect_ok=False)
        with mock.patch.object(registry, "write_diagram_index", spy):
            registry.extract(self.ws.root, [("system-architecture/3-one-map-pan-step-by-step", source_path("AD-0013"))],
                             self.snapshot, plan["token"])                   # named by its alias
        self.assertEqual(written, [True])
        self.assertEqual(tree_hashes(self.ws.root), docs_before)              # docs/architecture/ untouched
        after = (self.ws.root / registry.REGISTRY).read_text(encoding="utf-8")
        old = before.split("  - diagram_id: AD-0013\n")[1].split("  - diagram_id:")[0]
        new = after.split("  - diagram_id: AD-0013\n")[1].split("  - diagram_id:")[0]
        self.assertEqual(new, "    title: 3. One map pan, step by step\n"
                              "    owner: {kind: document, ref: docs/architecture/system-architecture.md}\n"
                              "    format: mermaid-md\n    category: sequence\n"
                              f"    path: {source_path('AD-0013')}\n"
                              "    aliases: [system-architecture/3-one-map-pan-step-by-step]\n"
                              "    status: active\n    created: '2026-11-22'\n    created_from:\n")
        self.assertEqual(before.replace(old, ""), after.replace(new, ""))      # every other entry byte-identical
        self.assertTrue(registry.diagram_index_is_fresh(self.ws.root))

    def test_revert_restores_the_registry_bytes_and_its_refusals(self):
        d = self.d("AD-0011")
        write_source(self.ws, d)
        reg_before = (self.ws.root / registry.REGISTRY).read_bytes()
        index_before = (self.ws.root / registry.DIAGRAM_INDEX).read_bytes()
        code, out, err = cmd(self.ws.root, "registry", "extract", "--revert", "AD-0011", "--heading", "credential-boundary")
        self.assertEqual(code, 2)                                            # not extracted yet
        self.assertIn("only an extracted diagram is reverted", err)
        extract(self.ws, [d], self.snapshot)
        for args, want in ((["--heading", "1-current-state-the-big-picture"], "not byte-identical"),
                           (["--heading", "nope"], "has no raw Mermaid block"),
                           ([], "give --heading")):
            with self.subTest(args):
                code, _, err = cmd(self.ws.root, "registry", "extract", "--revert", "AD-0011", *args)
                self.assertEqual(code, 2)
                self.assertIn(want, err)
        code, out, _ = cmd(self.ws.root, "registry", "extract", "--revert", "AD-0011", "--heading", "credential-boundary",
                           "--json")
        self.assertEqual(code, 1)
        token = json.loads(out)["token"]
        self.assertEqual(cmd(self.ws.root, "registry", "extract", "--revert", "AD-0011", "--heading",
                             "credential-boundary", "--confirm", token)[0], 0)
        self.assertEqual((self.ws.root / registry.REGISTRY).read_bytes().replace(b"\r\n", b"\n"),
                         reg_before.replace(b"\r\n", b"\n"))                 # byte-identical (LF, as Git stores it)
        self.assertEqual((self.ws.root / registry.DIAGRAM_INDEX).read_bytes().replace(b"\r\n", b"\n"),
                         index_before.replace(b"\r\n", b"\n"))
        code, problems = self.check()
        self.assertEqual(len(problems), 1)
        self.assertIn("extraction not finished", problems[0])
        (self.ws.root / source_path("AD-0011")).unlink()
        self.assertEqual(self.check(), (0, []))

    def test_revert_is_refused_while_the_document_shows_the_copy(self):
        d = self.d("AD-0001")
        write_source(self.ws, d)
        extract(self.ws, [d], self.snapshot)
        apply_printed_copy(self.ws, "docs/architecture/conventions.md")
        code, _, err = cmd(self.ws.root, "registry", "extract", "--revert", "AD-0001", "--heading",
                           "1-implementation-status-legend")
        self.assertEqual(code, 2)
        self.assertIn("still shows the generated copy", err)


class Interruption(Fixture):
    def run_cli(self, *args, fault=None, mode=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith("DESIGN_TEST_FAULT")}
        if fault:
            env.update(DESIGN_TEST_FAULT=fault, DESIGN_TEST_FAULT_ROOT=str(self.ws.root.resolve()))
        if mode:
            env["DESIGN_TEST_FAULT_MODE"] = mode
        return subprocess.Popen([PY, "-m", "tools.design", *args, "--root", str(self.ws.root)], cwd=str(REPO_ROOT),
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def plan(self, d):
        write_source(self.ws, d)
        return extract(self.ws, [d], self.snapshot, expect_ok=False)[1]["token"]

    def test_killed_after_the_registry_replace_is_reported_and_recoverable(self):
        d = self.d("AD-0001")
        token = self.plan(d)
        docs_before = tree_hashes(self.ws.root)
        p = self.run_cli(*extract_args([d], self.snapshot), "--confirm", token, fault="extract-after-registry")
        p.communicate(timeout=120)
        self.assertEqual(p.returncode, 97)
        self.assertEqual(tree_hashes(self.ws.root), docs_before)
        self.assertEqual(registry.load(self.ws.root).by_id()["AD-0001"].format, "mermaid-md")   # the switch happened
        self.assertFalse(registry.diagram_index_is_fresh(self.ws.root))
        code, problems = self.check()
        self.assertIn("designs/index/diagram-index.md: out of date or missing: run `python -m tools.design index`",
                      problems)                                              # clearly reported, never silent
        self.assertEqual(cmd(self.ws.root, "index")[0], 2)                   # the leftover lock is never broken
        self.assertEqual(cmd(self.ws.root, "registry", "unlock", "--confirm")[0], 0)
        self.assertEqual(cmd(self.ws.root, "index")[0], 0)
        self.assertTrue(registry.diagram_index_is_fresh(self.ws.root))

    def test_killed_before_the_registry_replace_changes_nothing(self):
        d = self.d("AD-0001")
        token = self.plan(d)
        reg_before = (self.ws.root / registry.REGISTRY).read_bytes()
        for fault, mode in (("extract-after-lock", None), ("extract-before-registry", "sleep")):
            with self.subTest(fault):
                p = self.run_cli(*extract_args([d], self.snapshot), "--confirm", token, fault=fault, mode=mode)
                if mode == "sleep":
                    deadline = time.time() + 60
                    line = b""
                    while b"FAULT" not in line and time.time() < deadline:
                        line = p.stderr.readline()
                    p.kill()                                                 # killed mid-command
                p.communicate(timeout=120)
                self.assertEqual((self.ws.root / registry.REGISTRY).read_bytes(), reg_before)
                self.assertEqual(registry.load(self.ws.root).by_id()["AD-0001"].format, "mermaid-embedded")
                state = registry.unlock(self.ws.root, confirm=True)
                self.assertTrue(state.removable, state.reason)
        code, problems = self.check()
        self.assertEqual(problems, [f"{source_path('AD-0001')}: holds AD-0001, which is still registered as embedded "
                                    "in docs/architecture/conventions.md: extraction not finished; run `python -m "
                                    "tools.design registry extract AD-0001 --path "
                                    f"{source_path('AD-0001')} --snapshot <file>` (T-97 M1)"])
        self.assertEqual(cmd(self.ws.root, *extract_args([d], self.snapshot), "--confirm", token)[0], 0)


# --------------------------------------------------------------------------- copies and check reports

class Copies(Fixture):
    def extracted(self, did, document):
        d = self.d(did)
        write_source(self.ws, d)
        extract(self.ws, [d], self.snapshot)
        apply_printed_copy(self.ws, document)
        self.assertEqual(cmd(self.ws.root, "index")[0], 0)
        self.assertEqual(self.check(), (0, []))
        return self.ws.root / document

    def test_states_are_reported_never_applied(self):
        doc = self.extracted("AD-0005", "docs/architecture/etl-workflow.md")
        src = self.ws.root / source_path("AD-0005")
        rel = "docs/architecture/etl-workflow.md"
        original_doc, original_src = doc.read_bytes(), src.read_bytes()
        src.write_bytes(original_src.replace(b"flowchart LR", b"flowchart TB"))     # the source changed: case 1
        code, problems = self.check()
        self.assertEqual(code, 1)
        self.assertEqual(len(problems), 1)
        self.assertIn("is out of date with its source", problems[0])
        self.assertIn("architecture copy AD-0005", problems[0])
        before = tree_hashes(self.ws.root)
        code, out, err = cmd(self.ws.root, "index")
        self.assertEqual(code, 0)
        self.assertIn("is out of date with its source", err)                  # a warning; nothing written there
        self.assertEqual(tree_hashes(self.ws.root), before)
        code, out, _ = cmd(self.ws.root, "index", "--check")
        self.assertEqual(code, 1)
        self.assertIn("is out of date with its source", out)
        apply_printed_copy(self.ws, rel)
        self.assertEqual(self.check(), (0, []))
        src.write_bytes(original_src)
        doc.write_bytes(original_doc)
        text = doc.read_bytes().decode("utf-8")
        doc.write_bytes(text.replace("flowchart LR", "flowchart RL", 1).encode("utf-8"))   # edited by hand: case 2
        problems = self.check()[1]
        self.assertTrue(any("was edited by hand" in p and "(E15)" in p and "apply to source" in p for p in problems),
                        problems)
        self.assertFalse(any("reconcile" in p or "run `python -m tools.design index`" in p for p in problems))
        src.write_bytes(original_src.replace(b"flowchart LR", b"flowchart TB"))          # both: case 3
        self.assertTrue(any("have both changed" in p for p in self.check()[1]))
        doc.write_bytes(original_doc)
        src.write_bytes(original_src)
        marker = re.compile(r"(<!-- diagram:start AD-0005) sha256:[0-9a-f]{16}")
        doc.write_bytes(marker.sub(r"\1", text).encode("utf-8"))                          # no fingerprint, same text
        self.assertTrue(any("fingerprint is missing" in p for p in self.check()[1]))
        doc.write_bytes(marker.sub(r"\1", text.replace("flowchart LR", "flowchart RL", 1)).encode("utf-8"))
        self.assertTrue(any("has no fingerprint and differs" in p for p in self.check()[1]))
        doc.write_bytes(original_doc)
        self.assertEqual(self.check(), (0, []))

    def test_e14_wrong_source_path_unknown_retired_feature_owned_and_embedded_ids(self):
        doc = self.extracted("AD-0001", "docs/architecture/conventions.md")
        text = doc.read_bytes().decode("utf-8")
        doc.write_bytes(text.replace("from diagrams/conventions_legend", "from diagrams/old_legend").encode("utf-8"))
        problems = self.check()[1]
        self.assertTrue(any("names its source as diagrams/old_legend" in p and "E14" in p for p in problems), problems)
        doc.write_bytes(text.encode("utf-8"))
        region = ("\n<!-- diagram:start {} -->\n<!-- diagram:end -->\n")
        base = text.replace("\r\n", "\n")
        cases = {"AD-0999": "unknown diagram ID", "AD-0002": "is still embedded"}
        f = new_feature(self.ws.root, "Owner")
        ownership.new_diagram(self.ws.root, f.feature_id, "Proposed one")
        cases["FD-0001-D1"] = "current-state documents show only document-owned diagrams"
        for ident, want in cases.items():
            with self.subTest(ident):
                doc.write_bytes((base + region.format(ident)).encode("utf-8"))
                self.assertTrue(any(want in p for p in self.check()[1]), self.check()[1])
        doc.write_bytes(text.encode("utf-8"))

    def test_duplicate_raw_block_and_not_shown(self):
        d = self.d("AD-0004")
        write_source(self.ws, d)
        extract(self.ws, [d], self.snapshot)
        problems = self.check()[1]
        self.assertIn("docs/architecture/database-schema.md: line 213: this Mermaid block is a second copy of AD-0004 "
                      f"(its source is {source_path('AD-0004')}): technical-lead replaces it with the generated copy "
                      "(`python -m tools.design architecture copy AD-0004`) (E2)", problems)
        self.assertEqual(len(self.rows()), 14)                                # counted once
        doc = self.ws.root / "docs/architecture/database-schema.md"
        text = doc.read_bytes().decode("utf-8")
        raw = "\n".join(["```mermaid", *d["mermaid_lines"], "```"])
        doc.write_bytes(text.replace("\r\n", "\n").replace(raw + "\n", "").encode("utf-8"))   # removed by mistake
        problems = self.check()[1]
        self.assertTrue(any("does not show AD-0004" in p and "(U3)" in p for p in problems), problems)
        self.assertEqual(len(self.rows()), 14)
        code, out, _ = cmd(self.ws.root, "architecture", "copy", "AD-0004", "--json")
        self.assertEqual(json.loads(out)["documents"][0]["not_shown"][0]["diagram_id"], "AD-0004")

    def test_copy_refusals(self):
        for args, want in ((["AD-0001"], "still embedded"), (["AD-0999"], "not in the registry"),
                           (["--document", "conventions.md"], "has no extracted"), ([], "not both")):
            with self.subTest(args):
                code, _, err = cmd(self.ws.root, "architecture", "copy", *args)
                self.assertEqual(code, 2)
                self.assertIn(want, err)


class FeatureBlocks(Fixture):
    def test_a_feature_block_naming_an_alias_becomes_case1_and_index_refreshes_it(self):
        f = new_feature(self.ws.root, "Uses credential boundary")
        path = self.ws.root / f.path
        text = path.read_bytes().decode("utf-8")
        alias = "system-architecture/credential-boundary"
        text = text.replace("## 1. Objective\n", f"## 1. Objective\n\n<!-- diagram:start {alias} -->\n<!-- diagram:end -->\n", 1)
        path.write_bytes(text.encode("utf-8"))
        self.assertEqual(cmd(self.ws.root, "index")[0], 0)
        self.assertEqual(self.check(), (0, []))
        before = diagrams.scan(path.read_bytes().decode("utf-8"))[0]
        d = self.d("AD-0011")
        write_source(self.ws, d)
        extract(self.ws, [d], self.snapshot)
        problems = self.check()[1]
        self.assertTrue(any(f.path in p and "is out of date with its source" in p for p in problems), problems)
        apply_printed_copy(self.ws, "docs/architecture/system-architecture.md")
        self.assertEqual(cmd(self.ws.root, "index")[0], 0)
        self.assertEqual(self.check(), (0, []))
        lines = path.read_bytes().decode("utf-8").replace("\r\n", "\n").split("\n")
        b = diagrams.scan("\n".join(lines))[0][0]
        self.assertEqual(b.diagram_id, alias)                                 # the author's ID is kept
        caption = lines[b.start + 1]
        self.assertIn("[Credential boundary](../../docs/architecture/diagrams/"
                      "system-architecture_system-architecture_credential-boundary.md)", caption)   # Q2
        self.assertEqual(lines[b.start + 3:b.end - 1], [x if x.strip() else "%%" for x in d["mermaid_lines"]])
        self.assertNotEqual(before[0].fp, b.fp)

    def test_proposed_diagram_files_citing_a_former_catalog_id_keep_resolving(self):
        f = new_feature(self.ws.root, "Cites")
        created = ownership.new_diagram(self.ws.root, f.feature_id, "Derived")
        path = self.ws.root / created.path
        original = path.read_bytes().decode("utf-8")

        def cite(ident):
            text = re.sub(r'(?m)^source_diagram: ""', f"source_diagram: {ident}", original, count=1)
            text = re.sub(r'(?m)^source_document: ""', "source_document: docs/architecture/system-architecture.md", text,
                          count=1)
            text = re.sub(r'(?m)^source_heading: ""', "source_heading: credential-boundary", text, count=1)
            self.assertNotEqual(text, original)
            path.write_bytes(text.encode("utf-8"))

        cite("system-architecture/no-such-diagram")                          # the check is active
        self.assertTrue(any("source_diagram 'system-architecture/no-such-diagram'" in p for p in self.check()[1]))
        cite("system-architecture/credential-boundary")
        self.assertEqual(cmd(self.ws.root, "index")[0], 0)
        base = self.check()[1]
        self.assertFalse(any("source_diagram" in p or "source_heading" in p for p in base), base)
        d = self.d("AD-0011")
        write_source(self.ws, d)
        extract(self.ws, [d], self.snapshot)
        apply_printed_copy(self.ws, "docs/architecture/system-architecture.md")
        self.assertEqual(cmd(self.ws.root, "index")[0], 0)
        self.assertEqual(self.check()[1], base)                               # the alias still resolves after M1


# --------------------------------------------------------------------------- verify

class Verify(Fixture):
    def setUp(self):
        super().setUp()
        d = self.d("AD-0001")
        write_source(self.ws, d)
        extract(self.ws, [d], self.snapshot)
        apply_printed_copy(self.ws, "docs/architecture/conventions.md")
        self.assertEqual(cmd(self.ws.root, "index")[0], 0)
        self.assertEqual(self.check(), (0, []))
        self.saved = {p: (self.ws.root / p).read_bytes() for p in
                      [*DOCS, "docs/architecture/diagram-library.md", "docs/architecture/system-overview.md",
                       registry.REGISTRY, source_path("AD-0001")]}

    def restore(self):
        for p, data in self.saved.items():
            (self.ws.root / p).write_bytes(data)
        extra = self.ws.root / "docs/architecture/diagrams/conventions_other_x.md"
        if extra.exists():
            extra.unlink()

    def verify(self):
        code, out, _ = cmd(self.ws.root, "architecture", "verify", "--snapshot", str(self.snapshot), "--json")
        return code, json.loads(out)

    def edit(self, rel, old, new, count=1):
        path = self.ws.root / rel
        text = path.read_bytes().decode("utf-8")
        self.assertIn(old, text)
        path.write_bytes(text.replace(old, new, count).encode("utf-8"))

    def test_passes_after_the_first_document(self):
        code, result = self.verify()
        self.assertEqual((code, result["problems"], result["extracted"]), (0, [], ["AD-0001"]))
        self.assertEqual(len(result["embedded"]), 13)
        self.assertTrue(result["checks"]["V7"].startswith("not run here"))

    def test_every_class_of_deviation_is_caught(self):
        conv, src = "docs/architecture/conventions.md", source_path("AD-0001")
        same = self.d("AD-0001")["mermaid_lines"][0]
        cases = [
            ("V3", "source and copy changed alike (check passes)",
             lambda: (self.edit(src, same, same + " "), apply_printed_copy(self.ws, conv))),
            ("V3", "copy with %% for a blank line", lambda: self._percent(conv)),
            ("V3", "an embedded block changed", lambda: self.edit("docs/architecture/database-schema.md",
                                                               "erDiagram", "erDiagram ")),
            ("V4", "prose changed in the extracted document", lambda: self.edit(conv, "Example:", "Examples:")),
            ("V4", "a document not yet in scope changed", lambda: self.edit("docs/architecture/etl-workflow.md",
                                                                          "## Safety gates", "## Safety gates ")),
            ("V5", "a new raw diagram", lambda: self.edit("docs/architecture/system-overview.md", "\n## ",
                                                          "\n```mermaid\nflowchart LR\n  A\n```\n\n## ")),
            ("V6", "the legend heading renamed", lambda: self.edit(conv, "## 1. Implementation-status legend",
                                                                   "## 1. Status legend")),
            ("V6", "a diagram in diagram-library.md", lambda: self.edit("docs/architecture/diagram-library.md", "\n## ",
                                                                        "\n```mermaid\nflowchart LR\n  A\n```\n\n## ")),
            ("V2", "a title changed through relink", lambda: self._retitle()),
            ("V1", "a new document-owned entry", lambda: self._adopt_new()),
        ]
        for check, what, deviate in cases:
            with self.subTest(what):
                deviate()
                code, result = self.verify()
                self.assertEqual(code, 1, what)
                self.assertIn(check, {p["check"] for p in result["problems"]}, (what, result["problems"]))
                self.assertEqual(result["checks"][check], "fail")
                self.restore()
                self.assertEqual(self.verify()[0], 0, what)

    def _percent(self, conv):
        path = self.ws.root / conv
        lines = path.read_bytes().decode("utf-8").split("\n")
        start = next(i for i, x in enumerate(lines) if x.startswith("<!-- diagram:start AD-0001"))
        blank = next(i for i in range(start, len(lines)) if not lines[i].strip())
        lines[blank] = "%%" + ("\r" if lines[blank].endswith("\r") else "")
        path.write_bytes("\n".join(lines).encode("utf-8"))

    def _retitle(self):
        self.edit(source_path("AD-0001"), 'title: "1. Implementation-status legend"', 'title: "Legend"')
        registry.relink(self.ws.root, "AD-0001", title="Legend")

    def _adopt_new(self):
        rel = "docs/architecture/diagrams/conventions_other_x.md"
        (self.ws.root / rel).write_text("---\ndiagram_id: AD-0015\ntitle: X\nowner_document: "
                                        "docs/architecture/conventions.md\n---\n\n```mermaid\nflowchart LR\n  A\n```\n",
                                        encoding="utf-8")
        registry.adopt(self.ws.root, rel, "other")


# --------------------------------------------------------------------------- the complete synthetic M1

class CompleteM1(Fixture):
    """Steps 0-5 of section 4.5 for the four real documents, on copies, in the planned order."""

    def test_all_four_documents(self):
        ws, root = self.ws, self.ws.root
        pre = {rel: (root / rel).read_bytes().replace(b"\r\n", b"\n") for rel in DOCS}
        self.assertEqual(self.check(), (0, []))                                       # step 0
        self.assertEqual(cmd(root, "index", "--check")[0], 0)
        self.assertEqual(cmd(root, "architecture", "verify", "--snapshot", str(self.snapshot))[0], 0)
        f = new_feature(root, "Watcher")                                              # library and links stay intact
        self.assertEqual(cmd(root, "index")[0], 0)
        lib_before = designer_api.library(root)["architecture"]
        for rel in DOCS:
            ds = by_document(self.snap, rel)
            ids = [d["diagram_id"] for d in ds]
            with self.subTest(rel):
                for d in ds:                                                          # step 1 (technical-lead)
                    write_source(ws, d)
                code, problems = self.check()
                self.assertEqual(code, 1)
                self.assertEqual(len(problems), len(ds), problems)
                self.assertTrue(all("extraction not finished" in p for p in problems))
                self.assertEqual(len(self.rows()), 14)
                guard = tree_hashes(root)
                extract(ws, ds, self.snapshot)                                        # step 2 (main)
                self.assertEqual(tree_hashes(root), guard)                            # never docs/architecture/
                code, problems = self.check()
                self.assertEqual(code, 1)
                dup = [p for p in problems if "is a second copy of" in p]
                self.assertEqual(len(dup), len(ds), problems)
                self.assertEqual(set(problems) - set(dup), {"designs/index/architecture-index.md: out of date with "
                                                            "docs/architecture/ or missing: run `python -m tools.design "
                                                            "index`"})
                self.assertEqual(len(self.rows()), 14)
                guard = tree_hashes(root)
                code, out, _ = cmd(root, "architecture", "copy", "--document", rel)   # read only
                self.assertEqual((code, tree_hashes(root)), (0, guard))
                plan = apply_printed_copy(ws, rel)                                    # step 3 (technical-lead)
                self.assertEqual(len(plan["documents"][0]["replacements"]), len(ds))
                code, problems = self.check()
                self.assertEqual((code, problems), (1, ["designs/index/architecture-index.md: out of date with "
                                                        "docs/architecture/ or missing: run `python -m tools.design "
                                                        "index`"]))
                self.assertEqual(len(self.rows()), 14)
                guard = tree_hashes(root)
                self.assertEqual(cmd(root, "index")[0], 0)                            # step 4 (main)
                self.assertEqual(tree_hashes(root), guard)
                self.assertEqual(self.check(), (0, []))
                self.assertEqual(cmd(root, "index", "--check")[0], 0)
                code, out, _ = cmd(root, "architecture", "verify", "--snapshot", str(self.snapshot), "--json")
                result = json.loads(out)
                self.assertEqual((code, result["problems"]), (0, []))                 # step 5
                for d in ds:
                    self.assertIn(d["diagram_id"], result["extracted"])
                lines = (root / rel).read_bytes().decode("utf-8").replace("\r\n", "\n").split("\n")
                for b in architecture_copies.scan("\n".join(lines))[0]:
                    self.assertIn(b.diagram_id, ids)                                  # canonical IDs
                    self.assertEqual(b.fp, FINGERPRINTS[b.diagram_id])
                    body = lines[b.start + 3:b.end - 1]
                    self.assertEqual(body, self.d(b.diagram_id)["mermaid_lines"])
                    self.assertNotIn("%%", [x.strip() for x in body if x.strip() == "%%"])
                    if b.diagram_id in BLANK_LINE_DIAGRAMS:
                        self.assertIn("", body)                                       # blank lines kept
                stripped, problems = architecture_copies.strip_regions("\n".join(lines))
                self.assertEqual((stripped.encode("utf-8"), problems), (pre[rel], []))   # the V4 invariant
        reg = registry.load(root)
        self.assertEqual([e.format for e in reg.entries if e.owner_kind == "document"], ["mermaid-md"] * 14)
        self.assertEqual(len(designer_api.library(root)["architecture"][0]["diagrams"])
                         + sum(len(g["diagrams"]) for g in designer_api.library(root)["architecture"][1:]), 14)
        lib = designer_api.library(root)["architecture"]
        self.assertEqual([[x["id"] for x in g["diagrams"]] for g in lib], [[x["id"] for x in g["diagrams"]]
                                                                           for g in lib_before])
        for g in lib:
            for x in g["diagrams"]:
                self.assertEqual((x["format"], x["path"]), ("mermaid-md", source_path(x["id"])))
                fence = (root / x["path"]).read_text(encoding="utf-8").split("\n")[x["line"] - 1]
                self.assertEqual(fence.rstrip("\r"), "```mermaid")
        rendered = architecture.render_architecture_index(root)
        self.assertIn("14 diagrams (4 architecture, 2 er, 1 example, 6 process, 1 sequence).", rendered)
        self.assertEqual(rendered.count("](../../docs/architecture/diagrams/"), 14)
        for rel in DOCS:                                                              # each document shows its copies
            text = (root / rel).read_bytes().decode("utf-8")
            self.assertEqual(text.count("<!-- diagram:start AD-"), len(by_document(self.snap, rel)))
        self.assertTrue(f.feature_id)


if __name__ == "__main__":
    unittest.main()
