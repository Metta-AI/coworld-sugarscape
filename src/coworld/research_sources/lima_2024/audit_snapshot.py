"""Audit a consistent native database snapshot without claiming a completed study."""

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Row(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table: Literal["m1", "m2", "m3", "router"]
    id: int
    agent_id: int
    data: str
    path: str
    asl_file_path: str
    processed: Literal[0, 1]
    created_at: datetime
    updated_at: datetime


class Checkpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table: Literal["m1", "m2", "m3"]
    id: int
    agent_id: int
    data: str
    path: str
    asl_file_path: str


def initial_rows(rows: list[Row], checkpoints: list[Checkpoint]) -> list[Row]:
    by_key = {(row.table, row.id): row for row in rows}
    assert len(by_key) == len(rows)
    assert len({(row.table, row.id) for row in checkpoints}) == len(checkpoints)
    initial = [row for row in rows if row.table != "router" and not row.path]
    for checkpoint in checkpoints:
        row = by_key[(checkpoint.table, checkpoint.id)]
        assert checkpoint.path
        assert all(
            getattr(row, field) == value
            for field, value in checkpoint.model_dump().items()
        )
        initial.append(row)
    assert len({row.agent_id for row in initial}) == len(initial)
    return initial


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
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
    checkpoint_keys = {(row.table, row.id) for row in checkpoints}
    raw = args.snapshot.read_bytes()
    rows = [Row.model_validate_json(line) for line in raw.splitlines()]
    assert rows
    assert len({(row.table, row.id) for row in rows}) == len(rows)
    initial = initial_rows(rows, checkpoints)
    assert {row.agent_id for row in rows} <= {row.agent_id for row in initial}
    assert all(row.created_at <= row.updated_at for row in rows)
    sent = Counter(
        (row.agent_id, row.data, row.path, row.asl_file_path)
        for row in rows
        if row.table == "router" and row.processed
    )
    received = Counter(
        (row.agent_id, row.data, row.path, row.asl_file_path)
        for row in rows
        if row.table != "router"
        and row.path
        and (row.table, row.id) not in checkpoint_keys
    )
    assert sent == received, {"missing": sent - received, "extra": received - sent}
    report = {
        "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
        "snapshot_rows": len(rows),
        "initial_unique_agents": len(initial),
        "initial_agents_by_model": dict(Counter(row.table for row in initial)),
        "exact_router_deliveries": sent.total(),
        "unmatched_deliveries": 0,
        "rows_by_table": dict(Counter(row.table for row in rows)),
        "queued_rows_by_table": dict(
            Counter(row.table for row in rows if not row.processed)
        ),
        "returns_from_jacamo": sum(
            row.table == "router" and row.path.split("-")[-1] == "3" for row in rows
        ),
        "nonempty_asl_paths": sum(bool(row.asl_file_path) for row in rows),
        "scope": (
            "Consistent database snapshot: exact identity, data, path and ASL-path "
            "multiset equality for processed router deliveries. This does not prove "
            "native model attribute reconstruction, ASL file-byte preservation, "
            "complete trajectories, dashboard behavior or the host-GUI scenario."
        ),
        "completed_study": False,
    }
    if checkpoints:
        report["initial_checkpoints"] = [row.model_dump() for row in checkpoints]
    with args.output.open("x") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
