"""Collect a change set from Git (T-83 phase 83b, stage 83b-1).

Two modes:
- local (no base): HEAD (or the empty tree on an unborn branch) against the working
  tree; origins `staged`, `unstaged`, `untracked`;
- branch (`base` given): the merge-base of base and HEAD against the working tree;
  origins `committed` (merge-base..HEAD) plus the three local ones.

Every changed path appears once, with every origin it was seen in. Its kind (added,
modified, deleted, renamed, copied) is decided against the BASELINE (the merge-base, or
HEAD in local mode) and the working tree, so a file deleted from the index and kept on
disk, or added and removed again, is classified by its net effect. Renames and copies
keep their old path; rename chains (a -> b committed, b -> c staged) are followed back
to the baseline path.

Changed lines (for content triggers) are the added and removed lines between the
baseline and the working tree. Binary files and files over the size limits are
reported as not scanned, never as "no change".

Programs git may run (safety statement):
- Git is run only through gitfiles: fixed argument lists, no shell, timeouts, and on
  every call --no-optional-locks, core.fsmonitor=false (no fsmonitor hook runs) and
  core.hooksPath set to a new empty folder outside the repository, removed after the
  call (no Git hook runs, including post-index-change).
- The repository's index is never written. `git diff` refreshes the index's cached file
  timestamps (taking index.lock) even with --no-optional-locks, so every analysis runs
  against a private copy of the index in a temporary folder outside the repository
  (GIT_INDEX_FILE, one copy per operation, deleted afterwards even on errors; split
  index disabled for those calls so no shared-index file is written into .git).
- Change analysis requires git 2.44 or later and refuses older git (GitError, exit
  code 2) rather than risk the lazy fetching described next.
- Lazy fetching is disabled on every call (GIT_NO_LAZY_FETCH=1, git 2.44 or later): in
  a partial clone, a missing object is never downloaded, so no transport program
  (ssh, remote or credential helper) starts and no network is used. Content that needs
  a missing object is reported as not scanned, never as "no change".
- External diff programs and textconv converters are disabled on every diff
  (--no-ext-diff, --no-textconv). --literal-pathspecs keeps file names from being read
  as patterns, and option-like values (--base, file names) cannot become git options.
- EXCEPTION, kept deliberately: Git content filters. When git reads a working-tree
  file it applies the content filter (filter.<driver>.clean / .process, e.g. Git LFS)
  that the file's attributes select. The commands are defined in Git configuration
  (user, system or repository config), and the repository's .gitattributes decide
  which configured filter applies to which file. They are kept because turning them
  off would make results wrong for repositories that rely on them (an LFS file would
  appear entirely changed). So the tool does not claim that no external program runs:
  it runs exactly the content filters that `git diff` itself would run.

Known limitations (documented, not addressed in this stage):
1. Phantom changes: an edit that is staged and then reverted in the working tree, a
   file deleted and recreated with identical content, or a file removed from the index
   with `git rm --cached` but left unchanged on disk (origins staged + untracked) is
   reported as "modified" with no changed lines; kinds are decided by existence, not
   by comparing content.
2. A file replaced by a folder of the same name is reported as "modified" (not
   scanned: "not a regular file"), not as "deleted".
3. Speed: changed lines are read with two or three git processes per file (about 37 ms
   per file on Windows; 300 files took about 11 s).
4. Symbolic links are read as their target path, as git does; this was not verified on
   Windows, where creating them needs extra privileges.
5. Copies of an unmodified file are classified as "added", not "copied": with git's
   default copy detection (-C, without --find-copies-harder) only files that are
   themselves changed in the same diff are considered as copy sources. Such a file is
   still fully scanned as added content.
"""

from __future__ import annotations

import difflib
from contextlib import contextmanager
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import gitfiles
from .gitfiles import GitError, Unsupported
from .paths import PathError, printable, repo_path

ORIGINS = ("committed", "staged", "unstaged", "untracked")
KINDS = ("added", "modified", "deleted", "renamed", "copied")

# A file larger than this (either version) is not scanned for changed lines.
MAX_FILE_BYTES = 2_000_000
# Diff output larger than this is not parsed (bounded memory and time).
MAX_DIFF_BYTES = 8_000_000
# Git's own binary heuristic: a NUL byte in the first 8,000 bytes.
BINARY_SNIFF_BYTES = 8000

