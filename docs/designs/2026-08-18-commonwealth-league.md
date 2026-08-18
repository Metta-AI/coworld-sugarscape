# Commonwealth league design

**Status:** Implemented.
**Date:** 2026-08-18
**Decision record:** conversation with James, 2026-08-18. Living document;
update as implementation reveals new information.

**Implementation notes (2026-08-18):** This branch introduced `score_method`
because it was not present at the implementation base; existing distribution
scoring is named `w1-support/1`. Qualifier identity is canonical normalized
SugarLang JSON, not raw WebSocket bytes, and `ruleset_sha256` records that
identity per seat. The existing two-seat distribution certification fixture
remains unchanged: it exercises the shared protocol/server plumbing, while
hosted Commonwealth coverage belongs to Observatory qualifier rounds.

## Problem and goal

The solo and duo ladders are the same game at different seat counts: the
observation varies (drawn world + assigned target distribution) and the policy
*generates* a ruleset conditioned on it. The commonwealth league inverts the
relationship: the policy **is** the ruleset. Every episode presents the same
canonical observation, the policy must return the same canonical ruleset every time, and
the score is not distribution match but the summed wellness of the agents that
survive under that ruleset. The ruleset is a constitution; the score is the
common weal.

## Decisions already made

These were settled explicitly and are not open:

1. **Wellness metric = DTL composite happiness, unmodified.** The known
   degenerate incentives (see *Accepted degeneracies* below) stay in; the
   strategies they induce are themselves informative about the metric.
2. **Per-agent wellness is normalized to [0, 1]** (non-negative). Population
   growth therefore strictly helps; that is accepted.
3. **Per-agent value = mean over the final measurement window**, not a
   final-tick snapshot. Window shortened to **50 ticks** (open to dropping to
   10; see open questions).
4. **Seed is random per episode** (`seed: -1`); the game config is otherwise
   fixed — pinned DTL defaults with the agent mechanics enabled (pollution and
   seasons stay off). No scenario pool.
5. **League signal = target id `wellness.max`**, carried by a new `maximize`
   target kind (add `minimize` alongside for symmetry).
6. League/variant name: **`commonwealth`**.
7. **Determinism is enforced by Observatory qualifier rounds** (3 fresh-process
   episodes, canonical-ruleset-identical submissions required) before a submission becomes an
   active champion — never by re-prompting inside tournament episodes.

## Non-goals

- No changes to solo/duo ladder scoring or scenarios.
- No modification of DTL happiness semantics (including its dead
  `happinessModifier` path and the relative wealth term).
- Multi-seat commonwealth is out of scope now, but nothing here should block
  it: seats already own disjoint agent populations, so per-seat wellness sums
  fall out naturally later.
- No mixing of target kinds within one episode (a duo with one distribution
  seat and one maximize seat is disallowed for now; validation rejects it).

## The wellness metric

DTL composite happiness (`src/sugarscape/agent.py:1014`) is the sum of five
components, recomputed each tick for every living agent (`agent.py:596`) — the
pinned sim already computes everything we need:

| Component | Source | Formula | Range |
|---|---|---|---|
| Health | `agent.py:1017` | +unit healthy, −unit sick | ±unit |
| Conflict | `agent.py:912` | ±unit only on a tick the agent fought (+ if aggression > 1) | ±unit or 0 |
| Social | `agent.py:1100` | `(friends/maxFriends)·2 − 1`, scaled by unit | [−unit, unit] |
| Family | `agent.py:940` | erf of unit-weighted sum over children/mates (alive +1, newborn +1, sick −0.5, dead −1) | (−1, 1) |
| Wealth | `agent.py:1164` | `erf(sugar + spice − meanWealth)` | (−1, 1) |

`happinessUnit` is 1, permanently multiplied by 0.5763 for agents born
depressed (`condition.py:20-31`). The erf-based terms are *not* unit-scaled,
so the composite is bounded by ±(3·unit + 2) ⊆ [−5, 5].

