"""Small target-aware baseline player for Sugarscape v3."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from urllib.parse import urlencode

from websockets.sync.client import connect


def choose_ruleset(target: Mapping[str, object]) -> dict[str, object]:
    """Select a readable canned ruleset from the assigned target."""

    target_id = str(target.get("id", ""))
    variable = str(target.get("variable", ""))
    welfare = ["get", "cell.welfare"]
    occupied = ["get", "cell.occupied"]
    if target_id == "wellness.max":
        return {
            "version": 1,
            "traits": {"aggression": 0, "trade": 1, "lending": 1, "fertility": 1},
            "movement": [{"score": welfare}],
        }
    if target_id == "wealth.egalitarian":
        return {
            "version": 1,
            "traits": {"aggression": 0, "trade": 1, "lending": 1},
            "movement": [
                {"score": ["-", welfare, ["*", 0.5, ["get", "cell.preyWealth"]]]}
            ],
        }
    if variable == "population" or variable == "age_at_death":
        return {
            "version": 1,
            "traits": {"fertility": 1, "aggression": 0},
            "movement": [{"score": welfare}],
        }
    if variable == "majority_tribe_share":
        direction = 1 if target_id == "tribe.convergence" else -1
        return {
            "version": 1,
            "movement": [{"score": ["+", welfare, ["*", direction, occupied]]}],
        }
    if variable == "sick_fraction":
        direction = 1 if target_id == "disease.endemic" else -2
        return {
            "version": 1,
            "movement": [{"score": ["+", welfare, ["*", direction, occupied]]}],
        }
    if variable == "mean_trade_price":
        return {
            "version": 1,
            "traits": {"trade": 1, "aggression": 0},
            "movement": [{"score": welfare}],
        }
    return {"version": 1, "movement": [{"score": welfare}]}


def resolve_websocket_url(
    args: argparse.Namespace, environment: Mapping[str, str]
) -> str:
    """Prefer the platform URL and construct a local-development fallback."""

    platform_url = environment.get("COWORLD_PLAYER_WS_URL")
    if platform_url:
        return platform_url
    if args.slot is None or args.token is None:
        raise ValueError(
            "COWORLD_PLAYER_WS_URL or both --slot and --token are required"
        )
    query = urlencode({"slot": args.slot, "token": args.token})
    return f"ws://{args.host}:{args.port}/player?{query}"


def run(url: str) -> None:
    """Receive one observation, submit one valid action, and exit after ack."""

    with connect(url, max_size=64 * 1024, proxy=None) as websocket:
        observation = json.loads(websocket.recv())
        if observation.get("type") != "observation":
            raise RuntimeError("game didn't send a Sugarscape observation")
        ruleset = choose_ruleset(observation["target"])
        websocket.send(
            json.dumps({"type": "action", "ruleset": ruleset}, separators=(",", ":"))
        )
        acknowledgement = json.loads(websocket.recv())
        if (
            acknowledgement.get("type") != "ack"
            or acknowledgement.get("valid") is not True
        ):
            raise RuntimeError(
                f"game rejected bundled baseline ruleset: {acknowledgement}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sugarscape target-aware baseline player"
    )
    parser.add_argument("--host", default="game")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--slot", type=int)
    parser.add_argument("--token")
    args = parser.parse_args(argv)
    run(resolve_websocket_url(args, os.environ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
