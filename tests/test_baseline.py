from __future__ import annotations

import argparse

import pytest

from coworld.ruleset import validate_ruleset
from coworld.targets import load_target_catalog
from players.baseline.player import choose_ruleset, resolve_websocket_url


def test_every_catalog_target_selects_a_valid_canned_ruleset() -> None:
    for target in load_target_catalog().targets.values():
        result = validate_ruleset(choose_ruleset(target.as_dict()))
        assert result.valid, (target.id, result.errors)


def test_platform_url_takes_priority_over_local_flags() -> None:
    args = argparse.Namespace(host="ignored", port=1, slot=7, token="ignored")
    assert resolve_websocket_url(args, {"COWORLD_PLAYER_WS_URL": "ws://platform/player?slot=0&token=x"}) == (
        "ws://platform/player?slot=0&token=x"
    )


def test_local_fallback_requires_slot_and_token() -> None:
    args = argparse.Namespace(host="127.0.0.1", port=8080, slot=None, token=None)
    with pytest.raises(ValueError, match="required"):
        resolve_websocket_url(args, {})

    args.slot = 2
    args.token = "a token"
    assert resolve_websocket_url(args, {}) == "ws://127.0.0.1:8080/player?slot=2&token=a+token"
