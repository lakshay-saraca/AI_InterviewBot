"""Deterministic question-count math for an interview plan.

total_questions includes 2 reserved slots (behavioral + project deep-dive).
The remaining technical pool is split into core (bank) and JD-specific questions.
"""

RESERVED_SLOTS = 2  # behavioral (disagreement) + project deep-dive


def compute_split(total_questions: int, core_ratio: float) -> tuple[int, int]:
    """Return (core_count, jd_count) for the technical pool.

    JD is floored at 1 so a JD-driven config always asks at least one JD question;
    core is therefore floored at 1 for any valid total (>= 4).
    """
    technical = total_questions - RESERVED_SLOTS
    jd_count = max(1, technical - round(technical * core_ratio))
    core_count = technical - jd_count
    return core_count, jd_count
