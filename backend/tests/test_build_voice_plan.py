"""Voice plan assembly: difficulty ramp, optional JD, additive resume/behavioral/project.

WHY: The admin's number is TECHNICAL-only; behavioral + project + resume are
additive. The first two technical questions must be the easiest (junior ease-in),
JD questions are optional, and a thin bank must fail loud rather than silently
under-deliver.
"""
import pytest
from src.services.interview.plan_builder import (
    build_voice_plan,
    order_easy_first,
    InsufficientQuestionsError,
)
from src.types.config import JDSummary
from src.types.interview import ExperienceLevel, Question, QuestionType


def _q(qid, difficulty, level="mid"):
    return Question(
        id=qid, topic=qid, difficulty=difficulty, question_type=QuestionType.CONCEPTUAL,
        experience_level=level, question_text=f"Q {qid}", rubric={"criteria": ["x"]},
    )


def test_order_easy_first_puts_two_easiest_in_front():
    qs = [_q("a", "medium"), _q("b", "hard"), _q("c", "easy"), _q("d", "easy"), _q("e", "medium")]
    out = order_easy_first(qs)
    assert [q.id for q in out[:2]] == ["c", "d"]          # the two easies, stable order
    assert [q.id for q in out[2:]] == ["a", "b", "e"]     # rest keep original order


def test_order_easy_first_noop_for_two_or_fewer():
    qs = [_q("a", "hard"), _q("b", "hard")]
    assert [q.id for q in order_easy_first(qs)] == ["a", "b"]


def test_build_voice_plan_no_jd_all_core_plus_extras(monkeypatch):
    bank = [_q(f"c{i}", "easy" if i < 2 else "medium", "junior") for i in range(5)]
    monkeypatch.setattr(
        "src.services.interview.plan_builder.get_question_set",
        lambda role, level, skills, count: bank[:count],
    )
    plan = build_voice_plan(
        role="Backend", experience_level=ExperienceLevel.JUNIOR,
        jd_summary=JDSummary(skills=["python"]), jd_question_ideas=[],
        resume_questions=[{"question_text": "Tell me about Acme.", "topic": "acme"}],
        technical_count=5, core_ratio=0.7,
    )
    ids = [q.id for q in plan.questions]
    # 5 technical (all core, no JD) + 1 resume + behavioral + project = 8 total
    assert len(plan.questions) == 8
    assert ids[-2:] == ["behavioral_0", "project_0"]                       # last two
    assert any(q.id == "resume_0" for q in plan.questions)                 # resume present
    assert sum(1 for q in plan.questions if q.tags == ["jd_generated"]) == 0   # no JD
    assert sum(1 for q in plan.questions if q.tags == ["resume_generated"]) == 1
    # first two technical questions are the easiest (junior ease-in)
    assert plan.questions[0].difficulty == "easy"
    assert plan.questions[1].difficulty == "easy"


def test_build_voice_plan_with_jd_splits_pool(monkeypatch):
    bank = [_q(f"c{i}", "medium", "mid") for i in range(10)]
    monkeypatch.setattr(
        "src.services.interview.plan_builder.get_question_set",
        lambda role, level, skills, count: bank[:count],
    )
    plan = build_voice_plan(
        role="Backend", experience_level=ExperienceLevel.MID,
        jd_summary=JDSummary(skills=["python"]),
        jd_question_ideas=[{"question_text": "Design X", "topic": "x"},
                           {"question_text": "Design Y", "topic": "y"},
                           {"question_text": "Design Z", "topic": "z"}],
        resume_questions=[], technical_count=10, core_ratio=0.7,
    )
    jd = sum(1 for q in plan.questions if q.tags == ["jd_generated"])
    core = sum(
        1 for q in plan.questions
        if q.tags not in (["jd_generated"], ["resume_generated"], ["behavioral"], ["project_deepdive"])
    )
    assert jd == 3 and core == 7                                # 7/3 split at count 10
    assert sum(1 for q in plan.questions if q.tags == ["resume_generated"]) == 0


def test_build_voice_plan_fails_loud_on_thin_bank(monkeypatch):
    monkeypatch.setattr(
        "src.services.interview.plan_builder.get_question_set",
        lambda role, level, skills, count: [_q("c0", "easy", "junior")],  # only 1
    )
    with pytest.raises(InsufficientQuestionsError):
        build_voice_plan(
            role="Backend", experience_level=ExperienceLevel.JUNIOR,
            jd_summary=JDSummary(skills=["python"]), jd_question_ideas=[],
            resume_questions=[], technical_count=5, core_ratio=0.7,
        )
