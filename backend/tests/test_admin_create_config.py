"""POST /admin/configs.

WHY: JD is mandatory; invalid configs are rejected before any persistence; JD-analysis
failure and DB-write failure both surface as loud HTTP errors (no half-built config).
"""
from unittest.mock import patch, AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.types.admin import CreateConfigRequest
from src.types.config import JDSummary
from src.types.interview import ExperienceLevel
from src.services.interview.plan_builder import InsufficientQuestionsError


def _req(**over):
    base = dict(
        title="Backend Hiring", role="backend engineer",
        experience_level=ExperienceLevel.MID,
        job_description="We need a Python/FastAPI engineer to build APIs.",
        total_questions=6, core_question_ratio=0.8,
    )
    base.update(over)
    return CreateConfigRequest(**base)


def test_blank_jd_rejected_by_model():
    with pytest.raises(ValidationError):
        _req(job_description="   ")


def test_total_below_minimum_rejected_by_model():
    with pytest.raises(ValidationError):
        _req(total_questions=3)


def test_ratio_out_of_range_rejected_by_model():
    with pytest.raises(ValidationError):
        _req(core_question_ratio=1.0)


@pytest.mark.asyncio
async def test_create_config_happy_path_persists():
    from src.routes.admin import create_config
    summary = JDSummary(skills=["python"], responsibilities=["apis"], seniority_signals=["mid"])
    ideas = [{"question_text": "Q1", "topic": "t1"}, {"question_text": "Q2", "topic": "t2"}]
    with (
        patch("src.routes.admin.analyze_jd", return_value=(summary, ideas)),
        patch("src.routes.admin.save_config", new=AsyncMock(return_value=True)) as save,
    ):
        resp = await create_config(_req())
    assert resp.total_questions == 6
    save.assert_awaited_once()


@pytest.mark.asyncio
async def test_jd_analysis_failure_returns_502_and_does_not_persist():
    from src.routes.admin import create_config
    from src.services.llm.jd_analysis import JDAnalysisError
    with (
        patch("src.routes.admin.analyze_jd", side_effect=JDAnalysisError("boom")),
        patch("src.routes.admin.save_config", new=AsyncMock(return_value=True)) as save,
    ):
        with pytest.raises(HTTPException) as exc:
            await create_config(_req())
    assert exc.value.status_code == 502
    save.assert_not_called()


@pytest.mark.asyncio
async def test_insufficient_bank_questions_returns_422():
    from src.routes.admin import create_config
    summary = JDSummary(skills=["python"])
    ideas = [{"question_text": "Q1", "topic": "t1"}]
    with (
        patch("src.routes.admin.analyze_jd", return_value=(summary, ideas)),
        patch("src.routes.admin.build_plan", side_effect=InsufficientQuestionsError("not enough")),
        patch("src.routes.admin.save_config", new=AsyncMock(return_value=True)) as save,
    ):
        with pytest.raises(HTTPException) as exc:
            await create_config(_req())
    assert exc.value.status_code == 422
    save.assert_not_called()


@pytest.mark.asyncio
async def test_db_write_failure_returns_500():
    from src.routes.admin import create_config
    summary = JDSummary(skills=["python"])
    ideas = [{"question_text": "Q1", "topic": "t1"}, {"question_text": "Q2", "topic": "t2"}]
    with (
        patch("src.routes.admin.analyze_jd", return_value=(summary, ideas)),
        patch("src.routes.admin.save_config", new=AsyncMock(return_value=False)),
    ):
        with pytest.raises(HTTPException) as exc:
            await create_config(_req())
    assert exc.value.status_code == 500
