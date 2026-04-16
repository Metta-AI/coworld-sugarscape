---
name: cg.game.log-mine-player-design
description:
  Use when improving a CoGames player and there are prior Claude/Codex logs, SSH-accessible machine histories, or
  abandoned experiments that may already contain mechanics insights, leaderboard targets, dead ends, or failure
  hypotheses.
---

# Log-Mine Player Design

## Overview

Mine local and remote agent logs before changing the player. Treat the logs as experiment memory: extract repeated
findings, proved failures, benchmark targets, and scripts worth reusing.

**Announce at start:** "I’m mining Claude and Codex logs across the local machine and SSH hosts first so we reuse prior
player-design work instead of repeating dead ends."

## Steps

1. Scan the shared log surfaces on `localhost`, `titan`, `zephyrus`, and `xpser`.

```bash
set -euo pipefail

KEYWORDS='slanky|glanky|planky|gassy|cogas|leaderboard|scrimmage|instrumented audit|failure mode|profile'

scan_host() {
  local host="$1"
  if [ "$host" = "localhost" ]; then
    rg -n -i "$KEYWORDS" ~/.claude/projects ~/.codex/sessions | sed -n '1,200p' || true
  else
    ssh "$host" "rg -n -i '$KEYWORDS' ~/.claude/projects ~/.codex/sessions | sed -n '1,200p' || true"
  fi
}

for host in localhost titan zephyrus xpser; do
  echo "=== $host ==="
  scan_host "$host"
done
```

2. Open the strongest hits, then bucket them into four outputs: mechanics truths, failure modes, benchmark targets, and
   "do not repeat" experiments.
3. Pull forward the recurring findings into a scratch note before coding. For CogsGuard-style policies, explicitly look
   for role-conversion timing, align/scramble prereqs, target deconfliction, navigation timeout, idle reset, and
   resource-to-junction conversion efficiency.
4. Prefer commands and scripts that already existed in the winning threads. In current CoGames work, that usually means
   `cogames-agents/scripts/run_cogsguard_instrumented_audit.py`, `cogames-agents/scripts/run_cogsguard_rollout.py`,
   `cogames-agents/scripts/run_cogsguard_parity.py`, `cogames-agents/scripts/benchmark_agents.sh`, and
   `cogames-agents/scripts/eval_cogas.sh`.
5. End with a short "working thesis" that the rest of the player-design loop can test. Example thesis: role mix is not
   the main problem; conversion timing, prerequisites, and coordination are.

## Quick Reference

| Goal                | Command / Output                                                 |
| ------------------- | ---------------------------------------------------------------- |
| Find relevant logs  | `rg -n -i "$KEYWORDS" ~/.claude/projects ~/.codex/sessions`      |
| Search remote hosts | `ssh <host> "rg -n -i ... ~/.claude/projects ~/.codex/sessions"` |
| Extract dead ends   | capture failed experiments and disproved hypotheses              |
| Extract winners     | capture scripts, metrics, baselines, and seeds                   |

## Integration

**Uses:** `tr.cogames-command` for command shaping once the good surfaces are known

**Called by:** `cg.game.build-player`

**Pairs with:** `cg.game.map-mechanics`, `cg.game.audit-complete-episode`, `cg.game.leaderboard-gap`
