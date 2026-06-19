"""GET /admin/configs returns saved configs as summaries."""
from unittest.mock import patch

import pytest

from src.types.config import InterviewConfig, JDSummary, InterviewPlan
from src.types.interview import ExperienceLevel


def _cfg(cid: str) -> InterviewConfig:
    return InterviewConfig(
        id=cid, title="t", role="backend", experience_level=ExperienceLevel.MID,
        job_description="jd", total_questions=6, core_question_ratio=0.8,
        jd_summary=JDSummary(), interview_plan=InterviewPlan(), created_at="2026-06-19T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_list_configs_returns_summaries():
    from src.routes.admin import list_configs
    with patch("src.routes.admin.list_configs_store", return_value=[_cfg("a"), _cfg("b")]):
        resp = await list_configs()
    assert resp.total == 2
    assert {c.id for c in resp.configs} == {"a", "b"}
