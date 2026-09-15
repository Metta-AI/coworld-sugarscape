"""PR state, authorization, and alert delivery for DTL sync."""
from __future__ import annotations

from dataclasses import asdict, replace
import json
import hashlib
from pathlib import Path
import re
import time
import html
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

from dtl_sync_contracts import (
    Candidate,
    Delivery,
    MAX_LOG_BYTES,
    MAX_PR_BODY_BYTES,
    MAX_REPORT_BYTES,
    Meta,
    PublicationIdentity,
    PublicationState,
    Report,
    STATE_END,
    STATE_START,
    SyncError,
    TELEMETRY_FIELDS,
    Verification,
    _branch,
    _identifier,
    _json,
    _object,
    _repository,
    _sha,
    classify,
    read_state,
    validate_artifact_provenance,
    validate_candidate,
    validate_meta,
    validate_report,
    validate_verification,
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dtl_sync import CommandRunner


def _git(runner: CommandRunner, directory: Path, *args: str, check: bool = True, env=None, input_text=None):
    return runner.run(["git", "-C", str(directory), *args], check=check, env=env, input_text=input_text)


def find_sync_pr(runner: CommandRunner, repository: str, app_login: str, *, allow_unlabeled: bool = False) -> dict | None:
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
                        if not isinstance(pr["body"], str) or STATE_START not in pr["body"]:
                            continue
                        if not allow_unlabeled:
                            raise SyncError("unlabeled sync state requires retained-publication reconciliation")
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


def new_state() -> PublicationState:
    telemetry = dict.fromkeys(TELEMETRY_FIELDS)
    telemetry["unavailable_reason"] = "workflow telemetry was not supplied"
    return PublicationState(1, None, {}, [], "noop", None, None, [], None, telemetry, [], [], "", "")


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


ALERT_USER_AGENT = "DiscordBot (https://github.com/Metta-AI/coworld-sugarscape, 1.0) dtl-sync"


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
        # Discord's edge rejects Python's default urllib User-Agent (Cloudflare 1010).
        headers = {"Authorization": token, "Content-Type": "application/json",
                   "User-Agent": ALERT_USER_AGENT}
        request = Request(url, data=None if payload is None else json.dumps(payload).encode(),
                          headers=headers, method=method)
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
                            {"content": truncate_alert(message), "allowed_mentions": {"parse": []}})
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


def truncate_alert(message: str) -> str:
    notice = "\n[Truncated; see PR for full details.]"
    return message if len(message) < 2000 else message[:1999 - len(notice)] + notice


def alert_content(meta: Meta, target: str, state: PublicationState, *, asana: bool) -> str:
    lines = [f"DTL sync review: {meta.repository} at {target}",
             f"https://github.com/{meta.repository}/pull/{meta.pr_number}",
             run_link(meta.repository, meta.run_id, meta.run_attempt),
             f"Classification: {state.classification or 'unavailable'}; cause: {state.cause or 'unavailable'}.",
             "Summary (up to 500 characters): " + public_text(state.summary, 500),
             "Open design questions:"]
    lines += [f"- {public_text(question['id'],100)}: {public_text(question['question'],300)}"
              for question in state.open_questions[:5]] or ["None."]
    if len(state.open_questions) > 5 or any(len(question["question"]) > 300 for question in state.open_questions[:5]):
        lines.append("[Truncated questions; see PR for full details.]")
    if asana:
        lines += ["Reasoning (up to 1500 characters): " + public_text(state.reasoning, 1500)]
    return "\n".join(lines)


def deliver_channels(runner: CommandRunner, http: AlertHTTP, meta: Meta, state: PublicationState,
                     save, *, james_login: str, discord_user_id: str, asana_project_gid: str) -> None:
    for target, channels in state.deliveries.items():
        for channel, receipt in list(channels.items()):
            if receipt.status == "delivered":
                continue
            channels[channel] = replace(receipt, status="pending", attempts=receipt.attempts + 1, last_error=None)
            save(state)
            try:
                if channel == "discord":
                    remote_id = send_discord(http, discord_user_id, alert_content(meta, target, state, asana=False))
                elif channel == "asana":
                    remote_id = send_asana(http, asana_project_gid, target, f"DTL sync review: {meta.repository}",
                                           alert_content(meta, target, state, asana=True))
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
                    summary=report.summary[:500], reasoning=report.reasoning[:1500],
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


def previous_report_identity(runner: CommandRunner, repository: str, artifact_id: str) -> dict:
    _repository(repository)
    _identifier(artifact_id)
    artifact = github(runner, "GET", f"repos/{repository}/actions/artifacts/{artifact_id}")
    try:
        match = re.fullmatch(r"dtl-sync-evaluate-([1-9][0-9]*)-([1-9][0-9]*)", artifact["name"])
        workflow_sha = _sha(artifact["workflow_run"]["head_sha"])
    except (KeyError, TypeError):
        raise SyncError("invalid previous report provenance") from None
    if match is None:
        raise SyncError("previous report is not an evaluation artifact")
    run_id, attempt = match.groups()
    run = github(runner, "GET", f"repos/{repository}/actions/runs/{run_id}/attempts/{attempt}")
    validate_artifact_provenance(artifact, run, producer="evaluate", artifact_id=artifact_id,
        repository=repository, run_id=run_id, run_attempt=attempt, workflow_sha=workflow_sha)
    return {"artifact_id": artifact_id, "run_id": run_id}


def failure_context(runner: CommandRunner, meta: Meta, app_login: str,
                    current_attempt: str, publication: object) -> Meta:
    _identifier(current_attempt)
    if not isinstance(publication, dict) or any(publication.get(key) != getattr(meta, key)
            for key in ("main_sha", "target_sha", "prompt_version")):
        raise SyncError("failure publication context mismatch")
    head = _sha(publication.get("published_head_sha"))
    pr = delivery_pr(runner, meta, app_login, head)
    expected = PublicationIdentity(meta.main_sha, meta.target_sha, head, meta.prompt_version)
    if pr is None or read_state(pr["body"]).last_publication != expected:
        raise SyncError("no matching initial PR publication for failure notification")
    return replace(meta, run_attempt=current_attempt, pr_number=pr["number"],
                   pr_head_sha=head, mode="update-pr")
