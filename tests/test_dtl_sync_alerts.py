from __future__ import annotations

from dataclasses import asdict
import io
import json
from urllib.error import HTTPError, URLError

import pytest

from dtl_sync_support import load_sync
from test_dtl_sync_prepare import world
from test_dtl_sync_publish import bundle, publish


@pytest.fixture
def sync():
    return load_sync()


class Response(io.BytesIO):

    def __init__(self, data):
        super().__init__(json.dumps(data).encode())


def test_http_retries_are_bounded_and_secret_safe(sync):
    calls = []
    sleeps = []

    def transport(request, timeout):
        calls.append((request, timeout))
        if len(calls) < 3:
            raise HTTPError(request.full_url, 429, 'secret', {'Retry-After': '900'}, None)
        return Response({'id': '123'})
    http = sync.AlertHTTP(discord_token='private-token', asana_token='private-pat', open_request=transport, sleep=sleeps.append)
    assert http.request('discord', 'POST', '/users/@me/channels', {'recipient_id': '12'}) == {'id': '123'}
    assert len(calls) == 3 and all((timeout == 10 for _, timeout in calls))
    assert sleeps == [5, 5]
    assert calls[0][0].get_header('Authorization') == 'Bot private-token'

    def forbidden(request, timeout):
        raise HTTPError(request.full_url, 403, 'private-token', {}, None)
    http.open_request = forbidden
    with pytest.raises(sync.SyncError, match='403') as error:
        http.request('discord', 'POST', '/users/@me/channels', {})
    assert 'private-token' not in str(error.value)
    with pytest.raises(sync.SyncError):
        http.request('discord', 'GET', 'https://evil.test', None)
    with pytest.raises(sync.SyncError):
        http.request('asana', 'GET', '//evil.test', None)


def test_http_redirects_never_forward_authorization(sync):
    from urllib.request import Request
    with pytest.raises(sync.SyncError, match='redirect'):
        sync.NoAlertRedirect().redirect_request(Request('https://discord.com/api/v10/users/@me'), None, 302, 'found', {}, 'https://evil.test')


def test_asana_marker_reuses_paginated_project_task(sync):
    calls = []

    class HTTP:

        def request(self, service, method, path, payload=None):
            calls.append((service, method, path, payload))
            if 'offset=' not in path:
                return {'data': [], 'next_page': {'offset': 'page-two', 'uri': 'https://evil.test'}}
            return {'data': [{'gid': '123', 'notes': 'dtl-sync:' + 'a' * 40}], 'next_page': None}
    assert sync.send_asana(HTTP(), '99', 'a' * 40, 'Review', 'Run URL') == '123'
    assert len(calls) == 2 and all((call[1] == 'GET' for call in calls))
    assert 'evil' not in calls[1][2]


def test_discord_dm_disables_mentions(sync):
    calls = []

    class HTTP:

        def request(self, service, method, path, payload=None):
            calls.append((service, method, path, payload))
            return {'id': '100' if len(calls) == 1 else '200'}
    assert sync.send_discord(HTTP(), '123', 'review @everyone') == '200'
    assert calls[1][3]['allowed_mentions'] == {'parse': []}


