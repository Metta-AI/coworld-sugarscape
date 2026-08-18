from __future__ import annotations

from tools.probe_commonwealth import summarize_component_frames


def test_component_probe_reports_ranges_and_nonzero_reachability() -> None:
    frames = [
        {
            "running": [
                {
                    "component_means": {
                        "health": 1,
                        "conflict": 0,
                        "social": -0.5,
                        "family": 0,
                        "wealth": 0.2,
                    }
                }
            ]
        },
        {
            "running": [
                {
                    "component_means": {
                        "health": 0.5,
                        "conflict": -0.1,
                        "social": 0,
                        "family": 0.4,
                        "wealth": -0.2,
                    }
                }
            ]
        },
    ]

    report = summarize_component_frames(frames)

    assert set(report) == {"health", "conflict", "social", "family", "wealth"}
    assert report["health"] == {
        "samples": 2,
        "nonzero_count": 2,
        "minimum": 0.5,
        "maximum": 1.0,
    }
    assert report["conflict"]["nonzero_count"] == 1
    assert report["family"]["maximum"] == 0.4
