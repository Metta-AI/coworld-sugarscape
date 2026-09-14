from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import tomllib

import pytest
import yaml

from dtl_sync_support import ROOT, load_sync
from test_dtl_sync_prepare import world
from test_dtl_sync_publish import bundle, publish


@pytest.fixture
def sync():
    return load_sync()


def item(path, symbol='*'):
    return {'path': path, 'symbol': symbol, 'reached': False, 'reason': 'Not used by the wrapper.'}


def test_directory_inventory_covers_large_changes_once(sync):
    changed = {f'plots/figure-{n}.py' for n in range(200)} | {'engine.py'}
    sync.validate_reachability([item('plots/'), item('engine.py', 'module')], changed)


@pytest.mark.parametrize('entries', [
    [item('plots/'), item('plots/a.py')],
    [item('plots/'), item('plots/nested/')],
    [item('plots/')],
    [item('plots/'), item('unused/'), item('engine.py')],
    [item('plots/'), item('engine.py'), item('engine.py', 'another')],
    [item('plots/'), item('engine.py'), item('missing.py')],
])
def test_directory_inventory_rejects_overlap_empty_and_missing_coverage(sync, entries):
    with pytest.raises(sync.SyncError, match='inventory'):
        sync.validate_reachability(entries, {'plots/a.py', 'plots/nested/b.py', 'engine.py'})


def test_directory_inventory_requires_wildcard_symbol_and_canonical_path(sync, world):
    meta, _, _, report, _ = bundle(sync, world)
    for path, symbol in [('plots/', 'draw'), ('/', '*'), ('plots//', '*'), ('../plots/', '*')]:
        with pytest.raises(sync.SyncError):
            sync.validate_report({**report, 'reachability': [item(path, symbol)]}, meta)
    assert sync.validate_report({**report, 'reachability': [item('plots/')]}, meta).reachability


def provenance():
    return ({'id': 5, 'name': 'dtl-sync-evaluate-123-2', 'expired': False,
             'workflow_run': {'id': 123, 'head_sha': 'a' * 40}},
            {'id': 123, 'run_attempt': 2, 'head_sha': 'a' * 40, 'head_branch': 'main',
             'path': '.github/workflows/dtl-sync.yml', 'event': 'workflow_dispatch',
             'repository': {'full_name': 'owner/game'}})


def test_artifact_provenance_uses_exact_producer_id_run_attempt_and_revision(sync):
    artifact, run = provenance()
    sync.validate_artifact_provenance(artifact, run, producer='evaluate', artifact_id='5',
        repository='owner/game', run_id='123', run_attempt='2', workflow_sha='a' * 40)
    mutations = [('name', 'dtl-sync-verify-123-2'), ('name', 'dtl-sync-evaluate-123-1'),
                 ('id', 6), ('expired', True), ('workflow_run', {'id': 999, 'head_sha': 'a' * 40})]
    for key, value in mutations:
        with pytest.raises(sync.SyncError, match='provenance'):
            sync.validate_artifact_provenance({**artifact, key: value}, run, producer='evaluate',
                artifact_id='5', repository='owner/game', run_id='123', run_attempt='2', workflow_sha='a' * 40)
    for key, value in [('run_attempt', 1), ('head_sha', 'b'*40), ('head_branch', 'untrusted'),
                       ('path', '.github/workflows/other.yml'), ('event', 'pull_request')]:
        with pytest.raises(sync.SyncError, match='provenance'):
            sync.validate_artifact_provenance(artifact, {**run, key: value}, producer='evaluate',
                artifact_id='5', repository='owner/game', run_id='123', run_attempt='2', workflow_sha='a' * 40)


