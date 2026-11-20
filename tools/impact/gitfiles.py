"""List the working tree's files from Git, safely.

The only module in tools/impact that starts a subprocess, and only `git`, with fixed
arguments, no shell, no stdin and a timeout. Output is NUL-delimited (`-z`), so Git
never quotes or escapes names and every byte of a file name survives. Every call adds
--no-optional-locks and core.fsmonitor=false. Git itself may still run the content
filters selected by .gitattributes and defined in Git configuration (e.g. Git LFS);
see the safety statement in changes.py.

Names the tool cannot process safely are not fatal: they are returned as
`Unsupported` entries (reported as the fixed `unsupported-path` WARNING) and are
left out of matching.
"""

from __future__ import annotations

import contextvars
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

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


# Added to EVERY git call, so no call site can forget them: avoid optional lock-taking,
# and never run a configured fsmonitor hook. (--no-optional-locks does NOT stop
# `git diff` from refreshing the index; change analysis therefore runs against a
# private copy of the index: see private_index.)
SAFE_GIT_OPTIONS = ("--no-optional-locks", "-c", "core.fsmonitor=false")
# Also on EVERY git call: core.hooksPath points at a new, empty folder that the tool
# creates in the system temporary folder (outside the repository) just for that call and
# removes afterwards, so no hook runs (for example post-index-change when git refreshes
# an index). A path given with -c overrides .git/hooks and any configured hooksPath.
HOOKS_FOLDER_PREFIX = "impact-nohooks-"
# Set in the environment of EVERY git call: in a partial clone git would otherwise fetch
# missing objects from the remote on demand, starting transport programs (ssh, remote
# and credential helpers) and using the network. With it, a missing object is simply an
# error, which the tool reports as "not scanned". Needs git 2.44 or later; change
# analysis enforces that (require_git) instead of silently fetching on older git.
SAFE_GIT_ENVIRONMENT = {"GIT_NO_LAZY_FETCH": "1"}
MIN_GIT_FOR_CHANGE_ANALYSIS = (2, 44)

# The private index of the change-analysis operation in progress: (repository root,
# path of the private copy). While set, every git call for that repository reads and
# writes the copy (GIT_INDEX_FILE), never the repository's own index.
_PRIVATE_INDEX: contextvars.ContextVar[tuple[Path, str] | None] = contextvars.ContextVar(
    "impact_private_index", default=None)
_VERSION_CACHE: dict[str, tuple[int, int]] = {}


def _run(root: Path, args: tuple[str, ...], timeout: float) -> subprocess.CompletedProcess:
    env = {**os.environ, **SAFE_GIT_ENVIRONMENT}
    options = SAFE_GIT_OPTIONS
    active = _PRIVATE_INDEX.get()
    if active is not None and active[0] == Path(root).resolve():
        env["GIT_INDEX_FILE"] = active[1]
        # A split index would make git write a new shared index file inside .git.
        options = SAFE_GIT_OPTIONS + ("-c", "core.splitIndex=false")
    no_hooks = tempfile.mkdtemp(prefix=HOOKS_FOLDER_PREFIX)
    try:
        return subprocess.run(["git", "-C", str(root), *options, "-c", f"core.hooksPath={no_hooks}", *args],
                              capture_output=True, stdin=subprocess.DEVNULL, timeout=timeout, env=env)
    except FileNotFoundError:
        raise GitError("the 'git' program was not found") from None
    except subprocess.TimeoutExpired:
        raise GitError(f"'git {_command(args)}' did not finish within {timeout:g} seconds") from None
    finally:
        shutil.rmtree(no_hooks, ignore_errors=True)


def _command(args: tuple[str, ...]) -> str:
    return next((a for a in args if not a.startswith("-")), args[0] if args else "")


def _failure(args: tuple[str, ...], result: subprocess.CompletedProcess) -> GitError:
    message = result.stderr.decode("utf-8", "replace").strip().splitlines()
    detail = printable(message[0]) if message else f"exit code {result.returncode}"
    return GitError(f"'git {_command(args)}' failed: {detail}")


def git_version(root: Path) -> tuple[int, int]:
    """(major, minor) of the git program, parsed from `git version` (cached)."""
    key = "git"
    if key not in _VERSION_CACHE:
        out = run_git(root, "version").decode("utf-8", "replace")
        m = re.search(r"git version (\d+)\.(\d+)", out)
        if not m:
            raise GitError(f"could not determine the git version from: {printable(out.strip())}")
        _VERSION_CACHE[key] = (int(m.group(1)), int(m.group(2)))
    return _VERSION_CACHE[key]


def require_git_for_change_analysis(root: Path) -> None:
    """Change analysis relies on GIT_NO_LAZY_FETCH (git 2.44+). An older git would
    silently fetch missing objects in a partial clone, so refuse instead (exit code 2)."""
    found = git_version(root)
    if found < MIN_GIT_FOR_CHANGE_ANALYSIS:
        need = ".".join(map(str, MIN_GIT_FOR_CHANGE_ANALYSIS))
        raise GitError(f"change analysis needs git {need} or later (found {found[0]}.{found[1]}): "
                       "older git would download missing objects in partial clones")


@contextmanager
def private_index(root: Path) -> Iterator[str]:
    """Run the enclosed git calls against a private copy of the repository's index.

    `git diff` refreshes the index's cached file timestamps and rewrites it (taking
    index.lock) even with --no-optional-locks. Inside this block every git call for
    `root` uses a copy in a temporary folder outside the repository (GIT_INDEX_FILE),
    so the repository's index and its lock file are never written. One copy serves the
    whole operation (nested use reuses it); it is deleted afterwards, also on errors.
    """
    root_resolved = Path(root).resolve()
    active = _PRIVATE_INDEX.get()
    if active is not None and active[0] == root_resolved:
        yield active[1]
        return
    real = run_git(root, "rev-parse", "--git-path", "index").decode("utf-8", "strict").strip()
    real_path = Path(real) if os.path.isabs(real) else Path(root) / real
    folder = tempfile.mkdtemp(prefix="impact-index-")
    try:
        private = os.path.join(folder, "index")
        if real_path.is_file():
            # copy2 keeps the index timestamp: git compares it with file timestamps to spot
            # "racily clean" entries (edited in the same second as the last index write)
            # and checks those by content. A fresh timestamp would hide such edits.
            shutil.copy2(real_path, private)          # no index yet (unborn, nothing staged): git starts empty
        token = _PRIVATE_INDEX.set((root_resolved, private))
        try:
            yield private
        finally:
            _PRIVATE_INDEX.reset(token)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def git_status(root: Path, *args: str, timeout: float = GIT_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    """Run git and return the completed process without raising on a non-zero exit, for
    checks where a non-zero status is an answer (an object or ref does not exist). A
    missing git or a timeout still raises GitError."""
    return _run(root, args, timeout)


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
        if raw.endswith(b"/"):
            # git lists an untracked nested repository as its folder with a trailing '/'.
            unsupported.add(Unsupported(_shown(raw), "nested Git repository (its files are not analysed)"))
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
