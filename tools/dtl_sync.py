"""Detect DTL updates using captured Git identities and read-only GitHub queries."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import subprocess
import sys


UPSTREAM_URL = "https://github.com/nkremerh/sugarscape"
GITLINK_PATH = "src/sugarscape"
PROMPT_PATH = "tools/dtl_sync/PROMPT.md"
MAX_REPORT_BYTES = 64 * 1024
MAX_PR_BODY_BYTES = 48 * 1024
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
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                args, cwd=cwd, env=self.env, input=input_text, timeout=timeout,
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
    return DetectionState(1, identity, parsed)


def _git(runner: CommandRunner, directory: Path, *args: str, check: bool = True):
    return runner.run(["git", "-C", str(directory), *args], check=check)


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
    args = parser.parse_args()
    try:
        meta = detect(
            checkout=args.checkout, scratch=args.scratch, repository=args.repository,
            app_login=args.app_login, run_id=args.run_id, run_attempt=args.run_attempt,
            upstream_ref=args.upstream_ref, force=args.force, replay=args.replay,
            runner=CommandRunner(),
        )
        write_meta(args.output, meta)
    except (SyncError, OSError) as error:
        message = str(error) if isinstance(error, SyncError) else "file operation failed; check scratch/output paths"
        print(f"dtl-sync: {message}", file=sys.stderr)
        return 1
    print(meta.mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
