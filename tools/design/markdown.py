"""Read the structure of a Markdown document: its headings (with the anchors GitHub gives
them) and its Mermaid diagrams.

Standard library only and independent of the rest of the design tool, so another checker
(for example the planned T-81 link checker) can reuse it instead of rewriting it.

What is recognised (a deliberate subset of CommonMark/GitHub Flavored Markdown):
- ATX headings: up to three spaces, 1 to 6 '#', then a space or the end of the line; an
  optional closing run of '#' is dropped. Setext headings: a paragraph line underlined
  with '=' (level 1) or '-' (level 2).
- Fenced code blocks: ``` or ~~~, three or more, closed by the same character at least as
  long. Nothing inside a fence is a heading. Fences are recognised at any indentation (as
  the Phase 1 tool does), so a fence inside a list item still counts.
- A Mermaid diagram is a fenced block whose info string's first word is "mermaid" (any
  case). Its type is the value of the first "%% diagram-type: <value>" line inside it
  (docs/architecture/conventions.md section 2), or None when it has none.

Anchors follow GitHub's algorithm (github-slugger): take the heading's rendered text,
lower-case it, remove everything except letters, digits, combining marks, spaces, '-' and
'_', turn each space into '-', and add -1, -2, ... to repeated anchors in the same document.
Not handled: headings written as HTML (<h2>), headings inside block quotes or lists, and
images inside headings (their alt text is not counted).
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass

_ATX = re.compile(r" {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*\Z")
_CLOSING = re.compile(r"(?:\A|[ \t]+)#+\Z")
_FENCE = re.compile(r"[ \t]*(`{3,}|~{3,})(.*)\Z")
_SETEXT = re.compile(r" {0,3}(=+|-+)[ \t]*\Z")
_INTERRUPTS = re.compile(r" {0,3}(?:[-+*][ \t]|\d{1,9}[.)][ \t]|>|<)")   # these end a paragraph
_NOT_PARAGRAPH = re.compile(r" {0,3}(?:[-+*][ \t]|\d{1,9}[.)][ \t]|>|\||<|#|    |\t)")
_DIAGRAM_TYPE = re.compile(r"\s*%%\s*diagram-type:\s*(\S+)")
_CODE_SPAN = re.compile(r"(`+)(.+?)(?<!`)\1(?!`)", re.S)
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\](?:\([^)]*\)|\[[^\]]*\])")
_AUTOLINK = re.compile(r"<((?:https?|mailto):[^>\s]*)>")
_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>")
_ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")
# a matched pair only: opens not after a letter or digit, closes not before one (CommonMark)
_UNDERSCORE_EMPHASIS = re.compile(r"(?<!\w)(_+)(?=\S)(.+?)(?<=\S)\1(?!\w)")


@dataclass(frozen=True)
class Heading:
    level: int
    source: str        # the heading's Markdown, without the '#' markers
    text: str          # the rendered text (markup removed)
    anchor: str        # unique within the document; '' for an empty heading
    line: int          # 1-based


@dataclass(frozen=True)
class Diagram:
    line: int                # 1-based line of the opening fence
    heading: int | None      # index into Document.headings of the heading it sits under
    diagram_type: str | None


@dataclass(frozen=True)
class Document:
    headings: tuple[Heading, ...]
    diagrams: tuple[Diagram, ...]


class Slugger:
    """GitHub's anchors for one document: repeated anchors get -1, -2, ..."""

    def __init__(self):
        self._seen: dict[str, int] = {}

    def slug(self, text: str) -> str:
        original = base_anchor(text)
        result = original
        while result in self._seen:
            self._seen[original] += 1
            result = f"{original}-{self._seen[original]}"
        self._seen[result] = 0
        return result


def base_anchor(text: str) -> str:
    """The anchor for rendered heading text, before repeats are numbered."""
    out = []
    for ch in text.lower():
        if ch == " ":
            out.append("-")
        elif ch in "-_" or unicodedata.category(ch)[0] in "LNM":
            out.append(ch)
    return "".join(out)


