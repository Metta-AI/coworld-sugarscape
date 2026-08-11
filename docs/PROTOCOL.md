# Sugarscape v2 — Player Protocol

**Status: DRAFT (2026-08-11) — design-stage specification; no implementing
code exists yet.** This is the concrete wire schema for the interface that
`docs/v2-design.md` settles semantically (F3 encoding, §6 gates, §7 policy
boundary). It is the protocol the coworld manifest will declare as
`manifest.game.protocols.player`. Where this draft makes a call the design
document does not, the call is listed in [§12 Decisions proposed by this
draft](#12-decisions-proposed-by-this-draft) for review; one flagged
inconsistency in the design document is recorded there too.

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
   the full public game config.
4. **Decision loop** — the game sends `decision_request` messages (§4.2);
   the policy answers each with a `decision` (§5). This is the entire
   in-episode vocabulary. There are no outcome acknowledgments: results of
   actions are learned from subsequent observations (§7.8).
5. **`episode_end`** (§4.3) — final scores; the game then closes the socket
   with WebSocket code 1000. The player exits cleanly.

**Disconnect is a fault.** A socket that closes before `episode_end` faults
the seat permanently (A3 freeze); the protocol has no reconnection. This
mirrors Arena, which drops a faulted seat permanently.

## 3. Envelope and conventions

Every message, both directions, is a single UTF-8 JSON object:

```json
{"v": 1, "type": "<message-type>", ...}
```

- **`v`** — protocol major version, integer. This document specifies `1`.
- **`type`** — one of `episode_start`, `decision_request`, `episode_end`
  (game → player) or `decision` (player → game).
- **Integers only.** Every number in every message is a JSON integer — no
  floats anywhere, matching the all-integer determinism spec (design §7.7).
  Fixed-point welfare is carried in scaled integer units (§6.1). All values
  fit comfortably below 2⁵³, so plain JSON numbers are safe in every
  language including JavaScript.
- **Unknown fields must be ignored** by both sides, and **unknown
  game→player message types must be ignored** by players. This is the
  additive-evolution seam (§10). An unknown *player→game* type is a
  protocol violation (§9).
- One JSON object per WebSocket text frame. No batching, no binary frames.

### Identifiers

| id | assigned by | scope / lifetime |
|---|---|---|
| `slot` (= seat) | platform | episode |
| agent `id` | core, creation order: initial agents `0..total_agents-1`, then newborns sequentially | episode; never reused |
| request `id` | shell, monotonically increasing from 0 | connection; echoed verbatim by the reply |
| `offer_id` | core, from 0 | one (tick, gate, cycle) sub-step |
| `contract_id` (loans) | core, from 0 | episode |

Agent ids are deterministic (creation order is seeded world evolution), so
they are identical across live runs, replays, and future runtimes.

## 4. Game → player messages

### 4.1 `episode_start`

```json
{
  "v": 1,
  "type": "episode_start",
  "slot": 3,
  "seats": 4,
  "config": { "...": "the full public game config, verbatim" }
}
```

`config` is the complete effective config of design §4 — map dimensions,
capacity grids (or built-in name plus the generated grids), growback,
seasons, pollution, disease, feature flags, combat α, visibility
configuration, `score_reduce`, `newborn_assignment`, episode length, round
caps. It is public information (it ships in replays), and it is sent
**once**; nothing in it is repeated in per-decision messages except the
current tick and season state.

Deliberately absent: a roster of the seat's agents. P1 admits no
population-scoped message; the seat learns its agent ids as invocations
arrive (§7.7). Since every agent is invoked at the movement gate of tick 0,
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
  `mate_propose`, `mate_respond`, `tribe` (§7).
- `cycle` — negotiation cycle number, 0-based; present only on the four
  negotiation gates.
- `offers` — present only on the two respond gates: the offers addressed to
  this agent in this cycle (shapes in §7.3–§7.4).
- `season` is present only when seasons are enabled. Throughout the
  protocol, absent means absent, not null.

The observation is built at invocation time. Under sequential movement (E1)
this matters: each movement request reflects every move already executed
this tick — full information is the point.

### 4.3 `episode_end`

```json
{
  "v": 1,
  "type": "episode_end",
  "tick": 1000,
  "scores": [512034, 498211, 623890, 407112],
  "survivors": [11, 9, 14, 6]
}
```

`scores[i]` is seat *i*'s final published score exactly as written to the
results artifact (integer; survivor tie-break bits included per B6/F6);
`survivors[i]` the seat's living agents at the end. Public information,
provided as a courtesy — the results JSON is authoritative.

## 5. Player → game: `decision`

The only message a policy sends:

```json
{"v": 1, "type": "decision", "id": 4211, "action": {"move": {"x": 12, "y": 31}}}
```

- `id` echoes the `decision_request` being answered.
- `action` holds exactly one action form valid for the request's gate (§7),
  or the universal explicit no-op:

```json
{"v": 1, "type": "decision", "id": 4211, "action": {"pass": true}}
```

`pass` is legal at every gate (E9): stay put, harvest nothing, offer
nothing, decline everything, keep your tribe.

**Semantic illegality is a no-op, not a fault** (E9): an out-of-range move,
an ineligible mating proposal, an over-holdings `give`, an unknown
`offer_id` in an accept list — each resolves exactly as `pass` (a bad
`offer_id` is simply ignored within an otherwise-valid accept list), never
penalized beyond its own opportunity cost. Faults are reserved for
*protocol* violations (§9): the boundary is "well-formed answer to the
question asked" vs "not an answer."

## 6. The observation

### 6.1 Own state (`agent`)

Complete per design F1, with the one `max_age` knob:

```json
{
  "id": 41,
  "seat": 3,
  "pos": {"x": 12, "y": 30},
  "holdings":   {"sugar": 22, "spice": 9},
  "metabolism": {"sugar": 2,  "spice": 1},
  "vision": 3,
  "age": 14,
  "max_age": 87,
  "sex": "female",
  "fertility": {"start": 14, "end": 40},
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
  "welfare": {"tick_q20": 1348271, "integral_q20": 20981134}
}
```

- `max_age` is omitted when config hides it even from self (F1's mortality
  knob).
- `sex`, `fertility` appear only when fertility is enabled; `tribe`,
  `tribeless` only when tribes are; `immune`, `diseases`, `sick` only when
  disease is. `diseases` lists the bit-strings currently infecting the
  agent (its immune string is its own state; C4).
- `loans` lists live contracts in both directions (`role` is this agent's
  side). `counterparty` tracks inheritance: if the other party died and an
  heir assumed the contract (E6), the id is the heir's.
- **Welfare units:** `tick_q20` and `integral_q20` are the fixed-point
  welfare values in units of 2⁻²⁰ — the published-score quantum F6 already
  defines. The core computes in 32.32; the observation quantizes to q20 for
  JSON-safe integers. The pair exists so the quantity being optimized is
  legible to the policy (B2).

### 6.2 Visible world (`rays`)

Classic von Neumann rays: four arrays, one per direction, each listing
cells outward from the agent's position, up to `vision` cells (truncated at
the map edge; the grid does not wrap unless config says otherwise — grid
topology is config, restated in `episode_start`).

