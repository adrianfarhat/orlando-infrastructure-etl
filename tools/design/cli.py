"""Command line for the Feature Design Workspace.

  python -m tools.design new feature [--name NAME] [--parent PARENT] [--convert-parent] [--root DIR]
  python -m tools.design new diagram --feature FD-0001 [--title TITLE] [--category CATEGORY] [--root DIR]
  python -m tools.design registry adopt PATH --category CATEGORY | adopt-architecture
  python -m tools.design registry relink ID [--path PATH] [--title TITLE] [--heading ANCHOR [--ordinal N]]
  python -m tools.design registry retire ID [--confirm]
  python -m tools.design resolve ID
  python -m tools.design reconcile --file PATH --line N (--discard | --apply-to-source) [--confirm TOKEN]
  python -m tools.design index [--check] [--root DIR]
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
import json
import sys
import traceback
from pathlib import Path
from typing import Callable, TextIO

from . import architecture, dependencies, designer_api, diagrams, ownership, registry, workspace
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
    retire = ops.add_parser("retire", help="retire a diagram (lists its references; the ID is never reused)")
    retire.add_argument("diagram_id", help="the diagram ID or alias")
    retire.add_argument("--confirm", action="store_true", help="retire it (without this, only the references are listed)")
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
    for p in (feature, diagram, designer, index, sub.choices["check"], adopt, adopt_arch, relink, retire, unlock,
              resolve, reconcile):
        p.add_argument("--root", type=Path, help="repository root (default: found from the current folder)")
    return parser


def main(argv: list[str] | None = None, stdout: TextIO | None = None, stderr: TextIO | None = None,
         ask: Callable[[str], str] | None = None, interactive: bool | None = None) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    try:
        args = build_parser().parse_args(argv)
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
        if args.command == "resolve":
            response, code = designer_api.handle(root, {"version": designer_api.VERSION, "op": "resolve",
                                                        "diagram_id": args.diagram_id})
            print(json.dumps(response, indent=2, sort_keys=True, ensure_ascii=False), file=out)
            return code
        if args.command == "reconcile":
            return _reconcile(args, root, out)
        if args.command == "index":
            if args.check:
                fresh = workspace.index_is_fresh(root)
                arch_fresh = architecture.architecture_index_is_fresh(root)
                diagram_fresh = registry.diagram_index_is_fresh(root)
                stale = workspace.stale_summaries(root) + dependencies.stale_related(root) + diagrams.stale(root)
                print(f"{workspace.INDEX} is {'up to date' if fresh else 'out of date: run `python -m tools.design index`'}",
                      file=out)
                print(f"{architecture.ARCHITECTURE_INDEX} is "
                      f"{'up to date' if arch_fresh else 'out of date: run `python -m tools.design index`'}", file=out)
                print(f"{registry.DIAGRAM_INDEX} is "
                      f"{'up to date' if diagram_fresh else 'out of date: run `python -m tools.design index`'}", file=out)
                for p in stale:
                    print(f"{p.path}: {p.message}", file=out)
                return EXIT_OK if fresh and arch_fresh and diagram_fresh and not stale else EXIT_PROBLEMS
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


def _registry(args, root: Path, out: TextIO) -> int:
    note = "Uncommitted working-tree changes: nothing was staged, committed or pushed."
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
    if plan.source_path:                               # the source first: a failure leaves the document as it was
        ownership.write_atomically(root / plan.source_path, plan.source_text, root=root)
    workspace.write_feature_text(root / rel, plan.document_text)
    print(f"{action}: updated {rel}" + (f" and {plan.source_path}" if plan.source_path else "")
          + ". Uncommitted working-tree changes: nothing was staged, committed or pushed.", file=out)
    return EXIT_OK

