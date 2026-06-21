"""Deterministic question-count math for an interview plan.

total_questions includes 2 reserved slots (behavioral + project deep-dive).
The remaining technical pool is split into core (bank) and JD-specific questions.
"""

RESERVED_SLOTS = 2  # behavioral (disagreement) + project deep-dive


def compute_split(total_questions: int, core_ratio: float) -> tuple[int, int]:
    """Return (core_count, jd_count) for the technical pool.

    Both counts are floored at 1 for any valid total (>= 4) and any ratio in
    (0, 1): JD is floored so a JD-driven config always asks at least one JD
    question, and JD is capped at technical-1 so a JD-heavy ratio still leaves
    at least one core question.
    """
    technical = total_questions - RESERVED_SLOTS
    jd_count = max(1, technical - round(technical * core_ratio))
    jd_count = min(jd_count, technical - 1)  # leave at least one core question
    core_count = technical - jd_count
    return core_count, jd_count


def compute_voice_split(
    technical_count: int, core_ratio: float, has_jd: bool
) -> tuple[int, int]:
    """Split the VOICE technical pool into (core_count, jd_count).

    technical_count IS the technical pool (NOT a total with reserved slots —
    behavioral/project/resume are added separately by build_voice_plan). With no
    JD, all technical questions come from the bank. With a JD, jd is floored at 1
    and capped at technical-1 so at least one core question always remains.
    """
    if technical_count < 1:
        raise ValueError(f"technical_count must be >= 1, got {technical_count}")
    if not has_jd or technical_count == 1:
        return technical_count, 0
    jd_count = max(1, technical_count - round(technical_count * core_ratio))
    jd_count = min(jd_count, technical_count - 1)
    return technical_count - jd_count, jd_count
