---
name: cg.game.skill-improvement
description:
  Systematically improve the game creation skills (cg.game.*) by exercising them against test games, identifying where
  they give bad guidance or miss important issues, and updating the skills with lessons learned.
---

# Game Skill Improvement

## Overview

`cg.game.skill-improvement` is a meta-skill that improves the `cg.game` skill suite by running it against test games and
collecting failure modes. The outputs are targeted skill updates that prevent recurring mistakes.

This skill uses two sub-agents: an **implementer** that follows `cg.game.new-game` strictly, and a **reviewer** that
plays the resulting game and provides feedback. The gap between what the skill produces and what the reviewer catches is
the signal for skill improvement.

## When to Use

- After completing a game implementation where skill guidance was wrong or missing.
- Periodically, to validate that skills still match the engine's actual capabilities.
- When the engine gains new primitives (new query types, mutation types, filter types) that skills should reference.
- When multiple game implementations hit the same problem independently.

## Phase 1: Pick a Target Game

Choose a game with known mechanics that stress-test different engine capabilities. Good candidates:

| Game | What it stress-tests |
|------|---------------------|
| Bomberman | Directional propagation, timed objects, visual markers, object removal, spatial occlusion |
| Snake | Growing body (linked objects), self-collision, boundary wrapping |
| Sokoban | Push mechanics (move handler chains), win-state detection, undo |
| Tag | Pursuit/evasion, team switching, role asymmetry |
| Tower defense | Path-following (agent AI), build placement, wave spawning |

The game should be simple enough to implement in one session but complex enough to surface skill gaps. Prefer games
whose mechanics span multiple engine subsystems (events + spatial queries + object lifecycle).

**Rotate games between runs.** Don't repeat the same test games — each run should exercise different mechanics. The table
above is a starting point; any well-known game with clear mechanics works. Previous runs used Tag, Bomberman, Sokoban,
and Pac-Man. Future runs should pick from the remaining candidates or introduce new ones (e.g., Tetris for gravity +
rotation, a cooking game for cooperative resource chains, Capture the Flag for team coordination + spatial objectives).

## Phase 2: Run the Implementer

Launch a sub-agent as the **implementer**. Give it:

1. The current version of `cg.game.new-game` (it must follow the skill strictly — no improvisation).
2. A naturally underspecified game description — the way a real user would ask. "I want to make a bomberman game" or
   "can we build a sokoban puzzle?" Don't pre-specify engine primitives or implementation details, but don't be
   antagonistically vague either. A real user knows what game they want; they just don't know mettagrid internals.
3. No access to this meta-skill or its improvement history.
4. Pointers to reference games and engine config directories so it can self-serve during the capability check.

The implementer follows the skill's phases: design contract, engine capability check, variant decomposition, build loop.

### Interact, don't fire-and-forget

The implementer should ask you design questions during Phase 1. Answer them helpfully, the way a real user would:

- Q: "Should blasts be cross-shaped or circular?" → A: "Cross-shaped, like classic Bomberman."
- Q: "How many agents?" → A: "4, free-for-all."
- Q: "Here's my proposed design contract, does this look right?" → Review it and give real feedback. If it missed
  something important, say so. If the engine mapping looks wrong, flag it.

The goal is to simulate a productive collaboration, not to trick the implementer. You're testing whether the skill
guides the implementer to ask the right questions and reach the right design — not whether it can survive adversarial
inputs. When the implementer proposes something, evaluate it honestly and give corrections where needed.

After the implementer finishes each mechanic, **verify it works**:

1. Run the tests it wrote. If they fail, send the error back and ask for a fix.
2. If no tests exist, that itself is a failure to flag.
3. If the environment supports it, run the game interactively and verify mechanics visually.

Iterate until the game is in a state where the core loop works or you've identified why it doesn't.

### Environment requirements

Running the game and its tests requires a built mettagrid (C++ via Bazel). If the environment cannot build mettagrid,
the implementer and reviewer can only verify Python-level correctness (imports, config structure, API usage). Document
this limitation — code review alone missed gameplay bugs in 3 out of 3 test runs. Prefer environments where the full
build works.

## Phase 3: Run the Reviewer

Launch a second sub-agent as the **reviewer**. Give it:

1. The implementer's game code and tests.
2. Access to run the game interactively (`./tools/run.py <game>.play render=none`) and inspect simulation state.
   If the environment can't build mettagrid, the reviewer should still verify imports, API correctness, and config
   structure — but note that code-only review is insufficient for mechanics verification.
3. A checklist of things to verify:

### Reviewer Checklist

- [ ] **Does the game run?** `./tools/run.py <game>.play` completes without errors.
- [ ] **Are mechanics correct?** Place bombs / move agents / trigger effects and verify they match the design contract.
- [ ] **Are spatial effects correct?** Blast shapes, ranges, occlusion. Do walls block? Do diagonals leak?
- [ ] **Are visual markers present?** If explosions/effects should be visible, do objects appear in `grid_objects()`?
- [ ] **Do objects get cleaned up?** Walk through where destroyed objects were. Can agents pass through?
- [ ] **Is the action space reasonable?** How many vibes/actions? Is the UI usable?
- [ ] **Do tests cover what the player sees?** Are there tests for visual markers, spatial patterns, object removal?
- [ ] **Were any mechanics silently downgraded?** Compare the design contract to the implementation. Did blast radius
      shrink? Did cross-shaped become circular? Did range get reduced?

