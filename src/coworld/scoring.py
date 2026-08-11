"""Histogram construction and distribution-distance scoring."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import math
from typing import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class Histogram:
    """A normalized histogram and its sample provenance."""

    bins: tuple[float, ...]
    probs: tuple[float, ...]
    sample_count: int

    @property
    def empty(self) -> bool:
        return self.sample_count == 0

    def as_dict(self) -> dict[str, object]:
        return {
            "support": [self.bins[0], self.bins[-1]],
            "bins": list(self.bins),
            "probs": list(self.probs),
            "sample_count": self.sample_count,
            "empty": self.empty,
        }


@dataclass(frozen=True, slots=True)
class DistributionScore:
    """Primary score and diagnostic distances for one measured histogram."""

    score: float
    w1: float
    js_divergence: float
    empty_measurement: bool


def make_histogram(samples: Iterable[float], bins: Sequence[float]) -> Histogram:
    """Bin finite samples, clamping out-of-support values to the edge bins."""

    edges = tuple(float(edge) for edge in bins)
    if len(edges) < 2 or any(left >= right for left, right in zip(edges, edges[1:])):
        raise ValueError("bins must contain at least two strictly increasing edges")
    counts = [0] * (len(edges) - 1)
    sample_count = 0
    for sample in samples:
        if not math.isfinite(sample):
            continue
        index = bisect_right(edges, sample) - 1
        index = min(len(counts) - 1, max(0, index))
        counts[index] += 1
        sample_count += 1
    if sample_count == 0:
        probs = (0.0,) * len(counts)
    else:
        probs = tuple(count / sample_count for count in counts)
    return Histogram(edges, probs, sample_count)


def normalized_wasserstein_1(
    measured: Sequence[float],
    target: Sequence[float],
    bins: Sequence[float],
) -> float:
    """Return W1 divided by the declared support width."""

    _validate_distributions(measured, target, bins)
    cumulative_measured = 0.0
    cumulative_target = 0.0
    distance = 0.0
    for index, width in enumerate(right - left for left, right in zip(bins, bins[1:])):
        cumulative_measured += measured[index]
        cumulative_target += target[index]
        distance += abs(cumulative_measured - cumulative_target) * width
    support_width = bins[-1] - bins[0]
    return min(1.0, max(0.0, distance / support_width))


def jensen_shannon_divergence(measured: Sequence[float], target: Sequence[float]) -> float:
    """Return base-2 Jensen-Shannon divergence in the interval [0, 1]."""

    if len(measured) != len(target):
        raise ValueError("distributions must have equal lengths")
    for name, distribution in (("measured", measured), ("target", target)):
        if any(value < 0 or not math.isfinite(value) for value in distribution):
            raise ValueError(f"{name} distribution must contain finite non-negative values")
        if not math.isclose(sum(distribution), 1.0, rel_tol=0, abs_tol=1e-9):
            raise ValueError(f"{name} distribution must sum to 1")
    midpoint = [(left + right) / 2 for left, right in zip(measured, target)]

    def divergence(distribution: Sequence[float]) -> float:
        total = 0.0
        for probability, middle in zip(distribution, midpoint):
            if probability > 0:
                total += probability * math.log2(probability / middle)
        return total

    return min(1.0, max(0.0, (divergence(measured) + divergence(target)) / 2))


def score_histogram(histogram: Histogram, target_probs: Sequence[float]) -> DistributionScore:
    """Score one measurement, making empty measurements an explicit zero."""

    if histogram.empty:
        return DistributionScore(0.0, 1.0, 1.0, True)
    w1 = normalized_wasserstein_1(histogram.probs, target_probs, histogram.bins)
    js = jensen_shannon_divergence(histogram.probs, target_probs)
    return DistributionScore(1.0 - w1, w1, js, False)


def _validate_distributions(
    measured: Sequence[float], target: Sequence[float], bins: Sequence[float]
) -> None:
    if len(measured) != len(target) or len(measured) != len(bins) - 1:
        raise ValueError("distribution lengths must equal len(bins)-1")
    for name, distribution in (("measured", measured), ("target", target)):
        if any(value < 0 or not math.isfinite(value) for value in distribution):
            raise ValueError(f"{name} distribution must contain finite non-negative values")
        if not math.isclose(sum(distribution), 1.0, rel_tol=0, abs_tol=1e-9):
            raise ValueError(f"{name} distribution must sum to 1")
