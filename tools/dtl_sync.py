"""Detect and prepare DTL updates without publishing or executing upstream code."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile


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
class DetectionState:
    """State needed by detect; publication will extend this closed contract."""

    schema_version: int
    last_publication: PublicationIdentity | None
    deliveries: dict[str, dict[str, Delivery]]
    open_questions: list[dict[str, str]]


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


def read_state(body: str) -> DetectionState:
    if len(body.encode("utf-8")) > MAX_PR_BODY_BYTES or body.count(STATE_START) != 1:
        raise SyncError("missing, repeated, or oversized sync state")
    text, separator, _ = body.split(STATE_START, 1)[1].partition(STATE_END)
    if not separator:
        raise SyncError("unterminated sync state")
    data = _object(_json(text, MAX_PR_BODY_BYTES, "state"), set(DetectionState.__dataclass_fields__), "state")
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
    return DetectionState(1, identity, parsed, questions)


def _git(runner: CommandRunner, directory: Path, *args: str, check: bool = True, env=None):
    return runner.run(["git", "-C", str(directory), *args], check=check, env=env)


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
                        and pr["head"]["ref"].startswith("dtl-sync/")
                        and any(label["name"] == "dtl-sync" for label in pr["labels"])):
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
    upstream_url: str = UPSTREAM_URL,
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
            mode = "retry-alerts" if pending else "noop"
    elif main_pin == target_sha and not force:
        mode = "noop"
    if mode == "new-pr":
        existing = runner.run(["git", "ls-remote", origin, f"refs/heads/{branch}"]).stdout.strip()
        if existing:
            raise SyncError("generated sync branch already exists; reconcile it before rerunning")
    return validate_meta(asdict(Meta(
        1, repository, run_id, run_attempt, main_sha, main_pin, target_sha, prompt_version,
        pr["number"] if pr else None, pr["head"]["sha"] if pr else None, branch, mode,
        f"{UPSTREAM_URL}/compare/{main_pin}...{target_sha}", force, replay,
    )))


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


def _resume_authorized(runner: CommandRunner, meta: Meta, comment_id: int | None) -> bool:
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
    permission = get(f"repos/{meta.repository}/collaborators/{login}/permission")
    return isinstance(permission, dict) and permission.get("permission") in ("write", "maintain", "admin")


def prepare_inputs(
    *, meta: Meta, checkout: Path, directory: Path, output: Path,
    app_login: str, runner: CommandRunner, upstream_url: str = UPSTREAM_URL,
    previous_report: Path | None = None, resume_comment_id: int | None = None,
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
        if published_head != meta.pr_head_sha and not _resume_authorized(runner, meta, resume_comment_id):
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
    args = parser.parse_args()
    try:
        runner = CommandRunner()
        if args.command == "detect":
            meta = detect(
                checkout=args.checkout, scratch=args.scratch, repository=args.repository,
                app_login=args.app_login, run_id=args.run_id, run_attempt=args.run_attempt,
                upstream_ref=args.upstream_ref, force=args.force, replay=args.replay, runner=runner,
            )
            write_meta(args.output, meta)
            print(meta.mode)
        elif args.stage == "inputs":
            result = prepare_inputs(
                meta=read_meta(args.meta), checkout=args.checkout, directory=args.directory,
                output=args.output, app_login=args.app_login, runner=runner,
                previous_report=args.previous_report, resume_comment_id=args.resume_comment_id,
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
