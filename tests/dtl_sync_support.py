from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def load_sync():
    name = "dtl_sync_tool"
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools/dtl_sync.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def git(directory: Path, *args: str, input_text: str | None = None) -> str:
    return subprocess.run(
        ["git", "-C", str(directory), *args], input=input_text,
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def repository(directory: Path, branch: str) -> None:
    directory.mkdir()
    git(directory, "init", "-b", branch)
    git(directory, "config", "user.name", "Fixture")
    git(directory, "config", "user.email", "fixture@example.test")


class World:
    def __init__(self, path: Path):
        self.path = path
        self.upstream = path / "upstream"
        repository(self.upstream, "master")
        # Detection must never execute this file.
        (self.upstream / "engine.py").write_text("raise RuntimeError('do not import upstream')\n")
        git(self.upstream, "add", ".")
        git(self.upstream, "commit", "-m", "First")
        self.first = git(self.upstream, "rev-parse", "HEAD")
        (self.upstream / "engine.py").write_text("raise RuntimeError('still not executable by detect')\n")
        git(self.upstream, "commit", "-am", "Second")
        self.second = git(self.upstream, "rev-parse", "HEAD")
        self.upstream_remote = path / "upstream.git"
        subprocess.run(["git", "clone", "--bare", str(self.upstream), str(self.upstream_remote)], check=True, capture_output=True)
        self.parent = path / "parent"
        repository(self.parent, "main")
        prompt = self.parent / "tools/dtl_sync/PROMPT.md"
        prompt.parent.mkdir(parents=True)
        prompt.write_text("Trusted prompt\n")
        (self.parent / ".gitmodules").write_text(
            f'[submodule "src/sugarscape"]\n\tpath = src/sugarscape\n\turl = {self.upstream_remote}\n'
        )
        git(self.parent, "add", ".")
        git(self.parent, "update-index", "--add", "--cacheinfo", f"160000,{self.first},src/sugarscape")
        git(self.parent, "commit", "-m", "Initial pin")
        self.origin = path / "origin.git"
        subprocess.run(["git", "clone", "--bare", str(self.parent), str(self.origin)], check=True, capture_output=True)
        git(self.parent, "remote", "add", "origin", str(self.origin))
        self.main = git(self.parent, "rev-parse", "HEAD")
        self.prompt = git(self.parent, "rev-parse", "HEAD:tools/dtl_sync/PROMPT.md")
        self.pages = path / "pages.json"
        self.pages.write_text("[[]]")
        self.calls = path / "gh-calls.jsonl"
        binary = path / "bin"
        binary.mkdir()
        gh = binary / "gh"
        gh.write_text(f'''#!{sys.executable}
import json, os, sys
args = sys.argv[1:]
assert args == ["api", "--method", "GET", "repos/owner/game/pulls?state=open&base=main&per_page=100", "--paginate", "--slurp"], args
with open(os.environ["FAKE_GH_CALLS"], "a") as f:
    f.write(json.dumps(args) + "\\n")
print(open(os.environ["FAKE_GH_PAGES"]).read())
''')
        gh.chmod(0o755)
        self.env = {**os.environ, "PATH": f"{binary}{os.pathsep}{os.environ['PATH']}",
                    "FAKE_GH_PAGES": str(self.pages), "FAKE_GH_CALLS": str(self.calls)}
        self.counter = 0

    def detect(self, sync, **options):
        self.counter += 1
        return sync.detect(
            checkout=self.parent, scratch=self.path / f"scratch-{self.counter}",
            repository="owner/game", app_login="dtl-sync[bot]", run_id="123", run_attempt="1",
            runner=sync.CommandRunner(env=self.env), upstream_url=str(self.upstream_remote), **options,
        )

    def pr(self, *, head: str | None = None, body: str = "") -> dict:
        return {"number": 7, "state": "open", "user": {"login": "dtl-sync[bot]"},
                "base": {"ref": "main", "repo": {"full_name": "owner/game"}},
                "head": {"ref": "dtl-sync/candidate", "sha": head or self.main,
                         "repo": {"full_name": "owner/game"}},
                "labels": [{"name": "dtl-sync"}], "body": body}

    def set_prs(self, *pages: list[dict]) -> None:
        self.pages.write_text(json.dumps(pages))