# Not-scanned reasons that callers and tests rely on.
MISSING_OBJECT = ("the previous version is not available in this repository (a missing Git object, "
                  "for example in a partial clone; it is not fetched)")
SUBMODULE = "submodule (its files are not analysed)"

# gitfiles adds --no-optional-locks and core.fsmonitor=false to every git call.
# --literal-pathspecs: no file name is ever read as a pattern.
_SAFE = ("--literal-pathspecs",)
_DIFF_FLAGS = ("--no-color", "--no-ext-diff", "--no-textconv")


@dataclass(frozen=True)
class Change:
    path: str                      # path in the working tree (for a deletion: the deleted path)
    kind: str                      # one of KINDS
    origins: tuple[str, ...]       # subset of ORIGINS, in ORIGINS order
    old_path: str | None = None    # for renamed and copied: the path at the baseline

    @property
    def removed_paths(self) -> tuple[str, ...]:
        """Paths that no longer exist because of this change (for stale references)."""
        if self.kind == "deleted":
            return (self.path,)
        if self.kind == "renamed" and self.old_path:
            return (self.old_path,)
        return ()


@dataclass(frozen=True)
class ChangeSet:
    root: Path
    base_ref: str | None           # as given by the user, or None in local mode
    baseline: str                  # commit id (merge-base or HEAD) or the empty tree id
    head: str | None               # HEAD commit id, None on an unborn branch
    changes: tuple[Change, ...]    # sorted by path
    unsupported: tuple[Unsupported, ...]
    baseline_files: frozenset[str] = field(default=frozenset(), repr=False)

    def by_path(self) -> dict[str, Change]:
        return {c.path: c for c in self.changes}


@dataclass(frozen=True)
class ChangedLines:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    scanned: bool                  # False: the content could not be read as text
    reason: str | None = None      # why it was not scanned

    @property
    def text(self) -> str:
        """Added and removed lines joined, for content-trigger scanning."""
        return "\n".join(self.added + self.removed)


# --------------------------------------------------------------------------- collection

@contextmanager
def analysis(root: Path):
    """One change-analysis operation: checks the git version (2.44+) and runs every
    enclosed git call against one private copy of the index (see gitfiles.private_index).
    collect() and changed_lines() open their own when called outside this block, so
    they are safe on their own; wrapping a whole operation shares one copy."""
    gitfiles.require_git_for_change_analysis(root)
    with gitfiles.private_index(root):
        yield


def collect(root: Path, base: str | None = None) -> ChangeSet:
    """The change set of the working tree against HEAD, or against merge-base(base, HEAD)."""
    with analysis(root):
        return _collect(root, base)


def _collect(root: Path, base: str | None = None) -> ChangeSet:
    """The change set of the working tree against HEAD, or against merge-base(base, HEAD)."""
    head = gitfiles.head(root)
    if base is not None:
        if head is None:
            raise GitError("--base needs at least one commit on the current branch")
        base_commit = _verify_commit(root, base)
        baseline = _merge_base(root, base, base_commit, head)
    else:
        baseline = head or _empty_tree(root)

    entries: list[tuple[str, str, str, str | None]] = []   # (origin, status, path, old_path)
    unsupported: set[Unsupported] = set()
    if base is not None:
        _name_status(root, ("diff", baseline, head), "committed", entries, unsupported)
    _name_status(root, ("diff", "--cached", head or _empty_tree(root)), "staged", entries, unsupported)
    _name_status(root, ("diff",), "unstaged", entries, unsupported)
    listing = gitfiles.parse_listing(gitfiles.run_git(root, *_SAFE, "ls-files", "-z", "--others",
                                                      "--exclude-standard"))
    unsupported.update(listing.unsupported)
    for path in listing.files:
        entries.append(("untracked", "?", path, None))

    baseline_files = _tree_files(root, baseline)
    changes = _merge(root, entries, baseline_files)
    return ChangeSet(root, base, baseline, head, changes, tuple(sorted(unsupported)), frozenset(baseline_files))


def _verify_commit(root: Path, ref: str) -> str:
    if not ref.strip():
        raise GitError("--base needs a branch, tag or commit")
    r = gitfiles.git_status(root, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}")
    sha = r.stdout.decode("ascii", "replace").strip()
    if r.returncode != 0 or not sha:
        raise GitError(f"--base is not a commit in this repository: {printable(ref, double_backslash=False)}")
    return sha


