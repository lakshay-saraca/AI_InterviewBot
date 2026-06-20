"""POST /voice/session/start-from-jd.

WHY: the endpoint must (a) reject non-admins BEFORE any LLM call, (b) build the voice
session's questions from the JD plan (so JD questions actually get asked), and
(c) fail loud at each stage instead of starting a half-built interview.
"""
import io
from unittest.mock import patch

import pytest
from fastapi import HTTPException, UploadFile

from src.lib.jd_extract import JDExtractError
from src.services.llm.jd_analysis import JDAnalysisError
from src.services.interview.plan_builder import InsufficientQuestionsError
from src.services.interview.special_questions import build_jd_question
from src.types.config import InterviewPlan, JDSummary
from src.types.interview import ExperienceLevel


def _upload(name="jd.pdf", data=b"%PDF-bytes") -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(data))


class _Req:
    """Minimal stand-in for starlette Request (only .url is used)."""

    class _Url:
        scheme = "http"
        netloc = "testserver"

    url = _Url()


@pytest.mark.asyncio
async def test_wrong_admin_key_rejected_before_llm():
    from src.routes.admin import require_admin

    with pytest.raises(HTTPException) as exc:
        await require_admin(x_admin_key="not-the-key")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_happy_path_session_questions_come_from_jd_plan():
    from src.routes.voice_api import start_voice_session_from_jd

    summary = JDSummary(skills=["python"], responsibilities=["apis"], seniority_signals=["mid"])
    ideas = [{"question_text": "Explain async IO", "topic": "async"},
             {"question_text": "Design a rate limiter", "topic": "systems"}]
    plan = InterviewPlan(questions=[
        build_jd_question("Explain async IO", "async", 0),
        build_jd_question("Design a rate limiter", "systems", 1),
    ])

    with (
        patch("src.routes.voice_api.extract_jd_text", return_value="JD TEXT"),
        patch("src.routes.voice_api.analyze_jd", return_value=(summary, ideas)),
        patch("src.routes.voice_api.build_plan", return_value=plan),
    ):
        resp = await start_voice_session_from_jd(
            request=_Req(),
            file=_upload(),
            candidate_name="Alex",
            job_role="Backend Engineer",
            experience_level=ExperienceLevel.MID,
        )

    from src.services.audio.voice_session import get_voice_session
    import json

    sess = get_voice_session(resp.session_id)
    assert sess is not None
    stored = json.loads(sess["questions"])
    assert [q["question_text"] for q in stored] == ["Explain async IO", "Design a rate limiter"]
    assert resp.ws_url.endswith(f"/ws/interview/voice/{resp.session_id}?token={resp.token}")


@pytest.mark.asyncio
async def test_unreadable_file_returns_422():
    from src.routes.voice_api import start_voice_session_from_jd

    with patch("src.routes.voice_api.extract_jd_text", side_effect=JDExtractError("bad")):
        with pytest.raises(HTTPException) as exc:
            await start_voice_session_from_jd(
                request=_Req(), file=_upload(), candidate_name="Alex",
                job_role="Backend Engineer", experience_level=ExperienceLevel.MID,
            )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_jd_analysis_failure_returns_502():
    from src.routes.voice_api import start_voice_session_from_jd

    with (
        patch("src.routes.voice_api.extract_jd_text", return_value="JD TEXT"),
        patch("src.routes.voice_api.analyze_jd", side_effect=JDAnalysisError("boom")),
    ):
        with pytest.raises(HTTPException) as exc:
            await start_voice_session_from_jd(
                request=_Req(), file=_upload(), candidate_name="Alex",
                job_role="Backend Engineer", experience_level=ExperienceLevel.MID,
            )
    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_insufficient_questions_returns_422():
    from src.routes.voice_api import start_voice_session_from_jd

    summary = JDSummary(skills=["python"])
    with (
        patch("src.routes.voice_api.extract_jd_text", return_value="JD TEXT"),
        patch("src.routes.voice_api.analyze_jd", return_value=(summary, [{"question_text": "Q", "topic": "t"}])),
        patch("src.routes.voice_api.build_plan", side_effect=InsufficientQuestionsError("not enough")),
    ):
        with pytest.raises(HTTPException) as exc:
            await start_voice_session_from_jd(
                request=_Req(), file=_upload(), candidate_name="Alex",
                job_role="Backend Engineer", experience_level=ExperienceLevel.MID,
            )
    assert exc.value.status_code == 422
