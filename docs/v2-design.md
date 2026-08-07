# Sugarscape v2 — Design

**Status: design complete (2026-08-07) — all open questions A1–F6 resolved.**
This document records decisions as they are made. Everything below is
**Decided** unless explicitly noted; changes now require revisiting a decision
by name. Implementation may surface revisions — record them here with dates.

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
| resources | — | **Decided (C5, 2026-08-07):** every world has both sugar and spice state — no single-resource mode. "Sugar-only" variants = zero spice capacity grid + zero spice metabolism ranges (CD exponent for spice becomes 0, welfare degrades to the classic sugar-only form). Uniform schemas everywhere; no trade validation needed since trade is policy-negotiated (E4) — a spiceless world just has nothing to exchange. C1's `two_hills` built-in = zero spice capacity |
| capacity | named built-in or explicit grids | **Decided (C1, 2026-08-07):** built-ins `four_hills` (ranked default — classic sugar NE/SW + spice NW/SE terraced hills), `two_hills` (sugar-only classic), `flat` (uniform; debugging/baselines), generated deterministically in-sim from `height`×`width`; custom maps are **explicit per-cell integer capacity grids** per resource, dims validated against `height`×`width` — a map is data, never a program (no procedural custom spec; generation belongs to tooling) |
| growback | growth rate for sugar; growth rate for spice | independently settable |
| endowments | ranges from which agent endowments are drawn | including fertility, if fertility is enabled; which attributes exactly is open (D5) |
| seasons | `season_length` (γ), `winter_divisor` (β) | **Decided (C2, 2026-08-07):** classic S_αβγ with integer semantics — N/S hemispheres swap summer/winter every `season_length` ticks; summer cells regrow at the normal growback rate every tick, winter cells regrow that amount only every `winter_divisor`-th tick. α is not a separate knob (it *is* the growback rate above); one climate governs both resources; all-integer math. Flagship ranked variant: seasons off (variant lever, not model spec). Phase-0 ordering → E8 |
| pollution | `production_coef`, `consumption_coef`, `diffusion_interval`, `decay_rate`, `suppression_coef`, `toxicity_coef` | **Decided (C3, 2026-08-07):** classic linear sources — harvesting `h` adds `production_coef·h`, metabolism `m` adds `consumption_coef·m` to the cell; diffusion = 4-neighbor mean every `diffusion_interval` ticks over **fixed-point integer** pollution (floor division); decay subtractive per tick (`max(0, p − decay_rate)`) so land heals. Physical effects, **both shipped, independently configurable** (coefficient 0 disables): growback suppression (effective regrowth = `max(0, growback − suppression_coef·p)` — commons tragedy as physics) and metabolic toxicity (agents on the cell burn `floor(toxicity_coef·p)` extra — personal harm). Observation-only pollution rejected: under P2 it would be inert |
| disease | `immune_length`, `disease_length`, `disease_count`, `initial_diseases_per_agent` | **Decided (C4, 2026-08-07):** classic bit-string model — agent immune strings, disease substrings; immune iff disease is a substring, else sick (+1 metabolism); immune response flips one bit per tick of the closest-matching substring (recovery = Hamming distance ticks); transmission passes one seeded-random disease per neighbor per tick. Specific persistent immunity; composes with D5 inheritance. Pure physics — policies interact only via observation (F1: sickness visibility) and movement |
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

Lifecycle:

- **Max age: Decided (D1, 2026-08-07).** Drawn per-agent at episode start
  (seeded) from config range `max_age: [min, max]`, classic ranked default
  `[60, 100]`; `null` = immortal (variant lever). With B1's 1000-tick
  episodes this forces ~10–15 generations — the partner mechanism to B5's
  `sum` reduce: reproduction becomes strategically necessary, not optional.
  Under integrated wellness, age death is amortized (full life's welfare
  already accrued), never a cliff.