The reviewer reports findings as a list of **failure modes** — specific places where the skill's guidance led to
incorrect or incomplete implementation.

## Phase 4: Classify Failure Modes

For each failure mode the reviewer found, determine:

1. **Is it game-specific or general?** Only update skills for general issues. "Bomber needs `life=2` for explosion
   markers" is game-specific. "Short-lived markers need `life=N+1` where N is the number of same-tick cleanup events"
   is general.

2. **Which skill phase failed?**
   - Design phase: mechanic wasn't flagged as needing special engine support.
   - Capability check: engine limitation wasn't identified (e.g., `isNear` can't do directional rays).
   - Implementation: correct primitive existed but wasn't used (e.g., used `isNear` instead of `RaycastQuery`).
   - Testing: bug existed but tests didn't catch it (e.g., no test for explosion marker objects).
   - Handoff: implementer claimed it worked without actually verifying (e.g., didn't run the game interactively).

3. **What's the minimal skill text change that prevents it?**
   - A new entry in the Engine Capability Check catalog.
   - A new Common Mechanic Pattern.
   - A new Stop Condition.
   - A correction to an existing pattern (e.g., `life=1` → `life=2`).

## Phase 5: Update Skills

Apply changes to the relevant skills (`cg.game.new-game`, `cg.game.build-game`, etc.). Each change should be:

- **Focused:** One failure mode per change. Don't bundle unrelated fixes.
- **General:** Applies to any game, not just the test game.
- **Actionable:** Tells the implementer what to do, not just what to avoid. "Use `RaycastQuery` for directional
  mechanics" is better than "Be careful with spatial queries."
- **Testable:** Can be verified by re-running the implementer against the same game.

## Phase 6: Validate

1. **Same game:** Re-run Phase 2 with the updated skills against the same target game. Confirm the failure modes from
   Phase 3 don't recur.
2. **Different game:** Run against a different game archetype to check for regressions. The update shouldn't break
   guidance that was correct for other game types.

## Running Multiple Games

For higher-confidence improvements, run 3+ games in parallel and only promote failures that appear in 2+ games. This
avoids overfitting the skill to one game's quirks. A good spread covers different engine subsystems:

| Subsystem | Good test game |
|-----------|---------------|
| Agent-agent interaction, tags | Tag, infection games |
| Timed events, spatial queries, object lifecycle | Bomberman, tower defense |
| Move handler chains, object displacement | Sokoban, push puzzles |
| Cooperative flows, resource chains | Cooking games, assembly lines |

### Cross-game classification

After reviewing all games, build a failure matrix:

- **2+ games hit it → promote to skill update.** These are systematic gaps.
- **1 game only → document but do not promote.** May be a game-specific quirk. Re-evaluate if a future run confirms it.

In a 3-game run (Tag, Bomberman, Sokoban), the following failures appeared across all three:
- No integration tests for the core mechanic (3/3)
- Recipe broken or missing (3/3)
- Game registration not discoverable (2/3)
- No observation config for RL training (2/3) — later found to be a FALSE POSITIVE: the default ObsConfig already
  exposes all inventory resources and tags automatically. The real issue was that the skill text implied explicit
  configuration was needed when it isn't. Corrected in the Pac-Man run.

In the Pac-Man run (4th test game), after the above fixes were applied to the skill:
- Integration tests present and passing (FIXED)
- Game registration correct (FIXED)
- Recipe exists but crashes (`policy_uri="random"` not a valid URI — need `"metta://policy/random"`) (1/1)
- Observation config: the previous "no observation config" finding was WRONG — the default ObsConfig already exposes
  all inventory resources and tags automatically. The real issue is ensuring game state lives in resources (which are
  automatically observable) rather than hidden engine state. The prior skill text incorrectly recommended a nonexistent
  `resource_channels` field. Corrected to document what ObsConfig actually does.
- Recipe missing `train()` function (1/1)
- Mechanics silently downgraded from rules.md without verification (1/1 — 4 dropped mechanics)
- rules.md contained unimplementable conditions (episode termination) that the engine doesn't support (1/1)
- Meta-skill process failure: implementer was fire-and-forget instead of interactive. Design questions were
  pre-answered and mechanics were not verified incrementally. Future runs MUST iterate with the implementer agent.

These became additional skill updates: correct policy URI, mandatory `train()`, episode termination engine limitation
documentation, rules.md compliance verification step, and corrected ObsConfig guidance.

## Principles

- **The reviewer must actually play the game** — inspect `grid_objects()`, check object positions, verify spatial
  patterns. Reading the code is not sufficient. Code says what should happen; simulation shows what actually happens.
- **The implementer must not have access to improvement history** — it uses the current skill version only. This
  ensures the test is honest.
- **Failure modes should be expressed as test-like assertions** where possible — "given a Bomberman design, the skill
  should recommend `RaycastQuery` during capability check" — so skill quality can be tracked over time.
- **Run against multiple game archetypes** to avoid overfitting the skills to one game's quirks. Bomberman tests spatial
  mechanics, a cooking game tests object lifecycle, a combat game tests agent interactions.
- **Prefer catalog entries over warnings.** "Use `RaycastQuery` for directional propagation" (positive, in the
  capability catalog) is more useful than "Don't use `isNear` for directional mechanics" (negative, in a pitfalls
  section). Engineers reach for what they know exists, not what they're warned against.

## Integration

**Uses:** `cg.game.new-game`, `cg.game.build-game`

**Outputs:** Updated skill files with targeted improvements based on empirical failure modes.
