"""Deterministic 80/20 split math.

WHY: total_questions includes the 2 reserved slots (behavioral + project deep-dive).
The remaining technical pool is split ~80/20 core/JD, but JD is floored at 1 so a
JD-driven config ALWAYS asks at least one JD question, and core is floored at 1.
These floors — not a literal 0.8 — are the invariant we test.
"""
import pytest
from src.services.interview.plan_math import compute_split


@pytest.mark.parametrize(
    "total,ratio,expected_core,expected_jd",
    [
        (6, 0.8, 3, 1),
        (5, 0.8, 2, 1),
        (8, 0.8, 5, 1),
        (4, 0.8, 1, 1),   # floor applies: technical=2 -> jd floored to 1
        (10, 0.8, 6, 2),
    ],
)
def test_compute_split_values(total, ratio, expected_core, expected_jd):
    core, jd = compute_split(total, ratio)
    assert (core, jd) == (expected_core, expected_jd)


@pytest.mark.parametrize("total", [4, 5, 6, 7, 8, 9, 10, 15, 20])
def test_split_invariants(total):
    core, jd = compute_split(total, 0.8)
    assert core >= 1
    assert jd >= 1
    assert core + jd + 2 == total  # 2 reserved slots