def heading_text(source: str) -> str:
    """The text GitHub renders for a heading's Markdown (the input to the anchor)."""
    parts, pos = [], 0
    for m in _CODE_SPAN.finditer(source):
        parts.append(_inline_text(source[pos:m.start()]))
        content = m.group(2).replace("\n", " ")
        if len(content) > 1 and content.startswith(" ") and content.endswith(" ") and content.strip():
            content = content[1:-1]
        parts.append(content)
        pos = m.end()
    parts.append(_inline_text(source[pos:]))
    return "".join(parts)          # the source is already trimmed; spaces left by removed markup stay


def _inline_text(text: str) -> str:
    text = _IMAGE.sub("", text)
    text = _LINK.sub(lambda m: m.group(1), text)
    text = _AUTOLINK.sub(lambda m: m.group(1), text)
    text = _TAG.sub("", text)
    escaped: list[str] = []

    def hold(m):                                  # keep \_ and \* literal through the emphasis step
        escaped.append(m.group(1))
        return f"\x00{len(escaped) - 1}\x00"
    text = _ESCAPE.sub(hold, text)
    text = text.replace("*", "")
    text = _UNDERSCORE_EMPHASIS.sub(lambda m: m.group(2), text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: escaped[int(m.group(1))], text)
    return html.unescape(text)


def parse(text: str) -> Document:
    """Headings and Mermaid diagrams of a Markdown text (LF or CRLF)."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[0].startswith("\ufeff"):
        lines[0] = lines[0][1:]
    slugger = Slugger()
    headings: list[Heading] = []
    diagrams: list[Diagram] = []
    fence: tuple[str, int] | None = None          # (character, length) of the open fence
    mermaid: dict | None = None                   # the open Mermaid block
    paragraph: list[str] = []                     # the open paragraph's lines (a setext heading's text)

    def add(level: int, source: str, number: int):
        rendered = heading_text(source)
        anchor = slugger.slug(rendered) if rendered else ""
        headings.append(Heading(level, source, rendered, anchor, number))

    for number, line in enumerate(lines, start=1):
        if fence is not None:
            m = _FENCE.match(line)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1] and not m.group(2).strip():
                if mermaid is not None:
                    diagrams.append(Diagram(mermaid["line"], mermaid["heading"], mermaid["type"]))
                fence, mermaid = None, None
            elif mermaid is not None and mermaid["type"] is None:
                t = _DIAGRAM_TYPE.match(line)
                if t:
                    mermaid["type"] = t.group(1)
            continue
        m = _FENCE.match(line)
        if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            fence = (m.group(1)[0], len(m.group(1)))
            info = m.group(2).strip().split()
            if info and info[0].lower() == "mermaid":
                mermaid = {"line": number, "heading": len(headings) - 1 if headings else None, "type": None}
            paragraph = []
            continue
        atx = _ATX.match(line)
        if atx:
            add(len(atx.group(1)), _CLOSING.sub("", atx.group(2) or "").strip(), number)
            paragraph = []
            continue
        setext = _SETEXT.match(line)
        if setext and paragraph:
            # every line of the paragraph above becomes the heading (CommonMark)
            add(1 if setext.group(1)[0] == "=" else 2, " ".join(p.strip() for p in paragraph),
                number - len(paragraph))
            paragraph = []
            continue
        if not line.strip():
            paragraph = []
        elif paragraph and not _INTERRUPTS.match(line):
            paragraph.append(line)                # a continuation line
        elif not (_NOT_PARAGRAPH.match(line) or setext):
            paragraph = [line]                    # a new paragraph
        else:
            paragraph = []
    if mermaid is not None:                       # an unclosed fence runs to the end of the document
        diagrams.append(Diagram(mermaid["line"], mermaid["heading"], mermaid["type"]))
    return Document(tuple(headings), tuple(diagrams))
