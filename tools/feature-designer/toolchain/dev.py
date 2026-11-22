"""Open VS Code with Feature Designer loaded in development mode (T-97, decision P2-B).

    .venv\\Scripts\\python tools\\feature-designer\\toolchain\\dev.py [FILE] [--isolated]

Opens a new VS Code window on this repository with the extension loaded from
tools/feature-designer/ (`--extensionDevelopmentPath`): nothing is installed, and your
installed extensions (Mark Sharp included) and settings are untouched. Close the window to
unload it. Then open a feature with right-click → "Open With…" → "Feature Designer".

--isolated uses the pinned VS Code test build with its own empty profile under
tools/feature-designer/.toolchain/profile (run bootstrap.py --vscode-test first).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]                  # tools/feature-designer
REPO = HERE.parents[1]


def _code_exe() -> str:
    """Your installed VS Code (Code.exe, next to bin/code.cmd). It is started directly with an
    argument list: no shell, so no path can be read as a command (QA D1)."""
    candidates = []
    found = shutil.which("code") or shutil.which("code.cmd")
    if found:
        candidates.append(Path(found).resolve().parent.parent / "Code.exe")
    candidates.append(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe")
    candidates.append(Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Microsoft VS Code" / "Code.exe")
    for exe in candidates:
        if exe.is_file():
            return str(exe)
    raise SystemExit("dev: VS Code (Code.exe) was not found; use --isolated with the test build instead")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Open VS Code with Feature Designer in development mode.")
    parser.add_argument("file", nargs="?", help="a feature file to open, e.g. designs/features/test1.md")
    parser.add_argument("--isolated", action="store_true", help="use the pinned VS Code test build and an empty profile")
    args = parser.parse_args(argv)
    if not (HERE / "node_modules" / "mermaid").is_dir():
        raise SystemExit("dev: run `.venv\\Scripts\\python tools\\feature-designer\\toolchain\\bootstrap.py` first")
    targets = [str(REPO)] + ([str((REPO / args.file).resolve())] if args.file else [])
    common = [f"--extensionDevelopmentPath={HERE}", *targets]
    if args.isolated:
        from bootstrap import VSCODE_VERSION                 # noqa: E402 (same folder)
        exe = HERE / ".vscode-test" / f"vscode-win32-x64-archive-{VSCODE_VERSION}" / "Code.exe"
        if not exe.is_file():
            raise SystemExit("dev: run `bootstrap.py --vscode-test` first")
        profile = HERE / ".toolchain" / "profile"
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("VSCODE_", "ELECTRON_", "CHROME_"))}
        subprocess.Popen([str(exe), f"--user-data-dir={profile / 'user'}", f"--extensions-dir={profile / 'extensions'}",
                          "--new-window", *common], env=env, cwd=REPO)
    else:
        env = {k: v for k, v in os.environ.items() if k.upper() != "ELECTRON_RUN_AS_NODE"}
        subprocess.Popen([_code_exe(), "--new-window", *common], cwd=REPO, env=env)
    print("opened VS Code with Feature Designer loaded from tools/feature-designer (development mode, nothing installed).")
    print("Open a feature: right-click it → Open With… → Feature Designer.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
