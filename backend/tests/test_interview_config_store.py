"""SQLite persistence for interview configs.

WHY: Configs must persist durably and reload byte-identically (same config ->
same frozen plan). Create must fail loud (return False) when the DB is unavailable,
unlike the reports layer which degrades silently.
"""
import pytest

from src.types.config import InterviewConfig, InterviewPlan, JDSummary
from src.types.interview import ExperienceLevel, Question, QuestionType
import src.models.interview_config as store


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "test_configs.db"))
    monkeypatch.setattr(store, "_db", None)
    yield
    monkeypatch.setattr(store, "_db", None)


def _config() -> InterviewConfig:
    q = Question(
        id="c1", topic="python", difficulty="medium",
        question_type=QuestionType.CONCEPTUAL, experience_level="mid",
        question_text="Explain the GIL.", rubric={"criteria": []}, tags=["bank_core"],
    )
    return InterviewConfig(
        id="cfg-1", title="Backend Hiring", role="backend engineer",
        experience_level=ExperienceLevel.MID, job_description="We need a Python backend dev.",
        total_questions=6, core_question_ratio=0.8,
        jd_summary=JDSummary(skills=["python"], responsibilities=["APIs"], seniority_signals=["mid"]),
        interview_plan=InterviewPlan(questions=[q]),
    )


@pytest.mark.asyncio
async def test_save_then_get_roundtrip_is_identical():
    cfg = _config()
    assert await store.save_config(cfg) is True
    loaded = await store.get_config("cfg-1")
    assert loaded is not None
    assert loaded.interview_plan.questions[0].question_text == "Explain the GIL."
    assert loaded.jd_summary.skills == ["python"]
    assert loaded.total_questions == 6


@pytest.mark.asyncio
async def test_get_missing_returns_none():
    assert await store.get_config("does-not-exist") is None


@pytest.mark.asyncio
async def test_list_configs_returns_saved():
    await store.save_config(_config())
    configs = await store.list_configs()
    assert len(configs) == 1
    assert configs[0].id == "cfg-1"


@pytest.mark.asyncio
async def test_save_fails_loud_when_db_unavailable(monkeypatch):
    async def _no_db():
        return None
    monkeypatch.setattr(store, "_get_db", _no_db)
    assert await store.save_config(_config()) is False
