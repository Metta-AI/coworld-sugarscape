"""Import the unmodified DTL Sugarscape submodule and hook its agent class.

The DTL simulation lives in the git submodule at ``src/sugarscape`` as a flat set
of top-level modules (``agent``, ``cell``, ``environment``, ...) that import each
other by those bare names. Nothing in that directory is patched, so this module
is the only place the wrapper touches upstream import mechanics:

1. The submodule directory is appended to ``sys.path`` (appended, not
   prepended, so coworld modules always win a name collision).
2. The two DTL entry points the wrapper needs are re-exported here.
3. :func:`agent_class` swaps ``agent.Agent`` for the duration of a block. DTL
   constructs agents through that module attribute at every site (initial
   placement, replacements, and ``spawnChild``), so the swap is exact and needs
   no upstream edit.

Bump the pin with ``git -C src/sugarscape checkout <commit>`` followed by
``git add src/sugarscape``; ``tests/test_dtl.py`` guards the stock trajectory.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DTL_ROOT = Path(__file__).resolve().parents[1] / "sugarscape"

if not (DTL_ROOT / "sugarscape.py").is_file():
    raise ImportError(
        f"DTL Sugarscape submodule is not checked out at {DTL_ROOT}; "
        "run `git submodule update --init` in the repository root."
    )

if str(DTL_ROOT) not in sys.path:
    sys.path.append(str(DTL_ROOT))

import agent as agent_module
import condition as condition_module

import sugarscape as sugarscape_module

Agent = agent_module.Agent
Sugarscape = sugarscape_module.Sugarscape
verifyConfiguration = sugarscape_module.verifyConfiguration
verifyRandomSeed = sugarscape_module.verifyRandomSeed


@contextmanager
def agent_class(cls: type[Agent]) -> Iterator[None]:
    """Make DTL construct ``cls`` wherever it would construct ``agent.Agent``."""

    previous = agent_module.Agent
    agent_module.Agent = cls
    try:
        yield
    finally:
        agent_module.Agent = previous


@contextmanager
def disease_classes(
    disease: type[condition_module.Disease], zombie: type[condition_module.ZombieVirus]
) -> Iterator[None]:
    """Scope the two upstream infection factories to the Coworld lifecycle."""

    previous = condition_module.Disease, condition_module.ZombieVirus
    condition_module.Disease, condition_module.ZombieVirus = disease, zombie
    try:
        yield
    finally:
        condition_module.Disease, condition_module.ZombieVirus = previous