```json
"rays": {
  "n": [ {"x": 12, "y": 29, "sugar": 3, "spice": 0, "pollution": 2, "occupant": null},
         {"x": 12, "y": 28, "sugar": 0, "spice": 4, "pollution": 0,
          "occupant": {"id": 77, "seat": 0, "holdings": {"sugar": 14, "spice": 2},
                       "tribe": 0, "sick": true}} ],
  "e": [ "..." ], "s": [ "..." ], "w": [ "..." ]
}
```

- Cell resource values are current levels (capacity is known from config).
- `occupant` is `null` for empty cells. For occupied cells it contains the
  **agent id plus exactly the attributes the visibility config exposes**
  (F1): hidden attributes are omitted entirely, so the ranked-default
  occupant is `{id, seat, holdings, tribe, sick}`.
- The agent **id is always visible** and not configurable. Identity is
  required for targeting (offers, proposals name an `id`) and deliberately
  enables cross-tick reputation, which the design expects policies to keep
  in instance memory (E4). What you can *learn about* an agent is
  configurable; *that it is the same agent* is not.
- Vision is movement range: any listed cell is a legal movement target
  (occupied ⇒ combat, E2).

## 7. Gates and actions

The per-tick gate order is design §6: `move` (sequential), `harvest`,
`trade` cycles, `mate` cycles, `tribe`. Phases for disabled features are
skipped entirely.

