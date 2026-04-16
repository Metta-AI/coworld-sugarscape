---
name: cg.game.audit-complete-episode
description:
  Use when a CoGames player needs instrumentation and failure-mode analysis across full episodes rather than short smoke
  tests, especially when local behavior looks plausible but leaderboard metrics stay bad.
---

# Audit Complete Episode

## Overview

Audit complete episodes, not toy windows. The point is to find when the player stalls, wastes resource windows, violates
prereqs, or loses coordination deep into the episode.

**Announce at start:** "I’m running full-episode audits so we can see complete failure windows instead of guessing from
short rollouts."

## Steps

1. Use the existing audit surfaces before inventing new instrumentation.

```bash
POLICY_URI=${POLICY_URI:-metta://policy/role}
POLICY_A=${POLICY_A:-metta://policy/role}
POLICY_B=${POLICY_B:-metta://policy/role_nim}

uv run python cogames-agents/scripts/run_cogsguard_rollout.py \
  --steps 1000 \
  --agents 10 \
  --seed 42 \
  --policy-uri "$POLICY_URI" \
  --trace-prereqs \
  --trace-roles \
  --trace-role-every 50 \
  --trace-resources \
  --trace-resource-every 50

uv run python cogames-agents/scripts/run_cogsguard_instrumented_audit.py \
  --steps 1000 \
  --agents 10 \
  --seed 42 \
  --trace-every 50
```

2. Repeat on a small seed set such as `11 23 42`. A player that only works on one seed is not ready.
3. For each run, extract the first concrete failure window: prerequisite miss, unreachable target chase, idle loop,
   resource window with no adjacent role use, wasted gear conversion, target duplication, or late-episode collapse.
4. If a reference policy exists, compare action mix or movement parity instead of eyeballing traces.

```bash
uv run python cogames-agents/scripts/run_cogsguard_parity.py \
  --steps 1000 \
  --agents 10 \
  --seed 42 \
  --policy-a "$POLICY_A" \
  --policy-b "$POLICY_B"
```

5. Write a short audit conclusion with evidence lines, not vibes. Example: "Agents reached aligner resource windows 19
   times, but only attempted aligned station use twice."

## Quick Reference

| Audit target                  | Signal                                              |
| ----------------------------- | --------------------------------------------------- |
| Prereq violations             | `--trace-prereqs` output                            |
| Role balance drift            | `--trace-roles` output                              |
| Resource window waste         | resource trace + station use counts                 |
| Late-episode collapse         | full 1000-step traces, not 100-200 step smoke tests |
| Behavioral parity vs baseline | `run_cogsguard_parity.py`                           |

## Integration

**Uses:** `cg.game.map-mechanics` for invariants

**Called by:** `cg.game.build-player`

**Pairs with:** `cg.game.profile-complete-episode`, `cg.game.leaderboard-gap`
