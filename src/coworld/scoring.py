"""Histogram construction and distribution-distance scoring."""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

SCORE_METHOD = "w1-hyperbolic/1"
LEGACY_SCORE_METHOD = "w1-support/1"
WELLNESS_SCORE_METHOD = "wellness-sum/1"
WELLNESS_COMPONENTS = ("health", "conflict", "social", "family", "wealth")


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
    raw_w1: float | None
    w1_scale: float
    js_divergence: float
    empty_measurement: bool


@dataclass(frozen=True, slots=True)
class AgentWellnessMean:
    """One agent's windowed wellness and component means."""

    agent_id: int
    seat: int
    wellness: float
    components: tuple[float, float, float, float, float]


@dataclass(frozen=True, slots=True)
class WellnessScore:
    """Summed survivor wellness and equal-agent diagnostic means."""

    score: float
    survivor_count: int
    mean_wellness: float
    component_means: tuple[float, float, float, float, float]

    def component_dict(self) -> dict[str, float]:
        return dict(zip(WELLNESS_COMPONENTS, self.component_means))


def make_histogram(samples: Iterable[float], bins: Sequence[float]) -> Histogram:
    """Bin finite samples, clamping out-of-support values to the edge bins."""

    edges = tuple(float(edge) for edge in bins)
    if len(edges) < 2 or any(
        left >= right for left, right in zip(edges, edges[1:])
    ):
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


def wasserstein_1(
    measured: Sequence[float],
    target: Sequence[float],
    bins: Sequence[float],
) -> float:
    """Return raw binned Wasserstein-1 distance in the variable's units."""

    _validate_distributions(measured, target, bins)
    cumulative_measured = 0.0
    cumulative_target = 0.0
    distance = 0.0
    for index, width in enumerate(
        right - left for left, right in zip(bins, bins[1:])
    ):
        cumulative_measured += measured[index]
        cumulative_target += target[index]
        distance += abs(cumulative_measured - cumulative_target) * width
    return distance


def target_scale(target: Sequence[float], bins: Sequence[float]) -> float:
    """Return the target's characteristic W1 scale, floored at one median bin."""

    _validate_distributions(target, target, bins)
    cumulative = 0.0
    median_index = 0
    for index, probability in enumerate(target):
        cumulative += probability
        if cumulative >= 0.5:
            median_index = index
            break
    point_mass = [0.0] * len(target)
    point_mass[median_index] = 1.0
    median_distance = wasserstein_1(point_mass, target, bins)
    median_bin_width = bins[median_index + 1] - bins[median_index]
    return max(median_distance, median_bin_width)


def jensen_shannon_divergence(
    measured: Sequence[float], target: Sequence[float]
) -> float:
    """Return base-2 Jensen-Shannon divergence in the interval [0, 1]."""

    if len(measured) != len(target):
        raise ValueError("distributions must have equal lengths")
    for name, distribution in (("measured", measured), ("target", target)):
        if any(value < 0 or not math.isfinite(value) for value in distribution):
            raise ValueError(
                f"{name} distribution must contain finite non-negative values"
            )
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


def score_histogram(
    histogram: Histogram, target_probs: Sequence[float]
) -> DistributionScore:
    """Score one measurement, making empty measurements an explicit zero."""

    scale = target_scale(target_probs, histogram.bins)
    if histogram.empty:
        return DistributionScore(0.0, None, scale, 1.0, True)
    raw_w1 = wasserstein_1(histogram.probs, target_probs, histogram.bins)
    js = jensen_shannon_divergence(histogram.probs, target_probs)
    return DistributionScore(scale / (scale + raw_w1), raw_w1, scale, js, False)


def score_wellness(agents: Iterable[AgentWellnessMean]) -> WellnessScore:
    """Sum normalized wellness while retaining equal-agent diagnostics."""
    values = tuple(agents)
    if not values:
        return WellnessScore(0.0, 0, 0.0, (0.0, 0.0, 0.0, 0.0, 0.0))
    count = len(values)
    score = sum(agent.wellness for agent in values)
    components = tuple(
        sum(agent.components[index] for agent in values) / count
        for index in range(len(WELLNESS_COMPONENTS))
    )
    return WellnessScore(score, count, score / count, components)


def _validate_distributions(
    measured: Sequence[float], target: Sequence[float], bins: Sequence[float]
) -> None:
    if len(measured) != len(target) or len(measured) != len(bins) - 1:
        raise ValueError("distribution lengths must equal len(bins)-1")
    for name, distribution in (("measured", measured), ("target", target)):
        if any(value < 0 or not math.isfinite(value) for value in distribution):
            raise ValueError(
                f"{name} distribution must contain finite non-negative values"
            )
        if not math.isclose(sum(distribution), 1.0, rel_tol=0, abs_tol=1e-9):
            raise ValueError(f"{name} distribution must sum to 1")
