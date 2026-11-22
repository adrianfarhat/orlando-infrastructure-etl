"""Stable IDs that are never reused (T-97 Phase 1, decision P1-A: Git history).

A new feature ID (FD-0001) or diagram ID (FD-0001-D1) is one higher than every ID that is
in the working tree now **or appears anywhere in the committed Git history** (all local
branches, remote-tracking branches, tags and the stash). So deleting a feature or diagram,
even the one with the highest number, never frees its number again.

Reading the history runs `git log` (read only; nothing is staged, committed or changed).
When the history cannot be read completely, allocation stops instead of guessing:
- not a Git repository, Git not installed, or `git log` fails: error;
- a shallow clone (history cut off): error, with `git fetch --unshallow` as the fix;
- a repository without any commit yet: allowed (nothing has been retired).

Known limits (documented in designs/README.md and DECISIONS.md):
- an ID that was created and deleted without ever being committed is not recorded
  anywhere, so it may be allocated again (it was never published); the same holds for an
  ID that existed only on a branch that was squash-merged and then deleted;
- two branches that allocate at the same time, before either sees the other, can pick the
  same number; `python -m tools.design check` reports the duplicate when they meet.
Existing IDs are never renumbered by any command.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from .workspace import DesignError

FEATURE_ID = re.compile(r"FD-(\d{4})\Z")
DIAGRAM_ID = re.compile(r"(FD-\d{4})-D([1-9]\d{0,3})\Z")
# A metadata line added or removed in a commit: "+feature_id: FD-0003", '-diagram_id: "FD-0003-D2"  # ...'
_HISTORY_LINE = re.compile(r"""^[+-]\s*(?:feature_id|diagram_id)\s*:\s*["']?(FD-\d{4}(?:-D[1-9]\d{0,3})?)["']?\s*(?:#.*)?$""")
_GIT_TIMEOUT = 120
# Environment variables that would point `git -C <root>` at another repository or index are
# dropped; GIT_NO_LAZY_FETCH stops a partial clone from fetching missing objects over the
# network (the scan then fails and allocation stops, as for any incomplete history).
_REDIRECTING = {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR",
                "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES"}


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        env = {k: v for k, v in os.environ.items() if k not in _REDIRECTING}
        env["GIT_NO_LAZY_FETCH"] = "1"
        return subprocess.run(["git", "-c", "core.quotepath=off", "-C", str(root), *args], capture_output=True,
                              timeout=_GIT_TIMEOUT, env=env)
    except FileNotFoundError:
        raise DesignError(_why("Git is not installed or not on PATH")) from None
    except subprocess.TimeoutExpired:
        raise DesignError(_why(f"reading the Git history took longer than {_GIT_TIMEOUT} s")) from None


def _why(reason: str) -> str:
    return (f"cannot allocate a new ID safely: {reason}. IDs are never reused, and the committed Git history "
            "is what records the retired ones; nothing was created")


def committed_ids(root: Path) -> set[str]:
    """Every feature and diagram ID that appears in a metadata line of any committed version
    of a file under designs/, on any branch, remote-tracking branch, tag or the stash."""
    root = Path(root)
    inside = _git(root, "rev-parse", "--is-inside-work-tree")
    if inside.returncode or inside.stdout.strip() != b"true":
        raise DesignError(_why(f"{root} is not a Git working tree"))
    shallow = _git(root, "rev-parse", "--is-shallow-repository")
    if shallow.returncode:
        raise DesignError(_why("Git could not report whether the clone is complete"))
    if shallow.stdout.strip() == b"true":
        raise DesignError(_why("this clone is shallow, so older history is missing; "
                               "run `git fetch --unshallow` and try again"))
    refs = _git(root, "for-each-ref", "--count=1", "--format=%(refname)")
    if refs.returncode:
        raise DesignError(_why("Git could not list the branches"))
    if not refs.stdout.strip():
        return set()                                   # no commit yet: nothing has been retired
    # --full-history: without it, Git skips a merged side branch whose result equals the main
    # line for designs/ (for example an ID added and removed again on a PR branch, or an
    # `-s ours` merge), and those IDs would be lost (T-97 Phase 1 QA D1).
    log = _git(root, "log", "--all", "--full-history", "--no-color", "--no-ext-diff", "--no-textconv", "--format=",
               "-p", "--", "designs")
    if log.returncode:
        raise DesignError(_why("`git log` failed: " + log.stderr.decode("utf-8", "replace").strip()[:200]))
    found = set()
    for line in log.stdout.decode("utf-8", "replace").split("\n"):
        m = _HISTORY_LINE.match(line.rstrip("\r"))
        if m:
            found.add(m.group(1))
    return found


def _feature_number(fid: str) -> int | None:
    m = FEATURE_ID.match(fid) or (DIAGRAM_ID.match(fid) and FEATURE_ID.match(DIAGRAM_ID.match(fid).group(1)))
    return int(m.group(1)) if m else None


def next_feature_id(in_tree: list[str], committed: set[str]) -> str:
    """One higher than every feature ID in the working tree and in the history (a diagram ID
    also proves its feature's number was used)."""
    numbers = [n for n in (_feature_number(x) for x in [*in_tree, *committed]) if n is not None]
    following = max(numbers, default=0) + 1
    if following > 9999:
        raise DesignError("no feature IDs left (FD-9999 is in use)")
    return f"FD-{following:04d}"


def next_diagram_id(owner: str, in_tree: list[str], committed: set[str]) -> str:
    """The owner's ID plus -D and one higher than every diagram number of that owner in the
    working tree and in the history."""
    if not FEATURE_ID.match(owner):
        raise DesignError(f"the owner must be a feature ID such as FD-0001, not {owner!r}")
    numbers = [int(m.group(2)) for m in (DIAGRAM_ID.match(x) for x in [*in_tree, *committed])
               if m and m.group(1) == owner]
    following = max(numbers, default=0) + 1
    if following > 9999:
        raise DesignError(f"no diagram IDs left for {owner}")
    return f"{owner}-D{following}"
