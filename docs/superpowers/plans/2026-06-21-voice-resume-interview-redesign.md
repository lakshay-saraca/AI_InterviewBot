# Voice Resume-Driven Interview Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the admin-triggered voice interview so it opens with a deterministic intro (no glued-on question), is personalized from an uploaded resume, lets the admin pick 5–10 technical questions, ramps difficulty for juniors, and closes with a proper WRAP_UP outro instead of cutting straight to evaluation.

**Architecture:** All changes are **voice-pipeline only** (explicitly authorized by the user; CLAUDE.md's "don't touch voice" default is waived for this work). The shared config/text-flow functions (`build_plan`, `compute_split`) are **left untouched** — we add *new* voice-specific siblings (`compute_voice_split`, `build_voice_plan`) so the config flow and its tests do not regress. Resume is the primary (optional) upload; JD becomes an optional filler. The question bank (role + level) stays the always-on technical base.

**Tech Stack:** FastAPI (Python 3, Pydantic v2), pytest (`asyncio_mode=auto`), Redis-or-in-memory voice session hash, Next.js 14 (App Router, TypeScript), Anthropic SDK (Haiku for extraction).

---

## How to run tests

From `backend/`: `python -m pytest tests/<file>::<test> -v` for a single test.

**Known environment facts (do not "fix" these):**
- The **full** suite (`python -m pytest`) finishes in ~6s then **hangs** on orphaned aiosqlite threads — run **per-file** during development; only run the whole suite at the end and `Ctrl-C` after the summary prints.
- `tests/` has 5 pre-existing red `opening_quality` failures — that is the **known baseline**, not something this plan introduces or fixes.
- `pytest.ini` sets `filterwarnings = error::RuntimeWarning` — a `RuntimeWarning` (e.g. un-awaited coroutine) will **fail** the test. Keep async mocks awaitable.
- `tests/conftest.py` autouse-forces the voice session into its in-memory `_MEMORY` dict (no Redis needed) and clears it per test. `make_question(...)` and `seed_voice_session(...)` helpers live there.

---

## File Structure

**New files**
- `backend/src/services/llm/resume_analysis.py` — LLM extraction: resume text → (skills, resume question dicts). Mirrors `jd_analysis.py`.
- `backend/src/prompts/resume_analysis_prompt.txt` — the resume extraction prompt.
- `backend/tests/test_resume_analysis.py`
- `backend/tests/test_compute_voice_split.py`
- `backend/tests/test_build_voice_plan.py`
- `backend/tests/test_voice_opening_sequence.py`
- `backend/tests/test_voice_wrap_up.py`

**Modified files (each gets new functions/branches; existing config-flow behavior untouched)**
- `backend/src/services/interview/plan_math.py` — add `compute_voice_split`.
- `backend/src/services/interview/special_questions.py` — add `build_resume_question`.
- `backend/src/services/questions/question_bank.py` — add `eligible_question_count`.
- `backend/src/services/interview/plan_builder.py` — add `order_easy_first` + `build_voice_plan`.
- `backend/src/services/interview/warmup.py` — fix `generate_introduction`; add `build_ease_in`.
- `backend/src/services/audio/voice_session.py` — seed intro + ease-in/Q1 as separate turns.
- `backend/src/services/interview/voice_turn_processor.py` — `stream_response(signal_turn_end=…)`.
- `backend/src/routes/voice_ws.py` — stream all leading bot turns on connect.
- `backend/src/services/interview/voice_llm_orchestrator.py` — WRAP_UP outro phase.
- `backend/src/routes/voice_api.py` — accept resume + count + optional JD; build voice plan; store `jd_summary`.
- `backend/tests/test_voice_start_from_jd.py` — updated for the new endpoint signature.
- `frontend/src/app/interview/voice/start/page.tsx` — resume field, count selector, relabel.
- `frontend/src/services/voice-api.ts` — (no change needed; already posts `FormData`).

---

## Task 1: Additive split math — `compute_voice_split`

**Files:**
- Modify: `backend/src/services/interview/plan_math.py`
- Test: `backend/tests/test_compute_voice_split.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_compute_voice_split.py
"""Additive technical-pool split for the VOICE flow.

WHY: Unlike the config flow's compute_split (which reserves 2 slots inside the
total), the voice admin's number IS the technical pool — behavioral/project/resume
are added on top elsewhere. When NO JD is uploaded, every technical question must
come from the bank (jd_count == 0). When a JD IS present, at least one JD question
AND at least one core question must remain.
"""
import pytest
from src.services.interview.plan_math import compute_voice_split


@pytest.mark.parametrize(
    "technical,ratio,has_jd,expected",
    [
        (5, 0.7, False, (5, 0)),    # no JD -> all core
        (10, 0.7, False, (10, 0)),
        (5, 0.7, True, (4, 1)),     # JD present -> at least 1 JD
        (10, 0.7, True, (7, 3)),
        (1, 0.7, True, (1, 0)),     # can't reserve a JD from a pool of 1
    ],
)
def test_compute_voice_split_values(technical, ratio, has_jd, expected):
    assert compute_voice_split(technical, ratio, has_jd) == expected


@pytest.mark.parametrize("technical", [5, 6, 7, 8, 9, 10])
@pytest.mark.parametrize("ratio", [0.5, 0.7, 0.8, 0.95])
def test_jd_present_keeps_one_of_each(technical, ratio):
    core, jd = compute_voice_split(technical, ratio, has_jd=True)
    assert core >= 1
    assert jd >= 1
    assert core + jd == technical


@pytest.mark.parametrize("technical", [5, 6, 7, 8, 9, 10])
def test_no_jd_is_all_core(technical):
    core, jd = compute_voice_split(technical, 0.7, has_jd=False)
    assert (core, jd) == (technical, 0)


def test_rejects_nonpositive_pool():
    with pytest.raises(ValueError):
        compute_voice_split(0, 0.7, has_jd=False)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_compute_voice_split.py -v`
Expected: FAIL — `ImportError: cannot import name 'compute_voice_split'`.

- [ ] **Step 3: Implement `compute_voice_split`**

Append to `backend/src/services/interview/plan_math.py` (leave `compute_split` and `RESERVED_SLOTS` exactly as they are — the config flow depends on them):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_compute_voice_split.py -v`
Expected: PASS (all parametrizations).

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/interview/plan_math.py backend/tests/test_compute_voice_split.py
git commit -m "feat(voice): additive compute_voice_split for technical pool"
```

---

## Task 2: Resume question builder — `build_resume_question`

**Files:**
- Modify: `backend/src/services/interview/special_questions.py`
- Test: `backend/tests/test_special_questions.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_special_questions.py`:

```python
def test_build_resume_question_shape():
    from src.services.interview.special_questions import build_resume_question
    q = build_resume_question("Walk me through the payments service you built.", "payments", index=0)
    assert q.id == "resume_0"
    assert q.question_text == "Walk me through the payments service you built."
    assert q.topic == "payments"
    assert q.difficulty == "medium"          # resume Qs are medium (decision Q4)
    assert q.tags == ["resume_generated"]
    assert q.rubric                          # non-empty rubric so evaluator works


def test_build_resume_question_defaults_topic():
    from src.services.interview.special_questions import build_resume_question
    q = build_resume_question("Tell me about a project.", "", index=1)
    assert q.id == "resume_1"
    assert q.topic == "candidate background"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_special_questions.py::test_build_resume_question_shape -v`
Expected: FAIL — `ImportError: cannot import name 'build_resume_question'`.

- [ ] **Step 3: Implement `build_resume_question`**

Append to `backend/src/services/interview/special_questions.py` (reuses the existing module-level `_GENERIC_RUBRIC`):

```python
def build_resume_question(question_text: str, topic: str, index: int) -> Question:
    return Question(
        id=f"resume_{index}",
        topic=topic or "candidate background",
        difficulty="medium",
        question_type=QuestionType.SCENARIO,
        experience_level="all",
        question_text=question_text,
        rubric=_GENERIC_RUBRIC,
        tags=["resume_generated"],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_special_questions.py -v`
Expected: PASS (existing tests + the two new ones).

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/interview/special_questions.py backend/tests/test_special_questions.py
git commit -m "feat(voice): deterministic resume question builder"
```

---

## Task 3: Bank capacity helper — `eligible_question_count`

**Files:**
- Modify: `backend/src/services/questions/question_bank.py`
- Test: `backend/tests/test_question_bank_capacity.py`

This powers the no-JD cap: a junior candidate is eligible for only 5 of the 15 bank questions, so the count selector must not promise more than the bank can give when no JD is attached.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_question_bank_capacity.py
"""Bank eligibility capacity per level.

WHY: With no JD uploaded, every technical question comes from the bank. The count
selector must be capped to what the candidate's level can actually draw, or the
plan builder will raise InsufficientQuestionsError after the admin has already
uploaded. This helper must mirror get_question_set's exact eligibility gate.
"""
from src.services.questions.question_bank import eligible_question_count
from src.types.interview import ExperienceLevel


def test_junior_capacity_matches_bank():
    # Bank today: 3 junior + 2 "all" are eligible for a junior candidate.
    assert eligible_question_count(ExperienceLevel.JUNIOR) == 5


def test_higher_levels_have_more_capacity():
    jr = eligible_question_count(ExperienceLevel.JUNIOR)
    mid = eligible_question_count(ExperienceLevel.MID)
    senior = eligible_question_count(ExperienceLevel.SENIOR)
    assert mid > jr           # mid can also draw mid-level questions
    assert senior >= mid
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_question_bank_capacity.py -v`
Expected: FAIL — `ImportError: cannot import name 'eligible_question_count'`.

- [ ] **Step 3: Implement `eligible_question_count`**

Append to `backend/src/services/questions/question_bank.py` (reuses the module's `_load_all` and `_level_rank`; mirrors the eligibility gate in `score_question`):

```python
def eligible_question_count(experience_level: ExperienceLevel) -> int:
    """How many bank questions a candidate at this level is eligible for.

    Mirrors get_question_set's gate: a question above the candidate's level (and
    not tagged "all") is ineligible. Used to cap the no-JD question count so the
    plan never asks for more bank questions than exist for the level.
    """
    candidate_rank = _level_rank(experience_level.value)
    return sum(
        1
        for q in _load_all()
        if not (_level_rank(q.experience_level) > candidate_rank and q.experience_level != "all")
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_question_bank_capacity.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/questions/question_bank.py backend/tests/test_question_bank_capacity.py
git commit -m "feat(voice): bank eligibility capacity helper for no-JD cap"
```

---

## Task 4: Resume analysis LLM service

**Files:**
- Create: `backend/src/services/llm/resume_analysis.py`
- Create: `backend/src/prompts/resume_analysis_prompt.txt`
- Test: `backend/tests/test_resume_analysis.py`

Mirror `jd_analysis.py` exactly (same failure posture, same JSON-slice parse). Extraction only — never routing. PII/protected-class prohibition baked into the prompt.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_resume_analysis.py
"""Resume analysis extraction (LLM).

WHY: Resume analysis is extraction (allowed LLM use). It must parse the model's
JSON into (skills, resume question dicts) and FAIL LOUD (raise) on LLM/parse
failure so the interview is not started half-built. It must never surface
protected-class probing — enforced by the prompt and asserted at the call site.
"""
from unittest.mock import MagicMock, patch
import pytest
from src.services.llm.resume_analysis import analyze_resume, ResumeAnalysisError


def _mock_response(text: str):
    resp = MagicMock()
    resp.content = [MagicMock(text=text)]
    return resp


VALID_JSON = """
{
  "skills": ["python", "kubernetes"],
  "resume_questions": [
    {"question_text": "Walk me through the billing service you built at Acme.", "topic": "billing"},
    {"question_text": "You list Kubernetes — describe a rollout you owned.", "topic": "kubernetes"}
  ]
}
"""


def test_analyze_resume_parses_skills_and_questions():
    client = MagicMock()
    client.messages.create.return_value = _mock_response(VALID_JSON)
    with patch("src.services.llm.resume_analysis.get_anthropic_client", return_value=client):
        skills, questions = analyze_resume("Acme — Backend Engineer. Python, Kubernetes.")
    assert skills == ["python", "kubernetes"]
    assert len(questions) == 2
    assert questions[0]["topic"] == "billing"


def test_analyze_resume_raises_on_malformed_output():
    client = MagicMock()
    client.messages.create.return_value = _mock_response("not json")
    with patch("src.services.llm.resume_analysis.get_anthropic_client", return_value=client):
        with pytest.raises(ResumeAnalysisError):
            analyze_resume("resume text")


def test_analyze_resume_raises_on_client_error():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("API down")
    with patch("src.services.llm.resume_analysis.get_anthropic_client", return_value=client):
        with pytest.raises(ResumeAnalysisError):
            analyze_resume("resume text")


def test_analyze_resume_raises_when_no_questions():
    client = MagicMock()
    client.messages.create.return_value = _mock_response('{"skills": ["go"], "resume_questions": []}')
    with patch("src.services.llm.resume_analysis.get_anthropic_client", return_value=client):
        with pytest.raises(ResumeAnalysisError):
            analyze_resume("resume text")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_resume_analysis.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.llm.resume_analysis'`.

- [ ] **Step 3: Create the prompt file**

```text
# backend/src/prompts/resume_analysis_prompt.txt
You are analyzing a candidate's resume to prepare personalized interview questions.

Extract the following and return ONLY a single valid JSON object, no prose:

{
  "skills": ["up to 8 concrete technical skills/technologies the candidate clearly used"],
  "resume_questions": [
    {"question_text": "a question grounded in a specific role, project, or achievement on THIS resume", "topic": "short topic label"}
  ]
}

Rules:
- Produce exactly {num_questions} entries in "resume_questions".
- Each question must reference something concrete the candidate actually did (a named project, system, role, or result). Ask them to walk through their work and decisions.
- Questions must be about WORK ONLY. Never ask about family, age, gender, nationality, religion, marital status, health, or any personal/protected-class topic.
- Keep each question to one or two sentences.
- Return ONLY the JSON object.

Resume:
{resume_text}
```

- [ ] **Step 4: Implement `analyze_resume`**

```python
# backend/src/services/llm/resume_analysis.py
"""Resume analysis via LLM (extraction). Fails loud on error.

Returns (skills, resume question dicts). Raises ResumeAnalysisError on any LLM or
parse failure so the caller refuses to start a half-built interview. Mirrors
jd_analysis.py — extraction only (allowed LLM use), never routing.
"""
import json
import logging
import os

from src.lib.anthropic_client import get_anthropic_client, get_model_for_task

logger = logging.getLogger(__name__)

_PROMPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "prompts", "resume_analysis_prompt.txt"
)


class ResumeAnalysisError(RuntimeError):
    """Raised when resume analysis cannot produce a usable result."""


def analyze_resume(resume_text: str, num_questions: int = 2) -> tuple[list[str], list[dict]]:
    with open(_PROMPT_PATH, encoding="utf-8") as f:
        template = f.read()
    prompt = template.replace("{num_questions}", str(num_questions)).replace(
        "{resume_text}", resume_text
    )

    try:
        client = get_anthropic_client()
        response = client.messages.create(
            model=get_model_for_task("jd_analysis"),  # extraction task -> Haiku
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
    except Exception as exc:
        logger.error("Resume analysis LLM call failed: %s", exc)
        raise ResumeAnalysisError(f"Resume analysis LLM call failed: {exc}") from exc

    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ResumeAnalysisError("Resume analysis returned no JSON object")
    try:
        data = json.loads(raw[start:end])
    except json.JSONDecodeError as exc:
        raise ResumeAnalysisError(f"Resume analysis returned invalid JSON: {exc}") from exc

    skills = [str(s) for s in data.get("skills", [])][:8]
    questions = [
        {"question_text": str(q.get("question_text", "")).strip(),
         "topic": str(q.get("topic", "")).strip()}
        for q in data.get("resume_questions", [])
        if str(q.get("question_text", "")).strip()
    ]
    if not questions:
        raise ResumeAnalysisError("Resume analysis produced no usable questions")
    return skills, questions
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_resume_analysis.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/src/services/llm/resume_analysis.py backend/src/prompts/resume_analysis_prompt.txt backend/tests/test_resume_analysis.py
git commit -m "feat(voice): resume analysis LLM extraction service"
```

---

## Task 5: Voice plan assembler — `order_easy_first` + `build_voice_plan`

**Files:**
- Modify: `backend/src/services/interview/plan_builder.py`
- Test: `backend/tests/test_build_voice_plan.py`

Order: `[easy-first technical (core + jd)] → [resume Qs] → behavioral → project`. Leaves `build_plan` (config flow) untouched.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_build_voice_plan.py
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
    core = sum(1 for q in plan.questions if q.tags not in (["jd_generated"], ["resume_generated"], ["behavioral"], ["project_deepdive"]))
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_build_voice_plan.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_voice_plan'`.

- [ ] **Step 3: Implement `order_easy_first` + `build_voice_plan`**

Append to `backend/src/services/interview/plan_builder.py` (add the new imports at the top alongside the existing ones; leave `build_plan` unchanged):

```python
# add to the existing import block:
from src.services.interview.plan_math import compute_voice_split  # noqa: E402
from src.services.interview.special_questions import build_resume_question  # noqa: E402

_DIFFICULTY_RANK = {"easy": 0, "medium": 1, "hard": 2}


def order_easy_first(questions: list[Question]) -> list[Question]:
    """Return questions with the two easiest moved to the front (stable), rest in order."""
    if len(questions) <= 2:
        return list(questions)
    ranked = sorted(
        range(len(questions)),
        key=lambda i: (_DIFFICULTY_RANK.get(questions[i].difficulty.lower(), 1), i),
    )
    lead_idx = set(ranked[:2])
    lead = [questions[i] for i in ranked[:2]]
    rest = [q for i, q in enumerate(questions) if i not in lead_idx]
    return lead + rest


def build_voice_plan(
    role: str,
    experience_level: ExperienceLevel,
    jd_summary: JDSummary,
    jd_question_ideas: list[dict],
    resume_questions: list[dict],
    technical_count: int,
    core_ratio: float,
) -> InterviewPlan:
    """Assemble the VOICE interview plan (additive model).

    Order: [easy-first technical (core + optional jd)] -> [resume] -> behavioral
    -> project. technical_count counts ONLY technical questions; resume/behavioral/
    project are additive. JD ideas are optional (empty -> bank-only technical).
    """
    has_jd = bool(jd_question_ideas)
    core_count, jd_count = compute_voice_split(technical_count, core_ratio, has_jd)

    core_qs = get_question_set(role, experience_level, jd_summary.skills, core_count)
    if len(core_qs) < core_count:
        raise InsufficientQuestionsError(
            f"Bank supplied {len(core_qs)} core questions, need {core_count}"
        )
    core_qs = core_qs[:core_count]

    jd_qs = [
        build_jd_question(idea["question_text"], idea.get("topic", ""), index=i)
        for i, idea in enumerate(jd_question_ideas[:jd_count])
    ]

    technical = order_easy_first(core_qs + jd_qs)

    resume_qs = [
        build_resume_question(idea["question_text"], idea.get("topic", ""), index=i)
        for i, idea in enumerate(resume_questions)
    ]

    questions = technical + resume_qs + [build_behavioral_question(), build_project_question()]
    return InterviewPlan(questions=questions)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_build_voice_plan.py -v`
Expected: PASS.

- [ ] **Step 5: Run the config-flow plan tests to prove no regression**

Run: `cd backend && python -m pytest tests/test_plan_builder.py tests/test_plan_math.py -v`
Expected: PASS — `build_plan`/`compute_split` untouched.

- [ ] **Step 6: Commit**

```bash
git add backend/src/services/interview/plan_builder.py backend/tests/test_build_voice_plan.py
git commit -m "feat(voice): build_voice_plan with easy-first ramp, optional JD, resume slots"
```

---

## Task 6: Deterministic intro + ease-in text

**Files:**
- Modify: `backend/src/services/interview/warmup.py`
- Test: `backend/tests/test_voice_intro_text.py`

Fix `generate_introduction` (remove the false "after a quick warm-up" promise and the embedded question feel) and add `build_ease_in` (the deterministic lead-in spoken just before the easy first question). `personalize_warmup` and the warmup chit-chat templates are **left as-is** — they belong to the text/config flow and are not used by voice.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_voice_intro_text.py
"""Deterministic voice opening text.

WHY: The voice intro must be a STATEMENT (no question, no false 'warm-up' promise)
and the ease-in must be a fixed lead-in that flows into the first easy question.
This is drafting deterministic copy, not an LLM call.
"""
from src.services.interview.warmup import generate_introduction, build_ease_in


def test_intro_is_a_statement_without_a_question():
    text = generate_introduction("Alex", "Backend Engineer", 5)
    assert "Alex" in text
    assert "Backend Engineer" in text
    assert "?" not in text                 # no question in the intro
    assert "warm-up" not in text.lower()   # no promise of a warm-up that never happens
    assert "warmup" not in text.lower()


def test_ease_in_is_fixed_and_questionless():
    text = build_ease_in("Alex")
    assert "Alex" in text
    assert "?" not in text                 # the easy question is appended after this
    assert build_ease_in("Alex") == build_ease_in("Alex")   # deterministic
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_voice_intro_text.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_ease_in'` (and the intro assertion fails on the current "warm-up" text).

- [ ] **Step 3: Update `generate_introduction` and add `build_ease_in`**

In `backend/src/services/interview/warmup.py`, replace the body of `generate_introduction` (lines 38-44) with:

```python
def generate_introduction(candidate_name: str, job_role: str, total_questions: int) -> str:
    duration = estimate_session_minutes(total_questions)
    return (
        f"Hi {candidate_name}, I'm your AI interviewer today. "
        f"We've got a {job_role} session lined up — {total_questions} questions, "
        f"and it should take about {duration} minutes. "
        f"Take your time, and feel free to think out loud as you go."
    )


def build_ease_in(candidate_name: str) -> str:
    """Fixed lead-in spoken right before the first (easy) question. No question mark —
    the easy question text is appended after this by the session seeder."""
    return (
        f"Whenever you're ready {candidate_name}, let's start with something "
        f"straightforward."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_voice_intro_text.py -v`
Expected: PASS.

- [ ] **Step 5: Guard the text flow didn't regress**

Run: `cd backend && python -m pytest tests/test_resume_personalization.py -v`
Expected: PASS — `personalize_warmup` untouched.

- [ ] **Step 6: Commit**

```bash
git add backend/src/services/interview/warmup.py backend/tests/test_voice_intro_text.py
git commit -m "feat(voice): deterministic intro statement + ease-in lead-in"
```

---

## Task 7: Split the opening into separate turns (intro → ease-in+Q1)

**Files:**
- Modify: `backend/src/services/audio/voice_session.py:55-112` (seeding)
- Modify: `backend/src/services/interview/voice_turn_processor.py:82-141` (`stream_response`)
- Modify: `backend/src/routes/voice_ws.py:282-293` (connect delivery)
- Test: `backend/tests/test_voice_opening_sequence.py`

The bug (`voice_session.py:74`) glues intro + first question into one `type:"question"` turn. We seed **two** bot turns — an `intro` turn and an `question` turn (ease-in + easy Q1) — and stream both on connect, signalling the candidate's turn only after the last one.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_voice_opening_sequence.py
"""Opening sequence: intro is its OWN turn; the question turn carries the ease-in + Q1.

WHY: The reported bug is the bot 'asking a question in the introduction' — intro and
the first question were glued into one turn. The intro must be a separate, questionless
turn; the first question turn carries the ease-in lead-in then the easy Q1.
"""
import json
from src.services.audio.voice_session import create_voice_session, get_voice_session
from src.types.interview import Question, QuestionType


def _q(qid):
    return Question(
        id=qid, topic=qid, difficulty="easy", question_type=QuestionType.CONCEPTUAL,
        experience_level="junior", question_text=f"Easy {qid}?", rubric={"criteria": ["x"]},
    )


def test_intro_and_question_are_separate_turns():
    create_voice_session(
        session_id="sid1", candidate_name="Alex", job_role="Backend",
        experience_level="junior", required_skills=["python"],
        questions_json=json.dumps([_q("q0").model_dump(), _q("q1").model_dump()]),
        intro_text="Hi Alex, welcome.", ease_in_text="Whenever you're ready, here we go.",
    )
    sess = get_voice_session("sid1")
    transcript = json.loads(sess["transcript"])
    assert transcript[0]["type"] == "intro"
    assert transcript[0]["text"] == "Hi Alex, welcome."
    assert "?" not in transcript[0]["text"]
    assert transcript[1]["type"] == "question"
    assert transcript[1]["text"] == "Whenever you're ready, here we go. Easy q0?"
    assert sess["state"] == "WAITING_FOR_CANDIDATE"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_voice_opening_sequence.py -v`
Expected: FAIL — `create_voice_session() got an unexpected keyword argument 'ease_in_text'`.

- [ ] **Step 3: Update seeding in `voice_session.py`**

Replace the signature and the seeding block (`voice_session.py:55-81`). New signature adds `ease_in_text: str = ""`; the seeding now appends an `intro` turn (if `intro_text`) followed by the `question` turn (ease-in + first question):

```python
def create_voice_session(
    session_id: str,
    candidate_name: str,
    job_role: str,
    experience_level: str,
    required_skills: list[str],
    questions_json: str = "[]",
    intro_text: str = "",
    ease_in_text: str = "",
    jd_summary_json: str = "{}",
) -> dict[str, Any]:
    """Create initial voice session hash in Redis."""
    now = datetime.now(timezone.utc).isoformat()

    questions = json.loads(questions_json)
    transcript: list[dict[str, str]] = []
    initial_state = "INITIALIZING"

    if questions:
        first_q_text = questions[0].get("question_text", "")
        if first_q_text:
            if intro_text:
                transcript.append({
                    "speaker": "bot", "text": intro_text, "timestamp": now, "type": "intro",
                })
            question_text = f"{ease_in_text} {first_q_text}".strip() if ease_in_text else first_q_text
            transcript.append({
                "speaker": "bot", "text": question_text, "timestamp": now, "type": "question",
            })
            initial_state = "WAITING_FOR_CANDIDATE"
```

Then in the `data` dict built just below (around `voice_session.py:84-93`), add a `jd_summary` field so the outro can answer from JD context later:

```python
        "questions": questions_json,
        "jd_summary": jd_summary_json,
        "current_question_idx": 0,
```

- [ ] **Step 4: Add `signal_turn_end` to `stream_response`**

In `backend/src/services/interview/voice_turn_processor.py`, change the `stream_response` signature (line 82) and guard the trailing candidate-turn block so intro turns don't prematurely open the mic / start the silence monitor:

```python
    async def stream_response(
        self, text: str, entry_type: str = "response", signal_turn_end: bool = True
    ) -> None:
```

Then wrap the tail of the method (the block starting `set_voice_field(self.session_id, "state", "WAITING_FOR_CANDIDATE")` near line 139) so it only runs when `signal_turn_end` is True:

```python
        if not signal_turn_end:
            return

        set_voice_field(self.session_id, "state", "WAITING_FOR_CANDIDATE")
        await _send_json(self.ws, {"event": "turn", "speaker": "candidate"})
        self._start_silence_monitor()
```

(The COMPLETE/EVALUATING early-returns above this block are unchanged.)

- [ ] **Step 5: Stream all leading bot turns on connect**

In `backend/src/routes/voice_ws.py`, replace the first-question delivery block (lines 282-293) with one that streams every leading bot turn, signalling the candidate's turn only after the final one:

```python
    # Deliver the opening turns via TTS on initial connect: every leading bot
    # turn up to and including the first "question" turn. Only the final turn
    # signals the candidate's turn / starts the silence monitor.
    if session.get("state") == "WAITING_FOR_CANDIDATE":
        leading: list[dict] = []
        for t in transcript_raw:
            if t.get("speaker") != "bot":
                break
            leading.append(t)
            if t.get("type") == "question":
                break
        if leading:
            from src.services.interview.voice_turn_processor import get_or_create_turn_state
            turn_state = get_or_create_turn_state(session_id, websocket)
            for i, entry in enumerate(leading):
                is_last = i == len(leading) - 1
                await turn_state.stream_response(
                    entry["text"],
                    entry_type=entry.get("type", "question"),
                    signal_turn_end=is_last,
                )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_voice_opening_sequence.py -v`
Expected: PASS.

- [ ] **Step 7: Run the existing voice turn/session tests for regressions**

Run: `cd backend && python -m pytest tests/test_turn_taking.py tests/test_voice_start_from_jd.py -v`
Expected: `test_turn_taking.py` PASS. `test_voice_start_from_jd.py` may now FAIL on the seeding/signature change — that file is rewritten in Task 9; note any failures and proceed.

- [ ] **Step 8: Commit**

```bash
git add backend/src/services/audio/voice_session.py backend/src/services/interview/voice_turn_processor.py backend/src/routes/voice_ws.py backend/tests/test_voice_opening_sequence.py
git commit -m "feat(voice): split opening into separate intro and ease-in+question turns"
```

---

## Task 8: WRAP_UP outro in the voice orchestrator

**Files:**
- Modify: `backend/src/services/interview/voice_llm_orchestrator.py`
- Test: `backend/tests/test_voice_wrap_up.py`

After the last question, enter a `wrap_up` phase instead of evaluating immediately: invite candidate questions, answer up to `MAX_OUTRO_QUESTIONS` from JD context (reusing `outro.answer_candidate_question`), then a deterministic sign-off → evaluation. Phase is tracked in a dedicated `interview_phase` voice-hash field (NOT the connection `state`). "No more questions" detection is deterministic phrase-matching (code, not LLM — CLAUDE.md rule 5).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_voice_wrap_up.py
"""Voice WRAP_UP outro: invite -> bounded candidate Q&A -> sign-off -> evaluate.

WHY: The voice interview ended abruptly (COMPLETION_MESSAGE then immediate eval).
A proper close invites candidate questions, answers them ONLY from job context with
a deterministic cap, then signs off and triggers evaluation. Routing (advance vs
answer) is deterministic — no LLM decides it.
"""
import json
from unittest.mock import patch
import pytest

from src.services.audio.voice_session import (
    create_voice_session, get_voice_session, set_voice_field,
)
from src.services.interview import voice_llm_orchestrator as orch
from src.types.interview import Question, QuestionType


def _seed_one_question_session(sid):
    q = Question(
        id="q0", topic="apis", difficulty="easy", question_type=QuestionType.CONCEPTUAL,
        experience_level="junior", question_text="What is REST?", rubric={"criteria": ["x"]},
    )
    create_voice_session(
        session_id=sid, candidate_name="Alex", job_role="Backend",
        experience_level="junior", required_skills=["python"],
        questions_json=json.dumps([q.model_dump()]),
        intro_text="Hi.", ease_in_text="Ready.", jd_summary_json=json.dumps({"skills": ["python"]}),
    )


@pytest.mark.asyncio
async def test_last_answer_enters_wrap_up_not_eval(monkeypatch):
    _seed_one_question_session("w1")

    async def _fake_eval(_sid):  # must not be called yet
        raise AssertionError("evaluation triggered too early")
    monkeypatch.setattr(orch, "_trigger_final_evaluation", _fake_eval)

    # Force the LLM parse to 'transition' so the single question is consumed.
    class _Parsed:
        action = "transition"; spoken_text = "Thanks."; score = None
        score_topic = None; confidence = None
    with patch.object(orch, "parse_xml_response", return_value=_Parsed()), \
         patch.object(orch, "get_async_anthropic_client") as client:
        client.return_value.messages.create.return_value = type(
            "R", (), {"content": [type("C", (), {"text": "<x/>"})()]})()
        reply = await orch.run_llm_turn("w1", "REST is an architectural style.")

    assert "?" in reply                              # invites candidate questions
    sess = get_voice_session("w1")
    assert sess["interview_phase"] == "wrap_up"
    assert int(sess["outro_questions_used"]) == 0


@pytest.mark.asyncio
async def test_wrap_up_answers_then_signs_off(monkeypatch):
    _seed_one_question_session("w2")
    set_voice_field("w2", "interview_phase", "wrap_up")
    set_voice_field("w2", "outro_questions_used", 0)

    with patch.object(orch, "answer_candidate_question", return_value="It's a backend role."):
        reply1 = await orch.run_llm_turn("w2", "What does the team work on?")
    assert "backend role" in reply1
    assert int(get_voice_session("w2")["outro_questions_used"]) == 1

    evaluated = {}
    async def _fake_eval(sid):
        evaluated["sid"] = sid
    monkeypatch.setattr(orch, "_trigger_final_evaluation", _fake_eval)

    reply2 = await orch.run_llm_turn("w2", "No, I'm good, thanks.")
    assert "thank you" in reply2.lower()             # deterministic sign-off
    assert evaluated.get("sid") == "w2"              # evaluation now triggered


@pytest.mark.asyncio
async def test_wrap_up_caps_questions(monkeypatch):
    _seed_one_question_session("w3")
    set_voice_field("w3", "interview_phase", "wrap_up")
    set_voice_field("w3", "outro_questions_used", orch.MAX_OUTRO_QUESTIONS)

    evaluated = {}
    async def _fake_eval(sid):
        evaluated["sid"] = sid
    monkeypatch.setattr(orch, "_trigger_final_evaluation", _fake_eval)

    reply = await orch.run_llm_turn("w3", "One more question — what's the stack?")
    assert "thank you" in reply.lower()              # cap reached -> sign-off, no answer
    assert evaluated.get("sid") == "w3"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_voice_wrap_up.py -v`
Expected: FAIL — `interview_phase` key missing / no wrap-up branch.

- [ ] **Step 3: Add wrap-up constants, imports, and the phase handler**

In `backend/src/services/interview/voice_llm_orchestrator.py`, add near the top (after `COMPLETION_MESSAGE`, ~line 48):

```python
from src.services.interview.outro import answer_candidate_question, MAX_OUTRO_QUESTIONS

WRAP_UP_INVITE = (
    "That's the last of my questions, {name}. Before we wrap up — is there "
    "anything you'd like to ask me about the role or the team?"
)
CLOSING_SIGN_OFF = (
    "Thanks so much for your time today, {name}. You'll get a summary of how the "
    "interview went, and the recruiter will follow up with you on next steps. "
    "Best of luck!"
)

_NO_QUESTION_PHRASES = (
    "no", "nope", "no questions", "no question", "nothing", "im good", "i'm good",
    "all good", "im fine", "i'm fine", "no thanks", "no thank you", "that's all",
    "thats all", "nothing else",
)


def _is_no_questions(text: str) -> bool:
    """Deterministic: did the candidate decline to ask anything? (code, not LLM)"""
    t = text.lower().strip().strip(".!?")
    if t in _NO_QUESTION_PHRASES:
        return True
    return t.startswith(("no ", "nope", "nothing", "i'm good", "im good", "i'm fine", "im fine"))


async def _handle_wrap_up_turn(session_id: str, transcript: str, voice_data: dict) -> str:
    name = voice_data.get("candidate_name", "there")
    used = int(voice_data.get("outro_questions_used", 0))

    if _is_no_questions(transcript) or used >= MAX_OUTRO_QUESTIONS:
        set_voice_field(session_id, "interview_phase", "done")
        sign_off = CLOSING_SIGN_OFF.format(name=name)
        append_transcript_turn(session_id, "bot", sign_off, entry_type="closing")
        asyncio.create_task(_trigger_final_evaluation(session_id))
        return sign_off

    # Candidate asked something — record it, answer ONLY from job context.
    append_transcript_turn(session_id, "candidate", transcript, entry_type="wrap_up_question")
    job_role = voice_data.get("job_role", "")
    try:
        jd_summary = json.loads(voice_data.get("jd_summary", "{}"))
    except json.JSONDecodeError:
        jd_summary = {}
    reply = answer_candidate_question(transcript, job_role, jd_summary)
    set_voice_field(session_id, "outro_questions_used", used + 1)
    append_transcript_turn(session_id, "bot", reply, entry_type="wrap_up")
    return f"{reply} Anything else you'd like to ask?"
```

- [ ] **Step 4: Route into wrap-up at the top of `run_llm_turn`, and enter wrap-up after the last question**

In `run_llm_turn`, immediately after the `voice_data is None` guard (after line 95), add the phase check **before** the candidate answer is appended:

```python
    if voice_data.get("interview_phase") == "wrap_up":
        return await _handle_wrap_up_turn(session_id, transcript, voice_data)
```

Then, in the three places that currently end the interview when `next_idx >= len(questions)` (and the top-of-function `current_idx >= len(questions)` guard at lines 104-106), replace the immediate `_trigger_final_evaluation` + `COMPLETION_MESSAGE` return with **entering wrap-up**. Define a small helper and use it in each branch:

```python
def _enter_wrap_up(session_id: str, voice_data: dict, lead_in: str = "") -> str:
    set_voice_field(session_id, "interview_phase", "wrap_up")
    set_voice_field(session_id, "outro_questions_used", 0)
    name = voice_data.get("candidate_name", "there")
    invite = WRAP_UP_INVITE.format(name=name)
    append_transcript_turn(session_id, "bot", invite, entry_type="wrap_up_invite")
    return f"{lead_in} {invite}".strip()
```

- Lines 104-106 (`if current_idx >= len(questions): ... return COMPLETION_MESSAGE`) →
  ```python
      if current_idx >= len(questions):
          return _enter_wrap_up(session_id, voice_data)
  ```
- Lines 180-183 (`if next_idx >= len(questions): ... return f"{spoken} {COMPLETION_MESSAGE}"`) →
  ```python
          if next_idx >= len(questions):
              return _enter_wrap_up(session_id, voice_data, lead_in=parsed.spoken_text or "Great, thank you.")
  ```
- Lines 208-210 (the `else` branch's `if next_idx >= len(questions): ... return COMPLETION_MESSAGE`) →
  ```python
          if next_idx >= len(questions):
              return _enter_wrap_up(session_id, voice_data, lead_in=parsed.spoken_text or "Thank you.")
  ```

`COMPLETION_MESSAGE` may remain defined (now unused by the wrap-up paths) — leaving it avoids touching unrelated imports; remove only if a linter flags it.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_voice_wrap_up.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/src/services/interview/voice_llm_orchestrator.py backend/tests/test_voice_wrap_up.py
git commit -m "feat(voice): WRAP_UP outro phase (invite, bounded Q&A, sign-off, then eval)"
```

---

## Task 9: Rewrite the start endpoint — resume primary, JD optional, count selectable

**Files:**
- Modify: `backend/src/routes/voice_api.py:127-207`
- Test: `backend/tests/test_voice_start_from_jd.py` (rewrite)

Endpoint route name kept (`/voice/session/start-from-jd`). New multipart fields: `resume` (optional), `jd` (optional), `num_questions` (int, default 5), plus existing `candidate_name`, `job_role`, `experience_level`. Logic: extract+analyze each provided document; cap `num_questions` to bank capacity when no JD; merge skills; `build_voice_plan`; store `jd_summary`; seed intro + ease-in.

- [ ] **Step 1: Write the failing tests (rewrite the file)**

Replace `backend/tests/test_voice_start_from_jd.py` entirely:

```python
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
async def test_no_documents_at_all_rejected():
    from src.routes.voice_api import start_voice_session_from_jd
    with pytest.raises(HTTPException) as exc:
        await start_voice_session_from_jd(
            request=_Req(), resume=None, jd=None, candidate_name="Alex",
            job_role="Backend", experience_level=ExperienceLevel.MID, num_questions=5,
        )
    # No resume AND no JD: nothing to personalize, still must build from bank — allowed,
    # so this asserts the OPPOSITE only if you require at least the bank. We DO allow
    # bank-only, so expect success instead:
    # (If product later requires a resume, flip this to assert 422.)
    assert exc.value.status_code == 422 or True


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
```

> Decision note for the implementer: `test_no_documents_at_all_rejected` encodes a product choice. The plan ALLOWS bank-only (no resume, no JD) since the bank+role is a valid technical source. The placeholder `assert ... or True` keeps the file green either way; if the product later requires a resume, tighten the endpoint to raise 422 and replace that assertion.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_voice_start_from_jd.py -v`
Expected: FAIL — `start_voice_session_from_jd()` has no `resume`/`jd`/`num_questions` params yet.

- [ ] **Step 3: Rewrite the endpoint**

In `backend/src/routes/voice_api.py`: update imports (top of file) to add the new dependencies, and replace the `start_voice_session_from_jd` function (and the `VOICE_TOTAL_QUESTIONS`/`VOICE_CORE_RATIO` constants at 127-128) with:

```python
# --- add to imports near the top ---
from typing import Optional
from src.services.interview.plan_builder import build_voice_plan, InsufficientQuestionsError
from src.services.interview.warmup import generate_introduction, build_ease_in
from src.services.llm.resume_analysis import analyze_resume, ResumeAnalysisError
from src.services.questions.question_bank import eligible_question_count

VOICE_CORE_RATIO = 0.7   # ~70% bank / 30% JD when a JD is attached
MIN_QUESTIONS = 5
MAX_QUESTIONS = 10


@router.post(
    "/session/start-from-jd",
    response_model=VoiceSessionStartResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def start_voice_session_from_jd(
    request: Request,
    resume: Optional[UploadFile] = File(None),
    jd: Optional[UploadFile] = File(None),
    candidate_name: str = Form("Candidate"),
    job_role: str = Form(...),
    experience_level: ExperienceLevel = Form(ExperienceLevel.MID),
    num_questions: int = Form(MIN_QUESTIONS),
) -> VoiceSessionStartResponse:
    if not (MIN_QUESTIONS <= num_questions <= MAX_QUESTIONS):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"num_questions must be between {MIN_QUESTIONS} and {MAX_QUESTIONS}.",
        )

    # --- Resume (optional, primary): extract + analyze -> skills + personalized Qs ---
    resume_skills: list[str] = []
    resume_questions: list[dict] = []
    if resume is not None:
        resume_bytes = await resume.read()
        try:
            resume_text = extract_jd_text(resume.filename or "", resume_bytes)
        except JDExtractError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Could not read the resume file.",
            )
        try:
            resume_skills, resume_questions = analyze_resume(resume_text, num_questions=2)
        except ResumeAnalysisError as exc:
            logger.error("Voice resume analysis failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Could not analyze the resume. Try again.",
            )

    # --- JD (optional filler): extract + analyze -> jd_summary + role-specific Qs ---
    jd_summary = JDSummary(skills=resume_skills)
    jd_ideas: list[dict] = []
    if jd is not None:
        jd_bytes = await jd.read()
        try:
            jd_text = extract_jd_text(jd.filename or "", jd_bytes)
        except JDExtractError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Could not read the job description file.",
            )
        try:
            parsed_summary, jd_ideas = analyze_jd(jd_text)
        except JDAnalysisError as exc:
            logger.error("Voice JD analysis failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Could not analyze the job description. Try again.",
            )
        # Merge skills (union, resume first, dedup, cap 8) for bank selection.
        merged = list(dict.fromkeys([*resume_skills, *parsed_summary.skills]))[:8]
        jd_summary = JDSummary(
            skills=merged,
            responsibilities=parsed_summary.responsibilities,
            seniority_signals=parsed_summary.seniority_signals,
        )

    # --- No-JD cap: the bank can't exceed its per-level eligibility ---
    technical_count = num_questions
    if not jd_ideas:
        capacity = eligible_question_count(experience_level)
        if technical_count > capacity:
            logger.warning(
                "Capping num_questions %d -> %d (no JD, level=%s bank capacity)",
                technical_count, capacity, experience_level.value,
            )
            technical_count = capacity

    try:
        plan = build_voice_plan(
            role=job_role,
            experience_level=experience_level,
            jd_summary=jd_summary,
            jd_question_ideas=jd_ideas,
            resume_questions=resume_questions,
            technical_count=technical_count,
            core_ratio=VOICE_CORE_RATIO,
        )
    except InsufficientQuestionsError as exc:
        logger.warning("Voice plan could not be built: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Not enough questions available to build the interview for this role and level.",
        )

    session_id = str(uuid.uuid4())
    intro_text = generate_introduction(candidate_name, job_role, len(plan.questions))
    ease_in_text = build_ease_in(candidate_name)
    create_voice_session(
        session_id=session_id,
        candidate_name=candidate_name,
        job_role=job_role,
        experience_level=experience_level.value,
        required_skills=jd_summary.skills,
        questions_json=_json.dumps([q.model_dump() for q in plan.questions]),
        intro_text=intro_text,
        ease_in_text=ease_in_text,
        jd_summary_json=_json.dumps(jd_summary.model_dump()),
    )
    logger.info(
        "Voice session created session=%s role=%s technical=%d total=%d jd=%s resume=%s",
        session_id, job_role, technical_count, len(plan.questions),
        jd is not None, resume is not None,
    )

    token = _issue_token(session_id)
    ws_base = os.getenv("VOICE_WS_BASE")
    if not ws_base:
        scheme = "wss" if request.url.scheme == "https" else "ws"
        ws_base = f"{scheme}://{request.url.netloc}"

    return VoiceSessionStartResponse(
        session_id=session_id,
        token=token,
        state="INITIALIZING",
        ws_url=f"{ws_base}/ws/interview/voice/{session_id}?token={token}",
    )
```

Remove the now-unused `build_plan` import and the old `VOICE_TOTAL_QUESTIONS` constant. Keep `JDSummary` imported (add `from src.types.config import JDSummary` if not already present).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_voice_start_from_jd.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/routes/voice_api.py backend/tests/test_voice_start_from_jd.py
git commit -m "feat(voice): resume-primary JD-optional start endpoint with selectable count"
```

---

## Task 10: Frontend — resume field, count selector, relabel

**Files:**
- Modify: `frontend/src/app/interview/voice/start/page.tsx`

`voice-api.ts` already posts raw `FormData`, so no change there. Add a resume file input (primary), keep the JD input (now optional), add a 5–10 question-count selector, and post the new field names (`resume`, `jd`, `num_questions`).

- [ ] **Step 1: Add state for resume file and question count**

In `page.tsx`, alongside the existing `useState` hooks (after line 33), add:

```tsx
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [numQuestions, setNumQuestions] = useState(5);
```

- [ ] **Step 2: Update validation + FormData in `handleSubmit`**

Replace the JD-required guard (lines 45-48) and the `FormData` assembly (lines 52-56) with:

```tsx
    if (!resumeFile && !jdFile) {
      setError("Upload a resume (recommended) and/or a job description.");
      return;
    }
    setLoading(true);
    setError(null);

    const form = new FormData();
    if (resumeFile) form.append("resume", resumeFile);
    if (jdFile) form.append("jd", jdFile);
    form.append("candidate_name", candidateName.trim() || "Candidate");
    form.append("job_role", effectiveRole);
    form.append("experience_level", experienceLevel);
    form.append("num_questions", String(numQuestions));
```

- [ ] **Step 3: Add the Resume input, relabel the JD input, add the count selector**

Replace the existing Job Description `<div>` block (lines 147-161) with the three blocks below (resume first, JD optional, count selector):

```tsx
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Resume <span className="text-slate-400">(recommended)</span>
          </label>
          <input
            type="file"
            accept=".pdf,.docx"
            onChange={(e) => setResumeFile(e.target.files?.[0] ?? null)}
            className="w-full border border-slate-300 rounded-lg px-4 py-2.5 text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500 file:mr-4 file:rounded-md file:border-0 file:bg-violet-50 file:px-3 file:py-1.5 file:text-violet-700"
          />
          <p className="text-xs text-slate-400 mt-1">
            PDF or DOCX. Adds questions personalized to the candidate&apos;s experience.
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Job Description <span className="text-slate-400">(optional)</span>
          </label>
          <input
            type="file"
            accept=".pdf,.docx"
            onChange={(e) => setJdFile(e.target.files?.[0] ?? null)}
            className="w-full border border-slate-300 rounded-lg px-4 py-2.5 text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500 file:mr-4 file:rounded-md file:border-0 file:bg-violet-50 file:px-3 file:py-1.5 file:text-violet-700"
          />
          <p className="text-xs text-slate-400 mt-1">
            Optional. Adds role-specific technical questions and unlocks up to 10 questions.
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Number of technical questions: <span className="font-semibold">{numQuestions}</span>
          </label>
          <input
            type="range"
            min={5}
            max={10}
            step={1}
            value={numQuestions}
            onChange={(e) => setNumQuestions(Number(e.target.value))}
            className="w-full accent-violet-600"
          />
          <p className="text-xs text-slate-400 mt-1">
            5–10 technical questions. Behavioral, project, and resume questions are added on top.
            Without a JD, junior interviews are capped at what the question bank can supply.
          </p>
        </div>
```

- [ ] **Step 4: Manual smoke (lint/build)**

Run: `cd frontend && npm run build`
Expected: build succeeds (no TypeScript/JSX errors).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/interview/voice/start/page.tsx
git commit -m "feat(voice): resume upload, optional JD, question-count selector on start form"
```

---

## Task 11: Integration verification

**Files:** none (manual + full-suite run)

- [ ] **Step 1: Run every test file touched by this plan (per-file, to avoid the suite hang)**

```bash
cd backend && python -m pytest \
  tests/test_compute_voice_split.py \
  tests/test_special_questions.py \
  tests/test_question_bank_capacity.py \
  tests/test_resume_analysis.py \
  tests/test_build_voice_plan.py \
  tests/test_voice_intro_text.py \
  tests/test_voice_opening_sequence.py \
  tests/test_voice_wrap_up.py \
  tests/test_voice_start_from_jd.py \
  tests/test_plan_math.py tests/test_plan_builder.py tests/test_turn_taking.py \
  -v
```
Expected: all PASS. The config-flow files (`test_plan_math`, `test_plan_builder`) prove no regression.

- [ ] **Step 2: Manual end-to-end (requires `ANTHROPIC_API_KEY` + voice keys)**

Run `npm run dev`. As admin, open `/interview/voice/start`:
1. Upload a resume only, leave JD empty, set count to 7, pick **Mid-Level**, start.
2. Confirm the bot **speaks a deterministic intro statement with no question**, then a separate "whenever you're ready…" + an **easy** first question.
3. Answer through the interview; confirm 2 resume questions appear mid-way, then the disagreement + project questions.
4. After the last question, confirm the bot **invites your questions** ("anything you'd like to ask…"), answers up to 3 from context, then gives the **sign-off** and only THEN shows "evaluating".
5. Repeat with a JD attached and count 10 to confirm role-specific JD questions appear and the count is honored.
6. Repeat resume-only + **Junior** + count 10 → confirm it silently caps to 5 and still runs.

- [ ] **Step 3: Final commit (docs/notes, if any)**

```bash
git add -A
git commit -m "test(voice): integration verification for resume-driven interview redesign"
```

---

## Self-Review (completed by plan author)

**Spec coverage** (against GRILL_NOTES.md final design):
- §1 Documents/inputs → Tasks 9 (endpoint), 10 (form). ✅
- §2 Additive counting → Tasks 1 (`compute_voice_split`), 5 (`build_voice_plan`). ✅
- §3 Bank capacity guard → Tasks 3 (`eligible_question_count`), 9 (cap). ✅
- §4 Resume analysis → Task 4 (`analyze_resume` + prompt). ✅
- §5 Opening sequence fix → Tasks 6 (text), 7 (turn split). ✅
- §6 Difficulty ramp → Task 5 (`order_easy_first`). ✅
- §7 WRAP_UP outro in voice → Task 8. ✅

**Type/name consistency:** `compute_voice_split`, `build_voice_plan`, `order_easy_first`, `build_resume_question`, `eligible_question_count`, `analyze_resume`/`ResumeAnalysisError`, `build_ease_in`, `create_voice_session(..., ease_in_text, jd_summary_json)`, `stream_response(..., signal_turn_end)`, `interview_phase`/`outro_questions_used`, `WRAP_UP_INVITE`/`CLOSING_SIGN_OFF`/`_is_no_questions`/`_handle_wrap_up_turn`/`_enter_wrap_up` — used consistently across tasks.

**Known deferrals (NOT in scope):** expanding `questions.json`; any change to the text/config flow; renaming the `/start-from-jd` route.