**Invocation filter.** At every gate the game invokes an agent only if a
non-`pass` action is plausibly available, judged **only on information the
agent can already see** — so being invoked leaks nothing the agent didn't
have (poker stays poker under F1's hidden-attribute regimes):

| gate | invoked iff |
|---|---|
| `move` | always (every living agent, every tick) |
| `harvest` | own cell holds any resource |
| `trade_propose` | ≥ 1 adjacent occupant |
| `trade_respond` | ≥ 1 offer addressed to the agent this cycle |
| `mate_propose` | agent is itself eligible (own fertility window, wealth ≥ own initial endowment) **and** has ≥ 1 adjacent occupant — partner eligibility is *not* pre-checked, since it may be hidden |
| `mate_respond` | ≥ 1 proposal addressed to the agent this cycle |
| `tribe` | always, when tribes are enabled |

A non-invoked agent implicitly passes. Faulted seats' agents are never
invoked (A3).

### 7.1 `move`

Sequential, episode-seeded order, one agent at a time across the whole
population (E1). Action:

```json
{"move": {"x": 12, "y": 31}}
```

Target must be a visible (in-ray) cell. Empty target: relocation. Occupied
target with combat enabled: the same action **is** the attack (E2); the
legality check (poorer-only, cross-tribe — or the hidden-holdings variant's
richer-wins rule) is physics, applied on execution. Illegal target: no-op.
`pass`: stay.

### 7.2 `harvest`

Order-free fan-out. Action names per-resource amounts, clamped to the
cell's current levels (E3):

```json
{"harvest": {"sugar": 3, "spice": 0}}
```

### 7.3 `trade_propose` / `trade_respond` — the exchange phase

Runs propose/respond cycles to quiescence, capped at `trade_rounds` (E4).
The phase carries **both spot barter (E4) and credit contracts (E6)** —
one economic proposal per agent per cycle, of either kind, to one adjacent
agent. (This merged reading resolves a design-doc gap — see §12.)

Propose action, barter:

```json
{"offer": {"to": 77, "kind": "barter",
           "give": {"sugar": 3, "spice": 0},
           "want": {"sugar": 0, "spice": 2}}}
```

Propose action, credit (either direction, E6):

```json
{"offer": {"to": 12, "kind": "credit", "direction": "borrow",
           "lend":  {"sugar": 5, "spice": 0},
           "repay": {"sugar": 6, "spice": 0},
           "due_tick": 700}}
```

`direction: "lend"` — proposer lends, acceptor borrows; principal flows
proposer → acceptor now, `repay` flows back at `due_tick`.
`direction: "borrow"` — proposer asks to borrow; the acceptor becomes the
lender and principal flows acceptor → proposer on acceptance.
`due_tick` must be ≤ episode length (physics; violating it voids the offer
as illegal → no-op).

Respond request carries the offers addressed to this agent:

```json
"offers": [
  {"offer_id": 3, "from": 77, "kind": "barter",
   "give": {"sugar": 3, "spice": 0}, "want": {"sugar": 0, "spice": 2}},
  {"offer_id": 4, "from": 12, "kind": "credit", "direction": "borrow",
   "lend": {"sugar": 5, "spice": 0}, "repay": {"sugar": 6, "spice": 0},
   "due_tick": 700}
]
```

(`give`/`want`/`lend`/`repay` are stated from the proposer's perspective in
both directions of the wire — the acceptor of offer 3 pays 2 spice and
receives 3 sugar.)

Respond action — accept any subset by id; everything unlisted is declined:

```json
{"accept": [3]}
```

Acceptances execute in episode-seeded order; any acceptance no longer
payable at execution voids (E4). Under hidden holdings, `want` is unclamped
and the same voiding rule absorbs unpayable acceptances (F1). Countering is
structural: decline now, propose back next cycle. A cycle in which no
offers were submitted ends the phase.

### 7.4 `mate_propose` / `mate_respond`

Same cycle machinery, capped at `mating_rounds` (E5). Propose:

```json
{"propose": {"to": 55}}
```

Respond request:

```json
"offers": [ {"offer_id": 1, "from": 55} ]
```

Respond action: `{"accept": [1]}`. Accepted matings execute in seeded
order, **re-validating full eligibility at execution** — including the
one-mating-per-agent-per-tick cap and the empty-cell requirement for the
child (none ⇒ the mating voids). Accepting several proposals is legal;
physics voids all but the first executed. Child genetics, placement, and
seat assignment are entirely sim-side (D5, A2) — no protocol surface.

### 7.5 `tribe`

Order-free fan-out, when tribes are enabled (E7). Declare a switch,
effective next tick:

```json
{"tribe": 2}
```

or, when the `tribeless` variant flag is on: `{"tribeless": true}` (rejoin
with `{"tribe": k}` later). `pass`: keep current allegiance.

### 7.6 What has no gate

Combat (inside `move`), loan collection and shortfall handling (phase-6
physics, E6), metabolism, aging, death, estates, disease transmission and
immune response, welfare accrual — all sim-side. Policies see the
consequences in their next observation.

### 7.7 Newborns

A newborn's controlling seat starts receiving `decision_request`s for the
new agent id at the child's first gate — there is no birth announcement
(P1: no population-scoped or roster messages). The first such observation
is self-describing: `age: 0`, endowed holdings, position. Under per-seat
instances (design §7.2) no new connection or instance is involved; the
existing socket simply carries one more agent id.

### 7.8 No acknowledgments, by design

The game never reports an action's outcome. Whether a move, attack, offer,
or acceptance took effect is learned from the next observation (holdings,
position, the world) — voided proposals *are* information (F1's
poker-not-chess), and within a negotiation phase each cycle's observation
already reflects the previous cycle's executed exchanges.

## 8. Concurrency, ordering, deadlines

- **`move` is globally sequential**: at most one outstanding
  `decision_request` in the entire episode at a time (E1).
- **All other gates are fan-outs** (`harvest`, `tribe`, and each
  propose/respond sub-step): the game may **pipeline** requests — several
  outstanding on one socket, at most **one per agent**. Replies may arrive
  in any order; correlation is by request `id` only. A policy is free to
  answer strictly in arrival order — pipelining is a game-side liberty, not
  a player-side obligation.
- **Sub-step barrier:** a new gate or cycle sub-step begins only after
  every outstanding request of the previous one has resolved (reply or
  fault). Requests from two different sub-steps are never interleaved on a
  socket.
- **Deadline:** each request carries a per-decision deadline owned by the
  runtime — the WS shell's `decision_timeout_seconds` config (order of
  seconds; design §7.5), Arena's per-delivery deadline later. The game
  itself has no notion of wall-clock time and no game-level budget (A4).
