"""Repository path normalization and glob matching (standard library only).

Paths and patterns are repository-relative POSIX strings. Matching is
case-sensitive, like Git, and uses `PurePosixPath.full_match`:

- `**` as a whole segment matches zero or more segments in the middle of a
  pattern (`a/**/b` matches `a/b`), and one or more at the end (`dir/**`
  matches everything inside `dir`, but not the path `dir` itself);
- `*`, `?` and `[...]` match within one segment and never cross `/`;
- dot-files and dot-folders are matched like any other name.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

WILDCARD_CHARS = frozenset("*?[")
# Repeated `**` makes full_match slow (QA: 8 x `**/*` against a deep path took ~2 s).
# Real patterns need one or two; three leaves headroom while bounding the cost.
MAX_DOUBLE_STAR_SEGMENTS = 3
# Several `*` inside one segment backtrack polynomially in the name length (measured on
# Python 3.15.2 against a non-matching name: 3 stars, 200 chars 0.012 s, 1000 chars 0.56 s;
# 4 stars, 200 chars 0.24 s, 1000 chars > 25 s). Real patterns use at most one per segment.
MAX_STARS_PER_SEGMENT = 3
_DRIVE = re.compile(r"[A-Za-z]:(/|$)")


class PathError(ValueError):
    """A path or pattern that cannot be used safely."""


MAX_SHOWN = 200


def printable(text: str, limit: int = MAX_SHOWN, double_backslash: bool = True) -> str:
    """A name as it may be shown in a report: every non-printable character (controls,
    format characters such as U+202E right-to-left override, invalid surrogates) as a
    Python escape, and cut to `limit` characters. With double_backslash (the default,
    used for raw file names) a literal backslash is doubled so escapes stay
    unambiguous; report rendering turns it off because its text may already contain
    escaped names and must not be escaped twice."""
    out = []
    for ch in text:
        code = ord(ch)
        if 0xDC80 <= code <= 0xDCFF:          # an undecodable byte kept by surrogateescape
            out.append(f"\\x{code - 0xDC00:02x}")
        elif ch == "\\" and double_backslash:
            out.append("\\\\")
        elif ch.isprintable():
            out.append(ch)
        else:
            out.append(ch.encode("unicode_escape").decode("ascii"))
    shown = "".join(out)
    return shown if len(shown) <= limit else shown[:limit] + f"... ({len(text)} characters)"


def bounded_repr(value: object, limit: int = 80) -> str:
    """A bounded description of a value for messages, computed WITHOUT calling repr()
    on containers: a YAML alias fan-out makes a tiny file expand into an exponentially
    large structure, and repr() of it can run for hours (QA: 10 levels took 66 s, each
    level about 9x more). Strings are cut before repr(); containers are summarised."""
    if isinstance(value, str):
        text = repr(value[:limit])
        return text if len(value) <= limit else f"{text}... ({len(value)} characters)"
    if value is None or isinstance(value, (bool, float)):
        return repr(value)
    if isinstance(value, int):
        try:
            text = repr(value)
        except ValueError:                    # beyond Python's int-to-string digit limit
            return "<a very large integer>"
        return text if len(text) <= limit else f"{text[:limit]}... ({len(text)} digits)"
    if isinstance(value, (list, tuple, dict, set, frozenset)):
        return f"<{type(value).__name__} of {len(value)} items>"
    return f"<{type(value).__name__}>"


_short = bounded_repr


def _check(value: object, what: str) -> str:
    if not isinstance(value, str):
        raise PathError(f"{what} must be a string, not {type(value).__name__}")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        raise PathError(f"{what} is not valid Unicode: {_short(value)}") from None
    if size > MAX_PATH_BYTES:
        raise PathError(f"{what} longer than {MAX_PATH_BYTES} bytes: {_short(value)}")
    # C0 controls, DEL and the C1 controls U+0080 to U+009F (Unicode category Cc).
    if any(ord(ch) < 32 or 0x7F <= ord(ch) <= 0x9F for ch in value):
        raise PathError(f"control character in {what}: {_short(value)}")
    p = value.replace("\\", "/")
    if p.startswith("/") or _DRIVE.match(p):
        raise PathError(f"absolute {what} not allowed: {_short(value)}")
    while p.startswith("./"):
        p = p[2:]
    if _DRIVE.match(p):  # a drive path hidden behind "./", for example "./C:/x"
        raise PathError(f"absolute {what} not allowed: {_short(value)}")
    if not p:
        raise PathError(f"empty {what}")
    if p.startswith("/"):
        raise PathError(f"empty segment (double '/') in {what}: {_short(value)}")
    for part in p.split("/"):
        if part == "":
            raise PathError(f"empty segment (double or trailing '/') in {what}: {_short(value)}")
        if part in (".", ".."):
            raise PathError(f"'{part}' segment not allowed in {what}: {_short(value)}")
        if len(part.encode("utf-8")) > MAX_SEGMENT_BYTES:
            raise PathError(f"{what} segment longer than {MAX_SEGMENT_BYTES} bytes: {_short(value)}")
    return p


def normalize(path: object) -> str:
    """Return a repository-relative POSIX path, or raise PathError.

    For values typed by people (configuration): backslashes are treated as path
    separators. Paths reported by Git go through `repo_path` instead.
    """
    return _check(path, "path")


# Longest name and path the tool processes. Longer ones cannot occur on common file
# systems; rejecting them also bounds glob-matching cost.
MAX_SEGMENT_BYTES = 255
MAX_PATH_BYTES = 4096


def repo_path(path: object) -> str:
    """Validate a path exactly as Git reported it, or raise PathError.

    Git always separates folders with '/', so a backslash in a Git path is part of a
    real file name (possible on Linux and macOS). Unlike `normalize`, it is kept as a
    literal character, never rewritten into a separator. No Unicode normalization or
    case-folding is applied: paths compare exactly, as in Git.
    """
    if not isinstance(path, str):
        raise PathError(f"path must be a string, not {type(path).__name__}")
    if any(ord(ch) < 32 or 0x7F <= ord(ch) <= 0x9F for ch in path):
        raise PathError(f"control character in path: {_short(path)}")
    if not path:
        raise PathError("empty path")
    if path.startswith("/"):
        raise PathError(f"absolute path not allowed: {_short(path)}")
    try:
        encoded = path.encode("utf-8")
    except UnicodeEncodeError:
        raise PathError(f"path is not valid Unicode: {_short(path)}") from None
    if len(encoded) > MAX_PATH_BYTES:
        raise PathError(f"path longer than {MAX_PATH_BYTES} bytes")
    for part in path.split("/"):
        if part == "":
            raise PathError(f"empty segment in path: {_short(path)}")
        if part in (".", ".."):
            raise PathError(f"'{part}' segment not allowed in path: {_short(path)}")
        if len(part.encode("utf-8")) > MAX_SEGMENT_BYTES:
            raise PathError(f"path segment longer than {MAX_SEGMENT_BYTES} bytes")
    return path


def normalize_pattern(pattern: object) -> str:
    """Return a normalized glob pattern, or raise PathError.

    `**` is only allowed as a whole segment (`a/**/b`), never inside a name
    (`a**b`), because its meaning there would be ambiguous, and at most
    MAX_DOUBLE_STAR_SEGMENTS times per pattern; and at most MAX_STARS_PER_SEGMENT
    `*` operators in any one segment (see `star_operators`). Both bound matching cost.
    Backslashes are path separators here, not escapes: to match a literal `[`,
    use the character class `[[]`.
    """
    p = _check(pattern, "pattern")
    parts = p.split("/")
    for part in parts:
        if "**" in part and part != "**":
            raise PathError(f"'**' must be a whole segment in pattern: {_short(pattern)}")
    if parts.count("**") > MAX_DOUBLE_STAR_SEGMENTS:
        raise PathError(f"more than {MAX_DOUBLE_STAR_SEGMENTS} '**' segments in pattern: {_short(pattern)}")
    for part in parts:
        if star_operators(part) > MAX_STARS_PER_SEGMENT:
            raise PathError(f"more than {MAX_STARS_PER_SEGMENT} '*' wildcards in one segment "
                            f"({_short(part)}) of pattern: {_short(pattern)}")
    return p


def star_operators(segment: str) -> int:
    """Number of `*` wildcard operators in one pattern segment.

    A whole `**` segment counts as 0 (it is limited separately). A `*` inside a
    character class (`[*]`, `[!*]`, `[]*]`) is a literal character, not an
    operator. Class syntax follows glob/fnmatch: after `[`, an optional `!`, then
    an optional `]` taken literally, then everything up to the next `]`. A `[`
    with no closing `]` is itself a literal, so the characters after it are
    scanned normally.
    """
    if segment == "**":
        return 0
    count, i, n = 0, 0, len(segment)
    while i < n:
        ch = segment[i]
        if ch == "[":
            j = i + 1
            if j < n and segment[j] == "!":
                j += 1
            if j < n and segment[j] == "]":
                j += 1
            while j < n and segment[j] != "]":
                j += 1
            if j < n:          # a closed class: skip it entirely
                i = j + 1
                continue
        elif ch == "*":
            count += 1
        i += 1
    return count


def is_literal(pattern: str) -> bool:
    """True when the pattern contains no wildcard characters."""
    return not (WILDCARD_CHARS & set(pattern))


def matches(path: str, pattern: str) -> bool:
    """True when a normalized path matches a normalized pattern."""
    return PurePosixPath(path).full_match(pattern)


def specificity(pattern: str) -> tuple[int, bool]:
    """Sort key: higher is more specific.

    (number of leading segments without wildcards, whether the pattern is fully
    literal). An exact file path always outranks a glob that matches the same
    path: the glob's first wildcard segment sits at or before the position of a
    path segment, so it has fewer leading literal segments (`a/b/**/c` has 2
    against the 3 of `a/b/c`; a trailing `**` never matches zero segments). The
    fully-literal flag is a further tie-breaker.
    """
    segments = pattern.split("/")
    literal = 0
    for seg in segments:
        if WILDCARD_CHARS & set(seg):
            break
        literal += 1
    return (literal, literal == len(segments))
