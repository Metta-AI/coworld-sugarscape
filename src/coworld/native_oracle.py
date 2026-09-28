"""Typed parity snapshot for the pinned Python and native simulators."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
import random
from typing import Mapping

from .measurement import MeasurementAgent, MeasurementDeath, MeasurementTick
from .ruleset import evaluate_reference, validate_ruleset
from .simulation import CoworldSugarscape


SCHEMA_VERSION = 7
SOURCE_PIN = "585282e9ce7b22a33b89abb0d777917bd5887d1a"
def _closed(raw: Mapping[str, object], expected: set[str], location: str) -> None:
    if set(raw) != expected:
        raise ValueError(f"{location} fields must be {', '.join(sorted(expected))}")


def _int(value: object, location: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{location} must be an integer >= {minimum}")
    return value


def _number(value: object, location: str) -> int | float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{location} must be a finite non-negative number")
    return value


def _signed_number(value: object, location: str) -> int | float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{location} must be a finite number")
    return value


def _digest(value: object) -> str:
    canonical = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _sha256(value: object, location: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{location} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True)
class NativeSnapshot:
    config_sha256: str
    ruleset_sha256: tuple[str, ...]
    rulesets: tuple[object, ...]
    timestep: int
    world_gini: float
    world_mean_wealth: float
    width: int
    height: int
    sugar_regrow_rate: int | float
    spice_regrow_rate: int | float
    max_cell_distance: int
    max_combat_loot: int | float
    max_tribes: int
    inheritance_policy: str
    next_agent_id: int
    depression_percentage: int | float
    rng_words: tuple[int, ...]
    rng_index: int
    live_order: tuple[int, ...]
    cells: tuple[
        tuple[int | float, int | float, int | float, int | float, int | None], ...
    ]
    agents: tuple[tuple[int | float, ...], ...]
    creditor_tombstones: tuple[tuple[int, str, tuple[int, ...]], ...]
    ordered_candidates: tuple[tuple[tuple[int, int | float], ...], ...]
    ordered_neighbors: tuple[tuple[int, ...], ...]
    diseases: tuple[tuple[object, ...], ...]
    remaining_disease_ids: tuple[int, ...]
    deaths: tuple[tuple[int, int, int, str], ...]

    def measurement_tick(self) -> MeasurementTick:
        """Convert this completed native tick into simulator-neutral measurements."""

        return MeasurementTick(
            agents=tuple(
                MeasurementAgent(
                    agent_id=int(agent[0]),
                    seat=int(agent[1]),
                    sugar=float(agent[4]),
                    spice=float(agent[5]),
                    age=float(agent[6]),
                    tribe=int(agent[27]),
                    sick=bool(agent[38]),
                    trade_volume=float(agent[31]),
                    sugar_price=float(agent[32]),
                    spice_price=float(agent[33]),
                    happiness=float(agent[71]),
                    wellness_components=(
                        float(agent[68]),
                        float(agent[66]),
                        float(agent[69]),
                        float(agent[67]),
                        float(agent[70]),
                    ),
                )
                for agent in self.agents
            ),
            deaths=tuple(
                MeasurementDeath(seat=seat, age=float(age))
                for _agent_id, seat, age, _cause in self.deaths
            ),
        )

    @classmethod
    def from_json(cls, raw: object) -> NativeSnapshot:
        if not isinstance(raw, Mapping):
            raise ValueError("snapshot must be an object")
        keys = {
            "schemaVersion",
            "sourcePin",
            "configurationSha256",
            "rulesetSha256",
            "rulesets",
            "timestep",
            "worldGini",
            "worldMeanWealth",
            "width",
            "height",
            "sugarRegrowRate",
            "spiceRegrowRate",
            "maxCellDistance",
            "maxCombatLoot",
            "maxTribes",
            "inheritancePolicy",
            "nextAgentId",
            "depressionPercentage",
            "rng",
            "liveOrder",
            "cells",
            "agents",
            "creditorTombstones",
            "orderedCandidates",
            "orderedNeighbors",
            "diseases",
            "remainingDiseaseIds",
            "deaths",
        }
        _closed(raw, keys, "snapshot")
        if raw["schemaVersion"] != SCHEMA_VERSION or raw["sourcePin"] != SOURCE_PIN:
            raise ValueError("snapshot schemaVersion or sourcePin is unsupported")
        config_sha256 = _sha256(
            raw["configurationSha256"],
            "configurationSha256",
        )
        raw_ruleset_hashes = raw["rulesetSha256"]
        if not isinstance(raw_ruleset_hashes, list) or not raw_ruleset_hashes:
            raise ValueError("rulesetSha256 must be a non-empty array")
        ruleset_sha256 = tuple(
            _sha256(value, f"rulesetSha256[{index}]")
            for index, value in enumerate(raw_ruleset_hashes)
        )
        raw_rulesets = raw["rulesets"]
        if not isinstance(raw_rulesets, list) or len(raw_rulesets) != len(
            ruleset_sha256
        ):
            raise ValueError("rulesets must contain one normalized ruleset per hash")
        rulesets = []
        for index, value in enumerate(raw_rulesets):
            validation = validate_ruleset(value)
            if not validation.valid or validation.normalized != value:
                raise ValueError(
                    f"rulesets[{index}] must be a normalized SugarLang ruleset"
                )
            if _digest(value) != ruleset_sha256[index]:
                raise ValueError(
                    f"rulesets[{index}] does not match rulesetSha256[{index}]"
                )
            rulesets.append(value)
        width = _int(raw["width"], "width", 1)
        height = _int(raw["height"], "height", 1)
        max_cell_distance = _int(raw["maxCellDistance"], "maxCellDistance")
        max_combat_loot = _number(raw["maxCombatLoot"], "maxCombatLoot")
        max_tribes = _int(raw["maxTribes"], "maxTribes", 1)
        if raw["inheritancePolicy"] not in {"none", "children"}:
            raise ValueError("inheritancePolicy must be none or children")
        next_agent_id = _int(raw["nextAgentId"], "nextAgentId")
        depression_percentage = _number(
            raw["depressionPercentage"], "depressionPercentage"
        )
        if depression_percentage > 1:
            raise ValueError("depressionPercentage must be <= 1")
        rng = raw["rng"]
        if not isinstance(rng, Mapping):
            raise ValueError("rng must be an object")
        _closed(rng, {"version", "words", "index", "gaussNext"}, "rng")
        words = rng["words"]
        if (
            rng["version"] != 3
            or rng["gaussNext"] is not None
            or not isinstance(words, list)
            or len(words) != 624
        ):
            raise ValueError(
                "rng must be an unbuffered CPython MT19937 version 3 state"
            )
        rng_words = tuple(_int(word, "rng.words") for word in words)
        if any(word > 0xFFFFFFFF for word in rng_words):
            raise ValueError("rng.words values must fit uint32")
        rng_index = _int(rng["index"], "rng.index")
        if rng_index > 624:
            raise ValueError("rng.index must be <= 624")

        raw_cells = raw["cells"]
        raw_agents = raw["agents"]
        raw_tombstones = raw["creditorTombstones"]
        raw_order = raw["liveOrder"]
        raw_candidates = raw["orderedCandidates"]
        raw_neighbors = raw["orderedNeighbors"]
        raw_deaths = raw["deaths"]
        raw_diseases = raw["diseases"]
        raw_remaining_diseases = raw["remainingDiseaseIds"]
        count = width * height
        if not isinstance(raw_cells, list) or len(raw_cells) != count:
            raise ValueError("cells must contain width * height entries")
        if (
            not isinstance(raw_agents, list)
            or not isinstance(raw_tombstones, list)
            or not isinstance(raw_order, list)
        ):
            raise ValueError("agents, creditorTombstones, and liveOrder must be arrays")
        if not isinstance(raw_candidates, list) or len(raw_candidates) != count:
            raise ValueError("orderedCandidates must contain width * height arrays")
        if not isinstance(raw_neighbors, list) or len(raw_neighbors) != count:
            raise ValueError("orderedNeighbors must contain width * height arrays")
        if not isinstance(raw_deaths, list):
            raise ValueError("deaths must be an array")

        cells = []
        for index, cell in enumerate(raw_cells):
            if not isinstance(cell, Mapping):
                raise ValueError(f"cells[{index}] must be an object")
            _closed(
                cell,
                {"sugar", "maxSugar", "spice", "maxSpice", "occupantId"},
                f"cells[{index}]",
            )
            occupant = cell["occupantId"]
            sugar = _number(cell["sugar"], "cell.sugar")
            max_sugar = _number(cell["maxSugar"], "cell.maxSugar")
            spice = _number(cell["spice"], "cell.spice")
            max_spice = _number(cell["maxSpice"], "cell.maxSpice")
            if sugar > max_sugar:
                raise ValueError("cell.sugar must not exceed cell.maxSugar")
            if spice > max_spice:
                raise ValueError("cell.spice must not exceed cell.maxSpice")
            cells.append(
                (
                    sugar,
                    max_sugar,
                    spice,
                    max_spice,
                    None if occupant is None else _int(occupant, "cell.occupantId"),
                )
            )

        agent_keys = {
            "id",
            "seat",
            "x",
            "y",
            "sugar",
            "spice",
            "age",
            "sugarMetabolism",
            "spiceMetabolism",
            "vision",
            "movement",
            "maxAge",
            "lookaheadFactor",
            "visionModifier",
            "movementModifier",
            "sugarMetabolismModifier",
            "spiceMetabolismModifier",
            "aggressionFactor",
            "aggressionFactorModifier",
            "fertilityFactor",
            "fertilityFactorModifier",
            "depressed",
            "happinessUnit",
            "maxFriends",
            "friendlinessModifier",
            "happinessModifier",
            "tags",
            "tribe",
            "tagging",
            "tradeFactor",
            "marginalRateOfSubstitution",
            "tradeVolume",
            "sugarPrice",
            "spicePrice",
            "lastTradeTimestep",
            "lastTradePartners",
            "diseaseProtectionChance",
            "immuneSystem",
            "diseases",
            "born",
            "startingSugar",
            "startingSpice",
            "sex",
            "fertilityAge",
            "infertilityAge",
            "inheritancePolicy",
            "lendingFactor",
            "baseInterestRate",
            "loanDuration",
            "sugarMeanIncome",
            "spiceMeanIncome",
            "startingImmuneSystem",
            "racialTags",
            "fatherId",
            "motherId",
            "childrenIds",
            "mateIds",
            "lastMovedTimestep",
            "lastReproducedTimestep",
            "lastMates",
            "lastLendedTimestep",
            "lastLoans",
            "creditorLoans",
            "debtorLoans",
            "friends",
            "lastCombatTimestep",
            "conflictHappiness",
            "familyHappiness",
            "healthHappiness",
            "socialHappiness",
            "wealthHappiness",
            "happiness",
        }
        agents = []
        for index, agent in enumerate(raw_agents):
            if not isinstance(agent, Mapping):
                raise ValueError(f"agents[{index}] must be an object")
            _closed(agent, agent_keys, f"agents[{index}]")
            max_age = agent["maxAge"]
            if (
                isinstance(max_age, bool)
                or not isinstance(max_age, int)
                or max_age < -1
            ):
                raise ValueError("agent.maxAge must be -1 or a non-negative integer")
            raw_tags = agent["tags"]
            if raw_tags is not None and not isinstance(raw_tags, list):
                raise ValueError("agent.tags must be null or an array")
            parsed_tags = (
                None
                if raw_tags is None
                else tuple(_int(tag, "agent.tags") for tag in raw_tags)
            )
            values = (
                _int(agent["id"], "agent.id"),
                _int(agent["seat"], "agent.seat"),
                _int(agent["x"], "agent.x"),
                _int(agent["y"], "agent.y"),
                _number(agent["sugar"], "agent.sugar"),
                _number(agent["spice"], "agent.spice"),
                _int(agent["age"], "agent.age"),
                _number(agent["sugarMetabolism"], "agent.sugarMetabolism"),
                _number(agent["spiceMetabolism"], "agent.spiceMetabolism"),
                _int(agent["vision"], "agent.vision"),
                _int(agent["movement"], "agent.movement"),
                max_age,
                _number(agent["lookaheadFactor"], "agent.lookaheadFactor"),
                _int(agent["visionModifier"], "agent.visionModifier", minimum=-(2**63)),
                _int(
                    agent["movementModifier"],
                    "agent.movementModifier",
                    minimum=-(2**63),
                ),
                _signed_number(
                    agent["sugarMetabolismModifier"],
                    "agent.sugarMetabolismModifier",
                ),
                _signed_number(
                    agent["spiceMetabolismModifier"],
                    "agent.spiceMetabolismModifier",
                ),
                _number(agent["aggressionFactor"], "agent.aggressionFactor"),
                _signed_number(
                    agent["aggressionFactorModifier"],
                    "agent.aggressionFactorModifier",
                ),
                _number(agent["fertilityFactor"], "agent.fertilityFactor"),
                _signed_number(
                    agent["fertilityFactorModifier"],
                    "agent.fertilityFactorModifier",
                ),
                agent["depressed"],
                _number(agent["happinessUnit"], "agent.happinessUnit"),
                _int(agent["maxFriends"], "agent.maxFriends"),
                _signed_number(
                    agent["friendlinessModifier"], "agent.friendlinessModifier"
                ),
                _signed_number(agent["happinessModifier"], "agent.happinessModifier"),
                parsed_tags,
                None if agent["tribe"] is None else _int(agent["tribe"], "agent.tribe"),
                agent["tagging"],
                _number(agent["tradeFactor"], "agent.tradeFactor"),
                _number(
                    agent["marginalRateOfSubstitution"],
                    "agent.marginalRateOfSubstitution",
                ),
                _int(agent["tradeVolume"], "agent.tradeVolume"),
                _number(agent["sugarPrice"], "agent.sugarPrice"),
                _number(agent["spicePrice"], "agent.spicePrice"),
                agent["lastTradeTimestep"],
                _int(agent["lastTradePartners"], "agent.lastTradePartners"),
                _number(
                    agent["diseaseProtectionChance"], "agent.diseaseProtectionChance"
                ),
                None,
                (),
                _int(agent["born"], "agent.born"),
                _number(agent["startingSugar"], "agent.startingSugar"),
                _number(agent["startingSpice"], "agent.startingSpice"),
                None if agent["sex"] is None else agent["sex"],
                _int(agent["fertilityAge"], "agent.fertilityAge"),
                _int(agent["infertilityAge"], "agent.infertilityAge"),
                agent["inheritancePolicy"],
                _number(agent["lendingFactor"], "agent.lendingFactor"),
                _number(agent["baseInterestRate"], "agent.baseInterestRate"),
                _int(agent["loanDuration"], "agent.loanDuration"),
                _number(agent["sugarMeanIncome"], "agent.sugarMeanIncome"),
                _number(agent["spiceMeanIncome"], "agent.spiceMeanIncome"),
                None,
                None,
                agent["fatherId"],
                agent["motherId"],
                (),
                (),
                agent["lastMovedTimestep"],
                agent["lastReproducedTimestep"],
                _int(agent["lastMates"], "agent.lastMates"),
                agent["lastLendedTimestep"],
                _int(agent["lastLoans"], "agent.lastLoans"),
                (),
                (),
                (),
                agent["lastCombatTimestep"],
                _signed_number(agent["conflictHappiness"], "agent.conflictHappiness"),
                _signed_number(agent["familyHappiness"], "agent.familyHappiness"),
                _signed_number(agent["healthHappiness"], "agent.healthHappiness"),
                _signed_number(agent["socialHappiness"], "agent.socialHappiness"),
                _signed_number(agent["wealthHappiness"], "agent.wealthHappiness"),
                _signed_number(agent["happiness"], "agent.happiness"),
            )
            if not isinstance(values[21], bool):
                raise ValueError("agent.depressed must be a boolean")
            tags, tribe, tagging = values[26:29]
            if not isinstance(tagging, bool):
                raise ValueError("agent.tagging must be a boolean")
            if tags is not None:
                if not tags or any(tag not in {0, 1} for tag in tags):
                    raise ValueError("agent.tags must be null or a non-empty bit array")
                tribe_size = (len(tags) + 1) / max_tribes
                expected = min(
                    math.ceil((tags.count(0) + 1) / tribe_size) - 1, max_tribes - 1
                )
                if tribe != expected:
                    raise ValueError("agent.tribe is inconsistent with tags")
            elif tribe is not None or tagging:
                raise ValueError("null tags require null tribe and disabled tagging")
            for field in (
                "tradeFactor",
                "marginalRateOfSubstitution",
                "sugarPrice",
                "spicePrice",
                "diseaseProtectionChance",
            ):
                _number(agent[field], f"agent.{field}")
            if agent["diseaseProtectionChance"] > 1:
                raise ValueError("agent.diseaseProtectionChance must be <= 1")
            for field in ("tradeVolume", "lastTradePartners"):
                _int(agent[field], f"agent.{field}")
            if isinstance(agent["lastTradeTimestep"], bool) or not isinstance(
                agent["lastTradeTimestep"], int
            ):
                raise ValueError("agent.lastTradeTimestep must be an integer")
            immune = agent["immuneSystem"]
            if immune is not None and (
                not isinstance(immune, list) or any(bit not in (0, 1) for bit in immune)
            ):
                raise ValueError("agent.immuneSystem must be null or a bit array")
            infections = agent["diseases"]
            if not isinstance(infections, list):
                raise ValueError("agent.diseases must be an array")
            parsed_infections = []
            for infection in infections:
                _closed(
                    infection,
                    {
                        "diseaseId",
                        "startIndex",
                        "endIndex",
                        "infectorId",
                        "caught",
                        "incubation",
                    },
                    "infection",
                )
                disease_id = _int(infection["diseaseId"], "infection.diseaseId")
                start_index = infection["startIndex"]
                end_index = infection["endIndex"]
                if (start_index is None) != (end_index is None):
                    raise ValueError(
                        "infection range indices must both be null or integers"
                    )
                if start_index is not None:
                    start_index = _int(start_index, "infection.startIndex")
                    end_index = _int(end_index, "infection.endIndex")
                    if end_index < start_index:
                        raise ValueError("infection range must be ordered")
                infector_id = infection["infectorId"]
                if infector_id is not None:
                    infector_id = _int(infector_id, "infection.infectorId")
                parsed_infections.append(
                    (
                        disease_id,
                        start_index,
                        end_index,
                        infector_id,
                        _int(infection["caught"], "infection.caught"),
                        _int(infection["incubation"], "infection.incubation"),
                    )
                )
            if len({infection[0] for infection in parsed_infections}) != len(
                parsed_infections
            ):
                raise ValueError("agent disease IDs must be unique")
            bits = agent["startingImmuneSystem"]
            if bits is not None and (
                not isinstance(bits, list) or any(bit not in (0, 1) for bit in bits)
            ):
                raise ValueError(
                    "agent.startingImmuneSystem must be null or a bit array"
                )
            racial_tags = agent["racialTags"]
            if racial_tags is not None and (
                not isinstance(racial_tags, list)
                or any(
                    isinstance(tag, bool) or not isinstance(tag, int) or tag < 0
                    for tag in racial_tags
                )
            ):
                raise ValueError(
                    "agent.racialTags must be null or non-negative integers"
                )
            starting_immune = agent["startingImmuneSystem"]
            if (starting_immune is None) != (immune is None) or (
                immune is not None and len(starting_immune) != len(immune)
            ):
                raise ValueError(
                    "starting and current immune systems must have matching shape"
                )
            if agent["sex"] not in {None, "female", "male"}:
                raise ValueError("agent.sex must be null, female, or male")
            if agent["inheritancePolicy"] not in {"none", "children"}:
                raise ValueError("agent.inheritancePolicy must be none or children")
            if agent["infertilityAge"] < agent["fertilityAge"]:
                raise ValueError("agent infertilityAge must be >= fertilityAge")
            for field in (
                "lastMovedTimestep",
                "lastReproducedTimestep",
                "lastLendedTimestep",
                "lastCombatTimestep",
            ):
                if isinstance(agent[field], bool) or not isinstance(agent[field], int):
                    raise ValueError(f"agent.{field} must be an integer")
            for field in ("fatherId", "motherId"):
                if agent[field] is not None:
                    _int(agent[field], f"agent.{field}")
            relations = []
            for field in ("childrenIds", "mateIds"):
                raw_ids = agent[field]
                if not isinstance(raw_ids, list):
                    raise ValueError(f"agent.{field} must be an array")
                parsed_ids = tuple(_int(value, f"agent.{field}") for value in raw_ids)
                if len(set(parsed_ids)) != len(parsed_ids):
                    raise ValueError(f"agent.{field} must contain unique IDs")
                relations.append(parsed_ids)
            parsed_loan_lists = []
            for field in ("creditorLoans", "debtorLoans"):
                raw_loans = agent[field]
                if not isinstance(raw_loans, list):
                    raise ValueError(f"agent.{field} must be an array")
                parsed_loans = []
                for loan in raw_loans:
                    if not isinstance(loan, Mapping):
                        raise ValueError("loan must be an object")
                    _closed(
                        loan,
                        {
                            "creditorId",
                            "debtorId",
                            "sugarLoan",
                            "spiceLoan",
                            "loanDuration",
                            "loanOrigin",
                        },
                        "loan",
                    )
                    parsed_loans.append(
                        (
                            _int(loan["creditorId"], "loan.creditorId"),
                            _int(loan["debtorId"], "loan.debtorId"),
                            _number(loan["sugarLoan"], "loan.sugarLoan"),
                            _number(loan["spiceLoan"], "loan.spiceLoan"),
                            _int(loan["loanDuration"], "loan.loanDuration", 1),
                            _int(loan["loanOrigin"], "loan.loanOrigin"),
                        )
                    )
                parsed_loan_lists.append(tuple(parsed_loans))
            raw_friends = agent["friends"]
            if not isinstance(raw_friends, list):
                raise ValueError("agent.friends must be an array")
            friends = []
            for friend in raw_friends:
                if not isinstance(friend, Mapping):
                    raise ValueError("agent.friends entries must be objects")
                _closed(friend, {"id", "hammingDistance"}, "agent.friend")
                friends.append(
                    (
                        _int(friend["id"], "agent.friend.id"),
                        _int(friend["hammingDistance"], "agent.friend.hammingDistance"),
                    )
                )
            if len(friends) > values[23]:
                raise ValueError("agent.friends must not exceed maxFriends")
            values = (
                values[:37]
                + (None if immune is None else tuple(immune), tuple(parsed_infections))
                + values[39:51]
                + (
                    None if starting_immune is None else tuple(starting_immune),
                    None if agent["racialTags"] is None else tuple(agent["racialTags"]),
                    agent["fatherId"],
                    agent["motherId"],
                    relations[0],
                    relations[1],
                )
                + values[57:62]
                + (parsed_loan_lists[0], parsed_loan_lists[1], tuple(friends))
                + values[65:]
            )
            if values[2] >= width or values[3] >= height:
                raise ValueError("agent position is outside the world")
            agents.append(values)
        ids = [int(agent[0]) for agent in agents]
        tombstones = []
        for index, tombstone in enumerate(raw_tombstones):
            if not isinstance(tombstone, Mapping):
                raise ValueError(f"creditorTombstones[{index}] must be an object")
            _closed(
                tombstone,
                {"id", "inheritancePolicy", "childrenIds"},
                f"creditorTombstones[{index}]",
            )
            if tombstone["inheritancePolicy"] not in {"none", "children"}:
                raise ValueError(
                    "creditor tombstone inheritancePolicy must be none or children"
                )
            raw_children = tombstone["childrenIds"]
            if not isinstance(raw_children, list):
                raise ValueError("creditor tombstone childrenIds must be an array")
            children = tuple(
                _int(child_id, "creditor tombstone childrenIds")
                for child_id in raw_children
            )
            if len(set(children)) != len(children):
                raise ValueError(
                    "creditor tombstone childrenIds must contain unique IDs"
                )
            tombstones.append(
                (
                    _int(tombstone["id"], "creditor tombstone id"),
                    tombstone["inheritancePolicy"],
                    children,
                )
            )
        tombstone_ids = [tombstone[0] for tombstone in tombstones]
        if tombstone_ids != sorted(set(tombstone_ids)) or set(tombstone_ids) & set(ids):
            raise ValueError(
                "creditor tombstones must be ID-sorted, unique, and absent from agents"
            )
        known_ids = ids + tombstone_ids
        if known_ids and next_agent_id <= max(known_ids):
            raise ValueError(
                "nextAgentId must exceed every live agent and tombstone ID"
            )
        if any(agent[28] for agent in agents) and any(
            agent[26] is None for agent in agents
        ):
            raise ValueError("every agent must have tags when tagging is enabled")
        if any(
            max(0, agent[17] + agent[18]) > 0 and agent[26] is None for agent in agents
        ):
            raise ValueError("combat requires agent tags and tribes")
        live_order = tuple(_int(value, "liveOrder") for value in raw_order)
        if ids != sorted(set(ids)) or sorted(live_order) != ids:
            raise ValueError(
                "agents must be ID-sorted and liveOrder must be its permutation"
            )
        occupants = [cell[4] for cell in cells if cell[4] is not None]
        if sorted(occupants) != ids:
            raise ValueError("cell occupancy must match live agents")
        for agent in agents:
            cell_index = int(agent[2]) * height + int(agent[3])
            if cells[cell_index][4] != int(agent[0]):
                raise ValueError("cell occupancy disagrees with agent position")
        creditor_records = Counter(loan for agent in agents for loan in agent[62])
        debtor_records = Counter(loan for agent in agents for loan in agent[63])
        for agent in agents:
            if any(loan[1] != agent[0] for loan in agent[62]):
                raise ValueError("creditorLoans debtorId must name the owning agent")
            if any(loan[0] != agent[0] for loan in agent[63]):
                raise ValueError("debtorLoans creditorId must name the owning agent")
        live_ids = set(ids)
        for loan, record_count in creditor_records.items():
            if loan[0] in live_ids and debtor_records[loan] != record_count:
                raise ValueError(
                    "live creditor and debtor loan records must be mirrored"
                )
        for loan, record_count in debtor_records.items():
            if loan[1] in live_ids and creditor_records[loan] != record_count:
                raise ValueError(
                    "live creditor and debtor loan records must be mirrored"
                )
        missing_creditors = {
            int(loan[0]) for loan in creditor_records if loan[0] not in live_ids
        }
        if set(tombstone_ids) != missing_creditors:
            raise ValueError(
                "creditor tombstones must exactly match missing loan creditors"
            )

        candidates = []
        for origin, entries in enumerate(raw_candidates):
            if not isinstance(entries, list):
                raise ValueError(f"orderedCandidates[{origin}] must be an array")
            parsed = []
            for entry in entries:
                if not isinstance(entry, list) or len(entry) != 2:
                    raise ValueError("candidate entries must be [cellIndex, distance]")
                target = _int(entry[0], "candidate index")
                if target >= count:
                    raise ValueError("candidate index is outside the world")
                distance = _number(entry[1], "candidate distance")
                if distance == 0 or distance > max_cell_distance:
                    raise ValueError("candidate distance is outside maxCellDistance")
                parsed.append((target, distance))
            targets = [entry[0] for entry in parsed]
            if len(set(targets)) != len(targets) or origin in targets:
                raise ValueError(
                    "ordered candidates must be unique and exclude their origin"
                )
            candidates.append(tuple(parsed))
        neighbors = []
        for entries in raw_neighbors:
            if not isinstance(entries, list):
                raise ValueError("orderedNeighbors entries must be arrays")
            parsed_neighbors = tuple(_int(entry, "neighbor index") for entry in entries)
            if any(entry >= count for entry in parsed_neighbors):
                raise ValueError("neighbor index is outside the world")
            neighbors.append(parsed_neighbors)
        disease_keys = {
            "id",
            "aggressionPenalty",
            "fertilityPenalty",
            "friendlinessPenalty",
            "happinessPenalty",
            "incubationPeriod",
            "movementPenalty",
            "spiceMetabolismPenalty",
            "startTimestep",
            "sugarMetabolismPenalty",
            "tags",
            "transmissionChance",
            "visionPenalty",
            "recoverable",
            "infectedIds",
        }
        if not isinstance(raw_diseases, list):
            raise ValueError("diseases must be an array")
        for disease in raw_diseases:
            if not isinstance(disease, Mapping):
                raise ValueError("disease must be an object")
            _closed(disease, disease_keys, "disease")
        # Preserve an explicit stable field order independent of set iteration.
        disease_fields = (
            "id",
            "aggressionPenalty",
            "fertilityPenalty",
            "friendlinessPenalty",
            "happinessPenalty",
            "incubationPeriod",
            "movementPenalty",
            "spiceMetabolismPenalty",
            "startTimestep",
            "sugarMetabolismPenalty",
            "tags",
            "transmissionChance",
            "visionPenalty",
            "recoverable",
            "infectedIds",
        )
        diseases = [
            tuple(
                None
                if disease[field] is None
                else tuple(disease[field])
                if field in {"tags", "infectedIds"}
                else disease[field]
                for field in disease_fields
            )
            for disease in raw_diseases
        ]
        for disease in raw_diseases:
            _int(disease["id"], "disease.id")
        disease_ids = [disease[0] for disease in diseases]
        if disease_ids != sorted(set(disease_ids)):
            raise ValueError("disease IDs must be unique and ID-sorted")
        disease_by_id = {disease[0]: disease for disease in diseases}
        raw_disease_by_id = {disease["id"]: disease for disease in raw_diseases}
        for disease in diseases:
            for index in (1, 2, 3, 4, 7, 9):
                _signed_number(disease[index], f"disease.{disease_fields[index]}")
            for index in (5, 8):
                _int(disease[index], f"disease.{disease_fields[index]}")
            for index in (6, 12):
                if isinstance(disease[index], bool) or not isinstance(
                    disease[index], int
                ):
                    raise ValueError(
                        f"disease.{disease_fields[index]} must be an integer"
                    )
            chance = _number(disease[11], "disease.transmissionChance")
            if chance > 1:
                raise ValueError("disease.transmissionChance must be <= 1")
            if disease[10] is not None and (
                not isinstance(raw_disease_by_id[disease[0]]["tags"], list)
                or any(bit not in (0, 1) for bit in disease[10])
            ):
                raise ValueError("disease tags must be null or a bit array")
            if not isinstance(disease[13], bool):
                raise ValueError("disease.recoverable must be a boolean")
            if not isinstance(raw_disease_by_id[disease[0]]["infectedIds"], list):
                raise ValueError("disease.infectedIds must be an array")
            infected_ids = tuple(
                _int(value, "disease.infectedIds") for value in disease[14]
            )
            if len(set(infected_ids)) != len(infected_ids):
                raise ValueError("disease.infectedIds must be unique")
        recorded_infections: dict[int, set[int]] = {
            disease_id: set() for disease_id in disease_ids
        }
        for agent in agents:
            for infection in agent[38]:
                disease_id, start_index, end_index = infection[:3]
                if disease_id not in disease_by_id:
                    raise ValueError("infection names an unknown disease")
                tags = disease_by_id[disease_id][10]
                if tags is None:
                    if start_index is not None:
                        raise ValueError(
                            "untagged disease requires a null immune range"
                        )
                elif (
                    start_index is None
                    or agent[37] is None
                    or end_index - start_index + 1 != len(tags)
                    or end_index >= len(agent[37])
                ):
                    raise ValueError(
                        "infection immune range must exactly match disease tags"
                    )
                recorded_infections[disease_id].add(int(agent[0]))
        for disease in diseases:
            if set(disease[14]) != recorded_infections[disease[0]]:
                raise ValueError(
                    "disease.infectedIds must match agent infection records"
                )
        remaining_disease_ids = tuple(
            _int(value, "remainingDiseaseIds") for value in raw_remaining_diseases
        )
        if remaining_disease_ids:
            raise ValueError("scheduled disease introduction is unsupported")
        deaths = []
        for index, death in enumerate(raw_deaths):
            if not isinstance(death, Mapping):
                raise ValueError(f"deaths[{index}] must be an object")
            _closed(death, {"id", "seat", "age", "cause"}, f"deaths[{index}]")
            cause = death["cause"]
            if cause not in {"starvation", "aging", "combat"}:
                raise ValueError("death cause must be starvation, aging, or combat")
            deaths.append(
                (
                    _int(death["id"], "death.id"),
                    _int(death["seat"], "death.seat"),
                    _int(death["age"], "death.age"),
                    str(cause),
                )
            )
        death_ids = [death[0] for death in deaths]
        if len(set(death_ids)) != len(death_ids) or set(death_ids) & set(ids):
            raise ValueError("death ids must be unique and absent from living agents")
        return cls(
            config_sha256,
            ruleset_sha256,
            tuple(rulesets),
            _int(raw["timestep"], "timestep"),
            _number(raw["worldGini"], "worldGini"),
            _number(raw["worldMeanWealth"], "worldMeanWealth"),
            width,
            height,
            _number(raw["sugarRegrowRate"], "sugarRegrowRate"),
            _number(raw["spiceRegrowRate"], "spiceRegrowRate"),
            max_cell_distance,
            max_combat_loot,
            max_tribes,
            raw["inheritancePolicy"],
            next_agent_id,
            depression_percentage,
            rng_words,
            rng_index,
            live_order,
            tuple(cells),
            tuple(agents),
            tuple(tombstones),
            tuple(candidates),
            tuple(neighbors),
            tuple(diseases),
            remaining_disease_ids,
            tuple(deaths),
        )

    def as_json(self) -> dict[str, object]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "sourcePin": SOURCE_PIN,
            "configurationSha256": self.config_sha256,
            "rulesetSha256": list(self.ruleset_sha256),
            "rulesets": list(self.rulesets),
            "timestep": self.timestep,
            "worldGini": self.world_gini,
            "worldMeanWealth": self.world_mean_wealth,
            "width": self.width,
            "height": self.height,
            "sugarRegrowRate": self.sugar_regrow_rate,
            "spiceRegrowRate": self.spice_regrow_rate,
            "maxCellDistance": self.max_cell_distance,
            "maxCombatLoot": self.max_combat_loot,
            "maxTribes": self.max_tribes,
            "inheritancePolicy": self.inheritance_policy,
            "nextAgentId": self.next_agent_id,
            "depressionPercentage": self.depression_percentage,
            "rng": {
                "version": 3,
                "words": list(self.rng_words),
                "index": self.rng_index,
                "gaussNext": None,
            },
            "liveOrder": list(self.live_order),
            "cells": [
                {
                    "sugar": sugar,
                    "maxSugar": max_sugar,
                    "spice": spice,
                    "maxSpice": max_spice,
                    "occupantId": occupant,
                }
                for sugar, max_sugar, spice, max_spice, occupant in self.cells
            ],
            "agents": [
                dict(
                    zip(
                        (
                            "id",
                            "seat",
                            "x",
                            "y",
                            "sugar",
                            "spice",
                            "age",
                            "sugarMetabolism",
                            "spiceMetabolism",
                            "vision",
                            "movement",
                            "maxAge",
                            "lookaheadFactor",
                            "visionModifier",
                            "movementModifier",
                            "sugarMetabolismModifier",
                            "spiceMetabolismModifier",
                            "aggressionFactor",
                            "aggressionFactorModifier",
                            "fertilityFactor",
                            "fertilityFactorModifier",
                            "depressed",
                            "happinessUnit",
                            "maxFriends",
                            "friendlinessModifier",
                            "happinessModifier",
                            "tags",
                            "tribe",
                            "tagging",
                            "tradeFactor",
                            "marginalRateOfSubstitution",
                            "tradeVolume",
                            "sugarPrice",
                            "spicePrice",
                            "lastTradeTimestep",
                            "lastTradePartners",
                            "diseaseProtectionChance",
                            "immuneSystem",
                            "diseases",
                            "born",
                            "startingSugar",
                            "startingSpice",
                            "sex",
                            "fertilityAge",
                            "infertilityAge",
                            "inheritancePolicy",
                            "lendingFactor",
                            "baseInterestRate",
                            "loanDuration",
                            "sugarMeanIncome",
                            "spiceMeanIncome",
                            "startingImmuneSystem",
                            "racialTags",
                            "fatherId",
                            "motherId",
                            "childrenIds",
                            "mateIds",
                            "lastMovedTimestep",
                            "lastReproducedTimestep",
                            "lastMates",
                            "lastLendedTimestep",
                            "lastLoans",
                            "creditorLoans",
                            "debtorLoans",
                            "friends",
                            "lastCombatTimestep",
                            "conflictHappiness",
                            "familyHappiness",
                            "healthHappiness",
                            "socialHappiness",
                            "wealthHappiness",
                            "happiness",
                        ),
                        agent,
                        strict=True,
                    )
                )
                | {
                    "tags": None if agent[26] is None else list(agent[26]),
                    "immuneSystem": None if agent[37] is None else list(agent[37]),
                    "diseases": [
                        dict(
                            zip(
                                (
                                    "diseaseId",
                                    "startIndex",
                                    "endIndex",
                                    "infectorId",
                                    "caught",
                                    "incubation",
                                ),
                                infection,
                                strict=True,
                            )
                        )
                        for infection in agent[38]
                    ],
                    "startingImmuneSystem": None
                    if agent[51] is None
                    else list(agent[51]),
                    "racialTags": None if agent[52] is None else list(agent[52]),
                    "childrenIds": list(agent[55]),
                    "mateIds": list(agent[56]),
                    "creditorLoans": [
                        dict(
                            zip(
                                (
                                    "creditorId",
                                    "debtorId",
                                    "sugarLoan",
                                    "spiceLoan",
                                    "loanDuration",
                                    "loanOrigin",
                                ),
                                loan,
                                strict=True,
                            )
                        )
                        for loan in agent[62]
                    ],
                    "debtorLoans": [
                        dict(
                            zip(
                                (
                                    "creditorId",
                                    "debtorId",
                                    "sugarLoan",
                                    "spiceLoan",
                                    "loanDuration",
                                    "loanOrigin",
                                ),
                                loan,
                                strict=True,
                            )
                        )
                        for loan in agent[63]
                    ],
                    "friends": [
                        {"id": friend_id, "hammingDistance": distance}
                        for friend_id, distance in agent[64]
                    ],
                }
                for agent in self.agents
            ],
            "creditorTombstones": [
                {
                    "id": agent_id,
                    "inheritancePolicy": inheritance_policy,
                    "childrenIds": list(children_ids),
                }
                for agent_id, inheritance_policy, children_ids in self.creditor_tombstones
            ],
            "orderedCandidates": [
                [list(entry) for entry in entries]
                for entries in self.ordered_candidates
            ],
            "orderedNeighbors": [list(entries) for entries in self.ordered_neighbors],
            "diseases": [
                dict(
                    zip(
                        (
                            "id",
                            "aggressionPenalty",
                            "fertilityPenalty",
                            "friendlinessPenalty",
                            "happinessPenalty",
                            "incubationPeriod",
                            "movementPenalty",
                            "spiceMetabolismPenalty",
                            "startTimestep",
                            "sugarMetabolismPenalty",
                            "tags",
                            "transmissionChance",
                            "visionPenalty",
                            "recoverable",
                            "infectedIds",
                        ),
                        disease,
                        strict=True,
                    )
                )
                | {
                    "tags": None if disease[10] is None else list(disease[10]),
                    "infectedIds": list(disease[14]),
                }
                for disease in self.diseases
            ],
            "remainingDiseaseIds": list(self.remaining_disease_ids),
            "deaths": [
                {"id": agent_id, "seat": seat, "age": age, "cause": cause}
                for agent_id, seat, age, cause in self.deaths
            ],
        }


@dataclass(frozen=True)
class NativeCompatibilityAudit:
    configuration_sha256: str
    ruleset_sha256: tuple[str, ...]
    population: int
    depressed_agents: int
    infected_agents: int
    modified_agents: int
    blockers: tuple[str, ...]


def validate_supported_world(world: CoworldSugarscape) -> None:
    config = world.configuration
    requirements = (
        (
            config["environmentWraparound"] is True,
            "environmentWraparound must be true",
        ),
        (
            config["agentMovementMode"] == "cardinal",
            "agentMovementMode must be cardinal",
        ),
        (config["agentVisionMode"] == "cardinal", "agentVisionMode must be cardinal"),
        (config["environmentSeasonInterval"] == 0, "seasons are unsupported"),
        (config["environmentPollutionTimeframe"] == [0, 0], "pollution is unsupported"),
        (
            config["environmentPollutionDiffusionDelay"] == 0,
            "pollution diffusion is unsupported",
        ),
        (config["agentReplacements"] == 0, "replacement is unsupported"),
        (not config["diseaseList"], "named diseases are unsupported"),
        (config["agentTagPreferences"] is False, "tag preferences are unsupported"),
        (
            config["agentInheritancePolicy"] in {"none", "children"},
            "inheritancePolicy must be none or children",
        ),
        (
            config["agentUniversalSugar"] == [0, 0]
            and config["agentUniversalSpice"] == [0, 0],
            "universal income is unsupported",
        ),
    )
    for accepted, message in requirements:
        if not accepted:
            raise ValueError(message)
    for index, agent in enumerate(world.agents):
        if not agent.alive or agent.cell is None:
            raise ValueError(f"agents[{index}] must be alive and placed")
        if agent.inheritancePolicy not in {"none", "children"}:
            raise ValueError(f"agents[{index}] inheritancePolicy is unsupported")
        if agent.decisionModelFactor != 0 and agent.decisionModel != "ruleset":
            raise ValueError(f"agents[{index}] ethical decision model is unsupported")
    for column in world.environment.grid:
        for cell in column:
            if cell.pollution != 0:
                raise ValueError("cell pollution state is unsupported")


def audit_snapshot_compatibility(world: CoworldSugarscape) -> NativeCompatibilityAudit:
    """Describe why a real DTL tick-zero world cannot yet use the native stepper."""

    agents = world.agents
    blockers = []
    if world.configuration["diseaseList"]:
        blockers.append("named_diseases")
    if world.remainingDiseases:
        blockers.append("scheduled_disease_introduction")
    return NativeCompatibilityAudit(
        _digest(world.configuration),
        tuple(_digest(ruleset.normalized) for ruleset in world.seat_manager.rulesets),
        len(agents),
        sum(agent.depressed for agent in agents),
        sum(bool(agent.diseases) for agent in agents),
        sum(
            any(
                modifier != 0
                for modifier in (
                    agent.visionModifier,
                    agent.movementModifier,
                    agent.sugarMetabolismModifier,
                    agent.spiceMetabolismModifier,
                    agent.aggressionFactorModifier,
                    agent.fertilityFactorModifier,
                    agent.friendlinessModifier,
                    agent.happinessModifier,
                )
            )
            for agent in agents
        ),
        tuple(blockers),
    )


def snapshot_world(world: CoworldSugarscape) -> NativeSnapshot:
    validate_supported_world(world)
    environment = world.environment
    version, state, gauss_next = random.getstate()
    if version != 3 or gauss_next is not None:
        raise ValueError(
            "native simulation requires an unbuffered CPython MT19937 state"
        )
    cells = tuple(
        (
            cell.sugar,
            cell.maxSugar,
            cell.spice,
            cell.maxSpice,
            cell.agent.ID if cell.agent is not None else None,
        )
        for column in environment.grid
        for cell in column
    )
    agents = tuple(
        (
            agent.ID,
            agent.seat,
            agent.cell.x,
            agent.cell.y,
            agent.sugar,
            agent.spice,
            agent.age,
            agent.sugarMetabolism,
            agent.spiceMetabolism,
            agent.vision,
            agent.movement,
            agent.maxAge,
            agent.lookaheadFactor,
            agent.visionModifier,
            agent.movementModifier,
            agent.sugarMetabolismModifier,
            agent.spiceMetabolismModifier,
            agent.aggressionFactor,
            agent.aggressionFactorModifier,
            agent.fertilityFactor,
            agent.fertilityFactorModifier,
            agent.depressed,
            agent.happinessUnit,
            agent.maxFriends,
            agent.friendlinessModifier,
            agent.happinessModifier,
            None if agent.tags is None else tuple(agent.tags),
            agent.tribe,
            agent.tagging,
            agent.tradeFactor,
            agent.marginalRateOfSubstitution,
            agent.tradeVolume,
            agent.sugarPrice,
            agent.spicePrice,
            agent.lastTradeTimestep,
            agent.lastTradePartners,
            agent.diseaseProtectionChance,
            None if agent.immuneSystem is None else tuple(agent.immuneSystem),
            tuple(
                (
                    record["disease"].ID,
                    record["startIndex"],
                    record["endIndex"],
                    None if record["infector"] is None else record["infector"].ID,
                    record["caught"],
                    record["incubation"],
                )
                for record in agent.diseases
            ),
            agent.born,
            agent.startingSugar,
            agent.startingSpice,
            agent.sex,
            agent.fertilityAge,
            agent.infertilityAge,
            agent.inheritancePolicy,
            agent.lendingFactor,
            agent.baseInterestRate,
            agent.loanDuration,
            agent.sugarMeanIncome,
            agent.spiceMeanIncome,
            None
            if agent.startingImmuneSystem is None
            else tuple(agent.startingImmuneSystem),
            None if agent.racialTags is None else tuple(agent.racialTags),
            None
            if agent.socialNetwork["father"] is None
            else agent.socialNetwork["father"].ID,
            None
            if agent.socialNetwork["mother"] is None
            else agent.socialNetwork["mother"].ID,
            tuple(child.ID for child in agent.socialNetwork["children"]),
            tuple(mate.ID for mate in agent.socialNetwork["mates"]),
            agent.lastMovedTimestep,
            agent.lastReproducedTimestep,
            agent.lastMates,
            agent.lastLendedTimestep,
            agent.lastLoans,
            tuple(
                (
                    loan["creditor"].ID,
                    loan["debtor"].ID,
                    loan["sugarLoan"],
                    loan["spiceLoan"],
                    loan["loanDuration"],
                    loan["loanOrigin"],
                )
                for loan in agent.socialNetwork["creditors"]
            ),
            tuple(
                (
                    loan["creditor"].ID,
                    loan["debtor"].ID,
                    loan["sugarLoan"],
                    loan["spiceLoan"],
                    loan["loanDuration"],
                    loan["loanOrigin"],
                )
                for loan in agent.socialNetwork["debtors"]
            ),
            tuple(
                (friend["friend"].ID, friend["hammingDistance"])
                for friend in agent.socialNetwork["friends"]
            ),
            agent.lastCombatTimestep,
            agent.conflictHappiness,
            agent.familyHappiness,
            agent.healthHappiness,
            agent.socialHappiness,
            agent.wealthHappiness,
            agent.happiness,
        )
        for agent in sorted(world.agents, key=lambda value: value.ID)
    )
    creditor_tombstones = tuple(
        (
            creditor.ID,
            creditor.inheritancePolicy,
            tuple(child.ID for child in creditor.socialNetwork["children"]),
        )
        for creditor in sorted(
            {
                loan["creditor"].ID: loan["creditor"]
                for agent in world.agents
                for loan in agent.socialNetwork["creditors"]
                if not loan["creditor"].isAlive()
            }.values(),
            key=lambda value: value.ID,
        )
    )
    candidates = tuple(
        tuple(
            (candidate.x * environment.height + candidate.y, distance)
            for bucket in range(1, environment.maxCellDistance + 1)
            for candidate, distance in cell.ranges[bucket].items()
        )
        for column in environment.grid
        for cell in column
    )
    neighbors = tuple(
        tuple(
            neighbor.x * environment.height + neighbor.y
            for neighbor in cell.neighbors.values()
        )
        for column in environment.grid
        for cell in column
    )
    disease_objects = sorted(
        {
            disease.ID: disease
            for disease in (*world.diseases, *world.remainingDiseases)
            if hasattr(disease, "incubationPeriod")
        }.values(),
        key=lambda disease: disease.ID,
    )
    diseases = tuple(
        (
            disease.ID,
            disease.aggressionPenalty,
            disease.fertilityPenalty,
            disease.friendlinessPenalty,
            disease.happinessPenalty,
            disease.incubationPeriod,
            disease.movementPenalty,
            disease.spiceMetabolismPenalty,
            disease.startTimestep,
            disease.sugarMetabolismPenalty,
            None if disease.tags is None else tuple(disease.tags),
            disease.transmissionChance,
            disease.visionPenalty,
            disease.recoverable,
            tuple(agent.ID for agent in disease.infected),
        )
        for disease in disease_objects
    )
    if world.remainingDiseases:
        raise ValueError("scheduled disease introduction is unsupported")
    return NativeSnapshot(
        _digest(world.configuration),
        tuple(_digest(ruleset.normalized) for ruleset in world.seat_manager.rulesets),
        tuple(ruleset.normalized for ruleset in world.seat_manager.rulesets),
        world.timestep,
        world.runtimeStats["giniCoefficient"],
        world.runtimeStats["meanWealth"],
        environment.width,
        environment.height,
        environment.sugarRegrowRate,
        environment.spiceRegrowRate,
        environment.maxCellDistance,
        environment.maxCombatLoot,
        world.configuration["environmentMaxTribes"],
        world.configuration["agentInheritancePolicy"],
        world.nextAgentID,
        world.configuration["agentDepressionPercentage"],
        tuple(state[:624]),
        state[624],
        tuple(agent.ID for agent in world.agents),
        cells,
        agents,
        creditor_tombstones,
        candidates,
        neighbors,
        diseases,
        (),
        tuple(getattr(world, "native_deaths", ())),
    )


def step_python(snapshot: NativeSnapshot, ticks: int) -> NativeSnapshot:
    """Run the v7 transition contract in Python from the same wire snapshot."""

    if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks < 0:
        raise ValueError("ticks must be a non-negative integer")
    rng = random.Random()
    rng.setstate((3, snapshot.rng_words + (snapshot.rng_index,), None))
    cells = [list(cell) for cell in snapshot.cells]
    agents = {int(agent[0]): list(agent) for agent in snapshot.agents}
    creditor_tombstones = {
        agent_id: (inheritance_policy, list(children_ids))
        for agent_id, inheritance_policy, children_ids in snapshot.creditor_tombstones
    }
    for agent in agents.values():
        agent[38] = [list(infection) for infection in agent[38]]
        agent[55] = list(agent[55])
        agent[56] = list(agent[56])
        agent[62] = [list(loan) for loan in agent[62]]
        agent[63] = [list(loan) for loan in agent[63]]
        agent[64] = [list(friend) for friend in agent[64]]
    diseases = [list(disease) for disease in snapshot.diseases]
    for disease in diseases:
        disease[14] = list(disease[14])
    disease_by_id = {disease[0]: disease for disease in diseases}
    live_order = list(snapshot.live_order)
    timestep = snapshot.timestep
    deaths = list(snapshot.deaths)
    next_agent_id = snapshot.next_agent_id
    world_gini = snapshot.world_gini
    world_mean_wealth = snapshot.world_mean_wealth

    def movement_score(
        ruleset: object,
        agent: list[object],
        target: int,
        distance: int | float,
        welfare: float,
        population: int,
    ) -> float:
        if ruleset is None or "movement" not in ruleset:
            return welfare
        sugar_metabolism, spice_metabolism = metabolisms(agent)
        sugar_need = agent[4] / sugar_metabolism if sugar_metabolism > 0 else 1
        spice_need = agent[5] / spice_metabolism if spice_metabolism > 0 else 1
        occupant_id = cells[target][4]
        prey_wealth = (
            agents[occupant_id][4] + agents[occupant_id][5]
            if occupant_id is not None
            else 0
        )
        features = {
            "agent.sugar": agent[4],
            "agent.spice": agent[5],
            "agent.wealth": agent[4] + agent[5],
            "agent.sugarMetabolism": sugar_metabolism,
            "agent.spiceMetabolism": spice_metabolism,
            "agent.vision": max(0, int(agent[9]) + int(agent[13])),
            "agent.movement": max(0, int(agent[10]) + int(agent[14])),
            "agent.age": agent[6],
            "agent.ttl": min(
                agent[4] / sugar_metabolism if sugar_metabolism > 0 else 2**63 - 1,
                agent[5] / spice_metabolism if spice_metabolism > 0 else 2**63 - 1,
            ),
            "agent.mrs": (
                agent[29] * (spice_need / sugar_need) if sugar_need != 0 else 0
            ),
            "cell.sugar": cells[target][0],
            "cell.spice": cells[target][2],
            "cell.pollution": 0,
            "cell.distance": distance,
            "cell.occupied": 1 if occupant_id is not None else 0,
            "cell.preyWealth": prey_wealth,
            "cell.welfare": welfare,
            "world.timestep": timestep,
            "world.population": population,
            "world.gini": world_gini,
            "world.meanWealth": world_mean_wealth,
        }
        for rule in ruleset["movement"]:
            if "if" not in rule or evaluate_reference(rule["if"], features) != 0:
                return evaluate_reference(rule["score"], features)
        raise AssertionError("normalized movement rules end unconditionally")

    def world_statistics() -> tuple[float, float]:
        wealths = sorted(agent[4] + agent[5] for agent in agents.values())
        if not wealths:
            return 0, 0
        total = sum(wealths)
        if total == 0:
            gini = 1
        else:
            cumulative = 0.0
            area = 0.0
            for wealth in wealths[:-1]:
                cumulative += wealth
                area += cumulative / total
            cumulative += wealths[-1]
            area += (cumulative / 2) / total
            area /= len(wealths)
            gini = round((0.5 - area) / 0.5, 3)
        return gini, round(total / len(wealths), 2)

    def update_friends(agent: list[object], neighbor: list[object]) -> None:
        distance = (
            0
            if agent[26] is None
            else sum(left != right for left, right in zip(agent[26], neighbor[26]))
        )
        entry = [neighbor[0], distance]
        if len(agent[64]) < agent[23]:
            agent[64].append(entry)
            return
        max_distance = 0
        max_index = None
        for index, friend in enumerate(agent[64]):
            if friend[0] == neighbor[0]:
                agent[64].pop(index)
                agent[64].append(entry)
                return
            if friend[1] > max_distance:
                max_index = index
                max_distance = friend[1]
        if max_distance > distance:
            assert max_index is not None
            agent[64].pop(max_index)
            agent[64].append(entry)

    def update_happiness(
        agent: list[object], deaths_by_id: dict[int, tuple[int, int, int, str]]
    ) -> None:
        unit = agent[22]
        agent[66] = (
            (unit if agent[17] + agent[18] > 1 else -unit)
            if agent[65] == timestep
            else 0
        )
        family = 0.0
        for relation_id in agent[55]:
            if relation_id not in agents or relation_id in deaths_by_id:
                family -= unit
                continue
            relation = agents[relation_id]
            family += unit
            if relation[38]:
                family -= unit * 0.5
            if relation[39] == timestep:
                family += unit
        for relation_id in agent[56]:
            if relation_id not in agents or relation_id in deaths_by_id:
                family -= unit
                continue
            relation = agents[relation_id]
            family += unit
            if relation[38]:
                family -= unit * 0.5
        agent[67] = math.erf(family)
        agent[68] = -unit if agent[38] else unit
        agent[69] = (
            0
            if agent[23] == 0
            else ((len(agent[64]) * (2 / agent[23])) - 1) * unit
        )
        agent[70] = math.erf((agent[4] + agent[5] - world_mean_wealth) * unit)
        agent[71] = agent[66] + agent[67] + agent[68] + agent[69] + agent[70]

    def fertile(agent: list[object]) -> bool:
        return (
            agent[4] >= agent[40]
            and agent[5] >= agent[41]
            and agent[6] >= agent[43]
            and agent[6] < agent[44]
            and agent[19] + agent[20] > 0
        )

    def empty_neighbors(agent: list[object]) -> list[int]:
        cell = agent[2] * snapshot.height + agent[3]
        return [
            index
            for index in snapshot.ordered_neighbors[cell]
            if cells[index][4] is None
        ]

    def inherited(
        first: list[object], second: list[object], field: str, index: int
    ) -> object:
        local = random.Random(
            int(hashlib.md5(field.encode()).hexdigest(), 16) + timestep
        )
        return (first, second)[local.randrange(2)][index]

    def distribute_inheritance(agent: list[object]) -> None:
        if agent[45] != "children":
            return
        children = [
            agents[child_id]
            for child_id in agent[55]
            if child_id in agents and child_id not in deaths_by_id
        ]
        if not children:
            return
        sugar = max(0, agent[4]) / len(children)
        spice = max(0, agent[5]) / len(children)
        for child in children:
            child[4] += sugar
            child[5] += spice
            agent[4] -= sugar
            agent[5] -= spice

    def metabolisms(agent: list[object]) -> tuple[float, float]:
        return max(0, agent[7] + agent[15]), max(0, agent[8] + agent[16])

    def marginal_rate(
        agent: list[object],
        sugar: float | None = None,
        spice: float | None = None,
        *,
        proposed: bool = False,
    ) -> float:
        sugar_metabolism, spice_metabolism = metabolisms(agent)
        sugar = agent[4] if sugar is None else sugar
        spice = agent[5] if spice is None else spice
        spice_need = spice / spice_metabolism if spice_metabolism > 0 else 1
        sugar_need = sugar / sugar_metabolism if sugar_metabolism > 0 else 1
        if proposed:
            if spice_need == sugar_need == 1:
                return 1
            if spice_need == 0:
                return spice_metabolism
            if sugar_need == 0:
                return 1 / sugar_metabolism
            return spice_need / sugar_need
        return agent[29] * (spice_need / sugar_need)

    def reward_welfare(
        agent: list[object], sugar_reward: float, spice_reward: float
    ) -> float:
        sugar_metabolism, spice_metabolism = metabolisms(agent)
        total = sugar_metabolism + spice_metabolism
        sugar_power = sugar_metabolism / total if total else 0
        spice_power = spice_metabolism / total if total else 0
        return (
            max(0, agent[4] + sugar_reward - sugar_metabolism * agent[12])
            ** sugar_power
            * max(0, agent[5] + spice_reward - spice_metabolism * agent[12])
            ** spice_power
        )

    def apply_disease(
        agent: list[object], disease: list[object], direction: int
    ) -> None:
        agent[18] += direction * disease[1]
        agent[20] += direction * disease[2]
        agent[24] += direction * disease[3]
        agent[25] += direction * disease[4]
        agent[14] += direction * disease[6]
        agent[16] += direction * disease[7]
        agent[15] += direction * disease[9]
        agent[13] += direction * disease[12]

    def clear_diseases(agent: list[object]) -> None:
        for infection in agent[38]:
            disease = disease_by_id[infection[0]]
            apply_disease(agent, disease, -1)
            if agent[0] in disease[14]:
                disease[14].remove(agent[0])
        agent[38] = []

    def add_loan(
        creditor: list[object],
        debtor: list[object],
        sugar_principal: float,
        sugar_loan: float,
        spice_principal: float,
        spice_loan: float,
        duration: int,
        origin: int,
    ) -> None:
        loan = [creditor[0], debtor[0], sugar_loan, spice_loan, duration, origin]
        creditor[63].append(loan.copy())
        debtor[62].append(loan.copy())
        creditor[4] -= sugar_principal
        creditor[5] -= spice_principal
        debtor[4] += sugar_principal
        debtor[5] += spice_principal

    def remove_mirrored_loan(loan: list[object]) -> None:
        creditor = agents.get(loan[0])
        debtor = agents.get(loan[1])
        if creditor is not None:
            creditor[63].remove(loan)
        if debtor is not None:
            debtor[62].remove(loan)

    def current_debt(agent: list[object], resource_index: int) -> float:
        return sum(loan[resource_index] / loan[4] for loan in agent[62])

    def service_loans(agent: list[object]) -> None:
        for loan in agent[62]:
            if agent[57] - loan[5] - loan[4] != 0:
                continue
            creditor = agents.get(loan[0])
            if creditor is None:
                inheritance_policy, children_ids = creditor_tombstones[loan[0]]
                agent[62].remove(loan)
                if inheritance_policy == "children":
                    children = [
                        agents[child_id]
                        for child_id in children_ids
                        if child_id != agent[0]
                        and child_id in agents
                        and child_id not in deaths_by_id
                    ]
                    if children:
                        sugar_loan = loan[2] / len(children)
                        spice_loan = loan[3] / len(children)
                        for child in children:
                            add_loan(
                                child,
                                agent,
                                0,
                                sugar_loan,
                                0,
                                spice_loan,
                                1,
                                int(agent[57]),
                            )
                continue
            if agent[4] - loan[2] > 0 and agent[5] - loan[3] > 0:
                agent[4] -= loan[2]
                agent[5] -= loan[3]
                creditor[4] += loan[2]
                creditor[5] += loan[3]
                remove_mirrored_loan(loan)
                continue
            sugar_payout = agent[4] / 2
            spice_payout = agent[5] / 2
            agent[4] -= sugar_payout
            agent[5] -= spice_payout
            creditor[4] += sugar_payout
            creditor[5] += spice_payout
            sugar_left = loan[2] - sugar_payout
            spice_left = loan[3] - spice_payout
            remove_mirrored_loan(loan)
            rate = creditor[46] * creditor[47]
            add_loan(
                creditor,
                agent,
                0,
                sugar_left + rate * sugar_left,
                0,
                spice_left + rate * spice_left,
                int(creditor[48]),
                int(agent[57]),
            )

    def do_lending(agent: list[object], destination: int) -> None:
        service_loans(agent)
        if agent[46] == 0 or agent[6] < agent[43]:
            return
        if fertile(agent) and (agent[4] <= agent[40] or agent[5] <= agent[41]):
            return
        borrowers = []
        for neighbor_cell in snapshot.ordered_neighbors[destination]:
            neighbor_id = cells[neighbor_cell][4]
            if neighbor_id is None or neighbor_id in deaths_by_id:
                continue
            borrower = agents[neighbor_id]
            if (
                borrower[6] >= borrower[43]
                and borrower[6] < borrower[44]
                and not fertile(borrower)
            ):
                borrowers.append(neighbor_id)
        rng.shuffle(borrowers)
        sugar_metabolism, spice_metabolism = metabolisms(agent)
        loans = 0
        for borrower_id in borrowers:
            borrower = agents[borrower_id]
            max_sugar = max(0, agent[4] - agent[40]) if fertile(agent) else agent[4] / 2
            max_spice = max(0, agent[5] - agent[41]) if fertile(agent) else agent[5] / 2
            if max_sugar == 0 and max_spice == 0:
                return
            sugar_need = max(0, borrower[40] - borrower[4])
            spice_need = max(0, borrower[41] - borrower[5])
            sugar_principal = min(max_sugar, sugar_need)
            spice_principal = min(max_spice, spice_need)
            rate = min(1, agent[46] * agent[47])
            sugar_loan = sugar_principal + sugar_principal * rate
            spice_loan = spice_principal + spice_principal * rate
            if (sugar_need == 0 and spice_need == 0) or (
                sugar_loan == 0 and spice_loan == 0
            ):
                continue
            if (
                agent[4] - sugar_principal <= sugar_metabolism
                or agent[5] - spice_principal <= spice_metabolism
            ):
                continue
            duration = int(agent[48])
            if duration == 0:
                continue
            borrower_sugar = (
                (borrower[49] - metabolisms(borrower)[0])
                - current_debt(borrower, 2)
                - sugar_loan / duration
            )
            borrower_spice = (
                (borrower[50] - metabolisms(borrower)[1])
                - current_debt(borrower, 3)
                - spice_loan / duration
            )
            if borrower_sugar < 0 or borrower_spice < 0:
                continue
            add_loan(
                agent,
                borrower,
                sugar_principal,
                sugar_loan,
                spice_principal,
                spice_loan,
                duration,
                int(agent[57]),
            )
            loans += 1
        if loans:
            agent[60] = timestep
            agent[61] = loans

    def create_child(
        first: list[object], second: list[object], child_cell: int
    ) -> list[object]:
        nonlocal next_agent_id
        paired = inherited(first, second, "decisionModel", 0)
        template = first if paired == first[0] else second
        child = list(template)
        for field, index in (
            ("aggressionFactor", 17),
            ("baseInterestRate", 47),
            ("diseaseProtectionChance", 36),
            ("fertilityAge", 43),
            ("fertilityFactor", 19),
            ("infertilityAge", 44),
            ("inheritancePolicy", 45),
            ("lendingFactor", 46),
            ("loanDuration", 48),
            ("lookaheadFactor", 12),
            ("maxAge", 11),
            ("maxFriends", 23),
            ("movement", 10),
            ("spiceMetabolism", 8),
            ("sugarMetabolism", 7),
            ("sex", 42),
            ("tradeFactor", 29),
            ("vision", 9),
        ):
            child[index] = inherited(first, second, field, index)
        child[40] = first[40] / (first[19] * 2) + second[40] / (second[19] * 2)
        child[41] = first[41] / (first[19] * 2) + second[41] / (second[19] * 2)
        child[4], child[5] = child[40], child[41]
        tag_rng = random.Random(int(hashlib.md5(b"tags").hexdigest(), 16) + timestep)
        child[26] = (
            None
            if first[26] is None
            else tuple(
                left if left == right else tag_rng.randrange(2)
                for left, right in zip(first[26], second[26], strict=True)
            )
        )
        racial_rng = random.Random(
            int(hashlib.md5(b"racialTags").hexdigest(), 16) + timestep
        )
        child[52] = (
            None
            if first[52] is None
            else tuple(
                racial_rng.choice((left, right))
                for left, right in zip(first[52], second[52], strict=True)
            )
        )
        child[21] = racial_rng.random() <= snapshot.depression_percentage
        immune_rng = random.Random(
            int(hashlib.md5(b"immuneSystem").hexdigest(), 16) + timestep
        )
        child[51] = (
            None
            if first[51] is None
            else tuple(
                left if left == right else immune_rng.randrange(2)
                for left, right in zip(first[51], second[51], strict=True)
            )
        )
        child[37] = child[51]
        child[0] = next_agent_id
        next_agent_id += 1
        child[1] = first[1] if rng.random() < 0.5 else second[1]
        child[2], child[3] = divmod(child_cell, snapshot.height)
        child[6] = 0
        if first[42] == "female":
            child[53], child[54] = second[0], first[0]
        else:
            child[53], child[54] = first[0], second[0]
        child[39] = timestep
        child[55], child[56] = [], []
        child[38], child[62], child[63] = [], [], []
        child[64] = []
        child[65] = -1
        child[66:72] = [0, 0, 0, 0, 0, 0]
        for index in (13, 14, 15, 16, 18, 20, 24, 25):
            child[index] = 0
        child[22] = 1
        child[30], child[31], child[32], child[33] = 1, 0, 0, 0
        child[34], child[35] = -1, 0
        child[57], child[58], child[59], child[60], child[61] = timestep, -1, 0, -1, 0
        child[49], child[50] = 1, 1
        if child[21]:
            child[17] *= 1.145
            child[23] = math.ceil(child[23] * 0.6333)
            child[22] *= 0.5763
            child[10] *= math.ceil(child[10] * 0.429)
            child[8] *= math.ceil(child[8] * 1.544)
            child[7] *= math.ceil(child[7] * 1.544)
        if child[26] is None:
            child[27] = None
        else:
            tribe_size = (len(child[26]) + 1) / snapshot.max_tribes
            child[27] = min(
                math.ceil((child[26].count(0) + 1) / tribe_size) - 1,
                snapshot.max_tribes - 1,
            )
        sugar_collected, spice_collected = cells[child_cell][0], cells[child_cell][2]
        child[4] += sugar_collected
        child[5] += spice_collected
        income_alpha = 0.05
        child[49] = income_alpha * sugar_collected + (1 - income_alpha)
        child[50] = income_alpha * spice_collected + (1 - income_alpha)
        cells[child_cell][0] = cells[child_cell][2] = 0
        cells[child_cell][4] = child[0]
        return child

    for _ in range(ticks):
        if not live_order:
            break
        deaths_by_id: dict[int, tuple[int, int, int, str]] = {}
        timestep += 1
        world_population = len(agents)
        for cell in cells:
            cell[0] = min(cell[1], cell[0] + snapshot.sugar_regrow_rate)
            cell[2] = min(cell[3], cell[2] + snapshot.spice_regrow_rate)
        rng.shuffle(live_order)
        for agent_id in live_order:
            if agent_id in deaths_by_id:
                continue
            agent = agents[agent_id]
            if agent[57] == timestep:
                continue
            origin = int(agent[2]) * snapshot.height + int(agent[3])
            effective_vision = max(0, int(agent[9]) + int(agent[13]))
            effective_movement = max(0, int(agent[10]) + int(agent[14]))
            sugar_metabolism = max(0, agent[7] + agent[15])
            spice_metabolism = max(0, agent[8] + agent[16])
            aggression = max(0, agent[17] + agent[18])
            cell_range = min(
                effective_vision,
                effective_movement,
                snapshot.max_cell_distance,
            )
            candidates = [
                (target, distance)
                for target, distance in snapshot.ordered_candidates[origin]
                if distance <= cell_range
            ]
            rng.shuffle(candidates)
            retaliators: dict[int | None, int | float] = {}
            for target, _distance in candidates:
                occupant_id = cells[target][4]
                if occupant_id is not None and occupant_id not in deaths_by_id:
                    occupant = agents[occupant_id]
                    wealth = occupant[4] + occupant[5]
                    tribe = occupant[27]
                    retaliators[tribe] = max(retaliators.get(tribe, 0), wealth)
            destination = origin
            best_welfare = float("-inf")
            best_distance = float("inf")
            for target, distance in candidates:
                occupant_id = cells[target][4]
                sugar_reward = spice_reward = 0
                prey_tribe = None
                if occupant_id is not None:
                    prey = agents[occupant_id]
                    if (
                        occupant_id in deaths_by_id
                        or aggression <= 0
                        or agent[27] == prey[27]
                        or agent[4] + agent[5] < prey[4] + prey[5]
                    ):
                        continue
                    prey_tribe = prey[27]
                    sugar_reward = aggression * min(snapshot.max_combat_loot, prey[4])
                    spice_reward = aggression * min(snapshot.max_combat_loot, prey[5])
                total_metabolism = sugar_metabolism + spice_metabolism
                sugar_proportion = (
                    sugar_metabolism / total_metabolism if total_metabolism else 0
                )
                spice_proportion = (
                    spice_metabolism / total_metabolism if total_metabolism else 0
                )
                adjusted_sugar = max(
                    agent[4]
                    + cells[target][0]
                    + sugar_reward
                    - sugar_metabolism * agent[12],
                    0,
                )
                adjusted_spice = max(
                    agent[5]
                    + cells[target][2]
                    + spice_reward
                    - spice_metabolism * agent[12],
                    0,
                )
                welfare = (adjusted_sugar**sugar_proportion) * (
                    adjusted_spice**spice_proportion
                )
                if not math.isfinite(welfare):
                    welfare = 0
                if occupant_id is not None and retaliators[prey_tribe] > (
                    agent[4] + agent[5] + welfare
                ):
                    continue
                score = movement_score(
                    snapshot.rulesets[int(agent[1])],
                    agent,
                    target,
                    distance,
                    welfare,
                    world_population,
                )
                if score > best_welfare or (
                    score == best_welfare and distance < best_distance
                ):
                    destination = target
                    best_welfare = score
                    best_distance = distance
            prey_id = cells[destination][4]
            if destination != origin and prey_id is not None:
                prey = agents[prey_id]
                sugar_loot = min(snapshot.max_combat_loot, prey[4])
                spice_loot = min(snapshot.max_combat_loot, prey[5])
                agent[4] += sugar_loot
                agent[5] += spice_loot
                prey[4] -= sugar_loot
                prey[5] -= spice_loot
                deaths_by_id[prey_id] = (prey_id, int(prey[1]), int(prey[6]), "combat")
                distribute_inheritance(prey)
                clear_diseases(prey)
                cells[destination][4] = None
                agent[65] = timestep
            if destination != origin:
                cells[origin][4] = None
                cells[destination][4] = agent_id
                agent[2] = destination // snapshot.height
                agent[3] = destination % snapshot.height
            for neighbor_cell in snapshot.ordered_neighbors[destination]:
                neighbor_id = cells[neighbor_cell][4]
                if neighbor_id is not None and neighbor_id not in deaths_by_id:
                    update_friends(agent, agents[neighbor_id])
            agent[57] = timestep
            sugar_collected = cells[destination][0]
            spice_collected = cells[destination][2]
            agent[4] += sugar_collected
            agent[5] += spice_collected
            income_alpha = 0.05
            agent[49] = income_alpha * sugar_collected + (1 - income_alpha) * agent[49]
            agent[50] = income_alpha * spice_collected + (1 - income_alpha) * agent[50]
            cells[destination][0] = 0
            cells[destination][2] = 0
            agent[4] -= sugar_metabolism
            agent[5] -= spice_metabolism
            sugar_starved = agent[4] < 0 or (agent[4] <= 0 and sugar_metabolism > 0)
            spice_starved = agent[5] < 0 or (agent[5] <= 0 and spice_metabolism > 0)
            if sugar_starved or spice_starved:
                cells[destination][4] = None
                deaths_by_id[agent_id] = (
                    agent_id,
                    int(agent[1]),
                    int(agent[6]),
                    "starvation",
                )
                distribute_inheritance(agent)
                clear_diseases(agent)
                continue
            if agent[28]:
                neighbors = list(snapshot.ordered_neighbors[destination])
                rng.shuffle(neighbors)
                for neighbor in neighbors:
                    neighbor_id = cells[neighbor][4]
                    if neighbor_id is not None and neighbor_id not in deaths_by_id:
                        position = rng.randrange(len(agent[26]))
                        target = agents[neighbor_id]
                        target[26] = tuple(
                            agent[26][position] if index == position else tag
                            for index, tag in enumerate(target[26])
                        )
                        tribe_size = (len(target[26]) + 1) / snapshot.max_tribes
                        target[27] = min(
                            math.ceil((target[26].count(0) + 1) / tribe_size) - 1,
                            snapshot.max_tribes - 1,
                        )
            if agent[29] != 0:
                agent[31:34] = [0, 0, 0]
                agent[30] = marginal_rate(agent)
                potential = []
                for neighbor_cell in snapshot.ordered_neighbors[destination]:
                    trader_id = cells[neighbor_cell][4]
                    if (
                        trader_id is not None
                        and trader_id not in deaths_by_id
                        and agents[trader_id][30] != agent[30]
                    ):
                        potential.append(trader_id)
                rng.shuffle(potential)
                partners = []
                for trader_id in potential:
                    trader = agents[trader_id]
                    spice_seller = sugar_seller = None
                    sugar_price = spice_price = 0
                    while True:
                        first, second = agent[30], trader[30]
                        if (
                            (first >= 1 and second >= 1)
                            or (first < 1 and second < 1)
                            or first == second
                        ):
                            break
                        spice_seller, sugar_seller = (
                            (trader, agent) if second > first else (agent, trader)
                        )
                        spice_mrs, sugar_mrs = spice_seller[30], sugar_seller[30]
                        if spice_mrs < 0 or sugar_mrs < 0:
                            spice_seller = sugar_seller = None
                            break
                        price = math.sqrt(spice_mrs * sugar_mrs)
                        spice_price, sugar_price = (
                            (1, price) if price < 1 else (price, 1)
                        )
                        if (
                            spice_seller[5] - spice_price < spice_seller[8]
                            or sugar_seller[4] - sugar_price < sugar_seller[7]
                        ):
                            break
                        spice_new = marginal_rate(
                            spice_seller,
                            spice_seller[4] + sugar_price,
                            spice_seller[5] - spice_price,
                            proposed=True,
                        )
                        sugar_new = marginal_rate(
                            sugar_seller,
                            sugar_seller[4] - sugar_price,
                            sugar_seller[5] + spice_price,
                            proposed=True,
                        )
                        spice_better = abs(1 - spice_mrs) > abs(
                            1 - spice_new
                        ) or reward_welfare(
                            spice_seller, sugar_price, -spice_price
                        ) >= reward_welfare(spice_seller, 0, 0)
                        sugar_better = abs(1 - sugar_mrs) > abs(
                            1 - sugar_new
                        ) or reward_welfare(
                            sugar_seller, -sugar_price, spice_price
                        ) >= reward_welfare(sugar_seller, 0, 0)
                        if (
                            not spice_better
                            or not sugar_better
                            or spice_new < sugar_new
                        ):
                            break
                        spice_seller[4] += sugar_price
                        spice_seller[5] -= spice_price
                        sugar_seller[4] -= sugar_price
                        sugar_seller[5] += spice_price
                        spice_seller[30] = marginal_rate(spice_seller)
                        sugar_seller[30] = marginal_rate(sugar_seller)
                    if spice_seller is not None:
                        agent[31] += 1
                        agent[32] += sugar_price
                        agent[33] += spice_price
                        agent[34] = timestep
                        if trader_id not in partners:
                            partners.append(trader_id)
                if agent[34] == timestep:
                    agent[35] = len(partners)
            if fertile(agent):
                neighbor_cells = list(snapshot.ordered_neighbors[destination])
                rng.shuffle(neighbor_cells)
                own_empty = empty_neighbors(agent)
                timestep_mates = []
                for neighbor_cell in neighbor_cells:
                    mate_id = cells[neighbor_cell][4]
                    if mate_id is None or mate_id in deaths_by_id:
                        continue
                    mate = agents[mate_id]
                    compatible = (
                        agent[42] is not None
                        and mate[42] is not None
                        and agent[42] != mate[42]
                        and fertile(mate)
                    )
                    empty_cells = own_empty + empty_neighbors(mate)
                    rng.shuffle(empty_cells)
                    if not fertile(agent) or not compatible or not empty_cells:
                        continue
                    child_cell = empty_cells.pop()
                    while cells[child_cell][4] is not None and empty_cells:
                        child_cell = empty_cells.pop()
                    if cells[child_cell][4] is not None:
                        continue
                    if mate_id not in agent[56]:
                        agent[56].append(mate_id)
                    child = create_child(agent, mate, child_cell)
                    agent[55].append(child[0])
                    agent[4] -= agent[40] / (agent[19] * 2)
                    agent[5] -= agent[41] / (agent[19] * 2)
                    mate[4] -= mate[40] / (mate[19] * 2)
                    mate[5] -= mate[41] / (mate[19] * 2)
                    agent[58] = timestep
                    if mate_id not in timestep_mates:
                        timestep_mates.append(mate_id)
                    agents[child[0]] = child
                    live_order.append(child[0])
                agent[59] = len(timestep_mates)
            do_lending(agent, destination)
            rng.shuffle(agent[38])
            infection_index = 0
            while infection_index < len(agent[38]):
                infection = agent[38][infection_index]
                disease = disease_by_id[infection[0]]
                if infection[4] != timestep and infection[5] > 0:
                    infection[5] -= 1
                if infection[5] == 0:
                    apply_disease(agent, disease, 1)
                if disease[13] and disease[10] is not None:
                    response = tuple(
                        agent[37][infection[1] : min(infection[2] + 1, len(agent[37]))]
                    )
                    for offset, bit in enumerate(response):
                        if bit != disease[10][offset]:
                            immune = list(agent[37])
                            immune[infection[1] + offset] = disease[10][offset]
                            agent[37] = tuple(immune)
                            agent[51] = agent[37]
                            break
                    if tuple(disease[10]) == response:
                        agent[38].remove(infection)
                        apply_disease(agent, disease, -1)
                        disease[14].remove(agent_id)
                        infection_index += 1
                        continue
                infection_index += 1
            disease_count = len(agent[38])
            if disease_count:
                disease_neighbors = [
                    cells[cell][4]
                    for cell in snapshot.ordered_neighbors[destination]
                    if cells[cell][4] is not None and cells[cell][4] not in deaths_by_id
                ]
                rng.shuffle(disease_neighbors)
                for neighbor_id in disease_neighbors:
                    infection = agent[38][rng.randrange(disease_count)]
                    disease_id = infection[0]
                    target = agents[neighbor_id]
                    if any(record[0] == disease_id for record in target[38]):
                        continue
                    disease = disease_by_id[disease_id]
                    start_index, end_index, distance = (
                        0,
                        len(disease[10] or ()) - 1,
                        len(disease[10] or ()),
                    )
                    if disease[10] is not None:
                        for start in range(len(target[37]) - len(disease[10])):
                            candidate = sum(
                                a != b
                                for a, b in zip(
                                    target[37][start : start + len(disease[10])],
                                    disease[10],
                                    strict=True,
                                )
                            )
                            if candidate < distance:
                                distance, start_index, end_index = (
                                    candidate,
                                    start,
                                    start + len(disease[10]) - 1,
                                )
                        if distance == 0:
                            continue
                    attack, defense = rng.random(), rng.random()
                    if (
                        disease[11] != 0
                        and attack <= disease[11]
                        and not (target[36] != 0 and defense <= target[36])
                    ):
                        target[38].append(
                            [
                                disease_id,
                                start_index if disease[10] is not None else None,
                                end_index if disease[10] is not None else None,
                                agent_id,
                                timestep,
                                disease[5],
                            ]
                        )
                        disease[14].append(neighbor_id)
                        if disease[5] == 0:
                            apply_disease(target, disease, 1)
            agent[6] += 1
            if agent[11] != -1 and agent[6] >= agent[11]:
                cells[destination][4] = None
                deaths_by_id[agent_id] = (
                    agent_id,
                    int(agent[1]),
                    int(agent[6]),
                    "aging",
                )
                distribute_inheritance(agent)
                clear_diseases(agent)
            else:
                update_happiness(agent, deaths_by_id)
        deaths = [
            deaths_by_id[agent_id]
            for agent_id in live_order
            if agent_id in deaths_by_id
        ]
        live_after_tick = set(agents) - set(deaths_by_id)
        missing_creditors = {
            int(loan[0])
            for agent_id, agent in agents.items()
            if agent_id in live_after_tick
            for loan in agent[62]
            if loan[0] not in live_after_tick
        }
        creditor_tombstones = {
            creditor_id: (
                (
                    agents[creditor_id][45],
                    list(agents[creditor_id][55]),
                )
                if creditor_id in agents
                else creditor_tombstones[creditor_id]
            )
            for creditor_id in missing_creditors
        }
        for agent_id, _seat, _age, _cause in deaths:
            agents.pop(agent_id)
        dead_ids = {death[0] for death in deaths}
        live_order = [agent_id for agent_id in live_order if agent_id not in dead_ids]
        world_gini, world_mean_wealth = world_statistics()

    _version, state, gauss_next = rng.getstate()
    if gauss_next is not None:
        raise AssertionError("shuffle cannot populate the Gaussian cache")
    return NativeSnapshot(
        snapshot.config_sha256,
        snapshot.ruleset_sha256,
        snapshot.rulesets,
        timestep,
        world_gini,
        world_mean_wealth,
        snapshot.width,
        snapshot.height,
        snapshot.sugar_regrow_rate,
        snapshot.spice_regrow_rate,
        snapshot.max_cell_distance,
        snapshot.max_combat_loot,
        snapshot.max_tribes,
        snapshot.inheritance_policy,
        next_agent_id,
        snapshot.depression_percentage,
        tuple(state[:624]),
        state[624],
        tuple(live_order),
        tuple(tuple(cell) for cell in cells),
        tuple(
            tuple(
                agent[:38]
                + [tuple(tuple(record) for record in agent[38])]
                + agent[39:55]
                + [tuple(agent[55]), tuple(agent[56])]
                + agent[57:62]
                + [
                    tuple(tuple(loan) for loan in agent[62]),
                    tuple(tuple(loan) for loan in agent[63]),
                ]
                + [tuple(tuple(friend) for friend in agent[64])]
                + agent[65:]
            )
            for agent_id in sorted(agents)
            for agent in [agents[agent_id]]
        ),
        tuple(
            (agent_id, policy, tuple(children))
            for agent_id, (policy, children) in sorted(creditor_tombstones.items())
        ),
        snapshot.ordered_candidates,
        snapshot.ordered_neighbors,
        tuple(tuple(disease[:14] + [tuple(disease[14])]) for disease in diseases),
        snapshot.remaining_disease_ids,
        tuple(deaths),
    )