- **Timeout (interim rule, design §7.5):** a missed deadline is a seat
  fault — permanent, A3 freeze. When Arena gains soft-timeout semantics,
  both shells will switch in the same release to: missed deadline ⇒ that
  one decision resolves as `pass`, seat keeps playing. The message
  vocabulary is unchanged by that future switch.

## 9. Faults

A **seat fault** permanently removes the seat (A3): its agents freeze, the
socket is closed (WebSocket code 1008), and the game writes
`{message, failed_policy_index}` to `COGAME_PLAYER_FAILURE_URI` (platform
contract). Fault causes:

- missed per-decision deadline (interim rule, §8);
- disconnect before `episode_end` (§2);
- **protocol violation**: a frame that is not valid JSON, not a
  `decision`-typed object with a well-formed envelope, an `id` that matches
  no outstanding request, a duplicate reply, an `action` whose *shape* is
  invalid for the gate (e.g. `{"harvest": ...}` answering a `move`
  request), or a non-integer number anywhere.

Contrast with §5: a well-formed answer whose content is *semantically*
illegal (bad target, unpayable amounts, unknown `offer_id` entries) is a
no-op, never a fault. The fault line is malformed-vs-illegal, not
smart-vs-dumb.

Other seats are not notified of a fault; a frozen seat's agents are simply
observable standing still.

