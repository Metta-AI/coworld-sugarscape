from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from dtl_sync_support import load_sync, git
from test_dtl_sync_prepare import world, sync, prepare


def artifact(sync, world):
    meta, directory, _, _ = prepare(sync, world)
    (directory / 'README.md').write_text('candidate\n')
    output = world.path / 'patch'
    candidate = sync.prepare_patch(meta=meta, directory=directory, output=output,
                                   runner=sync.CommandRunner())
    return meta, candidate, output


def reconstruct(sync, world, meta, candidate, output):
    return sync.reconstruct_candidate(meta=meta, candidate=candidate,
        patch=output / 'candidate.patch', checkout=world.parent,
        directory=world.path / 'verified', runner=sync.CommandRunner(),
        upstream_url=str(world.upstream_remote))


def test_verify_reconstructs_and_binds_candidate_tree(sync, world):
    meta, candidate, output = artifact(sync, world)
    directory = reconstruct(sync, world, meta, candidate, output)
    assert git(directory, 'write-tree') == candidate.candidate_tree
    assert git(directory / 'src/sugarscape', 'rev-parse', 'HEAD') == meta.target_sha
    assert (directory / 'README.md').read_text() == 'candidate\n'
    assert (directory / '.git').is_dir()
    assert (directory / 'src/sugarscape/.git').is_dir()


@pytest.mark.parametrize('field', ['main_sha', 'target_sha', 'patch_sha256', 'candidate_tree', 'files_changed'])
def test_verify_rejects_wrong_bindings(sync, world, field):
    meta, candidate, output = artifact(sync, world)
    bad = replace(candidate, **{field: [] if field == 'files_changed' else '0' * (64 if field == 'patch_sha256' else 40)})
    with pytest.raises(sync.SyncError):
        reconstruct(sync, world, meta, bad, output)


@pytest.mark.parametrize('path,content,mode', [
    ('tests/test_dtl.py', 'tampered', '100644'),
    ('Dockerfile', 'tampered', '100644'),
    ('src/coworld/link', '/tmp/escape', '120000'),
    ('src/coworld/binary', 'bad\x00data', '100644'),
])
def test_verify_independently_rejects_forbidden_patch(sync, world, path, content, mode):
    meta, candidate, output = artifact(sync, world)
    directory = world.path / 'candidate-1'
    blob = git(directory, 'hash-object', '-w', '--stdin', input_text=content)
    git(directory, 'update-index', '--add', '--cacheinfo', f'{mode},{blob},{path}')
    patch = subprocess.run(['git', '-C', str(directory), 'diff', '--cached', '--binary', meta.main_sha, '--', '.', ':!src/sugarscape'], check=True, capture_output=True, text=True).stdout
    (output / 'candidate.patch').write_text(patch)
    bad = replace(candidate, patch_sha256=hashlib.sha256(patch.encode()).hexdigest(),
                  candidate_tree=git(directory, 'write-tree'))
    with pytest.raises(sync.SyncError):
        reconstruct(sync, world, meta, bad, output)


def xml(tests=3, failures=0, errors=0, skipped=0):
    cases = ['<testcase name="pass"/>'] * (tests - failures - errors - skipped)
    cases += ['<testcase><failure/></testcase>'] * failures
    cases += ['<testcase><error/></testcase>'] * errors
    cases += ['<testcase><skipped/></testcase>'] * skipped
    return f'<testsuites><testsuite tests="{tests}" failures="{failures}" errors="{errors}" skipped="{skipped}">' + ''.join(cases) + '</testsuite></testsuites>'


@pytest.mark.parametrize('status,failed,errors', [(0,0,0),(1,1,0),(1,0,1)])
def test_verify_preserves_completed_red_results(sync, status, failed, errors):
    result = sync.parse_test_result(xml(failures=failed, errors=errors), status, 3, True)
    assert result.completed is True
    assert (result.failed, result.errors, result.exit_code) == (failed, errors, status)


@pytest.mark.parametrize('payload,status,collected,finished', [
    ('', 0, 3, True), ('<testsuites>', 0, 3, True),
    (xml(0), 5, 0, True), (xml(), 1, 3, True),
    (xml(failures=1), 0, 3, True), (xml(), 0, 4, True),
    (xml(), None, 3, True), (xml(), 0, True, True),
    (xml(), 0, 3, False), (xml(), 2, 3, True),
    (xml().replace('tests="3"', 'tests="-1"'), 0, 3, True),
    ('<!DOCTYPE x [<!ENTITY a "x">]>' + xml(), 0, 3, True),
])
def test_verify_unknowns_do_not_become_success(sync, payload, status, collected, finished):
    result = sync.parse_test_result(payload, status, collected, finished)
    assert result.completed is False
    assert result.passed is None
    assert result.reason


