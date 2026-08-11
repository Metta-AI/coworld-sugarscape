from __future__ import annotations

import pytest

from coworld.scoring import (
    jensen_shannon_divergence,
    make_histogram,
    normalized_wasserstein_1,
    score_histogram,
)


def test_wasserstein_known_pairs() -> None:
    bins = [0, 1, 2]
    assert normalized_wasserstein_1([1, 0], [1, 0], bins) == 0
    assert normalized_wasserstein_1([1, 0], [0, 1], bins) == 0.5
    assert normalized_wasserstein_1([0.5, 0.5], [0, 1], bins) == 0.25


def test_wasserstein_handles_unequal_bin_widths() -> None:
    assert normalized_wasserstein_1([1, 0], [0, 1], [0, 1, 4]) == 0.25


def test_js_divergence_known_pairs() -> None:
    assert jensen_shannon_divergence([1, 0], [1, 0]) == 0
    assert jensen_shannon_divergence([1, 0], [0, 1]) == 1
    assert jensen_shannon_divergence([0.5, 0.5], [1, 0]) == pytest.approx(0.31127812445913283)


def test_histogram_clamps_to_support_edges() -> None:
    histogram = make_histogram([-10, 0.5, 999], [0, 1, 2])
    assert histogram.sample_count == 3
    assert histogram.probs == pytest.approx((2 / 3, 1 / 3))


def test_empty_measurement_scores_zero_with_flag() -> None:
    result = score_histogram(make_histogram([], [0, 1, 2]), [0.5, 0.5])
    assert result.score == 0
    assert result.empty_measurement is True


def test_nonempty_score_is_one_minus_normalized_w1() -> None:
    result = score_histogram(make_histogram([0.25], [0, 1, 2]), [0, 1])
    assert result.score == 0.5
    assert result.w1 == 0.5
    assert result.js_divergence == 1
