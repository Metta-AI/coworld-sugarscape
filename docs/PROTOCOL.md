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

The effective public config contains world/mechanics settings but never contains
tokens, the drawn seed, the scenario pool/index, or any seat's target assignment.
The separate `target` object contains only this seat's assigned distribution.
The seed is disclosed later in results and replay artifacts.

Submit:

```json
{"type":"action","ruleset":{"version":1,"movement":[{"score":["get","cell.welfare"]}]}}
```

The server answers with `{"type":"ack","valid":true}`. Invalid actions receive
`{"type":"ack","valid":false,"errors":[{"path":"...","message":"..."}]}`
and may be corrected until the window closes. A seat without a valid submission
at close receives the null ruleset and is recorded with `submitted:false`.

Connected players receive a terminal `result` containing per-seat `scores`,
details, and summary scalars after artifacts are written. Players may exit after
a valid acknowledgement; the bundled baseline does so.

## Spectator connection

`WS /global` streams the same `frame` objects stored in the replay, followed by
one terminal `result`. Each spectator has a bounded queue; a slow spectator may
drop old presentation frames but cannot slow the simulation. `GET /client/global`
is a minimal raw-message browser client.

`GET /healthz` returns HTTP 200 once the submission server is ready.

## Replay

The replay is a zlib-compressed `sugarscape.replay.v3` JSON document containing
the post-episode seed, sanitized config, targets, submitted rulesets, scores,
initial grid, and presentation frames. The static viewer accepts
`index.html?replay=<url-encoded URL>`, `postMessage({type:"coworld-replay",bytes})`,
and `?chrome=off`.

Agent state uses birth/move/change upserts plus death removals. Replay-only
wealth is rounded to 50-unit display buckets to keep long episodes compact;
measurement histograms and scores retain full simulation precision.