def _merge_base(root: Path, ref: str, base_commit: str, head: str) -> str:
    r = gitfiles.git_status(root, "merge-base", base_commit, head)
    sha = r.stdout.decode("ascii", "replace").strip()
    if r.returncode == 0 and sha:
        return sha
    shallow = gitfiles.git_status(root, "rev-parse", "--is-shallow-repository")
    hint = (" (this is a shallow clone: fetch more history)"
            if shallow.stdout.decode("ascii", "replace").strip() == "true" else "")
    raise GitError(f"no common ancestor between --base {printable(ref, double_backslash=False)} and HEAD{hint}")


def _empty_tree(root: Path) -> str:
    # Computed, not written (no -w): works for SHA-1 and SHA-256 repositories.
    return gitfiles.run_git(root, "hash-object", "-t", "tree", "--stdin").decode("ascii").strip()


def _tree_files(root: Path, tree_ish: str) -> set[str]:
    data = gitfiles.run_git(root, *_SAFE, "ls-tree", "-r", "-z", "--name-only", tree_ish)
    return set(gitfiles.parse_listing(data).files)


def parse_name_status(data: bytes) -> tuple[list[tuple[str, str, str | None]], list[Unsupported]]:
    """Parse `git diff --name-status -z` output into (status letter, path, old path)."""
    tokens = data.split(b"\0")
    if tokens and tokens[-1] == b"":
        tokens.pop()
    out: list[tuple[str, str, str | None]] = []
    bad: list[Unsupported] = []
    i = 0
    while i < len(tokens):
        status = tokens[i].decode("ascii", "replace")
        letter = status[:1]
        if letter in ("R", "C"):
            if i + 2 >= len(tokens):
                raise GitError(f"unexpected git diff output after status {status!r}")
            raw_old, raw_new = tokens[i + 1], tokens[i + 2]
            i += 3
            old, new = _decode(raw_old, bad), _decode(raw_new, bad)
            if old is not None and new is not None:
                out.append((letter, new, old))
            elif new is not None:          # an unusable old name: keep the new path as added
                out.append(("A", new, None))
        else:
            if i + 1 >= len(tokens):
                raise GitError(f"unexpected git diff output after status {status!r}")
            raw = tokens[i + 1]
            i += 2
            path = _decode(raw, bad)
            if path is not None:
                out.append((letter, path, None))
    return out, bad


def _decode(raw: bytes, bad: list[Unsupported]) -> str | None:
    listing = gitfiles.parse_listing(raw + b"\0")
    bad.extend(listing.unsupported)
    return listing.files[0] if listing.files else None


def _name_status(root: Path, args: tuple[str, ...], origin: str, entries: list, unsupported: set) -> None:
    data = gitfiles.run_git(root, *_SAFE, *args[:1], "--name-status", "-z", "-M", "-C", *_DIFF_FLAGS,
                            *args[1:])
    parsed, bad = parse_name_status(data)
    unsupported.update(bad)
    for letter, path, old in parsed:
        entries.append((origin, letter, path, old))


