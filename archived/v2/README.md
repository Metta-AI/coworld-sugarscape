> [!WARNING]
> **ARCHIVAL ONLY.** Sugarscape v2 was designed but never implemented, and
> was backburnered on 2026-08-11 in favor of v3. Do not implement from these
> documents or treat them as the current design without explicitly reviving
> v2.

# Sugarscape v2 — archived design (no implementation)

v2 was a from-scratch redesign of Sugarscape (not a DTL port — platform
decision D1) whose founding principle was agent-level player control designed
in from the start: every classic behavioral rule became either a policy gate
in a phased timestep or a negotiation protocol between agents. It was
designed collaboratively over 2026-08-07 → 2026-08-11 and reached **design
complete except open question group G** (eight determinism/physics pinning
details, recorded with recommendations in `v2-design.md` §9). No game code
was ever written.

## Contents

- **`v2-design.md`** — the authoritative design record: principles, all 35
  settled questions A1–F6 with revision history, the six-gate timestep, the
  policy boundary, determinism spec, and the open G group.
- **`designs/sugarscape-v2-design-2026-08-07.html`** — the commentable
  Ink & Print HTML rendering of the same design (kept in sync through
  2026-08-11), including the review-round history and decision index.
- **`PROTOCOL.md`** — draft JSON-over-WebSocket player protocol (design-stage;
  revised after a cross-model Codex review; depends on G1–G8).
- **`issues/arena-soft-timeout-limitation.md`** — an Arena platform
  limitation written up for the Arena team during v2 design (games cannot
  express soft per-decision timeouts). The limitation is platform-scoped and
  remains true independent of v2.
- **`designs/.sugarscape-v2-design-brief.md`**,
  **`designs/.sugarscape-v2-round2-delta.md`** — working briefs from the
  design sessions (previously untracked dotfiles), committed here for
  provenance.

## Status at archive time

- All original design questions (A1–F6) resolved; major late revisions:
  one policy instance per seat (shared RAM accepted), WASM/Arena
  implementation deferred to future work, lend gate added to the timestep
  as phase 5.
- Open: G1–G8 (`v2-design.md` §9 G) — loan-collection integer algorithm,
  combat loot composition, newborn mid-tick activation, tick/`due_tick`
  domain, grid topology + coordinates, pollution fixed-point scale,
  score/welfare quantum + wire bounds, identifier opacity.

## Path references

These documents were written at the repository root; internal references
like `docs/v2-design.md`, `docs/issues/...`, and `docs/what-is-a-coworld.md`
refer to the pre-archive layout. `what-is-a-coworld.md` (the platform
reference) still lives at `docs/` in the repository root.
