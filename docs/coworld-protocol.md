# Coworld protocol

## Service and artifacts

`GET /healthz` returns `healthy` after the HTTP/WebSocket server is ready.
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

Connect to `GET /global`. The first message is the latest frame, followed by one
`sugarscape.frame.v1` JSON frame every configured `frameInterval` timesteps.
Frames contain the complete resource grid, living agent summaries, policy-slot
metadata, and canonical aggregate statistics.

The browser spectator is served at `/client/global` (also `/clients/global`).
The player-protocol explainer is at `/client/player`. `/client/replay` uses the
same viewer while a process started with `COGAME_LOAD_REPLAY_URI` publishes the
recorded frames.

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
