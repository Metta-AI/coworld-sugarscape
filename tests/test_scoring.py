from __future__ import annotations

import pytest

from coworld.scoring import (
    AgentWellnessMean,
    jensen_shannon_divergence,
    make_histogram,
    score_histogram,
    score_wellness,
    target_scale,
    wasserstein_1,
)


def test_wasserstein_known_pairs() -> None:
    bins = [0, 1, 2]
    assert wasserstein_1([1, 0], [1, 0], bins) == 0
    assert wasserstein_1([1, 0], [0, 1], bins) == 1
    assert wasserstein_1([0.5, 0.5], [0, 1], bins) == 0.5


def test_wasserstein_handles_unequal_bin_widths() -> None:
    assert wasserstein_1([1, 0], [0, 1], [0, 1, 4]) == 1


def test_target_scale_uses_leftmost_median_and_its_bin_width() -> None:
    assert target_scale([0.5, 0.5], [0, 1, 4]) == 1


def test_one_bin_target_uses_bin_width_floor_and_adjacent_bin_scores_half() -> None:
    result = score_histogram(make_histogram([1.5], [0, 1, 2]), [1, 0])
    assert result.raw_w1 == 1
    assert result.w1_scale == 1
    assert result.score == 0.5


def test_score_strictly_decreases_with_transport_distance() -> None:
    bins = [0, 1, 2, 3]
    scores = [
        score_histogram(make_histogram([sample], bins), [1, 0, 0]).score
        for sample in (0.5, 1.5, 2.5)
    ]
    assert scores == [1.0, 0.5, pytest.approx(1 / 3)]


def test_js_divergence_known_pairs() -> None:
    assert jensen_shannon_divergence([1, 0], [1, 0]) == 0
    assert jensen_shannon_divergence([1, 0], [0, 1]) == 1
    assert jensen_shannon_divergence([0.5, 0.5], [1, 0]) == pytest.approx(
        0.31127812445913283
    )


def test_histogram_clamps_to_support_edges() -> None:
    histogram = make_histogram([-10, 0.5, 999], [0, 1, 2])
    assert histogram.sample_count == 3
    assert histogram.probs == pytest.approx((2 / 3, 1 / 3))


def test_empty_measurement_scores_zero_with_flag() -> None:
    result = score_histogram(make_histogram([], [0, 1, 2]), [0.5, 0.5])
    assert result.score == 0
    assert result.raw_w1 is None
    assert result.w1_scale == 1
    assert result.empty_measurement is True


def test_nonempty_score_is_target_scaled_hyperbolic_w1() -> None:
    result = score_histogram(make_histogram([0.25], [0, 1, 2]), [0, 1])
    assert result.score == 0.5
    assert result.raw_w1 == 1
    assert result.w1_scale == 1
    assert result.js_divergence == 1


def test_replay_regression_case_scores_shape_collapse_below_half() -> None:
    import json
    from pathlib import Path

    target = json.loads(
        (Path(__file__).resolve().parents[1] / "targets" / "wealth.skewed-gini-0.5.json")
        .read_text(encoding="utf-8")
    )
    result = score_histogram(
        make_histogram([0.0] * 344, target["bins"]),
        target["probs"],
    )

    assert result.raw_w1 == pytest.approx(39.82773333333348)
    assert result.w1_scale == pytest.approx(33.711466666666816)
    assert result.score == pytest.approx(0.45841492247218735)


def test_wellness_score_sums_agents_and_averages_components_equally() -> None:
    result = score_wellness(
        [
            AgentWellnessMean(1, 0, 0.25, (-1, 0, 1, 0.5, -0.5)),
            AgentWellnessMean(2, 0, 0.75, (1, 0.5, -1, 0.5, 0.5)),
        ]
    )
    assert result.score == 1
    assert result.survivor_count == 2
    assert result.mean_wellness == 0.5
    assert result.component_dict() == pytest.approx(
        {"health": 0, "conflict": 0.25, "social": 0, "family": 0.5, "wealth": 0}
    )


def test_empty_wellness_score_is_zero() -> None:
    result = score_wellness([])
    assert result.score == 0
    assert result.survivor_count == 0
    assert all(value == 0 for value in result.component_dict().values())