@pytest.mark.parametrize('mode,detected,evaluated,verified,expected', [
    ('noop', 'success', 'skipped', 'skipped', 'noop'),
    ('retry-alerts', 'success', 'skipped', 'skipped', 'retry-alerts'),
    ('new-pr', 'failure', 'skipped', 'skipped', 'operational-failure'),
    ('new-pr', 'success', 'failure', 'skipped', 'operational-failure'),
    ('new-pr', 'success', 'success', 'failure', 'incomplete-verification'),
    ('new-pr', 'success', 'success', 'success', 'publish'),
    ('update-pr', 'success', 'success', 'success', 'publish'),
])
def test_outcome_routing_skips_unneeded_candidate_artifacts(sync, mode, detected, evaluated, verified, expected):
    assert sync.workflow_route(mode, detected, evaluated, verified, 'ready') == expected
    assert sync.workflow_route('update-pr', 'success', 'failure', 'skipped', 'needs-human') == 'needs-human'


def workflow():
    return yaml.safe_load((ROOT / '.github/workflows/dtl-sync.yml').read_text())


def test_sync_workflow_has_four_trust_separated_jobs():
    data = workflow()
    assert set(data['jobs']) == {'detect', 'evaluate', 'verify', 'publish'}
    assert data['concurrency'] == {'group': 'dtl-upstream-sync', 'cancel-in-progress': False}
    for name, job in data['jobs'].items():
        assert job['runs-on'] == 'ubuntu-24.04'
        assert job['timeout-minutes'] == {'detect': 10, 'evaluate': 30, 'verify': 60, 'publish': 10}[name]
        assert job['permissions']['contents'] == ('write' if name == 'publish' else 'read')
        if name in {'detect', 'verify'}:
            assert 'secrets.' not in str(job)
        if name != 'publish':
            assert 'DTL_SYNC_APP_PRIVATE_KEY' not in str(job)
        for step in job['steps']:
            if step.get('uses', '').startswith('actions/checkout@'):
                assert step['with']['persist-credentials'] is False
                assert step['with']['ref'] in {'${{ github.workflow_sha }}', '${{ needs.detect.outputs.main_sha }}'}


def test_evaluate_executes_no_candidate_code_before_codex():
    steps = workflow()['jobs']['evaluate']['steps']
    codex = next(i for i, s in enumerate(steps) if s.get('uses', '').startswith('openai/codex-action@'))
    prior = '\n'.join(step.get('run', '') for step in steps[:codex])
    assert 'uv sync --project controller' in prior
    assert 'prepare inputs' in prior
    assert 'pytest' not in prior and 'pip install' not in prior
    assert 'working-directory' not in str(steps[:codex])
    action = steps[codex]['with']
    assert action['working-directory'] == '${{ github.workspace }}/candidate'
    assert action['codex-home'] == '${{ github.workspace }}/controller/tools/dtl_sync/codex-home'
    assert 'git commit' not in '\n'.join(step.get('run', '') for step in steps)


def test_sync_action_inputs_match_pinned_contract():
    from test_dtl_sync_workflows import ACTION_PINS
    pins = {**ACTION_PINS,
        'actions/upload-artifact': '043fb46d1a93c77aae656e7c1c64a875d1fc6a0a',
        'actions/download-artifact': '3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c',
        'actions/create-github-app-token': 'bcd2ba49218906704ab6c1aa796996da409d3eb1',
        'openai/codex-action': '86365089eb2b84e0a8fb0717b304f8bdcb13b20e'}
    for job in workflow()['jobs'].values():
        for step in job['steps']:
            if 'uses' in step:
                action, sha = step['uses'].split('@')
                assert pins[action] == sha
    step = next(s for s in workflow()['jobs']['evaluate']['steps'] if s.get('uses', '').startswith('openai/'))
    args = step['with']
    assert args['codex-version'] == '0.154.0'
    assert args['permission-profile'] == ':workspace'
    assert args['safety-strategy'] == 'drop-sudo'
    assert args['effort'] == 'high'
    assert 'sandbox' not in args and 'model' not in args
    assert args['output-schema-file'].endswith('/controller/tools/dtl_sync/REPORT_SCHEMA.json')
    assert args['output-file'].endswith('/evaluation/report.json')


