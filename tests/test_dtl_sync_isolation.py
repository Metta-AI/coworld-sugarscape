from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from dtl_sync_support import ROOT, git, load_sync, repository


@pytest.fixture
def docker_image():
    if os.environ.get('DTL_SYNC_CONTAINER') == '1':
        pytest.skip('Docker isolation acceptance runs on the host; measurement containers have no Docker socket')
    sync = load_sync()
    try:
        return sync.verifier_image(sync.CommandRunner(), 'dtl-sync-verifier')
    except sync.SyncError as error:
        if os.environ.get('DTL_SYNC_REQUIRE_DOCKER') == '1':
            pytest.fail(str(error))
        pytest.skip(str(error))


def test_verifier_container_cannot_write_control_files(tmp_path, docker_image):
    sync = load_sync()
    workspace = tmp_path / 'candidate'
    harness = tmp_path / 'harness'
    workspace.mkdir()
    harness.mkdir()
    sentinel = tmp_path / 'controller-sentinel'
    sentinel.write_text('controller owned')
    final = tmp_path / 'verify.json'
    final.write_text('final evidence')
    baseline = tmp_path / 'baseline'
    baseline.mkdir()
    (baseline / 'sentinel').write_text('baseline owned')
    target = harness / 'trusted.txt'
    target.write_text('trusted')
    script = harness / 'attack.py'
    script.write_text('''import json, os
from pathlib import Path
paths = ['/harness/trusted.txt', '/workspace/attempt', '/var/run/docker.sock',
         '/controller-sentinel', '/verify.json', '/baseline/sentinel', ''' + repr(str(sentinel)) + ''']
blocked = []
for path in paths:
    try:
        Path(path).write_text('compromised')
    except OSError:
        blocked.append(path)
Path('/tmp/allowed').write_text('scratch')
print('DTL_SYNC_RESULT=' + json.dumps({'blocked': blocked, 'uid': os.getuid()}))
''')
    before = {file: hashlib.sha256(file.read_bytes()).hexdigest() for file in (sentinel, final, target, script, baseline / 'sentinel')}
    result = sync.container_measurement(runner=sync.CommandRunner(), image=docker_image,
        directory=workspace, harness=harness, command=['attack.py'])
    assert result.returncode == 0, result.stdout
    data = sync.measurement_data(result)
    assert data['uid'] == 65534
    assert len(data['blocked']) == 7
    assert before == {file: hashlib.sha256(file.read_bytes()).hexdigest() for file in before}
    assert not (workspace / 'attempt').exists()


def stock_checkout(tmp_path):
    directory = tmp_path / 'stock'
    repository(directory, 'main')
    for name in ('tests/test_dtl.py', 'tests/conftest.py', 'src/coworld/dtl.py'):
        destination = directory / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    subprocess.run(['git', 'clone', '--no-hardlinks', str(ROOT / 'src/sugarscape'),
                    str(directory / 'src/sugarscape')], check=True, capture_output=True)
    git(directory, 'add', '.')
    git(directory, 'commit', '-m', 'Trusted stock fixture')
    return directory


def test_stock_probe_uses_main_loader_and_harness(tmp_path, docker_image):
    sync = load_sync()
    directory = stock_checkout(tmp_path)
    harness = tmp_path / 'harness'
    harness.mkdir()
    shutil.copyfile(ROOT / 'tools/dtl_sync/probe.py', harness / 'probe.py')
    candidate = tmp_path / 'candidate'
    candidate.mkdir()
    (candidate / 'conftest.py').write_text("raise RuntimeError('must not execute')")
    (candidate / 'dtl.py').write_text("raise RuntimeError('must not execute')")
    result = sync.container_measurement(runner=sync.CommandRunner(), image=docker_image,
        directory=directory, harness=harness, command=['probe.py'])
    assert result.returncode == 0, result.stdout
    assert sync.measurement_data(result)['hash_new'] == '240db84051c7c67f5519653dfcdbfbb4c05f142a437d651993edb1442b4cfbce'


def test_suite_has_project_python_imports_and_executable_scratch(tmp_path, docker_image):
    sync = load_sync()
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'tests').mkdir()
    (workspace / 'support.py').write_text('VALUE = 42\n')
    (workspace / 'tests/test_environment.py').write_text('''from pathlib import Path
import os, subprocess, sys
import support

def test_environment(tmp_path):
    assert support.VALUE == 42
    python = Path('/workspace/.venv/bin/python')
    subprocess.run([str(python), '-c', 'print(42)'], check=True)
    script = tmp_path / 'fake-gh'
    script.write_text('#!' + sys.executable + '\\nprint(42)\\n')
    script.chmod(0o755)
    subprocess.run([str(script)], check=True)
''')
    harness = tmp_path / 'harness'
    harness.mkdir()
    shutil.copyfile(ROOT / 'tools/dtl_sync/test_results.py', harness / 'test_results.py')
    sync.prepare_measurement_environment(workspace)
    result = sync.container_measurement(runner=sync.CommandRunner(), image=docker_image,
        directory=workspace, harness=harness, command=['test_results.py'])
    assert result.returncode == 0, result.stdout
    data = sync.measurement_data(result)
    measured = sync.parse_test_result(data['xml'], result.returncode, data['collected'], data['collection_complete'])
    assert measured.completed and measured.passed == 1
