# Getting started with Sugarscape

Sugarscape is a coworld where you play a **lawgiver, not a joystick**. Each
episode you submit one declarative SugarLang ruleset — four societal traits
plus one movement decision list — and then watch a society of agents live
under that law for 1,000 ticks with no further input from you. Your score is
decided entirely by what your law causes.

This page is the human orientation. The normative references are
[`RULES.md`](RULES.md) (SugarLang, test-enforced against the
implementation), [`TARGETS.md`](TARGETS.md) (the target catalog and scoring
math), and [`SCENARIOS.md`](SCENARIOS.md) (the ranked-play scenario pool).
For a guided walk from "what's a target?" to a working ruleset, read the
[SugarLang tutorial](sugarlang-tutorial.md).

## The three leagues

Sugarscape runs two kinds of competition on the
[Observatory](https://softmax.com/sugarscape):

**Targeted generation — Solo and Duos.** Every episode draws one of 80
curated worlds and hands your player a *target distribution* (wealth curves,
lifespan curves, tribe splits, and more). Your player must **generate** a
ruleset conditioned on that world and target, on the spot; the score
measures how closely the society's outcome matches the target. Solo seats
one player per world; Duos seats two players in the same world with
different targets and independent scores — the other player's law reshapes
the world you're both trying to steer.

- Solo league: `league_620a74a7-eb1f-4386-b386-0e7246be4eb6`
- Duos league: `league_d5b48dfe-5e08-499f-80f1-63f14720c50c`

**Commonwealth — handcrafted.** The same canonical world every episode, and
no target distribution: you hand-craft **one fixed constitution** and its
score is the summed wellness of every citizen surviving to the final tick.
Maximize, no ceiling. Submissions pass a determinism qualifier — your player
must return byte-identical rulesets every time it is asked — so this league
rewards a carefully crafted artifact, not a clever generator.

- Commonwealth league: `league_dac00450-027a-45e6-9f6b-c9bda7ddd61d`

**If one player serves both kinds of league**, it must branch on the target
it receives: a `maximize` target (Commonwealth) means *return your fixed
constitution*; a `distribution` target means *generate for this world and
target*. The bundled baseline in [`players/baseline/`](../players/baseline/)
shows the branch.

## Run it locally

Everything scores locally, fast — a full 1,000-tick episode takes seconds
on small worlds and under about a minute on the biggest ranked ones:

```sh
git clone https://github.com/Metta-AI/coworld-sugarscape
cd coworld-sugarscape
uv sync                          # creates .venv with all dependencies
.venv/bin/python -m pytest       # the offline suite; should be all green
docker compose up                # one-seat local game + the bundled baseline
```

## The Ruleset Studio

The [Ruleset Studio](../ruleset-studio/README.md) is a local visual editor
for SugarLang: movement rules as Blockly stacks, trait sliders, live
validation by the real Python validator, and one-click save into
`rulesets/`. If you work with a coding agent, the Studio also gives you a
chat pane wired to your agent, so you can co-edit the same canvas. It is the
recommended way to hand-craft a Commonwealth constitution.

```sh
.venv/bin/python -m tools.ruleset_studio
```

## Join a league

A player is a small Docker image: it connects, reads its observation,
submits one ruleset, and exits. Set up your own player project and enter a
league with the [coworld CLI](https://github.com/Metta-AI/coworld) (its
[`COOKBOOK.md`](https://github.com/Metta-AI/coworld/blob/main/COOKBOOK.md)
covers every command below, plus the raw API):

```sh
# set up a project
mkdir sugarscape-player && cd sugarscape-player
uv init --bare && uv add "coworld[auth]"

# download the coworld (manifest, docs, protocols, baseline player)
uv run coworld download cow_049e7dc0-f4b5-49f8-81df-59ea73493b6a

# optional: run a local episode against the baseline
uv run coworld run-episode \
  ./coworld/cow_049e7dc0-f4b5-49f8-81df-59ea73493b6a/coworld_manifest.json \
  --timeout-seconds 120

# build your player image, then upload and enter a league
uv run softmax login
uv run coworld upload-policy my-player:latest --name my-player
uv run coworld submit my-player --league league_620a74a7-eb1f-4386-b386-0e7246be4eb6   # Solo
# Duos:         --league league_d5b48dfe-5e08-499f-80f1-63f14720c50c
# Commonwealth: --league league_dac00450-027a-45e6-9f6b-c9bda7ddd61d
```

Uploading a policy is routine and free; **submitting to a league is the one
gate** — it puts your policy into ranked play.

## Working with a coding agent

The fastest path: point your agent at the
[participation guide](https://softmax.com/sugarscape/play.md), which walks
it through the full loop. For a durable, growing setup, have your agent
clone the [optimizer-seed](https://github.com/Metta-AI/optimizer-seed) and
install the
[sugarscape-mixin](https://github.com/Metta-AI/sugarscape-mixin) — a
game-knowledge pack that teaches the agent SugarLang, the leagues, local
evaluation, and the Studio, and interviews you about how you want to work
before it starts.
