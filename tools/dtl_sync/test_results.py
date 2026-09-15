"""Collect functional-suite evidence inside the isolated measurement container."""
import json
from pathlib import Path
import sys

import pytest


class Results:
    collected = None

    def pytest_sessionfinish(self, session, exitstatus):
        self.collected = session.testscollected


if __name__ == '__main__':
    sys.path.insert(0, '/workspace')
    sys.path.insert(0, '/workspace/tests')
    results = Results()
    status = pytest.main(['-q', '-n', 'auto', '-ra', '-m', 'not perf', '-p', 'no:cacheprovider',
                          '--junitxml=/tmp/results.xml', '/workspace/tests'], plugins=[results])
    report = Path('/tmp/results.xml')
    payload = report.read_text() if report.exists() and report.stat().st_size <= 1024*1024 else ''
    # xdist performs collection in workers; a normal terminal exit and positive count
    # establish that the master received collection and all worker results.
    print('DTL_SYNC_RESULT=' + json.dumps({'xml': payload, 'collected': results.collected,
        'collection_complete': status in (0, 1) and bool(results.collected)}))
    raise SystemExit(status)