def test_publish_runs_after_failed_or_skipped_dependencies():
    job = workflow()['jobs']['publish']
    assert set(job['needs']) == {'detect', 'evaluate', 'verify'}
    assert 'always()' in job['if']
    steps = job['steps']
    preflight = next(i for i, s in enumerate(steps) if s.get('id') == 'route')
    token = next(i for i, s in enumerate(steps) if s.get('id') == 'app')
    assert preflight < token
    assert 'steps.route.outputs.mode' in steps[token]['if']
    commands = '\n'.join(s.get('run', '') for s in steps)
    for command in ('publish tree', 'publish deliver', 'publish retry-alerts', 'publish failure'):
        assert command in commands
    assert 'gh pr create' not in commands


def test_artifacts_are_downloaded_from_expected_producers():
    for job in workflow()['jobs'].values():
        steps = job['steps']
        for index, step in enumerate(steps):
            if step.get('uses', '').startswith('actions/download-artifact@'):
                inputs = step['with']
                assert 'artifact-ids' in inputs and 'pattern' not in inputs and 'name' not in inputs
                assert inputs['repository'] == '${{ github.repository }}'
                if step.get('id') == 'previous_download':
                    assert inputs['artifact-ids'] == '${{ steps.previous.outputs.artifact_id }}'
                    assert inputs['run-id'] == '${{ steps.previous.outputs.run_id }}'
                    assert any('workflow previous' in earlier.get('run', '') for earlier in steps[:index])
                else:
                    assert inputs['run-id'] == '${{ github.run_id }}'
                    assert 'needs.' in inputs['artifact-ids']
                    assert any('workflow artifact' in earlier.get('run', '') for earlier in steps[:index])
            if step.get('uses', '').startswith('actions/upload-artifact@'):
                assert step['with']['retention-days'] == 30
                assert '${{ github.run_attempt }}' in step['with']['name']
                assert '*' not in step['with']['path']


def test_manual_secret_use_requires_default_branch():
    for job in workflow()['jobs'].values():
        assert "github.ref == 'refs/heads/main'" in job['if']
        assert "github.event.repository.default_branch == 'main'" in job['if']
        assert 'github.workflow_ref' in job['if']


def test_dispatch_exercise_and_invalid_key_are_explicit():
    data = workflow()
    assert data['on']['schedule'] == [{'cron': '0 13 * * *'}]
    inputs = data['on']['workflow_dispatch']['inputs']
    assert set(inputs) == {'upstream_ref', 'force', 'replay', 'exercise', 'test_invalid_key'}
    assert inputs['exercise']['options'] == ['none', 'needs-design']
    for name in ('detect', 'publish'):
        assert "vars.DTL_SYNC_ENABLED == 'true'" in data['jobs'][name]['if']
    assert 'DTL_SYNC_INVALID_OPENAI_API_KEY' in str(data['jobs']['evaluate'])
    assert 'workflow inputs' in str(data['jobs']['detect'])


def test_prompt_schema_and_trusted_config_match_contract():
    prompt = (ROOT/'tools/dtl_sync/PROMPT.md').read_text()
    for required in ('main_pin', 'target_sha', '100', '64 KiB', 'directory', 'symbol',
                     'tests/test_dtl.py', 'tests/conftest.py', 'advisory', 'Do not commit'):
        assert required in prompt
    config = tomllib.loads((ROOT/'tools/dtl_sync/codex-home/config.toml').read_text())
    assert config['approval_policy'] == 'never'
    assert config['web_search'] == 'disabled'
    assert config['project_doc_max_bytes'] == 0
    assert not any(key in config for key in ('mcp_servers', 'hooks', 'model_providers'))
    schema = json.loads((ROOT/'tools/dtl_sync/REPORT_SCHEMA.json').read_text())
    assert schema['properties']['reachability']['maxItems'] == 100
    directory = schema['properties']['reachability']['items']['anyOf'][1]
    assert 'directory' in directory['properties']['path']['description']
    assert directory['properties']['symbol']['enum'] == ['*']


def test_invalid_key_selection_cannot_fall_back_to_working_secret():
    actions = [s for s in workflow()['jobs']['evaluate']['steps'] if s.get('uses', '').startswith('openai/')]
    assert len(actions) == 2
    invalid = next(s for s in actions if s['with']['openai-api-key'] == '${{ secrets.DTL_SYNC_INVALID_OPENAI_API_KEY }}')
    working = next(s for s in actions if s['with']['openai-api-key'] == '${{ secrets.OPENAI_API_KEY }}')
    assert "== 'true'" in invalid['if']
    assert "== 'false'" in working['if']


