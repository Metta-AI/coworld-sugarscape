# Coworld protocol

## Service and artifacts

`GET /healthz` returns `healthy` after the HTTP/WebSocket server is ready.
Legacy replay mode remains available after loading and publishing its frames;
the hosting platform owns the server process lifetime. Hosted replay links use
the manifest's static replay-viewer bundle instead and do not start this
process.
Player and global browser pages are available at `/client/player` and
`/client/global`; the plural `/clients/...` forms are aliases. Replay mode uses
the same viewer at `/client/replay` or `/clients/replay`.

The standard Bitworld runtime reads configuration and writes artifacts through
`COGAME_CONFIG_URI`, `COGAME_RESULTS_URI`, `COGAME_SAVE_REPLAY_URI`, and
`COGAME_LOAD_REPLAY_URI`. These accept `file://`, HTTP, or HTTPS URIs.
Equivalent local development flags are `--config-path`, `--results`,
`--save-replay`, and `--load-replay`. `COGAME_HOST` and `COGAME_PORT` configure
the bind address, which defaults to `0.0.0.0:8080`.

The committed `config.json` contains obvious local-example tokens. Production
runners must replace them with fresh per-episode values and give each policy
only its own authenticated URL. In `onePlayerPerAgent` mode, every player seat
requires one nonempty token at the matching index of top-level `tokens`.
Startup fails unless the player count equals `startingAgents`. Legacy
population slots may instead carry a `token` field.

## Player socket

Connect to `GET /player?slot=N&token=T` with a WebSocket upgrade. In the default
`onePlayerPerAgent` contract, seat `N` exclusively controls initial agent ID
`N`; the default roster therefore has 64 seats for 64 initial agents. Decisions
are requested synchronously in the shuffled activation order. The optional
legacy `slots` configuration can still assign populations by decision-model
label when `onePlayerPerAgent` is false.

The game sends:

```json
{
  "type": "observation",
  "requestId": 12,
  "slot": 0,
  "timestep": 4,
  "world": {"width": 32, "height": 32},
  "agent": {
    "id": 0,
    "cell": 241,
    "age": 4,
    "sugar": 11,
    "spice": 7,
    "sugarMetabolism": 2,
    "spiceMetabolism": 1,
    "decisionModel": "none",
    "tribe": 0,
    "race": -1,
    "sick": false
  },
  "candidates": [
    {
      "cell": 209,
      "welfare": 17.4,
      "distance": 1,
      "sugar": 3,
      "spice": 2,
      "pollution": 0,
      "occupied": false
    }
  ]
}
```

The policy replies:

```json
{"type":"action","requestId":12,"cell":209}
```

The request is bound to the authenticated socket and slot. The selected cell
must appear in that request's candidates. A malformed, spoofed, late, missing,
or illegal response is ignored; after `decisionTimeoutMs`, the game uses
`candidates[0]` and increments the slot's fallback count. The timeout defaults
to 100 milliseconds.

Only movement is delegated. Collection, combat, tagging, trade, reproduction,
lending, disease, metabolism, aging, and all RNG consumption remain inside the
canonical simulation.

When `playerTribes` is true, each player seat is also a fixed combat tribe: an
agent's tribe equals its controlling seat index. With one agent per player,
combat therefore occurs between players rather than between randomly assigned
cultural groups. Cultural tag copying (`agentTagging`) is incompatible with
fixed player tribes and is rejected at startup.

## Global and replay sockets

Connect to `GET /global`; replay runtimes expose the same stream at the required
`GET /replay` alias. A spectator joining an episode in progress first receives
up to the most recent 300 `sugarscape.frame.v1` frames in order, then receives
one live frame every configured `frameInterval` timesteps without a gap. Frames
contain the complete sugar/spice/pollution grid, living agent
summaries (including display attributes), friend/mate/active-loan links,
policy-slot metadata, and an immutable snapshot of the canonical aggregate
statistics. Each streamed frame also carries a server-generated `streamId`.
The spectator uses it to discard buffered frames when a reconnect reaches a
new server run, while repeated frames from the same run are deduplicated by
timestep.

The browser spectator is served at `/client/global` (also `/clients/global`).
It provides selectable resource and agent-color modes, social-link overlays,
cell/agent inspection, a live statistic series with timestep and value axes, a
wealth histogram with a stable observed wealth domain, a normalized Lorenz
curve, and buffered play/pause/step/scrub controls. The histogram measures each
living agent's current sugar plus spice; the Lorenz curve compares cumulative
population share with cumulative wealth share. The player-protocol explainer is
at `/client/player`. `/client/replay` uses the same viewer while a legacy
process started with `COGAME_LOAD_REPLAY_URI` publishes the recorded frames.

New replay artifacts are deterministic zlib streams. Inflating one produces a
UTF-8 JSON document with metadata stored once and compact frame rows:

```json
{
  "format": "sugarscape.replay.v2",
  "config": {"seed": 8675309},
  "width": 32,
  "height": 32,
  "slots": [],
  "agentFields": ["id", "cell"],
  "statFields": ["population"],
  "keyframeInterval": 100,
  "frames": []
}
```

`config` is the effective validated configuration, including the concrete seed
chosen for an input seed of `-1`. Each frame is
`[timestep, keyframe, cells, agents, links, stats]`. A keyframe has a complete
row-major cell array; other frames contain changed cells as
`[cellIndex, sugar, spice, pollution]`. Agent and statistic rows use the
top-level column lists. Frame zero and every 100th recorded frame are keyframes,
so arbitrary seeks apply at most 99 deltas.

The static bundle declared by `game.replay_viewer.bundle` fetches and indexes
the complete artifact before rendering frame zero in a paused state. It retains
all compact frames and supports pause, step, seek, rewind, playback speed, and
bounded random access. It also accepts historical uncompressed
`sugarscape.replay.v1` documents. The legacy native replay server accepts both
formats and expands v2 rows back to `sugarscape.frame.v1` messages.

## Results

The results artifact contains parallel arrays by slot: `names`, integer
`scores`, `population`, `mean_wealth`, `decision_requests`,
`actions_received`, and `fallbacks`, plus `final_stats`.

`scores[i]` is the final living population's total sugar plus spice, truncated
to an integer. Scoring is read-only: it does not mutate state or consume RNG.