class GitHub:

    def __init__(self, sync, meta, head):
        self.sync = sync
        self.meta = meta
        self.head = head
        self.pr = None
        self.comments = []
        self.permissions = {}
        self.writes = []
        self.fail_assignment = False

    def run(self, args, **kwargs):
        import subprocess
        assert args[:3] == ['gh', 'api', '--method']
        method = args[3]
        endpoint = args[4]
        body = json.loads(kwargs['input_text']) if 'input_text' in kwargs and kwargs['input_text'] else None
        if method != 'GET':
            self.writes.append((method, endpoint, body))
        if method == 'GET' and '/collaborators/' in endpoint:
            result = {'permission': self.permissions.get(endpoint.split('/')[-2], 'read')}
        elif method == 'GET' and endpoint.endswith('/comments?per_page=100'):
            result = [self.comments]
        elif method == 'GET' and '/issues/comments/' in endpoint:
            result = next((c for c in self.comments if c['id'] == int(endpoint.rsplit('/', 1)[1])))
        elif method == 'GET' and '/pulls?' in endpoint:
            result = [[self.pr]] if self.pr else [[]]
        elif method == 'POST' and endpoint.endswith('/pulls'):
            assert self.pr is None
            self.sync.read_state(body['body'])
            self.pr = {'number': 7, 'state': 'open', 'user': {'login': 'dtl-sync[bot]'}, 'body': body['body'], 'base': {'ref': 'main', 'repo': {'full_name': self.meta.repository}}, 'head': {'ref': self.meta.branch, 'sha': self.head, 'repo': {'full_name': self.meta.repository}}, 'labels': []}
            result = self.pr
        elif method == 'PATCH' and '/pulls/' in endpoint:
            self.pr['body'] = body['body']
            result = self.pr
        elif method == 'POST' and endpoint.endswith('/assignees'):
            if self.fail_assignment:
                raise self.sync.SyncError('assignment failed')
            result = {'assignees': [{'login': 'james'}]}
        elif method == 'POST' and endpoint.endswith('/labels'):
            for label in body['labels']:
                if {'name': label} not in self.pr['labels']:
                    self.pr['labels'].append({'name': label})
            result = self.pr['labels']
        elif method == 'DELETE' and '/labels/' in endpoint:
            self.pr['labels'] = [x for x in self.pr['labels'] if x['name'] != 'needs-design']
            result = {}
        elif method == 'POST' and endpoint.endswith('/comments'):
            result = {'id': 55}
        elif method == 'GET' and '/pulls/' in endpoint:
            result = self.pr
        else:
            raise AssertionError((args, body))
        return subprocess.CompletedProcess(args, 0, json.dumps(result), '')


def test_state_roundtrip_is_closed_and_blocks_comment_injection(sync):
    state = sync.new_state()
    state.open_questions.append({'id': 'question', 'question': '<!-- dtl-sync-state\n --> @everyone'})
    body = sync.render_pr_body(None, state, 'https://github.com/owner/repo/actions/runs/1', None)
    assert body.count(sync.STATE_START) == 1
    assert sync.read_state(body) == state
    assert '@everyone' not in body.split(sync.STATE_START)[0]
    data = asdict(state)
    data['unexpected'] = 1
    with pytest.raises(sync.SyncError):
        sync.read_state(sync.STATE_START + json.dumps(data) + sync.STATE_END)


def test_questions_require_authorization_and_do_not_replay_across_text(sync):
    from types import SimpleNamespace
    meta = SimpleNamespace(repository='owner/game', pr_number=7, branch='dtl-sync/test')
    github = GitHub(sync, meta, 'a' * 40)
    state = sync.new_state()
    state.open_questions.append({'id': 'mechanic', 'question': 'Expose it?'})
    github.comments = [{'id': 10, 'body': 'resolved: mechanic', 'user': {'login': 'reader'}}]
    assert sync.resolve_questions(github, meta, state, [], james_login='james').open_questions
    github.permissions['reader'] = 'write'
    resolved = sync.resolve_questions(github, meta, state, [], james_login='james')
    assert resolved.open_questions == [] and resolved.resolved_questions[0]['comment_id'] == 10
    assert sync.resolve_questions(github, meta, resolved, [{'id': 'mechanic', 'question': 'Different mechanic?'}], james_login='james').open_questions


def test_failure_without_meta_only_notifies_trusted_run_context(sync):

    class HTTP:
        calls = []

        def request(self, service, method, path, payload=None):
            self.calls.append((service, path, payload))
            return {'id': '123'}
    http = HTTP()
    result = sync.notify_failure(repository='owner/game', run_id='42', run_attempt='2', outcome='operational-failure', discord_user_id='99', http=http)
    assert result['outcome'] == 'operational-failure'
    assert 'target_sha' not in result
    assert 'https://github.com/owner/game/actions/runs/42/attempts/2' in http.calls[-1][2]['content']


class Alerts:

    def __init__(self):
        self.calls = []
        self.fail_asana = True

    def request(self, service, method, path, payload=None):
        self.calls.append((service, method, path, payload))
        if service == 'discord':
            return {'id': '123'}
        if method == 'GET':
            return {'data': [], 'next_page': None}
        if self.fail_asana:
            raise RuntimeError('replace with SyncError in test')
        return {'data': {'gid': '456'}}