def test_producer_archives_are_flat_and_download_digest_errors_block_publication():
    for name in ('detect', 'evaluate', 'verify'):
        upload = next(s for s in workflow()['jobs'][name]['steps'] if s.get('uses', '').startswith('actions/upload'))
        paths = upload['with']['path'].splitlines()
        assert len({str(Path(path).parent) for path in paths}) == 1
    route = next(s for s in workflow()['jobs']['publish']['steps'] if s.get('id') == 'route')
    assert 'steps.evaluate_download.outcome' in route['env']['EVALUATE_VALID']
    assert 'steps.verify_download.outcome' in route['env']['VERIFY_VALID']


def test_dispatch_validation_requires_explicit_force_for_invalid_key(sync):
    with pytest.raises(sync.SyncError):
        sync.workflow_inputs('workflow_dispatch', 'false', 'false', 'needs-design', 'true')
    with pytest.raises(sync.SyncError):
        sync.workflow_inputs('schedule', 'true', 'false', 'none', 'true')
    assert sync.workflow_inputs('workflow_dispatch', 'false', 'false', 'needs-design', 'false')['force'] == 'true'
    assert sync.workflow_inputs('workflow_dispatch', 'true', 'false', 'none', 'true')['invalid_key'] == 'true'


def test_preflight_is_read_only_and_reconciles_push_before_delivery(sync, world):
    values = bundle(sync, world)
    meta, candidate, patch, report, evidence = values
    options = dict(meta=meta, candidate=candidate, patch=patch/'candidate.patch',
        report=sync.validate_report(report, meta), verification=asdict(evidence), checkout=world.parent,
        runner=sync.CommandRunner(env=world.env), app_login='dtl-sync[bot]',
        app_email='123+dtl-sync[bot]@users.noreply.github.com', james_login='james',
        upstream_url=str(world.upstream_remote))
    sync.publication_preflight(**options, directory=world.path/'first-preflight')
    assert sync.publication_heads(options['runner'], str(world.origin), meta.branch).get('refs/heads/'+meta.branch) is None
    result = publish(sync, world, values)
    sync.publication_preflight(**options, directory=world.path/'recovery-preflight')
    assert sync.publication_heads(options['runner'], str(world.origin), meta.branch)['refs/heads/'+meta.branch] == result['published_head_sha']


def test_recovery_after_initial_pr_creation_uses_exact_recorded_publication(sync, world):
    from test_dtl_sync_alerts import GitHub, Alerts, deliver
    values = bundle(sync, world)
    result = publish(sync, world, values)
    gh = GitHub(sync, values[0], result['published_head_sha'])
    class Runner(sync.CommandRunner):
        def run(self, args, **kwargs):
            return gh.run(args, **kwargs) if args[0] == 'gh' else super().run(args, **kwargs)
    runner = Runner(env=world.env)
    deliver(sync, world, values, result, runner, Alerts())
    gh.pr['labels'] = []
    sync.publication_preflight(meta=values[0], candidate=values[1], patch=values[2]/'candidate.patch',
        report=sync.validate_report(values[3], values[0]), verification=asdict(values[4]),
        checkout=world.parent, directory=world.path/'partial-pr-preflight', runner=runner,
        app_login='dtl-sync[bot]', app_email='123+dtl-sync[bot]@users.noreply.github.com',
        james_login='james', upstream_url=str(world.upstream_remote))
    assert len([w for w in gh.writes if w[0] == 'POST' and w[1].endswith('/pulls')]) == 1


def test_workflow_reruns_bind_each_producer_attempt():
    data = workflow()
    for name in ('detect', 'evaluate', 'verify'):
        assert data['jobs'][name]['outputs']['run_attempt'] == '${{ github.run_attempt }}'
    for job in data['jobs'].values():
        for step in job['steps']:
            if 'workflow artifact' in step.get('run', ''):
                assert 'PRODUCER_ATTEMPT' in step['env']
                assert '--run-attempt "$PRODUCER_ATTEMPT"' in step['run']