def _merge(root: Path, entries: list[tuple[str, str, str, str | None]], baseline_files: set[str]) -> tuple[Change, ...]:
    origins: dict[str, set[str]] = {}
    moved_from: dict[str, tuple[str, str]] = {}          # new path -> (old path, "R" or "C")
    for origin, letter, path, old in entries:
        origins.setdefault(path, set()).add(origin)
        if letter in ("R", "C") and old is not None:
            moved_from[path] = (old, letter)
            origins.setdefault(old, set()).add(origin)   # the source changed in this origin too

    def exists_now(p: str) -> bool:
        return os.path.lexists(root / p)

    def baseline_source(p: str) -> tuple[str, set[str]]:
        """Follow a rename chain back to the path at the baseline; also return the
        origins of the intermediate steps (a -> b committed, b -> c staged: c carries
        both origins, because both steps made this change)."""
        seen = {p}
        via: set[str] = set()
        while p in moved_from and moved_from[p][1] == "R" and p not in baseline_files:
            p = moved_from[p][0]
            if p in seen:
                break
            seen.add(p)
            if p not in baseline_files:
                via |= origins.get(p, set())
        return p, via

    # A rename whose new path was later deleted again leaves only the source's deletion;
    # that deletion must carry the origins of every step (e.g. renamed when staged,
    # deleted when unstaged).
    extra: dict[str, set[str]] = {}
    for path, (old, letter) in moved_from.items():
        if letter == "R" and path not in baseline_files and not exists_now(path):
            source, via = baseline_source(path)
            extra.setdefault(source, set()).update(origins[path] | via)

    renamed_sources: set[str] = set()
    changes: list[Change] = []
    for path in sorted(origins):
        at_base, now = path in baseline_files, exists_now(path)
        ordered = tuple(o for o in ORIGINS if o in origins[path] | extra.get(path, set()))
        if path in moved_from and now and not at_base:
            old, letter = moved_from[path]
            source, via = baseline_source(path) if letter == "R" else (old, set())
            if via:
                ordered = tuple(o for o in ORIGINS if o in origins[path] | via)
            if source in baseline_files:
                if letter == "R" and not exists_now(source):
                    changes.append(Change(path, "renamed", ordered, source))
                    renamed_sources.add(source)
                    continue
                changes.append(Change(path, "copied", ordered, source))
                continue
        if not at_base and now:
            kind = "added"
        elif at_base and not now:
            kind = "deleted"
        elif at_base and now:
            kind = "modified"
        else:
            continue                       # added and removed again: no net change
        changes.append(Change(path, kind, ordered))
    # A rename's source is represented by the rename itself, not as a separate deletion.
    return tuple(c for c in changes if not (c.kind == "deleted" and c.path in renamed_sources))


# --------------------------------------------------------------------------- changed lines

def changed_lines(change_set: ChangeSet, change: Change) -> ChangedLines:
    """Added and removed lines of one change, between the baseline and the working tree."""
    with analysis(change_set.root):
        return _changed_lines(change_set, change)


def _changed_lines(change_set: ChangeSet, change: Change) -> ChangedLines:
    """Added and removed lines of one change, between the baseline and the working tree."""
    root = change_set.root
    old_path = change.old_path if change.kind in ("renamed", "copied") else change.path
    old_exists = old_path in change_set.baseline_files and change.kind != "added"
    new_exists = change.kind != "deleted"

    if (old_exists and _is_gitlink(root, change_set.baseline, old_path)) or (
            new_exists and _is_submodule_folder(root / change.path)):
        return ChangedLines((), (), False, SUBMODULE)
    if old_exists:
        size = _blob_size(root, change_set.baseline, old_path)
        if size is None:
            return ChangedLines((), (), False, MISSING_OBJECT)
        if size > MAX_FILE_BYTES:
            return ChangedLines((), (), False, f"the previous version is larger than {MAX_FILE_BYTES} bytes")
    if new_exists:
        local = root / change.path
        if os.path.islink(local):
            new_size = len(os.readlink(local).encode("utf-8", "surrogateescape"))
        elif os.path.isfile(local):
            new_size = os.path.getsize(local)
        else:
            return ChangedLines((), (), False, "not a regular file (for example a submodule or folder)")
        if new_size > MAX_FILE_BYTES:
            return ChangedLines((), (), False, f"the file is larger than {MAX_FILE_BYTES} bytes")

    if "untracked" in change.origins or change.kind == "copied":
        # Untracked: not in the index, so `git diff <baseline>` would not see the
        # working-tree file. Copied: the lines that differ from the copy's source (a
        # plain diff would mix in the source file's own edits).
        if _marked_binary(root, change.path) or (old_exists and _marked_binary(root, old_path)):
            return ChangedLines((), (), False, "binary file (.gitattributes)")
        old = _blob(root, change_set.baseline, old_path) if old_exists else b""
        new = _read_worktree(root / change.path) if new_exists else b""
        if old is None:
            return ChangedLines((), (), False, MISSING_OBJECT)
        if new is None:
            return ChangedLines((), (), False, "the file could not be read")
        if _binary(old) or _binary(new):
            return ChangedLines((), (), False, "binary file")
        return _difflib_lines(old, new)

    paths = (old_path, change.path) if old_path != change.path else (change.path,)
    r = gitfiles.git_status(root, *_SAFE, "diff", "-U0", "-M", *_DIFF_FLAGS, change_set.baseline, "--", *paths)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace")
        if "lazy fetching disabled" in err or "could not fetch" in err or "missing blob" in err:
            return ChangedLines((), (), False, MISSING_OBJECT)
        return ChangedLines((), (), False, "git diff failed for this file")
    if len(r.stdout) > MAX_DIFF_BYTES:
        return ChangedLines((), (), False, f"the diff is larger than {MAX_DIFF_BYTES} bytes")
    return parse_unified_diff(r.stdout)


