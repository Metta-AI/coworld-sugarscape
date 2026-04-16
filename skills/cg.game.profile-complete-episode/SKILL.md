---
name: cg.game.profile-complete-episode
description:
  Use when a CoGames player needs full-episode profiling or timeout analysis, especially when behavior is plausible but
  action timeouts, repeated scanning, or late-episode stalls may be hiding the real bottleneck.
---

# Profile Complete Episode

## Overview

Profile the same full episodes you audit. The goal is to attribute wasted time to concrete code paths or decision loops,
not to guess from aggregate reward alone.

**Announce at start:** "I’m profiling a complete episode so we can tie timeouts and stalls to specific player code
paths."

## Steps

1. Profile a traced rollout with built-in tooling first.

```bash
POLICY_URI=${POLICY_URI:-metta://policy/role}
uv run python -m cProfile -o /tmp/cogsguard_rollout.prof \
  cogames-agents/scripts/run_cogsguard_rollout.py \
  --steps 1000 \
  --agents 10 \
  --seed 42 \
  --policy-uri "$POLICY_URI" \
  --trace-prereqs \
  --trace-roles \
  --trace-resources

uv run python - <<'PY'
import pstats
p = pstats.Stats("/tmp/cogsguard_rollout.prof")
p.strip_dirs().sort_stats("cumtime").print_stats(40)
PY
```

2. Measure the eval surface too, because bad action latency shows up there.

```bash
./cogames-agents/scripts/eval_cogas.sh --policy "${POLICY:-role}" --episodes 10 --steps 1000 --mission arena --seed 42
```

3. Correlate hotspots with the audit output. Good examples: repeated path recomputation while stuck, over-frequent
   target reselection, expensive structure scans, or excessive coordination bookkeeping that does not improve
   `aligned.junction.held`.
4. Do not chase micro-optimizations before resolving behavioral waste. If the profile says the player spends time
   repeatedly doing the wrong thing, fix the policy logic first.
5. End with one ranked list: top hot paths, top timeout sources, and the smallest likely fix for each.

## Quick Reference

| Question                    | Tool / Signal                            |
| --------------------------- | ---------------------------------------- |
| Where is CPU time going?    | `python -m cProfile` + `pstats`          |
| Are action timeouts rising? | `eval_cogas.sh` summary table            |
| Is time tied to bad logic?  | compare hotspots to audit failure lines  |
| What to fix first?          | highest cumulative time with clear waste |

## Integration

**Uses:** `cg.game.audit-complete-episode`

**Called by:** `cg.game.build-player`

**Pairs with:** `tr.perf-eval-env`, `cg.game.scrimmage-gauntlet`