def test_collector_never_uploads_oversized_or_symlinked_agent_output(sync, tmp_path):
    source = tmp_path/'raw'
    source.mkdir()
    (source/'report.json').write_bytes(b'x' * (sync.MAX_REPORT_BYTES + 1))
    (source/'telemetry.json').symlink_to(tmp_path/'outside.json')
    (tmp_path/'outside.json').write_text('private data')
    (source/'prepare.json').write_text('{"outcome":"ready"}')
    (source/'executable.py').write_text('never transfer')
    destination = tmp_path/'artifact'
    with pytest.raises(sync.SyncError, match='artifact'):
        sync.collect_evaluation_artifacts(source, destination)
    assert sorted(p.name for p in destination.iterdir()) == ['prepare.json']


@pytest.mark.parametrize('scenario', ['new', 'update', 'red', 'missing', 'missing-update'])
def test_offline_workflow_routes_and_publishes_with_fake_services(sync, world, scenario):
    from types import SimpleNamespace
    from test_dtl_sync_prepare import add_pr, pr_state
    from test_dtl_sync_alerts import GitHub, Alerts, deliver
    if 'update' in scenario:
        head = add_pr(sync, world, {'src/coworld/prior.py': 'prior adaptation\n'})
    values = list(bundle(sync, world))
    meta = values[0]
    if scenario == 'red':
        values[4] = sync.replace(values[4], hash_changed=True, hash_new='c' * 64)
    evaluation = world.path/'evaluation'
    verification = world.path/'verification'
    evaluation.mkdir()
    verification.mkdir()
    meta_file = world.path/'meta.json'
    sync.write_meta(meta_file, meta)
    if not scenario.startswith('missing'):
        sync._write_json(evaluation/'candidate.json', asdict(values[1]))
        sync._write_json(evaluation/'report.json', values[3])
        sync._write_json(evaluation/'telemetry.json', sync.new_state().telemetry)
        (evaluation/'candidate.patch').write_bytes((values[2]/'candidate.patch').read_bytes())
        sync._write_json(verification/'verify.json', asdict(values[4]))
    gh = GitHub(sync, meta, meta.pr_head_sha or meta.main_sha)
    if meta.pr_number:
        gh.pr = world.pr(head=meta.pr_head_sha, body=pr_state(sync, world, meta.pr_head_sha))
    class Runner(sync.CommandRunner):
        def run(self, args, **kwargs):
            return gh.run(args, **kwargs) if args[0] == 'gh' else super().run(args, **kwargs)
    runner = Runner(env={**world.env, 'GIT_CONFIG_COUNT':'1',
        'GIT_CONFIG_KEY_0': f'url.{world.upstream_remote}.insteadOf', 'GIT_CONFIG_VALUE_0': sync.UPSTREAM_URL})
    args = SimpleNamespace(stage='route', meta_valid='true', meta=meta_file, repository=meta.repository,
        run_id=meta.run_id, run_attempt=meta.run_attempt, main_sha=meta.main_sha, detected='success',
        evaluated='success', verified='success', prepared='ready', evaluate_valid='true', verify_valid='true',
        evaluation=evaluation, verification=verification, checkout=world.parent, directory=world.path/'preflight',
        app_login='dtl-sync[bot]', app_email='123+dtl-sync[bot]@users.noreply.github.com', james_login='james',
        current_attempt='2', notification_meta=world.path/'notification-meta.json')
    routed = sync.run_workflow(args, runner)
    if scenario.startswith('missing'):
        assert routed['mode'] == 'operational-failure'
        assert gh.writes == []
        if meta.pr_number:
            assert sync.read_meta(args.notification_meta).run_attempt == '2'
            assert sync.read_meta(meta_file).run_attempt == meta.run_attempt
        return
    assert routed['mode'] == 'publish'
    assert gh.writes == []
    published = publish(sync, world, values, runner=runner)
    gh.head = published['published_head_sha']
    if gh.pr:
        gh.pr['head']['sha'] = gh.head
    http = Alerts()
    http.fail_asana = False
    delivered = deliver(sync, world, values, published, runner, http)
    assert delivered.last_publication.published_head_sha == gh.head
    assert (delivered.classification == 'needs-design') == (scenario == 'red')
    assert bool(http.calls) == (scenario == 'red')
    world.set_prs([gh.pr])
    following = world.detect(sync)
    assert following.mode == 'noop'
    sync.write_meta(meta_file, following)
    args.evaluated = args.verified = 'skipped'
    writes = len(gh.writes)
    assert sync.run_workflow(args, runner)['mode'] == 'noop'
    assert len(gh.writes) == writes


