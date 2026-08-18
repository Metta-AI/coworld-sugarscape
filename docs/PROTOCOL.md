# Sugarscape v3 protocol

Sugarscape uses JSON messages over WebSocket. The protocol identifier is
`sugarscape-v3/1`. A player submits one SugarLang ruleset; there is no player
I/O while the simulation runs.

## Player connection

Connect to `WS /player?slot=<n>&token=<t>`. Invalid slots, tokens, and duplicate
connections are rejected during the HTTP handshake, before WebSocket upgrade.
Incoming messages are limited to 64 KiB; an oversized frame closes with code
1009. The default submission window is 180 monotonic seconds and closes early
when every seat has submitted a valid action.

The game first sends:

```json
{
  "type": "observation",
  "protocol": "sugarscape-v3/1",
  "seat": 0,
  "config": {"seats": 2, "timesteps": 1000},
  "target": {
    "id": "wealth.skewed-gini-0.5",
    "kind": "distribution",
    "variable": "wealth",
    "scope": "global",
    "support": [0, 1000],
    "bins": [0, 25, 50],
    "probs": [0.4, 0.6],
    "window": 100,
    "source": "..."
  },
  "ruleset_schema": {
    "version": 1,
    "limits": {"max_nodes": 256, "max_depth": 16, "max_bytes": 32768}
  }
}
```

Commonwealth sends a scalar objective instead of a histogram:

```json
{
  "id": "wellness.max",
  "kind": "maximize",
  "variable": "wellness",
  "description": "Maximize the summed normalized DTL happiness of agents surviving to the final tick."
}
```

The effective public config contains world/mechanics settings but never contains
tokens, the drawn seed, the scenario pool/index, or any seat's target assignment.
The separate `target` object contains only this seat's assigned target. Omitted
`kind` on an older or inline target means `distribution`; objective targets
carry no support, bins, probabilities, scope, or target-level window.
The seed is disclosed later in results and replay artifacts.

Submit:

```json
{"type":"action","ruleset":{"version":1,"movement":[{"score":["get","cell.welfare"]}]}}
```

The server answers with `{"type":"ack","valid":true}`. Invalid actions receive
`{"type":"ack","valid":false,"errors":[{"path":"...","message":"..."}]}`
and may be corrected until the window closes. A seat without a valid submission
at close receives the null ruleset and is recorded with `submitted:false`.

Connected players receive a terminal `result` containing `score_method`,
per-seat `scores`, details, and summary scalars after artifacts are written.
Players may exit after a valid acknowledgement; the bundled baseline does so.

Every seat detail includes a versioned `score_method` and a
`ruleset_sha256`. The hash is SHA-256 over compact, sorted-key JSON for the
validated normalized ruleset (`null` hashes as JSON `null`), so it identifies
canonical SugarLang semantics rather than original wire whitespace or key order.
Distribution targets use `w1-hyperbolic/1`; Commonwealth uses
`wellness-sum/1`. The top-level result `score_method` reports the episode's
method (episodes never mix target kinds).

Scoring includes a survival rule (2026-08-11): a seat's score is 0 unless its
target's scope population is alive at the final tick — any living agent for
global-scope targets, the seat's own agents for seat scope. Window samples
banked before a collapse do not count; the per-seat detail records the outcome
under `died_before_end`.

Commonwealth uses implicit seat scope. Its score is the sum of each final
survivor's mean normalized DTL happiness over the final measurement window.
The detail also reports survivor count, mean wellness, and mean health,
conflict, social, family, and wealth happiness components. Its score is
non-negative but intentionally not bounded by 1. The legacy aggregate keys
`score.match_mean` and `score.match_min` remain for platform compatibility and
aggregate the active score method.

## Spectator connection

`WS /global` sends an immediate
`{"type":"status","protocol":"sugarscape-v3/1","phase":"submission_window"|"run","seats":N,"submitted":M}`
greeting on connect (the hosted runner's viewer probe requires a first message
within 10 seconds, long before players may have submitted), then streams the
same `frame` objects stored in the replay, followed by one terminal `result`.
Each spectator has a bounded queue; a slow spectator may drop old presentation
frames but cannot slow the simulation. `GET /client/global` is a minimal
raw-message browser client.

After the terminal result, the server remains available briefly for late
spectators. An established spectator remains open until its peer disconnects or
the player submission timeout elapses (180 seconds by default), and
protocol-level Ping frames receive automatic Pong responses throughout that
interval.

The initial `status` greeting is immediate, but the server briefly paces the
first live `frame`. This keeps control frames ahead of a burst of simulation
messages when a client performs Ping/Pong before it begins consuming the stream.

`GET /healthz` returns HTTP 200 once the submission server is ready.

## Replay

The replay is a zlib-compressed `sugarscape.replay.v3` JSON document containing
the post-episode seed, sanitized config, targets, submitted rulesets, scores,
the `score_method` identifier, initial grid, and presentation frames. Results
carry the same method identifier; each seat detail includes raw Wasserstein-1
distance (`raw_w1`), its target-derived scale (`w1_scale`), and diagnostic
Jensen-Shannon divergence. The static viewer accepts
`index.html?replay=<url-encoded URL>`, `postMessage({type:"coworld-replay",bytes})`,
and `?chrome=off`.

Agent state uses birth/move/change upserts plus death removals. Replay-only
wealth is rounded to 50-unit display buckets to keep long episodes compact;
measurement histograms and scores retain full simulation precision.
Periodic Commonwealth frames carry the running wellness sum, survivor count,
mean wellness, and component means instead of a distribution match overlay.
