# Coworld protocol

## Service and artifacts

`GET /healthz` returns `healthy` after the HTTP/WebSocket server is ready.
Player and global browser pages are available at `/client/player` and
`/client/global`; the plural `/clients/...` forms are aliases. Replay mode uses
the same viewer at `/client/replay` or `/clients/replay`. The spectator
WebSocket answers on both `/global` and `/replay`.

The standard Bitworld runtime reads configuration and writes artifacts through
`COGAME_CONFIG_URI`, `COGAME_RESULTS_URI`, `COGAME_SAVE_REPLAY_URI`, and
`COGAME_LOAD_REPLAY_URI`. These accept `file://`, HTTP, or HTTPS URIs.
Equivalent local development flags are `--config-path`, `--results`,
`--save-replay`, and `--load-replay`. `COGAME_HOST` and `COGAME_PORT` configure
the bind address, which defaults to `0.0.0.0:8080`.

The committed `config.json` contains obvious local-example tokens. Production
runners must replace them with fresh per-episode values and give each policy
only its own authenticated URL. Every configured slot requires one nonempty
token, either at the matching index of top-level `tokens` or in the slot's
`token` field; startup fails rather than exposing an unauthenticated slot.

## Player socket

Connect to `GET /player?slot=N&token=T` with a WebSocket upgrade. A slot owns a
configured set of agent decision-model labels, so one socket controls a whole
population. Decisions are requested synchronously in the shuffled activation
order.

The game sends:

```json
{
  "type": "observation",
  "requestId": 12,
  "slot": 0,
  "timestep": 4,
  "world": {"width": 32, "height": 32},
  "agent": {
    "id": 19,
    "cell": 241,
    "age": 4,
    "sugar": 11,
    "spice": 7,
    "sugarMetabolism": 2,
    "spiceMetabolism": 1,
    "decisionModel": "population-a",
    "tribe": -1,
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

## Global and replay sockets

Connect to `GET /global` or its alias `GET /replay`. Both names serve the same
stream; `/replay` is the sibling socket a browser derives when the viewer is
served at `/client/replay`, and the path the Coworld certifier probes for replay
liveness.

A spectator joining a live episode in progress first receives up to the most
recent 300 `sugarscape.frame.v1` frames in order, then receives one live frame
every configured `frameInterval` timesteps without a gap. Frames contain the
complete sugar/spice/pollution grid, living agent summaries (including display
attributes), friend/mate/active-loan links, policy-slot metadata, the scheduled
`maxTimestep`, and an immutable snapshot of the canonical aggregate statistics.
Each streamed frame also carries a server-generated `streamId`. The spectator
uses it to discard buffered frames when a reconnect reaches a new server run,
while repeated frames from the same run are deduplicated by timestep.

A process started with `COGAME_LOAD_REPLAY_URI` publishes the whole recording
into the backlog at once and then keeps serving until it is stopped, so a
spectator who connects at any later moment still receives every recorded frame.
Replay mode does not trim the backlog and does not pace the stream; the browser
owns playback.

The browser viewer is served at `/client/global` and `/client/replay` (with the
plural `/clients/...` aliases). It is one self-contained document with every
asset inlined, because the hosted embed is a sandboxed iframe behind a proxy
that rewrites the base href and cannot reach a CDN. It presents the episode as a
broadcast: the sugar lattice with each policy's settlers rendered on it, a
standing on the score axis, a lead chart, an event feed derived by diffing
consecutive frames, the canonical inequality and carrying-capacity readouts, and
play/pause/step/scrub/speed controls. It never mutates simulation state or
consumes randomness. The player-protocol explainer is at `/client/player`.

The viewer is generated from `viewer/` into `src/sugarscape/viewer.html` by
`tools/build_viewer.py`, which inlines the vendored typefaces and the art batch;
`coworld.nim` embeds the result with `staticRead`, so the generated file is
committed and `tools/test_all.sh` fails when it is stale.

Replay artifacts use:

```json
{
  "format": "sugarscape.replay.v1",
  "config": {"seed": 8675309},
  "frames": []
}
```

`config` is the effective validated configuration, including the concrete seed
chosen for an input seed of `-1`.

## Results

The results artifact contains parallel arrays by slot: `names`, integer
`scores`, `population`, `mean_wealth`, `decision_requests`,
`actions_received`, and `fallbacks`, plus `final_stats`.

`scores[i]` is the final living population's total sugar plus spice, truncated
to an integer. Scoring is read-only: it does not mutate state or consume RNG.
