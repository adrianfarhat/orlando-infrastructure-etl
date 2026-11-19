"""Entry point: `python -m tools.impact ...` (run from the repository root).

Exit code 1 means "validation found ERRORs", so nothing else may produce it: an
unsupported Python, a missing dependency or any other start-up failure exits 2 with
a clear message.
"""

import sys

# Reports can contain non-ASCII file names and a Windows console may not be UTF-8.
# newline="\n": stdout must be byte-identical to the --out files on every platform.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace", newline="\n")


def _safe(text: str, limit: int = 2000) -> str:
    """Escape non-printable characters and bound the length. Self-contained on purpose:
    it runs when the package itself may have failed to import."""
    shown = "".join(ch if ch.isprintable() else ch.encode("unicode_escape").decode("ascii") for ch in text)
    return shown if len(shown) <= limit else f"{shown[:limit]}... ({len(shown)} characters)"


if sys.version_info < (3, 13):
    print("impact: error: Python 3.13 or later is required (found "
          f"{sys.version_info.major}.{sys.version_info.minor})", file=sys.stderr)
    sys.exit(2)

try:
    from .cli import main
except ImportError as exc:
    print(f"impact: error: cannot start: {_safe(str(exc))}. Install the pinned dependencies: "
          "pip install -r requirements.txt", file=sys.stderr)
    sys.exit(2)
except Exception as exc:                      # any other start-up failure is internal: never 1
    print(f"impact: internal error while starting: {type(exc).__name__}: {_safe(str(exc))}", file=sys.stderr)
    sys.exit(2)

sys.exit(main())
