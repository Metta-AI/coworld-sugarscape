"""Detect, prepare, verify, and publish validated DTL candidate trees."""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
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

from dtl_sync_contracts import (
    ALLOWED_DIRECTORIES,
    ALLOWED_FILES,
    Candidate,
    GITLINK_PATH,
    MAX_LOG_BYTES,
    MAX_PATCH_BYTES,
    MAX_REPORT_BYTES,
    Meta,
    PROMPT_PATH,
    PROTECTED_FILES,
    PublicationIdentity,
    Report,
    SyncError,
    TestResult,
    UPSTREAM_URL,
    Verification,
    _identifier,
    _json,
    _repository,
    _sha,
    _write_json,
    classify,
    path_is_allowed,
    path_is_protected,
    read_candidate,
    read_meta,
    read_publication_artifact,
    read_state,
    validate_candidate,
    validate_meta,
    validate_report,
    validate_verification,
    write_meta,
)

from dtl_sync_delivery import (
    AlertHTTP,
    _git,
    _resume_authorized,
    deliver_publication,
    find_sync_pr,
    new_state,
    notify_failure,
    publication_heads,
    resolve_questions,
    retry_deliveries,
)


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
