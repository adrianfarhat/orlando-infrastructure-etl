"""Feature Design Workspace tool (T-94): create feature specifications and keep the index.

Usage (from the repository root):
    python -m tools.design new feature [--name NAME] [--parent PARENT] [--convert-parent]
    python -m tools.design index [--check]
    python -m tools.design check

The tool only reads and writes files under designs/. It runs no other program (in
particular never git): new files are ordinary uncommitted working-tree changes.
"""

__version__ = "0.1.0"