**Normalization:** per-agent wellness `w = (happiness + 5) / 10 ∈ [0, 1]`.
Depressed agents (unit 0.5763) are confined to roughly [0.13, 0.87] — they
cannot reach bliss, which is faithful to the metric.

Provenance note: happiness is a DTL extension (it also powers DTL's
utilitarian `ethics.py`), not part of Epstein & Axtell 1996, whose only
built-in valuation is the movement welfare function.

### Accepted degeneracies (deliberate)

- **Sacrificial pauper:** the wealth term saturates to ~`sign(wealth − mean)`,
  so a left-skewed wealth distribution (a few destitute agents dragging the
  mean below the median) maximizes the population's summed wealth happiness.
- **Population dominance:** with non-negative per-agent wellness, adding an
  agent never hurts, so score ≈ population × mean wellness and fertility is
  the dominant lever.
- **Conflict asymmetry:** under the canonical config (aggression 1), fighting
  only ever subtracts happiness unless disease pushes an agent's aggression
  above 1.

All three are retained intentionally: strategies that exploit them illuminate
the metric.

## Canonical config

Fixed for every commonwealth episode: the pinned DTL defaults
(`src/sugarscape/config.json`, already merged by
`config.load_dtl_defaults()`), plus explicit overrides so that **every agent
mechanic is on**. Under pinned defaults these are already live: reproduction
(fertility 1), trading, lending, friendship (maxFriends 5–10), cultural
tagging/3 tribes, disease (50 environment diseases), combat-capable aggression
(factor 1), bentham decision model. Overrides:

| Key | Pinned default | Canonical override | Why |
|---|---|---|---|
| `seed` | −1 | −1 (unchanged) | fresh seed each episode |
| `seats` | — | 1 | one-player case for now |
| `timesteps` | 1000 | 1000 (unchanged) | |
| `measurement_window` | 100 (coworld default) | 50 | decision 3 |
| `targets` | — | `["wellness.max"]` | league signal |
| `agentDepressionPercentage` | 0 | 0.1 *(open question)* | enable depression |
| `agentReplacements` | 0 | 0 (unchanged — **must stay 0**) | replacements would refill the population and confound survivorship scoring |

Pollution and seasons stay off (decided 2026-08-18): pollution factors remain
0, and seasons are world-geometry variation rather than an agent mechanic.
The exact override set is validated during implementation with a probe run
confirming each happiness component actually takes nonzero values.

## Target schema: `maximize` / `minimize` kinds

Current targets are distribution targets (variable + support + bins + probs;
`docs/TARGETS.md` schema, `targets.parse_target`). Add a `kind` field:

- `kind: "distribution"` — the implicit default; existing targets unchanged.
- `kind: "maximize"` / `"minimize"` — carries `id`, `variable`, `description`;
  **no** support/bins/probs.

Shipped new target: `wellness.max` = maximize `wellness`. The observation
payload is otherwise unchanged — the policy recognizes the league purely from
the target, exactly as policies already recognize their assigned distribution
target. `resolve_seat_targets` is kind-agnostic; episode validation rejects
episodes mixing kinds across seats (non-goal above).

## Measurement

New per-agent measured variable **`wellness`** in `measurement.py`, recorded
each tick of the window like other per-agent variables, but keyed by agent
identity so a per-agent windowed mean is computable:

- Each in-window tick, record `w` for every living agent (keyed by the DTL
  agent's stable id).
- An agent's value = mean of its samples within the window (agents born
  mid-window average over their partial presence).
- **Survivors** = agents alive at the final tick. Only survivors count toward
  the score; an agent dying at t=999 contributes nothing (the survivorship
  cliff is intended).
- Following the existing convention that every variable is measured for every
  episode regardless of targets, per-agent wellness means are also pooled into
  a `[0, 1]` histogram for replays and diagnostics — which incidentally makes
  future *distribution* targets over wellness possible.

## Scoring