def parse_unified_diff(data: bytes) -> ChangedLines:
    """Added and removed lines from `git diff -U0` output. Header lines (before the first
    @@ of each file) are skipped, so content lines that begin with +++ or --- are kept."""
    added: list[str] = []
    removed: list[str] = []
    in_hunk = False
    for raw in data.split(b"\n"):
        if raw.startswith(b"diff --git "):
            in_hunk = False
            continue
        if not in_hunk:
            if raw.startswith(b"Binary files ") or raw.startswith(b"GIT binary patch"):
                return ChangedLines((), (), False, "binary file")
            if raw.startswith(b"@@"):
                in_hunk = True
            continue
        if raw.startswith(b"@@"):
            continue
        if raw.startswith(b"+"):
            added.append(_line(raw[1:]))
        elif raw.startswith(b"-"):
            removed.append(_line(raw[1:]))
    return ChangedLines(tuple(added), tuple(removed), True)


def _line(raw: bytes) -> str:
    return raw.rstrip(b"\r").decode("utf-8", "replace")


def _difflib_lines(old: bytes, new: bytes) -> ChangedLines:
    a = [_line(x) for x in old.split(b"\n")] if old else []
    b = [_line(x) for x in new.split(b"\n")] if new else []
    if a and a[-1] == "":
        a.pop()
    if b and b[-1] == "":
        b.pop()
    added: list[str] = []
    removed: list[str] = []
    # autojunk keeps SequenceMatcher fast on large files (at most MAX_FILE_BYTES each); it
    # may report a few more changed lines than git would, never fewer.
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if tag in ("replace", "delete"):
            removed.extend(a[i1:i2])
        if tag in ("replace", "insert"):
            added.extend(b[j1:j2])
    return ChangedLines(tuple(added), tuple(removed), True)


def _binary(data: bytes) -> bool:
    return b"\0" in data[:BINARY_SNIFF_BYTES]


def _is_gitlink(root: Path, rev: str, path: str) -> bool:
    """True when `path` is a submodule (gitlink, mode 160000) in `rev`."""
    data = gitfiles.run_git(root, *_SAFE, "ls-tree", "-z", rev, "--", path)
    return data.startswith(b"160000 ")


def _is_submodule_folder(path: Path) -> bool:
    """A checked-out submodule: a folder with its own .git (a file or a folder)."""
    return os.path.isdir(path) and os.path.lexists(path / ".git")


def _marked_binary(root: Path, path: str) -> bool:
    """True when .gitattributes marks the path as not diffable as text (`binary`, which
    implies `-diff`, or `-diff` itself), as git does for tracked files."""
    r = gitfiles.git_status(root, *_SAFE, "check-attr", "-z", "diff", "--", path)
    parts = r.stdout.split(b"\0")
    return r.returncode == 0 and len(parts) >= 3 and parts[2] == b"unset"


def _blob_size(root: Path, rev: str, path: str) -> int | None:
    r = gitfiles.git_status(root, *_SAFE, "cat-file", "-s", f"{rev}:{path}")
    try:
        return int(r.stdout.decode("ascii").strip()) if r.returncode == 0 else None
    except ValueError:
        return None


def _blob(root: Path, rev: str, path: str) -> bytes | None:
    r = gitfiles.git_status(root, *_SAFE, "cat-file", "blob", f"{rev}:{path}")
    return r.stdout if r.returncode == 0 else None


def _read_worktree(path: Path) -> bytes | None:
    try:
        if os.path.islink(path):
            return os.readlink(path).encode("utf-8", "surrogateescape")
        return path.read_bytes()
    except OSError:
        return None


__all__ = ["analysis", "ORIGINS", "KINDS", "MAX_FILE_BYTES", "MAX_DIFF_BYTES", "Change", "ChangeSet", "ChangedLines",
           "collect", "changed_lines", "parse_name_status", "parse_unified_diff", "PathError", "repo_path"]
