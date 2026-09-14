# DTL sync: CI and implementation status

The upstream sync automation is being built in reviewed phases. Currently,
only CI is implemented. Detection, Codex evaluation, independent verification,
PR publication, alerts, and scheduled dispatch are not implemented or enabled.
The intended system is described in the
[upstream sync design](designs/2026-09-10-dtl-upstream-sync.md).

## CI

[ci.yml](../.github/workflows/ci.yml) runs on pull requests targeting `main`
and pushes to `main`. It declares read-only repository permissions, persists
no checkout credentials, and uses pinned action commits. It does not publish
images or request service secrets.

The jobs are:

| Job/check name | Runs | What it checks |
|---|---|---|
| `tests` | PRs and main pushes | Python suite, including parsed workflow invariants |
| `workflow-lint` | PRs and main pushes | actionlint on workflow files |
| `image-smoke` | Every PR | Game image build and headless DTL import |

These are the job names to verify when configuring required status checks;
`ci.yml` is a filename, not a check name. Branch protection and hosted execution
have not been configured or validated by the local implementation work.

The test job initializes submodules, uses Python 3.13.5 and uv 0.12.13, runs
`uv sync`, and sets `PYTHONHASHSEED=0`. PyYAML 6.0.3 is a development dependency
for the structural tests; it is not a game runtime dependency. Workflow `'on'`
keys are quoted so PyYAML's safe loader preserves them as strings.

## Local checks

From an initialized clone, with Python 3.13.5 and uv 0.12.13:

```sh
git submodule update --init
uv sync
PYTHONHASHSEED=0 .venv/bin/python -m pytest -q -n auto
```

If your installed uv is a different version, `uvx --from uv==0.12.13 uv sync`
runs the pinned version without replacing a global installation. `uv.lock` is
local generated state and must not be committed as part of this work.

Install actionlint 1.7.12 into ignored `build/tools/`. On macOS arm64:

```sh
mkdir -p build/tools
curl --fail --silent --show-error --location \
  https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_darwin_arm64.tar.gz \
  --output build/tools/actionlint.tar.gz
echo 'aba9ced2dee8d27fecca3dc7feb1a7f9a52caefa1eb46f3271ea66b6e0e6953f  build/tools/actionlint.tar.gz' | shasum -a 256 --check
# Extract only after the checksum succeeds.
tar -xzf build/tools/actionlint.tar.gz -C build/tools actionlint
build/tools/actionlint
```

The CI workflow contains the corresponding Linux amd64 URL and checksum.
For another platform, verify its archive against the
[actionlint release checksums](https://github.com/rhysd/actionlint/releases/tag/v1.7.12)
before extraction. A successful actionlint run prints nothing and exits zero.

With Docker running, check the existing game image:

```sh
docker build --tag sugarscape-ci --file Dockerfile .
docker run --rm --network none sugarscape-ci python -c \
  "import sys; import coworld.dtl; assert 'tkinter' not in sys.modules"
```

The import smoke catches missing submodule contents that a Docker `COPY` alone
would not detect. It does not certify a complete hosted game or exercise the
future sync service. No CI step pushes the image.

## Later phases

This runbook will grow with implemented commands for dispatch, red PR review,
credential rotation, and week-one operations. Until those phases are complete,
use the design as a proposal, not an operational command reference.
