"""Entry point: `python -m tools.design ...` (run from the repository root)."""

import sys

# Names can be non-ASCII and a Windows console may not be UTF-8.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace", newline="\n")

try:
    from .cli import main
except ImportError as exc:
    print(f"design: error: cannot start: {exc}. Install the pinned dependencies: "
          "pip install -r requirements.txt", file=sys.stderr)
    sys.exit(2)

sys.exit(main())
