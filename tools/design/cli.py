"""Command line for the Feature Design Workspace.

  python -m tools.design new feature [--name NAME] [--parent PARENT] [--convert-parent] [--root DIR]
  python -m tools.design new diagram --feature FD-0001 [--title TITLE] [--root DIR]
  python -m tools.design index [--check] [--root DIR]
  python -m tools.design check [--root DIR]
  python -m tools.design designer [--root DIR]  < request.json   (the Feature Designer interface, T-97)

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

from . import architecture, dependencies, designer_api, diagrams, ownership, workspace
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
    designer = sub.add_parser("designer", help="answer one Feature Designer request (JSON on stdin, JSON on "
                                               "stdout); writes nothing")
    index = sub.add_parser("index", help="refresh each feature's generated summary table and Related features rows, "
                                         "then regenerate designs/index/feature-index.md and "
                                         "designs/index/architecture-index.md")
    index.add_argument("--check", action="store_true",
                       help="only report whether the indexes, summary tables and Related features rows are up to "
                            "date (writes nothing)")
    sub.add_parser("check", help="check every feature specification and both indexes")
    for p in (feature, diagram, designer, index, sub.choices["check"]):
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
            return _designer(root, out)
        root = workspace.find_root(args.root if args.root is not None else Path.cwd())
        if args.command == "new":
            if interactive is None:                 # a closed stdin (None) is not interactive
                interactive = sys.stdin is not None and sys.stdin.isatty()
            if args.kind == "diagram":
                return _new_diagram(args, root, out, ask or input, interactive)
            return _new_feature(args, root, out, ask or input, interactive)
        if args.command == "index":
            if args.check:
                fresh = workspace.index_is_fresh(root)
                arch_fresh = architecture.architecture_index_is_fresh(root)
                stale = workspace.stale_summaries(root) + dependencies.stale_related(root) + diagrams.stale(root)
                print(f"{workspace.INDEX} is {'up to date' if fresh else 'out of date: run `python -m tools.design index`'}",
                      file=out)
                print(f"{architecture.ARCHITECTURE_INDEX} is "
                      f"{'up to date' if arch_fresh else 'out of date: run `python -m tools.design index`'}", file=out)
                for p in stale:
                    print(f"{p.path}: {p.message}", file=out)
                return EXIT_OK if fresh and arch_fresh and not stale else EXIT_PROBLEMS
            for p in diagrams.problems(root):                    # warn before those blocks are regenerated
                if "inside a generated summary or Related features block" in p.message:
                    print(f"design: warning: {p.path}: {p.message}", file=err)
            for path in workspace.refresh_summaries(root):
                print(f"refreshed the summary table in {path}", file=out)
            for path in dependencies.refresh_related(root):
                print(f"refreshed the Related features rows in {path}", file=out)
            for path, count in diagrams.refresh(root):
                print(f"refreshed {count} diagram block{'s' if count != 1 else ''} in {path}", file=out)
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
    except (ValueError, UnicodeDecodeError, AttributeError) as exc:
        response, code = ({"version": designer_api.VERSION, "ok": False,
                           "error": {"code": "bad-request", "message": f"the request is not valid JSON: {exc}"}},
                          designer_api.EXIT_BAD)
    else:
        response, code = designer_api.handle(root, request)
    print(designer_api.dumps(response), file=out)
    return code


def _new_diagram(args, root: Path, out: TextIO, ask: Callable[[str], str], interactive: bool) -> int:
    title = args.title
    if title is None:
        if not interactive:
            raise DesignError("--title is required when not running interactively")
        title = ask("Diagram title: ")
    created = ownership.new_diagram(root, args.feature, title)
    print(f"created {created.path} ({created.diagram_id}, owned by {created.owner})", file=out)
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
