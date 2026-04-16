---
name: cg.game.leaderboard-gap
description:
  Use when a CoGames player works locally but still needs a rigorous gap analysis against baselines, scrimmage
  references, or current leaderboard contenders before more tuning.
---

# Leaderboard Gap

## Overview

Turn "it still loses" into a concrete gap table. Compare the candidate against the best local baselines and, when
needed, against the current published leaderboard surface using the same mission, steps, seeds, and metrics.

**Announce at start:** "I’m measuring the gap to the best baselines so we know exactly what the player still needs to
close."

## Steps

1. Pick the candidate and reference set. For CogsGuard, that usually means the candidate plus `planky`, `nlanky`,
   `baseline`, and the strongest current scripted control.
2. Run the same gauntlet for all contenders.

```bash
AGENTS=${AGENTS:-role,nlanky,baseline}
OUTDIR=/tmp/cogsguard_gap
./cogames-agents/scripts/benchmark_agents.sh \
  -a "$AGENTS" \
  -e 10 \
  -s 1000 \
  -m arena \
  -o "$OUTDIR"

uv run python cogames-agents/scripts/compare_agents.py "$(ls -dt "$OUTDIR"/* | head -n1)"
```

3. Capture the metrics that actually matter: `aligned.junction.held`, `aligned.junction.gained`, `heart.gained`,
   `heart.lost`, reward, and `action_timeouts`.
4. If the user cares about the live tournament surface, pull the current leaderboard after confirming the active season.

```bash
uv run cogames seasons
uv run cogames leaderboard --season <season>
```

5. Convert the result into a ranked gap table: metric, candidate value, best baseline value, delta, and the likely
   mechanic behind the gap. Prioritize gaps that recur across seeds.

## Quick Reference

| Gap type                  | Typical interpretation                        |
| ------------------------- | --------------------------------------------- |
| Low junctions held        | coordination or conversion failure            |
| High heart gain, low hold | good economy, weak spend timing               |
| High timeouts             | policy latency or pathological decision loops |
| Reward okay, hold bad     | shaping mismatch or wrong objective emphasis  |

## Integration

**Uses:** `cg.game.audit-complete-episode`, `cg.game.profile-complete-episode`

**Called by:** `cg.game.build-player`

**Pairs with:** `cg.game.scrimmage-gauntlet`, `cg.submit`
