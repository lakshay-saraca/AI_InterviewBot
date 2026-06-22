"""Additive technical-pool split for the VOICE flow.

WHY: Unlike the config flow's compute_split (which reserves 2 slots inside the
total), the voice admin's number IS the technical pool — behavioral/project/resume
are added on top elsewhere. When NO JD is uploaded, every technical question must
come from the bank (jd_count == 0). When a JD IS present, at least one JD question
AND at least one core question must remain.
"""
import pytest
from src.services.interview.plan_math import compute_voice_split


@pytest.mark.parametrize(
    "technical,ratio,has_jd,expected",
    [
        (5, 0.7, False, (5, 0)),    # no JD -> all core
        (10, 0.7, False, (10, 0)),
        (5, 0.7, True, (4, 1)),     # JD present -> at least 1 JD
        (10, 0.7, True, (7, 3)),
        (1, 0.7, True, (1, 0)),     # can't reserve a JD from a pool of 1
    ],
)
def test_compute_voice_split_values(technical, ratio, has_jd, expected):
    assert compute_voice_split(technical, ratio, has_jd) == expected


@pytest.mark.parametrize("technical", [5, 6, 7, 8, 9, 10])
@pytest.mark.parametrize("ratio", [0.5, 0.7, 0.8, 0.95])
def test_jd_present_keeps_one_of_each(technical, ratio):
    core, jd = compute_voice_split(technical, ratio, has_jd=True)
    assert core >= 1
    assert jd >= 1
    assert core + jd == technical


@pytest.mark.parametrize("technical", [5, 6, 7, 8, 9, 10])
def test_no_jd_is_all_core(technical):
    core, jd = compute_voice_split(technical, 0.7, has_jd=False)
    assert (core, jd) == (technical, 0)


def test_rejects_nonpositive_pool():
    with pytest.raises(ValueError):
        compute_voice_split(0, 0.7, has_jd=False)
