from __future__ import annotations

import pytest

from coworld.native_simulator import build_native_simulator
from tools.benchmark_native_commonwealth import benchmark, parse_seeds


def test_parse_seeds_expands_one_base_or_requires_one_per_world() -> None:
    assert parse_seeds("1729", 3) == [1729, 1730, 1731]
    assert parse_seeds("7,11,13", 3) == [7, 11, 13]
    with pytest.raises(ValueError, match="one base seed"):
        parse_seeds("7,11", 3)
    with pytest.raises(ValueError, match="non-negative"):
        parse_seeds("-1", 1)


def test_full_commonwealth_parallel_benchmark_uses_native_timing_only(
    tmp_path,
) -> None:
    binary = build_native_simulator(binary=tmp_path / "simulator")

    report = benchmark(
        seeds=[1729, 1730],
        workers=2,
        ticks=1,
        binary=binary,
        timeout=30,
    )

    assert report["mode"] == "full_commonwealth_v7"
    assert report["metric"] == "completed_whole_world_ticks_per_second"
    assert report["seeds"] == [1729, 1730]
    assert report["world_count"] == report["workers"] == 2
    assert report["completed_world_ticks"] == 2
    assert report["elapsed_ns"] >= max(
        world["worker_elapsed_ns"] for world in report["worlds"]
    )
    assert report["wave_elapsed_ns"] == [report["elapsed_ns"]]
    assert report["world_ticks_per_second"] == pytest.approx(
        2_000_000_000 / report["elapsed_ns"]
    )
    assert report["timing_excludes"] == [
        "world construction",
        "process startup",
        "snapshot parsing",
        "final snapshot serialization",
        "replay",
        "compression",
    ]
    assert report["timing_scope"] == (
        "sum of parent-observed synchronized wave windows, from immediately before "
        "the first start dispatch through receipt of the final finished line"
    )
    assert [world["final_population"] for world in report["worlds"]] == [240, 236]
    assert all(world["initial_population"] == 250 for world in report["worlds"])
    assert all(world["final_timestep"] == 1 for world in report["worlds"])
    assert all(len(world["final_state_sha256"]) == 64 for world in report["worlds"])
    assert report["configuration"]["variant"] == "commonwealth"
    assert report["configuration"]["manifest_game_config"]["seed"] == -1
    assert report["configuration"]["width"] == 50
    assert report["configuration"]["height"] == 50
    assert report["configuration"]["initial_population"] == 250
    assert report["source"]["schema_version"] == 7
    assert (
        report["source"]["dtl_commit"]
        == "585282e9ce7b22a33b89abb0d777917bd5887d1a"
    )
    assert set(report["source"]["provenance_sha256"]) == {
        "benchmark_driver",
        "native_oracle",
        "native_fixture",
        "native_simulator",
        "config",
        "ruleset",
        "baseline_player",
    }
    assert all(
        len(digest) == 64
        for digest in report["source"]["provenance_sha256"].values()
    )
    assert report["host"]["cpu_affinity"] is None or all(
        isinstance(cpu, int) for cpu in report["host"]["cpu_affinity"]
    )
    assert set(report["host"]["slurm"]) == {
        "SLURM_JOB_ID",
        "SLURM_JOB_NAME",
        "SLURM_JOB_PARTITION",
        "SLURM_NODELIST",
        "SLURM_NTASKS",
        "SLURM_PROCID",
        "SLURM_CPUS_ON_NODE",
        "SLURM_CPUS_PER_TASK",
        "SLURM_JOB_GPUS",
        "SLURM_GPUS",
        "CUDA_VISIBLE_DEVICES",
    }
    assert all(set(gpu) == {"name", "uuid"} for gpu in report["host"]["gpus"])