def delivery_setup(sync, world):
    values = list(bundle(sync, world))
    values[3]['classification'] = 'needs-design'
    values[3]['cause'] = 'new-feature'
    values[3]['design_questions'] = [{'id': 'expose', 'question': 'Expose the mechanic?'}]
    publication = publish(sync, world, values)
    gh = GitHub(sync, values[0], publication['published_head_sha'])

    class Runner(sync.CommandRunner):

        def run(self, args, **kwargs):
            return gh.run(args, **kwargs) if args[0] == 'gh' else super().run(args, **kwargs)
    return (values, publication, gh, Runner(env=world.env))


def deliver(sync, world, values, publication, runner, http):
    return sync.deliver_publication(meta=values[0], candidate=values[1], report=values[3], verification=asdict(values[4]), publication=publication, checkout=world.parent, runner=runner, http=http, app_login='dtl-sync[bot]', james_login='james', discord_user_id='99', asana_project_gid='88')


def test_first_pr_state_is_atomic_and_delivery_retries_only_failed_channels(sync, world):
    values, publication, gh, runner = delivery_setup(sync, world)

    class HTTP(Alerts):

        def request(self, service, method, path, payload=None):
            if service == 'asana' and method == 'POST' and self.fail_asana:
                self.calls.append((service, method, path, payload))
                raise sync.SyncError('Asana unavailable')
            return super().request(service, method, path, payload)
    http = HTTP()
    result = deliver(sync, world, values, publication, runner, http)
    assert result.outcome == 'published'
    state = sync.read_state(gh.pr['body'])
    target = values[0].target_sha
    assert state.deliveries[target]['discord'].status == 'delivered'
    assert state.deliveries[target]['assignment'].status == 'delivered'
    assert state.deliveries[target]['asana'].status == 'failed'
    assert state.last_publication.published_head_sha == publication['published_head_sha']
    assert {'name': 'needs-design'} in gh.pr['labels']
    creates = [body for method, path, body in gh.writes if method == 'POST' and path.endswith('/pulls')]
    assert len(creates) == 1
    assert sync.read_state(creates[0]['body']).last_publication == state.last_publication
    before = len([c for c in http.calls if c[0] == 'discord'])
    http.fail_asana = False
    deliver(sync, world, values, publication, runner, http)
    assert len([c for c in http.calls if c[0] == 'discord']) == before
    assert len([x for x in gh.writes if x[1].endswith('/assignees')]) == 1
    state = sync.read_state(gh.pr['body'])
    assert state.deliveries[target]['asana'].status == 'delivered'
    assert state.deliveries[target]['asana'].attempts == 2


def test_failure_with_pr_preserves_successful_tuple_and_posts_comment(sync, world):
    values, publication, gh, runner = delivery_setup(sync, world)
    http = Alerts()
    http.fail_asana = False
    deliver(sync, world, values, publication, runner, http)
    before = sync.read_state(gh.pr['body']).last_publication
    meta = sync.replace(values[0], pr_number=7, pr_head_sha=publication['published_head_sha'], mode='update-pr')
    sync.notify_failure(repository=meta.repository, run_id=meta.run_id, run_attempt=meta.run_attempt, outcome='incomplete-verification', discord_user_id='99', http=http, meta=meta, runner=runner, app_login='dtl-sync[bot]')
    after = sync.read_state(gh.pr['body'])
    assert after.last_publication == before and after.outcome == 'incomplete-verification'
    assert any((path.endswith('/comments') for _, path, _ in gh.writes))
    assert {'name': 'needs-design'} in gh.pr['labels']


def test_unlabeled_partial_create_is_reconciled_and_closed_pr_is_refused(sync, world):
    values, publication, gh, runner = delivery_setup(sync, world)
    http = Alerts()
    http.fail_asana = False
    deliver(sync, world, values, publication, runner, http)
    gh.pr['labels'] = []
    deliver(sync, world, values, publication, runner, http)
    assert len([x for x in gh.writes if x[1].endswith('/pulls') and x[0] == 'POST']) == 1
    assert {'name': 'dtl-sync'} in gh.pr['labels']
    gh.pr['state'] = 'closed'
    with pytest.raises(sync.SyncError, match='closed|stale'):
        deliver(sync, world, values, publication, runner, http)