class Docker:
    def __init__(self, sync, timeout=False):
        self.sync, self.timeout, self.calls = sync, timeout, []

    def run(self, args, **kwargs):
        self.calls.append(args)
        return subprocess.CompletedProcess(args, 0, 'sha256:' + 'a'*64 + '\n', '')

    def run_bounded(self, args, **kwargs):
        self.calls.append(args)
        if self.timeout:
            raise self.sync.SyncError('measurement timed out')
        return subprocess.CompletedProcess(args, 0, '{"ok": true}\n', '')


def test_verifier_environment_excludes_credentials(sync, tmp_path):
    runner = Docker(sync)
    result = sync.container_measurement(runner=runner, image='sha256:'+'a'*64,
        directory=tmp_path / 'candidate', harness=tmp_path / 'trusted', command=['probe.py'])
    command = next(c for c in runner.calls if c[:2] == ['docker', 'run'])
    for flag in ['--read-only', '--network=none', '--cap-drop=ALL', '--security-opt=no-new-privileges']:
        assert flag in command
    assert '65534:65534' in command
    assert sum('/workspace,readonly' in x for x in command) == 1
    assert sum('/harness,readonly' in x for x in command) == 1
    assert not any('sock' in x or 'TOKEN' in x or 'HOME=' in x for x in command)
    assert result.returncode == 0


def test_verifier_timeout_removes_container(sync, tmp_path):
    runner = Docker(sync, timeout=True)
    with pytest.raises(sync.SyncError, match='timed out'):
        sync.container_measurement(runner=runner, image='sha256:'+'a'*64,
            directory=tmp_path, harness=tmp_path, command=['probe.py'])
    run = next(c for c in runner.calls if c[:2] == ['docker','run'])
    assert ['docker','rm','--force',run[run.index('--name')+1]] in runner.calls


def test_missing_image_fails_with_setup_command(sync):
    class Missing:
        def run(self, *args, **kwargs):
            raise sync.SyncError('missing')
    with pytest.raises(sync.SyncError, match='docker build -f tools/dtl_sync/verify.Dockerfile'):
        sync.verifier_image(Missing(), 'dtl-sync-verifier')


def trusted_assets(world):
    root = Path(__file__).resolve().parents[1]
    for name in ('probe.py', 'test_results.py'):
        (world.parent / 'tools/dtl_sync' / name).write_text((root / 'tools/dtl_sync' / name).read_text())
    (world.parent / 'tests/test_dtl.py').write_text('EXPECTED_TRAJECTORY_HASH = "' + 'a'*64 + '"\n')
    git(world.parent, 'add', '.')
    git(world.parent, 'commit', '-m', 'Trusted verifier assets')
    git(world.parent, 'push', 'origin', 'main')
    world.main = git(world.parent, 'rev-parse', 'HEAD')


@pytest.mark.parametrize('changed,failed', [(False,False),(True,False),(False,True)])
def test_verify_records_main_baseline_separately(sync, world, changed, failed):
    trusted_assets(world)
    meta, candidate, output = artifact(sync, world)
    measured = []
    class Runner(sync.CommandRunner):
        def run(self, args, **kwargs):
            if args[:3] == ['docker','image','inspect']:
                return subprocess.CompletedProcess(args, 0, 'sha256:'+'f'*64, '')
            if args[:2] == ['docker','rm']:
                return subprocess.CompletedProcess(args, 0, '', '')
            return super().run(args, **kwargs)

        def run_bounded(self, args, **kwargs):
            mount = next(arg for arg in args if 'dst=/workspace,' in arg)
            directory = Path(mount.split('src=')[1].split(',dst=')[0])
            measured.append(directory.name)
            if directory.name == 'stock':
                assert (directory / 'README.md').read_text() == 'orientation\n'
                assert git(directory / 'src/sugarscape', 'rev-parse', 'HEAD') == meta.target_sha
                data = {'hash_new': ('b' if changed else 'a')*64}
                status = 0
            else:
                baseline = directory.name == 'baseline'
                assert (directory / 'README.md').read_text() == ('orientation\n' if baseline else 'candidate\n')
                assert git(directory / 'src/sugarscape', 'rev-parse', 'HEAD') == (meta.main_pin if baseline else meta.target_sha)
                status = int(failed and not baseline)
                data = {'xml': xml(failures=status), 'collected': 3, 'collection_complete': True}
            return subprocess.CompletedProcess(args, status, sync.RESULT_PREFIX+json.dumps(data)+'\n', '')
    result = sync.verify(meta=meta, candidate=candidate, patch=output/'candidate.patch',
        checkout=world.parent, directory=world.path/'measurement', output=world.path/'evidence',
        runner=Runner(), upstream_url=str(world.upstream_remote))
    assert measured == ['stock','candidate','baseline']
    assert result.reason is None
    assert result.hash_changed is changed
    assert result.candidate_tests.completed
    assert result.candidate_tests.failed == int(failed)
    assert result.baseline_tests.passed == 3
    assert result.candidate_tree == candidate.candidate_tree
    assert json.loads((world.path/'evidence/verify.json').read_text()) == asdict(result)


