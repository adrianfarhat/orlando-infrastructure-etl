"""Closed-document updates as recoverable transactions (T-97 PR B2b-1, decisions D1-D8).

`python -m tools.design refresh-blocks` refreshes the out-of-date diagram blocks (case 1 only;
never a conflict) of several feature documents that are not open in an editor. Every listed
document is updated, or none is. A crash part-way through leaves a durable record from which
the update can be completed or undone, by an explicit action only.

The record (D1) is a folder `designs/diagrams/.transactions/<id>/` (ignored by Git):
  journal.json  the format, version, state, process, registry and source revisions, and for
                every file its path, the SHA-256 of its original and of its replacement bytes,
                the diagram IDs refreshed, and a checksum over the whole journal;
  <n>.orig      the exact original bytes of file n;
  <n>.new       the exact replacement bytes of file n.

Protocol (all under the registry lock, which every cooperating writer takes; D3):
  0. refuse while a Git operation is in progress (D4), while an unresolved or unreadable record
     holds any of the files, while a Feature Designer window lists one of them as open (D6), or
     when a file changed since it was listed;
  1. prepare in `<id>.preparing/` (bytes and journal written and flushed to disk), then rename
     it to `<id>/` (state "prepared"; no document has been touched);
  2. commit (state "committing"): for each file, check its bytes are still the original ones,
     replace it (a flushed temporary file renamed over it) and verify the result;
  3. state "committed", then the record is renamed `<id>.done/` and removed.
A failure during step 2 undoes the files already replaced (only those still exactly as written).

Recovery judges every file only by its current bytes: the replacement (updated), the original
(not updated), or anything else (changed by someone since: never overwritten). Complete writes
the replacement over originals, Undo writes the original over replacements; both are idempotent
and can be repeated after an interruption, including one during recovery itself. Complete first
revalidates the registry and every source the replacement was computed from. A record is removed
only when every file is in the state the action leads to, or by an explicit abandonment (D8).

Limits (stated, not hidden):
- Between checking a file's bytes and renaming the replacement over it (a temporary file is
  written and flushed, then renamed), another program that does not take the registry lock can
  still write that file; such a write is then replaced. The window is short (milliseconds) but
  real. No absolute atomicity against non-cooperating programs is claimed.
- Windows has no directory flush; the renames rely on the file system's own metadata journal.
- Open documents are known only from Feature Designer windows (decision D6): a VS Code window
  without the extension (another installation, Restricted Mode, the repository opened as a
  subfolder), another editor, or a window silent for more than WINDOW_LIVE seconds (asleep or
  hung) is not seen; a document opened in the last moment before the check (a window publishes
  within about 0.1 s of a change, and every 5 s) may be missed.
- Git operations are checked by the update and by recovery (D4), not by `index`, `new feature`
  or `reconcile`.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import posixpath
import re
import secrets
import stat
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .workspace import DesignError, Problem

TX_ROOT = "designs/diagrams/.transactions"
WINDOWS = TX_ROOT + "/windows"
FEATURES = "designs/features/"
JOURNAL = "journal.json"
FORMAT, VERSION = "feature-design-transaction", 1
WINDOW_FORMAT = "feature-designer-window"
ID_RE = re.compile(r"tx-\d{8}T\d{6}Z-[0-9a-f]{8}\Z")
WINDOW_RE = re.compile(r"[0-9a-f]{16}\.json\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
BLOB_RE = re.compile(r"(\d+)\.(orig|new)\Z")
STATES = ("prepared", "committing", "rolling-back", "completing", "undoing", "needs-attention", "committed")
MAX_FILES = 200
MAX_BYTES = 8 << 20
MAX_JOURNAL = 1 << 20
WINDOW_FRESH = 20.0            # seconds: an unreadable window file this recent may belong to a running window
WINDOW_LIVE = 120.0            # a window rewrites its file every 5 s; one silent for longer has ended (or hangs)
WINDOW_OTHER_HOST = 600.0      # another computer's clock may differ: its window counts for longer
GIT_MARKERS = ("index.lock", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "rebase-merge", "rebase-apply",
               "sequencer")
CODE = "E16"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- test fault points

def _fault_here(root: Path) -> bool:
    """Whether DESIGN_TEST_FAULT_ROOT names this repository (compared as the file system does)."""
    named = os.environ.get("DESIGN_TEST_FAULT_ROOT")
    return bool(named) and os.path.normcase(str(Path(named).resolve())) == os.path.normcase(str(Path(root).resolve()))


def _fault(root: Path, point: str) -> None:
    """Crash injection for the automated tests only: inert unless DESIGN_TEST_FAULT names this
    point and DESIGN_TEST_FAULT_ROOT names this repository exactly."""
    if os.environ.get("DESIGN_TEST_FAULT") != point or not _fault_here(root):
        return
    if os.environ.get("DESIGN_TEST_FAULT_MODE") == "sleep":   # the test then terminates the process itself
        sys.stderr.write(f"FAULT {point}\n")
        sys.stderr.flush()
        time.sleep(120)
    os._exit(97)


# --------------------------------------------------------------------------- paths

def _is_link(p: Path) -> bool:
    """A symbolic link, a junction or any other reparse point (never followed)."""
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & 0x400)     # FILE_ATTRIBUTE_REPARSE_POINT


def _clean_rel(rel) -> str:
    if not isinstance(rel, str) or not rel or len(rel) > 400 or "\\" in rel or "\0" in rel or ":" in rel:
        raise DesignError(f"{rel!r} is not a repository path")
    if rel.startswith("/") or posixpath.normpath(rel) != rel or any(p in ("", ".", "..") for p in rel.split("/")):
        raise DesignError(f"{rel!r} is not a normalised repository path")
    return rel


def safe_path(root: Path, rel, feature: bool = True) -> Path:
    """`rel` inside the repository, with no symbolic link or junction on the way. With `feature`
    (every document this module writes): a feature document under designs/features/, never
    docs/architecture/ or any other file. Without it (a diagram source that is only read, which
    may be an architecture document): any repository path."""
    rel = _clean_rel(rel)
    if feature and (rel == "docs/architecture" or rel.startswith("docs/architecture/")):
        raise DesignError(f"{rel} is under docs/architecture/; nothing is written there")
    if feature and not (rel.startswith(FEATURES) and rel.endswith(".md")):
        raise DesignError(f"{rel} is not a feature document under {FEATURES}")
    root = Path(root)
    p = root
    for part in rel.split("/"):
        p = p / part
        if _is_link(p):
            raise DesignError(f"{rel} goes through a symbolic link or junction ({p.relative_to(root).as_posix()}); "
                              "nothing is written there")
    real, base = os.path.realpath(p), os.path.realpath(root)
    if os.path.normcase(real) != os.path.normcase(os.path.join(base, *rel.split("/"))):
        raise DesignError(f"{rel} does not resolve inside the repository")
    return p


def _tx_root(root: Path, create: bool) -> Path | None:
    p = Path(root)
    for part in TX_ROOT.split("/"):
        p = p / part
        if _is_link(p):
            raise DesignError(f"{TX_ROOT} goes through a symbolic link or junction; nothing was changed ({CODE})")
    if not p.is_dir():
        if not create:
            return None
        p.mkdir(parents=True, exist_ok=True)
    return p


# --------------------------------------------------------------------------- durable writes

def _write_new(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    if sys.platform == "win32":            # no directory flush on Windows (NTFS journals the rename)
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _replace(target: Path, data: bytes, prefix: str = ".feature.") -> None:
    """Replace `target` with exactly `data`: a flushed temporary file beside it, renamed over it."""
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=prefix, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    _fsync_dir(target.parent)


def _canonical(data: dict) -> bytes:
    return json.dumps({k: v for k, v in data.items() if k != "checksum"}, sort_keys=True,
                      ensure_ascii=True, separators=(",", ":")).encode("ascii")


def _save_journal(folder: Path, data: dict) -> None:
    data = dict(data)
    data["checksum"] = _sha(_canonical(data))
    tmp = folder / ".journal.tmp"
    if tmp.exists():
        tmp.unlink()
    _write_new(tmp, json.dumps(data, sort_keys=True, indent=1, ensure_ascii=True).encode("ascii"))
    os.replace(tmp, folder / JOURNAL)
    _fsync_dir(folder)


# --------------------------------------------------------------------------- Git (D4)

def _git_dir(root: Path) -> Path | None:
    dot = Path(root) / ".git"
    if dot.is_dir():
        return dot
    if dot.is_file():
        try:
            line = dot.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return None
        if line.startswith("gitdir:"):
            p = Path(line[7:].strip())
            return p if p.is_absolute() else (Path(root) / p)
    return None


def git_busy(root: Path) -> str:
    """The Git operation in progress in this working tree ('' when none)."""
    gd = _git_dir(root)
    if gd is None:
        return ""
    for name in GIT_MARKERS:
        if (gd / name).exists():
            return name
    return ""


def _git_ready(root: Path) -> None:
    for attempt in range(8):               # index.lock is also taken briefly by `git status` (VS Code)
        busy = git_busy(root)
        if not busy:
            return
        if busy != "index.lock" or attempt == 7:
            break
        time.sleep(0.25)
    raise DesignError(f"a Git operation is in progress ({busy} in the Git folder); nothing was changed. "
                      "Finish or abort it, then try again")


# --------------------------------------------------------------------------- open documents (D6)

def _key(rel: str) -> str:
    """Paths compared as the file system does (Windows ignores letter case)."""
    return rel.casefold() if sys.platform == "win32" else rel


def open_documents(root: Path, exclude_window: str = "") -> tuple[dict[str, list[str]], list[str]]:
    """Feature documents that Feature Designer windows that may still be running list as open:
    {path: [description]}, and the windows whose file cannot be read but may be live (these
    block every update, because what they have open is unknown)."""
    folder = Path(root) / WINDOWS
    found: dict[str, list[str]] = {}
    unknown: list[str] = []
    try:
        if not folder.is_dir() or _is_link(folder) or _is_link(folder.parent):
            return found, unknown
        names = sorted(os.listdir(folder))
    except OSError:
        return found, unknown
    now = time.time()
    me = platform.node().lower()
    for name in names:
        p = folder / name
        if not WINDOW_RE.match(name) or name[:-5] == exclude_window:
            continue
        try:
            st = os.lstat(p)
            age_file = now - st.st_mtime
            if _is_link(p) or st.st_size > (256 << 10):
                raise ValueError("not a plain file")
            raw = None
            for attempt in range(5):           # the window may be replacing its file at this instant (Windows refuses the read)
                try:
                    raw = p.read_bytes()
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.05)
            data = json.loads(raw.decode("utf-8"))
            if not (isinstance(data, dict) and data.get("format") == WINDOW_FORMAT and data.get("version") == 1
                    and isinstance(data.get("pid"), int) and isinstance(data.get("host"), str)
                    and isinstance(data.get("heartbeat"), (int, float)) and isinstance(data.get("documents"), list)):
                raise ValueError("not a window record")
        except (OSError, ValueError, UnicodeDecodeError):
            if age_file < WINDOW_FRESH:             # written moments ago by a window that may be running
                unknown.append(name)
            continue
        age = now - max(float(data["heartbeat"]), st.st_mtime)
        # Liveness by heartbeat only (this package runs no process API). The extension removes the files
        # of windows whose process has ended; one that hangs longer than WINDOW_LIVE is not seen (stated).
        if age >= (WINDOW_OTHER_HOST if data["host"].lower() != me else WINDOW_LIVE):
            continue
        desc = f"a VS Code window (process {data['pid']}" + (f" on {data['host']}" if data["host"].lower() != me else "") + ")"
        for d in data["documents"]:
            if isinstance(d, dict) and isinstance(d.get("path"), str):
                found.setdefault(_key(d["path"]), []).append(desc + (" with unsaved changes" if d.get("dirty") else ""))
    return found, unknown


# --------------------------------------------------------------------------- reading records

class Record:
    """One transaction record, validated. `problem` is '' when it can be used."""

    def __init__(self, folder: Path, data: dict | None, problem: str):
        self.folder, self.data, self.problem = folder, data, problem
        self.id = folder.name

    @property
    def files(self) -> list[dict]:
        return self.data["files"] if self.data else []


def _read_record(root: Path, folder: Path) -> Record:
    def bad(why: str) -> Record:
        return Record(folder, None, why)
    try:
        if _is_link(folder):
            return bad("the record folder is a symbolic link or junction")
        if not ID_RE.match(folder.name):
            return bad("the record folder has an unexpected name")
        names = set(os.listdir(folder))
        jp = folder / JOURNAL
        if JOURNAL not in names:
            return bad("journal.json is missing")
        if _is_link(jp) or jp.stat().st_size > MAX_JOURNAL:
            return bad("journal.json is not a plain file of a plausible size")
        data = json.loads(jp.read_bytes().decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        return bad(f"journal.json cannot be read ({type(exc).__name__})")
    if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("version") != VERSION:
        return bad("journal.json is not a version-1 transaction record")
    if data.get("checksum") != _sha(_canonical(data)):
        return bad("journal.json does not match its checksum (it was changed or damaged)")
    if data.get("id") != folder.name or data.get("tool") != "refresh-blocks" or data.get("state") not in STATES:
        return bad("journal.json names another record, tool or an unknown state")
    if not isinstance(data.get("pid"), int) or not isinstance(data.get("host"), str):
        return bad("journal.json does not record its process")
    if not isinstance(data.get("history", []), list) or not isinstance(data.get("action", ""), str):
        return bad("journal.json has a malformed history")
    reg_sha = data.get("registry_sha")
    if reg_sha is not None and not (isinstance(reg_sha, str) and HEX64.match(reg_sha)):
        return bad("the registry revision is malformed")
    sources = data.get("sources")
    if not isinstance(sources, dict) or len(sources) > 1000:
        return bad("the source revisions are malformed")
    for p, h in sources.items():
        try:
            _clean_rel(p)
        except DesignError:
            return bad(f"source path {p!r} is not a repository path")
        if not (isinstance(h, str) and HEX64.match(h)):
            return bad(f"the revision of {p} is malformed")
    files = data.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        return bad("the file list is malformed")
    expected = {JOURNAL, ".journal.tmp"}
    seen = set()
    for i, f in enumerate(files):
        if not isinstance(f, dict):
            return bad("a file entry is malformed")
        try:
            safe_path(root, f.get("path"))
        except DesignError as exc:
            return bad(f"file {i + 1}: {exc}")
        if _key(f["path"]) in seen:
            return bad(f"{f['path']} is listed twice")
        seen.add(_key(f["path"]))
        for key in ("before_sha", "after_sha"):
            if not (isinstance(f.get(key), str) and HEX64.match(f[key])):
                return bad(f"{f['path']}: {key} is malformed")
        if f["before_sha"] == f["after_sha"]:
            return bad(f"{f['path']}: the original and the replacement are the same")
        if f.get("orig") != f"{i}.orig" or f.get("new") != f"{i}.new":
            return bad(f"{f['path']}: unexpected data file names")
        if not isinstance(f.get("blocks"), list) or not all(isinstance(b, str) for b in f["blocks"]):
            return bad(f"{f['path']}: the block list is malformed")
        for key, want in (("orig", "before_sha"), ("new", "after_sha")):
            bp = folder / f[key]
            try:
                if _is_link(bp) or not bp.is_file() or bp.stat().st_size > MAX_BYTES:
                    return bad(f"{f[key]} (for {f['path']}) is missing or not a plain file")
                if _sha(bp.read_bytes()) != f[want]:
                    return bad(f"{f[key]} (for {f['path']}) does not match its recorded checksum")
            except OSError:
                return bad(f"{f[key]} (for {f['path']}) cannot be read")
        expected.update((f["orig"], f["new"]))
    extra = names - expected
    if extra:
        return bad(f"unexpected files in the record: {', '.join(sorted(extra))}")
    return Record(folder, data, "")


def records(root: Path) -> list[Record]:
    """Every unresolved transaction record (valid or not), oldest first. Read only."""
    tx = _tx_root(root, create=False)
    if tx is None:
        return []
    out = []
    for name in sorted(os.listdir(tx)):
        p = tx / name
        if name == "windows" or name.endswith(".preparing") or name.endswith(".done") or name.startswith("."):
            continue
        if not ID_RE.match(name):                      # not a record this tooling made: never read or used
            continue
        if p.is_dir() or _is_link(p):
            r = _read_record(root, p)
            if not r.problem and r.data["state"] == "committed":
                continue                               # verified complete; only its removal was interrupted
            out.append(r)
    return out


def file_state(root: Path, f: dict) -> str:
    """updated (the replacement), original, changed (anything else) or missing."""
    try:
        p = safe_path(root, f["path"])
    except DesignError:
        return "changed"
    if not p.is_file():
        return "missing"
    try:
        h = _sha(p.read_bytes())
    except OSError:
        return "changed"
    return "updated" if h == f["after_sha"] else "original" if h == f["before_sha"] else "changed"


def _registry_sha(root: Path) -> str | None:
    from . import registry
    p = Path(root) / registry.REGISTRY
    return _sha(p.read_bytes()) if p.is_file() else None


def _source_changes(root: Path, rec: Record) -> list[str]:
    """What changed since the replacement bytes were computed (requirement 5)."""
    out = []
    if _registry_sha(root) != rec.data.get("registry_sha"):
        out.append("the diagram registry")
    for p, h in sorted(rec.data["sources"].items()):
        try:
            q = safe_path(root, p, feature=False)
            now = _sha(q.read_bytes()) if q.is_file() else None
        except (DesignError, OSError):
            now = None
        if now != h:
            out.append(p)
    return out


def describe(root: Path, rec: Record, live: bool | None = None) -> dict:
    """Everything the person deciding needs: each file's current state and what Complete, Undo
    and Abandon would do, and a token that changes whenever any of it changes."""
    root = Path(root)
    if live is None:
        live = _other_holds_lock(root)
    out = {"id": rec.id, "valid": not rec.problem, "problem": rec.problem, "live": live}
    if rec.problem:
        try:
            listing = sorted((n, os.lstat(rec.folder / n).st_size) for n in os.listdir(rec.folder))
        except OSError:
            listing = []
        out.update(files=[], complete={"possible": False, "reason": "the record cannot be trusted: " + rec.problem},
                   undo={"possible": False, "reason": "the record cannot be trusted: " + rec.problem},
                   abandon={"possible": not live, "effect": "removes the unreadable record; no document is changed"})
        out["token"] = _sha(json.dumps([rec.id, rec.problem, listing, live]).encode())[:16]
        return out
    d = rec.data
    files = [{"path": f["path"], "blocks": f["blocks"], "state": file_state(root, f)} for f in rec.files]
    changes = _source_changes(root, rec)
    to_write = [f["path"] for f in files if f["state"] == "original"]
    to_undo = [f["path"] for f in files if f["state"] == "updated"]
    left = [f["path"] for f in files if f["state"] in ("changed", "missing")]
    opened, unknown = open_documents(root)                # D6 also holds for recovery: never under an open editor
    busy = sorted({p for p in to_write + to_undo if _key(p) in opened})
    for f in files:
        f["open"] = "; ".join(opened.get(_key(f["path"]), []))
    if live:
        complete = undo = {"possible": False, "reason": "the registry lock is held by a process that may still be "
                                                       "running (or cannot be verified from here: another computer, "
                                                       "an unreadable lock file); wait for it, or check it with "
                                                       "`python -m tools.design registry unlock`"}
    elif busy or unknown:
        why = (f"close {', '.join(busy)} first: open in " + "; ".join(sorted({w for p in busy for w in opened[_key(p)]}))
               if busy else "a Feature Designer window's list of open documents cannot be read; try again in a moment")
        complete = {"possible": False, "reason": why, "writes": to_write, "left_alone": left}
        undo = {"possible": False, "reason": why, "restores": to_undo, "left_alone": left}
    else:
        complete = {"possible": not (to_write and changes), "writes": to_write, "left_alone": left,
                    "reason": (f"refused: {', '.join(changes)} changed since the update was prepared, so its "
                               "replacement text may be out of date; use Undo, then update again") if to_write and changes else ""}
        undo = {"possible": True, "restores": to_undo, "left_alone": left, "reason": ""}
    out.update(state=d["state"], action=d.get("action") or "", created=d.get("created", ""), pid=d["pid"],
               host=d["host"], files=files, source_changes=changes, complete=complete, undo=undo,
               abandon={"possible": not live, "effect": "removes the record and the preserved original and replacement "
                                                        "copies; every document stays exactly as it is now"})
    out["token"] = _sha(json.dumps([d["checksum"], [(f["path"], f["state"], bool(f["open"])) for f in files], changes, live,
                                    bool(unknown)], sort_keys=True).encode())[:16]
    return out


def status(root: Path) -> list[dict]:
    """Every unresolved record with its description. Read only (used by `check`, the Feature
    Designer and `transaction status`)."""
    root = Path(root).resolve()
    live = _other_holds_lock(root)
    return [describe(root, r, live) for r in records(root)]


def held(root: Path) -> tuple[set[str], list[str]]:
    """Paths held by unresolved records, and the IDs of records that cannot be read (these hold
    every feature document, since what they cover is unknown)."""
    paths: set[str] = set()
    bad: list[str] = []
    for r in records(root):
        if r.problem:
            bad.append(r.id)
        else:
            paths.update(f["path"] for f in r.files)
    return paths, bad


def problems(root: Path) -> list[Problem]:
    """For `check`: one problem per unresolved record (E16)."""
    out = []
    for r in records(root):
        what = (f"cannot be read ({r.problem})" if r.problem else
                f"was interrupted ({r.data['state']}) and holds {len(r.files)} document(s): "
                + ", ".join(f['path'] for f in r.files))
        out.append(Problem(f"{TX_ROOT}/{r.id}", f"an update of closed documents {what}; nothing is written to those "
                           f"documents until it is resolved: run `python -m tools.design transaction status` ({CODE})"))
    return out


def guard(root: Path, paths=None) -> None:
    """For every cooperating writer (D3), inside the registry lock: refuse to write a document
    held by an unresolved record (paths None: any feature document). Folders no running process
    can own are removed first (only while this process holds the lock)."""
    from . import registry
    if registry.holds_lock(root):
        _remove_debris(root)
    hold, bad = held(root)
    if bad:
        raise DesignError(f"an update record cannot be read ({', '.join(bad)}), so no feature document is written until "
                          f"it is resolved: run `python -m tools.design transaction status` ({CODE})")
    hit = sorted(hold if paths is None else hold & set(paths))
    if hit:
        raise DesignError(f"{', '.join(hit)} {'is' if len(hit) == 1 else 'are'} part of an interrupted update; nothing "
                          f"was written. Resolve it first: `python -m tools.design transaction status` ({CODE})")


# --------------------------------------------------------------------------- locking

def _other_holds_lock(root: Path) -> bool:
    """Whether another process that may still be running holds the registry lock: the same check
    as `registry unlock` (the operating-system lock its process holds until it ends)."""
    from . import registry
    if registry.holds_lock(root):
        return False
    if not (Path(root) / registry.LOCK).exists():
        return False
    return not registry.unlock(root, confirm=False, patient=False).removable   # one instant: never keep the file open


def _remove_flat(folder: Path) -> None:
    """Remove a record folder (it only ever holds plain files)."""
    for name in sorted(os.listdir(folder)):
        p = folder / name
        if p.is_dir() and not _is_link(p):
            raise DesignError(f"{folder.name} contains a folder ({name}); remove it by hand")
        os.unlink(p)
    os.rmdir(folder)


def _remove_debris(root: Path) -> list[str]:
    """Inside the lock: folders no running process can own. `<id>.preparing` (no document was
    touched yet), `<id>.done` (resolved, being removed), and records whose state is "committed"
    (every document was verified)."""
    tx = _tx_root(root, create=False)
    done = []
    if tx is None:
        return done
    for name in sorted(os.listdir(tx)):
        p = tx / name
        if _is_link(p) or not p.is_dir():
            continue
        if (name.endswith(".preparing") or name.endswith(".done")) and ID_RE.match(name.rsplit(".", 1)[0]):
            _remove_flat(p)
            done.append(name)
        elif ID_RE.match(name):
            r = _read_record(root, p)
            if not r.problem and r.data["state"] == "committed":
                _finish(root, r)
                done.append(name)
    return done


def _finish(root: Path, rec: Record) -> None:
    """Remove a resolved record: renamed first, so an interruption leaves only `<id>.done`."""
    done = rec.folder.with_name(rec.id + ".done")
    os.rename(rec.folder, done)
    _fault(root, "after-done-rename")
    for i, name in enumerate(sorted(os.listdir(done))):
        os.unlink(done / name)
        _fault(root, f"during-cleanup:{i + 1}")
    os.rmdir(done)


def _set(root: Path, rec: Record, **changes) -> None:
    rec.data.update(changes)
    rec.data.setdefault("history", []).append({"time": _now(), "state": rec.data["state"],
                                               "action": rec.data.get("action") or ""})
    _save_journal(rec.folder, rec.data)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- planning

def sources_token(root: Path, known=None) -> str:
    """Changes whenever the registry or any diagram source changes (what the listed documents'
    replacement text is computed from)."""
    from . import diagrams
    known = diagrams.sources(root) if known is None else known
    body = {k: [s.kind, s.title, s.path, s.anchor, list(s.lines), s.legend, s.closed, s.problem]
            for k, s in sorted(known.items())}
    return _sha(json.dumps([_registry_sha(root), body], sort_keys=True, ensure_ascii=True).encode())[:16]


def affected(root: Path, exclude_window: str = "") -> dict:
    """Feature documents on disk whose diagram blocks `refresh-blocks` would refresh, with their
    hashes, the conflicts it would leave alone, and why a document would be excluded. Read only."""
    from . import diagrams
    from .workspace import discover
    root = Path(root).resolve()
    known = diagrams.sources(root)
    hold, bad = held(root)
    opened, unknown = open_documents(root, exclude_window)
    docs = []
    features, _ = discover(root)
    for f in features:
        if not f.meta_ok:
            continue
        try:
            p = safe_path(root, f.path)
            data = p.read_bytes()
            text = data.decode("utf-8")
        except (DesignError, OSError, UnicodeDecodeError):
            continue
        blocks, _ = diagrams.scan(text)
        if not blocks or diagrams.blocking(text, f.path, known):
            continue
        todo = diagrams.regenerated(text, f.path, known)
        if not todo:
            continue
        lines = text.replace("\r\n", "\n").split("\n")
        ids = [diagrams.START.match(new[0]).group("id") for _s, _e, new in todo]
        conflicts = [b.diagram_id for b in blocks if diagrams._usable(b, known) and diagrams.classify(
            b, lines[b.start + 1:b.end], diagrams.render(known[b.diagram_id], f.path)) in diagrams.CONFLICTS]
        excluded = ("part of an update that is running or was interrupted" if f.path in hold or bad else
                    "open in " + "; ".join(opened[_key(f.path)]) if _key(f.path) in opened else "")
        docs.append({"path": f.path, "sha256": _sha(data), "blocks": ids, "conflicts": conflicts, "excluded": excluded})
    return {"documents": docs, "sources_token": sources_token(root, known), "unknown_windows": unknown,
            "unreadable_records": bad}


# --------------------------------------------------------------------------- the update

def update(root: Path, requests: list[tuple[str, str]], expect_token: str | None = None) -> dict:
    """Refresh the listed documents (path, expected SHA-256) as one transaction."""
    from . import diagrams, registry
    from .workspace import discover
    root = Path(root).resolve()
    if not requests:
        raise DesignError("no document to update")
    paths = [p for p, _ in requests]
    if len(set(paths)) != len(paths):
        raise DesignError("a document is listed twice")
    if len(paths) > MAX_FILES:
        raise DesignError(f"at most {MAX_FILES} documents per update")
    with registry.lock(root):
        _git_ready(root)
        _remove_debris(root)
        guard(root, paths)
        features = {f.path: f for f in discover(root)[0]}
        for p in paths:
            safe_path(root, p)
            if p not in features or not features[p].meta_ok:
                raise DesignError(f"{p} is not a feature specification with valid metadata; nothing was changed")
        opened, unknown = open_documents(root)          # every window, the caller's too (it may have opened one since)
        if unknown:
            raise DesignError("a Feature Designer window's list of open documents cannot be read "
                              f"({', '.join(unknown)}), so no document is updated now; try again in a moment")
        busy_docs = [f"{p} is open in {'; '.join(opened[_key(p)])}" for p in paths if _key(p) in opened]
        if busy_docs:
            raise DesignError("; ".join(busy_docs) + ". Documents open in an editor are updated there, not on disk; "
                              "nothing was changed")
        known = diagrams.sources(root)
        token = sources_token(root, known)
        if expect_token is not None and expect_token != token:
            raise DesignError("a diagram source or the registry changed since the documents were listed; nothing was "
                              "changed. List them again")
        plan = []
        for p, expect in requests:
            data = safe_path(root, p).read_bytes()
            if _sha(data) != expect:
                raise DesignError(f"{p} changed since it was listed; nothing was changed. List the documents again")
            text = data.decode("utf-8")
            if diagrams.blocking(text, p, known):
                raise DesignError(f"{p} has a diagram problem that must be fixed first; nothing was changed")
            todo = diagrams.regenerated(text, p, known)
            new = diagrams.apply(text, p, known).encode("utf-8")
            if not todo or new == data:
                raise DesignError(f"{p} has no out-of-date diagram block; nothing was changed. List the documents again")
            ids = [diagrams.START.match(n[0]).group("id") for _s, _e, n in todo]
            plan.append((p, data, new, ids, sorted({known[i].path for i in ids})))
        src_revs = {}
        for _p, _d, _n, _ids, srcs in plan:
            for s in srcs:
                q = safe_path(root, s, feature=False)
                src_revs[s] = _sha(q.read_bytes())
        rec = _prepare(root, plan, src_revs)
        # D4 and requirement 5: the repository, the registry and the sources once more, just before writing
        try:
            _git_ready(root)
            if sources_token(root) != token or _source_changes(root, rec):
                raise DesignError("a diagram source or the registry changed while the update was prepared")
        except DesignError as exc:
            _finish(root, rec)                         # no document was touched
            raise DesignError(f"{exc}; nothing was changed") from None
        return _commit(root, rec)


def _prepare(root: Path, plan, src_revs: dict) -> Record:
    tx = _tx_root(root, create=True)
    tx_id = f"tx-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
    staging = tx / (tx_id + ".preparing")
    staging.mkdir()
    files = []
    for i, (p, data, new, ids, _srcs) in enumerate(plan):
        _write_new(staging / f"{i}.orig", data)
        _fault(root, f"after-orig:{i + 1}")
        _write_new(staging / f"{i}.new", new)
        _fault(root, f"after-new:{i + 1}")
        files.append({"path": p, "before_sha": _sha(data), "after_sha": _sha(new), "before_size": len(data),
                      "after_size": len(new), "orig": f"{i}.orig", "new": f"{i}.new", "blocks": ids})
    data = {"format": FORMAT, "version": VERSION, "id": tx_id, "tool": "refresh-blocks", "pid": os.getpid(),
            "host": platform.node(), "created": _now(), "state": "prepared", "action": "",
            "registry_sha": _registry_sha(root), "sources": src_revs, "files": files,
            "history": [{"time": _now(), "state": "prepared", "action": ""}]}
    _fault(root, "before-journal")
    _save_journal(staging, data)
    _fault(root, "after-journal")
    os.rename(staging, tx / tx_id)
    _fsync_dir(tx)
    _fault(root, "after-prepare")
    rec = _read_record(root, tx / tx_id)
    if rec.problem:                                    # what was just written must read back exactly
        raise DesignError(f"the update record could not be verified ({rec.problem}); no document was changed")
    return rec


def _write_file(root: Path, rec: Record, f: dict, want: str, blob: str) -> str:
    """Replace one document with `blob`, only if it currently has `want` (compare and swap).
    "skipped": not written (it did not have `want`); "written": replaced and verified;
    "unverified": replaced, but the file read back is not what was written."""
    _git_ready(root)
    p = safe_path(root, f["path"])
    if not p.is_file() or _sha(p.read_bytes()) != want:
        return "skipped"
    data = (rec.folder / f[blob]).read_bytes()
    if _sha(data) != f["after_sha" if blob == "new" else "before_sha"]:
        raise DesignError(f"the preserved copy {f[blob]} no longer matches its checksum; nothing was written to {f['path']}")
    _replace(p, data)
    return "written" if _sha(p.read_bytes()) == _sha(data) else "unverified"


def _commit(root: Path, rec: Record) -> dict:
    _set(root, rec, state="committing")
    _fault(root, "after-committing-mark")
    failure = ""
    replaced = set()                                   # the documents this update wrote
    for i, f in enumerate(rec.files):
        try:
            if os.environ.get("DESIGN_TEST_FAULT") == f"change-before-replace:{i + 1}" and _fault_here(root):
                with open(safe_path(root, f["path"]), "ab") as h:      # a concurrent external edit (tests only)
                    h.write(b"\nexternal edit\n")
            _fault(root, f"before-replace:{i + 1}")
            done = _write_file(root, rec, f, f["before_sha"], "new")
            if done == "skipped":
                failure = f"{f['path']} changed during the update"
                break
            replaced.add(f["path"])
            if done == "unverified":
                failure = f"{f['path']} was replaced, but what is on disk now is not what was written"
                break
            _fault(root, f"after-replace:{i + 1}")
        except (OSError, DesignError) as exc:
            failure = f"{f['path']} could not be written ({exc})"
            replaced.add(f["path"])                    # it may or may not have been replaced
            break
    if not failure:
        _fault(root, "before-committed-mark")
        _set(root, rec, state="committed")
        _fault(root, "after-committed-mark")
        _finish(root, rec)
        return {"ok": True, "id": rec.id, "files": [{"path": f["path"], "blocks": f["blocks"], "state": "updated"}
                                                    for f in rec.files]}
    _set(root, rec, state="rolling-back", action="rollback")
    for i, f in enumerate(rec.files):
        try:
            if file_state(root, f) == "updated":
                _write_file(root, rec, f, f["after_sha"], "orig")
        except (OSError, DesignError):
            pass
        _fault(root, f"rollback-after:{i + 1}")
    states = {f["path"]: file_state(root, f) for f in rec.files}
    # Resolved when no document still holds this update's text, and every document it wrote is back
    # to its original; a document it never wrote that someone else changed is theirs, not this update's.
    ours = [p for p, st in states.items() if st == "updated" or (p in replaced and st != "original")]
    if not ours:
        _finish(root, rec)
        others = [p for p, st in states.items() if st != "original"]
        raise DesignError(f"{failure}; every document this update wrote is back to its original, so this update "
                          "changed nothing" + (f" ({', '.join(others)} was changed by another program before this "
                                               "update wrote it)" if others else ""))
    _set(root, rec, state="needs-attention")
    left = ", ".join(f"{p} ({states[p]})" for p in ours)
    raise DesignError(f"{failure}; PARTLY DONE: not every document could be put back ({left}). The record "
                      f"{rec.id} keeps every original: run `python -m tools.design transaction status` ({CODE})")


# --------------------------------------------------------------------------- recovery

def _stale_lock(root: Path) -> str:
    """Before an explicit recovery action: remove a registry lock that no process holds (the
    process that took it was terminated), with the same verification as `registry unlock`."""
    from . import registry
    if not (Path(root) / registry.LOCK).exists():
        return ""
    st = registry.unlock(root, confirm=False)
    if not st.removable:
        return ""
    registry.unlock(root, confirm=True)
    return f"removed the registry lock left by process {st.pid}, which has ended"


def resolve(root: Path, tx_id: str, action: str, token: str) -> dict:
    """Complete, Undo or Abandon one record, only on the state the person saw (`token`)."""
    from . import diagrams, registry
    root = Path(root).resolve()
    if action not in ("complete", "undo", "abandon"):
        raise DesignError("the action must be complete, undo or abandon")
    if not isinstance(tx_id, str) or not ID_RE.match(tx_id):
        raise DesignError(f"{tx_id!r} is not an update record ID")
    note = _stale_lock(root)
    with registry.lock(root):
        _git_ready(root)
        _remove_debris(root)
        tx = _tx_root(root, create=False)
        folder = tx / tx_id if tx is not None else None
        if folder is None or not (folder.is_dir() or _is_link(folder)):
            return {"ok": True, "id": tx_id, "action": action, "already": True, "note": note,
                    "message": "this update was already resolved (here or in another window, by Complete, Undo or "
                               "Abandon); nothing was done now. Check the documents"}
        rec = _read_record(root, folder)
        now = describe(root, rec, live=False)
        if now["token"] != token:
            raise DesignError("the documents or the record changed since they were shown; nothing was changed. Show "
                              "the update again and decide on what it shows now")
        if action == "abandon":
            if _is_link(folder):                    # only the link itself: never anything it points to
                try:
                    os.unlink(folder)
                except OSError:
                    os.rmdir(folder)                     # a directory junction (Windows)
            elif rec.problem:
                done = folder.with_name(tx_id + ".done")
                os.rename(folder, done)
                _remove_flat(done)
            else:
                _finish(root, rec)
            return {"ok": True, "id": tx_id, "action": action, "note": note, "files": now["files"],
                    "message": "the record was removed; no document was changed"}
        if rec.problem:
            raise DesignError(f"the record cannot be trusted ({rec.problem}): only Abandon is possible")
        if action == "undo" and not now["undo"]["possible"]:
            raise DesignError(now["undo"]["reason"])
        if action == "complete":
            if not now["complete"]["possible"]:
                raise DesignError(now["complete"]["reason"])
            known = diagrams.sources(root)                     # the replacement is still exactly what `index` would write
            for f in rec.files:
                if file_state(root, f) == "original":
                    orig = (rec.folder / f["orig"]).read_bytes().decode("utf-8")
                    if diagrams.apply(orig, f["path"], known).encode("utf-8") != (rec.folder / f["new"]).read_bytes():
                        raise DesignError(f"the replacement for {f['path']} is no longer what its sources generate; "
                                          "use Undo, then update again. Nothing was changed")
            _set(root, rec, state="completing", action="complete")
            _fault(root, "complete-after-mark")
            for i, f in enumerate(rec.files):
                if file_state(root, f) == "original":
                    _write_file(root, rec, f, f["before_sha"], "new")
                _fault(root, f"complete-after:{i + 1}")
            goal = "updated"
        else:
            _set(root, rec, state="undoing", action="undo")
            _fault(root, "undo-after-mark")
            for i, f in enumerate(rec.files):
                if file_state(root, f) == "updated":
                    _write_file(root, rec, f, f["after_sha"], "orig")
                _fault(root, f"undo-after:{i + 1}")
            goal = "original"
        files = [{"path": f["path"], "blocks": f["blocks"], "state": file_state(root, f)} for f in rec.files]
        if all(f["state"] == goal for f in files):
            if goal == "updated":
                _set(root, rec, state="committed")
            _finish(root, rec)
            return {"ok": True, "id": tx_id, "action": action, "note": note, "files": files,
                    "message": "completed: every document is updated" if goal == "updated" else
                               "undone: every document is as it was before the update"}
        _set(root, rec, state="needs-attention")
        return {"ok": False, "id": tx_id, "action": action, "note": note, "files": files,
                "message": "partly done: the documents marked changed or missing were left alone; the record is kept"}
