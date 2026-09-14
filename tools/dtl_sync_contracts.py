"""Closed data contracts and shared validation for DTL sync."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import math


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
    summary: str
    reasoning: str


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
        if path.startswith("/") or "\\" in path or any(part in {"", ".", ".."} for part in (path[:-1] if path.endswith("/") else path).split("/")) or any(ord(c) < 32 for c in path):
            raise SyncError("invalid upstream inventory path")
        _report_text(item["symbol"], 500, "symbol")
        if path.endswith("/") and item["symbol"] != "*":
            raise SyncError("directory inventory symbol must be *")
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


def read_publication_artifact(path: Path) -> object:
    with path.open(encoding="utf-8") as file:
        payload = file.read(MAX_REPORT_BYTES + 1)
    return _json(payload, MAX_REPORT_BYTES, path.name)


OUTCOMES = {"noop", "published", "needs-human", "incomplete-verification", "operational-failure"}
TELEMETRY_FIELDS = {"requested_model", "actual_model", "codex_version", "action_sha",
                    "elapsed_seconds", "token_usage", "unavailable_reason"}


def validate_publication_state_fields(data: dict) -> None:
    for field, limit in (("summary", 500), ("reasoning", 1500)):
        if not isinstance(data[field], str) or len(data[field]) > limit:
            raise SyncError(f"invalid state {field} excerpt")
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


def validate_reachability(entries: list[dict], changed: set[str]) -> None:
    covered = set()
    for entry in entries:
        path = entry["path"]
        matches = {file for file in changed if file.startswith(path)} if path.endswith("/") else {path} & changed
        if not matches or covered & matches:
            raise SyncError("upstream inventory has empty or duplicate coverage")
        covered.update(matches)
    if covered != changed:
        raise SyncError("upstream inventory does not cover the exact changed files")


def validate_artifact_provenance(artifact: object, run: object, *, producer: str,
                                 artifact_id: str, repository: str, run_id: str,
                                 run_attempt: str, workflow_sha: str) -> None:
    _repository(repository)
    for identifier in (artifact_id, run_id, run_attempt):
        _identifier(identifier)
    _sha(workflow_sha)
    if producer not in ("detect", "evaluate", "verify"):
        raise SyncError("invalid artifact producer")
    try:
        valid = (type(artifact["id"]) is int and artifact["id"] == int(artifact_id)
                 and artifact["name"] == f"dtl-sync-{producer}-{run_id}-{run_attempt}"
                 and artifact["expired"] is False
                 and artifact["workflow_run"]["id"] == int(run_id)
                 and artifact["workflow_run"]["head_sha"] == workflow_sha
                 and type(run["id"]) is int and run["id"] == int(run_id)
                 and type(run["run_attempt"]) is int and run["run_attempt"] == int(run_attempt)
                 and run["head_sha"] == workflow_sha and run["head_branch"] == "main"
                 and run["path"] == ".github/workflows/dtl-sync.yml"
                 and run["event"] in ("schedule", "workflow_dispatch")
                 and run["repository"]["full_name"] == repository)
    except (KeyError, TypeError):
        valid = False
    if not valid:
        raise SyncError("artifact provenance mismatch")
