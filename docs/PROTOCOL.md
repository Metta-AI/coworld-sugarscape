# Sugarscape v2 — Player Protocol

**Status: DRAFT (2026-08-11), revised after cross-model review — design-stage
specification; no implementing code exists yet.** This is the concrete wire
schema for the interface that `docs/v2-design.md` settles semantically (F3
encoding, §6's six-gate timestep, §7 policy boundary). It is the protocol
the coworld manifest will declare as `manifest.game.protocols.player`.
Calls this draft makes beyond the design are listed in
[§12](#12-decisions-proposed-by-this-draft); a handful of rules additionally
depend on the open design questions **G1–G8** (`docs/v2-design.md` §9 G) and
are marked `pending G_n` where they appear — the recommended G resolutions
are written inline so the document reads whole.

Everything here binds the **payloads**; the transport differs by runtime:

- **WS shell (v2.0):** the messages below travel as WebSocket text frames
  over `WS /player?slot=<n>&token=<t>`, per the platform game-container
  contract (`docs/what-is-a-coworld.md` §1.2–1.3).
- **Arena (future work):** the same JSON payloads travel through the
  `softmax:player` message interface; payloads are opaque to Arena, so
  nothing here changes. Session-layer rules that are WS-specific (§2) are
  marked as such.

Per F3, encoding and decoding live in **pure core functions** shared by
every shell; this document describes what those functions produce and
accept.

---

## 1. Scope and layering

Two layers:

1. **Invocation payloads** (§3–§7) — `episode_start`, `decision_request`,
   `decision`, `episode_end`. Owned by the deterministic core. Identical on
   every runtime.
2. **Session layer** (§2, §8–§9) — connection lifecycle, correlation,
   concurrency, deadlines, faults. Owned by the hosting shell. The rules
   here are written for the WS shell; Arena's host implements the same
   semantics with its own machinery (per-delivery deadlines, `SeatFault`).

Out of scope: the spectator stream (`WS /global`) and browser client pages —
separate document when the viewer work lands; the game-config schema itself
(summarized in `docs/v2-design.md` §4); the results and replay artifact
formats (design §7.6).

## 2. Session lifecycle (WS shell)

1. **Connect.** The player container reads `COWORLD_PLAYER_WS_URL` and opens
   the socket. A bad or missing token is rejected **at the handshake**
   (HTTP 403 on the upgrade request) — the platform runner asserts this.
   `slot` is the seat index, 0-based; "slot" (platform term) and "seat"
   (design term) are the same thing.
2. **Wait.** The game is silent until the episode begins — when all seats
   have connected, or after the platform's `player_connect_timeout_seconds`.
   A seat that never connects is faulted from t=0: its agents freeze for the
   whole episode (design A3).
3. **`episode_start`** (§4.1) — one message, carrying the seat's slot and
   the public game config.
4. **Decision loop** — the game sends `decision_request` messages (§4.2);
   the policy answers each with a `decision` (§5). This is the entire
   in-episode vocabulary. There are no outcome acknowledgments: results of
   actions are learned from subsequent observations (§7.9).
5. **`episode_end`** (§4.3) — final scores; the game then closes the socket
   with WebSocket code 1000. The player exits cleanly.

**Disconnect is a fault.** A socket that closes before `episode_end` faults
the seat permanently (A3 freeze); the protocol has no reconnection. This
mirrors Arena, which drops a faulted seat permanently. A faulted seat's
socket is closed at the fault (§9) and never receives `episode_end`.

## 3. Envelope and conventions

Every message, both directions, is a single UTF-8 JSON object:

```json
{"v": 1, "type": "<message-type>", ...}
```

- **`v`** — protocol major version, integer. This document specifies `1`.
  The game validates `v` on every player frame; a mismatch is a protocol
  violation (§9).
- **`type`** — one of `episode_start`, `decision_request`, `episode_end`
  (game → player) or `decision` (player → game).
- One JSON object per WebSocket text frame. No batching, no binary frames.

### Numbers

- **Integers only, in every known field.** No floats anywhere, matching the
  all-integer determinism spec (design §7.7). Fixed-point welfare is
  carried in scaled integer units (§6.1); pollution is carried in its raw
  internal fixed-point integer units (scale pinned by G6).
- **Every wire integer is < 2⁵³** (JavaScript-safe; pending G7's normative
  bound). Quantities that a hostile config could in principle push past
  that — welfare integrals, seat score sums — **saturate** at 2⁵³ − 1;
  config validation is expected to reject worlds anywhere near the bound,
  so saturation is a backstop, not a gameplay mechanism. Ids are below the
  bound by construction.
- Quantity fields (holdings, amounts, bundles, ticks, ids) are
  non-negative. A negative integer in a known quantity field of a player
  frame is a protocol violation (§9) — signs are shape, not semantics, so
  no "negative harvest" can ever reach the clamping layer.

### Player-frame limits

A player→game frame is malformed (protocol violation, §9) if it exceeds
**16 KiB** UTF-8, nests deeper than **8** levels, contains duplicate keys
in any object, or contains a non-integer number in a known field. Unknown
fields are ignored **without inspection** (any JSON value is permitted
inside them) — validation applies to known fields only, which keeps the
ignore-unknown rule (§10) and the strict-shape rule from contradicting
each other. Game→player frames carry no size cap (`episode_start` includes
capacity grids), but everything after `episode_start` is small in
practice (~1–4 KB, F3).

### Identifiers

| id | assigned by | scope / lifetime | ordering guarantee |
|---|---|---|---|
| `slot` (= seat) | platform | episode | — |
| agent `id` | core, creation order: initial agents `0..total_agents-1`, then newborns sequentially | episode; never reused | ascending = creation order |
| request `id` | shell, monotonically increasing from 0 | connection; echoed verbatim by the reply | ascending = delivery order |
| `offer_id` | core, from 0, ascending proposer agent id | one (tick, gate, cycle) sub-step | see §7.3 |
| `contract_id` (loans) | core, from 0, in contract-creation order | episode | ascending = creation order |

Agent ids are deterministic (creation order is seeded world evolution), so
they are identical across live runs, replays, and future runtimes.
Sequential ids are globally allocated and always visible, which leaks
aggregate unseen-event volume under hidden-attribute regimes — kept
deliberately for legibility, flagged as design question **G8**.

**Canonical array orders** (a policy indexing "the first element" must
behave identically on every implementation): `offers` ascending
`offer_id`; `loans` ascending `contract_id`; `diseases` ascending
lexicographic; rays fixed `n`,`e`,`s`,`w`, cells nearest-first.

## 4. Game → player messages

### 4.1 `episode_start`

```json
{
  "v": 1,
  "type": "episode_start",
  "slot": 3,
  "seats": 4,
  "config": { "...": "the public game config — design surface only" }
}
```

`config` is the game-design config surface of `docs/v2-design.md` §4, and
**nothing else**: map dimensions, per-resource capacity grids (built-in
maps are shipped *resolved* — the built-in's name plus the explicit grids
it generated), growback, seasons, pollution, disease, feature flags,
combat α, the visibility configuration, `score_reduce`,
`newborn_assignment`, episode length, and the three negotiation caps
(`trade_rounds`, `mating_rounds`, `lend_rounds`). **Platform and runtime
fields never appear** — no tokens, no URIs, no endpoints, no timeout
settings. (The runtime config the game reads at startup contains
per-seat auth tokens; sending it verbatim would let any policy
authenticate as any seat. The protocol therefore defines `config` as an
allowlist, not a passthrough.) It is sent **once**; the only config-owned
values repeated later are the current `tick`, `episode_length`, and
season state in `globals` (§4.2).

Deliberately absent: a roster of the seat's agents. P1 admits no
population-scoped message; the seat learns its agent ids as invocations
arrive (§7.8). Since every agent is invoked at the movement gate of tick 0,
the initial roster is fully known one gate into the episode anyway.

### 4.2 `decision_request`

One invocation of the policy for one agent at one gate — the design's unit
of control (P1), including each delivery within a negotiation cycle.

```json
{
  "v": 1,
  "type": "decision_request",
  "id": 4211,
  "gate": "move",
  "agent": { "...": "own state, §6.1" },
  "rays": { "...": "visible world, §6.2" },
  "globals": { "tick": 17, "episode_length": 1000,
               "season": {"north": "summer", "south": "winter", "ticks_until_flip": 33} }
}
```

- `gate` — one of `move`, `harvest`, `trade_propose`, `trade_respond`,
  `mate_propose`, `mate_respond`, `lend_propose`, `lend_respond`, `tribe`
  (§7).
- `cycle` — negotiation cycle number, 0-based; present only on the six
  negotiation gates.
- `offers` — present only on the three respond gates: the offers addressed
  to this agent in this cycle (shapes in §7.3–§7.5), ascending `offer_id`.
- `season` is present only when seasons are enabled. Throughout the
  protocol, absent means absent, not null.

Observations are built from the sub-step's frozen snapshot (§8) — except
at the movement gate, where each request is built from the live world at
that agent's turn (E1: sequential activation is full information).

### 4.3 `episode_end`

```json
{
  "v": 1,
  "type": "episode_end",
  "tick": 999,
  "scores": [512034, 498211, 623890, 407112],
  "survivors": [11, 9, 14, 6]
}
```

`tick` is the last tick played (ticks run `0..T-1`, pending G4).
`scores[i]` is seat *i*'s final published score exactly as written to the
results artifact (integer; quantum and survivor-bit layout pinned by G7);
`survivors[i]` the seat's living agents at the end. Faulted seats appear
in both arrays — their agents' truncated integrals still score (B2) — but
their sockets, closed at fault time, do not receive this message. Public
information, provided as a courtesy; the results JSON is authoritative.

## 5. Player → game: `decision`

The only message a policy sends:

```json
{"v": 1, "type": "decision", "id": 4211, "action": {"move": {"x": 12, "y": 31}}}
```

- `id` echoes the `decision_request` being answered — which, per §8, is
  the seat's single outstanding request.
- `action` contains **exactly one known action key**, valid for the
  request's gate (§7), or the universal explicit no-op below. Unknown
  extra keys inside `action` are ignored like unknown fields anywhere
  (§3); two *known* action keys are a shape violation (§9).

```json
{"v": 1, "type": "decision", "id": 4211, "action": {"pass": true}}
```

`pass` (the literal `true`) is legal at every gate (E9): stay put, harvest
nothing, offer nothing, decline everything, keep your tribe.

**Semantic illegality is a no-op, not a fault** (E9): an out-of-range move
target, an ineligible mating proposal, a `due_tick` past the horizon —
each resolves exactly as `pass`, never penalized beyond its own
opportunity cost. Where the design specifies **clamping** instead of
voiding, clamping wins: an over-holdings `give` is clamped to holdings at
admission (E4), not voided (§7.3). Unknown or duplicate `offer_id`
entries in an `accept` list are dropped and the remaining valid subset
executes; only an empty normalized subset is equivalent to `pass` (§7.3).
Faults are reserved for *protocol* violations (§9): the boundary is
"well-formed answer to the question asked" vs "not an answer."

## 6. The observation

### 6.1 Own state (`agent`)

Complete per design F1, with the one `max_age` knob:

```json
{
  "id": 41,
  "seat": 3,
  "pos": {"x": 12, "y": 30},
  "cell": {"sugar": 0, "spice": 4, "pollution": 2},
  "holdings":   {"sugar": 22, "spice": 9},
  "initial_endowment": {"sugar": 18, "spice": 6},
  "metabolism": {"sugar": 2,  "spice": 1},
  "vision": 3,
  "age": 14,
  "max_age": 87,
  "sex": "female",
  "fertility": {"start": 14, "end": 40},
  "mated_this_tick": false,
  "tribe": 1,
  "tribeless": false,
  "sick": false,
  "immune": "01011010",
  "diseases": ["0110"],
  "loans": [
    {"contract_id": 7, "role": "borrower", "counterparty": 12,
     "principal": {"sugar": 5, "spice": 0},
     "repay":     {"sugar": 6, "spice": 0},
     "due_tick": 620}
  ],
  "welfare": {"last_tick_q20": 1348271, "integral_q20": 20981134}
}
```

- `cell` is the agent's own cell — current resource levels and pollution.
  (An agent must be able to see what it stands on: partial harvest (E3)
  and pollution restraint are decisions about these exact numbers.)
- `initial_endowment` is the agent's own t-0 (or birth) endowment — own
  information the E5 fertility wealth check is defined against.
- `mated_this_tick` reports whether one of this agent's matings has
  already **executed** this tick (E5's once-per-tick cap) — the policy
  cannot infer this reliably itself, because acceptances can void.
- `max_age` is omitted when config hides it even from self (F1's
  mortality knob).
- `sex`, `fertility`, `mated_this_tick` appear only when fertility is
  enabled; `tribe`, `tribeless` only when tribes are; `immune`,
  `diseases`, `sick` only when disease is. `diseases` lists the
  bit-strings currently infecting the agent (C4).
- `loans` lists live contracts in both directions (`role` is this agent's
  side), ascending `contract_id`. `counterparty` tracks inheritance: if
  the other party died and an heir assumed the contract (E6), the id is
  the heir's. Collection mechanics are phase-7 physics (algorithm pinned
  by G1).
- **Welfare units:** `last_tick_q20` is the welfare accrued at the end of
  the **previous** tick, and `integral_q20` the running sum over all
  completed ticks — both in units of 2⁻²⁰ (quantum pinned by G7; the
  core computes in 32.32 and quantizes for the wire). Welfare accrues in
  phase-7 upkeep, so a mid-tick observation cannot contain the current
  tick's value; both fields are absent at tick 0. The pair exists so the
  quantity being optimized is legible to the policy (B2).

### 6.2 Visible world (`rays`)

Classic von Neumann rays: four arrays, one per direction, each listing
cells outward from the agent's position, nearest first, up to `vision`
cells.

**Coordinate convention (normative):** the origin `(0,0)` is the
northwest corner; `x` increases eastward, `y` increases southward; `n`
means decreasing `y`, `e` increasing `x`, `s` increasing `y`, `w`
decreasing `x`. Whether the grid is a torus (rays wrap) or bounded (rays
truncate at the edge) is design question **G5**; the ray arrays are
simply shorter than `vision` where truncation applies.

```json
"rays": {
  "n": [ {"x": 12, "y": 29, "sugar": 3, "spice": 0, "pollution": 2, "occupant": null},
         {"x": 12, "y": 28, "sugar": 0, "spice": 4, "pollution": 0,
          "occupant": {"id": 77, "seat": 0, "holdings": {"sugar": 14, "spice": 2},
                       "tribe": 0, "sick": true}} ],
  "e": [ "..." ], "s": [ "..." ], "w": [ "..." ]
}
```

- Cell resource values are current levels (capacity is known from
  config); `pollution` is the raw fixed-point integer state (G6).
- `occupant` is `null` for empty cells. For occupied cells it contains
  the agent `id` plus **exactly the attributes the visibility config
  exposes** (F1); hidden attributes are omitted entirely. The complete
  occupant field set, with wire shapes matching §6.1's own-state forms:

  | field | shape | ranked default |
  |---|---|---|
  | `id` | int | **always present** (not configurable) |
  | `seat` | int | visible |
  | `holdings` | `{sugar, spice}` | visible |
  | `tribe` / `tribeless` | int / bool | visible |
  | `sick` | bool | visible |
  | `age` | int | hidden |
  | `sex` | `"male"` / `"female"` | hidden |
  | `fertile_now` | bool | hidden |
  | `metabolism` | `{sugar, spice}` | hidden |
  | `vision` | int | hidden |
  | `max_age` | — | **never visible to others** (not configurable) |

- The agent **id is always visible**: identity is required for targeting
  (offers and proposals name an `id`) and deliberately enables cross-tick
  reputation, which the design expects policies to keep in instance
  memory (E4). What you can *learn about* an agent is configurable; *that
  it is the same agent* is not (leak tradeoff flagged as G8).
- Vision is movement range: any listed cell is a legal movement target
  (occupied ⇒ combat, E2).

## 7. Gates and actions

The per-tick gate order is design §6: `move` (sequential), `harvest`,
`trade` cycles, `mate` cycles, `lend` cycles, `tribe`. Phases for disabled
features are skipped entirely.

**Invocation filter.** At every gate the game invokes an agent only if a
non-`pass` action is plausibly available, judged **only on information the
agent can already see** — so being invoked leaks nothing the agent didn't
have (poker stays poker under F1's hidden-attribute regimes):

| gate | invoked iff |
|---|---|
| `move` | always (every living agent, every tick) |
| `harvest` | own cell (§6.1 `cell`, already visible) holds any resource |
| `trade_propose` | ≥ 1 adjacent occupant |
| `trade_respond` | ≥ 1 admitted offer addressed to the agent this cycle |
| `mate_propose` | agent is itself eligible (own fertility window, wealth ≥ own initial endowment, not yet mated this tick) **and** has ≥ 1 adjacent occupant — partner eligibility is *not* pre-checked, since it may be hidden |
| `mate_respond` | ≥ 1 admitted proposal addressed to the agent this cycle |
| `lend_propose` | ≥ 1 adjacent occupant |
| `lend_respond` | ≥ 1 admitted offer addressed to the agent this cycle |
| `tribe` | always, when tribes are enabled |

A non-invoked agent implicitly passes. Faulted seats' agents are never
invoked (A3). Newborns are invoked at no gate until the tick after their
birth (pending G3).

### 7.1 `move`

Sequential, one agent at a time across the whole population (E1). The
**activation list is frozen at phase start**: the episode-seeded shuffle
is drawn over the agents alive when the phase begins; an agent that dies
before its turn (a combat victim — or, under the hidden-holdings variant,
an attacker losing its own attack) is skipped when reached, and actions
already executed stand permanently. Action:

```json
{"move": {"x": 12, "y": 31}}
```

Target must be a visible (in-ray) cell. Empty target: relocation. Occupied
target with combat enabled: the same action **is** the attack (E2); the
legality check (poorer-only, cross-tribe — or the hidden-holdings
variant's richer-wins rule) is physics, applied on execution; the loot's
resource composition is pinned by **G2**. Illegal target: no-op. `pass`:
stay.

### 7.2 `harvest`

Order-free fan-out (§8). Action names per-resource amounts, clamped to the
snapshot's cell levels (E3):

```json
{"harvest": {"sugar": 3, "spice": 0}}
```

### 7.3 `trade_propose` / `trade_respond`

Phase 3 runs propose/respond cycles to quiescence, capped at `trade_rounds`
(E4). Spot barter only — credit lives in the lend phase (§7.5). One offer
per agent per cycle, targeted at one von-Neumann-adjacent agent.

Propose action:

```json
{"offer": {"to": 77,
           "give": {"sugar": 3, "spice": 0},
           "want": {"sugar": 0, "spice": 2}}}
```

**Admission and normalization.** A submitted offer is admitted iff, after
normalization, it is non-trivial and deliverable: the target is a living,
non-frozen, adjacent agent; `give` is **clamped to the proposer's
holdings** (E4); `want` is clamped to the target's holdings when holdings
are visible, and unclamped when hidden (F1); an offer whose `give` *and*
`want` are both all-zero after clamping is not admitted. Only admitted
offers are delivered, receive `offer_id`s (allocated in ascending proposer
agent id), and count toward quiescence: **a cycle with zero admitted
offers ends the phase** — inadmissible submissions cannot pin a phase at
its cap.

Respond request carries the admitted offers addressed to this agent:

```json
"offers": [
  {"offer_id": 3, "from": 77,
   "give": {"sugar": 3, "spice": 0}, "want": {"sugar": 0, "spice": 2}}
]
```

(`give`/`want` are stated from the proposer's perspective on both sides of
the wire — the acceptor of offer 3 pays 2 spice and receives 3 sugar.)

Respond action — accept any subset by id; everything unlisted is declined:

```json
{"accept": [3]}
```

Unknown and duplicate ids are dropped from the list; the remaining subset
executes. Acceptances execute in episode-seeded order; any acceptance no
longer payable at execution voids (E4). Countering is structural: decline
now, propose back next cycle.

### 7.4 `mate_propose` / `mate_respond`

Phase 4, same cycle machinery, capped at `mating_rounds` (E5). Propose:

```json
{"propose": {"to": 55}}
```

Admission mirrors §7.3: the target must be a living, non-frozen, adjacent
agent, and the proposer must itself still be eligible; partner attributes
are *not* pre-checked (they may be hidden — a proposal to an ineligible
partner is admitted, delivered, and voids at execution if accepted:
voided proposals are information, F1). Respond request:

```json
"offers": [ {"offer_id": 1, "from": 55} ]
```

Respond action: `{"accept": [1]}`. Accepted matings execute in seeded
order, **re-validating full eligibility at execution** — both parties'
fertility, wealth, opposite sex, the one-mating-per-agent-per-tick cap
(§6.1 `mated_this_tick`), and the empty-cell requirement for the child
(none ⇒ the mating voids). Accepting several proposals is legal; physics
voids all but the first executed. Child genetics, placement, and seat
assignment are entirely sim-side (D5, A2); the child acts from the next
tick (G3) — no protocol surface.

### 7.5 `lend_propose` / `lend_respond`

Phase 5 — lending's own gate, after mate so credit cannot finance the
fertility wealth check within the tick it is borrowed, and before upkeep
so distress borrowing can still pay the tick's metabolism and due
collections. Same cycle machinery, capped at `lend_rounds` (E6). One
credit proposal per agent per cycle, in **either direction**:

```json
{"offer": {"to": 12, "direction": "lend",
           "lend":  {"sugar": 5, "spice": 0},
           "repay": {"sugar": 6, "spice": 0},
           "due_tick": 700}}
```

- `direction: "lend"` — the proposer lends; on acceptance the principal
  flows proposer → acceptor now, and `repay` is collected acceptor →
  proposer at `due_tick`.
- `direction: "borrow"` — the proposer asks to borrow; the acceptor
  becomes the lender, principal flows acceptor → proposer on acceptance.
- `lend` and `repay` are always stated as (principal, repayment)
  regardless of direction. Interest is whatever the two bundles imply —
  the protocol imposes no relation between them (a `repay` below `lend`
  is a legal, gift-shaped contract; E4 gifts are legal too).
- Physics: `current_tick ≤ due_tick ≤ episode_length − 1` (pending G4;
  out-of-range voids as illegal → no-op). A contract due the current
  tick collects in this tick's upkeep.

**Admission** mirrors §7.3: living, non-frozen, adjacent target; the
`lend` bundle is clamped to the prospective lender's snapshot holdings
(the proposer's under `"lend"`, the target's under `"borrow"` when
visible, unclamped when hidden — F1's rule applied to whichever side the
bundle draws from); an offer whose `lend` and `repay` are both all-zero
after clamping is not admitted. Quiescence counts admitted offers only.

Respond request:

```json
"offers": [
  {"offer_id": 0, "from": 12, "direction": "borrow",
   "lend": {"sugar": 5, "spice": 0}, "repay": {"sugar": 6, "spice": 0},
   "due_tick": 700}
]
```

Respond action: `{"accept": [0]}` (same normalization as §7.3).
Acceptances execute in seeded order with execution-time re-validation:
both parties alive and adjacent, and whoever is lending still holding the
principal. Collection, `collection_floor`, `shortfall_mode`, and debt
inheritance are phase-7 physics — integer algorithm pinned by **G1** —
visible to policies only through the `loans` array (§6.1) and their
holdings.

### 7.6 `tribe`

Phase 6, order-free fan-out, when tribes are enabled (E7). Declare a
switch, effective next tick:

```json
{"tribe": 2}
```

or, when the `tribeless` variant flag is on: `{"tribeless": true}` (rejoin
with `{"tribe": k}` later). `pass`: keep current allegiance.

### 7.7 What has no gate

Combat (inside `move`), loan collection and shortfall handling (phase-7
physics, E6/G1), metabolism, aging, death, estates, disease transmission
and immune response, welfare accrual — all sim-side. Policies see the
consequences in their next observation.

### 7.8 Newborns

A newborn's controlling seat starts receiving `decision_request`s for the
new agent id from the next tick's movement gate (G3) — there is no birth
announcement (P1: no population-scoped or roster messages). The first
such observation is self-describing: an unfamiliar agent id, near-zero
`age` (whether the birth tick's upkeep ages a newborn is a G3 detail),
endowed holdings, position. Under per-seat instances (design §7.2) no new connection or
instance is involved; the existing socket simply carries one more agent
id.

### 7.9 No acknowledgments, by design

The game never reports an action's outcome. Whether a move, attack, offer,
or acceptance took effect is learned from the next observation (holdings,
position, `mated_this_tick`, the `loans` array, the world) — voided
proposals *are* information (F1's poker-not-chess), and within a
negotiation phase each cycle's observation already reflects the previous
cycle's executed exchanges.

## 8. Concurrency, ordering, deadlines

- **`move` is globally sequential**: at most one outstanding
  `decision_request` in the entire episode at a time, in the phase-start
  seeded order (§7.1).
- **Every other sub-step is a cross-seat fan-out, per-seat serial.** The
  game runs seats concurrently but keeps **at most one outstanding
  request per seat** at all times, issuing each seat's invocations in
  ascending agent id. One policy instance serves the whole seat (design
  §7.2), so per-seat serialization is what makes a per-decision deadline
  fair to a synchronous policy: a deadline never runs while the policy is
  busy answering an earlier request. (An earlier draft allowed pipelining
  multiple outstanding requests per seat; that is withdrawn — queued
  requests' deadlines would penalize legal serial policies.)
- **Snapshot and commit.** For every fan-out sub-step: (1) the world
  snapshot is frozen at sub-step start; (2) every request is built from
  that snapshot; (3) replies are collected; (4) nothing resolves until
  the barrier — after the last reply or fault — where all decisions
  execute in canonical order: the episode-seeded acceptance order for
  negotiation sub-steps (E4), ascending agent id for `harvest` and
  `tribe` (conflict-free; pinned anyway). Observations and outcomes never
  depend on socket timing.
- **Fault during a sub-step:** decisions the game had already received
  from the seat remain valid and execute at the barrier; the request that
  faulted and the seat's not-yet-issued invocations in that sub-step
  resolve as `pass`; from the next sub-step the seat is frozen (A3).
- **Deadline:** each request is governed by a per-decision deadline owned
  by the runtime — the WS shell's `decision_timeout_seconds` config
  (order of seconds; design §7.5), Arena's per-delivery deadline later.
  No deadline field appears on the wire; the game itself has no notion of
  wall-clock time and no game-level budget (A4).
- **Timeout (interim rule, design §7.5):** a missed deadline is a seat
  fault — permanent, A3 freeze. When Arena gains soft-timeout semantics,
  both shells will switch in the same release to: missed deadline ⇒ that
  one decision resolves as `pass`, seat keeps playing. The message
  vocabulary is unchanged by that future switch.

## 9. Faults

A **seat fault** permanently removes the seat (A3): its agents freeze and
the socket is closed (WebSocket code 1008). Fault causes:

- missed per-decision deadline (interim rule, §8);
- disconnect before `episode_end` (§2);
- **protocol violation**: a frame that is not valid JSON; violates the
  player-frame limits of §3 (size, depth, duplicate keys); is not a
  `decision`-typed object with a well-formed envelope or carries the
  wrong `v`; an `id` that does not match the seat's outstanding request;
  a duplicate reply; an `action` whose *shape* is invalid for the gate —
  no known action key, two known action keys, a gate-mismatched key
  (e.g. `{"harvest": ...}` answering a `move` request), or a negative or
  non-integer value in a known quantity field.

Contrast with §5: a well-formed answer whose content is *semantically*
illegal (bad target, out-of-range `due_tick`, unknown `offer_id` entries)
is a no-op or is normalized, never a fault. The fault line is
malformed-vs-illegal, not smart-vs-dumb.

**Reporting.** The platform artifact `COGAME_PLAYER_FAILURE_URI` holds one
`{message, failed_policy_index}` object; when several seats fault in one
episode, the **first fault in game order** (tick, then phase, then
within-phase canonical order) is written there, atomically, and every
fault is recorded in results metadata and the replay. Other seats are not
notified in-protocol; a frozen seat's agents are simply observable
standing still.

## 10. Versioning

- `v` is the protocol major version; this document is `v: 1`.
- Without bumping `v`, the game may add: new **optional fields** on
  existing messages, and new game→player message types that are pure
  notifications — types a policy can ignore with **no reply and no
  penalty**. The ignore-unknown rules (§3) absorb exactly these.
- Anything a policy must *act on* to stay healthy — new request types,
  new gates, removed or renamed fields, changed units or id semantics —
  bumps `v`. (A new request type cannot ride the ignore rule: a policy
  that ignores it times out and faults.)
- The manifest's `protocols.player` value names this protocol and version;
  a policy seeing an unexpected `v` in `episode_start` should fail fast
  rather than guess.

## 11. Worked example

Tick 17, seat 3's agent 41 attacks a poorer cross-tribe neighbor two
cells north (visible in `rays.n[1]`), harvests the captured cell, accepts
a barter offer, then proposes to borrow against a due date late in the
episode; the target accepts, and the contract appears in agent 41's next
observation.

```
game →  {"v":1,"type":"decision_request","id":4211,"gate":"move",
         "agent":{"id":41,...},"rays":{...},
         "globals":{"tick":17,"episode_length":1000}}
player→ {"v":1,"type":"decision","id":4211,"action":{"move":{"x":12,"y":28}}}

          (combat resolves sim-side: agent 77 dies, 41 loots min(α, 16) — composition per G2 — and takes the cell)

game →  {"v":1,"type":"decision_request","id":4302,"gate":"harvest",
         "agent":{"id":41,"pos":{"x":12,"y":28},"cell":{"sugar":0,"spice":4,"pollution":0},...},
         "rays":{...},"globals":{...}}
player→ {"v":1,"type":"decision","id":4302,"action":{"harvest":{"sugar":0,"spice":4}}}

game →  {"v":1,"type":"decision_request","id":4419,"gate":"trade_respond","cycle":0,
         "agent":{...},"rays":{...},"globals":{...},
         "offers":[{"offer_id":2,"from":30,
                    "give":{"sugar":0,"spice":3},"want":{"sugar":4,"spice":0}}]}
player→ {"v":1,"type":"decision","id":4419,"action":{"accept":[2]}}

game →  {"v":1,"type":"decision_request","id":4501,"gate":"lend_propose","cycle":0,
         "agent":{...},"rays":{...},"globals":{...}}
player→ {"v":1,"type":"decision","id":4501,
         "action":{"offer":{"to":30,"direction":"borrow",
                            "lend":{"sugar":6,"spice":0},
                            "repay":{"sugar":8,"spice":0},"due_tick":900}}}

  (on seat 0's socket, agent 30 receives the admitted offer and accepts)
game →  {"v":1,"type":"decision_request","id":9016,"gate":"lend_respond","cycle":0,
         "agent":{"id":30,...},"rays":{...},"globals":{...},
         "offers":[{"offer_id":0,"from":41,"direction":"borrow",
                    "lend":{"sugar":6,"spice":0},"repay":{"sugar":8,"spice":0},
                    "due_tick":900}]}
player→ {"v":1,"type":"decision","id":9016,"action":{"accept":[0]}}

  (tick 18: agent 41's own state now shows the executed contract)
         "loans":[{"contract_id":9,"role":"borrower","counterparty":30,
                   "principal":{"sugar":6,"spice":0},
                   "repay":{"sugar":8,"spice":0},"due_tick":900}]
```

## 12. Decisions proposed by this draft

Calls made here that `docs/v2-design.md` does not make. Each is open to
review; accepted ones should be reflected back into the design document
where they touch it. Rules that depend on the open design questions
G1–G8 are marked where they appear in the body and are *not* repeated
here.

1. **Agent identity is always visible** (§6.2), outside the F1 visibility
   config: targeting requires it and persistent identity is what makes
   cross-tick reputation possible, which E4 expects. (The sequential-id
   leak this creates is design question G8.)
2. **Welfare is serialized in q20 units, named `last_tick_q20` /
   `integral_q20`** (§6.1) — quantized from 32.32 for JS-safe integers
   (exact quantum and bounds pinned by G7), and explicitly the *previous*
   tick's accrual, since welfare accrues in phase-7 upkeep.
3. **Cross-seat fan-out, per-seat serial, snapshot/commit at a barrier**
   (§8): at most one outstanding request per seat, requests built from a
   frozen sub-step snapshot, resolution only at the barrier in canonical
   order, and a defined mid-sub-step fault rule.
4. **Invocation filter on agent-visible information only** (§7) — skips
   pointless invocations without leaking hidden attributes through the
   fact of invocation itself.
5. **Offer admission and normalization** (§7.3–§7.5): design-specified
   clamping applied at admission; only non-trivial, deliverable offers
   are delivered, receive ids, or count toward quiescence — inadmissible
   submissions cannot pin a negotiation phase at its cap.
6. **No outcome acknowledgments** (§7.9) and **no birth announcements**
   (§7.8): observation-driven feedback only, per P1 and poker-not-chess —
   with `mated_this_tick` (§6.1) added because execution-time voiding
   makes that one fact unknowable to an honest policy.
7. **Own-cell state (`cell`) and `initial_endowment` in own state**
   (§6.1): harvest and fertility decisions are defined against these
   numbers; both are the agent's own information.
8. **Disconnect = permanent fault, no reconnection** (§2), mirroring A3's
   uniform-across-runtimes drop rule.
9. **Malformed-vs-illegal fault line, with normative player-frame
   limits** (§3, §5, §9): shape violations (including negative
   quantities, duplicate keys, oversized frames) fault the seat;
   semantically illegal content no-ops or normalizes.
10. **Versioning: only reply-free notifications are additive** (§10);
    anything a policy must act on bumps `v`.
11. **Coordinate convention** (§6.2): origin northwest, `x` east, `y`
    south; topology itself is G5.
12. **`episode_end` carries all seats' scores and survivor counts**
    (§4.3) — public information, courtesy copy of the results artifact;
    faulted seats included in the arrays but not messaged.
13. **First-fault-wins on the platform failure artifact** (§9), with all
    faults in results metadata and the replay.
