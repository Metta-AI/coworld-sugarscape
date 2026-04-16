---
name: cg.game.map-mechanics
description:
  Use when a CoGames player needs a clean mechanics contract before tuning, especially when roles, prerequisites,
  scoring, or intended game phases are partially understood or contradicted by behavior in playtests.
---

# Map Mechanics

## Overview

Do not optimize a player whose mechanics model is fuzzy. Build an explicit contract for how the mission, roles,
resources, structures, and scoring are supposed to work, then verify it against code and observed behavior.

**Announce at start:** "I’m mapping the mechanics contract first so the player logic matches how the game is actually
supposed to work."

## Steps

1. Identify the mission, policy surface, and target metric.

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"
rg -n "GEAR_COSTS|aligned\\.junction|heart\\.gained|heart\\.lost|scramble|align|charger|extractor" \
  cogames-agents packages/cogames
```

2. Write the mechanics contract in a scratch note. At minimum cover: role acquisition costs, align/scramble
   prerequisites, junction ownership semantics, heart/influence spending, intended phase changes, role-conversion
   policy, target ownership rules, and stall recovery rules.
3. Translate the contract into concrete invariants. For CogsGuard this usually includes: no align/scramble without
   required gear and heart, no long-lived unreachable target chase, no idle loop that spans a large fraction of the
   episode, and no team-wide overcommitment to one role.
4. Prove the contract with a traced rollout instead of relying on inspection alone.

```bash
POLICY_URI=${POLICY_URI:-metta://policy/role}
uv run python cogames-agents/scripts/run_cogsguard_rollout.py \
  --steps 300 \
  --agents 10 \
  --seed 42 \
  --policy-uri "$POLICY_URI" \
  --trace-prereqs \
  --trace-roles \
  --trace-role-every 25 \
  --trace-resources \
  --trace-resource-every 25
```

5. If logs and code disagree, trust the code plus observed rollout, then record the mismatch as a design-risk item
   before changing the player.

## Quick Reference

| Output               | What it should answer                                  |
| -------------------- | ------------------------------------------------------ |
| Mechanics contract   | How the mission is supposed to work                    |
| Invariant list       | What must never happen if the player is correct        |
| Phase model          | When roles or goals should change over the episode     |
| Coordination rules   | How agents avoid collisions and target duplication     |
| Stall recovery rules | How the player exits idle or unreachable-target states |

## Integration

**Uses:** `cg.game.log-mine-player-design` for prior findings

**Called by:** `cg.game.build-player`

**Pairs with:** `cg.game.audit-complete-episode`, `cg.game.profile-complete-episode`
