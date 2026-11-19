"""Command line: `python -m tools.impact validate [--root DIR] [--format text|json] [--out [DIR]]`.

Exit codes:
  0  validation completed with no ERROR findings (WARNINGs allowed);
  1  validation completed with at least one ERROR finding, including a missing or
     malformed configuration file (reported as a registry-invalid finding);
  2  operational or internal failure that prevented reliable validation: bad
     arguments, Git missing or failing, an unreadable file, an unusable --out
     target, or an unexpected internal error.

Output: without --out, the selected format is printed to stdout and no file is
written. With --out, both validate.txt and validate.json are written to the given
directory (default .local/impact/ under the repository root) and the selected
format is also printed. The only files this tool ever writes are those two.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import TextIO

from . import gitfiles
from .config import LoadError, Problem, check_files, load_for_report
from .paths import printable
from .findings import Report, from_problems, render_json, render_text
from .resolve import ambiguities

EXIT_OK, EXIT_ERRORS, EXIT_FAILURE = 0, 1, 2
DEFAULT_OUT = ".local/impact"
REPORT_FILES = ("validate.txt", "validate.json")


class UsageError(Exception):
    """Bad arguments or an unusable --root (exit code 2)."""


class OutputError(Exception):
    """An --out target that must not be written (exit code 2)."""


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="python -m tools.impact", description="Change-impact tool (T-83).")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    v = sub.add_parser("validate", help="check impact.yml and the registry against the working tree")
    v.add_argument("--root", type=Path, help="repository to validate (default: the one containing the "
                                             "current folder)")
    v.add_argument("--format", choices=("text", "json"), default="text", help="report printed to stdout")
    v.add_argument("--out", nargs="?", const=DEFAULT_OUT, default=None, metavar="DIR",
                   help=f"also write validate.txt and validate.json to DIR, a folder inside the repository; "
                        f"a relative DIR is taken from the repository root (default {DEFAULT_OUT}/)")
    return parser


def main(argv: list[str] | None = None, stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except CommandLineError as exc:           # bad arguments: escaped message, exit 2
        err.write(parser.format_usage())
        print(f"impact: error: {safe(str(exc))}", file=err)
        return EXIT_FAILURE
    except SystemExit as exc:              # argparse --help / --version
        return EXIT_OK if exc.code in (0, None) else EXIT_FAILURE
    try:
        return validate(args, out)
    except (UsageError, OutputError, gitfiles.GitError) as exc:
        print(f"impact: error: {safe(str(exc))}", file=err)
        return EXIT_FAILURE
    except LoadError as exc:               # only operational load failures reach here
        print(f"impact: error: {safe(str(exc))}", file=err)
        return EXIT_FAILURE
    except Exception:                      # never let a bug look like "ERROR found" (exit 1)
        print("impact: internal error; validation did not complete. Details:", file=err)
        # The traceback can carry repository-controlled text (file names in an OS error):
        # every line is escaped and bounded, and only the last lines are kept.
        lines = traceback.format_exc().splitlines()
        if len(lines) > MAX_TRACEBACK_LINES:
            print(f"  ... ({len(lines) - MAX_TRACEBACK_LINES} earlier traceback lines omitted)", file=err)
            lines = lines[-MAX_TRACEBACK_LINES:]
        for line in lines:
            print(safe(line), file=err)
        return EXIT_FAILURE


MAX_TRACEBACK_LINES = 60


def safe(text: str) -> str:
    """Text for stderr: control and format characters escaped, length bounded."""
    return printable(text, 2000, double_backslash=False)


class CommandLineError(Exception):
    """A command-line argument error (argparse would otherwise print it unescaped)."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise CommandLineError(message)


def validate(args: argparse.Namespace, out: TextIO) -> int:
    start = args.root if args.root is not None else Path.cwd()
    if not start.is_dir():
        raise UsageError(f"--root is not a folder: {printable(str(start), double_backslash=False)}")
    root = gitfiles.toplevel(start.resolve())

    config, registry, problems, sources = load_for_report(root)
    listing = gitfiles.list_files(root)
    if config is not None and registry is not None:
        problems += check_files(config, registry, config.registry, listing.files)
        problems += ambiguities(config, registry, config.registry, listing.files)
    for u in listing.unsupported:
        problems.append(Problem("(working tree)", "file name", u.shown, "unsupported-path", "WARNING",
                                f"{u.reason}; the file is not analysed: {u.shown}"))

    report = Report("validate", gitfiles.head(root), len(listing.files), tuple(sources), from_problems(problems))
    text, data = render_text(report), render_json(report)
    if args.out is not None:
        write_reports(root, args.out, {"validate.txt": text, "validate.json": data})
    out.write(data if args.format == "json" else text)
    return report.exit_code


