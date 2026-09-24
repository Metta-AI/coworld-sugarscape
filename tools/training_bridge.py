"""Finite SugarLang training sessions over the shared Coworld JSONL protocol."""

# ruff: noqa: E402 - this repository runs source packages through PYTHONPATH.

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from coworld.config import load_dtl_defaults, resolve_episode_config, ruleset_limits
from coworld.episode import run_episode
from coworld.ruleset import validate_ruleset
from coworld.server import public_config
from coworld.targets import load_target_catalog, resolve_seat_targets
from players.baseline.player import choose_ruleset

CATALOG = load_target_catalog()
TARGET_IDS = tuple(sorted(CATALOG.targets))
PUBLIC_NUMERIC_FIELDS = tuple(
    sorted(
        key
        for key, value in load_dtl_defaults().items()
        if isinstance(value, (int, float, bool))
        and key
        not in {
            "seed",
            "interfaceHeight",
            "interfaceWidth",
            "agentLeader",
            "headlessMode",
            "keepAliveAtEnd",
            "profileMode",
            "screenshots",
        }
    )
) + ("measurement_window", "seats")
MAX_PROBS = max(len(target.probs or ()) for target in CATALOG.targets.values())


def compact(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class TrainingSession:
    def __init__(self, variant: str, mode: str, timesteps: int | None):
        manifest = json.loads((ROOT / "coworld_manifest.json").read_text())
        if variant == "certification":
            self.base_config = manifest["certification"]["game_config"]
        else:
            self.base_config = next(
                entry["game_config"]
                for entry in manifest["variants"]
                if entry["id"] == variant
            )
        self.mode = mode
        self.timesteps = timesteps
        self.seat = 0
        self.decision_id = 0
        self.rulesets: list[object] = []

    def reset(self, request: Mapping[str, object]) -> dict[str, object]:
        config = dict(self.base_config)
        config["seed"] = int.from_bytes(
            hashlib.sha256(str(request["seed"]).encode()).digest()[:8], "big"
        )
        if self.timesteps is not None:
            config["timesteps"] = self.timesteps
        self.config = config
        self.resolved = resolve_episode_config(config)
        self.players = int(request["players"])
        if self.players != self.resolved["seats"]:
            raise ValueError(f"Variant requires {self.resolved['seats']} players")
        self.targets = resolve_seat_targets(
            self.resolved.get("targets"),
            seats=self.players,
            measurement_window=int(self.resolved["measurement_window"]),
            catalog=CATALOG,
        )
        programs = [
            choose_ruleset(target.as_dict()) for target in CATALOG.targets.values()
        ]
        limits = ruleset_limits(self.resolved)
        self.candidates = list(
            {
                compact(program): program
                for program in programs
                if validate_ruleset(program, limits=limits).valid
            }.values()
        )
        self.seat = 0
        self.decision_id = 0
        self.rulesets = []
        return self.decision()

    def decision(self) -> dict[str, object]:
        target = self.targets[self.seat].as_dict()
        view = {"config": public_config(self.resolved), "target": target}
        if self.mode == "choice":
            view["candidate_rulesets"] = self.candidates
            schema = {
                "type": "object",
                "properties": {
                    "choice": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": len(self.candidates) - 1,
                    }
                },
                "required": ["choice"],
            }
            question = {
                "state": view,
                "instructions": "Choose one legal SugarLang ruleset to maximize this seat's final score.",
                "candidates": {
                    str(index): {"decision": {"choice": index}, "criterion": program}
                    for index, program in enumerate(self.candidates)
                },
            }
        else:
            schema = {
                "type": "object",
                "properties": {"ruleset": {"type": "object"}},
                "required": ["ruleset"],
            }
            question = None
        return {
            "kind": "decision",
            "game": "sugarscape",
            "decision_id": self.decision_id,
            "seat": self.seat,
            "engine_seat": self.seat,
            "turn": 0,
            "semantic_view": view,
            "inbox": [],
            "messages": [
                {
                    "role": "system",
                    "content": "Submit one valid SugarLang ruleset for the visible target. Higher final score wins.",
                },
                {"role": "user", "content": compact(view)},
            ],
            "speech_messages": [],
            "action_schema": schema,
            "typed_question": question,
        }

    def encode(self) -> dict[str, object]:
        if self.mode != "choice":
            raise ValueError("Numeric encoding requires choice mode")
        target = self.targets[self.seat]
        visible = public_config(self.resolved)
        values = [float(target.id == name) for name in TARGET_IDS]
        probabilities = list(target.probs or ())
        values.extend(probabilities + [0.0] * (MAX_PROBS - len(probabilities)))
        values.extend(
            float(visible[name]) / (1 + abs(float(visible[name])))
            if name in visible and isinstance(visible[name], (int, float, bool))
            else 0.0
            for name in PUBLIC_NUMERIC_FIELDS
        )
        return {
            "decision_id": self.decision_id,
            "values": values,
            "actions": [{"choice": index} for index in range(len(self.candidates))],
        }

    def teacher(self) -> dict[str, str]:
        program = choose_ruleset(self.targets[self.seat].as_dict())
        if self.mode == "choice":
            action = {"choice": self.candidates.index(program)}
        else:
            action = {"ruleset": program}
        return {"response": compact(action)}

    def step(self, request: Mapping[str, object]) -> dict[str, object]:
        if request["decision_id"] != self.decision_id:
            return {"kind": "rejected", "reason": "stale decision"}
        action = json.loads(str(request["response"]))
        if self.mode == "choice":
            choice = action["choice"]
            if type(choice) is not int or not 0 <= choice < len(self.candidates):
                return {"kind": "rejected", "reason": "illegal choice"}
            program = self.candidates[choice]
            accepted = {"choice": choice}
        else:
            program = action["ruleset"]
            validation = validate_ruleset(program, limits=ruleset_limits(self.resolved))
            if not validation.valid:
                return {
                    "kind": "rejected",
                    "reason": "; ".join(str(error) for error in validation.errors),
                }
            accepted = {"ruleset": program}
        self.rulesets.append(program)
        self.seat += 1
        self.decision_id += 1
        if self.seat < self.players:
            observation = self.decision()
        else:
            results, _, _ = run_episode(
                self.config, self.rulesets, emit_timing_logs=False
            )
            scores = {
                seat: float(score) for seat, score in enumerate(results["scores"])
            }
            world_area = int(self.resolved["environmentWidth"]) * int(
                self.resolved["environmentHeight"]
            )
            observation = {
                "kind": "terminal",
                "scores": scores,
                "utilities": {
                    seat: score
                    if self.targets[seat].kind == "distribution"
                    else score / (world_area + abs(score))
                    for seat, score in scores.items()
                },
            }
        return {"kind": "accepted", "action": accepted, "observation": observation}


def main() -> None:
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.execvpe(
            sys.executable,
            [sys.executable, *sys.argv],
            {**os.environ, "PYTHONHASHSEED": "0"},
        )
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", default="certification")
    parser.add_argument("--mode", choices=("choice", "text"), default="choice")
    parser.add_argument("--timesteps", type=int)
    args = parser.parse_args()
    session = TrainingSession(args.variant, args.mode, args.timesteps)
    for line in sys.stdin:
        request = json.loads(line)
        match request["kind"]:
            case "reset":
                response = session.reset(request)
            case "encode":
                response = session.encode()
            case "teacher":
                response = session.teacher()
            case "step":
                response = session.step(request)
            case _:
                raise ValueError(f"Unknown training command {request['kind']}")
        print(compact(response), flush=True)


if __name__ == "__main__":
    main()
