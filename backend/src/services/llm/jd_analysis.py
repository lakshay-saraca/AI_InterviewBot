"""JD analysis via LLM (extraction). Fails loud on error.

Returns (JDSummary, list of JD question dicts). Raises JDAnalysisError on any
LLM or parse failure so the caller can refuse to persist a half-built config.
"""
import json
import logging
import os

from src.lib.anthropic_client import get_anthropic_client, get_model_for_task
from src.types.config import JDSummary

logger = logging.getLogger(__name__)

_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "prompts", "jd_analysis_prompt.txt")


class JDAnalysisError(RuntimeError):
    """Raised when JD analysis cannot produce a usable result."""


def analyze_jd(job_description: str, min_questions: int = 3) -> tuple[JDSummary, list[dict]]:
    with open(_PROMPT_PATH, encoding="utf-8") as f:
        template = f.read()
    prompt = template.replace("{min_questions}", str(min_questions)).replace(
        "{job_description}", job_description
    )

    try:
        client = get_anthropic_client()
        response = client.messages.create(
            model=get_model_for_task("jd_analysis"),
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
    except Exception as exc:
        logger.error("JD analysis LLM call failed: %s", exc)
        raise JDAnalysisError(f"JD analysis LLM call failed: {exc}") from exc

    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise JDAnalysisError("JD analysis returned no JSON object")
    try:
        data = json.loads(raw[start:end])
    except json.JSONDecodeError as exc:
        raise JDAnalysisError(f"JD analysis returned invalid JSON: {exc}") from exc

    summary = JDSummary(
        skills=[str(s) for s in data.get("skills", [])][:8],
        responsibilities=[str(r) for r in data.get("responsibilities", [])],
        seniority_signals=[str(s) for s in data.get("seniority_signals", [])],
    )
    questions = [
        {"question_text": str(q.get("question_text", "")).strip(),
         "topic": str(q.get("topic", "")).strip()}
        for q in data.get("jd_questions", [])
        if str(q.get("question_text", "")).strip()
    ]
    if not questions:
        raise JDAnalysisError("JD analysis produced no usable questions")
    return summary, questions