def test_missing_detection_routes_without_reading_meta_or_candidate(sync, tmp_path):
    from types import SimpleNamespace
    args = SimpleNamespace(stage='route', meta_valid='false')
    class Runner:
        def run(self, *args, **kwargs):
            raise AssertionError('missing metadata must not select external operations')
    assert sync.run_workflow(args, Runner()) == {'mode':'operational-failure','has_pr':'false'}


def test_exercise_overlays_only_report_and_keeps_verifier_evidence(sync, world):
    meta, _, _, report, evidence = bundle(sync, world)
    before = asdict(evidence)
    first = sync.workflow_report(meta, report, 'needs-design')
    second = sync.workflow_report(meta, asdict(first), 'needs-design')
    assert first.classification == 'needs-design'
    assert [q['id'] for q in second.design_questions].count('exercise-needs-design') == 1
    assert asdict(evidence) == before


def test_previous_report_provenance_uses_its_original_run_and_attempt(sync):
    artifact, run = provenance()
    class Runner:
        def run(self, args, **kwargs):
            endpoint = args[4]
            if endpoint.endswith('/artifacts/5'):
                value = artifact
            else:
                assert endpoint.endswith('/runs/123/attempts/2')
                value = run
            return subprocess.CompletedProcess(args, 0, json.dumps(value), '')
    assert sync.previous_report_identity(Runner(), 'owner/game', '5') == {'artifact_id':'5', 'run_id':'123'}
    artifact['expired'] = True
    with pytest.raises(sync.SyncError):
        sync.previous_report_identity(Runner(), 'owner/game', '5')


def test_post_agent_git_commands_disable_executable_hooks():
    env = workflow()['env']
    config = {env[f'GIT_CONFIG_KEY_{i}']:env[f'GIT_CONFIG_VALUE_{i}'] for i in range(int(env['GIT_CONFIG_COUNT']))}
    assert config['core.fsmonitor'] == 'false'
    assert config['core.hooksPath'] == '/dev/null'
    stages = workflow()['jobs']['evaluate']['steps']
    collector = next(i for i, step in enumerate(stages) if 'workflow collect' in step.get('run',''))
    upload = next(i for i, step in enumerate(stages) if step.get('uses','').startswith('actions/upload'))
    assert collector < upload


def test_candidate_has_trusted_venv_for_server_subprocess_tests():
    steps = workflow()['jobs']['evaluate']['steps']
    action = next(i for i, step in enumerate(steps) if step.get('uses', '').startswith('openai/'))
    assert any('ln -s "$GITHUB_WORKSPACE/controller/.venv" candidate/.venv' in step.get('run','') for step in steps[:action])


def test_failure_context_recovers_pr_created_after_detection(sync, world):
    from test_dtl_sync_alerts import delivery_setup, Alerts, deliver
    values, publication, gh, runner = delivery_setup(sync, world)
    http = Alerts()
    http.fail_asana = False
    delivered = deliver(sync, world, values, publication, runner, http)
    recovered = sync.failure_context(runner, values[0], 'dtl-sync[bot]', '2', publication)
    assert recovered.pr_number == 7 and recovered.run_attempt == '2'
    sync.notify_failure(repository=recovered.repository, run_id=recovered.run_id, run_attempt='2',
        outcome='operational-failure', discord_user_id='99', http=http, meta=recovered,
        runner=runner, app_login='dtl-sync[bot]')
    assert sync.read_state(gh.pr['body']).last_publication == delivered.last_publication
    assert sync.read_state(gh.pr['body']).recent_runs[-1]['run_attempt'] == '2'