- **Death causes: Decided (D2, 2026-08-07).** Starvation (cannot pay a
  tick's metabolism from holdings), old age (D1), and combat if E2 resolves
  lethally. *When* in the timestep death is checked → E8.
- **No replacement: Decided (D3, 2026-08-07).** P3's fixed pool + P1
  (every agent belongs to a seat) preclude batch-style replacement;
  reproduction (E5) is the only source of new agents.
- **Estate: inherit, else drop. (Decided — D4, 2026-08-07)** A dead agent's
  holdings split by integer division among living children (possibly
  cross-seat per A2 — under `sum`, inheritance makes mating an investment,
  not just a lottery); the remainder, and the whole estate when no child
  lives, drops on the death cell as harvestable resource. Cell levels may
  exceed capacity; growback simply doesn't apply above capacity.
  Inheritance is feature-flagged, ranked default on. E&A's
  inequality-amplifier caution doesn't bite within one bounded episode
  (P3). E6 hook: classic lending ties outstanding debts to heirs — E6
  owns that linkage.
- **Endowments and newborn genetics: Decided (D5, 2026-08-07).** At t=0
  each agent draws, seeded, from configured ranges: initial sugar + spice
  holdings, per-resource metabolism, vision, max age (D1), and — when the
  features are on — sex, fertility window (childbearing start/end ages),
  and an immune bit-string (C4). Newborns follow the full classic rule S:
  vision and each metabolism by per-attribute 50/50 crossover; immune
  string by bitwise crossover (inherited resistance); **each parent
  contributes half of its own initial endowment as the child's starting
  wealth** — mating's price tag, and the reason E5 gates fertility on
  wealth; max age, sex, and fertility window drawn fresh. Consequence:
  genes and estates (D4) both flow through lineages — mate choice is
  genetic strategy, episode-bounded per P3, and partially benefits rival
  seats via A2's cross-seat children.

## 6. The timestep

**Decided (upgraded from Leaning; E8 fixed the order, 2026-08-07): a phased
timestep rather than per-agent sequential turns.** Classic Sugarscape (and
DTL) activates one agent at a time, which does *everything* — move, harvest,
mate, trade — before the next agent acts. v2 runs phases across the whole
population. The canonical timestep:

```
Phase 0 — world updates (no policy invocations):
   growback (seasons C2 + pollution suppression C3 applied)
   pollution: diffusion (on interval ticks), then decay (every tick)
   disease: transmission from neighbors, then one immune-response bit-step
Phases 1–5 — action gates (policies invoked):
   1. move/combat   (sequential, seeded order — E1)
   2. harvest       (order-free fan-out)
   3. trade         (E4 propose/respond cycles)
   4. mate          (E5 propose/respond cycles)
   5. tribe         (declare switch — E7)
Phase 6 — upkeep (no policy invocations):
   loan collections due this tick (E6)
   metabolism burn (base + disease sickness penalty + pollution toxicity)
   aging (+1); death checks: starvation, max age
   estate settlement (D4) for upkeep deaths
   welfare accrual: per-tick Cobb–Douglas on post-upkeep holdings → integral
```

Load-bearing ordering choices (E8): **metabolism at end of tick** — an agent
can harvest in the morning to pay for dinner; starvation is failing to feed
yourself despite acting (classic collect-then-metabolize grace, phased).
**Loans before metabolism** — today's debts are collectible from today's
earnings, but senior to dinner: you can starve by repaying; over-leverage is
genuinely dangerous while E6's write-off keeps lender risk real too.
**Welfare accrues once per tick, post-upkeep, after deaths** — the day's
actions count the same day; a death tick contributes 0 (B2-consistent).
Combat deaths (phase 1) settle estates immediately, event-driven (E2);
phase 6 checks only starvation and age.

**Inaction is legal at every gate. (Decided — E9, 2026-08-07)** No-move /
no-action is always a valid choice (the classic's forced best-cell move was
behavior — evicted; A3's freeze rule depends on this). Illegal actions
(out-of-range move, ineligible attack, unpayable offer) resolve as no-ops,
identical to choosing inaction — never penalized beyond their own
opportunity cost.

What this buys: each phase is a clean *gate* — a named point where policies
are consulted, with a defined observation before it and defined resolution
after it. That is precisely the structure DTL lacked and v1 could not retrofit
(v1 exposed one gate, movement, because that's all the closed 14-step agent
turn allowed).

What it costs / leaves open:

- **Within-phase order: per-phase disciplines. (Decided — E1, 2026-08-07)**
  Different phases use different activation strategies:
  - **Movement (and therefore combat): sequential, episode-seeded shuffled
    order each timestep.** Each agent observes fully-updated state at its
    turn; an occupied cell is simply occupied — no conflict rules, classic
    semantics. Runtime note, accepted deliberately: this is N serial policy
    round-trips per timestep — negligible under Arena (in-process), slow
    for the WS shell at full scale (Arena is the primary runtime; the WS
    shell serves certification/local play at small configs).
  - **Harvest: order-free** (own-cell only; no agent interaction) —
    delivered as one concurrent fan-out.
  - **Trade / mating: negotiation phases** — their within-phase structure
    (pairing, proposal rounds, quiescence) is part of the protocol design
    in E4/E5, explicitly not a simple activation-order question.
  - **Tribe: order-free.**
  (Closes fork 5's residue in `what-is-a-coworld.md`.)
- **Trade protocol: bilateral targeted offers over R cycles. (Decided — E4,
  2026-08-07)** The trade phase runs `trade_rounds` (default 2–3)
  propose/respond cycles:
  1. *Propose:* each agent may submit **one** offer targeted at one
     von-Neumann-adjacent agent: `{give: (sugar, spice), want: (sugar,
     spice)}`, integer bundles, give clamped to holdings.
  2. *Respond:* each agent accepts/declines the offers addressed to it;
     acceptances execute in episode-seeded order, voiding any no longer
     payable (one-offer-per-proposer kills double-spend; voiding handles
     acceptor overcommitment).
  Countering is structural, not special-cased: decline and propose back
  next cycle. A cycle with zero offers ends the phase early — quiescence
  is a trivial deterministic check, not a definition problem. The sim
  never computes MRS or prices; **prices emerge or don't**. Spot barter
  only (credit is E6). Cross-tick price discovery is expected — the
  scratchpad (§7.2) is where reputation lives. Order-book matching and
  free-form negotiation channels remain buildable later as variants on the
  same encoding.
- **Mating: E4-shaped consent, classic eligibility. (Decided — E5,
  2026-08-07)** `mating_rounds` propose/respond cycles: one targeted
  proposal per agent per cycle to an eligible adjacent partner;
  accept/decline; accepted matings execute in seeded order,
  **re-validating eligibility at execution** (E4's voiding rule reused);
  zero-proposal cycle ends the phase early. Eligibility is physics, all
  classic: fertile age window, **wealth ≥ own initial endowment** (makes
  the D5 contribution payable, limits reproduction to the successful),
  opposite sex (D5 draws sex when fertility is on), von Neumann adjacency,
  and an empty cell adjacent to either parent for the child (seeded pick;
  none ⇒ the mating voids — classic crowding cap). Delta from classic:
  each agent completes at most **one mating per timestep** (closes
  tick-scale Genghis strategies; lineage volume lives across ticks). Mate
  *choice* is the strategy layer D5 built: proposing to good genes is
  investment; accepting prices in the endowment cost and A2's coin-flip
  seat assignment.
- **Lending: negotiated credit contracts. (Decided — E6, 2026-08-07)**
  Third instance of the E4 shape: proposal `{lend: (s,sp), repay: (s,sp),
  due_tick}` to an adjacent agent; accept ⇒ principal transfers now;
  interest is implicit and per-contract (repay > lend, negotiated).
  Physics: **`due_tick ≤ episode end`** (no contracting past P3's
  horizon); at due, the sim auto-collects `min(owed, holdings)`;
  **shortfall closes the contract** — the lender eats the loss, so credit
  risk prices into negotiated interest. Death: heirs inherit debt pro-rata
  with the estate, **capped at what they inherited** (limited liability);
  no heirs ⇒ write-off. Anyone holding goods may lend (classic
  age/fertility matchmaking evicted as behavior). **Closes B4's
  remainder: welfare stays over gross holdings** — under integrated
  welfare + due≤T + auto-collect, interest is the price of welfare-time
  and the market sets it; even Cobb–Douglas concavity gains (rich→poor
  transfers raise total welfare, incl. via E4 gifts) are legitimate
  distribution management under `sum`, not exploits.
- **Movement and combat share one verb (Decided):** the movement action names
  a target cell; if the cell is occupied (and combat is enabled), the same
  action *is* an attack. No separate combat action.
- **Combat resolution: classic, P2-cleaned. (Decided — E2, 2026-08-07)**
  Legality (physics): the target must be strictly poorer — wealth = sugar +
  spice, unweighted integer sum — and, when tribes are enabled (E7),
  different-tribe. An eligible attacker deterministically wins: the victim
  dies (D2), the attacker loots `min(α, victim wealth)` and takes the cell;
  the victim's **remaining** estate flows through D4 (heirs or ground) —
  combat and inheritance compose with no extra rule. Wealth doubles as
  armor (poorer-only prevents kamikaze deletion). The classic retaliation
  look-ahead is evicted as behavior: the sim permits any legal attack; risk
  assessment belongs to policies (F1 must expose neighbor wealth
  visibility). Illegal attack attempts = illegal moves (resolution → E9's
  illegal-action rule).
- **Harvest is explicit and optional (Decided):** unlike every classic
  Sugarscape variant, an agent on a resource cell chooses whether to harvest.
  Not harvesting is a meaningful move (e.g. leaving sugar to grow, or denying
  pollution production under a pollution regime).
- **Harvest amounts are partial. (Decided — E3, 2026-08-07)** The action
  names per-resource amounts, clamped to the cell's current level.
  All-or-nothing stays expressible (request everything); restraint becomes
  priceable — harvesting exactly metabolic need minimizes C3's pollution
  production, self-toxicity, and growback suppression. Sustainable-yield
  farming is the strategy this buys.
- **Tribes: chosen allegiance. (Decided — E7, 2026-08-07)** A tribe is a
  declared affiliation, not emergent culture (classic tags) or static
  teams (v1 seat-tribes): `tribe_count` (K, ranked default 2) config;
  initial assignment episode-seeded; **phase 5 is real** — an agent may
  declare a switch, effective at the next timestep; combat (E2) gates
  cross-tribe. Tribes are protection pacts: safety-in-numbers, defection,
  and betrayal (leave today, attack your ex-tribemate tomorrow) become
  policy strategy. Feature-flagged like other mechanics; tribeless
  variants gate combat on wealth alone. Novel-mechanic caveat recorded:
  no literature precedent, dynamics to be observed in playtesting.

## 7. The policy boundary

What a policy invocation receives and controls, per agent (P1):

### 7.1 Observation (Decided — F1, 2026-08-07)

- **Geometry: classic von Neumann rays.** An agent sees the four axis rays
  of length `vision` — no diagonals — and **vision is movement range**
  (movement targets any visible cell; occupied ⇒ combat per E2). Visible
  cells show current sugar/spice levels and pollution.
- **Visible agents: minimal attributes.** Each visible occupant shows only
  `{seat, holdings (sugar, spice), tribe, sick}` — the E2/E4/C4 minimums.
  Genes (metabolisms, vision), age, sex, and fertility are **hidden**: mate
  and rival assessment is inference, not reading — voided proposals carry
  information, and the scratchpad (§7.2) is where courtship/reputation
  knowledge accumulates. Fog is thus both spatial *and* attribute-deep
  (poker, not chess). `max_age` is private to everyone, including
  observers.
- **Own state: complete.** Holdings, metabolisms, vision, age, own
  max_age, sex, fertility window, tribe, sick + immune state, outstanding
  loan contracts (both directions), position, **current-tick welfare and
  the running integral** (the score being optimized is legible — B2).
- **Globals:** current tick, episode length T, season state (when
  enabled). The **public game config — including the capacity map — is
  handed to every policy at start** (it's public anyway; it ships in
  replays). The map is known; the other agents are the uncertainty.

### 7.2 Memory: a scratchpad (Decided — F2, 2026-08-07)

Each **agent** has one persistent scratchpad: **8 KiB (config-adjustable) of
validated UTF-8 text**, delivered with that agent's observation and
rewritable with its action. Pads don't touch world state, so they're not
needed for replay determinism; whether replays optionally snapshot them
(spectator value vs. size) is F5's call.

**Honest-rules clause.** The Arena research corrected §8.3's premise:
component instances (and WS player processes) live for the whole episode,
so *seat-scoped RAM persists regardless* — per-agent pad scope cannot be an
isolation boundary, and v2 doesn't pretend it is. Intra-seat coordination
through private memory is **legal** (unenforceable to ban); P1 governs the
invocation shape (per-agent observations and actions), not memory
isolation. The pad's real value is *legibility*: protocol-owned, per-agent
keyed memory — inspectable in debugging, replay-snapshottable, and the
natural home for courtship/reputation inference under F1's minimal
visibility. Stateless-per-invocation policy styles (fresh-context LLM
calls) read their pad instead of re-deriving.

### 7.3 Actions (partially decided)

| phase | action | status |
|---|---|---|
| move | target cell; occupied target = combat | **Decided** — sequential seeded order (E1); classic P2-cleaned combat (E2) |
| harvest | per-resource amounts, clamped | **Decided** — optional, partial (E3) |
| trade | targeted bilateral offers | **Decided** — E4 propose/respond cycles |
| mate | targeted proposals, classic eligibility | **Decided** — E5, E4-shaped consent |
| lend | negotiated credit contracts | **Decided** — E6, E4-shaped; due ≤ T; write-off; gross welfare |
| tribe | change tribe? | tentative (E7) |

### 7.4 Encoding (Decided — F3, 2026-08-07)

All observation/action/negotiation messages are **UTF-8 JSON with a
versioned envelope** (`{v, type, ...}`), schema documented in PROTOCOL.md,
encoded/decoded by pure core functions shared by every shell. Rationale:
zero-codegen authoring in any language, LLM-direct legibility, eyeball
debuggability; under F1's minimal observations messages are small (~1–4 KB)
and the boundary is not the hot loop. A binary protocol version can be
added behind the same seam if profiling ever demands it. (Closes fork 1 in
`what-is-a-coworld.md`.)

### 7.5 Time (Decided — A4, 2026-08-07)

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

### 7.6 Runtime and replay (Decided — F4 + F5, 2026-08-07)

**Runtime (F4, closes fork 2):** one deterministic core, thin shells, built
in this order: **core → Arena components (`softmax:game`/`softmax:player`,
per the merged coworld-ctf `arena/` recipe) → WS container shell → replay
viewer.** Arena is the dogfood and the smallest harness for the core; the
WS shell remains mandatory for certification/league hosting (Arena is
experiment-scoped) and serves small configs, accepting E1's sequential-
movement latency. The manifest **omits `engine_runtime`** — v2 builds on
none of the listed runtimes.

**Replay (F5, closes fork 3):** replay = **config + seed + decision log**
(every accepted action/offer per gate in execution order), versioned JSON
envelope consistent with §7.4, compressed; emitted incrementally via
Arena's `replay-append` and written to `COGAME_SAVE_REPLAY_URI` by the WS
shell — same bytes. The viewer is a **static bundle that resimulates**
with the same core compiled for the browser (v1's own signpost; the
ctf/crewrift production pattern). Scratchpad snapshots are **excluded**
from the base format (not needed for resimulation; policy memory isn't
broadcast by default) — a flagged debug/spectator extension may add them
later. Emscripten-vs-jco viewer build path is an implementation choice,
not spec.

### 7.7 Determinism spec (Decided — F6, 2026-08-07)

Same config + seed + decision log ⇒ **bit-identical world state on every
target** (native, Arena wasm32, browser viewer). The spec:

1. **All-integer world state** — no floats anywhere in the game, including
   welfare: Cobb–Douglas is computed in **fixed-point (32.32)** via pinned
   polynomial/table `ln`/`exp` implementations
   (`welfare = exp((m₁·ln w₁ + m₂·ln w₂)/mT)`). No libm, no FMA/contraction
   discipline (v1's `-ffp-contract=off` era ends), exact integer scores
   with B6's survivor bits assembled arithmetically, exact integers in
   results JSON.
2. **RNG:** master `u64` seed → per-subsystem streams (movement shuffle,
   lotteries, endowments, disease, child placement) derived by hashing
   (master, subsystem-id); PCG-class generators with explicit `uint64`
   state — never platform-width `int` (the wasm32 32-bit trap).
   Per-subsystem streams keep behavior stable under feature toggles.
3. **Defined iteration order everywhere** — arrays and explicit sort keys;
   no hash-table ordering may leak into behavior.
4. **Canonical per-tick state hash**, recorded periodically into the
   replay; native↔wasm↔viewer hash parity tests are the correctness gate
   (the coworld-ctf `gameHash` pattern).

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

**Resolved (2026-08-07), with a corrected premise:** component RAM persists
per-episode, so scope was never an enforceable isolation boundary — see
§7.2's honest-rules clause. Per-agent pads chosen for legibility.

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
  runtime-owned, a missed runtime deadline is a fault → A3. See §7.5.

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

- **C1.** ~~Custom capacity map format and built-in set.~~ **Resolved
  (2026-08-07):** explicit grids only; built-ins `four_hills`, `two_hills`,
  `flat`. See §4.
- **C2.** ~~Seasonal migration α, β, γ semantics.~~ **Resolved
  (2026-08-07):** classic hemispheric rule, integer winter semantics,
  `season_length` + `winter_divisor` config. See §4.
- **C3.** ~~Pollution: functional forms, diffusion, decay.~~ **Resolved
  (2026-08-07):** classic linear sources, fixed-point neighbor-mean
  diffusion, subtractive decay, and two configurable physical effects
  (growback suppression + metabolic toxicity). See §4. Application order
  within phase 0 → E8.
- **C4.** ~~Disease model.~~ **Resolved (2026-08-07):** classic bit-string
  immune systems. Policies see/act on infection only via observation and
  movement (visibility details → F1). See §4.
- **C5.** ~~Single-resource support?~~ **Resolved (2026-08-07):** always
  both; sugar-only = zero spice capacity + zero spice metabolism. See §4.

### D. Agent lifecycle

- **D1.** ~~Max age.~~ **Resolved (2026-08-07):** per-agent draw from config
  range, ranked default [60,100], null = immortal. See §5.
- **D2.** ~~Death causes and holdings disposal.~~ **Resolved (2026-08-07):**
  starvation / age / combat; estate per D4. Timing within the timestep →
  E8. See §5.
- **D3.** ~~Replacement on death.~~ **Resolved (2026-08-07):** confirmed —
  no replacement. See §5.
- **D4.** ~~Inheritance.~~ **Resolved (2026-08-07):** on (feature-flagged,
  ranked default on) — split among living children, else drop on cell.
  See §5.
- **D5.** ~~Endowments and newborn genetics.~~ **Resolved (2026-08-07):**
  full classic — crossover genetics, half-initial-endowment parental
  contributions, fresh draws for age/sex/fertility. See §5.

### E. Actions and phases

- **E1.** ~~Within-phase activation.~~ **Resolved (2026-08-07):** per-phase
  — movement/combat sequential in seeded order; harvest and tribe
  order-free; trade/mating structure belongs to E4/E5. See §6.
- **E2.** ~~Combat.~~ **Resolved (2026-08-07):** poorer-only (+
  different-tribe when tribes on), deterministic win, loot min(α, wealth),
  remainder through D4, victim dies, no sim-side safety check. See §6.
- **E3.** ~~Harvest semantics.~~ **Resolved (2026-08-07):** partial
  per-resource amounts, clamped. See §6.
- **E4.** ~~Trade protocol.~~ **Resolved (2026-08-07):** bilateral targeted
  offers over `trade_rounds` propose/respond cycles; decline+repropose is
  the counter; zero-offer cycle = early end; seeded-order execution with
  voiding. See §6.
- **E5.** ~~Mating.~~ **Resolved (2026-08-07):** E4-shaped consent protocol,
  classic eligibility as physics, once-per-tick cap, seeded child placement.
  See §6.
- **E6.** ~~Lending.~~ **Resolved (2026-08-07):** E4-shaped contracts,
  due ≤ T, auto-collect, write-off on shortfall, heirs liable capped at
  inheritance, gross-holdings welfare (closes B4's deferral). See §6.
- **E7.** ~~Tribes.~~ **Resolved (2026-08-07):** chosen allegiance —
  K-tribe config, seeded initial assignment, phase 5 declares switches
  (next-tick effective), combat gates cross-tribe. See §6.
- **E8.** ~~Simulation-phase composition and order.~~ **Resolved
  (2026-08-07):** world → gates → upkeep; loans → metabolism → aging →
  deaths → estates → welfare accrual. See §6.
- **E9.** ~~Is "stay put" legal?~~ **Resolved (2026-08-07):** yes, at every
  gate; illegal actions no-op. See §6.

### F. Policy interface and platform

- **F1.** ~~Observation contents.~~ **Resolved (2026-08-07):** classic rays
  (= movement range); visible agents show only seat/holdings/tribe/sick;
  own state complete incl. welfare integral; globals tick/T/season; public
  config at start. See §7.1.
- **F2.** ~~Scratchpad scope, size, format.~~ **Resolved (2026-08-07):**
  per-agent, 8 KiB UTF-8, honest-rules clause on seat RAM. See §7.2.
- **F3.** ~~Message encoding.~~ **Resolved (2026-08-07):** JSON, versioned
  envelope, pure-core codec. See §7.4. (Closes fork 1.)
- **F4.** ~~Runtime target.~~ **Resolved (2026-08-07):** core → Arena
  shells → WS shell; `engine_runtime` omitted. See §7.6. (Closes fork 2.)
- **F5.** ~~Replay architecture.~~ **Resolved (2026-08-07):** decision-log
  replay + resimulating static bundle; no pad snapshots in base format.
  See §7.6. (Closes fork 3.)
- **F6.** ~~Determinism spec.~~ **Resolved (2026-08-07):** all-integer
  world + fixed-point welfare, per-subsystem u64 RNG streams, defined
  iteration order, per-tick hash parity gates. See §7.7. (Completes
  fork 4.)

## 10. Relation to the platform forks

From `what-is-a-coworld.md` §"Open design forks for v2":

| fork | status here |
|---|---|
| 1 — message encoding | **closed (F3):** JSON, versioned envelope |
| 2 — engine runtime | **closed (F4):** Arena-first dual shell; `engine_runtime` omitted |
| 3 — replay architecture | **closed (F5):** decision-log + resimulating static bundle |
| 4 — determinism spec | **closed (D1 + F6):** own spec — all-integer, fixed-point welfare |
| 5 — activation model | **closed (§6 + E1):** phased timestep; movement sequential seeded |
| 6 — fault/fallback | **closed (A3):** faulted seat's agents freeze |

All six platform forks are closed as of 2026-08-07.
