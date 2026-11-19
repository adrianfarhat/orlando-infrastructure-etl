"""Safe subset for content-trigger regular expressions, and bounded scanning.

Python's `re` has no timeout, and content triggers are repository-owned, so a
pattern is accepted only if its matching cost can be bounded. This module uses an
ALLOWLIST: a pattern must be built only from the constructs below, otherwise it is
rejected (registry-invalid ERROR).

Why no unbounded quantifiers: measured on Python 3.15.2 with worst-case input
(256 KB of "a", no match), any pattern combining `*` or `+` with further atoms or
choices backtracked roughly quadratically per line, multiplied by what follows, in
ways the syntax could not reliably bound: `\\w*` followed by nine `\\w` took 7.2 s,
`a*a?a?b` 2.2 s. Without unbounded quantifiers and quantified groups, every match
attempt has a bounded length, so cost grows linearly with the text. Write
`[A-Z_]{1,20}` instead of `[A-Z_]+`.

Allowed:
- literal characters, and `\\` followed by a non-alphanumeric character;
- `.`, the class escapes `\\d \\D \\w \\W \\s \\S`, and the assertions `\\b \\B ^ $`;
- character classes `[...]` (no nested `[`, no set operators `-- && ~~ ||`);
- bounded quantifiers `? {m} {m,n} {,n}` (optionally lazy `?`) on a single
  character-level atom, with n <= MAX_BOUND;
- unquantified groups `( )` / `(?: )` and alternation `|`.

Rejected:
- unbounded quantifiers (`*`, `+`, `{m,}`);
- quantified groups, backreferences, lookaround, flags, named groups, other `(?...)`;
- more "choices" (product of bounded-quantifier ranges and alternation branch
  counts) than MAX_BRANCHING;
- newline/carriage-return escapes (triggers are matched within single lines);
- patterns longer than MAX_PATTERN_LENGTH.

Matching: a pattern that is a plain literal (after unescaping) is found with a
substring search over the whole text (linear, no limit). Any other pattern is
searched line by line up to MAX_SCAN_CHARS per file; text past the cap is reported
as "not scanned", never as "no match".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_PATTERN_LENGTH = 200
MAX_BOUND = 20
# "Choices" = product of bounded-quantifier ranges and alternation branch counts.
MAX_BRANCHING = 64
# Per-file cap for non-literal patterns (literals are matched over the whole text).
# Worst accepted pattern measured (64 alternation choices, non-matching "a" text):
# ~0.9 s per 1,000,000 chars, so 512,000 keeps a file under ~0.5 s.
MAX_SCAN_CHARS = 512_000

_CLASS_ESCAPES = set("dDwWsS")
_ASSERT_ESCAPES = set("bB")
_SET_OPERATORS = ("--", "&&", "~~", "||")
_QUANT_BRACE = re.compile(r"\{(\d*)(,?)(\d*)\}")


class UnsafeRegex(ValueError):
    """A content-trigger pattern outside the safe subset."""


@dataclass(frozen=True)
class RegexProfile:
    literal: str | None   # the plain text to search for, if the pattern is a literal
    branching: int        # product of bounded-quantifier ranges and alternation branches


@dataclass(frozen=True)
class ScanResult:
    matched: bool
    complete: bool        # False when text beyond MAX_SCAN_CHARS was not scanned


def check(pattern: str) -> RegexProfile:
    """Return the pattern's profile, or raise UnsafeRegex explaining why it is rejected."""
    if not isinstance(pattern, str) or not pattern:
        raise UnsafeRegex("pattern must be a non-empty string")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise UnsafeRegex(f"pattern longer than {MAX_PATTERN_LENGTH} characters")

    n = len(pattern)
    i = 0
    depth = 0
    alternatives = [1]     # branch count per open group; [0] is the top level
    last = None            # None | "atom" | "assert" | "group" | "quant"
    branching = 1
    literal_chars: list[str] | None = []

    def not_literal() -> None:
        nonlocal literal_chars
        literal_chars = None

    while i < n:
        ch = pattern[i]
        if ch == "\\":
            if i + 1 >= n:
                raise UnsafeRegex("pattern ends with a lone backslash")
            e = pattern[i + 1]
            if e.isdigit():
                raise UnsafeRegex(f"backreferences and octal escapes are not allowed: \\{e}")
            if e in "nr\n\r":
                raise UnsafeRegex("newline escapes are not allowed: triggers match within single lines")
            if e in _CLASS_ESCAPES:
                last = "atom"
                not_literal()
            elif e in _ASSERT_ESCAPES:
                last = "assert"
                not_literal()
            elif not e.isalnum():
                last = "atom"
                if literal_chars is not None:
                    literal_chars.append(e)
            else:
                raise UnsafeRegex(f"escape \\{e} is not allowed")
            i += 2
        elif ch == "[":
            j = i + 1
            if j < n and pattern[j] == "^":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                if pattern[j] == "\\":
                    if j + 1 < n and (pattern[j + 1].isdigit() or pattern[j + 1] in "nr\n\r"):
                        raise UnsafeRegex(f"escape \\{pattern[j + 1]} is not allowed in a class")
                    j += 2
                    continue
                if pattern[j] == "[":
                    raise UnsafeRegex("'[' inside a character class is not allowed (write \\[)")
                if pattern[j] in "\n\r":
                    raise UnsafeRegex("newlines are not allowed: triggers match within single lines")
                j += 1
            if j >= n:
                raise UnsafeRegex("unterminated character class")
            body = pattern[i + 1:j]
            if any(op in body for op in _SET_OPERATORS):
                raise UnsafeRegex("set operators (-- && ~~ ||) are not allowed in a character class")
            last = "atom"
            not_literal()
            i = j + 1
        elif ch == "(":
            if pattern.startswith("(?:", i):
                i += 3
            elif pattern.startswith("(?", i):
                raise UnsafeRegex("only plain ( ) and (?: ) groups are allowed: no lookaround, flags, "
                                  "named groups or conditionals")
            else:
                i += 1
            depth += 1
            alternatives.append(1)
            last = None
            not_literal()
        elif ch == ")":
            depth -= 1
            if depth < 0:
                raise UnsafeRegex("unbalanced ')'")
            branching *= alternatives.pop()
            last = "group"
            i += 1
        elif ch == "|":
            alternatives[-1] += 1
            last = None
            not_literal()
            i += 1
        elif ch in "^$":
            last = "assert"
            not_literal()
            i += 1
        elif ch == ".":                       # any character: never part of a literal
            last = "atom"
            not_literal()
            i += 1
        elif ch in "*+?{":
            if ch == "{":
                m = _QUANT_BRACE.match(pattern, i)
                if not m or (m.group(1) == "" and m.group(3) == ""):
                    raise UnsafeRegex("'{' must start a quantifier like {2} or {1,5} (write \\{ for a brace)")
                lo = int(m.group(1) or 0)
                comma = m.group(2) == ","
                hi = int(m.group(3)) if m.group(3) else (None if comma else lo)
                end = m.end()
            else:
                lo, hi = {"*": (0, None), "+": (1, None), "?": (0, 1)}[ch]
                end = i + 1
            if last is None:
                raise UnsafeRegex(f"quantifier '{pattern[i:end]}' has nothing to repeat")
            if last == "group":
                raise UnsafeRegex("quantified groups are not allowed (the main cause of catastrophic "
                                  "backtracking)")
            if last == "quant":
                raise UnsafeRegex("stacked or possessive quantifiers are not allowed")
            if last == "assert":
                raise UnsafeRegex("quantified assertions are not allowed")
            if hi is None:
                raise UnsafeRegex(f"unbounded quantifier '{pattern[i:end]}' is not allowed; "
                                  f"use a bounded form such as {{1,{MAX_BOUND}}}")
            if hi < lo:
                raise UnsafeRegex(f"quantifier '{pattern[i:end]}' has max below min")
            if hi > MAX_BOUND:
                raise UnsafeRegex(f"quantifier bound {hi} is above {MAX_BOUND}")
            branching *= (hi - lo + 1)
            i = end
            if i < n and pattern[i] == "?":   # lazy form
                i += 1
            last = "quant"
            not_literal()
        else:
            if ch in "\n\r":
                raise UnsafeRegex("newlines are not allowed: triggers match within single lines")
            last = "atom"
            if literal_chars is not None:
                literal_chars.append(ch)
            i += 1

    if depth != 0:
        raise UnsafeRegex("unbalanced '('")
    branching *= alternatives[0]
    if branching > MAX_BRANCHING:
        raise UnsafeRegex(f"{branching} choices (alternatives and bounded quantifiers) (limit {MAX_BRANCHING})")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise UnsafeRegex(f"invalid regular expression: {exc}") from None
    literal = "".join(literal_chars) if literal_chars is not None else None
    return RegexProfile(literal=literal, branching=branching)


def scan(regex: re.Pattern, profile: RegexProfile, text: str) -> ScanResult:
    """Search text for a checked pattern.

    A literal is found with a substring search over the whole text. Other patterns
    are searched line by line (triggers match within single lines) up to
    MAX_SCAN_CHARS; if the text is longer and nothing matched in the scanned part,
    the result is complete=False ("not scanned"), never a plain "no match".
    """
    if profile.literal is not None:
        return ScanResult(matched=profile.literal in text, complete=True)
    scanned = 0
    for line in text.splitlines():
        if scanned + len(line) > MAX_SCAN_CHARS:
            return ScanResult(matched=False, complete=False)
        scanned += len(line)
        if regex.search(line):
            return ScanResult(matched=True, complete=True)
    return ScanResult(matched=False, complete=True)
