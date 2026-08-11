# Arena issue: games cannot express soft per-decision timeouts

**Audience:** the Arena implementation agent (metta spec 0076 stack).
**From:** Sugarscape v2 design work (`coworld-sugarscape`).
**Date:** 2026-08-10. Code references are to the unmerged stack at
`origin/jb/arena-task-*` (tip `jb/arena-task-8-tooling`) as inspected
2026-08-06 — re-verify paths against whatever has landed since.

**This document describes a limitation. It deliberately prescribes no fix.**

## The game semantics we want and cannot express

Sugarscape v2 wants a policy that misses a decision deadline to **forfeit
that one decision** — the agent takes no action at that gate (a legal no-op
in our rules) — and the seat **continues playing** the rest of the episode.
A seat should be removed only for hard faults (guest trap, protocol
violation), not for being slow once.

Under the current Arena contract this is not expressible, for three
compounding reasons:

1. **Guests have no clock.** By design (determinism), a `softmax:game`
   component cannot observe wall time — WASI is configured bare, with no
   clocks usable for gameplay. So the *game* cannot implement its own
   timeout policy; only the host can observe elapsed time.

2. **The host's only timeout vocabulary is the permanent drop.** In the
   pump (`app_backend/src/metta/app_backend/arena_runner/pump.py`), a seat
   whose `on-message` call exceeds the per-delivery deadline gets a
   `SeatFault(kind="deadline")` and is skipped for the remainder of the
   episode (`if seat in seat_faults: continue`); its executor is retired
   and its store's epoch deadline interrupts the outstanding call. There
   is no host mechanism that reports "seat X missed this delivery" to the
   game while keeping the seat alive — the game is never told which seats
   were late; it just stops receiving their `seat-message`s, permanently.

3. **The deadline itself is host deployment config, not game config.**
   `ARENA_RUNNER_PLAYER_RESPONSE_SECONDS` (default 180 s, sized for
   CTF/LLM-scale turns) applies uniformly per delivery. A game whose
   profile is thousands of sub-second decisions per episode (Sugarscape:
   ~10⁵–10⁶ tiny per-agent gate calls) has no way to declare its own
   appropriate per-decision deadline, nor different deadlines for
   different message kinds (e.g. a movement decision vs. a negotiation
   response).

## Consequences observed for game design

- Our fault rule ("a dropped seat's agents freeze forever") is the only
  rules answer the current runtime supports, and it is far harsher than
  the game itself would choose. One transient stall — a GC pause, a cold
  code path — permanently removes a competitor from a 1000-tick episode.
- The episode wall clock becomes the only bound on a slow-but-responsive
  policy: a seat answering just under the 180 s default per delivery can
  burn the shared 3600 s episode budget without ever faulting, which
  punishes the other seats, not the slow one.
- Related edge, same area: on the terminal step (`step-output.done =
  true`), player replies to the final fan-out are discarded by the pump
  (deliberate — PR #19035 discussion), so any game protocol that wants an
  acknowledged shutdown cannot get one. Minor for us, noted for
  completeness while you are in this code.

## What Sugarscape v2 does meanwhile

Design doc (`docs/v2-design.md`, §7.5 and A3/A4): time stays entirely
runtime-owned; the model defines only *responsive* vs *faulted*; a faulted
seat's agents freeze. If the runtime ever gains softer timeout semantics,
our preferred rules change is already written down (miss ⇒ that decision
is a no-op, seat lives), and our deployment guidance asks for a
per-invocation deadline of ~1–5 s for this game's profile rather than the
180 s default.
