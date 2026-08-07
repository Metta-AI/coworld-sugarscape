# Sugarscape v2 — Design

**Status: draft, under active design.** This document records decisions as they
are made and highlights what remains open. Nothing here is frozen until marked
**Decided**.

Each item is tagged:

- **Decided** — settled; change requires revisiting explicitly.
- **Leaning** — a stated preference, not yet committed.
- **Open** — unspecified; listed in [§9 Open questions](#9-open-questions).

Founding context: v2 is our own implementation of Sugarscape, not a port of the
DTL Python model (decision D1 in `what-is-a-coworld.md`). DTL and `archived/v1/`
are reference material for what mechanics exist, not templates. The central
motivation is that player control of agents must be designed in from the start,
with clear gates, rather than retrofitted.

---

## 1. Principles

**P1 — Agent-level control, not population-level control. (Decided)**
Every agent is controlled by a submitted player policy. A single policy may
control more than one agent, but it is invoked *per agent*, with that agent's
context, and makes a decision *for that agent*. A policy can control a
population of agents; it cannot control them *as* a population. There is no
call in the protocol whose subject is "all your agents."

Consequences worth stating:

- The observation given to a policy invocation is scoped to one agent (§7.1).
  A policy does not receive a roster of its agents or their positions.
- The scratchpad memory (§7.2) is the only channel through which a policy
  could coordinate its own agents, and its scope (per-agent vs per-seat) is
  therefore a design decision with teeth — see open question F2.

**P2 — The simulation defines the physics; policies define the behavior.
(Decided)**
Config controls the environment and which mechanics exist (§4). It does not
control how agents behave: no movement rules, no aggression parameters, no
lending rates or durations. Where classic Sugarscape hard-codes a behavioral
rule (M, C, T, S...), v2 exposes a decision to the policy instead. The
exceptions are physics-side parameters of a mechanic — e.g. combat α (§6),
which bounds what combat *yields*, not whether an agent fights.

**P3 — Fixed pool, fixed length, scored at the end. (Decided)**
An episode starts with a fixed set of players, runs for a fixed duration, and
reports a score per player at the end. No persistent world, no drop-in entry.

Rationale (recorded because it forecloses a tempting alternative): a
run-forever world accumulates wealth — through lifetime accumulation and
through inheritance if enabled — so incumbents dominate on tenure rather than
policy quality, and a newly entering policy faces an unfair, uninteresting
test. Age-based die-offs don't fix this. Real life has this property; a
competitive benchmark shouldn't.

## 2. Players, seats, and agents

- **Up to 64 seats. (Decided)** A seat is one submitted policy.
- **A seat may control multiple agents (Decided)**, invoked per-agent per P1.
  E.g. 4 seats × 16 agents each.
- **`total_agents` is config; seat count must divide it. (Decided — A1,
  2026-08-07)** Config declares the total agent count (default 64);
  validation enforces `total_agents % seats == 0`, and each seat starts with
  `total_agents / seats` agents — equal allocation at t=0. This keeps
  density a per-variant/league dial (it drives combat/trade pressure), lets
  the certification fixture run tiny (e.g. 4 agents, 2 seats), and preserves
  the Arena stress range (64 seats = 65 component instances is the stress
  case; 4 seats is the gentle case).
- **Newborn assignment: configurable. (Decided — A2, 2026-08-07)** When
  mating creates an agent, the controlling seat is chosen per the config
  option `newborn_assignment`:

  | mode | child goes to |
  |---|---|
  | `random_parent` | one of the two parents' seats, episode-seeded 50/50 |
  | `initiating_parent` | the seat whose agent initiated the mating |
  | `receiving_parent` | the seat whose agent was initiated to (closer to human mating dynamics — offspring stays with the receiving parent) |

  Ranked default: `random_parent` (settled with B5, 2026-08-07 — under the
  `sum` reduce a child is upside for whichever seat receives it, so the
  neutral 50/50 keeps E5's negotiation symmetric). Note the incentive
  asymmetry:
  `initiating_parent`/`receiving_parent` make the two sides of E5's
  negotiation structurally different; that is now a *variant design* lever
  rather than a flaw. Equal allocation remains a t=0 property; mating
  creates deliberate compute/score asymmetry over time (§8.1).
- **Dropped seats: agents freeze. (Decided — A3, 2026-08-07)** When a seat
  faults (Arena drops it permanently; the WS shell mirrors the same rule),
  its agents act in no phase from then on. Physics continues — they
  metabolize, age, starve, and die per D2, and other agents may exploit
  them (combat targets, occupied cells). No sim-owned fallback behavior:
  a frozen agent is indistinguishable from one whose policy legally chooses
  inaction every phase (P2; kills v1's `candidates[0]` fallback for good).
  The platform separately records the fault (`SeatFault`,
  `failed_policy_index`); the freeze rule is only the in-world consequence.

## 3. Scoring

- **Per-agent wellness = Cobb–Douglas welfare. (Decided)** Established in the
  field; grounds an agent's welfare in its own metabolisms for the resources
  (an agent that needs more spice weighs spice more). **Exponents decided
  (B4, 2026-08-07): metabolism shares, the classic form** — for holdings w᛬
  and metabolisms m᛬, `welfare = Π wᵣ^(mᵣ/mT)`, `mT = Σ mᵣ`. Whether
  holdings are gross or net of loan principal is deferred into E6 (lending
  design) — E6 now owns a scoring-critical sub-decision: under integrated
  scoring with a known episode end, gross holdings make endgame
  borrow-and-hold free welfare unless E6 counters it.
- **Wellness is time-integrated over the episode. (Decided — B2+B3,
  2026-08-07)** An agent's wellness = Σ per-tick Cobb–Douglas welfare over
  the episode ÷ T (episode length, not ticks-alive); ticks after death
  contribute 0, and **dead agents remain in the reduce** with their
  truncated integrals. Consequences, which are the reason for the choice:
  death costs proportionally to how early it happens (no `min` cliff, no
  one-death-zeroes-everything); dying rich early doesn't pay (the integral
  stops — normalizing by ticks-alive would resurrect that exploit, hence
  ÷T); culling weak agents doesn't pay (they stay in the reduce); newborns
  (A2) integrate naturally with a bounded contribution. Resolves the §8.2
  tension. Implementation: one running welfare sum per agent; observation
  (§7.1) should expose both current-tick welfare and the running integral
  so policies can see the quantity being optimized; results/replays can
  carry per-tick welfare curves.
- **Per-player score = a configurable reduce over the wellness of the
  policy's agents. (Decided)** The config names a reduce function; the game
  applies it to the wellness scores of all agents the policy controlled:

  | `score_reduce` | meaning |
  |---|---|
  | `sum` | total across agents — **ranked default (B5, 2026-08-07)** |
  | `max` | best single agent |
  | `min` | worst single agent |
  | `median` | middle agent |
  | `mean` | arithmetic mean |
  | `geometric_mean` | geometric mean |

  **Ranked default: `sum` (Decided — B5, 2026-08-07)** — total integrated
  welfare of every agent the seat controlled, ÷ T. The one reduce under
  which survival, prosperity, *and* reproduction all point the same way: a
  child is worth the welfare it goes on to accrue, death is its own
  penalty, culling never pays. Bounded by carrying capacity (the map can
  only sustain so many agents), which caps the total-utilitarian failure
  mode. `mean` remains the variant lever for leagues that want wealth
  strategy without population growth (it structurally punishes mating —
  late-born agents dilute the average). Rider settled with it: ranked
  `newborn_assignment` default = `random_parent` (keeps E5's negotiation
  symmetric; the directional modes are variant levers).
- ~~**Dead agents' contribution: Open — and load-bearing.**~~ Resolved by
  the integrated-wellness decision above (B2+B3).
- **Ties: broken by surviving agent count, then draw. (Decided — B6,
  2026-08-07)** Equal integrals → the seat with more agents alive at
  episode end ranks higher; still equal → a genuine draw (the platform's
  all-pairs Elo scores draws 0.5/0.5 natively). Implementation note: the
  platform ranks on the single `results.scores` scalar, so the survivor
  tie-break must be encoded lexicographically into the score value (e.g.
  survivor count in bits strictly below welfare precision — exact layout
  belongs to F6's determinism/precision spec). Results also carry survivor
  counts as a plain field for human reading.

## 4. The world and its configuration

All of the following are config surface. **Decided** that each exists as a
config option; the exact semantics of several are open (§9 group C).

| area | config | notes |
|---|---|---|
| map | `height`, `width` | |
| capacity | pre-made capacity distribution for sugar and spice | the default / the four hills Sugarscape normally uses, selectable by name; custom maps also specifiable (format open, C1) |
| growback | growth rate for sugar; growth rate for spice | independently settable |
| endowments | ranges from which agent endowments are drawn | including fertility, if fertility is enabled; which attributes exactly is open (D5) |
| seasons | seasonal migration α, β, γ | exact semantics open (C2) |
| pollution | production coefficient (harvesting), consumption coefficient (metabolism), diffusion, **decay rate** | decay is deliberate: pollution must not monotonically take over the map (C3) |
| disease | disease characteristics | model open (C4) |
| features | enable/disable each mechanic | including agent capabilities: combat, trade, lending, fertility |
| combat | α | the one behavior-adjacent constant we keep: it is physics (bounds combat's yield), not behavior |
| scoring | `score_reduce` | §3 |
| episode | length | **Decided (B1, 2026-08-07): ranked default 1000 timesteps** — ~10–15 generations and 10+ season cycles if enabled, deep trade horizon, ~half of v1's 2000-tick league compute (spend the difference on more episodes per round); certification fixtures stay ~10–20 ticks |

**Explicitly *not* config (Decided):** movement rules, aggression parameters,
lending rate and duration. Action selection belongs to policies; lending terms
are a negotiation between agents (E6).

## 5. Agents

An agent has position, sugar and spice holdings, per-resource metabolism,
vision, age, and whatever the enabled mechanics add (tribe/tags, immune
state, fertility attributes, loans). Endowments are drawn from configured
ranges at episode start.

Lifecycle is largely **Open**: death causes and timing (D2), max age (D1),
whether anything replaces a dead agent (D3 — P3's fixed pool suggests no),
inheritance (D4), and what a newborn inherits from parents (D5).

## 6. The timestep

**Leaning: a phased timestep rather than per-agent sequential turns.** Classic
Sugarscape (and DTL) activates one agent at a time, which does *everything* —
move, harvest, mate, trade — before the next agent acts. v2 instead leans
toward phases across the whole population:

```
0. Simulation phase — all the world's own updates happen first
   (growback, seasons, pollution dynamics, ... — composition and order open, E8)
1. All agents move            (moving onto an occupied cell = combat, if enabled)
2. All agents may harvest     (harvesting is an action, and optional)
3. All agents may trade       — repeated until quiescent
4. All agents may mate        — repeated until quiescent
5. An agent may decide to change tribes
```

What this buys: each phase is a clean *gate* — a named point where policies
are consulted, with a defined observation before it and defined resolution
after it. That is precisely the structure DTL lacked and v1 could not retrofit
(v1 exposed one gate, movement, because that's all the closed 14-step agent
turn allowed).

What it costs / leaves open:

- **Within-phase order (E1):** simultaneous with conflict resolution, or
  sequential in randomized order? Two agents moving to the same cell must
  resolve somehow. This is fork 5 (activation model) from
  `what-is-a-coworld.md`, now a free rules choice.
- **Quiescence (E4, E5):** phases 3 and 4 loop "until quiescent" — quiescence
  needs a definition and a round cap.
- **Movement and combat share one verb (Decided):** the movement action names
  a target cell; if the cell is occupied (and combat is enabled), the same
  action *is* an attack. No separate combat action. Combat's resolution
  mechanics are open (E2).
- **Harvest is explicit and optional (Decided):** unlike every classic
  Sugarscape variant, an agent on a resource cell chooses whether to harvest.
  Not harvesting is a meaningful move (e.g. leaving sugar to grow, or denying
  pollution production under a pollution regime).
- **Tribe change (tentative — the user's own question mark):** phase 5 exists
  in the leaning sketch, but what tribes *are* in v2 and what changing one
  means is open (E7).

## 7. The policy boundary

What a policy invocation receives and controls, per agent (P1):

### 7.1 Observation (Decided in outline, contents open — F1)

- **Vision:** what the agent can see from its position, per its vision stat.
  Range shape, and what is visible about other agents (holdings? tribe?
  metabolism?), are open.
- **Internal stats:** the agent's own state — holdings, metabolisms, age,
  vision, and mechanic-specific state.
- **Welfare, maybe (Leaning):** the pre-computed Cobb–Douglas wellness value,
  so policies don't have to re-derive the scoring function.

### 7.2 Memory: a scratchpad (Decided in principle)

Each policy gets, for each agent, a persistent scratchpad — "some kind of text
file" — carried across invocations. The policy reads it with the observation
and can rewrite it with its action.

Implication to design around, not an afterthought (§8.3): under the Arena
runtime a WASM component has no filesystem, so "a text file" concretely means
a blob the host passes in with each invocation and accepts back, with a size
cap. Scope (strictly per-agent, or per-seat shared — which would let one
policy's agents coordinate), size limit, and format are open (F2).

### 7.3 Actions (partially decided)

| phase | action | status |
|---|---|---|
| move | target cell; occupied target = combat | **Decided** as the verb; resolution open (E1, E2) |
| harvest | harvest or don't | **Decided** optional; amount semantics open (E3) |
| trade | negotiate with neighbors | protocol entirely open (E4) — this is the hard one |
| mate | ? | protocol open (E5) |
| lend | negotiate terms with the counterparty | terms are agent-negotiated, not configured (**Decided**); protocol open (E6) |
| tribe | change tribe? | tentative (E7) |

### 7.4 Time (Decided — A4, 2026-08-07)

The game has no notion of wall-clock time and imposes no per-invocation
budget. A policy is either *responsive* or *faulted* (→ A3 freeze); deadlines
that produce faults belong to the runtime — Arena's host per-delivery
deadline, or the WS shell's per-decision timeout (config, order of seconds).
This is forced as well as chosen: a deterministic Arena guest has no clock,
so game-enforced time limits are inexpressible there, and any game-level
budget would make the two runtimes play different rules. Consequence for
deployment (not model) docs: Arena runners for Sugarscape should set the
per-invocation deadline to ~1–5 s (the 180 s host default is sized for
CTF/LLM profiles), since the episode wall clock is the only other bound on
a slow-but-legal policy. Per-policy compute fairness is the platform's job
(fixed CPU per component), not the game's.

## 8. Design tensions (read before answering the open questions)

Three places where decided items interact and something has to give.

### 8.1 Newborns vs "every agent has a policy"

P1 requires every agent to be policy-controlled. Mating creates agents
mid-episode. So either a newborn is assigned to a policy (whose? a parent's —
which parent?), or fertility produces something other than a controllable
agent, or fertility is off in competitive play. Assignment also erodes the
divisor-of-64 equal allocation, which only holds at t=0 — a policy good at
mating ends up invoking on more agents, which is both a reward and a compute
asymmetry. (A2)

### 8.2 Death vs end-of-episode scoring

P3 scores at the end; agents can die mid-episode (starvation, combat, age).
The reduce in §3 runs over *what*, exactly — all agents ever controlled, or
survivors? A dead agent scored as zero makes `min` degenerate (one death ⇒
score 0) and drags `mean`; scoring welfare-at-death rewards dying rich early;
excluding the dead rewards sacrificing agents. Each choice creates a different
game. This is the biggest unspecified scoring question. (B2)

**Resolved (2026-08-07):** dissolved by choosing time-integrated wellness —
see §3. The pathologies above were all artifacts of end-snapshot scoring.

### 8.3 The scratchpad is protocol, not storage

Because Arena components are sandboxed WASM with no filesystem and no
`wasi:random`, the scratchpad must live in the host—policy contract itself:
observation carries the blob in, the action result carries it back. That makes
its size cap a bandwidth/determinism knob of the protocol, and makes per-seat
vs per-agent scope an explicit information-flow decision rather than a file
layout. (F2)

## 9. Open questions

Grouped; tags reference the sections above.

### A. Players and seats

- **A1.** ~~Is 64 the fixed total agent count with `seats ∈ divisors(64)`
  enforced, or is total agent count itself config (with seats dividing it)?~~
  **Resolved (2026-08-07):** `total_agents` is config (default 64), seats
  must divide it. See §2.
- **A2.** ~~Newborn control assignment (§8.1).~~ **Resolved (2026-08-07):**
  configurable `newborn_assignment ∈ {random_parent, initiating_parent,
  receiving_parent}`; ranked-play default deferred to B5. See §2.
- **A3.** ~~Dropped seat semantics.~~ **Resolved (2026-08-07):** orphaned
  agents freeze — no actions, physics continues. See §2. (Closes fork 6 in
  `what-is-a-coworld.md`.)
- **A4.** ~~Per-invocation compute budget for a policy, and what happens on
  timeout.~~ **Resolved (2026-08-07):** no game-level budget; time is
  runtime-owned, a missed runtime deadline is a fault → A3. See §7.4.

### B. Episode and scoring

- **B1.** ~~Episode length (timesteps).~~ **Resolved (2026-08-07):** ranked
  default 1000 (config per §4).
- **B2.** ~~Dead agents in the reduce (§8.2).~~ **Resolved (2026-08-07):**
  dead agents stay in the reduce with truncated integrals. See §3.
- **B3.** ~~Wellness measured when?~~ **Resolved (2026-08-07):** integrated
  over the episode, ÷T. See §3.
- **B4.** ~~Exact Cobb–Douglas form.~~ **Resolved (2026-08-07):** exponents
  = metabolism shares (classic). Gross-vs-net-of-debt holdings deferred into
  E6, which now owns it (see §3).
- **B5.** ~~Default `score_reduce` for ranked play.~~ **Resolved
  (2026-08-07):** `sum` (newly added to the table); ranked
  `newborn_assignment` = `random_parent`. See §3.
- **B6.** ~~Tie-breaking between policies.~~ **Resolved (2026-08-07):**
  survivors, then draw. See §3.

### C. World mechanics

- **C1.** Custom capacity map format (and what "the default or the four
  hills" set of named built-ins contains exactly).
- **C2.** Seasonal migration α, β, γ: exact semantics of each parameter.
- **C3.** Pollution: functional form of production (harvest) and consumption
  terms, diffusion schedule, decay rate application order.
- **C4.** Disease model: classic bit-string immune systems, or something
  simpler? Transmission, and whether policies see/act on infection.
- **C5.** Are sugar *and* spice always both present, or is single-resource a
  supported config?

### D. Agent lifecycle

- **D1.** Max age: enabled? drawn from a configured range?
- **D2.** Death causes (starvation, age, combat) and *when* in the phase
  order death is checked; what happens to holdings on death (inheritance —
  D4 — or vanish, or drop on the cell?).
- **D3.** Replacement on death: P3 implies no replacement (fixed pool,
  fixed length) — confirm.
- **D4.** Inheritance: enabled at all? (P3's rationale mentions it as a
  wealth-accumulation vector; within a single episode it may be fine.)
- **D5.** Endowment attribute list and ranges; what a newborn inherits
  (genetics: vision/metabolism crossover as in the classic?).

### E. Actions and phases

- **E1.** Within-phase activation: simultaneous with conflict resolution, or
  randomized sequential? If simultaneous: how do movement collisions resolve
  (two agents, one target cell)?
- **E2.** Combat: eligibility (classic rule limits targets by tribe and
  wealth), what the winner takes (min(α, victim wealth) + ?), loser's fate
  (death? displacement?), retaliation risk visibility.
- **E3.** Harvest semantics: all-or-nothing, or partial amounts?
- **E4.** Trade protocol — the hardest open question. Classic Sugarscape
  computes MRS-crossing trades automatically at a geometric-mean price; v2
  wants trade decisions made by policies. What's the negotiation primitive
  (structured bid/ask? offer–accept–counter rounds?), what's quiescence, and
  what's the round cap?
- **E5.** Mating: eligibility (fertility window, neighboring, wealth
  threshold as in the classic?), consent (both policies agree?), child
  endowment split, child placement, and A2.
- **E6.** Lending: negotiation protocol (terms agent-negotiated per §4),
  default handling, whether debts survive death (classic ties this to
  inheritance).
- **E7.** Tribes: what they are in v2 (classic cultural tags? seat-aligned
  teams as v1's `playerTribes`?), what changing tribe means, and whether
  phase 5 survives at all.
- **E8.** Simulation-phase composition and order: growback, seasons,
  pollution diffusion/decay, disease progression, aging, metabolism burn —
  which happen in phase 0 vs after the action phases, and where death checks
  sit.
- **E9.** Is "stay put" a legal move? (Presumably yes; classic Sugarscape
  forces movement to the best cell, but P2 hands the choice to the policy.)

### F. Policy interface and platform

- **F1.** Observation contents: vision shape (classic is von Neumann rays of
  length `vision`), what's visible about other agents, whether any global
  info (timestep, season) is included.
- **F2.** Scratchpad scope (per-agent vs per-seat), size cap, format
  (opaque bytes vs UTF-8 text) (§8.3).
- **F3.** Message encoding for observations/actions — fork 1 (JSON vs
  binary) in `what-is-a-coworld.md`.
- **F4.** Runtime target: Arena WASM components (`softmax:game@0.1.0` /
  `softmax:player@0.1.0`) vs Docker+WebSocket contract — fork 2. Arena is
  the dogfood target and its host-driven pump makes the phased timestep
  natural (a "step" needn't be a timestep — each phase can be a step).
- **F5.** Replay architecture — fork 3.
- **F6.** v2's own determinism spec: seeded RNG discipline, float policy,
  replay reproducibility (D1 freed us from CPython parity; we still owe a
  spec of our own).

## 10. Relation to the platform forks

From `what-is-a-coworld.md` §"Open design forks for v2":

| fork | status here |
|---|---|
| 1 — message encoding | open (F3) |
| 2 — engine runtime | open (F4); Arena favored as dogfood target |
| 3 — replay architecture | open (F5) |
| 4 — determinism spec | resolved by D1: our own spec; contents open (F6) |
| 5 — activation model | narrowed by §6's phased leaning; within-phase order open (E1) |
| 6 — fault/fallback | now a rules question (A3) |
