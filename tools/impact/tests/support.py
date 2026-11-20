"""Throwaway Git repositories for tests. Everything lives in a temporary folder that is
deleted afterwards; the project repository is never touched."""

import json
import subprocess
import tempfile
from pathlib import Path

GIT = ["git", "-c", "init.defaultBranch=main", "-c", "core.autocrlf=false",
       "-c", "user.name=impact-tests", "-c", "user.email=impact-tests@example.invalid",
       "-c", "commit.gpgsign=false"]

IMPACT = {"version": 1, "registry": "registry/components.yml"}
REGISTRY = {
    "version": 1,
    "components": [{"id": "app", "paths": ["app/**"], "docs": ["docs/app.md"]}],
    "content_triggers": [{"id": "secret", "paths": ["**/*.py"], "match": "SECRET", "docs": ["docs/app.md"]}],
}


class TempRepo:
    def __init__(self, init: bool = True):
        self._tmp = tempfile.TemporaryDirectory(prefix="impact-test-")
        self.root = Path(self._tmp.name) / "repo"
        self.root.mkdir()
        if init:
            self.git("init", "-q")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()

    def git(self, *args: str) -> str:
        r = subprocess.run(GIT + ["-C", str(self.root), *args], capture_output=True, timeout=60)
        if r.returncode:
            raise AssertionError(f"git {' '.join(args)} failed: {r.stderr.decode('utf-8', 'replace')}")
        return r.stdout.decode("utf-8", "replace")

    def write(self, rel: str, content) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        return p

    def write_json(self, rel: str, data) -> Path:
        return self.write(rel, json.dumps(data, indent=2) + "\n")   # JSON is valid YAML

    def add_all(self) -> None:
        self.git("add", "-A")

    def commit(self, message: str = "test") -> None:
        self.git("commit", "-q", "-m", message)

    def status(self) -> str:
        return self.git("status", "--porcelain", "--untracked-files=all", "--ignored")


def valid_repo(commit: bool = True, registry=None, impact=None) -> TempRepo:
    """A small repository that validates cleanly."""
    repo = TempRepo()
    repo.write_json("impact.yml", impact or IMPACT)
    repo.write_json("registry/components.yml", registry or REGISTRY)
    repo.write("docs/app.md", "# App\n")
    repo.write("app/main.py", "print('hello')\n")
    repo.write(".gitignore", ".local/\n")
    repo.add_all()
    if commit:
        repo.commit()
    return repo