def test_retry_mode_needs_no_candidate_or_report_artifacts(sync, world):
    values, publication, gh, runner = delivery_setup(sync, world)

    class HTTP(Alerts):

        def request(self, service, method, path, payload=None):
            if service == 'asana' and method == 'POST' and self.fail_asana:
                raise sync.SyncError('failed')
            return super().request(service, method, path, payload)
    http = HTTP()
    deliver(sync, world, values, publication, runner, http)
    before = len([c for c in http.calls if c[0] == 'discord'])
    http.fail_asana = False
    meta = sync.replace(values[0], pr_number=7, pr_head_sha=publication['published_head_sha'], mode='retry-alerts')
    state = sync.retry_deliveries(meta=meta, runner=gh, http=http, app_login='dtl-sync[bot]', james_login='james', discord_user_id='99', asana_project_gid='88')
    assert state.deliveries[meta.target_sha]['asana'].status == 'delivered'
    assert len([c for c in http.calls if c[0] == 'discord']) == before


def test_resume_reuses_head_bound_authorization_and_james_override(sync, world):
    meta = world.detect(sync)
    meta = sync.replace(meta, mode='update-pr', pr_number=7, pr_head_sha=world.main)
    gh = GitHub(sync, meta, world.main)
    gh.comments = [{'id': 5, 'body': 'resume-sync ' + world.main, 'user': {'login': 'james'}, 'issue_url': 'https://api.github.com/repos/owner/game/issues/7'}]
    assert sync._resume_authorized(gh, meta, 5, james_login='james')
    assert not sync._resume_authorized(gh, sync.replace(meta, pr_head_sha='a' * 40), 5, james_login='james')


def test_failure_telemetry_and_receipts_are_strict(sync):
    for field, value in [('outcome', 'invented'), ('telemetry', {}), ('accepted_resumes', [{'head_sha': 'bad', 'comment_id': True}])]:
        data = asdict(sync.new_state())
        data[field] = value
        with pytest.raises(sync.SyncError):
            sync.read_state(sync.STATE_START + json.dumps(data) + sync.STATE_END)


def test_authorized_resolution_wakes_a_noop_evaluation(sync, world):
    from test_dtl_sync import state_body
    body = state_body(sync, world)
    state = sync.read_state(body)
    state.open_questions.append({'id': 'expose', 'question': 'Expose it?'})
    world.set_prs([world.pr(body=sync.state_block(state))])
    comment = {'id': 10, 'body': 'resolved: expose', 'user': {'login': 'maintainer'}}
    world.api_responses({'repos/owner/game/issues/7/comments?per_page=100': [[comment]], 'repos/owner/game/collaborators/maintainer/permission': {'permission': 'write'}})
    assert world.detect(sync).mode == 'update-pr'


def test_large_human_body_keeps_complete_machine_state(sync):
    from types import SimpleNamespace
    state = sync.new_state()
    report = SimpleNamespace(summary='Summary', reasoning='Reason', reachability=[{'path': 'p' * 500, 'symbol': 's' * 500, 'reached': False, 'reason': 'r' * 200} for _ in range(100)])
    body = sync.render_pr_body(report, state, 'https://github.com/owner/game/actions/runs/1', None)
    assert len(body.encode()) <= sync.MAX_PR_BODY_BYTES
    assert sync.read_state(body) == state
    assert 'Full report' in body


@pytest.mark.parametrize('failure', ['transport', 'server'])
def test_http_transient_failures_stop_after_three_attempts(sync, failure):
    calls = []

    def transport(request, timeout):
        calls.append(request.full_url)
        if failure == 'transport':
            raise URLError('private-token')
        raise HTTPError(request.full_url, 503, 'private-token', {}, None)
    http = sync.AlertHTTP(discord_token='private-token', asana_token='', open_request=transport, sleep=lambda delay: None)
    with pytest.raises(sync.SyncError) as error:
        http.request('discord', 'POST', '/users/@me/channels', {})
    assert len(calls) == 3
    assert 'private-token' not in str(error.value)


def test_receipt_persistence_failure_stops_further_channels(sync):
    from types import SimpleNamespace
    meta = SimpleNamespace(repository='owner/game', run_id='1', run_attempt='1', pr_number=7)
    state = sync.new_state()
    state.deliveries['a' * 40] = {channel: sync.Delivery('pending', None, 0, None) for channel in ('discord', 'asana')}
    http = Alerts()
    saved = []

    def save(updated):
        saved.append(asdict(updated))
        if len(saved) == 2:
            raise sync.SyncError('could not persist receipt')
    with pytest.raises(sync.SyncError, match='persist'):
        sync.deliver_channels(None, http, meta, state, save, james_login='james', discord_user_id='99', asana_project_gid='88')
    assert all((call[0] == 'discord' for call in http.calls))
    assert saved[0]['deliveries']['a' * 40]['discord']['status'] == 'pending'


