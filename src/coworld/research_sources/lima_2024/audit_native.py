"""Reconcile completed native trajectories and every registered agent's location."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from audit_snapshot import Checkpoint, Row, initial_rows

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("run", type=Path)
parser.add_argument("output", type=Path)
parser.add_argument("--jacamo-log", default="native.log")
parser.add_argument("--initial-checkpoints", default="")
args = parser.parse_args()
checkpoints = (
    [
        Checkpoint.model_validate(row)
        for row in json.loads(Path(args.initial_checkpoints).read_text())
    ]
    if args.initial_checkpoints
    else []
)
rows = [
    Row.model_validate_json(line)
    for line in (args.run / "snapshot-final.jsonl").read_bytes().splitlines()
]
initial = Counter(row.agent_id for row in initial_rows(rows, checkpoints))
assert initial and all(count == 1 for count in initial.values())
locations = Counter()
model_counts = {}
netlogo_creations = {}
hashes = {}
for model in ("m1", "m2"):
    path = args.run / f"shared_volume/netlogo_output/{model}_output.txt"
    raw = path.read_bytes()
    hashes[str(path.relative_to(args.run))] = hashlib.sha256(raw).hexdigest()
    log = raw.decode()
    ticks = list(map(int, re.findall(r"NL: Tick number: \n(\d+)", log)))
    assert ticks == list(range(1000))
    assert log.count("NL: ---------- FIM DA SIMULACAO...") == 1
    assert log.count("NL: ---------- FIM!") == 1
    creation_pattern = (
        r"NL: agent_id:\n(\d+)\nNL: tupla interna:\n([^\n]+)\n"
        r"NL: path:\n([^\n]*)\nNL: tupla interna 0 - sugar:\n(-?\d+)\n"
        r"NL: tupla interna 1 - metabolism:\n(\d+)\n"
        r"NL: tupla interna 2 - vision:\n(\d+)\nhistoric:\n([^\n]*)\n"
        r"new agent created from previous model"
    )
    reconstructed = Counter()
    for agent, data, path, sugar, metabolism, vision, historic in re.findall(
        creation_pattern, log
    ):
        assert data == f"[{sugar} {metabolism} {vision}]"
        assert historic == path
        reconstructed[(int(agent), path, data)] += 1
    consumed = Counter(
        (row.agent_id, row.path, row.data)
        for row in rows
        if row.table == model and row.processed
    )
    assert reconstructed == consumed
    assert reconstructed.total() == log.count("new agent created from previous model")
    netlogo_creations[model] = reconstructed.total()
    alive = args.run / f"shared_volume/netlogo_output/{model}_alive.txt"
    ids = list(map(int, alive.read_text().split()))
    assert len(ids) == len(set(ids))
    hashes[str(alive.relative_to(args.run))] = hashlib.sha256(
        alive.read_bytes()
    ).hexdigest()
    locations.update(ids)
    model_counts[model] = len(ids)
queued = Counter(row.agent_id for row in rows if not row.processed)
entered = Counter(row.agent_id for row in rows if row.table == "m3" and row.processed)
left = Counter(
    row.agent_id
    for row in rows
    if row.table == "router" and row.path.split("-")[-1] == "3"
)
assert not left - entered
active = entered - left
# The original checker admits one agent only when its native slot is empty.
# Between a return and its next poll, zero active transferred agents is valid.
assert active.total() <= 1
locations.update(queued)
locations.update(active)
assert locations == initial, {
    "missing": initial - locations,
    "extra": locations - initial,
}
native = (args.run / args.jacamo_log).read_text()
pattern = (
    r'Vai criar o agente com os beliefs: agent_id\((\d+)\),path\("([^"]*)"\), '
    r"sugar\((-?\d+)\), metabolism\((\d+)\), vision\((\d+)\)"
)
creations = Counter(
    (int(agent), path, f"[{sugar} {metabolism} {vision}]")
    for agent, path, sugar, metabolism, vision in re.findall(pattern, native)
)
expected = Counter(
    (row.agent_id, row.path, row.data)
    for row in rows
    if row.table == "m3" and row.processed
)
assert creations == expected
report = {
    "ticks_per_netlogo_model": 1000,
    "ordered_ticks_and_final_markers_verified": True,
    "netlogo_survivors": model_counts,
    "netlogo_native_creation_records": netlogo_creations,
    "queued_agents": queued.total(),
    "active_jacamo_agents": dict(active),
    "registered_agents_accounted_for_once": initial.total(),
    "jacamo_native_attribute_reconstructions": creations.total(),
    "jacamo_returns": left.total(),
    "native_file_sha256": hashes,
    "scope": (
        "Complete native trajectories and identity conservation at "
        "shutdown; native NetLogo incoming tuples/paths and JaCaMo creation attributes "
        "match every consumed database record. NetLogo logs do not expose the newly "
        "drawn sugar value or prove unchanged native sugar state. "
        "This does not establish AgentSpeak reload or host-GUI scenario completion."
    ),
    "completed_study": False,
}
if checkpoints:
    report["initial_checkpoints"] = [row.model_dump() for row in checkpoints]
with args.output.open("x") as stream:
    stream.write(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
