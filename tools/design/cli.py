"""Command line for the Feature Design Workspace.

  python -m tools.design new feature [--name NAME] [--parent PARENT] [--convert-parent] [--root DIR]
  python -m tools.design new diagram --feature FD-0001 [--title TITLE] [--category CATEGORY] [--root DIR]
  python -m tools.design registry adopt PATH --category CATEGORY | adopt-architecture
  python -m tools.design registry relink ID [--path PATH] [--title TITLE] [--heading ANCHOR [--ordinal N]]
  python -m tools.design registry retire ID [--confirm]
  python -m tools.design registry move SOURCE [SOURCE ...] --to DEST [--to DEST ...] [--confirm TOKEN] [--json]
  python -m tools.design registry adopt-moves [--from OLD --to NEW [--sha256 HEX] ...] [--confirm TOKEN] [--json]
  python -m tools.design registry move-back --from NOW --to REGISTERED [--sha256 HEX] [...] [--confirm TOKEN] [--json]
  python -m tools.design registry extract ID --path SOURCE [ID --path SOURCE ...] --snapshot FILE [--confirm TOKEN] [--json]
  python -m tools.design registry extract --revert ID --heading ANCHOR [--ordinal N] [--confirm TOKEN] [--json]
  python -m tools.design architecture snapshot --out FILE [--json]
  python -m tools.design architecture copy (ID [ID ...] | --document DOC) [--json]
  python -m tools.design architecture verify --snapshot FILE [--json]
  python -m tools.design resolve ID
  python -m tools.design reconcile --file PATH --line N (--discard | --apply-to-source) [--confirm TOKEN]
  python -m tools.design index [--check] [--root DIR]
  python -m tools.design refresh-blocks --file PATH --expect SHA256 [--file ... --expect ...] [--sources-token T] [--json]
  python -m tools.design transaction status [--json]
  python -m tools.design transaction (complete | undo | abandon) ID [--confirm TOKEN] [--json]
  python -m tools.design transaction windows [--json]
  python -m tools.design transaction forget-window NAME [--confirm]
  python -m tools.design check [--root DIR]
  python -m tools.design designer [--root DIR]  < request.json   (the Feature Designer interface, T-97)
  python -m tools.design designer --serve [--root DIR]   (one JSON request per line until end of input)

Exit codes: 0 success; 1 problems found (check, index --check) or a refused designer request;
2 a usage or file error, including a refused name or destination, or a malformed designer
request. Nothing is ever overwritten. The only other program run is a read-only `git log`
when a new ID is allocated (IDs are never reused, tools/design/ids.py): new files are
ordinary uncommitted changes (never staged, committed or pushed).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import traceback
from pathlib import Path
from typing import Callable, TextIO

from . import (architecture, architecture_copies, dependencies, designer_api, diagrams, ownership, registry,
               transactions, workspace)
from .workspace import DesignError

EXIT_OK, EXIT_PROBLEMS, EXIT_FAILURE = 0, 1, 2


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise DesignError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="python -m tools.design", description="Feature Design Workspace (T-94).")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    new = sub.add_parser("new", help="create a document from a template")
    kinds = new.add_subparsers(dest="kind", required=True, metavar="KIND")
    feature = kinds.add_parser("feature", help="create a feature specification (asks for missing values)")
    feature.add_argument("--name", help="feature name, e.g. \"Pipe road intersections\"")
    # nargs="?" with const="": "--parent" with an empty or missing value (an editor may drop an
    # empty argument) means a standalone feature, never an error.
    feature.add_argument("--parent", nargs="?", const="", default=None,
                         help="parent feature ID (e.g. FD-0003) or a folder under designs/features/; "
                              "empty or omitted for a standalone feature")
    feature.add_argument("--convert-parent", action="store_true",
                         help="allow turning a standalone parent feature x.md into x/README.md")
    diagram = kinds.add_parser("diagram", help="create a proposed diagram file owned by a feature "
                                               "(the next diagram ID that was never used)")
    diagram.add_argument("--feature", required=True, help="the owning feature's ID, e.g. FD-0001")
    diagram.add_argument("--title", help="the diagram's readable name (asked for when missing)")
    diagram.add_argument("--json", action="store_true", help="print the result as one JSON object (for the "
                         "Feature Designer)")
    diagram.add_argument("--category", default="other", choices=registry.CATEGORIES,
                         help="the diagram's category (part of its file name): " + ", ".join(registry.CATEGORIES))
    reg = sub.add_parser("registry", help="change the diagram registry (designs/diagrams/registry.yml) under its lock")
    ops = reg.add_subparsers(dest="action", required=True, metavar="ACTION")
    adopt = ops.add_parser("adopt", help="register an existing, unregistered Mermaid diagram source")
    adopt.add_argument("path", help="the source file, e.g. designs/features/diagrams/x_process_y.md")
    adopt.add_argument("--category", required=True, choices=registry.CATEGORIES)
    adopt_arch = ops.add_parser("adopt-architecture", help="stage M0: register the architecture diagrams in place "
                                                           "(AD IDs, catalog IDs as aliases; no document is changed)")
    relink = ops.add_parser("relink", help="change a diagram's path or title, or re-point an embedded diagram")
    relink.add_argument("diagram_id", help="the diagram ID or alias")
    relink.add_argument("--path", help="the source's new path (a moved or renamed file)")
    relink.add_argument("--title", help="the diagram's new title (also written to a Mermaid source's front matter)")
    relink.add_argument("--heading", help="mermaid-embedded: the heading anchor the diagram is now under")
    relink.add_argument("--ordinal", type=int, help="mermaid-embedded: which diagram under that heading (default 1)")
    unlock = ops.add_parser("unlock", help="remove a stale registry lock, only after checking that the process that "
                                           "took it has ended (shows the check; removes it only with --confirm)")
    unlock.add_argument("--confirm", action="store_true", help="remove the lock if the check allows it")
    move = ops.add_parser("move", help="move feature-owned diagram sources and their registry paths as one recorded, "
                                       "recoverable move (shows the plan first; acts only with --confirm TOKEN)")
    move.add_argument("source", nargs="+", help="a diagram ID or alias, a registered source path, or a folder that "
                                                "holds only registered sources (several for a batch)")
    move.add_argument("--to", action="append", required=True,
                      help="the new path, or an existing folder to move it into (one per source, in the same order)")
    move.add_argument("--confirm", metavar="TOKEN", help="carry out exactly the plan that printed this token")
    move.add_argument("--json", action="store_true", help="print the plan or the result as JSON")
    adopt_moves = ops.add_parser("adopt-moves", help="update the registry for sources that were already renamed (by "
                                                     "VS Code, Git or another program): shows the plan first; acts only "
                                                     "with --confirm TOKEN")
    adopt_moves.add_argument("--from", dest="old", action="append",
                             help="the registered path, ID or folder (repeat with --to for a batch; omit both for every "
                                  "moved source that `check` reports, E6)")
    adopt_moves.add_argument("--to", action="append", help="where that source is now (one per --from)")
    adopt_moves.add_argument("--sha256", action="append", metavar="HEX",
                             help="the SHA-256 the source had before it was renamed (one per --from, in the same order; "
                                  "refused if the file at --to differs). Feature Designer passes the checksum it took "
                                  "just before VS Code renamed the file")
    adopt_moves.add_argument("--confirm", metavar="TOKEN", help="carry out exactly the plan that printed this token")
    adopt_moves.add_argument("--json", action="store_true", help="print the plan or the result as JSON")
    move_back = ops.add_parser("move-back", help="rename sources that were renamed while the registry still names their "
                                                 "old paths back to those paths, as one recorded, recoverable move; "
                                                 "the registry is not changed (shows the plan first; acts only with "
                                                 "--confirm TOKEN)")
    move_back.add_argument("--from", dest="old", action="append", required=True,
                           help="where the source is now (an unregistered path; repeat with --to for a batch)")
    move_back.add_argument("--to", action="append", required=True,
                           help="the diagram's registered path, or its ID (one per --from): where it goes back to")
    move_back.add_argument("--sha256", action="append", metavar="HEX",
                           help="the SHA-256 the source had before it was renamed (one per --from; refused if it differs)")
    move_back.add_argument("--confirm", metavar="TOKEN", help="carry out exactly the plan that printed this token")
    move_back.add_argument("--json", action="store_true", help="print the plan or the result as JSON")
    extract = ops.add_parser("extract", help="T-97 M1: switch the embedded architecture diagrams of one document to "
                                             "their standalone sources in docs/architecture/diagrams/ (shows the plan "
                                             "first; acts only with --confirm TOKEN; writes only the registry and the "
                                             "diagram index)")
    extract.add_argument("diagram_id", nargs="*", help="a diagram ID or alias, each followed by its --path")
    extract.add_argument("--path", action="append", default=[], help="the diagram's standalone source (one per ID)")
    extract.add_argument("--snapshot", help="the pre-migration snapshot (`architecture snapshot`)")
    extract.add_argument("--revert", action="store_true", help="set one extracted diagram back to mermaid-embedded "
                                                               "(needs --heading)")
    extract.add_argument("--heading", help="--revert: the heading anchor of the raw block in the document")
    extract.add_argument("--ordinal", type=int, help="--revert: which diagram under that heading (default 1)")
    extract.add_argument("--confirm", metavar="TOKEN", help="carry out exactly the plan that printed this token")
    extract.add_argument("--json", action="store_true", help="print the plan or the result as JSON")
    retire = ops.add_parser("retire", help="retire a diagram (lists its references; the ID is never reused)")
    retire.add_argument("diagram_id", help="the diagram ID or alias")
    retire.add_argument("--confirm", action="store_true", help="retire it (without this, only the references are listed)")
    arch = sub.add_parser("architecture", help="T-97 M1: the generated copies of architecture diagrams (read only)")
    arch_ops = arch.add_subparsers(dest="action", required=True, metavar="ACTION")
    snap = arch_ops.add_parser("snapshot", help="record the pre-migration state (documents and diagrams) in a new file")
    snap.add_argument("--out", required=True, type=Path, help="the snapshot file to create (never overwritten)")
    snap.add_argument("--json", action="store_true", help="print the result as JSON")
    copy = arch_ops.add_parser("copy", help="print the exact generated copy technical-lead applies to a document "
                                            "(writes nothing)")
    copy.add_argument("diagram_id", nargs="*", help="diagram IDs or aliases")
    copy.add_argument("--document", help="every extracted diagram of this document, e.g. system-architecture.md")
    copy.add_argument("--json", action="store_true", help="print the plan as JSON")
    ver = arch_ops.add_parser("verify", help="prove the M1 state against the snapshot (V1-V7; writes nothing)")
    ver.add_argument("--snapshot", required=True, type=Path, help="the pre-migration snapshot")
    ver.add_argument("--json", action="store_true", help="print the result as JSON")
    resolve = sub.add_parser("resolve", help="show a diagram's authoritative source (JSON); writes nothing")
    resolve.add_argument("diagram_id", help="the diagram ID or alias")
    reconcile = sub.add_parser("reconcile", help="resolve a diagram block that was edited by hand (E15): shows the "
                                                 "change first; repeat with --confirm TOKEN to apply it")
    reconcile.add_argument("--file", required=True, help="the feature document, e.g. designs/features/x.md")
    reconcile.add_argument("--line", required=True, type=int, help="the 1-based line of the block's start marker")
    how = reconcile.add_mutually_exclusive_group(required=True)
    how.add_argument("--discard", action="store_true", help="discard the manual change: regenerate the block")
    how.add_argument("--apply-to-source", action="store_true",
                     help="copy the block's Mermaid into its feature-owned source, then regenerate the block")
    reconcile.add_argument("--confirm", metavar="TOKEN", help="apply the change shown in the preview with this token")
    designer = sub.add_parser("designer", help="answer one Feature Designer request (JSON on stdin, JSON on "
                                               "stdout); writes nothing")
    designer.add_argument("--serve", action="store_true",
                          help="keep running: read one JSON request per line and write one JSON response per line "
                               "until the input ends (used by the Feature Designer extension)")
    index = sub.add_parser("index", help="refresh each feature's generated summary table and Related features rows, "
                                         "and the diagram blocks (never a hand-edited one), then regenerate "
                                         "designs/index/feature-index.md, architecture-index.md and diagram-index.md")
    index.add_argument("--check", action="store_true",
                       help="only report whether the indexes, summary tables and Related features rows are up to "
                            "date (writes nothing)")
    sub.add_parser("check", help="check every feature specification and both indexes")
    rb = sub.add_parser("refresh-blocks", help="refresh the out-of-date diagram blocks of closed feature documents as "
                                               "one recoverable update: every listed document, or rolled back; an interruption leaves a "
                                               "record to complete or undo explicitly (T-97 PR B2b-1)")
    rb.add_argument("--file", action="append", required=True, help="a feature document (repeat for each document)")
    rb.add_argument("--expect", action="append", required=True,
                    help="the SHA-256 of that document as listed (one per --file, in the same order)")
    rb.add_argument("--sources-token", help="the sources token from the listing: refused if a source changed since")
    rb.add_argument("--json", action="store_true", help="print the result as JSON")
    tx = sub.add_parser("transaction", help="show or resolve an interrupted update of closed documents (E16)")
    tx.add_argument("action", choices=["status", "complete", "undo", "abandon", "windows", "forget-window"])
    tx.add_argument("record", nargs="?", help="the record ID (tx-...), for complete, undo and abandon; the window "
                                              "record name, for forget-window")
    tx.add_argument("--confirm", metavar="TOKEN", nargs="?", const="",
                    help="carry out the action on exactly the state that was shown (forget-window takes no token)")
    tx.add_argument("--json", action="store_true", help="print the result as JSON")
    for p in (feature, diagram, designer, index, sub.choices["check"], adopt, adopt_arch, relink, retire, unlock,
              resolve, reconcile, rb, tx, move, adopt_moves, move_back, extract, snap, copy, ver):
        p.add_argument("--root", type=Path, help="repository root (default: found from the current folder)")
    return parser


def main(argv: list[str] | None = None, stdout: TextIO | None = None, stderr: TextIO | None = None,
         ask: Callable[[str], str] | None = None, interactive: bool | None = None) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    try:
        args, extra = build_parser().parse_known_args(argv)
        if extra:                                   # only `registry extract ID --path P ID --path P ...` interleaves
            if getattr(args, "action", None) == "extract" and args.command == "registry" \
                    and not any(x.startswith("-") for x in extra):
                args.diagram_id = list(args.diagram_id) + extra
            else:
                raise DesignError(f"unrecognized arguments: {' '.join(extra)}")
        if args.command == "designer":              # always answers in JSON, even without a workspace
            try:
                root = workspace.find_root(args.root if args.root is not None else Path.cwd())
            except DesignError as exc:
                print(designer_api.dumps({"version": designer_api.VERSION, "ok": False,
                                          "error": {"code": "workspace", "message": str(exc)}}), file=out)
                return designer_api.EXIT_BAD
            return _serve(root, out) if args.serve else _designer(root, out)
        root = workspace.find_root(args.root if args.root is not None else Path.cwd())
        if args.command == "new":
            if interactive is None:                 # a closed stdin (None) is not interactive
                interactive = sys.stdin is not None and sys.stdin.isatty()
            if args.kind == "diagram":
                return _new_diagram(args, root, out, ask or input, interactive)
            return _new_feature(args, root, out, ask or input, interactive)
        if args.command == "registry":
            return _registry(args, root, out)
        if args.command == "architecture":
            return _architecture(args, root, out)
        if args.command == "resolve":
            response, code = designer_api.handle(root, {"version": designer_api.VERSION, "op": "resolve",
                                                        "diagram_id": args.diagram_id})
            print(json.dumps(response, indent=2, sort_keys=True, ensure_ascii=False), file=out)
            return code
        if args.command == "reconcile":
            return _reconcile(args, root, out)
        if args.command == "refresh-blocks":
            return _refresh_blocks(args, root, out)
        if args.command == "transaction":
            return _transaction(args, root, out)
        if args.command == "index":
            if args.check:
                fresh = workspace.index_is_fresh(root)
                arch_fresh = architecture.architecture_index_is_fresh(root)
                diagram_fresh = registry.diagram_index_is_fresh(root)
                stale = (workspace.stale_summaries(root) + dependencies.stale_related(root) + diagrams.stale(root)
                         + architecture_copies.stale(root))        # T-97 M1: technical-lead applies these
                print(f"{workspace.INDEX} is {'up to date' if fresh else 'out of date: run `python -m tools.design index`'}",
                      file=out)
                print(f"{architecture.ARCHITECTURE_INDEX} is "
                      f"{'up to date' if arch_fresh else 'out of date: run `python -m tools.design index`'}", file=out)
                print(f"{registry.DIAGRAM_INDEX} is "
                      f"{'up to date' if diagram_fresh else 'out of date: run `python -m tools.design index`'}", file=out)
                for p in stale:
                    print(f"{p.path}: {p.message}", file=out)
                return EXIT_OK if fresh and arch_fresh and diagram_fresh and not stale else EXIT_PROBLEMS
            with registry.lock(root):                # D3: the same lock as every other writer
                transactions.guard(root)                # never a document held by an interrupted update
                return _index(root, out, err)
        problems = workspace.check(root)
        features, _ = workspace.discover(root)
        for p in problems:
            print(f"{p.path}: {p.message}", file=out)
        print(f"{len(features)} feature file(s), {len(problems)} problem(s)", file=out)
        return EXIT_PROBLEMS if problems else EXIT_OK
    except DesignError as exc:
        print(f"design: error: {exc}", file=err)
        return EXIT_FAILURE
    except (KeyboardInterrupt, EOFError):           # Ctrl+C, or Ctrl+Z / end of input at a prompt
        print("design: cancelled; nothing was created or changed", file=err)
        return EXIT_FAILURE
    except SystemExit as exc:                       # --help
        return EXIT_OK if exc.code in (0, None) else EXIT_FAILURE
    except Exception:                               # never let a bug look like "problems found"
        print("design: internal error; nothing more was done. Details:", file=err)
        print("\n".join(traceback.format_exc().splitlines()[-20:]), file=err)
        return EXIT_FAILURE


def _index(root: Path, out: TextIO, err: TextIO) -> int:
    """`index` (not --check), inside the registry lock."""
    for p in diagrams.problems(root):                    # warn before those blocks are regenerated
        if "inside a generated summary or Related features block" in p.message:
            print(f"design: warning: {p.path}: {p.message}", file=err)
    for path in workspace.refresh_summaries(root):
        print(f"refreshed the summary table in {path}", file=out)
    for path in dependencies.refresh_related(root):
        print(f"refreshed the Related features rows in {path}", file=out)
    for path, count in diagrams.refresh(root):
        print(f"refreshed {count} diagram block{'s' if count != 1 else ''} in {path}", file=out)
    for p in diagrams.stale(root):                       # conflicts are never overwritten (U13)
        if "(E15)" in p.message:
            print(f"design: warning: {p.path}: {p.message}", file=err)
    for p in architecture_copies.stale(root):           # T-97 M1: never written by the tooling (C1)
        print(f"design: warning: {p.path}: {p.message}", file=err)
    for p in workspace.not_refreshable(root):           # one line per file; nothing is repaired
        print(f"design: warning: {p.path}: {p.message}; run `python -m tools.design check`", file=err)
    fresh = workspace.index_is_fresh(root)
    path = workspace.write_index(root)
    print(f"{path} is already up to date" if fresh else f"wrote {path}", file=out)
    arch_fresh = architecture.architecture_index_is_fresh(root)
    path = architecture.write_architecture_index(root)
    if path is None:
        print(f"no {workspace.ARCHITECTURE}/ folder, so there is no architecture index", file=out)
    else:
        print(f"{path} is already up to date" if arch_fresh else f"wrote {path}", file=out)
    diagram_fresh = registry.diagram_index_is_fresh(root)
    path = registry.write_diagram_index(root)
    if path is not None:
        print(f"{path} is already up to date" if diagram_fresh else f"wrote {path}", file=out)
    return EXIT_OK


def _designer(root: Path, out: TextIO) -> int:
    """One JSON request from stdin, one JSON response on stdout (designer_api)."""
    try:
        raw = sys.stdin.buffer.read() if sys.stdin is not None and hasattr(sys.stdin, "buffer") else sys.stdin.read()
        request = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except (ValueError, UnicodeDecodeError, AttributeError, RecursionError) as exc:
        response, code = ({"version": designer_api.VERSION, "ok": False,
                           "error": {"code": "bad-request",
                                     "message": f"the request is not valid JSON: {type(exc).__name__}: {exc}"[:500]}},
                          designer_api.EXIT_BAD)
    else:
        response, code = designer_api.handle(root, request)
    print(designer_api.dumps(response), file=out)
    return code


def _serve(root: Path, out: TextIO) -> int:
    """One JSON request per input line, one JSON response per output line, until end of input.
    A request may carry "request_id", which the response echoes, so a client can match them."""
    source = sys.stdin.buffer if sys.stdin is not None and hasattr(sys.stdin, "buffer") else sys.stdin
    for raw in iter(source.readline, b"" if source is not sys.stdin else ""):
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        if not line.strip():
            continue
        request_id = None
        try:
            request = json.loads(line)
        except (ValueError, RecursionError) as exc:
            response = {"version": designer_api.VERSION, "ok": False,
                        "error": {"code": "bad-request",
                                  "message": f"the request is not valid JSON: {type(exc).__name__}: {exc}"[:500]}}
        else:
            if isinstance(request, dict):
                request_id = request.pop("request_id", None)
            response, _code = designer_api.handle(root, request)
        if request_id is not None:
            response = {**response, "request_id": request_id}
        out.write(designer_api.dumps(response) + "\n")
        out.flush()
    return EXIT_OK


def _new_diagram(args, root: Path, out: TextIO, ask: Callable[[str], str], interactive: bool) -> int:
    title = args.title
    if title is None:
        if not interactive:
            raise DesignError("--title is required when not running interactively")
        title = ask("Diagram title: ")
    created = ownership.new_diagram(root, args.feature, title, args.category)
    if getattr(args, "json", False):
        print(json.dumps({"path": created.path, "diagram_id": created.diagram_id, "owner": created.owner,
                          "category": created.category}, sort_keys=True), file=out)
        return EXIT_OK
    print(f"created {created.path} ({created.diagram_id}, owned by {created.owner}, category {created.category}) "
          f"and registered it in {registry.REGISTRY}", file=out)
    print("Attach it to a feature with a diagram block (see designs/README.md). This is an uncommitted "
          "working-tree change: nothing was staged, committed or pushed.", file=out)
    return EXIT_OK


def _new_feature(args, root: Path, out: TextIO, ask: Callable[[str], str], interactive: bool) -> int:
    name, parent = args.name, args.parent
    if name is None:
        if not interactive:
            raise DesignError("--name is required when not running interactively")
        name = ask("Feature name: ")
        if args.parent is None:
            parent = ask("Parent feature ID or folder (Enter for a standalone feature): ")
    with registry.lock(root):                       # D3: the same lock as every other writer
        transactions.guard(root)                    # it may move a feature and refresh others
        created = workspace.new_feature(root, name, parent or None, args.convert_parent)
    if created.moved:
        print(f"moved {created.moved[0]} -> {created.moved[1]} (same feature ID; its relative links were "
              "adjusted)", file=out)
    for path in created.refreshed:
        print(f"refreshed the Related features rows in {path} (links to the moved feature)", file=out)
    print(f"created {created.path} ({created.feature_id})", file=out)
    print(f"updated {created.index}", file=out)
    print("These are uncommitted working-tree changes: nothing was staged, committed or pushed.", file=out)
    return EXIT_OK


def _move(args, root: Path, out: TextIO) -> int:
    """`registry move`, `registry adopt-moves` (PR B2b-2a S2) and `registry move-back` (PR B2b-2b): the
    plan first, then exactly that plan."""
    from . import moves
    mode = {"move": "move", "adopt-moves": "adopt", "move-back": "restore"}[args.action]
    if mode == "move":
        if len(args.source) != len(args.to):
            raise DesignError("give one --to for every source, in the same order")
        reqs = list(zip(args.source, args.to))
    else:
        olds, news = args.old or [], args.to or []
        if len(olds) != len(news):
            raise DesignError("give one --to for every --from, in the same order")
        shas = args.sha256
        if shas is not None:                        # B2b-2b: the checksum from before the rename, one per pair
            if len(shas) != len(olds):
                raise DesignError("give one --sha256 for every --from, in the same order")
            bad = [h for h in shas if not transactions.HEX64.match(h)]
            if bad:
                raise DesignError(f"--sha256 must be 64 lowercase hexadecimal characters, not {bad[0]!r}")
            reqs = [(o, n, h) for o, n, h in zip(olds, news, shas)]
        else:
            reqs = list(zip(olds, news))
        reqs = reqs or None
    if args.confirm is None:
        p = moves.plan(root, mode, reqs)
        if args.json:
            print(json.dumps(p.to_json(), sort_keys=True, ensure_ascii=False), file=out)
            return EXIT_PROBLEMS if not p.problems else EXIT_FAILURE
        if p.problems:
            for s in p.skipped:
                print(f"not adopted: {s}", file=out)
            raise DesignError({"move": "the move", "adopt": "the adoption", "restore": "the move back"}[mode]
                              + " was refused; " + moves.refused(p))
        print({"move": "registry move (the tooling renames the files, then the registry):",
               "adopt": "registry adopt-moves (the files were already renamed: only the registry follows):",
               "restore": "registry move-back (the tooling renames the files back to their registered paths; the "
                          "registry is not changed):"}[mode], file=out)
        for r in p.renames:
            print(f"  {r['diagram_id']}: {r['from']} -> {r['to']}"
                  + (f" (letter case only: through {r['via']})" if r["via"] else ""), file=out)
        for s in p.skipped:
            print(f"  not adopted: {s}", file=out)
        for w in p.warnings:
            print(f"  warning: {w}", file=out)
        refs = sum(len(v) for v in p.references.values())
        print("The registry is not changed, and the source contents stay the same." if mode == "restore" else
              "Only the path of these registry entries changes: the IDs, owners, titles, categories, aliases and the "
              "source contents stay the same.", file=out)
        if refs and mode != "restore":
            print(f"{refs} reference(s) show these diagrams; their generated captions and links are refreshed afterwards, "
                  "separately (Feature Designer, or `refresh-blocks`), never as part of the move.", file=out)
        print(f"Nothing was changed. To carry out exactly this, repeat with --confirm {p.token}", file=out)
        return EXIT_PROBLEMS
    result = moves.execute(root, mode, reqs, args.confirm)
    if args.json:
        print(json.dumps(result, sort_keys=True, ensure_ascii=False), file=out)
        return EXIT_OK
    for r in result["renames"]:
        print(f"{ {'move': 'moved', 'adopt': 'adopted', 'restore': 'moved back'}[mode]} {r['diagram_id']}: {r['from']} -> "
              f"{r['to']}", file=out)
    print(("the move back is complete: every source is at its registered path; the registry was not changed"
           if mode == "restore" else "the move is complete: the registry names the new paths")
          + (f" and {registry.DIAGRAM_INDEX} was regenerated." if result["index"]["regenerated"] else "."), file=out)
    for w in result["warnings"]:
        print(f"warning: {w}", file=out)
    docs = [d for d in result["refresh"]["documents"] if not d["excluded"]]
    held = [d for d in result["refresh"]["documents"] if d["excluded"]]
    if docs:
        print(f"{len(docs)} closed document(s) still show the old path in a diagram block (E14). Refresh them with Feature "
              "Designer's Update closed documents, or:", file=out)
        print("  python -m tools.design refresh-blocks " + " ".join(f"--file {d['path']} --expect {d['sha256']}" for d in docs)
              + f" --sources-token {result['refresh']['sources_token']}", file=out)
    for d in held:
        print(f"{d['path']} also shows a moved diagram and is not refreshed now: {d['excluded']}", file=out)
    print("Uncommitted working-tree changes: nothing was staged, committed or pushed.", file=out)
    return EXIT_OK


def _extract(args, root: Path, out: TextIO) -> int:
    """`registry extract` (T-97 M1): the plan first, then exactly that plan."""
    note = "Uncommitted working-tree changes: nothing was staged, committed or pushed."
    if args.revert:
        if len(args.diagram_id) != 1 or args.path or args.snapshot:
            raise DesignError("--revert takes one diagram ID and --heading (no --path, no --snapshot)")
        if args.confirm is None:
            plan = registry.plan_revert(root, args.diagram_id[0], args.heading, args.ordinal)
        else:
            plan = registry.revert(root, args.diagram_id[0], args.heading, args.ordinal, args.confirm)
    else:
        if args.heading or args.ordinal:
            raise DesignError("--heading and --ordinal belong to --revert")
        if not args.snapshot:
            raise DesignError("give --snapshot FILE (the pre-migration record from `architecture snapshot`)")
        if len(args.diagram_id) != len(args.path):
            raise DesignError("give one --path after every diagram ID, in the same order")
        items = list(zip(args.diagram_id, args.path))
        plan = (registry.plan_extract(root, items, args.snapshot) if args.confirm is None
                else registry.extract(root, items, args.snapshot, args.confirm))
    if args.json:
        print(json.dumps(plan, sort_keys=True, ensure_ascii=False), file=out)
        if plan.get("done"):
            return EXIT_OK
        return EXIT_FAILURE if plan["problems"] else EXIT_PROBLEMS
    if plan["problems"]:
        raise DesignError(f"the {plan['action']} was refused; nothing was changed:\n"
                          + "\n".join(f"  - {p}" for p in plan["problems"]))
    if plan["action"] == "revert":
        head = (f"registry extract --revert: {plan['diagram_id']} back to mermaid-embedded in {plan['document']} "
                f"#{plan['heading']} ({plan['ordinal']}); its source {plan['path']} stays")
        lines = []
    else:
        head = f"registry extract: {len(plan['diagrams'])} diagram(s) of {plan['document']}"
        lines = [f"  {d['diagram_id']}: mermaid-embedded #{d['anchor']} ({d['ordinal']}) -> mermaid-md {d['path']} "
                 f"(Mermaid SHA-256 {d['mermaid_sha256']})" for d in plan["diagrams"]]
        lines.append(f"  snapshot {plan['snapshot']['path']} (SHA-256 {plan['snapshot']['sha256']})")
    if plan.get("done"):
        print(("reverted " if plan["action"] == "revert" else "extracted ") + head.split(": ", 1)[1], file=out)
        for line in lines:
            print(line, file=out)
        print(f"wrote {', '.join(plan['writes'])}; nothing under docs/architecture/ was changed. " + note, file=out)
        return EXIT_OK
    print(head + ":", file=out)
    for line in lines:
        print(line, file=out)
    print(f"Only the registry entries' format and path change (anchor and ordinal "
          f"{'are added' if plan['action'] == 'revert' else 'are removed'}); it writes {', '.join(plan['writes'])} "
          "and nothing under docs/architecture/.", file=out)
    print(f"Nothing was changed. To carry out exactly this, repeat with --confirm {plan['token']}", file=out)
    return EXIT_PROBLEMS


def _architecture(args, root: Path, out: TextIO) -> int:
    """`architecture snapshot | copy | verify` (T-97 M1). Nothing under docs/architecture/ is written."""
    if args.action == "snapshot":
        target = Path(args.out).resolve()
        if _inside(root, target):
            ownership.guard_write(root, target)        # never under docs/architecture/
        if target.exists():
            raise DesignError(f"{args.out} exists; a snapshot is never overwritten")
        data = architecture_copies.snapshot(root)
        text = json.dumps(data, sort_keys=True, ensure_ascii=False, indent=1) + "\n"
        # whole or not at all: a temporary file, then a link that fails if the name exists (never overwritten)
        ownership.create_exclusively(target, text, str(args.out))
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if args.json:
            print(json.dumps({"path": str(target), "sha256": sha, "commit": data["commit"],
                              "diagrams": len(data["diagrams"]), "documents": len(data["documents"])}, sort_keys=True),
                  file=out)
        else:
            print(f"wrote {target} (SHA-256 {sha}): {len(data['diagrams'])} diagrams, {len(data['documents'])} "
                  f"documents, commit {data['commit'] or '(none)'}", file=out)
        return EXIT_OK
    if args.action == "copy":
        plan = architecture_copies.plan_copies(root, args.diagram_id or None, args.document)
        if args.json:
            print(json.dumps(plan, sort_keys=True, ensure_ascii=False), file=out)
            return EXIT_OK
        for doc in plan["documents"]:
            print(f"{doc['path']} (LF SHA-256 now {doc['sha256_before']}, after these replacements "
                  f"{doc['sha256_after']}):", file=out)
            for r in doc["replacements"]:
                print(f"\n{r['diagram_id']}: replace lines {r['start_line']}-{r['end_line']} ({r['kind']}; old text "
                      f"SHA-256 {r['old_sha256']}{'' if r['old_unique'] else '; NOT unique in the document'}) with:",
                      file=out)
                print(r["new_text"], file=out)
            for d in doc["current"]:
                print(f"\n{d}: the generated copy is current; nothing to replace", file=out)
            for d in doc["not_shown"]:
                print(f"\n{d['diagram_id']}: not shown in {doc['path']}; add where it belongs:", file=out)
                print(d["new_text"], file=out)
        print("\nNothing was written: technical-lead applies this text in docs/architecture/, then runs "
              "`python -m tools.design check` and `architecture verify`.", file=out)
        return EXIT_OK
    result = architecture_copies.verify(root, args.snapshot)
    if args.json:
        print(json.dumps(result, sort_keys=True, ensure_ascii=False), file=out)
    else:
        for v, state in result["checks"].items():
            print(f"{v}: {state}", file=out)
        for p in result["problems"]:
            print(f"  {p['check']}: {p['message']}", file=out)
        print(f"{len(result['extracted'])} extracted, {len(result['embedded'])} embedded; "
              f"{len(result['problems'])} problem(s) against snapshot {result['snapshot']['sha256']}", file=out)
    return EXIT_OK if result["ok"] else EXIT_PROBLEMS


def _inside(root: Path, target: Path) -> bool:
    try:
        target.relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def _registry(args, root: Path, out: TextIO) -> int:
    note = "Uncommitted working-tree changes: nothing was staged, committed or pushed."
    if args.action in ("move", "adopt-moves", "move-back"):
        return _move(args, root, out)
    if args.action == "extract":
        return _extract(args, root, out)
    if args.action == "adopt":
        e = registry.adopt(root, args.path, args.category)
        print(f"registered {e.diagram_id} ({e.path}, owned by {e.owner_ref}). {note}", file=out)
        return EXIT_OK
    if args.action == "adopt-architecture":
        created = registry.adopt_architecture(root)
        for e in created:
            print(f"registered {e.diagram_id} = {e.aliases[0]} ({e.category}, in place in {e.path})", file=out)
        print(f"{len(created)} architecture diagram(s) registered; no document was changed. "
              "Run `python -m tools.design index`. " + note, file=out)
        return EXIT_OK
    if args.action == "unlock":
        state = registry.unlock(root, args.confirm)
        if not state.exists:
            print("there is no registry lock; nothing to do", file=out)
            return EXIT_OK
        print(f"{registry.LOCK}: process {state.pid}, computer {state.host or '(unknown)'}, "
              f"{int(state.age_seconds // 60)} minute(s) old: {state.reason}", file=out)
        if not state.removable:
            print("the lock was kept", file=out)
            return EXIT_PROBLEMS
        if not args.confirm:
            print("nothing was changed: repeat with --confirm to remove it", file=out)
            return EXIT_PROBLEMS
        print("removed the stale registry lock", file=out)
        return EXIT_OK
    if args.action == "relink":
        e = registry.relink(root, args.diagram_id, path=args.path, title=args.title, heading=args.heading,
                            ordinal=args.ordinal)
        print(f"relinked {e.diagram_id}: {e.path}" + (f" #{e.anchor} ({e.ordinal})" if e.format == "mermaid-embedded"
                                                      else "") + f", title {e.title!r}. Run `python -m tools.design "
                                                                 f"index` to refresh the blocks that show it. {note}",
              file=out)
        return EXIT_OK
    e, refs, done = registry.retire(root, args.diagram_id, args.confirm)
    print(f"{e.diagram_id} ({e.title}) is referenced {len(refs)} time(s):", file=out)
    for r in refs:
        print(f"  {r}", file=out)
    if not done:
        print("nothing was changed: repeat with --confirm to retire it (its ID is never issued again)", file=out)
        return EXIT_PROBLEMS
    print(f"retired {e.diagram_id} on {e.retired}; the references above are now reported (E11). {note}", file=out)
    return EXIT_OK


def _reconcile(args, root: Path, out: TextIO) -> int:
    action = "discard" if args.discard else "apply-to-source"
    try:
        plan = diagrams.plan_reconcile(root, args.file, args.line, action)
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        raise DesignError(str(exc)) from None
    rel = plan.rel                                      # a feature document inside the repository
    if args.confirm is None:
        print(f"{action} for the {plan.block.diagram_id} block on line {args.line} of {rel} (state: {plan.state}).",
              file=out)
        if plan.warning:
            print(f"Warning: {plan.warning}.", file=out)
        print(plan.diff or "(no change)", file=out, end="" if plan.diff.endswith("\n") else "\n")
        print(f"Nothing was changed. To apply exactly this change, repeat with --confirm {plan.token}", file=out)
        return EXIT_OK
    if args.confirm != plan.token:
        print("the document or the diagram source changed since the preview: nothing was changed; "
              "preview again (without --confirm)", file=out)
        return EXIT_PROBLEMS
    ownership.guard_write(root, root / rel)            # never docs/architecture/ (plan_reconcile also refuses it)
    with registry.lock(root):                          # D3: the same lock as every other writer
        transactions.guard(root, [rel])
        again = diagrams.plan_reconcile(root, args.file, args.line, action)   # nothing changed while waiting
        if again.token != args.confirm:
            print("the document or the diagram source changed since the preview: nothing was changed; "
                  "preview again (without --confirm)", file=out)
            return EXIT_PROBLEMS
        if plan.source_path:                           # the source first: a failure leaves the document as it was
            ownership.write_atomically(root / plan.source_path, plan.source_text, root=root)
        workspace.write_feature_text(root / rel, plan.document_text)
    print(f"{action}: updated {rel}" + (f" and {plan.source_path}" if plan.source_path else "")
          + ". Uncommitted working-tree changes: nothing was staged, committed or pushed.", file=out)
    return EXIT_OK


def _refresh_blocks(args, root: Path, out: TextIO) -> int:
    if len(args.file) != len(args.expect):
        raise DesignError("give one --expect for every --file, in the same order")
    result = transactions.update(root, list(zip(args.file, args.expect)), args.sources_token)
    if args.json:
        print(json.dumps(result, sort_keys=True, ensure_ascii=False), file=out)
        return EXIT_OK
    for f in result["files"]:
        print(f"refreshed {', '.join(f['blocks'])} in {f['path']}", file=out)
    print(f"updated {len(result['files'])} document(s). Uncommitted working-tree changes: nothing was staged, "
          "committed or pushed.", file=out)
    for w in result.get("warnings", []):
        print(f"warning: {w}", file=out)
    return EXIT_OK


def _transaction(args, root: Path, out: TextIO) -> int:
    if args.action == "windows":
        found = transactions.window_records(root)
        if args.json:
            print(json.dumps({"windows": found}, sort_keys=True, ensure_ascii=False), file=out)
            return EXIT_OK
        if not found:
            print("no Feature Designer window record", file=out)
        for w in found:
            if w["state"] == "unreadable":
                print(f"{w['name']}: {w['problem']}; it blocks every update of closed documents", file=out)
                continue
            print(f"{w['name']}: process {w['pid']} on {w['host']}, {w['state']} (heartbeat {int(w['age'])} s ago)", file=out)
            for d in w["documents"]:
                print(f"  {d['path']}" + (" (unsaved changes)" if d["dirty"] else ""), file=out)
        if any(w["state"] != "responding" for w in found):
            print("A record that is not responding or cannot be read keeps protecting its documents. Remove it only if "
                  "that window is no longer open: transaction forget-window NAME --confirm", file=out)
        return EXIT_OK
    if args.action == "forget-window":
        if not args.record:
            raise DesignError("give the window record name: transaction forget-window NAME")
        result = transactions.forget_window(root, args.record, args.confirm is not None)
        w = result.get("window")
        if w:
            print(f"{w['name']}: " + (w["problem"] if w["state"] == "unreadable" else
                                     f"process {w['pid']} on {w['host']}, not responding for {int(w['age'])} s"), file=out)
            for d in w["documents"]:
                print(f"  {d['path']}" + (" (unsaved changes)" if d["dirty"] else ""), file=out)
        print(result["message"], file=out)
        return EXIT_OK if result["ok"] else EXIT_PROBLEMS
    if args.action == "status":
        found = transactions.status(root)
        cleanup = transactions.pending_cleanup(root)   # pre-PR review: discoverable, but not an unresolved operation
        if args.json:
            print(json.dumps({"records": found, "cleanup": cleanup}, sort_keys=True, ensure_ascii=False), file=out)
            return EXIT_PROBLEMS if found else EXIT_OK
        if not found:
            print("no interrupted update", file=out)
        for r in found:
            _print_record(r, out)
        for c in cleanup:
            print(f"cleanup pending: {c['folder']}: {c['kind']}. It holds nothing and is never carried out again; diagram "
                  "commands retry its removal, which may stay pending until the cause (for example another program "
                  "using the folder) is removed", file=out)
        return EXIT_PROBLEMS if found else EXIT_OK
    if not args.record:
        raise DesignError(f"give the record ID: transaction {args.action} tx-...")
    if args.confirm is None:
        shown = [r for r in transactions.status(root) if r["id"] == args.record]
        if not shown:
            print(f"{args.record}: no such unresolved update; nothing to do", file=out)
            return EXIT_OK
        _print_record(shown[0], out)
        print(f"Nothing was changed. To {args.action} exactly this, repeat with --confirm {shown[0]['token']}", file=out)
        return EXIT_PROBLEMS
    result = transactions.resolve(root, args.record, args.action, args.confirm)
    if args.json:
        print(json.dumps(result, sort_keys=True, ensure_ascii=False), file=out)
    else:
        if result.get("note"):
            print(result["note"], file=out)
        print(f"{args.record}: {result['message']}", file=out)
        for f in result.get("files", []):
            print(f"  {f['path']}: {f['state']}", file=out)
    return EXIT_OK if result["ok"] else EXIT_PROBLEMS


def _print_record(r: dict, out: TextIO) -> None:
    if not r["valid"]:
        print(f"{r['id']}: the record cannot be read ({r['problem']}). Only abandon is possible: "
              f"{r['abandon']['effect']}", file=out)
        return
    print(f"{r['id']} (created {r['created']}, state {r['state']}{', last action ' + r['action'] if r['action'] else ''}"
          f"{', STILL RUNNING' if r['live'] else ''}):", file=out)
    for f in r["files"]:
        print(f"  {f['path']}: {f['state']} ({', '.join(f['blocks'])})", file=out)
    if r["source_changes"]:
        print(f"  changed since it was prepared: {', '.join(r['source_changes'])}", file=out)
    c, u = r["complete"], r["undo"]
    if r.get("tool") == transactions.MOVE_TOOL:     # a registry move (version 2): renames and the registry
        print("  (" + {"adopt": "observed renames: only the registry follows",
                       "restore": "tool-initiated move back: the sources go back to their registered paths; the "
                                  "registry is not changed"}.get(r["mode"], "tool-initiated move") + ")", file=out)
        print("  complete: " + (c["reason"] if not c["possible"] else
                                f"finishes {', '.join(c['writes']) or 'nothing (only the record is removed)'}" +
                                (f"; leaves {', '.join(c['left_alone'])} alone" if c["left_alone"] else "") +
                                (f" ({c['reason']})" if c["reason"] else "")), file=out)
        print("  undo: " + (u["reason"] if not u["possible"] else
                            f"puts back {', '.join(u['restores']) or 'nothing (only the record is removed)'}" +
                            (f"; leaves {', '.join(u['left_alone'])} alone" if u["left_alone"] else "")), file=out)
        print(f"  abandon: {r['abandon']['effect']}", file=out)
        return
    print("  complete: " + (c["reason"] if not c["possible"] else
                            f"writes the update into {len(c['writes'])} document(s)" +
                            (f"; leaves {', '.join(c['left_alone'])} alone" if c["left_alone"] else "")), file=out)
    print("  undo: " + (u["reason"] if not u["possible"] else
                        f"restores the original of {len(u['restores'])} document(s)" +
                        (f"; leaves {', '.join(u['left_alone'])} alone" if u["left_alone"] else "")), file=out)
    print(f"  abandon: {r['abandon']['effect']}", file=out)
