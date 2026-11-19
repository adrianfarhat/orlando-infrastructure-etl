"""List the working tree's files from Git, safely.

The only module in tools/impact that starts a subprocess, and only `git`, with fixed
arguments, no shell, no stdin and a timeout. Output is NUL-delimited (`-z`), so Git
never quotes or escapes names and every byte of a file name survives.

Names the tool cannot process safely are not fatal: they are returned as
`Unsupported` entries (reported as the fixed `unsupported-path` WARNING) and are
left out of matching.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .paths import PathError, printable, repo_path

GIT_TIMEOUT_SECONDS = 60


class GitError(Exception):
    """Git is missing, failed or timed out: an operational failure (exit code 2)."""


@dataclass(frozen=True, order=True)
class Unsupported:
    shown: str     # printable form of the name (non-printable characters escaped)
    reason: str


@dataclass(frozen=True)
class Listing:
    files: tuple[str, ...]              # sorted, unique, validated with repo_path
    unsupported: tuple[Unsupported, ...]


def _run(root: Path, args: tuple[str, ...], timeout: float) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                              stdin=subprocess.DEVNULL, timeout=timeout)
    except FileNotFoundError:
        raise GitError("the 'git' program was not found") from None
    except subprocess.TimeoutExpired:
        raise GitError(f"'git {_command(args)}' did not finish within {timeout:g} seconds") from None


def _command(args: tuple[str, ...]) -> str:
    return next((a for a in args if not a.startswith("-")), args[0] if args else "")


def _failure(args: tuple[str, ...], result: subprocess.CompletedProcess) -> GitError:
    message = result.stderr.decode("utf-8", "replace").strip().splitlines()
    detail = printable(message[0]) if message else f"exit code {result.returncode}"
    return GitError(f"'git {_command(args)}' failed: {detail}")


def run_git(root: Path, *args: str, timeout: float = GIT_TIMEOUT_SECONDS) -> bytes:
    result = _run(root, args, timeout)
    if result.returncode != 0:
        raise _failure(args, result)
    return result.stdout


def toplevel(start: Path) -> Path:
    """The root folder of the Git repository containing `start`."""
    out = run_git(start, "rev-parse", "--show-toplevel").decode("utf-8", "strict").strip()
    if not out:
        raise GitError(f"{printable(str(start))} is not inside a Git working tree")
    return Path(out)


def head(root: Path) -> str | None:
    """The full commit id of HEAD, or None when HEAD is an unborn branch (no commits yet).

    Measured git behaviour: `rev-parse --verify --quiet HEAD` exits 1 silently both for
    an unborn branch and for a corrupt branch ref, and exits 0 for a ref pointing to a
    missing object. So HEAD is resolved with `^{commit}` (which checks the object), and
    "no commits" is reported only when HEAD is a symbolic ref to a branch that does not
    exist yet. Every other failure is an operational error (exit code 2)."""
    args = ("rev-parse", "--verify", "--quiet", "--end-of-options", "HEAD^{commit}")
    result = _run(root, args, GIT_TIMEOUT_SECONDS)
    if result.returncode == 0:
        sha = result.stdout.decode("ascii", "replace").strip()
        if not sha:
            raise GitError("'git rev-parse' succeeded but printed no commit id")
        return sha
    if result.returncode != 1 or result.stdout.strip() or result.stderr.strip():
        raise _failure(args, result)
    sym_args = ("symbolic-ref", "-q", "HEAD")
    sym = _run(root, sym_args, GIT_TIMEOUT_SECONDS)
    ref = sym.stdout.decode("utf-8", "replace").strip()
    if sym.returncode == 0 and ref:
        ref_args = ("rev-parse", "--verify", "--quiet", "--end-of-options", ref)
        exists = _run(root, ref_args, GIT_TIMEOUT_SECONDS)
        if exists.returncode == 1 and not exists.stdout.strip() and not exists.stderr.strip():
            return None                                  # unborn branch: no commits yet
    raise GitError("HEAD does not point to a valid commit (the repository may be corrupt)")


def is_tracked(root: Path, relative: str) -> bool:
    """Whether exactly this path is tracked. --literal-pathspecs stops Git from reading
    characters such as `[1]` in the name as a glob."""
    return bool(run_git(root, "--literal-pathspecs", "ls-files", "-z", "--cached", "--", relative))


def _shown(raw: bytes) -> str:
    """A printable, unambiguous, bounded form of a raw name (for reports only)."""
    return printable(raw.decode("utf-8", "surrogateescape"))


def parse_listing(data: bytes) -> Listing:
    """Split NUL-delimited Git output into supported and unsupported names."""
    files: set[str] = set()
    unsupported: set[Unsupported] = set()
    for raw in data.split(b"\0"):
        if not raw:
            continue
        try:
            name = raw.decode("utf-8", "strict")
        except UnicodeDecodeError:
            unsupported.add(Unsupported(_shown(raw), "file name is not valid UTF-8"))
            continue
        try:
            files.add(repo_path(name))
        except PathError as exc:
            unsupported.add(Unsupported(_shown(raw), str(exc).split(":")[0]))
    return Listing(tuple(sorted(files)), tuple(sorted(unsupported)))


def list_files(root: Path, exists: Callable[[str], bool] | None = None) -> Listing:
    """Files in the working tree: tracked plus untracked-but-not-ignored, minus files
    deleted from disk but not yet from the index."""
    data = run_git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    listing = parse_listing(data)
    check = exists or (lambda rel: os.path.lexists(root / rel))
    return Listing(tuple(f for f in listing.files if check(f)), listing.unsupported)
