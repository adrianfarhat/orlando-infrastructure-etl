"""Set up Feature Designer's isolated development toolchain (T-97, decision Q2/P2-C).

    .venv\\Scripts\\python tools\\feature-designer\\toolchain\\bootstrap.py [--vscode-test]

- Downloads the pinned portable Node.js (26.13.0, Windows x64) into
  tools/feature-designer/.toolchain/ and checks it against the SHA-256 published by
  nodejs.org (pinned below). Nothing is installed globally; PATH is not changed.
- Installs the exact dependencies from package-lock.json with `npm ci --ignore-scripts`
  (no install scripts run), with npm's cache inside .toolchain/.
- With --vscode-test, also downloads the pinned VS Code 1.146.0 test build into
  tools/feature-designer/.vscode-test/ (only needed for the automated GUI tests or
  `dev.py --isolated`).
All three folders are ignored by Git. Run it again at any time; finished steps are skipped.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]                 # tools/feature-designer
TOOLCHAIN = HERE / ".toolchain"
NODE_VERSION = "26.13.0"
NODE_FILE = f"node-v{NODE_VERSION}-win-x64.zip"
NODE_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/{NODE_FILE}"
NODE_SHA256 = "dcc60d59a0746999f99064a01c020445d54d84228c691cdbf25b49ac3b59150a"   # nodejs.org SHASUMS256.txt
VSCODE_VERSION = "1.146.0"


def node_dir() -> Path:
    return TOOLCHAIN / f"node-v{NODE_VERSION}-win-x64"


def node_exe() -> Path:
    return node_dir() / "node.exe"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_node() -> Path:
    if node_exe().is_file():
        print(f"Node.js {NODE_VERSION}: already set up ({node_exe()})")
        return node_exe()
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise SystemExit("bootstrap: only Windows x64 is pinned so far; add the platform's archive and SHA-256 first")
    downloads = TOOLCHAIN / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / NODE_FILE
    if not archive.is_file() or _sha256(archive) != NODE_SHA256:
        print(f"downloading {NODE_URL}")
        tmp = archive.with_suffix(".part")
        with urllib.request.urlopen(NODE_URL, timeout=120) as response, open(tmp, "wb") as out:
            shutil.copyfileobj(response, out)
        tmp.replace(archive)
    digest = _sha256(archive)
    if digest != NODE_SHA256:
        archive.unlink()
        raise SystemExit(f"bootstrap: {NODE_FILE} has SHA-256 {digest}, expected {NODE_SHA256}; deleted, nothing installed")
    print(f"verified {NODE_FILE} (SHA-256 {NODE_SHA256[:16]}…)")
    root = TOOLCHAIN.resolve()
    with zipfile.ZipFile(archive) as z:
        for member in z.namelist():                         # never write outside .toolchain/
            target = (TOOLCHAIN / member).resolve()
            if root not in target.parents and target != root:
                raise SystemExit(f"bootstrap: unsafe path in the archive: {member}")
        z.extractall(TOOLCHAIN)
    if not node_exe().is_file():
        raise SystemExit("bootstrap: node.exe not found after extracting the archive")
    return node_exe()


def _env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.lower().startswith("npm_config_")}
    env["npm_config_cache"] = str(TOOLCHAIN / "npm-cache")
    env["PATH"] = str(node_dir()) + os.pathsep + env.get("PATH", "")
    return env


def npm_ci(node: Path) -> None:
    npm = node_dir() / "node_modules" / "npm" / "bin" / "npm-cli.js"
    print("installing the pinned dependencies (npm ci --ignore-scripts)")
    subprocess.run([str(node), str(npm), "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=HERE, env=_env(),
                   check=True)


def vscode_test(node: Path) -> Path:
    script = ("require('@vscode/test-electron').downloadAndUnzipVSCode({version: process.argv[1], cachePath: process.argv[2]})"
              ".then(p => console.log(p)).catch(e => { console.error(e); process.exit(1); })")
    out = subprocess.run([str(node), "-e", script, VSCODE_VERSION, str(HERE / ".vscode-test")], cwd=HERE, env=_env(),
                         check=True, capture_output=True, text=True)
    path = Path(out.stdout.strip().splitlines()[-1])
    print(f"VS Code {VSCODE_VERSION} test build: {path}")
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--vscode-test", action="store_true", help="also download the VS Code test build")
    args = parser.parse_args(argv)
    node = ensure_node()
    npm_ci(node)
    if args.vscode_test:
        vscode_test(node)
    print("done: nothing was installed outside tools/feature-designer/ (.toolchain, node_modules, .vscode-test)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