def write_reports(root: Path, out: str, contents: dict[str, str]) -> None:
    """Write the report files, refusing an empty target, the repository root itself,
    anything outside the repository or inside .git, and anything that would overwrite a
    tracked file or a folder. All temporary files are written before any report is
    replaced, so a write failure cannot leave one new and one old report."""
    if not str(out).strip():
        raise OutputError("--out needs a folder name (or no value for the default .local/impact/)")
    target = Path(out)
    root_resolved = root.resolve()
    folder = (target if target.is_absolute() else root / target).resolve()
    if not folder.is_relative_to(root_resolved):
        raise OutputError(f"--out must be inside the repository: {printable(str(target), double_backslash=False)}")
    if folder == root_resolved:
        raise OutputError(f"--out must be a folder inside the repository, not its root: {printable(str(target), double_backslash=False)}")
    if ".git" in folder.relative_to(root_resolved).parts:
        raise OutputError(f"--out must not be inside .git: {printable(str(target), double_backslash=False)}")
    if folder.exists() and not folder.is_dir():
        raise OutputError(f"--out is not a folder: {printable(str(target), double_backslash=False)}")
    for name in contents:
        path = folder / name
        rel = path.relative_to(root_resolved).as_posix()
        if path.is_dir():
            raise OutputError(f"a folder is in the way of the report file: {printable(rel)}")
        if gitfiles.is_tracked(root, rel):
            raise OutputError(f"refusing to overwrite a tracked file: {printable(rel)}")
        if path.exists() and not os.access(path, os.W_OK):
            raise OutputError(f"an existing report file is read-only: {printable(rel)}")

    # Write every new report to a temp file, move the existing reports aside, then put the
    # new ones in place. On any failure the moved-aside reports are restored, so the
    # folder ends with all old reports or all new ones, never a mix.
    temps: dict[str, str] = {}
    backups: dict[str, str] = {}
    placed: list[str] = []
    keep: set[str] = set()          # backups that could not be restored are never deleted
    created: list[str] = []         # every backup file created, moved into or not
    # Folders this run creates (deepest first): removed again if the write fails, so a
    # failed --out leaves no empty folder behind. Only folders that did not exist are listed.
    new_folders: list[Path] = []
    probe = folder
    while not probe.exists() and probe != root_resolved:
        new_folders.append(probe)
        probe = probe.parent
    succeeded = False
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for name, text in contents.items():
            fd, tmp = tempfile.mkstemp(dir=folder, prefix=f".{name}.", suffix=".tmp")
            temps[name] = tmp
            with os.fdopen(fd, "wb") as handle:
                handle.write(text.encode("utf-8"))
        for name in contents:
            if (folder / name).exists():
                fd, backup = tempfile.mkstemp(dir=folder, prefix=f".{name}.", suffix=".old")
                os.close(fd)
                created.append(backup)    # tracked now: removed even if the move below fails
                os.replace(folder / name, backup)
                backups[name] = backup
        for name, tmp in temps.items():
            os.replace(tmp, folder / name)
            placed.append(name)
        succeeded = True
    except OSError as exc:
        restore_failed = []
        for name in placed:
            if name not in backups:
                try:
                    os.unlink(folder / name)      # a new report that had no old version
                except OSError:
                    restore_failed.append(name)
        for name, backup in backups.items():
            try:
                os.replace(backup, folder / name)
            except OSError:
                restore_failed.append(name)
                keep.add(backup)
        detail = f"could not write the reports to {printable(str(target), double_backslash=False)}: {printable(str(exc.strerror or exc))}"
        if restore_failed:
            kept = ", ".join(Path(b).name for b in sorted(keep))
            detail += (f"; could not restore {', '.join(restore_failed)}, so the reports there may be "
                       f"inconsistent" + (f" (previous version kept as {kept})" if kept else ""))
        raise OutputError(detail) from None
    finally:
        for leftover in list(temps.values()) + created:
            if leftover not in keep and os.path.exists(leftover):
                try:
                    os.unlink(leftover)
                except OSError:
                    pass
        if not succeeded:
            # Remove the folders this run created, deepest first. os.rmdir only removes an
            # empty folder, so anything left inside (e.g. a kept backup) is never deleted.
            for new in new_folders:
                try:
                    os.rmdir(new)
                except OSError:
                    break
