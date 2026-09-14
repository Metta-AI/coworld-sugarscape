"""Detect, prepare, verify, and publish validated DTL candidate trees."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
import json
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
import ast
import html
import math
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener


UPSTREAM_URL = "https://github.com/nkremerh/sugarscape"
GITLINK_PATH = "src/sugarscape"
PROMPT_PATH = "tools/dtl_sync/PROMPT.md"
MAX_REPORT_BYTES = 64 * 1024
MAX_PR_BODY_BYTES = 48 * 1024
MAX_PATCH_BYTES = 2 * 1024 * 1024
MAX_LOG_BYTES = 1024 * 1024
ALLOWED_DIRECTORIES = ("src/coworld/", "tests/", "tools/", "docs/")
ALLOWED_FILES = frozenset({"README.md", "AGENTS.md"})
PROTECTED_FILES = frozenset({"tests/test_dtl.py", "tests/conftest.py"})
PROTECTED_PREFIXES = ("src/sugarscape/", "tools/dtl_sync", ".github/")
STATE_START = "<!-- dtl-sync-state\n"
STATE_END = "\n-->"
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+")
MODES = {"new-pr", "update-pr", "noop", "retry-alerts"}


class SyncError(Exception):
    """A failed command or invalid external input that requires operator attention."""


class CommandRunner:
    def __init__(self, env: dict[str, str] | None = None):
        self.env = env

    def run(
        self, args: list[str], *, cwd: Path | None = None,
        input_text: str | None = None, timeout: float = 60, check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                args, cwd=cwd, env={**(self.env if self.env is not None else os.environ), **(env or {})},
                input=input_text, timeout=timeout,
                capture_output=True, text=True, check=False,
            )
        except subprocess.TimeoutExpired:
            raise SyncError(f"{Path(args[0]).name} timed out") from None
        except OSError:
            raise SyncError(f"could not execute {Path(args[0]).name}; check tool installation") from None
        if check and result.returncode:
            # Arguments, stdin and stderr may contain credentials or private API data.
            raise SyncError(f"{Path(args[0]).name} exited with status {result.returncode}")
        return result


    def run_bounded(self, args: list[str], *, timeout: float = 900) -> subprocess.CompletedProcess[str]:
        """Bound child output while it runs, including output from hostile test code."""
        with tempfile.TemporaryFile() as output:
            try:
                process = subprocess.Popen(args, stdout=output, stderr=subprocess.STDOUT,
                                           env=self.env)
            except OSError:
                raise SyncError("could not execute Docker; check verifier setup") from None
            deadline = time.monotonic() + timeout
            try:
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        raise SyncError("measurement timed out")
                    if os.fstat(output.fileno()).st_size > MAX_LOG_BYTES:
                        raise SyncError("measurement output exceeds size limit")
                    time.sleep(0.05)
                output.seek(0)
                data = output.read(MAX_LOG_BYTES + 1)
                if len(data) > MAX_LOG_BYTES:
                    raise SyncError("measurement output exceeds size limit")
                return subprocess.CompletedProcess(args, process.returncode, data.decode("utf-8", errors="replace"), "")
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()


@dataclass(frozen=True)
class Meta:
    schema_version: int
    repository: str
    run_id: str
    run_attempt: str
    main_sha: str
    main_pin: str
    target_sha: str
    prompt_version: str
    pr_number: int | None
    pr_head_sha: str | None
    branch: str
    mode: str
    compare_url: str
    force: bool
    replay: bool


@dataclass(frozen=True)
class PublicationIdentity:
    main_sha: str
    target_sha: str
    published_head_sha: str
    prompt_version: str


@dataclass(frozen=True)
class Delivery:
    status: str
    remote_id: str | None
    attempts: int
    last_error: str | None


@dataclass(frozen=True)
class PublicationState:
    """Bounded, bot-owned publication and per-channel delivery state."""

    schema_version: int
    last_publication: PublicationIdentity | None
    deliveries: dict[str, dict[str, Delivery]]
    open_questions: list[dict[str, str]]
    outcome: str
    classification: str | None
    cause: str | None
    recent_runs: list[dict]
    previous_report_artifact: str | None
    telemetry: dict
    resolved_questions: list[dict]
    accepted_resumes: list[dict]


@dataclass(frozen=True)
class Candidate:
    schema_version: int
    main_sha: str
    target_sha: str
    patch_sha256: str
    candidate_tree: str
    files_changed: list[str]
    protected_edits: list[str]
    dropped_edits: list[str]


def _object(value: object, keys: set[str], context: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise SyncError(f"invalid {context} fields")
    return value


def _sha(value: object) -> str:
    if not isinstance(value, str) or not SHA_PATTERN.fullmatch(value):
        raise SyncError("invalid commit/blob identity")
    return value


def _repository(value: object) -> str:
    if not isinstance(value, str) or not REPOSITORY_PATTERN.fullmatch(value) or value.split("/")[1] in {".", ".."}:
        raise SyncError("invalid repository; expected owner/name")
    return value


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
        raise SyncError("run id and attempt must be positive decimal strings")
    return value


def _branch(value: object) -> str:
    if (not isinstance(value, str) or not re.fullmatch(r"dtl-sync/[A-Za-z0-9][A-Za-z0-9._/-]*", value)
            or ".." in value or "//" in value
            or any(part.startswith(".") or part.endswith((".", ".lock")) for part in value.split("/"))
            or value.endswith("/")):
        raise SyncError("invalid sync branch")
    return value


def _json(text: str, limit: int, context: str) -> object:
    if len(text.encode("utf-8")) > limit:
        raise SyncError(f"{context} exceeds size limit")
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise SyncError(f"duplicate field in {context}")
            result[key] = value
        return result
    try:
        return json.loads(text, object_pairs_hook=unique_pairs)
    except (ValueError, RecursionError):
        raise SyncError(f"invalid {context} JSON") from None


def validate_meta(value: object) -> Meta:
    data = _object(value, set(Meta.__dataclass_fields__), "meta")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise SyncError("unsupported meta version")
    _repository(data["repository"])
    for field in ("run_id", "run_attempt"):
        _identifier(data[field])
    for field in ("main_sha", "main_pin", "target_sha", "prompt_version"):
        _sha(data[field])
    for field in ("force", "replay"):
        if type(data[field]) is not bool:
            raise SyncError(f"invalid {field}")
    _branch(data["branch"])
    if not isinstance(data["mode"], str) or data["mode"] not in MODES:
        raise SyncError("invalid detection mode")
    number = data["pr_number"]
    if number is not None:
        if type(number) is not int or number <= 0:
            raise SyncError("invalid PR number")
        _sha(data["pr_head_sha"])
    elif data["pr_head_sha"] is not None:
        raise SyncError("PR identity is incomplete")
    if data["mode"] in {"update-pr", "retry-alerts"} and number is None:
        raise SyncError("detection mode requires a PR")
    if data["mode"] == "new-pr" and number is not None:
        raise SyncError("new-pr mode cannot reference an existing PR")
    if data["compare_url"] != f"{UPSTREAM_URL}/compare/{data['main_pin']}...{data['target_sha']}":
        raise SyncError("invalid upstream compare URL")
    return Meta(**data)


def write_meta(path: Path, meta: Meta) -> None:
    validate_meta(asdict(meta))
    path.write_text(json.dumps(asdict(meta), indent=2) + "\n", encoding="utf-8")


def read_meta(path: Path) -> Meta:
    with path.open(encoding="utf-8") as file:
        text = file.read(MAX_REPORT_BYTES + 1)
    return validate_meta(_json(text, MAX_REPORT_BYTES, "meta"))


def read_state(body: str) -> PublicationState:
    if len(body.encode("utf-8")) > MAX_PR_BODY_BYTES or body.count(STATE_START) != 1:
        raise SyncError("missing, repeated, or oversized sync state")
    text, separator, _ = body.split(STATE_START, 1)[1].partition(STATE_END)
    if not separator:
        raise SyncError("unterminated sync state")
    data = _object(_json(text, MAX_PR_BODY_BYTES, "state"), set(PublicationState.__dataclass_fields__), "state")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise SyncError("unsupported state version")
    identity = data["last_publication"]
    if identity is not None:
        identity = _object(identity, set(PublicationIdentity.__dataclass_fields__), "state identity")
        identity = PublicationIdentity(**{key: _sha(value) for key, value in identity.items()})
    deliveries = data["deliveries"]
    if not isinstance(deliveries, dict):
        raise SyncError("invalid state deliveries")
    parsed = {}
    for target, channels in deliveries.items():
        _sha(target)
        if not isinstance(channels, dict) or not set(channels) <= {"assignment", "discord", "asana"}:
            raise SyncError("invalid state channels")
        parsed[target] = {}
        for channel, receipt in channels.items():
            receipt = _object(receipt, set(Delivery.__dataclass_fields__), "state receipt")
            if receipt["status"] not in ("pending", "failed", "delivered"):
                raise SyncError("invalid state delivery status")
            if type(receipt["attempts"]) is not int or receipt["attempts"] < 0:
                raise SyncError("invalid state attempt count")
            for field in ("remote_id", "last_error"):
                if receipt[field] is not None and not isinstance(receipt[field], str):
                    raise SyncError("invalid state delivery details")
            if receipt["status"] == "delivered" and not receipt["remote_id"]:
                raise SyncError("delivered state requires a receipt")
            parsed[target][channel] = Delivery(**receipt)
    questions = data["open_questions"]
    if not isinstance(questions, list):
        raise SyncError("invalid state questions")
    seen = set()
    for question in questions:
        _object(question, {"id", "question"}, "state question")
        slug = question["id"]
        if (not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug)
                or slug in seen or not isinstance(question["question"], str) or not question["question"].strip()):
            raise SyncError("invalid state question")
        seen.add(slug)
    validate_publication_state_fields(data)
    return PublicationState(**{**data, "last_publication": identity, "deliveries": parsed})


def _git(runner: CommandRunner, directory: Path, *args: str, check: bool = True, env=None, input_text=None):
    return runner.run(["git", "-C", str(directory), *args], check=check, env=env, input_text=input_text)


def _bare_fetch(runner: CommandRunner, directory: Path, url: str, branch: str) -> None:
    directory.mkdir(parents=True)
    _git(runner, directory, "init", "--bare")
    _git(runner, directory, "fetch", "--no-tags", "--", url, f"refs/heads/{branch}:refs/heads/{branch}")


def resolve_upstream(runner: CommandRunner, scratch: Path, url: str, ref: str) -> str:
    if ref != "master" and not re.fullmatch(r"[0-9a-f]{4,40}", ref):
        raise SyncError("upstream ref must be master or a hexadecimal commit id")
    advertised = None
    if ref == "master":
        advertised = runner.run(["git", "ls-remote", "--exit-code", url, "refs/heads/master"]).stdout.split()
        if len(advertised) != 2 or advertised[1] != "refs/heads/master":
            raise SyncError("upstream master could not be resolved")
        _sha(advertised[0])
    _bare_fetch(runner, scratch, url, "master")
    head = _git(runner, scratch, "rev-parse", "refs/heads/master").stdout.strip()
    if advertised is not None:
        if head != advertised[0]:
            raise SyncError("upstream moved during detection; rerun")
        return _sha(head)
    matches = _git(runner, scratch, "rev-parse", f"--disambiguate={ref}").stdout.splitlines()
    if len(matches) != 1:
        raise SyncError("ambiguous or unavailable upstream commit")
    target = _sha(matches[0])
    if _git(runner, scratch, "cat-file", "-t", target).stdout.strip() != "commit":
        raise SyncError("upstream identity is not a commit")
    if _git(runner, scratch, "merge-base", "--is-ancestor", target, head, check=False).returncode:
        raise SyncError("upstream commit is unreachable from master")
    return target


def find_sync_pr(runner: CommandRunner, repository: str, app_login: str) -> dict | None:
    endpoint = f"repos/{repository}/pulls?state=open&base=main&per_page=100"
    result = runner.run(["gh", "api", "--method", "GET", endpoint, "--paginate", "--slurp"])
    pages = _json(result.stdout, 8 * 1024 * 1024, "GitHub response")
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise SyncError("invalid paginated GitHub response")
    matches = []
    try:
        for page in pages:
            for pr in page:
                if (pr["state"] == "open" and pr["user"]["login"] == app_login
                        and pr["base"]["ref"] == "main"
                        and pr["base"]["repo"]["full_name"] == repository
                        and pr["head"]["repo"] is not None
                        and pr["head"]["repo"]["full_name"] == repository
                        and pr["head"]["ref"].startswith("dtl-sync/")):
                    if not any(label["name"] == "dtl-sync" for label in pr["labels"]):
                        if isinstance(pr["body"], str) and STATE_START in pr["body"]:
                            raise SyncError("unlabeled sync state requires retained-publication reconciliation")
                        continue
                    _branch(pr["head"]["ref"])
                    _sha(pr["head"]["sha"])
                    if type(pr["number"]) is not int or pr["number"] <= 0 or not isinstance(pr["body"], str):
                        raise SyncError("invalid sync PR identity/body")
                    matches.append(pr)
    except (KeyError, TypeError, AttributeError):
        raise SyncError("invalid GitHub PR response") from None
    if len(matches) > 1:
        raise SyncError("multiple open sync PRs; resolve the ambiguity before rerunning")
    return matches[0] if matches else None


def detect(
    *, checkout: Path, scratch: Path, repository: str, app_login: str,
    run_id: str, run_attempt: str, runner: CommandRunner,
    upstream_ref: str = "master", force: bool = False, replay: bool = False,
    upstream_url: str = UPSTREAM_URL, james_login: str | None = None,
) -> Meta:
    _repository(repository)
    _identifier(run_id)
    _identifier(run_attempt)
    if not re.fullmatch(r"[A-Za-z0-9-]+\[bot\]", app_login):
        raise SyncError("app login must be the GitHub App's bot login")
    origin = _git(runner, checkout, "remote", "get-url", "origin").stdout.strip()
    parent = scratch / "parent.git"
    _bare_fetch(runner, parent, origin, "main")
    main_sha = _sha(_git(runner, parent, "rev-parse", "refs/heads/main").stdout.strip())
    entry = _git(runner, parent, "ls-tree", main_sha, GITLINK_PATH).stdout.split()
    if len(entry) != 4 or entry[0:2] != ["160000", "commit"] or entry[3] != GITLINK_PATH:
        raise SyncError("main must contain src/sugarscape as a gitlink")
    main_pin = _sha(entry[2])
    prompt_version = _sha(_git(runner, parent, "rev-parse", f"{main_sha}:{PROMPT_PATH}").stdout.strip())
    if _git(runner, parent, "cat-file", "-t", prompt_version).stdout.strip() != "blob":
        raise SyncError("main prompt must be a file")
    upstream = scratch / "upstream.git"
    target_sha = resolve_upstream(runner, upstream, upstream_url, upstream_ref)
    pr = find_sync_pr(runner, repository, app_login)
    ancestry = _git(runner, upstream, "merge-base", "--is-ancestor", main_pin, target_sha, check=False)
    if ancestry.returncode not in (0, 1):
        raise SyncError("main pin is unavailable in upstream history")
    if replay and pr is not None:
        raise SyncError("replay is refused while an open sync PR exists")
    if ancestry.returncode == 1 and not replay:
        raise SyncError("target is not a descendant of main pin; explicit replay is required")
    branch = f"dtl-sync/{target_sha[:12]}-{run_id}-{run_attempt}"
    mode = "new-pr"
    if pr is not None:
        branch = pr["head"]["ref"]
        state = read_state(pr["body"])
        mode = "update-pr"
        current = PublicationIdentity(main_sha, target_sha, pr["head"]["sha"], prompt_version)
        if not force and state.last_publication == current:
            pending = any(receipt.status != "delivered" for channels in state.deliveries.values() for receipt in channels.values())
            has_design_label = any(label["name"] == "needs-design" for label in pr["labels"])
            label_mismatch = (state.classification is not None
                              and has_design_label != (state.classification == "needs-design"))
            mode = "retry-alerts" if pending or label_mismatch else "noop"
    elif main_pin == target_sha and not force:
        mode = "noop"
    if mode == "new-pr":
        existing = runner.run(["git", "ls-remote", origin, f"refs/heads/{branch}"]).stdout.strip()
        if existing:
            raise SyncError("generated sync branch already exists; reconcile it before rerunning")
    result = validate_meta(asdict(Meta(
        1, repository, run_id, run_attempt, main_sha, main_pin, target_sha, prompt_version,
        pr["number"] if pr else None, pr["head"]["sha"] if pr else None, branch, mode,
        f"{UPSTREAM_URL}/compare/{main_pin}...{target_sha}", force, replay,
    )))
    if pr and mode in {"noop", "retry-alerts"} and state.open_questions:
        resolved = resolve_questions(runner, result, state, [], james_login=james_login)
        if resolved.open_questions != state.open_questions:
            result = replace(result, mode="update-pr")
    return result


def path_is_protected(path: str) -> bool:
    return path in PROTECTED_FILES or path in {GITLINK_PATH, ".github"} or path.startswith(PROTECTED_PREFIXES)


def path_is_allowed(path: str) -> bool:
    parts = path.split("/")
    if (not path or path.startswith("/") or "\\" in path
            or any(part in {"", ".", ".."} or part.lower() == ".git" for part in parts)
            or any(ord(character) < 32 for character in path)):
        raise SyncError("unsafe or noncanonical patch path")
    return not path_is_protected(path) and (path in ALLOWED_FILES or path.startswith(ALLOWED_DIRECTORIES))


def _write_json(path: Path, value: object) -> None:
    text = json.dumps(value, indent=2) + "\n"
    if len(text.encode()) > MAX_REPORT_BYTES:
        raise SyncError("artifact exceeds size limit")
    path.write_text(text, encoding="utf-8")


def _write_log(path: Path, text: str) -> None:
    if len(text.encode()) > MAX_LOG_BYTES:
        raise SyncError("input log/diff exceeds size limit; manual review required")
    path.write_text(text, encoding="utf-8")


def _tree_entries(runner: CommandRunner, directory: Path, tree: str) -> dict[str, tuple[str, str]]:
    entries = {}
    for entry in _git(runner, directory, "ls-tree", "-r", "-z", tree).stdout.split("\0"):
        if entry:
            header, path = entry.split("\t", 1)
            mode, _, sha = header.split()
            path_is_allowed(path)
            entries[path] = (mode, sha)
    return entries


def _allowed_pathspecs() -> list[str]:
    return [*ALLOWED_DIRECTORIES, *sorted(ALLOWED_FILES),
            *[f":(exclude){path}" for path in sorted(PROTECTED_FILES)],
            ":(exclude)tools/dtl_sync*"]


def _resume_authorized(runner: CommandRunner, meta: Meta, comment_id: int | None, *, james_login: str | None = None) -> bool:
    if comment_id is None:
        return False
    if type(comment_id) is not int or comment_id <= 0:
        raise SyncError("invalid resume comment id")
    def get(endpoint):
        response = runner.run(["gh", "api", "--method", "GET", endpoint])
        return _json(response.stdout, MAX_REPORT_BYTES, "GitHub comment/permission")
    comment = get(f"repos/{meta.repository}/issues/comments/{comment_id}")
    if (not isinstance(comment, dict)
            or not isinstance(comment.get("body"), str)
            or comment["body"].strip() != f"resume-sync {meta.pr_head_sha}"
            or comment.get("issue_url") != f"https://api.github.com/repos/{meta.repository}/issues/{meta.pr_number}"):
        return False
    user = comment.get("user")
    login = user.get("login") if isinstance(user, dict) else None
    if not isinstance(login, str) or not re.fullmatch(r"[A-Za-z0-9-]+", login):
        raise SyncError("invalid resume author")
    return author_can_manage(runner, meta.repository, login, james_login)


def prepare_inputs(
    *, meta: Meta, checkout: Path, directory: Path, output: Path,
    app_login: str, runner: CommandRunner, upstream_url: str = UPSTREAM_URL,
    previous_report: Path | None = None, resume_comment_id: int | None = None,
    james_login: str | None = None,
) -> dict:
    validate_meta(asdict(meta))
    if meta.mode not in {"new-pr", "update-pr"}:
        raise SyncError("prepare requires an evaluation mode")
    output.mkdir(parents=True)
    result = {"main_sha": meta.main_sha, "target_sha": meta.target_sha,
              "pr_head_sha": meta.pr_head_sha, "outcome": "ready", "reason": None}
    def pause(reason):
        result.update(outcome="needs-human", reason=reason)
        _write_json(output / "prepare.json", result)
        return result
    state = None
    if meta.pr_number is not None:
        pr = find_sync_pr(runner, meta.repository, app_login)
        if pr is None or pr["number"] != meta.pr_number or pr["head"]["sha"] != meta.pr_head_sha:
            raise SyncError("PR identity moved since detection")
        state = read_state(pr["body"])
        published_head = state.last_publication.published_head_sha if state.last_publication else None
        if published_head != meta.pr_head_sha and not _resume_authorized(runner, meta, resume_comment_id, james_login=james_login):
            return pause("PR head changed outside the recorded publication; authorized resume required")
    origin = _git(runner, checkout, "remote", "get-url", "origin").stdout.strip()
    directory.mkdir(parents=True)
    _git(runner, directory, "init")
    _git(runner, directory, "config", "user.name", "DTL sync")
    _git(runner, directory, "config", "user.email", "dtl-sync@users.noreply.github.com")
    _git(runner, directory, "config", "core.hooksPath", "/dev/null")
    _git(runner, directory, "remote", "add", "origin", origin)
    _git(runner, directory, "fetch", "--no-tags", "origin", meta.main_sha)
    start = meta.pr_head_sha or meta.main_sha
    if start != meta.main_sha:
        _git(runner, directory, "fetch", "--no-tags", "origin", start)
        common = _git(runner, directory, "merge-base", meta.main_sha, start).stdout.strip()
        changed = _git(runner, directory, "diff", "--name-only", "-z", common, start).stdout.split("\0")
        if any(path and path != GITLINK_PATH and not path_is_allowed(path) for path in changed):
            return pause("PR changes protected or unsupported paths; automation stays paused until merge")
    _git(runner, directory, "checkout", "--detach", start)
    previous_pin = _tree_entries(runner, directory, start)[GITLINK_PATH][1]
    ancestor = _git(runner, directory, "merge-base", "--is-ancestor", meta.main_sha, start, check=False)
    if ancestor.returncode == 1:
        merged = _git(runner, directory, "merge", "--no-commit", "--no-ff", meta.main_sha, check=False)
        if merged.returncode:
            return pause("main merge has conflicts; review the disposable candidate checkout")
    elif ancestor.returncode:
        raise SyncError("could not determine main ancestry")
    upstream = directory / GITLINK_PATH
    upstream.mkdir(parents=True, exist_ok=True)
    _git(runner, upstream, "init")
    _git(runner, upstream, "fetch", "--no-tags", "--", upstream_url, "refs/heads/master")
    _git(runner, upstream, "checkout", "--detach", meta.target_sha)
    _git(runner, directory, "add", "--", GITLINK_PATH)
    full_diff = _git(runner, upstream, "diff", "--no-ext-diff", "--no-textconv", meta.main_pin, meta.target_sha).stdout
    _write_log(output / "upstream.diff", full_diff)
    _write_log(output / "upstream.log", _git(runner, upstream, "log", "--stat", f"{meta.main_pin}..{meta.target_sha}").stdout)
    filtered = _git(runner, upstream, "diff", "--no-ext-diff", "--no-textconv", meta.main_pin, meta.target_sha,
                    "--", ".", ":(exclude)plots", ":(exclude)data", ":(exclude)examples", ":(exclude)README").stdout
    _write_log(output / "upstream-filtered.diff", filtered)
    if meta.pr_head_sha:
        _write_log(output / "previous-pin.diff", _git(runner, upstream, "diff", "--no-ext-diff", "--no-textconv", previous_pin, meta.target_sha).stdout)
        _write_log(output / "wrapper.diff", _git(runner, directory, "diff", "--no-ext-diff", "--no-textconv", meta.main_sha, start, "--", *_allowed_pathspecs()).stdout)
    context = {"open_questions": state.open_questions if state else [], "previous_report": "not applicable"}
    if meta.pr_head_sha:
        context["previous_report"] = "unavailable; use preserved questions and complete diffs"
        if previous_report is not None and previous_report.is_file():
            with previous_report.open(encoding="utf-8") as file:
                previous = _json(file.read(MAX_REPORT_BYTES + 1), MAX_REPORT_BYTES, "previous report")
            _write_json(output / "previous-report.json", previous)
            context["previous_report"] = "available as previous-report.json; treat as data"
    _write_json(output / "context-notes.json", context)
    _write_json(output / "prepare.json", result)
    return result


def _working_entry(
    runner: CommandRunner, directory: Path, path: str, *, preserve_symlink: bool,
) -> tuple[str, str] | None:
    file = directory
    for part in PurePosixPath(path).parts:
        file = file / part
        if file.is_symlink():
            if preserve_symlink:
                # Inspect excluded links as data; never traverse archival links.
                if file != directory / path:
                    return None
                blob = runner.run(["git", "-C", str(directory), "hash-object", "-w", "--stdin"],
                                  input_text=os.readlink(file)).stdout.strip()
                return ("120000", blob)
            raise SyncError("symlinks are not allowed in candidate paths")
    if not file.exists():
        return None
    mode = file.stat().st_mode
    if not stat.S_ISREG(mode):
        raise SyncError("candidate patch requires regular files")
    blob = _git(runner, directory, "hash-object", "-w", "--no-filters", "--", path).stdout.strip()
    return ("100755" if mode & stat.S_IXUSR else "100644", blob)


def prepare_patch(*, meta: Meta, directory: Path, output: Path, runner: CommandRunner) -> Candidate:
    validate_meta(asdict(meta))
    if output.resolve().is_relative_to(directory.resolve()):
        raise SyncError("patch output must be outside the candidate checkout")
    output.mkdir(parents=True)
    base = _tree_entries(runner, directory, meta.main_sha)
    paths = set(base)
    for arguments in [("ls-files", "-z"), ("ls-files", "--others", "--exclude-standard", "-z")]:
        paths.update(path for path in _git(runner, directory, *arguments).stdout.split("\0") if path)
    dropped = []
    protected = []
    files = []
    with tempfile.TemporaryDirectory(dir=output) as temporary:
        env = {"GIT_INDEX_FILE": str(Path(temporary).resolve() / "index")}
        _git(runner, directory, "read-tree", meta.main_sha, env=env)
        for path in sorted(paths):
            if path == GITLINK_PATH:
                continue
            allowed = path_is_allowed(path)
            current = _working_entry(runner, directory, path, preserve_symlink=not allowed)
            if current == base.get(path):
                continue
            if not allowed:
                dropped.append(path)
                if path_is_protected(path):
                    protected.append(path)
                continue
            if current is not None:
                # Candidate attributes can override Git's binary detection.
                data = (directory / path).read_bytes()
                try:
                    data.decode("utf-8")
                except UnicodeDecodeError:
                    raise SyncError("binary candidate files are not allowed") from None
                if b"\0" in data:
                    raise SyncError("binary candidate files are not allowed")
            files.append(path)
            if current is None:
                _git(runner, directory, "update-index", "--force-remove", "--", path, env=env)
            else:
                mode, blob = current
                _git(runner, directory, "update-index", "--add", "--cacheinfo", f"{mode},{blob},{path}", env=env)
        numbers = _git(runner, directory, "diff", "--cached", "--numstat", "--no-ext-diff", "--no-textconv", "--no-renames", meta.main_sha, env=env).stdout
        if any(line.startswith("-\t-\t") for line in numbers.splitlines()):
            raise SyncError("binary candidate patches are not allowed")
        payload = _git(runner, directory, "diff", "--cached", "--binary", "--full-index", "--no-ext-diff", "--no-textconv", "--no-renames", meta.main_sha, env=env).stdout.encode()
        if len(payload) > MAX_PATCH_BYTES:
            raise SyncError("candidate patch exceeds size limit")
        _git(runner, directory, "update-index", "--add", "--cacheinfo", f"160000,{meta.target_sha},{GITLINK_PATH}", env=env)
        tree = _git(runner, directory, "write-tree", env=env).stdout.strip()
    upstream = directory / GITLINK_PATH
    if (_git(runner, upstream, "rev-parse", "HEAD").stdout.strip() != meta.target_sha
            or _git(runner, upstream, "status", "--porcelain", "--untracked-files=all").stdout.strip()):
        protected.append(GITLINK_PATH)
        dropped.append(GITLINK_PATH)
    result = Candidate(1, meta.main_sha, meta.target_sha, hashlib.sha256(payload).hexdigest(), tree,
                       files, sorted(protected), sorted(dropped))
    (output / "candidate.patch").write_bytes(payload)
    _write_json(output / "candidate.json", asdict(result))
    _write_json(output / "report-notes.json", {
        "main_sha": meta.main_sha, "target_sha": meta.target_sha, "patch_sha256": result.patch_sha256,
        "dropped_edits": result.dropped_edits, "protected_edits": result.protected_edits,
        "forced_classification": "needs-design" if protected else None,
        "cause": "protected-path-edit" if protected else None,
    })
    return result



@dataclass(frozen=True)
class TestResult:
    completed: bool
    exit_code: int | None = None
    collected: int | None = None
    passed: int | None = None
    failed: int | None = None
    errors: int | None = None
    skipped: int | None = None
    reason: str | None = None


@dataclass(frozen=True)
class Verification:
    schema_version: int
    main_sha: str
    target_sha: str
    patch_sha256: str
    candidate_tree: str | None
    pin_matches_target: bool | None
    patch_applied: bool | None
    hash_changed: bool | None
    hash_old: str | None
    hash_new: str | None
    candidate_tests: TestResult
    baseline_tests: TestResult
    reason: str | None
    image_id: str | None
    excluded_markers: list[str]


def validate_candidate(value: object) -> Candidate:
    data = _object(value, set(Candidate.__dataclass_fields__), "candidate")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise SyncError("unsupported candidate version")
    for key in ("main_sha", "target_sha", "candidate_tree"):
        _sha(data[key])
    if not isinstance(data["patch_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", data["patch_sha256"]):
        raise SyncError("invalid patch digest")
    for key in ("files_changed", "protected_edits", "dropped_edits"):
        items = data[key]
        if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
            raise SyncError("invalid candidate path list")
        if items != sorted(set(items)):
            raise SyncError("candidate paths must be unique and sorted")
    return Candidate(**data)



def read_candidate(path: Path) -> Candidate:
    with path.open(encoding="utf-8") as file:
        text = file.read(MAX_REPORT_BYTES + 1)
    return validate_candidate(_json(text, MAX_REPORT_BYTES, "candidate"))


def fresh_checkout(runner: CommandRunner, source: Path, directory: Path, main: str,
                   pin: str, upstream_url: str) -> None:
    directory.mkdir(parents=True)
    _git(runner, directory, "init")
    _git(runner, directory, "config", "core.hooksPath", "/dev/null")
    origin = _git(runner, source, "remote", "get-url", "origin").stdout.strip()
    _git(runner, directory, "fetch", "--no-tags", origin, main)
    _git(runner, directory, "checkout", "--detach", main)
    upstream = directory / GITLINK_PATH
    upstream.mkdir(parents=True, exist_ok=True)
    _git(runner, upstream, "init")
    _git(runner, upstream, "config", "core.hooksPath", "/dev/null")
    _git(runner, upstream, "fetch", "--no-tags", upstream_url, pin)
    _git(runner, upstream, "checkout", "--detach", pin)
    if _git(runner, upstream, "rev-parse", "HEAD").stdout.strip() != pin:
        raise SyncError("independent upstream checkout has wrong pin")
    _git(runner, directory, "update-index", "--add", "--cacheinfo", f"160000,{pin},{GITLINK_PATH}")


def reconstruct_candidate(*, meta: Meta, candidate: Candidate, patch: Path,
                          checkout: Path, directory: Path, runner: CommandRunner,
                          upstream_url: str = UPSTREAM_URL) -> Path:
    validate_meta(asdict(meta))
    validate_candidate(asdict(candidate))
    if (candidate.main_sha, candidate.target_sha) != (meta.main_sha, meta.target_sha):
        raise SyncError("candidate identity mismatch")
    with patch.open("rb") as file:
        payload = file.read(MAX_PATCH_BYTES + 1)
    if len(payload) > MAX_PATCH_BYTES or hashlib.sha256(payload).hexdigest() != candidate.patch_sha256:
        raise SyncError("candidate patch size or digest mismatch")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise SyncError("candidate patch is not UTF-8") from None
    fresh_checkout(runner, checkout, directory, meta.main_sha, meta.target_sha, upstream_url)
    base = _tree_entries(runner, directory, meta.main_sha)
    if base.get(GITLINK_PATH) != ("160000", meta.main_pin):
        raise SyncError("captured main pin mismatch")
    # Git validates paths and modes in its index; no candidate hooks or filters run.
    if text:
        summary = _git(runner, directory, "apply", "--numstat", "-z", "-", input_text=text).stdout
        for entry in summary.split("\0"):
            if not entry:
                continue
            parts = entry.split("\t", 2)
            if len(parts) != 3 or not path_is_allowed(parts[2]):
                raise SyncError("candidate patch contains a forbidden path")
            if "-" in parts[:2]:
                raise SyncError("binary candidate patch encoding")
        _git(runner, directory, "apply", "--cached", "--check", "--whitespace=nowarn", "-", input_text=text)
        _git(runner, directory, "apply", "--cached", "--whitespace=nowarn", "-", input_text=text)
    tree = _git(runner, directory, "write-tree").stdout.strip()
    entries = _tree_entries(runner, directory, tree)
    changed = sorted(path for path in base.keys() | entries.keys() if base.get(path) != entries.get(path) and path != GITLINK_PATH)
    if entries.get(GITLINK_PATH) != ("160000", meta.target_sha):
        raise SyncError("patch changes the independently staged gitlink")
    for path in changed:
        if not path_is_allowed(path):
            raise SyncError("candidate patch contains a forbidden path")
        for entry in (base.get(path), entries.get(path)):
            if entry is None:
                continue
            if entry[0] not in {"100644", "100755"}:
                raise SyncError("candidate patch requires regular files")
            # cat-file returns bytes through a strict UTF-8 command transport.
            try:
                content = _git(runner, directory, "cat-file", "blob", entry[1]).stdout
            except UnicodeDecodeError:
                raise SyncError("binary candidate patch") from None
            if "\0" in content:
                raise SyncError("binary candidate patch")
    if changed != candidate.files_changed or tree != candidate.candidate_tree:
        raise SyncError("candidate file list or tree mismatch")
    # Populate only after policy validation, using fresh trusted Git configuration.
    _git(runner, directory, "read-tree", "--reset", "-u", tree)
    return directory


def parse_test_result(payload: str, exit_code: int | None, collected: object,
                      collection_complete: object) -> TestResult:
    unknown = TestResult(False, exit_code, reason="missing or inconsistent test evidence")
    if (type(exit_code) is not int or exit_code not in (0, 1) or type(collected) is not int
            or collected <= 0 or collection_complete is not True or not isinstance(payload, str)
            or len(payload.encode()) > MAX_LOG_BYTES or "<!" in payload):
        return unknown
    try:
        root = ET.fromstring(payload)
        if root.tag != "testsuites" or len(root) != 1 or root[0].tag != "testsuite":
            return unknown
        suite = root[0]
        counts = {key: int(suite.attrib[key]) for key in ("tests", "failures", "errors", "skipped")}
        cases = list(suite)
        if any(case.tag != "testcase" for case in cases) or any(value < 0 for value in counts.values()):
            return unknown
        failed = sum(case.find("failure") is not None for case in cases)
        errors = sum(case.find("error") is not None for case in cases)
        skipped = sum(case.find("skipped") is not None for case in cases)
        if (len(cases) != counts["tests"] or counts["tests"] != collected
                or (failed, errors, skipped) != (counts["failures"], counts["errors"], counts["skipped"])
                or failed + errors + skipped > collected
                or (exit_code == 0) != (failed + errors == 0)):
            return unknown
        return TestResult(True, exit_code, collected, collected-failed-errors-skipped,
                          failed, errors, skipped)
    except (ET.ParseError, KeyError, ValueError, RecursionError):
        return unknown


VERIFIER_SETUP = "docker build -f tools/dtl_sync/verify.Dockerfile -t dtl-sync-verifier ."
RESULT_PREFIX = "DTL_SYNC_RESULT="


def verifier_image(runner: CommandRunner, image: str) -> str:
    try:
        identity = runner.run(["docker", "image", "inspect", image, "--format", "{{.Id}}"]).stdout.strip()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", identity):
            raise SyncError("invalid image identity")
        return identity
    except SyncError:
        raise SyncError(f"Docker/verifier image unavailable. Start Docker, then run: {VERIFIER_SETUP}") from None


def container_measurement(*, runner: CommandRunner, image: str, directory: Path,
                          harness: Path, command: list[str], timeout: float = 900):
    name = "dtl-sync-" + uuid.uuid4().hex
    mounts = []
    for source, target in ((directory, "/workspace"), (harness, "/harness")):
        if "," in str(source.resolve()):
            raise SyncError("Docker mount path cannot contain commas")
        mounts.extend(["--mount", f"type=bind,src={source.resolve()},dst={target},readonly"])
    args = ["docker", "run", "--name", name, "--read-only", "--network=none",
            "--user", "65534:65534", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--cpus=2", "--memory=4g", "--pids-limit=256", "--log-driver=none",
            "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=1g,mode=1777", "--workdir", "/workspace",
            "--env", "PYTHONHASHSEED=0", "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--env", "DTL_SYNC_CONTAINER=1", *mounts, image,
            "/opt/venv/bin/python", "-I", "/harness/" + command[0], *command[1:]]
    try:
        return runner.run_bounded(args, timeout=timeout)
    finally:
        # Removing by controller-generated name kills every remaining container process.
        runner.run(["docker", "rm", "--force", name])


def measurement_data(result) -> dict:
    lines = [line[len(RESULT_PREFIX):] for line in result.stdout.splitlines() if line.startswith(RESULT_PREFIX)]
    if len(lines) != 1:
        raise SyncError("measurement did not emit exactly one result")
    data = _json(lines[0], MAX_LOG_BYTES, "measurement")
    if not isinstance(data, dict):
        raise SyncError("invalid measurement")
    return data


def prepare_measurement_environment(directory: Path) -> None:
    """Expose the image's trusted environment at the repository's normal test path."""
    (directory / ".venv").symlink_to("/opt/venv", target_is_directory=True)


def suite_measurement(runner: CommandRunner, image: str, directory: Path,
                      harness: Path, log: Path) -> TestResult:
    try:
        result = container_measurement(runner=runner, image=image, directory=directory,
                                       harness=harness, command=["test_results.py"])
        _write_log(log, result.stdout)
        data = measurement_data(result)
        return parse_test_result(data.get("xml", ""), result.returncode,
                                 data.get("collected"), data.get("collection_complete"))
    except SyncError as error:
        return TestResult(False, reason=str(error))


def verify(*, meta: Meta, candidate: Candidate, patch: Path, checkout: Path,
           directory: Path, output: Path, runner: CommandRunner,
           image: str = "dtl-sync-verifier", upstream_url: str = UPSTREAM_URL) -> Verification:
    validate_meta(asdict(meta))
    validate_candidate(asdict(candidate))
    output.mkdir(parents=True)
    directory.mkdir(parents=True)
    unknown = TestResult(False, reason="measurement not run")
    fields = dict(schema_version=1, main_sha=meta.main_sha, target_sha=meta.target_sha,
                  patch_sha256=candidate.patch_sha256, candidate_tree=None,
                  pin_matches_target=None, patch_applied=None, hash_changed=None,
                  hash_old=None, hash_new=None, candidate_tests=unknown, baseline_tests=unknown,
                  reason=None, image_id=None, excluded_markers=["perf"])
    try:
        fields["image_id"] = verifier_image(runner, image)
        candidate_dir = reconstruct_candidate(meta=meta, candidate=candidate, patch=patch,
            checkout=checkout, directory=directory / "candidate", runner=runner, upstream_url=upstream_url)
        fields.update(candidate_tree=candidate.candidate_tree, patch_applied=True, pin_matches_target=True)
        stock = directory / "stock"
        baseline = directory / "baseline"
        fresh_checkout(runner, checkout, stock, meta.main_sha, meta.target_sha, upstream_url)
        fresh_checkout(runner, checkout, baseline, meta.main_sha, meta.main_pin, upstream_url)
        harness = directory / "harness"
        harness.mkdir()
        for name in ("probe.py", "test_results.py"):
            content = _git(runner, baseline, "show", f"{meta.main_sha}:tools/dtl_sync/{name}").stdout
            (harness / name).write_text(content)
        # Read the expected constant as syntax, never import main/candidate code on the host.
        syntax = ast.parse((baseline / "tests/test_dtl.py").read_text())
        constants = [node.value.value for node in syntax.body if isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id == "EXPECTED_TRAJECTORY_HASH" for target in node.targets)
                     and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)]
        if len(constants) != 1 or not re.fullmatch(r"[0-9a-f]{64}", constants[0]):
            raise SyncError("trusted trajectory constant unavailable")
        fields["hash_old"] = constants[0]
        for tree in (candidate_dir, stock, baseline):
            prepare_measurement_environment(tree)
        reasons = []
        try:
            result = container_measurement(runner=runner, image=fields["image_id"], directory=stock,
                                           harness=harness, command=["probe.py"])
            _write_log(output / "stock.log", result.stdout)
            data = measurement_data(result)
            measured = data.get("hash_new")
            if result.returncode != 0 or not isinstance(measured, str) or not re.fullmatch(r"[0-9a-f]{64}", measured):
                raise SyncError("stock probe did not complete")
            fields.update(hash_new=measured, hash_changed=measured != fields["hash_old"])
        except SyncError as error:
            reasons.append(str(error))
        for key, tree in (("candidate_tests", candidate_dir), ("baseline_tests", baseline)):
            measured = suite_measurement(runner, fields["image_id"], tree, harness, output / f"{key}.log")
            fields[key] = measured
            if not measured.completed:
                reasons.append(f"{key}: {measured.reason}")
        fields["reason"] = "; ".join(reasons) or None
    except (SyncError, OSError, SyntaxError) as error:
        fields["reason"] = str(error) if isinstance(error, SyncError) else "verifier input/setup failed"
    result = Verification(**fields)
    _write_json(output / "verify.json", asdict(result))
    return result



@dataclass(frozen=True)
class Report:
    classification: str
    cause: str
    summary: str
    upstream_range: dict[str, str]
    reachability: list[dict]
    design_questions: list[dict[str, str]]
    reasoning: str


CLASSIFICATIONS = {"mechanical", "no-impact", "needs-design"}
CAUSES = {"semantic-change", "new-feature", "compat-defect", "baseline-failure",
          "protected-path-edit", "incomplete-verification", "none"}


def _report_text(value: object, limit: int, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise SyncError(f"invalid report {field}")
    return value


def validate_report(value: object, meta: Meta) -> Report:
    data = _object(value, set(Report.__dataclass_fields__), "report")
    if not isinstance(data["classification"], str) or data["classification"] not in CLASSIFICATIONS:
        raise SyncError("invalid report classification")
    if not isinstance(data["cause"], str) or data["cause"] not in CAUSES:
        raise SyncError("invalid report cause")
    _report_text(data["summary"], 1000, "summary")
    _report_text(data["reasoning"], 8000, "reasoning")
    interval = _object(data["upstream_range"], {"from", "to"}, "upstream range")
    if interval != {"from": meta.main_pin, "to": meta.target_sha}:
        raise SyncError("report upstream range mismatch")
    for field in ("reachability", "design_questions"):
        if not isinstance(data[field], list) or len(data[field]) > 100:
            raise SyncError(f"invalid report {field}")
    items = set()
    for item in data["reachability"]:
        _object(item, {"path", "symbol", "reached", "reason"}, "reachability item")
        path = _report_text(item["path"], 500, "path")
        if path.startswith("/") or "\\" in path or any(part in {"", ".", ".."} for part in path.split("/")) or any(ord(c) < 32 for c in path):
            raise SyncError("invalid upstream inventory path")
        _report_text(item["symbol"], 500, "symbol")
        _report_text(item["reason"], 2000, "reachability reason")
        if type(item["reached"]) is not bool or (path, item["symbol"]) in items:
            raise SyncError("invalid or duplicate reachability item")
        items.add((path, item["symbol"]))
    questions = set()
    for question in data["design_questions"]:
        _object(question, {"id", "question"}, "design question")
        slug = _report_text(question["id"], 100, "question id")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) or slug in questions:
            raise SyncError("invalid or duplicate design question id")
        _report_text(question["question"], 2000, "question")
        questions.add(slug)
    if len(json.dumps(data).encode()) > MAX_REPORT_BYTES:
        raise SyncError("report exceeds size limit")
    return Report(**data)


def validate_verification(value: object, meta: Meta, candidate: Candidate) -> Verification:
    """Accept only complete, bound evidence; completed red tests remain valid."""
    data = _object(value, set(Verification.__dataclass_fields__), "verification")
    if (candidate.main_sha, candidate.target_sha) != (meta.main_sha, meta.target_sha):
        raise SyncError("candidate verification binding mismatch")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise SyncError("invalid verification version")
    for field, expected in (("main_sha", meta.main_sha), ("target_sha", meta.target_sha),
                            ("patch_sha256", candidate.patch_sha256), ("candidate_tree", candidate.candidate_tree)):
        if data[field] != expected:
            raise SyncError("verification binding mismatch")
    if data["pin_matches_target"] is not True or data["patch_applied"] is not True:
        raise SyncError("incomplete verification: pin or patch not verified")
    for field in ("hash_old", "hash_new"):
        if not isinstance(data[field], str) or not re.fullmatch(r"[0-9a-f]{64}", data[field]):
            raise SyncError("incomplete verification: invalid hash")
    if type(data["hash_changed"]) is not bool or data["hash_changed"] != (data["hash_old"] != data["hash_new"]):
        raise SyncError("inconsistent verification hash evidence")
    if data["reason"] is not None or data["excluded_markers"] != ["perf"]:
        raise SyncError("incomplete verification or unexpected test exclusions")
    if not isinstance(data["image_id"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", data["image_id"]):
        raise SyncError("incomplete verification image identity")
    parsed = dict(data)
    for field in ("candidate_tests", "baseline_tests"):
        result = _object(data[field], set(TestResult.__dataclass_fields__), field)
        if result["completed"] is not True or result["reason"] is not None:
            raise SyncError("incomplete verification: test collection did not complete")
        for count in ("exit_code", "collected", "passed", "failed", "errors", "skipped"):
            if type(result[count]) is not int or result[count] < 0:
                raise SyncError("invalid verification test count")
        if (result["exit_code"] not in (0, 1) or result["collected"] <= 0
                or sum(result[k] for k in ("passed", "failed", "errors", "skipped")) != result["collected"]
                or (result["exit_code"] == 0) != (result["failed"] + result["errors"] == 0)
                or result["collected"] == result["skipped"]):
            raise SyncError("incomplete or inconsistent verification test results")
        parsed[field] = TestResult(**result)
    return Verification(**parsed)


def classify(report: Report, candidate: Candidate, verification: Verification,
             open_questions: list[dict]) -> tuple[str, str]:
    """Classify already validated evidence, retaining conservative agent judgement."""
    if verification.hash_changed:
        return "needs-design", "semantic-change"
    if candidate.protected_edits:
        return "needs-design", "protected-path-edit"
    if verification.baseline_tests.exit_code:
        return "needs-design", "baseline-failure"
    if verification.candidate_tests.exit_code:
        return "needs-design", "compat-defect"
    if report.cause == "new-feature":
        return "needs-design", "new-feature"
    if open_questions or report.design_questions or report.classification == "needs-design":
        return "needs-design", "none"
    if candidate.files_changed or any(item["reached"] for item in report.reachability):
        return "mechanical", "none"
    return "no-impact", "none"


def publication_heads(runner: CommandRunner, origin: str, branch: str) -> dict[str, str]:
    refs = {"refs/heads/main", f"refs/heads/{branch}"}
    lines = runner.run(["git", "ls-remote", "--heads", origin, *sorted(refs)]).stdout.splitlines()
    heads = {}
    for line in lines:
        fields = line.split()
        if len(fields) != 2 or fields[1] not in refs or fields[1] in heads:
            raise SyncError("invalid remote head response")
        heads[fields[1]] = _sha(fields[0])
    return heads


def publication_pr(runner: CommandRunner, meta: Meta, app_login: str) -> dict | None:
    pr = find_sync_pr(runner, meta.repository, app_login)
    if ((meta.pr_number is None and pr is not None)
            or (meta.pr_number is not None and (pr is None or pr["number"] != meta.pr_number
                                               or pr["head"]["ref"] != meta.branch))):
        raise SyncError("stale PR identity or state")
    return pr


def publication_commit(runner: CommandRunner, directory: Path, meta: Meta, report: Report,
                       tree: str, classification: str, app_login: str, app_email: str) -> str:
    parent = meta.pr_head_sha or meta.main_sha
    parents = ["-p", parent]
    if meta.pr_head_sha:
        ancestry = _git(runner, directory, "merge-base", "--is-ancestor", meta.main_sha, parent, check=False).returncode
        if ancestry not in (0, 1):
            raise SyncError("could not establish publication ancestry")
        if ancestry == 1:
            parents += ["-p", meta.main_sha]
    timestamp = int(_git(runner, directory, "show", "-s", "--format=%ct", parent).stdout.strip()) + 1
    # Stable dates and complete input identity let a retry recognize exactly its
    # own pushed commit after a branch-success/PR-failure split, without trusting authorship.
    environment = {"GIT_AUTHOR_NAME": app_login, "GIT_COMMITTER_NAME": app_login,
                   "GIT_AUTHOR_EMAIL": app_email, "GIT_COMMITTER_EMAIL": app_email,
                   "GIT_AUTHOR_DATE": f"@{timestamp} +0000", "GIT_COMMITTER_DATE": f"@{timestamp} +0000"}
    subject = report.summary.splitlines()[0].split(". ", 1)[0].rstrip(".")[:180]
    body = json.dumps({"meta": asdict(meta), "report": asdict(report)}, sort_keys=True, indent=2)
    message = f"dtl-sync: {classification}: {subject}\n\n{body}\n"
    return _sha(_git(runner, directory, "commit-tree", tree, *parents,
                     input_text=message, env=environment).stdout.strip())


def publish_tree(*, meta: Meta, candidate: Candidate, patch: Path, report: object,
                 verification: object, checkout: Path, directory: Path, output: Path,
                 runner: CommandRunner, app_login: str, app_email: str,
                 upstream_url: str = UPSTREAM_URL, james_login: str | None = None) -> dict:
    validate_meta(asdict(meta))
    validate_candidate(asdict(candidate))
    report = validate_report(report, meta)
    verification = validate_verification(verification, meta, candidate)
    if meta.mode not in {"new-pr", "update-pr"}:
        raise SyncError("publication requires an evaluated candidate")
    if not re.fullmatch(r"[A-Za-z0-9-]+\[bot\]", app_login) or not re.fullmatch(r"[A-Za-z0-9+_.\[\]-]+@users\.noreply\.github\.com", app_email):
        raise SyncError("invalid publication App identity")
    output.mkdir(parents=True)
    origin = _git(runner, checkout, "remote", "get-url", "origin").stdout.strip()
    heads = publication_heads(runner, origin, meta.branch)
    if heads.get("refs/heads/main") != meta.main_sha:
        raise SyncError("stale main head")
    pr = publication_pr(runner, meta, app_login)
    observed = heads.get(f"refs/heads/{meta.branch}")
    if pr is not None and pr["head"]["sha"] != observed:
        raise SyncError("stale PR head differs from branch")
    question_state = resolve_questions(runner, meta, read_state(pr["body"]), report.design_questions,
                                       james_login=james_login) if pr else new_state()
    resolved_report = replace(report, design_questions=question_state.open_questions) if pr else report
    classification, cause = classify(resolved_report, candidate, verification, question_state.open_questions)
    reconstruct_candidate(meta=meta, candidate=candidate, patch=patch, checkout=checkout,
                          directory=directory, runner=runner, upstream_url=upstream_url)
    upstream = directory / GITLINK_PATH
    _git(runner, upstream, "fetch", "--no-tags", upstream_url, meta.main_pin)
    changed = set(_git(runner, upstream, "diff", "--name-only", "--no-renames", "-z",
                       meta.main_pin, meta.target_sha).stdout.split("\0")) - {""}
    if {item["path"] for item in report.reachability} != changed:
        raise SyncError("upstream reachability inventory does not cover the exact changed files")
    if meta.pr_head_sha:
        _git(runner, directory, "fetch", "--no-tags", origin, meta.pr_head_sha)
    parent = meta.pr_head_sha or meta.main_sha
    if _git(runner, directory, "rev-parse", f"{parent}^{{tree}}").stdout.strip() == candidate.candidate_tree:
        outgoing = parent
        outcome = "unchanged"
    else:
        outgoing = publication_commit(runner, directory, meta, report, candidate.candidate_tree,
                                      classification, app_login, app_email)
        outcome = "reconciled" if observed == outgoing else "pushed"
    expected = meta.pr_head_sha
    if observed != expected and observed != outgoing:
        raise SyncError("stale branch head; refusing to overwrite unrelated work")
    # Re-check both Git and GitHub immediately before the normal fast-forward push.
    if publication_heads(runner, origin, meta.branch) != heads or publication_pr(runner, meta, app_login) != pr:
        raise SyncError("stale remote state changed during publication")
    if outcome == "pushed":
        _git(runner, directory, "push", "--", origin, f"{outgoing}:refs/heads/{meta.branch}")
    result = {"schema_version": 1, "outcome": outcome, "main_sha": meta.main_sha,
              "target_sha": meta.target_sha, "prompt_version": meta.prompt_version,
              "published_head_sha": outgoing, "candidate_tree": candidate.candidate_tree,
              "patch_sha256": candidate.patch_sha256, "classification": classification, "cause": cause,
              "verification": asdict(verification),
              "report_sha256": hashlib.sha256(json.dumps(asdict(report), sort_keys=True).encode()).hexdigest()}
    _write_json(output / "publication.json", result)
    return result


def read_publication_artifact(path: Path) -> object:
    with path.open(encoding="utf-8") as file:
        payload = file.read(MAX_REPORT_BYTES + 1)
    return _json(payload, MAX_REPORT_BYTES, path.name)


OUTCOMES = {"noop", "published", "needs-human", "incomplete-verification", "operational-failure"}
TELEMETRY_FIELDS = {"requested_model", "actual_model", "codex_version", "action_sha",
                    "elapsed_seconds", "token_usage", "unavailable_reason"}


def new_state() -> PublicationState:
    telemetry = dict.fromkeys(TELEMETRY_FIELDS)
    telemetry["unavailable_reason"] = "workflow telemetry was not supplied"
    return PublicationState(1, None, {}, [], "noop", None, None, [], None, telemetry, [], [])


def validate_publication_state_fields(data: dict) -> None:
    if not isinstance(data["outcome"], str) or data["outcome"] not in OUTCOMES:
        raise SyncError("invalid state outcome")
    for key, allowed in (("classification", CLASSIFICATIONS), ("cause", CAUSES)):
        if data[key] is not None and (not isinstance(data[key], str) or data[key] not in allowed):
            raise SyncError("invalid state classification/cause")
    artifact = data["previous_report_artifact"]
    if artifact is not None and (not isinstance(artifact, str) or not re.fullmatch(r"[1-9][0-9]*", artifact)):
        raise SyncError("invalid report artifact id")
    runs = data["recent_runs"]
    if not isinstance(runs, list) or len(runs) > 10:
        raise SyncError("invalid recent runs")
    for run in runs:
        _object(run, {"run_id", "run_attempt", "outcome"}, "state run")
        _identifier(run["run_id"]); _identifier(run["run_attempt"])
        if not isinstance(run["outcome"], str) or run["outcome"] not in OUTCOMES:
            raise SyncError("invalid run outcome")
    for field, keys in (("resolved_questions", {"id", "question", "comment_id"}),
                        ("accepted_resumes", {"comment_id", "head_sha"})):
        if not isinstance(data[field], list):
            raise SyncError("invalid authorization receipts")
        seen = set()
        for receipt in data[field]:
            _object(receipt, keys, "authorization receipt")
            number = receipt["comment_id"]
            if type(number) is not int or number <= 0 or number in seen:
                raise SyncError("invalid authorization comment id")
            seen.add(number)
            if field == "accepted_resumes":
                _sha(receipt["head_sha"])
            elif (not isinstance(receipt["id"], str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", receipt["id"])
                  or not isinstance(receipt["question"], str) or not receipt["question"].strip()):
                raise SyncError("invalid resolved question")
    telemetry = _object(data["telemetry"], TELEMETRY_FIELDS, "telemetry")
    for key in ("requested_model", "actual_model", "codex_version", "unavailable_reason"):
        if telemetry[key] is not None:
            _report_text(telemetry[key], 500, key)
    if telemetry["action_sha"] is not None:
        _sha(telemetry["action_sha"])
    elapsed = telemetry["elapsed_seconds"]
    if elapsed is not None and (type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0):
        raise SyncError("invalid elapsed telemetry")
    usage = telemetry["token_usage"]
    if usage is not None:
        _object(usage, {"input_tokens", "output_tokens", "total_tokens"}, "token usage")
        if any(type(v) is not int or v < 0 for v in usage.values()) or usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]:
            raise SyncError("invalid token telemetry")
    if any(telemetry[key] is None for key in TELEMETRY_FIELDS - {"unavailable_reason"}) and not telemetry["unavailable_reason"]:
        raise SyncError("missing telemetry must have a reason")


def github(runner: CommandRunner, method: str, endpoint: str, payload=None, *, paginate=False):
    args = ["gh", "api", "--method", method, endpoint]
    options = {}
    if payload is not None:
        args += ["--input", "-"]
        options["input_text"] = json.dumps(payload)
    if paginate:
        args += ["--paginate", "--slurp"]
    response = runner.run(args, **options)
    return _json(response.stdout, MAX_LOG_BYTES, "GitHub response") if response.stdout.strip() else None


def author_can_manage(runner: CommandRunner, repository: str, login: str, james_login: str | None) -> bool:
    if not isinstance(login, str) or not re.fullmatch(r"[A-Za-z0-9-]+", login):
        return False
    if james_login is not None and login == james_login:
        return True
    permission = github(runner, "GET", f"repos/{repository}/collaborators/{login}/permission")
    return isinstance(permission, dict) and permission.get("permission") in {"write", "maintain", "admin"}


def resolve_questions(runner: CommandRunner, meta: Meta, state: PublicationState,
                      proposed: list[dict], *, james_login: str | None) -> PublicationState:
    resolved = [dict(receipt) for receipt in state.resolved_questions]
    closed = {(receipt["id"], receipt["question"]) for receipt in resolved}
    questions = {question["id"]: dict(question) for question in state.open_questions}
    for question in proposed:
        if (question["id"], question["question"]) not in closed:
            questions[question["id"]] = dict(question)
    if questions:
        pages = github(runner, "GET", f"repos/{meta.repository}/issues/{meta.pr_number}/comments?per_page=100", paginate=True)
        if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
            raise SyncError("invalid comment pages")
        consumed = {receipt["comment_id"] for receipt in resolved}
        for comment in (comment for page in pages for comment in page):
            if not isinstance(comment, dict) or not isinstance(comment.get("body"), str):
                raise SyncError("invalid resolution comment")
            match = re.fullmatch(r"resolved: ([a-z0-9]+(?:-[a-z0-9]+)*)", comment["body"].strip())
            number = comment.get("id")
            if not match or match[1] not in questions or number in consumed:
                continue
            if type(number) is not int or number <= 0:
                raise SyncError("invalid resolution comment id")
            user = comment.get("user")
            login = user.get("login") if isinstance(user, dict) else None
            if author_can_manage(runner, meta.repository, login, james_login):
                question = questions.pop(match[1])
                resolved.append({**question, "comment_id": number})
                consumed.add(number)
    return replace(state, open_questions=list(questions.values()), resolved_questions=resolved)


def state_block(state: PublicationState) -> str:
    payload = json.dumps(asdict(state), sort_keys=True).replace("<", "\\u003c").replace(">", "\\u003e")
    block = STATE_START + payload + STATE_END
    read_state(block)
    return block


def public_text(value: str, limit: int = 1500) -> str:
    return html.escape(value[:limit]).replace("@", "&#64;").replace("|", "\\|")


def render_pr_body(report: Report | None, state: PublicationState, run_url: str, compare_url: str | None,
                   verification: Verification | None = None) -> str:
    lines = ["## DTL upstream sync", "", f"Outcome: **{state.outcome}**. Classification: **{state.classification or 'unavailable'}**; cause: **{state.cause or 'unavailable'}**.",
             f"[Run and artifacts]({run_url})"]
    if compare_url:
        lines.append(f"[Upstream comparison]({compare_url})")
    if report:
        lines += ["", public_text(report.summary), "", "### Reachability", "", "Path / symbol | Reached | Reason", "--- | --- | ---"]
        table_bytes = 0
        for item in report.reachability:
            row = f"{public_text(item['path'],500)} / {public_text(item['symbol'],500)} | {item['reached']} | {public_text(item['reason'],200).replace(chr(10),' ')}"
            table_bytes += len(row.encode()) + 1
            if table_bytes > 12 * 1024:
                lines += ["", "Full report, including remaining reachability entries, is in the linked artifacts."]
                break
            lines.append(row)
        lines += ["", "### Reasoning", "", public_text(report.reasoning,2000)]
    if verification:
        lines += ["", "### Independent measurements", "", f"Stock hash changed: {verification.hash_changed}. Excluded markers: perf."]
        for name, result in (("Candidate", verification.candidate_tests), ("Baseline", verification.baseline_tests)):
            lines.append(f"{name}: exit {result.exit_code}; {result.passed} passed, {result.failed} failed, {result.errors} errors, {result.skipped} skipped / {result.collected} collected.")
    lines += ["", "### Open design questions", ""]
    lines += [f"- **{question['id']}**: {public_text(question['question'],500)}" for question in state.open_questions] or ["None."]
    telemetry = state.telemetry
    lines += ["", "### Telemetry", "", public_text(json.dumps(telemetry),1500)]
    block = state_block(state)
    human = "\n".join(lines)
    budget = MAX_PR_BODY_BYTES - len(block.encode()) - 2
    if len(human.encode()) > budget:
        notice = f"\n\nFull report is in [the run artifacts]({run_url}); human summary shortened to retain complete state."
        if budget < len(notice.encode()):
            raise SyncError("complete state leaves no room for the PR summary; manual archival required")
        human = human.encode()[:budget - len(notice.encode())].decode("utf-8", errors="ignore") + notice
    return human + "\n\n" + block


class NoAlertRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SyncError("alert redirect refused")


class AlertHTTP:
    def __init__(self, *, discord_token: str, asana_token: str, open_request=None, sleep=time.sleep):
        self.tokens = {"discord": discord_token, "asana": asana_token}
        self.open_request = open_request or build_opener(NoAlertRedirect()).open
        self.sleep = sleep

    def request(self, service: str, method: str, path: str, payload=None):
        hosts = {"discord": "discord.com/api/v10", "asana": "app.asana.com/api/1.0"}
        if service not in hosts or not path.startswith("/") or path.startswith("//") or "\\" in path or urlsplit(path).scheme or urlsplit(path).netloc:
            raise SyncError("invalid alert API path")
        if not self.tokens[service]:
            raise SyncError(f"missing {service} credential")
        url = "https://" + hosts[service] + path
        token = ("Bot " if service == "discord" else "Bearer ") + self.tokens[service]
        request = Request(url, data=None if payload is None else json.dumps(payload).encode(),
                          headers={"Authorization": token, "Content-Type": "application/json"}, method=method)
        for attempt in range(3):
            try:
                with self.open_request(request, timeout=10) as response:
                    raw = response.read(MAX_LOG_BYTES + 1)
                return _json(raw.decode(), MAX_LOG_BYTES, "alert response")
            except HTTPError as error:
                if error.code != 429 and not 500 <= error.code <= 599 or attempt == 2:
                    raise SyncError(f"{service} HTTP {error.code}") from None
                delay = error.headers.get("Retry-After", "1") if error.headers else "1"
                try:
                    delay = float(delay)
                except ValueError:
                    try:
                        delay = parsedate_to_datetime(delay).timestamp() - time.time()
                    except (ValueError, TypeError, OverflowError):
                        delay = 1
                self.sleep(max(0, min(5, delay)))
            except (URLError, OSError):
                if attempt == 2:
                    raise SyncError(f"{service} transport failed after three attempts") from None
                self.sleep(attempt + 1)
            except UnicodeDecodeError:
                raise SyncError(f"invalid {service} response encoding") from None


def send_discord(http: AlertHTTP, recipient: str, message: str) -> str:
    _identifier(recipient)
    channel = http.request("discord", "POST", "/users/@me/channels", {"recipient_id": recipient})
    channel_id = _identifier(channel.get("id") if isinstance(channel, dict) else None)
    response = http.request("discord", "POST", f"/channels/{channel_id}/messages",
                            {"content": message[:1800], "allowed_mentions": {"parse": []}})
    return _identifier(response.get("id") if isinstance(response, dict) else None)


def send_asana(http: AlertHTTP, project: str, target: str, title: str, message: str) -> str:
    _identifier(project); _sha(target)
    marker = "dtl-sync:" + target
    offset = None
    seen = set()
    for _ in range(100):
        query = {"limit": "100", "opt_fields": "gid,notes"}
        if offset:
            query["offset"] = offset
        page = http.request("asana", "GET", f"/projects/{project}/tasks?{urlencode(query)}")
        if not isinstance(page, dict) or not isinstance(page.get("data"), list):
            raise SyncError("invalid Asana project tasks")
        matches = [task for task in page["data"] if isinstance(task, dict) and marker in str(task.get("notes", "")).splitlines()]
        if matches:
            return _identifier(matches[0].get("gid"))
        next_page = page.get("next_page")
        if next_page is None:
            response = http.request("asana", "POST", "/tasks", {"data": {"name": title[:200], "notes": marker + "\n" + message, "projects": [project]}})
            task = response.get("data") if isinstance(response, dict) else None
            return _identifier(task.get("gid") if isinstance(task, dict) else None)
        offset = next_page.get("offset") if isinstance(next_page, dict) else None
        if not isinstance(offset, str) or not offset or offset in seen:
            raise SyncError("invalid Asana pagination")
        seen.add(offset)
    raise SyncError("Asana project pagination limit reached")


def run_link(repository: str, run_id: str, run_attempt: str) -> str:
    _repository(repository); _identifier(run_id); _identifier(run_attempt)
    return f"https://github.com/{repository}/actions/runs/{run_id}/attempts/{run_attempt}"


def notify_failure(*, repository: str, run_id: str, run_attempt: str, outcome: str,
                   discord_user_id: str, http: AlertHTTP, meta: Meta | None = None,
                   runner: CommandRunner | None = None, app_login: str | None = None) -> dict:
    if outcome not in {"needs-human", "incomplete-verification", "operational-failure"}:
        raise SyncError("invalid failure outcome")
    link = run_link(repository, run_id, run_attempt)
    if meta is not None and meta.pr_number is not None:
        validate_meta(asdict(meta))
        if (repository, run_id, run_attempt) != (meta.repository, meta.run_id, meta.run_attempt):
            raise SyncError("failure context differs from captured metadata")
        pr = check_delivery_pr(github(runner, "GET", f"repos/{repository}/pulls/{meta.pr_number}"), meta, app_login, None)
        state = remember_run(read_state(pr["body"]), meta, outcome)
        body = replace_state_block(pr["body"], state)
        github(runner, "PATCH", f"repos/{repository}/pulls/{meta.pr_number}", {"body": body})
        github(runner, "POST", f"repos/{repository}/issues/{meta.pr_number}/comments", {"body": f"DTL sync {outcome}. [Run and artifacts]({link}). No candidate edits were published by this failure path."})
        return {"outcome": outcome, "run_url": link, "pr_number": meta.pr_number}
    receipt = send_discord(http, discord_user_id, f"DTL sync {outcome}: {repository}\n{link}")
    return {"outcome": outcome, "run_url": link, "discord_message_id": receipt}


def check_delivery_pr(pr: object, meta: Meta, app_login: str, head: str | None) -> dict:
    try:
        valid = (isinstance(pr, dict) and pr["state"] == "open" and pr["user"]["login"] == app_login
                 and pr["base"]["ref"] == "main" and pr["base"]["repo"]["full_name"] == meta.repository
                 and pr["head"]["repo"]["full_name"] == meta.repository and pr["head"]["ref"] == meta.branch
                 and (head is None or pr["head"]["sha"] == head)
                 and (meta.pr_number is None or pr["number"] == meta.pr_number)
                 and type(pr["number"]) is int and pr["number"] > 0 and isinstance(pr["body"], str))
    except (KeyError, TypeError):
        valid = False
    if not valid:
        raise SyncError("stale, closed, or unowned delivery PR")
    return pr


def delivery_pr(runner: CommandRunner, meta: Meta, app_login: str, head: str) -> dict | None:
    if meta.pr_number:
        return check_delivery_pr(github(runner, "GET", f"repos/{meta.repository}/pulls/{meta.pr_number}"), meta, app_login, head)
    # Include closed PRs and unlabeled partial creates, but only for this exact head branch.
    query = urlencode({"state": "all", "head": meta.repository.split('/')[0] + ':' + meta.branch,
                       "base": "main", "per_page": 100})
    pages = github(runner, "GET", f"repos/{meta.repository}/pulls?{query}", paginate=True)
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise SyncError("invalid delivery PR response")
    matches = [pr for page in pages for pr in page]
    if len(matches) > 1:
        raise SyncError("ambiguous delivery PR history")
    return check_delivery_pr(matches[0], meta, app_login, head) if matches else None


def remember_run(state: PublicationState, meta: Meta, outcome: str) -> PublicationState:
    runs = [run for run in state.recent_runs if (run["run_id"], run["run_attempt"]) != (meta.run_id, meta.run_attempt)]
    runs.append({"run_id": meta.run_id, "run_attempt": meta.run_attempt, "outcome": outcome})
    return replace(state, outcome=outcome, recent_runs=runs[-10:])


def replace_state_block(body: str, state: PublicationState) -> str:
    read_state(body)
    before, remaining = body.split(STATE_START, 1)
    _, _, after = remaining.partition(STATE_END)
    result = before + state_block(state) + after
    if len(result.encode()) > MAX_PR_BODY_BYTES:
        raise SyncError("PR body exceeds size limit")
    return result


def deliver_channels(runner: CommandRunner, http: AlertHTTP, meta: Meta, state: PublicationState,
                     save, *, james_login: str, discord_user_id: str, asana_project_gid: str) -> None:
    link = run_link(meta.repository, meta.run_id, meta.run_attempt)
    for target, channels in state.deliveries.items():
        message = f"DTL sync review: {meta.repository} at {target}\nhttps://github.com/{meta.repository}/pull/{meta.pr_number}\n{link}"
        for channel, receipt in list(channels.items()):
            if receipt.status == "delivered":
                continue
            channels[channel] = replace(receipt, status="pending", attempts=receipt.attempts + 1, last_error=None)
            save(state)
            try:
                if channel == "discord":
                    remote_id = send_discord(http, discord_user_id, message)
                elif channel == "asana":
                    remote_id = send_asana(http, asana_project_gid, target, f"DTL sync review: {meta.repository}", message)
                else:
                    response = github(runner, "POST", f"repos/{meta.repository}/issues/{meta.pr_number}/assignees", {"assignees": [james_login]})
                    if not isinstance(response, dict) or not any(user.get("login") == james_login for user in response.get("assignees", [])):
                        raise SyncError("GitHub did not confirm assignment")
                    remote_id = f"{meta.repository}#{meta.pr_number}:{james_login}"
                channels[channel] = replace(channels[channel], status="delivered", remote_id=remote_id)
            except SyncError as error:
                channels[channel] = replace(channels[channel], status="failed", last_error=str(error)[:300])
            # A persistence failure stops the loop: do not lose more receipts.
            save(state)


def deliver_publication(*, meta: Meta, candidate: Candidate, report: object, verification: object,
                        publication: object, checkout: Path, runner: CommandRunner, http: AlertHTTP,
                        app_login: str, james_login: str, discord_user_id: str, asana_project_gid: str,
                        telemetry: dict | None = None, report_artifact_id: str | None = None,
                        resume_comment_id: int | None = None) -> PublicationState:
    validate_meta(asdict(meta)); validate_candidate(asdict(candidate))
    report = validate_report(report, meta)
    verification = validate_verification(verification, meta, candidate)
    fields = {"schema_version", "outcome", "main_sha", "target_sha", "prompt_version", "published_head_sha",
              "candidate_tree", "patch_sha256", "classification", "cause", "verification", "report_sha256"}
    publication = _object(publication, fields, "publication")
    expected = {"main_sha": meta.main_sha, "target_sha": meta.target_sha, "prompt_version": meta.prompt_version,
                "candidate_tree": candidate.candidate_tree, "patch_sha256": candidate.patch_sha256,
                "verification": asdict(verification),
                "report_sha256": hashlib.sha256(json.dumps(asdict(report), sort_keys=True).encode()).hexdigest()}
    if (type(publication["schema_version"]) is not int or publication["schema_version"] != 1
            or publication["outcome"] not in {"pushed", "reconciled", "unchanged"}
            or any(publication[key] != value for key, value in expected.items())):
        raise SyncError("invalid publication receipt bindings")
    head = _sha(publication["published_head_sha"])
    _identifier(discord_user_id); _identifier(asana_project_gid)
    if not re.fullmatch(r"[A-Za-z0-9-]+", james_login):
        raise SyncError("invalid maintainer login")
    origin = _git(runner, checkout, "remote", "get-url", "origin").stdout.strip()
    heads = publication_heads(runner, origin, meta.branch)
    if heads.get("refs/heads/main") != meta.main_sha:
        raise SyncError("stale main before PR delivery")
    if publication["outcome"] == "unchanged" and meta.pr_number is None:
        if head != meta.main_sha:
            raise SyncError("invalid unchanged publication head")
        return new_state()
    if heads.get(f"refs/heads/{meta.branch}") != head:
        raise SyncError("stale branch before PR delivery")
    pr = delivery_pr(runner, meta, app_login, head)
    identity = PublicationIdentity(meta.main_sha, meta.target_sha, head, meta.prompt_version)
    if pr and meta.pr_number is None and read_state(pr["body"]).last_publication != identity:
        raise SyncError("partial-create state does not match captured publication")
    active_meta = replace(meta, pr_number=pr["number"], pr_head_sha=head, mode="update-pr") if pr else meta
    state = read_state(pr["body"]) if pr else new_state()
    state = resolve_questions(runner, active_meta, state, report.design_questions, james_login=james_login) if pr else replace(state, open_questions=list(report.design_questions))
    if resume_comment_id is not None:
        if not _resume_authorized(runner, meta, resume_comment_id, james_login=james_login):
            raise SyncError("resume comment is not authorized for the captured head")
        receipt = {"comment_id": resume_comment_id, "head_sha": meta.pr_head_sha}
        if receipt not in state.accepted_resumes:
            state.accepted_resumes.append(receipt)
    classification, cause = classify(replace(report, design_questions=state.open_questions), candidate, verification, state.open_questions)
    state = replace(remember_run(state, meta, "published"), last_publication=identity,
                    classification=classification, cause=cause,
                    telemetry=telemetry if telemetry is not None else new_state().telemetry,
                    previous_report_artifact=report_artifact_id or state.previous_report_artifact)
    if classification == "needs-design":
        channels = state.deliveries.setdefault(meta.target_sha, {})
        for channel in ("assignment", "discord", "asana"):
            channels.setdefault(channel, Delivery("pending", None, 0, None))
    link = run_link(meta.repository, meta.run_id, meta.run_attempt)
    body = render_pr_body(report, state, link, meta.compare_url, verification)
    if pr is None:
        pr = github(runner, "POST", f"repos/{meta.repository}/pulls",
                    {"title": f"DTL sync: {classification}: {report.summary.splitlines()[0][:120]}",
                     "head": meta.branch, "base": "main", "body": body})
        pr = check_delivery_pr(pr, meta, app_login, head)
        if read_state(pr["body"]) != state:
            raise SyncError("created PR did not retain initial state")
    active_meta = replace(meta, pr_number=pr["number"], pr_head_sha=head, mode="update-pr")
    current_body = pr["body"]
    def save(updated):
        nonlocal current_body
        latest = check_delivery_pr(github(runner, "GET", f"repos/{meta.repository}/pulls/{pr['number']}"), active_meta, app_login, head)
        if latest["body"] != current_body:
            raise SyncError("PR body changed during delivery")
        current_body = render_pr_body(report, updated, link, meta.compare_url, verification)
        github(runner, "PATCH", f"repos/{meta.repository}/pulls/{pr['number']}", {"body": current_body})
    save(state)
    labels = ["dtl-sync"] + (["needs-design"] if classification == "needs-design" else [])
    github(runner, "POST", f"repos/{meta.repository}/issues/{pr['number']}/labels", {"labels": labels})
    if classification != "needs-design" and any(label["name"] == "needs-design" for label in pr.get("labels", [])):
        github(runner, "DELETE", f"repos/{meta.repository}/issues/{pr['number']}/labels/needs-design")
    deliver_channels(runner, http, active_meta, state, save, james_login=james_login,
                     discord_user_id=discord_user_id, asana_project_gid=asana_project_gid)
    return state


def retry_deliveries(*, meta: Meta, runner: CommandRunner, http: AlertHTTP, app_login: str,
                     james_login: str, discord_user_id: str, asana_project_gid: str) -> PublicationState:
    validate_meta(asdict(meta))
    if meta.mode != "retry-alerts":
        raise SyncError("retry requires captured retry-alerts metadata")
    pr = delivery_pr(runner, meta, app_login, meta.pr_head_sha)
    state = read_state(pr["body"])
    if state.last_publication != PublicationIdentity(meta.main_sha, meta.target_sha, meta.pr_head_sha, meta.prompt_version):
        raise SyncError("retry metadata does not match successful publication")
    current_body = pr["body"]
    def save(updated):
        nonlocal current_body
        latest = delivery_pr(runner, meta, app_login, meta.pr_head_sha)
        if latest["body"] != current_body:
            raise SyncError("PR body changed during retry")
        current_body = replace_state_block(current_body, updated)
        github(runner, "PATCH", f"repos/{meta.repository}/pulls/{meta.pr_number}", {"body": current_body})
    # Restore labels if a prior label request failed after body creation/update.
    github(runner, "POST", f"repos/{meta.repository}/issues/{meta.pr_number}/labels",
           {"labels": ["dtl-sync"] + (["needs-design"] if state.classification == "needs-design" else [])})
    if state.classification in {"mechanical", "no-impact"} and any(label["name"] == "needs-design" for label in pr.get("labels", [])):
        github(runner, "DELETE", f"repos/{meta.repository}/issues/{meta.pr_number}/labels/needs-design")
    deliver_channels(runner, http, meta, state, save, james_login=james_login,
                     discord_user_id=discord_user_id, asana_project_gid=asana_project_gid)
    return state

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("detect", help="resolve upstream and PR identities without modifying the checkout")
    command.add_argument("--checkout", type=Path, required=True)
    command.add_argument("--scratch", type=Path, required=True, help="new directory for bare Git fetches")
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--repository", required=True)
    command.add_argument("--app-login", required=True)
    command.add_argument("--run-id", required=True)
    command.add_argument("--run-attempt", default="1")
    command.add_argument("--upstream-ref", default="master")
    command.add_argument("--force", action="store_true")
    command.add_argument("--replay", action="store_true")
    prepare = commands.add_parser("prepare", help="prepare a disposable evaluation checkout or its patch")
    stages = prepare.add_subparsers(dest="stage", required=True)
    inputs = stages.add_parser("inputs")
    patch = stages.add_parser("patch")
    for stage in (inputs, patch):
        stage.add_argument("--meta", type=Path, required=True)
        stage.add_argument("--directory", type=Path, required=True)
        stage.add_argument("--output", type=Path, required=True, help="new artifact directory")
    inputs.add_argument("--checkout", type=Path, required=True, help="source of the parent origin URL")
    inputs.add_argument("--app-login", required=True)
    inputs.add_argument("--previous-report", type=Path)
    inputs.add_argument("--resume-comment-id", type=int)
    verification = commands.add_parser("verify", help="independently reconstruct and measure inside Docker")
    for name in ("meta", "candidate", "patch", "checkout", "directory", "output"):
        verification.add_argument("--" + name, type=Path, required=True)
    verification.add_argument("--image", default="dtl-sync-verifier")
    publisher = commands.add_parser("publish", help="publish validated trees, PR state, or delivery receipts")
    stages = publisher.add_subparsers(dest="stage", required=True)
    publication = stages.add_parser("tree")
    for name in ("meta", "candidate", "patch", "report", "verification", "checkout", "directory", "output"):
        publication.add_argument("--" + name, type=Path, required=True)
    publication.add_argument("--app-login", required=True)
    publication.add_argument("--app-email", required=True)
    publication.add_argument("--james-login")
    delivery = stages.add_parser("deliver")
    retry = stages.add_parser("retry-alerts")
    failure = stages.add_parser("failure")
    for stage in (delivery, retry):
        stage.add_argument("--meta", type=Path, required=True)
        stage.add_argument("--app-login", required=True)
        stage.add_argument("--james-login", required=True)
        stage.add_argument("--asana-project-gid", required=True)
    for stage in (delivery, retry, failure):
        stage.add_argument("--output", type=Path, required=True, help="new artifact directory")
        stage.add_argument("--discord-user-id", required=True)
    for name in ("candidate", "report", "verification", "publication", "checkout"):
        delivery.add_argument("--" + name, type=Path, required=True)
    delivery.add_argument("--telemetry", type=Path)
    delivery.add_argument("--report-artifact-id")
    delivery.add_argument("--resume-comment-id", type=int)
    failure.add_argument("--meta", type=Path)
    failure.add_argument("--app-login")
    failure.add_argument("--repository", required=True)
    failure.add_argument("--run-id", required=True)
    failure.add_argument("--run-attempt", default="1")
    failure.add_argument("--outcome", choices=["needs-human", "incomplete-verification", "operational-failure"], required=True)
    command.add_argument("--james-login")
    inputs.add_argument("--james-login")
    args = parser.parse_args()
    try:
        runner = CommandRunner()
        if args.command == "detect":
            meta = detect(
                checkout=args.checkout, scratch=args.scratch, repository=args.repository,
                app_login=args.app_login, run_id=args.run_id, run_attempt=args.run_attempt,
                upstream_ref=args.upstream_ref, force=args.force, replay=args.replay, runner=runner,
                james_login=args.james_login,
            )
            write_meta(args.output, meta)
            print(meta.mode)
        elif args.command == "publish" and args.stage == "tree":
            result = publish_tree(meta=read_meta(args.meta), candidate=read_candidate(args.candidate),
                patch=args.patch, report=read_publication_artifact(args.report),
                verification=read_publication_artifact(args.verification), checkout=args.checkout,
                directory=args.directory, output=args.output, runner=runner,
                app_login=args.app_login, app_email=args.app_email, james_login=args.james_login)
            print(result["outcome"])
        elif args.command == "publish":
            args.output.mkdir(parents=True)
            http = AlertHTTP(discord_token=os.environ.get("DISCORD_BOT_TOKEN", ""),
                             asana_token=os.environ.get("ASANA_PAT", ""))
            if args.stage == "failure":
                meta = read_meta(args.meta) if args.meta else None
                if meta and meta.pr_number and not args.app_login:
                    raise SyncError("failure with a PR requires --app-login")
                result = notify_failure(repository=args.repository, run_id=args.run_id,
                    run_attempt=args.run_attempt, outcome=args.outcome,
                    discord_user_id=args.discord_user_id, http=http, meta=meta,
                    runner=runner, app_login=args.app_login)
                _write_json(args.output / "failure.json", result)
                print(result["outcome"])
            else:
                common = dict(meta=read_meta(args.meta), runner=runner, http=http,
                              app_login=args.app_login, james_login=args.james_login,
                              discord_user_id=args.discord_user_id, asana_project_gid=args.asana_project_gid)
                if args.stage == "retry-alerts":
                    state = retry_deliveries(**common)
                else:
                    state = deliver_publication(**common, candidate=read_candidate(args.candidate),
                        report=read_publication_artifact(args.report),
                        verification=read_publication_artifact(args.verification),
                        publication=read_publication_artifact(args.publication), checkout=args.checkout,
                        telemetry=read_publication_artifact(args.telemetry) if args.telemetry else None,
                        report_artifact_id=args.report_artifact_id, resume_comment_id=args.resume_comment_id)
                _write_json(args.output / "delivery.json", asdict(state))
                pending = any(receipt.status != "delivered" for channels in state.deliveries.values() for receipt in channels.values())
                print("retry-alerts" if pending else state.outcome)
                return 1 if pending else 0
        elif args.command == "verify":
            candidate = read_candidate(args.candidate)
            result = verify(meta=read_meta(args.meta), candidate=candidate, patch=args.patch,
                            checkout=args.checkout, directory=args.directory, output=args.output,
                            image=args.image, runner=runner)
            if result.reason:
                print(result.reason, file=sys.stderr)
                return 1
            print("complete")
        elif args.stage == "inputs":
            result = prepare_inputs(
                meta=read_meta(args.meta), checkout=args.checkout, directory=args.directory,
                output=args.output, app_login=args.app_login, runner=runner,
                previous_report=args.previous_report, resume_comment_id=args.resume_comment_id,
                james_login=args.james_login,
            )
            print(result["outcome"])
            return 2 if result["outcome"] == "needs-human" else 0
        else:
            candidate = prepare_patch(meta=read_meta(args.meta), directory=args.directory,
                                      output=args.output, runner=runner)
            print(candidate.candidate_tree)
    except (SyncError, OSError) as error:
        message = str(error) if isinstance(error, SyncError) else "file operation failed; check scratch/output paths"
        print(f"dtl-sync: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