## 10. Versioning

- `v` is the protocol major version; this document is `v: 1`.
- Additive changes — new optional fields, new game→player message types —
  do **not** bump `v`; the ignore-unknown rules (§3) absorb them.
- Anything else — removing or renaming fields, changing units or id
  semantics, new required player behavior — bumps `v`.
- The manifest's `protocols.player` value names this protocol and version;
  a policy seeing an unexpected `v` in `episode_start` should fail fast
  rather than guess.

## 11. Worked example

Tick 17, seat 3's agent 41 is invoked at the movement gate; it attacks a
poorer cross-tribe neighbor two cells north (visible in `rays.n[1]`), then
later the same tick receives one barter offer and accepts it.

```
game →  {"v":1,"type":"decision_request","id":4211,"gate":"move",
         "agent":{"id":41,...},"rays":{...},
         "globals":{"tick":17,"episode_length":1000}}
player→ {"v":1,"type":"decision","id":4211,"action":{"move":{"x":12,"y":28}}}

          (combat resolves sim-side: agent 77 dies, 41 loots min(α, 16), takes the cell)

game →  {"v":1,"type":"decision_request","id":4302,"gate":"harvest",
         "agent":{"id":41,"pos":{"x":12,"y":28},...},"rays":{...},"globals":{...}}
player→ {"v":1,"type":"decision","id":4302,"action":{"harvest":{"sugar":0,"spice":4}}}

game →  {"v":1,"type":"decision_request","id":4419,"gate":"trade_respond","cycle":0,
         "agent":{...},"rays":{...},"globals":{...},
         "offers":[{"offer_id":2,"from":30,"kind":"barter",
                    "give":{"sugar":0,"spice":3},"want":{"sugar":4,"spice":0}}]}
player→ {"v":1,"type":"decision","id":4419,"action":{"accept":[2]}}
```

## 12. Decisions proposed by this draft

Calls made here that `docs/v2-design.md` does not make, plus one flagged
inconsistency. Each is open to review; accepted ones should be reflected
back into the design document where they touch it.

1. **Flagged design inconsistency — lending has no phase.** The canonical
   timestep (design §6) lists five gates — move, harvest, trade, mate,
   tribe — but §7.3's action table adds a sixth, `lend` (E6 negotiation),
   with no phase to run in. This draft resolves it by **merging credit
   offers into the trade phase** (§7.3): one economic proposal per agent
   per cycle, `kind: barter | credit`, sharing `trade_rounds` and the
   one-offer-per-proposer anti-double-spend property. Rationale: E6 calls
   lending "the third instance of the E4 shape" with identical adjacency
   and consent structure. The alternative — a separate lend phase between
   mate and tribe with its own `lend_rounds` — costs an extra fan-out per
   tick. **The design doc needs the chosen answer recorded either way.**
2. **Agent identity is always visible** (§6.2), outside the F1 visibility
   config: targeting requires it and persistent identity is what makes
   cross-tick reputation possible, which E4 expects.
3. **Welfare is serialized in q20 units** (§6.1) — the F6 published-score
   quantum — rather than raw 32.32 (JS-unsafe above 2⁵³) or decimal
   strings.
4. **Pipelined fan-outs with per-request correlation** (§8); movement alone
   is one-at-a-time. Sub-step barriers keep cycles well-defined.
5. **Invocation filter on agent-visible information only** (§7) — skips
   pointless invocations without leaking hidden attributes through the fact
   of invocation itself.
6. **No outcome acknowledgments** (§7.8) and **no birth announcements**
   (§7.7): observation-driven feedback only, per P1 and poker-not-chess.
7. **Disconnect = permanent fault, no reconnection** (§2), mirroring A3's
   uniform-across-runtimes drop rule.
8. **Malformed-vs-illegal fault line** (§5, §9): schema violations fault
   the seat; semantically illegal actions no-op.
9. **`episode_end` carries all seats' scores and survivor counts** (§4.3) —
   public information, courtesy copy of the results artifact.