def test_failure_cli_requires_only_trusted_notification_context(sync, monkeypatch, tmp_path):
    import sys
    http = Alerts()
    monkeypatch.setattr(sync, 'AlertHTTP', lambda **kwargs: http)
    output = tmp_path / 'failure'
    monkeypatch.setattr(sys, 'argv', ['dtl_sync.py', 'publish', 'failure', '--repository', 'owner/game', '--run-id', '42', '--outcome', 'operational-failure', '--discord-user-id', '99', '--output', str(output)])
    assert sync.main() == 0
    assert json.loads((output / 'failure.json').read_text())['discord_message_id'] == '123'


def test_unlabeled_state_bearing_pr_requires_reconciliation(sync, world):
    from test_dtl_sync import state_body
    pr = world.pr(body=state_body(sync, world))
    pr['labels'] = []
    world.set_prs([pr])
    with pytest.raises(sync.SyncError, match='reconcil'):
        world.detect(sync)


def test_resolved_question_removes_label_only_with_green_evidence(sync, world):
    values = bundle(sync, world)
    publication = publish(sync, world, values)
    gh = GitHub(sync, values[0], publication['published_head_sha'])
    class Runner(sync.CommandRunner):
        def run(self, args, **kwargs):
            return gh.run(args, **kwargs) if args[0] == 'gh' else super().run(args, **kwargs)
    runner = Runner(env=world.env)
    http = Alerts()
    deliver(sync, world, values, publication, runner, http)
    state = sync.read_state(gh.pr['body'])
    state.open_questions.append({'id': 'expose', 'question': 'Expose it?'})
    state = sync.replace(state, classification='needs-design')
    gh.pr['body'] = sync.state_block(state)
    gh.pr['labels'].append({'name': 'needs-design'})
    gh.comments = [{'id': 10, 'body': 'resolved: expose', 'user': {'login': 'james'}}]
    result = deliver(sync, world, values, publication, runner, http)
    assert result.classification == 'mechanical'
    assert result.resolved_questions == [{'id': 'expose', 'question': 'Expose it?', 'comment_id': 10}]
    assert {'name': 'needs-design'} not in gh.pr['labels']
    assert http.calls == []


def test_label_failure_wakes_retry_even_without_pending_alerts(sync, world):
    from test_dtl_sync import state_body
    state = sync.read_state(state_body(sync, world))
    state = sync.replace(state, classification='mechanical', cause='none')
    pr = world.pr(body=sync.state_block(state))
    pr['labels'].append({'name': 'needs-design'})
    world.set_prs([pr])
    meta = world.detect(sync)
    assert meta.mode == 'retry-alerts'
    gh = GitHub(sync, meta, meta.pr_head_sha)
    gh.pr = pr
    sync.retry_deliveries(meta=meta, runner=gh, http=Alerts(), app_login='dtl-sync[bot]',
        james_login='james', discord_user_id='99', asana_project_gid='88')
    assert {'name': 'needs-design'} not in gh.pr['labels']


def test_bot_resolution_comment_cannot_interrupt_human_resolution(sync):
    from types import SimpleNamespace
    meta = SimpleNamespace(repository='owner/game', pr_number=7, branch='dtl-sync/test')
    gh = GitHub(sync, meta, 'a' * 40)
    gh.comments = [{'id': 1, 'body': 'resolved: expose', 'user': {'login': 'stranger[bot]'}},
                   {'id': 2, 'body': 'resolved: expose', 'user': {'login': 'james'}}]
    state = sync.new_state()
    state.open_questions.append({'id': 'expose', 'question': 'Expose it?'})
    resolved = sync.resolve_questions(gh, meta, state, [], james_login='james')
    assert resolved.open_questions == []
    assert resolved.resolved_questions[0]['comment_id'] == 2


