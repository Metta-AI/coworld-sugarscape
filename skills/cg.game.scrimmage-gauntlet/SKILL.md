---
name: cg.game.scrimmage-gauntlet
description:
  Use when a CoGames player needs repeatable local scrimmage gates before upload, especially when the goal is to match
  or exceed leaderboard-relevant baselines without regressions.
---

# Scrimmage Gauntlet

## Overview

Run a repeatable local gauntlet until the candidate meets the bar. The gauntlet should start fast, escalate to
full-episode checks, and stop treating single-seed wins as success.

**Announce at start:** "I’m running the local scrimmage gauntlet now so we only promote players that actually clear the
baseline bar."

## Steps

1. Start with fast iteration, then graduate to the real gate.

```bash
POLICY=${POLICY:-role}
./cogames-agents/scripts/quick_eval.sh "$POLICY" -e 3 -s 500 --seed 42 --json
./cogames-agents/scripts/eval_cogas.sh --policy "$POLICY" --episodes 10 --steps 1000 --mission arena --seed 42
```

2. Add a small seed sweep. A reasonable default is `11 23 42`.
3. Run the candidate alongside trusted baselines, then compare.

```bash
AGENTS=${AGENTS:-role,nlanky,baseline}
OUTDIR=/tmp/cogsguard_gauntlet
./cogames-agents/scripts/benchmark_agents.sh \
  -a "$AGENTS" \
  -e 10 \
  -s 1000 \
  -m arena \
  -o "$OUTDIR"

uv run python cogames-agents/scripts/compare_agents.py "$(ls -dt "$OUTDIR"/* | head -n1)"
```

4. Fail the gauntlet if the candidate regresses on the primary objective, spikes `action_timeouts`, or only wins by a
   narrow single-seed margin.
5. Only after the gauntlet is clean should the policy move to `cg.submit` or a live leaderboard check.

## Quick Reference

| Stage           | Tool                  | Purpose                          |
| --------------- | --------------------- | -------------------------------- |
| Fast loop       | `quick_eval.sh`       | cheap iteration                  |
| Real gate       | `eval_cogas.sh`       | full metric check                |
| Multi-agent run | `benchmark_agents.sh` | compare against baselines        |
| Ranking         | `compare_agents.py`   | inspect deltas                   |
| Promotion       | `cg.submit`           | publish only after local success |

## Integration

**Uses:** `cg.game.leaderboard-gap`

**Called by:** `cg.game.build-player`

**Pairs with:** `cg.submit`, `cg.test`