def test_verify_writes_incomplete_evidence_when_image_missing(sync, world):
    meta, candidate, output = artifact(sync, world)
    class Missing(sync.CommandRunner):
        def run(self, *args, **kwargs):
            raise sync.SyncError('missing image')
    result = sync.verify(meta=meta, candidate=candidate, patch=output/'candidate.patch',
        checkout=world.parent, directory=world.path/'measurement', output=world.path/'evidence', runner=Missing())
    assert result.hash_changed is None
    assert result.patch_applied is None
    assert result.candidate_tests.completed is False
    assert sync.VERIFIER_SETUP in result.reason
    assert (world.path/'evidence/verify.json').is_file()


def test_bounded_runner_stops_excessive_output_and_timeout(sync):
    import sys
    runner = sync.CommandRunner()
    with pytest.raises(sync.SyncError, match='size limit'):
        runner.run_bounded([sys.executable, '-c', 'import sys; sys.stdout.write("x"*2000000)'])
    with pytest.raises(sync.SyncError, match='timed out'):
        runner.run_bounded([sys.executable, '-c', 'import time; time.sleep(5)'], timeout=0.1)


@pytest.mark.parametrize('payload', [None, {}, 123])
def test_malformed_test_payload_is_unknown(sync, payload):
    assert sync.parse_test_result(payload, 0, 3, True).completed is False


def test_patch_cannot_delete_gitlink(sync, world):
    meta, candidate, output = artifact(sync, world)
    directory = world.path/'candidate-1'
    git(directory, 'update-index', '--force-remove', 'src/sugarscape')
    payload = git(directory,'diff','--cached','--binary',meta.main_sha) + '\n'
    (output/'candidate.patch').write_text(payload)
    candidate = replace(candidate, patch_sha256=hashlib.sha256(payload.encode()).hexdigest())
    with pytest.raises(sync.SyncError):
        reconstruct(sync,world,meta,candidate,output)


def test_candidate_reader_is_closed_and_bounded(sync, world):
    meta, candidate, output = artifact(sync, world)
    assert sync.read_candidate(output/'candidate.json') == candidate
    value = asdict(candidate)
    value['unknown'] = True
    (output/'candidate.json').write_text(json.dumps(value))
    with pytest.raises(sync.SyncError):
        sync.read_candidate(output/'candidate.json')
    (output/'candidate.json').write_text(' '*(sync.MAX_REPORT_BYTES+1))
    with pytest.raises(sync.SyncError, match='size limit'):
        sync.read_candidate(output/'candidate.json')


def test_verify_rejects_binary_patch_encoding_even_for_text(sync, world):
    meta, candidate, output = artifact(sync, world)
    directory = world.path/'candidate-1'
    (directory/'.gitattributes').write_text('README.md -diff\n')
    git(directory,'add','README.md')
    payload = subprocess.run(['git','-C',str(directory),'diff','--cached','--binary','--full-index',meta.main_sha,'--','README.md'], check=True,capture_output=True,text=True).stdout
    assert 'GIT binary patch' in payload
    (output/'candidate.patch').write_text(payload)
    candidate = replace(candidate,patch_sha256=hashlib.sha256(payload.encode()).hexdigest())
    with pytest.raises(sync.SyncError, match='binary'):
        reconstruct(sync,world,meta,candidate,output)
