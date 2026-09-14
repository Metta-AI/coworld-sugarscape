"""Run only the captured main trajectory harness with the independently fetched pin."""
import importlib.util
import json
from pathlib import Path
import sys


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == '__main__':
    root = Path('/workspace')
    load('conftest', root / 'tests/conftest.py')
    harness = load('stock_test', root / 'tests/test_dtl.py')
    measured = harness._trajectory_hash()
    print('DTL_SYNC_RESULT=' + json.dumps({'hash_new': measured}))
