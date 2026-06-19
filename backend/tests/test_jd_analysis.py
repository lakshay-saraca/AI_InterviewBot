"""JD analysis extraction (LLM).

WHY: JD analysis is extraction (allowed LLM use). It must parse the model's JSON
into a JDSummary + JD question ideas, and FAIL LOUD (raise) on LLM/parse failure so
config creation does not persist a half-built config.
"""
from unittest.mock import MagicMock, patch

import pytest

from src.services.llm.jd_analysis import analyze_jd, JDAnalysisError


def _mock_response(text: str):
    resp = MagicMock()
    resp.content = [MagicMock(text=text)]
    return resp


VALID_JSON = """
{
  "skills": ["python", "fastapi"],
  "responsibilities": ["build APIs"],
  "seniority_signals": ["mid-level ownership"],
  "jd_questions": [
    {"question_text": "How do you design a rate limiter?", "topic": "rate limiting"},
    {"question_text": "Explain dependency injection in FastAPI.", "topic": "fastapi"}
  ]
}
"""


def test_analyze_jd_parses_summary_and_questions():
    client = MagicMock()
    client.messages.create.return_value = _mock_response(VALID_JSON)
    with patch("src.services.llm.jd_analysis.get_anthropic_client", return_value=client):
        summary, questions = analyze_jd("We need a Python/FastAPI backend engineer.")
    assert summary.skills == ["python", "fastapi"]
    assert summary.responsibilities == ["build APIs"]
    assert len(questions) == 2
    assert questions[0]["question_text"].startswith("How do you design")


def test_analyze_jd_raises_on_malformed_output():
    client = MagicMock()
    client.messages.create.return_value = _mock_response("not json at all")
    with patch("src.services.llm.jd_analysis.get_anthropic_client", return_value=client):
        with pytest.raises(JDAnalysisError):
            analyze_jd("some jd")


def test_analyze_jd_raises_on_client_error():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("API down")
    with patch("src.services.llm.jd_analysis.get_anthropic_client", return_value=client):
        with pytest.raises(JDAnalysisError):
            analyze_jd("some jd")