def test_alerts_include_review_context_and_retry_from_state(sync, world):
    values, publication, gh, runner = delivery_setup(sync, world)
    http = Alerts()
    http.fail_asana = False
    state = deliver(sync, world, values, publication, runner, http)
    discord = next(call[3]['content'] for call in http.calls if call[0] == 'discord' and '/messages' in call[2])
    notes = next(call[3]['data']['notes'] for call in http.calls if call[0] == 'asana' and call[1] == 'POST')
    for text in (discord, notes):
        assert 'needs-design' in text and 'new-feature' in text
        assert values[3]['summary'] in text
        assert 'expose' in text and 'Expose the mechanic?' in text
        assert 'https://github.com/owner/game/pull/7' in text
    assert values[3]['reasoning'] in notes
    assert state.summary == values[3]['summary']
    assert state.reasoning == values[3]['reasoning']
    state.deliveries[values[0].target_sha]['discord'] = sync.Delivery('failed', None, 1, 'failed')
    state.deliveries[values[0].target_sha]['asana'] = sync.Delivery('failed', None, 1, 'failed')
    gh.pr['body'] = sync.state_block(state)
    http.calls.clear()
    meta = sync.replace(values[0], pr_number=7, pr_head_sha=publication['published_head_sha'], mode='retry-alerts')
    sync.retry_deliveries(meta=meta, runner=gh, http=http, app_login='dtl-sync[bot]',
                         james_login='james', discord_user_id='99', asana_project_gid='88')
    assert next(call[3]['content'] for call in http.calls if '/messages' in call[2]) == discord
    assert next(call[3]['data']['notes'] for call in http.calls if call[0] == 'asana' and call[1] == 'POST') == notes


def test_alert_excerpts_are_bounded_sanitized_and_explicitly_truncated(sync):
    from types import SimpleNamespace
    meta = SimpleNamespace(repository='owner/game', pr_number=7, run_id='1', run_attempt='1')
    state = sync.replace(sync.new_state(), classification='needs-design', cause='new-feature',
                         summary='<summary> @everyone ' + 's' * 480,
                         reasoning='<reason> @everyone ' + 'r' * 1480)
    state.open_questions.extend({'id': f'question-{i}', 'question': '<question> @everyone ' + 'q' * 400}
                                for i in range(6))
    state.deliveries['a' * 40] = {name: sync.Delivery('pending', None, 0, None) for name in ('discord', 'asana')}
    http = Alerts()
    http.fail_asana = False
    sync.deliver_channels(None, http, meta, state, lambda updated: None, james_login='james',
                          discord_user_id='99', asana_project_gid='88')
    message = next(call[3]['content'] for call in http.calls if '/messages' in call[2])
    notes = next(call[3]['data']['notes'] for call in http.calls if call[0] == 'asana' and call[1] == 'POST')
    assert len(message) < 2000
    assert 'Truncated' in message
    for text in (message, notes):
        assert '<summary>' not in text and '@everyone' not in text
        assert '&lt;summary&gt;' in text and '&#64;everyone' in text
        assert 'question-5' not in text
        assert 'q' * 301 not in text
        assert 'https://github.com/owner/game/pull/7' in text
    assert '&lt;reason&gt;' in notes
    assert 'question-4' in notes
    assert 'r' * 1501 not in notes


@pytest.mark.parametrize('field,limit', [('summary', 500), ('reasoning', 1500)])
def test_alert_state_excerpts_are_closed_and_bounded(sync, field, limit):
    state = sync.replace(sync.new_state(), **{field: 'x' * limit})
    assert sync.read_state(sync.state_block(state)) == state
    for value in ('x' * (limit + 1), None, 1):
        data = asdict(state)
        data[field] = value
        with pytest.raises(sync.SyncError):
            sync.read_state(sync.STATE_START + json.dumps(data) + sync.STATE_END)


def test_alert_requests_send_an_explicit_user_agent(sync):
    seen = []

    class Response:
        status = 200

        def read(self, n=None):
            return b'{"id": "1"}'

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def open_request(request, timeout):
        seen.append(request)
        return Response()
    http = sync.AlertHTTP(discord_token='d', asana_token='a', open_request=open_request, sleep=lambda s: None)
    http.request('discord', 'GET', '/users/@me')
    http.request('asana', 'GET', '/users/me')
    for request in seen:
        agent = request.get_header('User-agent')
        assert agent == sync.ALERT_USER_AGENT
        assert 'Python-urllib' not in agent