New score method **`wellness-sum/1`**, reported via the
`score_method` field introduced for every seat detail and running replay record
by this implementation. The `/1` is the method version suffix; current
distribution scoring is identified as `w1-support/1`. The suffix identifies this
revision of the scoring contract, so a future change to the formula ships as
`wellness-sum/2` and replay tooling can fail closed on unknown identifiers.

```text
score(seat) = Σ over seat agents alive at final tick of mean_window_wellness(agent)
```

- Higher = better, same orientation as `w1-hyperbolic/1` (no platform
  conflict). Unbounded above via population — accepted.
- Extinction naturally scores 0 (no survivors); the existing seat-survival
  rule is subsumed.
- Seat details include diagnostics: survivor count, mean wellness, and mean
  per-component happiness (health/conflict/social/family/wealth) over the
  window — cheap to collect and makes replays and strategy analysis legible.
- `episode.py` branches on target kind: distribution seats keep
  `score_histogram`; maximize-wellness seats use the sum above.

## Determinism enforcement (qualification)

Requirement: for the fixed commonwealth observation the policy must return the
same canonical normalized ruleset every time.

**Mechanism — qualifier rounds before champion acceptance.** Tournament
episodes are untouched: one observation, one action, no re-prompting, no
protocol change. Instead, before a submitted policy is accepted as an active
commonwealth champion, the Observatory runs **3 qualifier episodes** against
the canonical commonwealth config and asserts the submitted rulesets are
canonically identical across all of them; any mismatch rejects the submission. The
Observatory already has a champion-qualification mechanism; wiring the check
into it is platform-side integration, outside this repository.

Each qualifier episode is a fresh policy process, so this is strictly stronger
than in-episode re-prompting: a policy that seeds an RNG once at process start
is self-consistent within one episode but drifts across processes, and fails
qualification.

**Repo-side support:** episode results already record the submitted rulesets;
we additionally surface a `ruleset_sha256` in each seat detail so the qualifier
comparison (and any later offline audit of an active champion's episodes) is a
cheap hash equality rather than a payload diff.

The hash is over compact, sorted-key JSON for the validated normalized ruleset,
including JSON `null` for a null ruleset. It deliberately does not preserve or
compare irrelevant wire whitespace and object-key order.

## Components touched

| Area | Change |
|---|---|
| `coworld_manifest.json` | new `commonwealth` variant (canonical config) and unbounded score schema; the existing two-seat certification fixture remains unchanged |
| `src/coworld/targets.py` | `kind` field, maximize/minimize parsing, `wellness.max` catalog entry |
| `src/coworld/measurement.py` | per-agent-identity wellness recording + windowed means + histogram |
| `src/coworld/scoring.py` | `wellness-sum/1` |
| `src/coworld/episode.py` | kind branch, mixed-kind rejection, `ruleset_sha256` in results |
| `src/coworld/replay.py` + `replay-viewer/` | maximize targets have no distribution overlay; show wellness sum trajectory + component breakdown |
| bundled baseline player | fixed-ruleset special case for `wellness.max` |
| `docs/PROTOCOL.md`, `docs/TARGETS.md`, `README.md` | maximize target kind in observations + `ruleset_sha256` in results, target kind + variable + score method, third league |

No changes to `src/sugarscape/` — happiness is already computed every tick.

## Validation

- Unit tests: normalization bounds (incl. depressed agents), windowed-mean
  bookkeeping across births/deaths, survivor filtering, mixed-kind rejection,
  maximize-target parsing, `ruleset_sha256` presence and stability across
  same-ruleset episodes.
- Probe run on the canonical config verifying every enabled happiness
  component takes nonzero values in practice (the reachability-gate spirit,
  applied to mechanics instead of targets).
- Determinism qualification itself is platform-side (Observatory qualifier
  rounds); repo-side risk is covered by the hash tests above.
- Replay viewer test covers a commonwealth replay end to end.

## Resolved questions

1. `agentDepressionPercentage`: **0.1** (approved 2026-08-18).
2. Measurement window: **50 ticks** (approved 2026-08-18; 10 was considered
   but 50 keeps the spiky family/conflict terms stable).
