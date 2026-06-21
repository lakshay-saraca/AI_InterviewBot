"""POST /voice/session/start-from-jd (resume-primary, JD-optional).

WHY: the endpoint must (a) reject non-admins before any LLM call; (b) build the
voice plan from resume + optional JD with an admin-chosen technical count; (c) cap
the count to bank capacity when no JD is attached; (d) fail loud at each stage
instead of starting a half-built interview; (e) store jd_summary for the outro.
"""
import io
import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException, UploadFile

from src.lib.jd_extract import JDExtractError
from src.services.interview.plan_builder import InsufficientQuestionsError
from src.services.interview.special_questions import build_jd_question, build_resume_question
from src.types.config import InterviewPlan, JDSummary
from src.types.interview import ExperienceLevel


def _upload(name="doc.pdf", data=b"%PDF-bytes"):
    return UploadFile(filename=name, file=io.BytesIO(data))


class _Req:
    class _Url:
        scheme = "http"; netloc = "testserver"
    url = _Url()


def _no_session_stored():
    from src.services.audio.voice_session import _MEMORY
    return len(_MEMORY) == 0


@pytest.mark.asyncio
async def test_wrong_admin_key_rejected_before_llm():
    from src.routes.admin import require_admin
    with pytest.raises(HTTPException) as exc:
        await require_admin(x_admin_key="not-the-key")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_resume_only_builds_plan_and_stores_jd_summary():
    from src.routes.voice_api import start_voice_session_from_jd

    plan = InterviewPlan(questions=[
        build_resume_question("Tell me about Acme.", "acme", 0),
        build_resume_question("Tell me about K8s.", "k8s", 1),
    ])
    with (
        patch("src.routes.voice_api.extract_jd_text", return_value="RESUME TEXT"),
        patch("src.routes.voice_api.analyze_resume", return_value=(["python"], [
            {"question_text": "Tell me about Acme.", "topic": "acme"}])),
        patch("src.routes.voice_api.build_voice_plan", return_value=plan),
    ):
        resp = await start_voice_session_from_jd(
            request=_Req(), resume=_upload("resume.pdf"), jd=None,
            candidate_name="Alex", job_role="Backend Engineer",
            experience_level=ExperienceLevel.JUNIOR, num_questions=5,
        )

    from src.services.audio.voice_session import get_voice_session
    sess = get_voice_session(resp.session_id)
    assert sess is not None
    assert json.loads(sess["transcript"])[0]["type"] == "intro"   # split opening
    assert "jd_summary" in sess


@pytest.mark.asyncio
async def test_num_questions_capped_when_no_jd(monkeypatch):
    from src.routes import voice_api

    captured = {}
    def _fake_build(**kwargs):
        captured.update(kwargs)
        return InterviewPlan(questions=[build_resume_question("x", "x", 0)])

    monkeypatch.setattr(voice_api, "build_voice_plan", _fake_build)
    monkeypatch.setattr(voice_api, "eligible_question_count", lambda level: 5)
    monkeypatch.setattr(voice_api, "analyze_resume", lambda text, num_questions=2: (["py"], [
        {"question_text": "q", "topic": "t"}]))
    monkeypatch.setattr(voice_api, "extract_jd_text", lambda fn, data: "TEXT")

    await voice_api.start_voice_session_from_jd(
        request=_Req(), resume=_upload(), jd=None,
        candidate_name="Alex", job_role="Backend", experience_level=ExperienceLevel.JUNIOR,
        num_questions=10,   # asked for 10, bank only supports 5
    )
    assert captured["technical_count"] == 5            # capped to capacity
    assert captured["jd_question_ideas"] == []


@pytest.mark.asyncio
async def test_num_questions_out_of_range_rejected():
    from src.routes.voice_api import start_voice_session_from_jd
    with pytest.raises(HTTPException) as exc:
        await start_voice_session_from_jd(
            request=_Req(), resume=_upload(), jd=None, candidate_name="Alex",
            job_role="Backend", experience_level=ExperienceLevel.MID, num_questions=99,
        )
    assert exc.value.status_code == 422
    assert _no_session_stored()


@pytest.mark.asyncio
async def test_unreadable_resume_returns_422():
    from src.routes.voice_api import start_voice_session_from_jd
    with patch("src.routes.voice_api.extract_jd_text", side_effect=JDExtractError("bad")):
        with pytest.raises(HTTPException) as exc:
            await start_voice_session_from_jd(
                request=_Req(), resume=_upload(), jd=None, candidate_name="Alex",
                job_role="Backend", experience_level=ExperienceLevel.MID, num_questions=5,
            )
    assert exc.value.status_code == 422
    assert _no_session_stored()


@pytest.mark.asyncio
async def test_insufficient_questions_returns_422_without_leak():
    from src.routes.voice_api import start_voice_session_from_jd
    with (
        patch("src.routes.voice_api.extract_jd_text", return_value="TEXT"),
        patch("src.routes.voice_api.analyze_resume", return_value=(["py"], [
            {"question_text": "q", "topic": "t"}])),
        patch("src.routes.voice_api.build_voice_plan", side_effect=InsufficientQuestionsError("need 5")),
    ):
        with pytest.raises(HTTPException) as exc:
            await start_voice_session_from_jd(
                request=_Req(), resume=_upload(), jd=None, candidate_name="Alex",
                job_role="Backend", experience_level=ExperienceLevel.MID, num_questions=5,
            )
    assert exc.value.status_code == 422
    assert "need" not in (exc.value.detail or "").lower()
    assert _no_session_stored()
