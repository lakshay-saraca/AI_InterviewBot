# Admin Features & Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add industry-standard navigation, admin/candidate roles, interview history, and post-interview analysis with confidence metrics.

**Architecture:** Minimal role-based auth (React Context + localStorage, backend API key), top navbar with role-aware links, two new admin pages (History + Analysis) backed by existing PostgreSQL reports table and new admin API endpoints. Text-mode interviews gain PG persistence (currently Redis-only) and confidence tracking to match voice-mode parity.

**Tech Stack:** Next.js 14 (App Router), Tailwind CSS, FastAPI, Redis, PostgreSQL (asyncpg), existing Pydantic models.

---

## Codebase Analysis

### Current App Structure

```
D:\AIBOT/
├── backend/                  # FastAPI (Python 3.11)
│   ├── main.py               # App + router registration
│   ├── src/
│   │   ├── routes/           # interview.py, voice_api.py, voice_ws.py, health.py
│   │   ├── services/         # interview/, llm/, audio/, questions/
│   │   ├── models/           # interview_report.py (PG persistence)
│   │   ├── types/            # api.py, interview.py (Pydantic schemas)
│   │   ├── lib/              # anthropic_client.py, redis_client.py, settings.py
│   │   └── prompts/          # system_prompt.txt, evaluation_prompt.txt, voice_evaluation_prompt.txt
│   ├── data/questions.json   # 16 interview questions
│   ├── migrations/           # 001_interview_reports.sql
│   └── tests/                # 2 test files (pytest)
├── frontend/                 # Next.js 14, App Router, Tailwind
│   └── src/
│       ├── app/              # Routes: /, /interview/*, /report/*
│       ├── components/       # ReportCard, ScoreBadge, TranscriptTimeline, etc.
│       ├── services/         # api.ts, voice-api.ts
│       ├── types/            # interview.ts, voice-interview.ts
│       └── lib/              # websocket.ts, voice-capture.ts
└── docker-compose.yml        # Redis 7 + PostgreSQL 16
```

### Existing Auth / Role / Session Behavior

- **No authentication system exists.** No login, no user table, no roles.
- **Session management**: Client-side `sessionStorage` keyed by `interview_session_{sessionId}`. Backend sessions live in Redis with 4hr TTL.
- **Voice-only JWT**: Voice WebSocket uses HS256 JWT (issued at session start, validated on WS upgrade). Has `session_id` claim, no user/role concept.
- **No route protection**: All pages accessible to anyone with the URL.

### Existing Backend Code for Interviews, Transcripts, Analysis, Scoring, Confidence

| What | Where | Status |
|------|-------|--------|
| Per-answer scoring (0-10) | `llm_service.evaluate_answer()` → XML → `response_parser.parse_xml_response()` | Working, both modes |
| Per-answer confidence (0-1) | `response_parser.py` extracts from XML, but `llm_service.py` **discards it** | Voice: captured in orchestrator. Text: **lost** |
| Final evaluation | `llm_service.generate_final_evaluation()` (text), `voice_evaluation.run_voice_evaluation()` (voice) | Working, both modes |
| Composite per-topic confidence | `voice_evaluation._compute_per_topic_confidence()` — 3-signal composite (LLM 0.55 + follow-up 0.30 + STT 0.15) | Voice only |
| InterviewReport model | `models/interview_report.py` — InterviewMetrics, InterviewAnalysis, CategoryScore | Used by voice, reusable for text |
| PG persistence | `save_report()` / `get_report_by_session()` in `interview_report.py` | Voice saves to PG. **Text does NOT** |
| Report endpoint | `GET /api/v1/interview/report/{session_id}` — checks Redis text → Redis voice → PG | Working |
| Transcript | `SessionState.transcript` (text), `voice_session:transcript` (voice) — both are `list[dict]` | Working |
| Question results | `SessionState.question_results` — has Q, answer, score, reasoning per question | Text only |
| Category scores | `InterviewAnalysis` — communication_clarity, technical_depth, confidence_consistency, relevance | Voice only (from LLM) |

### Key Gaps to Fill

1. **Text interviews are not persisted to PostgreSQL** — lost after Redis 4hr TTL
2. **Text-mode confidence is discarded** — `response_parser` extracts it, `llm_service` drops it
3. **No list endpoint** — can only fetch by session_id, no way to list all interviews
4. **No admin auth** — no role concept, no route protection
5. **No navigation** — just a brand title link in layout.tsx
6. **No interview_type column** — can't distinguish text vs voice in PG

---

## Proposed Scoring & Confidence Model

### Per-Answer Metrics (shown on analysis page per Q&A pair)
| Metric | Source | Range | Text Mode | Voice Mode |
|--------|--------|-------|-----------|------------|
| **Answer Score** | LLM evaluation | 0-10 | From `evaluate_answer()` | From `voice_llm_orchestrator` |
| **Score Reasoning** | LLM evaluation | text | Already in QuestionResult | Already in per_question |
| **Evaluation Confidence** | LLM self-reported | 0-1 | **Currently discarded — will capture** | Already in `llm_confidence_by_topic` |

### Summary Confidence Dashboard (3 metrics, shown at top of analysis page)
| Metric | Description | Text Mode | Voice Mode |
|--------|-------------|-----------|------------|
| **Transcription Confidence** | How reliable was the input text? | Always 1.0 (typed input is exact) | Average Deepgram STT confidence across final transcripts |
| **Q&A Extraction Confidence** | How well were Q&A pairs identified? | Always 1.0 (structured request-response by design) | `1.0 - (follow_ups / 2*topics)` — more follow-ups = harder to extract clean pairs |
| **Answer Evaluation Confidence** | How confident is the AI in its scoring? | Average LLM confidence across questions | Average LLM confidence across questions |

### Design Principles
- **No fake numbers.** Text-mode transcription confidence is 1.0 because it IS 1.0 — the user typed the answer.
- **Reuse existing signals.** Voice mode already computes all three components in `_compute_per_topic_confidence()`.
- **Clearly labeled.** UI will show what each metric means and note when values are trivially perfect (text mode).

---

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `backend/migrations/002_add_interview_type.sql` | Add interview_type column to PG |
| `backend/src/routes/admin.py` | Admin-only API endpoints (list + detail) |
| `backend/src/types/admin.py` | Admin API request/response schemas |
| `backend/tests/test_admin_routes.py` | Tests for admin endpoints |
| `frontend/src/contexts/AuthContext.tsx` | Auth state provider (role, name, login/logout) |
| `frontend/src/components/Navbar.tsx` | Responsive top navigation bar |
| `frontend/src/components/AdminGuard.tsx` | Route protection wrapper |
| `frontend/src/components/ConfidenceMetrics.tsx` | 3-metric confidence dashboard |
| `frontend/src/app/login/page.tsx` | Login / role selection page |
| `frontend/src/app/admin/history/page.tsx` | Interview history table |
| `frontend/src/app/admin/analysis/[sessionId]/page.tsx` | Post-interview analysis page |
| `frontend/src/services/admin-api.ts` | Admin API client functions |
| `frontend/src/types/admin.ts` | Admin TypeScript types |

### Modified Files

| File | Change |
|------|--------|
| `backend/main.py` | Register admin router |
| `backend/src/lib/settings.py` | Add `admin_api_key` setting |
| `backend/src/services/llm/llm_service.py` | Capture confidence in `EvaluationResult` |
| `backend/src/types/interview.py` | Add `confidence` to `QuestionResult` |
| `backend/src/services/interview/turn_manager.py` | Pass confidence to QuestionResult |
| `backend/src/routes/interview.py` | Save text-mode report to PG after evaluation |
| `backend/src/models/interview_report.py` | Add `interview_type` to model + SQL, add confidence fields to InterviewMetrics |
| `backend/src/services/interview/voice_evaluation.py` | Populate new confidence fields in metrics |
| `backend/.env.example` | Add `ADMIN_API_KEY` |
| `frontend/src/app/layout.tsx` | Wrap with AuthProvider, replace inline nav with Navbar |
| `frontend/src/app/page.tsx` | Update CTA to route based on role |

---

## Tasks

### Task 1: Database Migration — Add interview_type Column

**Files:**
- Create: `backend/migrations/002_add_interview_type.sql`

- [ ] **Step 1: Create migration file**

```sql
-- Add interview_type to distinguish text vs voice interviews

ALTER TABLE interview_reports
    ADD COLUMN IF NOT EXISTS interview_type VARCHAR(16) NOT NULL DEFAULT 'text';

CREATE INDEX IF NOT EXISTS idx_interview_reports_type ON interview_reports(interview_type);
```

- [ ] **Step 2: Run migration against local PostgreSQL**

Run: `cd backend && psql -h localhost -U postgres -d interview_db -f migrations/002_add_interview_type.sql`
Expected: `ALTER TABLE` and `CREATE INDEX` with no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/002_add_interview_type.sql
git commit -m "feat: add interview_type column to interview_reports"
```

---

### Task 2: Backend — Admin Auth Dependency & Settings

**Files:**
- Modify: `backend/src/lib/settings.py:6-19` (add field)
- Modify: `backend/.env.example` (add key)
- These will be used by the admin router in Task 5.

- [ ] **Step 1: Add admin_api_key to Settings**

In `backend/src/lib/settings.py`, add a new field to the `Settings` class:

```python
class Settings(BaseSettings):
    anthropic_api_key: str = ""
    deepgram_api_key: str = ""
    elevenlabs_api_key: str = ""
    database_url: str = "postgresql://postgres:dev@localhost:5432/interview_db"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me-in-production"
    admin_api_key: str = "change-me-admin-key"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"
    s3_bucket_name: str = "interview-audio"
    environment: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"
```

- [ ] **Step 2: Add ADMIN_API_KEY to .env.example**

Append to `backend/.env.example`:

```
ADMIN_API_KEY=change-me-admin-key
```

- [ ] **Step 3: Add the same to root .env.example**

Append to `.env.example`:

```
ADMIN_API_KEY=change-me-admin-key
```

- [ ] **Step 4: Commit**

```bash
git add backend/src/lib/settings.py backend/.env.example .env.example
git commit -m "feat: add admin_api_key to settings"
```

---

### Task 3: Backend — Capture Confidence in Text-Mode Evaluation

**Files:**
- Modify: `backend/src/services/llm/llm_service.py:17-24` (add confidence field)
- Modify: `backend/src/services/llm/llm_service.py:26-59` (capture confidence)
- Modify: `backend/src/types/interview.py` (add confidence to QuestionResult)
- Modify: `backend/src/services/interview/turn_manager.py` (pass confidence)
- Test: `backend/tests/test_confidence_capture.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_confidence_capture.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from src.services.llm.llm_service import EvaluationResult


def test_evaluation_result_has_confidence_field():
    result = EvaluationResult(
        spoken_text="Good answer.",
        score=7.5,
        reasoning="Solid understanding.",
        confidence=0.85,
    )
    assert result.confidence == 0.85


def test_evaluation_result_confidence_defaults_to_none():
    result = EvaluationResult(
        spoken_text="Good answer.",
        score=7.5,
        reasoning="Solid understanding.",
    )
    assert result.confidence is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_confidence_capture.py -v`
Expected: FAIL — `EvaluationResult.__init__() got an unexpected keyword argument 'confidence'`

- [ ] **Step 3: Add confidence to EvaluationResult**

In `backend/src/services/llm/llm_service.py`, modify the dataclass:

```python
@dataclass
class EvaluationResult:
    spoken_text: str
    score: Optional[float]
    reasoning: Optional[str]
    flags: list[str] = field(default_factory=list)
    internal_notes: str = ""
    confidence: Optional[float] = None
```

- [ ] **Step 4: Capture confidence from parsed response**

In `backend/src/services/llm/llm_service.py`, in the `evaluate_answer` function, update the return statement inside the try block (around line 45):

```python
        return EvaluationResult(
            spoken_text=parsed.spoken_text or _fallback_acknowledgement(parsed.score),
            score=parsed.score,
            reasoning=parsed.reasoning,
            flags=parsed.flags,
            internal_notes=parsed.internal_notes,
            confidence=parsed.confidence,
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_confidence_capture.py -v`
Expected: PASS

- [ ] **Step 6: Add confidence to QuestionResult**

In `backend/src/types/interview.py`, find the `QuestionResult` class and add the field:

```python
class QuestionResult(BaseModel):
    question_id: str
    question_text: str
    topic: str
    answer_text: str
    score: Optional[float] = None
    score_reasoning: Optional[str] = None
    follow_up_count: int = 0
    time_spent_seconds: float = 0.0
    confidence: Optional[float] = None
```

- [ ] **Step 7: Pass confidence through turn_manager**

In `backend/src/services/interview/turn_manager.py`, find where `QuestionResult` is constructed (inside `process_answer`). Add the confidence field. The exact location is where `session.question_results.append(...)` is called. Update the QuestionResult construction:

```python
    qr = QuestionResult(
        question_id=question.id,
        question_text=question.question_text,
        topic=question.topic,
        answer_text=answer_text,
        score=result.score,
        score_reasoning=result.reasoning,
        confidence=result.confidence,
    )
```

Note: Read `turn_manager.py` first to find the exact variable names used. The above shows the intent — match the actual variable names in the file.

- [ ] **Step 8: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests pass (existing + new).

- [ ] **Step 9: Commit**

```bash
git add backend/src/services/llm/llm_service.py backend/src/types/interview.py backend/src/services/interview/turn_manager.py backend/tests/test_confidence_capture.py
git commit -m "feat: capture LLM confidence in text-mode answer evaluation"
```

---

### Task 4: Backend — Save Text-Mode Reports to PostgreSQL

**Files:**
- Modify: `backend/src/models/interview_report.py:17-26` (add confidence fields to InterviewMetrics, add interview_type to InterviewReport)
- Modify: `backend/src/models/interview_report.py:90-129` (update save_report SQL)
- Modify: `backend/src/routes/interview.py:72-87` (save report after text evaluation)
- Modify: `backend/src/services/interview/voice_evaluation.py:170-193` (set interview_type for voice)

- [ ] **Step 1: Add fields to InterviewMetrics and InterviewReport**

In `backend/src/models/interview_report.py`, update `InterviewMetrics`:

```python
class InterviewMetrics(BaseModel):
    total_questions: int = 0
    questions_answered: int = 0
    avg_answer_duration_s: float = 0.0
    total_candidate_words: int = 0
    total_bot_words: int = 0
    follow_ups_used: int = 0
    barge_ins: int = 0
    silence_strikes: int = 0
    per_topic_confidence: dict[str, float] = Field(default_factory=dict)
    avg_transcription_confidence: float = 1.0
    avg_evaluation_confidence: float = 0.0
    qa_extraction_confidence: float = 1.0
```

Update `InterviewReport`:

```python
class InterviewReport(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    candidate_name: str = "Candidate"
    job_role: str = ""
    experience_level: str = "mid"
    interview_type: str = "text"
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    transcript: list[dict] = Field(default_factory=list)
    metrics: InterviewMetrics = Field(default_factory=InterviewMetrics)
    analysis: InterviewAnalysis = Field(default_factory=InterviewAnalysis)
    created_at: Optional[str] = None
```

- [ ] **Step 2: Update save_report SQL to include interview_type**

In `backend/src/models/interview_report.py`, update the `save_report` function's SQL:

```python
async def save_report(report: InterviewReport) -> bool:
    pool = await _get_pool()
    if pool is None:
        logger.error("No PG pool — report not saved for session %s", report.session_id)
        return False

    now = datetime.now(timezone.utc).isoformat()
    try:
        await pool.execute(
            """
            INSERT INTO interview_reports
                (id, session_id, candidate_name, job_role, experience_level,
                 interview_type, started_at, ended_at, duration_seconds,
                 transcript, metrics, analysis, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (session_id) DO UPDATE SET
                transcript = EXCLUDED.transcript,
                metrics = EXCLUDED.metrics,
                analysis = EXCLUDED.analysis,
                ended_at = EXCLUDED.ended_at,
                duration_seconds = EXCLUDED.duration_seconds,
                interview_type = EXCLUDED.interview_type
            """,
            uuid.UUID(report.id),
            report.session_id,
            report.candidate_name,
            report.job_role,
            report.experience_level,
            report.interview_type,
            datetime.fromisoformat(report.started_at) if report.started_at else None,
            datetime.fromisoformat(report.ended_at) if report.ended_at else None,
            report.duration_seconds,
            json.dumps(report.transcript),
            report.metrics.model_dump_json(),
            report.analysis.model_dump_json(),
            now,
        )
        logger.info("Report saved to PG for session %s", report.session_id)
        return True
    except Exception as exc:
        logger.error("Failed to save report session=%s: %s", report.session_id, exc)
        return False
```

- [ ] **Step 3: Update get_report_by_session to read interview_type**

In the same file, update `get_report_by_session`:

```python
async def get_report_by_session(session_id: str) -> Optional[InterviewReport]:
    pool = await _get_pool()
    if pool is None:
        return None

    try:
        row = await pool.fetchrow(
            "SELECT * FROM interview_reports WHERE session_id = $1",
            session_id,
        )
        if row is None:
            return None

        return InterviewReport(
            id=str(row["id"]),
            session_id=row["session_id"],
            candidate_name=row["candidate_name"],
            job_role=row["job_role"],
            experience_level=row["experience_level"],
            interview_type=row.get("interview_type", "text"),
            started_at=row["started_at"].isoformat() if row["started_at"] else None,
            ended_at=row["ended_at"].isoformat() if row["ended_at"] else None,
            duration_seconds=row["duration_seconds"],
            transcript=json.loads(row["transcript"]) if isinstance(row["transcript"], str) else row["transcript"],
            metrics=InterviewMetrics.model_validate_json(
                row["metrics"] if isinstance(row["metrics"], str) else json.dumps(row["metrics"])
            ),
            analysis=InterviewAnalysis.model_validate_json(
                row["analysis"] if isinstance(row["analysis"], str) else json.dumps(row["analysis"])
            ),
            created_at=row["created_at"].isoformat() if row["created_at"] else None,
        )
    except Exception as exc:
        logger.error("Failed to read report session=%s: %s", session_id, exc)
        return None
```

- [ ] **Step 4: Add list_reports function**

In the same file, add a new function after `get_report_by_session`:

```python
async def list_reports(
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[InterviewReport], int]:
    pool = await _get_pool()
    if pool is None:
        return [], 0

    try:
        count_row = await pool.fetchrow("SELECT COUNT(*) as cnt FROM interview_reports")
        total = count_row["cnt"] if count_row else 0

        rows = await pool.fetch(
            """
            SELECT * FROM interview_reports
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )

        reports = []
        for row in rows:
            try:
                reports.append(InterviewReport(
                    id=str(row["id"]),
                    session_id=row["session_id"],
                    candidate_name=row["candidate_name"],
                    job_role=row["job_role"],
                    experience_level=row["experience_level"],
                    interview_type=row.get("interview_type", "text"),
                    started_at=row["started_at"].isoformat() if row["started_at"] else None,
                    ended_at=row["ended_at"].isoformat() if row["ended_at"] else None,
                    duration_seconds=row["duration_seconds"],
                    transcript=json.loads(row["transcript"]) if isinstance(row["transcript"], str) else row["transcript"],
                    metrics=InterviewMetrics.model_validate_json(
                        row["metrics"] if isinstance(row["metrics"], str) else json.dumps(row["metrics"])
                    ),
                    analysis=InterviewAnalysis.model_validate_json(
                        row["analysis"] if isinstance(row["analysis"], str) else json.dumps(row["analysis"])
                    ),
                    created_at=row["created_at"].isoformat() if row["created_at"] else None,
                ))
            except Exception as exc:
                logger.warning("Skipping malformed report row %s: %s", row.get("session_id"), exc)

        return reports, total
    except Exception as exc:
        logger.error("Failed to list reports: %s", exc)
        return [], 0
```

- [ ] **Step 5: Save text-mode report to PG after evaluation**

In `backend/src/routes/interview.py`, modify the `submit_answer` function. After the evaluation is saved to the session and before the return, add PG persistence. Import needed modules at the top:

Add import at top of file:

```python
from src.models.interview_report import InterviewReport, InterviewMetrics, InterviewAnalysis, save_report as save_report_to_pg, get_report_by_session
```

Then in the `submit_answer` function, after `session_manager.end_session(session)` (around line 78), add:

```python
        # Persist to PostgreSQL for history
        confidences = [
            qr.confidence for qr in session.question_results
            if qr.confidence is not None
        ]
        avg_eval_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        text_metrics = InterviewMetrics(
            total_questions=len(session.questions),
            questions_answered=len(session.question_results),
            total_candidate_words=sum(
                len(t.text.split()) for t in session.transcript if t.speaker == "candidate"
            ),
            total_bot_words=sum(
                len(t.text.split()) for t in session.transcript if t.speaker == "bot"
            ),
            follow_ups_used=session.follow_up_count,
            avg_transcription_confidence=1.0,
            avg_evaluation_confidence=round(avg_eval_confidence, 3),
            qa_extraction_confidence=1.0,
        )

        text_analysis = InterviewAnalysis(
            summary=evaluation.summary,
            strengths=evaluation.strengths,
            weaknesses=evaluation.weaknesses,
            overall_score=evaluation.overall_score,
            hiring_recommendation=evaluation.recommendation,
            per_question=[qr.model_dump() for qr in evaluation.per_question],
            topic_scores=evaluation.topic_scores,
        )

        started = session.started_at
        ended = session.ended_at
        duration = None
        if started and ended:
            duration = int(
                (datetime.fromisoformat(ended) - datetime.fromisoformat(started)).total_seconds()
            )

        text_report = InterviewReport(
            session_id=session.session_id,
            candidate_name=session.candidate_name,
            job_role=session.job_role,
            experience_level=session.experience_level.value,
            interview_type="text",
            started_at=started,
            ended_at=ended,
            duration_seconds=duration,
            transcript=[t.model_dump() for t in session.transcript],
            metrics=text_metrics,
            analysis=text_analysis,
        )

        await save_report_to_pg(text_report)
```

- [ ] **Step 6: Set interview_type="voice" in voice evaluation**

In `backend/src/services/interview/voice_evaluation.py`, in the `run_voice_evaluation` function, update the InterviewReport construction (around line 172):

```python
    report = InterviewReport(
        session_id=session_id,
        candidate_name=voice_data.get("candidate_name", "Candidate"),
        job_role=voice_data.get("job_role", ""),
        experience_level=voice_data.get("experience_level", "mid"),
        interview_type="voice",
        started_at=voice_data.get("started_at"),
        ended_at=now,
        duration_seconds=None,
        transcript=transcript_raw,
        metrics=metrics,
        analysis=analysis,
    )
```

- [ ] **Step 7: Populate new confidence fields in voice metrics**

In `backend/src/services/interview/voice_evaluation.py`, update `_compute_metrics` to populate the new fields:

```python
def _compute_metrics(voice_data: dict[str, Any]) -> InterviewMetrics:
    transcript: list[dict] = json.loads(voice_data.get("transcript", "[]"))
    questions: list[dict] = json.loads(voice_data.get("questions", "[]"))

    candidate_turns = [t for t in transcript if t.get("speaker") == "candidate"]
    bot_turns = [t for t in transcript if t.get("speaker") == "bot"]

    total_candidate_words = sum(len(t.get("text", "").split()) for t in candidate_turns)
    total_bot_words = sum(len(t.get("text", "").split()) for t in bot_turns)

    questions_answered = len(candidate_turns)
    avg_duration = 0.0

    per_topic_conf = _compute_per_topic_confidence(voice_data)

    llm_confs: dict[str, float] = json.loads(voice_data.get("llm_confidence_by_topic", "{}"))
    avg_eval_conf = sum(llm_confs.values()) / len(llm_confs) if llm_confs else 0.0

    total_turns = max(int(voice_data.get("turn_count", 1)), 1)
    retries = int(voice_data.get("low_confidence_retries", 0))
    stt_reliability = max(0.0, 1.0 - (retries / total_turns))

    fu_count = int(voice_data.get("follow_up_count", 0))
    topic_count = max(len(per_topic_conf), 1)
    qa_extraction = max(0.0, 1.0 - (fu_count / (2.0 * topic_count)))

    return InterviewMetrics(
        total_questions=len(questions),
        questions_answered=questions_answered,
        avg_answer_duration_s=avg_duration,
        total_candidate_words=total_candidate_words,
        total_bot_words=total_bot_words,
        follow_ups_used=int(voice_data.get("follow_up_count", 0)),
        barge_ins=int(voice_data.get("barge_in_count", 0)),
        silence_strikes=int(voice_data.get("silence_strikes", 0)),
        per_topic_confidence=per_topic_conf,
        avg_transcription_confidence=round(stt_reliability, 3),
        avg_evaluation_confidence=round(avg_eval_conf, 3),
        qa_extraction_confidence=round(qa_extraction, 3),
    )
```

- [ ] **Step 8: Run tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 9: Commit**

```bash
git add backend/src/models/interview_report.py backend/src/routes/interview.py backend/src/services/interview/voice_evaluation.py
git commit -m "feat: persist text-mode reports to PostgreSQL, add confidence fields"
```

---

### Task 5: Backend — Admin API Endpoints

**Files:**
- Create: `backend/src/types/admin.py`
- Create: `backend/src/routes/admin.py`
- Modify: `backend/main.py:50-54` (register router)
- Test: `backend/tests/test_admin_routes.py`

- [ ] **Step 1: Write test for admin auth dependency**

Create `backend/tests/test_admin_routes.py`:

```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    with patch.dict("os.environ", {"ADMIN_API_KEY": "test-admin-key"}):
        from src.lib.settings import get_settings
        get_settings.cache_clear()

        from main import app
        yield app

        get_settings.cache_clear()


@pytest.fixture
def client(app):
    return TestClient(app)


def test_admin_list_requires_api_key(client):
    response = client.get("/api/v1/admin/interviews")
    assert response.status_code == 401


def test_admin_list_rejects_wrong_key(client):
    response = client.get(
        "/api/v1/admin/interviews",
        headers={"X-Admin-Key": "wrong-key"},
    )
    assert response.status_code == 401


def test_admin_list_accepts_valid_key(client):
    with patch("src.routes.admin.list_reports", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = ([], 0)
        response = client.get(
            "/api/v1/admin/interviews",
            headers={"X-Admin-Key": "test-admin-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["interviews"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_admin_routes.py -v`
Expected: FAIL — module or route not found.

- [ ] **Step 3: Create admin API schemas**

Create `backend/src/types/admin.py`:

```python
from typing import Optional
from pydantic import BaseModel, Field


class InterviewSummary(BaseModel):
    session_id: str
    candidate_name: str
    job_role: str
    experience_level: str
    interview_type: str
    overall_score: float
    recommendation: str
    started_at: Optional[str]
    ended_at: Optional[str]
    duration_seconds: Optional[int]
    created_at: Optional[str]


class InterviewListResponse(BaseModel):
    interviews: list[InterviewSummary]
    total: int
    page: int
    limit: int


class InterviewDetailResponse(BaseModel):
    session_id: str
    candidate_name: str
    job_role: str
    experience_level: str
    interview_type: str
    overall_score: float
    recommendation: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    summary: str = ""
    per_question: list[dict] = Field(default_factory=list)
    topic_scores: dict[str, float] = Field(default_factory=dict)
    transcript: list[dict] = Field(default_factory=list)
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    created_at: Optional[str] = None
    avg_transcription_confidence: float = 1.0
    avg_evaluation_confidence: float = 0.0
    qa_extraction_confidence: float = 1.0
    per_topic_confidence: dict[str, float] = Field(default_factory=dict)
    category_scores: dict[str, dict] = Field(default_factory=dict)
```

- [ ] **Step 4: Create admin router**

Create `backend/src/routes/admin.py`:

```python
import logging
from fastapi import APIRouter, HTTPException, Header, Depends, Query, status
from src.lib.settings import get_settings
from src.types.admin import InterviewListResponse, InterviewSummary, InterviewDetailResponse
from src.models.interview_report import list_reports, get_report_by_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


async def require_admin(x_admin_key: str = Header(default="")) -> None:
    settings = get_settings()
    if not x_admin_key or x_admin_key != settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin API key.",
        )


@router.get(
    "/interviews",
    response_model=InterviewListResponse,
    dependencies=[Depends(require_admin)],
)
async def list_interviews(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> InterviewListResponse:
    offset = (page - 1) * limit
    reports, total = await list_reports(limit=limit, offset=offset)

    summaries = []
    for r in reports:
        summaries.append(InterviewSummary(
            session_id=r.session_id,
            candidate_name=r.candidate_name,
            job_role=r.job_role,
            experience_level=r.experience_level,
            interview_type=r.interview_type,
            overall_score=r.analysis.overall_score,
            recommendation=r.analysis.hiring_recommendation,
            started_at=r.started_at,
            ended_at=r.ended_at,
            duration_seconds=r.duration_seconds,
            created_at=r.created_at,
        ))

    return InterviewListResponse(
        interviews=summaries,
        total=total,
        page=page,
        limit=limit,
    )


@router.get(
    "/interviews/{session_id}",
    response_model=InterviewDetailResponse,
    dependencies=[Depends(require_admin)],
)
async def get_interview_detail(session_id: str) -> InterviewDetailResponse:
    report = await get_report_by_session(session_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Interview not found.",
        )

    category_scores = {}
    for field_name in ("communication_clarity", "technical_depth", "confidence_consistency", "relevance"):
        cs = getattr(report.analysis, field_name, None)
        if cs and cs.score > 0:
            category_scores[field_name] = {
                "score": cs.score,
                "explanation": cs.explanation,
                "evidence": cs.evidence,
            }

    return InterviewDetailResponse(
        session_id=report.session_id,
        candidate_name=report.candidate_name,
        job_role=report.job_role,
        experience_level=report.experience_level,
        interview_type=report.interview_type,
        overall_score=report.analysis.overall_score,
        recommendation=report.analysis.hiring_recommendation,
        strengths=report.analysis.strengths,
        weaknesses=report.analysis.weaknesses,
        summary=report.analysis.summary,
        per_question=report.analysis.per_question,
        topic_scores=report.analysis.topic_scores,
        transcript=report.transcript,
        started_at=report.started_at,
        ended_at=report.ended_at,
        duration_seconds=report.duration_seconds,
        created_at=report.created_at,
        avg_transcription_confidence=report.metrics.avg_transcription_confidence,
        avg_evaluation_confidence=report.metrics.avg_evaluation_confidence,
        qa_extraction_confidence=report.metrics.qa_extraction_confidence,
        per_topic_confidence=report.metrics.per_topic_confidence,
        category_scores=category_scores,
    )
```

- [ ] **Step 5: Register admin router in main.py**

In `backend/main.py`, add the import and registration:

Add import:
```python
from src.routes.admin import router as admin_router
```

Add registration after the last `app.include_router(...)` line:
```python
app.include_router(admin_router, prefix="/api/v1")
```

- [ ] **Step 6: Run tests**

Run: `cd backend && python -m pytest tests/test_admin_routes.py -v`
Expected: All 3 tests pass.

- [ ] **Step 7: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add backend/src/types/admin.py backend/src/routes/admin.py backend/main.py backend/tests/test_admin_routes.py
git commit -m "feat: add admin API endpoints for interview history and detail"
```

---

### Task 6: Frontend — Auth Context & Login Page

**Files:**
- Create: `frontend/src/contexts/AuthContext.tsx`
- Create: `frontend/src/app/login/page.tsx`

- [ ] **Step 1: Create AuthContext**

Create `frontend/src/contexts/AuthContext.tsx`:

```tsx
"use client";

import { createContext, useContext, useState, useEffect, useCallback } from "react";
import type { ReactNode } from "react";

export type UserRole = "admin" | "candidate";

interface AuthState {
  name: string;
  role: UserRole;
}

interface AuthContextValue {
  user: AuthState | null;
  isAdmin: boolean;
  login: (name: string, role: UserRole) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  isAdmin: false,
  login: () => {},
  logout: () => {},
});

const STORAGE_KEY = "ai_interview_auth";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthState | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        setUser(JSON.parse(stored));
      }
    } catch {}
    setLoaded(true);
  }, []);

  const login = useCallback((name: string, role: UserRole) => {
    const state: AuthState = { name, role };
    setUser(state);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }, []);

  const logout = useCallback(() => {
    setUser(null);
    localStorage.removeItem(STORAGE_KEY);
  }, []);

  if (!loaded) {
    return null;
  }

  return (
    <AuthContext.Provider
      value={{ user, isAdmin: user?.role === "admin", login, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
```

- [ ] **Step 2: Create login page**

Create `frontend/src/app/login/page.tsx`:

```tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth, type UserRole } from "@/contexts/AuthContext";

const ADMIN_PASSPHRASE = process.env.NEXT_PUBLIC_ADMIN_PASSPHRASE ?? "admin";

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuth();
  const [name, setName] = useState("");
  const [role, setRole] = useState<UserRole>("candidate");
  const [passphrase, setPassphrase] = useState("");
  const [error, setError] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!name.trim()) {
      setError("Please enter your name.");
      return;
    }

    if (role === "admin" && passphrase !== ADMIN_PASSPHRASE) {
      setError("Invalid admin passphrase.");
      return;
    }

    login(name.trim(), role);
    router.push("/");
  };

  return (
    <div className="flex flex-col items-center justify-center min-h-[70vh]">
      <div className="w-full max-w-md">
        <h1 className="text-2xl font-bold text-slate-900 mb-6 text-center">
          Sign In
        </h1>
        <form onSubmit={handleSubmit} className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm space-y-5">
          <div>
            <label htmlFor="name" className="block text-sm font-medium text-slate-700 mb-1">
              Name
            </label>
            <input
              id="name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              placeholder="Your name"
              autoFocus
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">
              Role
            </label>
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setRole("candidate")}
                className={`px-4 py-3 rounded-lg border text-sm font-medium transition-colors ${
                  role === "candidate"
                    ? "border-blue-500 bg-blue-50 text-blue-700"
                    : "border-slate-200 text-slate-600 hover:bg-slate-50"
                }`}
              >
                Candidate
              </button>
              <button
                type="button"
                onClick={() => setRole("admin")}
                className={`px-4 py-3 rounded-lg border text-sm font-medium transition-colors ${
                  role === "admin"
                    ? "border-violet-500 bg-violet-50 text-violet-700"
                    : "border-slate-200 text-slate-600 hover:bg-slate-50"
                }`}
              >
                Admin
              </button>
            </div>
          </div>

          {role === "admin" && (
            <div>
              <label htmlFor="passphrase" className="block text-sm font-medium text-slate-700 mb-1">
                Admin Passphrase
              </label>
              <input
                id="passphrase"
                type="password"
                value={passphrase}
                onChange={(e) => setPassphrase(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent"
                placeholder="Enter admin passphrase"
              />
            </div>
          )}

          {error && (
            <p className="text-sm text-red-600">{error}</p>
          )}

          <button
            type="submit"
            className="w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-3 rounded-lg transition-colors"
          >
            Continue
          </button>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Add NEXT_PUBLIC_ADMIN_PASSPHRASE to frontend env example**

Append to `frontend/.env.local.example`:

```
NEXT_PUBLIC_ADMIN_PASSPHRASE=admin
NEXT_PUBLIC_ADMIN_API_KEY=change-me-admin-key
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/contexts/AuthContext.tsx frontend/src/app/login/page.tsx frontend/.env.local.example
git commit -m "feat: add auth context and login page with role selection"
```

---

### Task 7: Frontend — Navbar Component

**Files:**
- Create: `frontend/src/components/Navbar.tsx`

- [ ] **Step 1: Create responsive Navbar**

Create `frontend/src/components/Navbar.tsx`:

```tsx
"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";

interface NavLink {
  href: string;
  label: string;
  adminOnly?: boolean;
}

const NAV_LINKS: NavLink[] = [
  { href: "/interview/mode-select", label: "Text Interview" },
  { href: "/interview/voice/start", label: "Voice Interview" },
  { href: "/admin/history", label: "History", adminOnly: true },
];

export default function Navbar() {
  const { user, isAdmin, logout } = useAuth();
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  const visibleLinks = NAV_LINKS.filter((link) => !link.adminOnly || isAdmin);

  const isActive = (href: string) => {
    if (href === "/interview/mode-select") {
      return pathname.startsWith("/interview") && !pathname.startsWith("/interview/voice");
    }
    if (href === "/interview/voice/start") {
      return pathname.startsWith("/interview/voice");
    }
    return pathname.startsWith(href);
  };

  return (
    <nav className="bg-white border-b border-slate-200">
      <div className="max-w-6xl mx-auto px-4 sm:px-6">
        <div className="flex items-center justify-between h-14">
          <div className="flex items-center gap-8">
            <Link href="/" className="text-lg font-bold text-slate-900 shrink-0">
              AI Interview Bot
            </Link>

            {user && (
              <div className="hidden md:flex items-center gap-1">
                {visibleLinks.map((link) => (
                  <Link
                    key={link.href}
                    href={link.href}
                    className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                      isActive(link.href)
                        ? "bg-blue-50 text-blue-700"
                        : "text-slate-600 hover:text-slate-900 hover:bg-slate-50"
                    }`}
                  >
                    {link.label}
                  </Link>
                ))}
              </div>
            )}
          </div>

          <div className="flex items-center gap-3">
            {user ? (
              <>
                <span className="hidden sm:inline text-sm text-slate-500">
                  {user.name}
                </span>
                {isAdmin && (
                  <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-violet-100 text-violet-700">
                    Admin
                  </span>
                )}
                <button
                  onClick={logout}
                  className="text-sm text-slate-500 hover:text-slate-700 transition-colors"
                >
                  Sign out
                </button>
              </>
            ) : (
              <Link
                href="/login"
                className="text-sm font-medium text-blue-600 hover:text-blue-700 transition-colors"
              >
                Sign in
              </Link>
            )}

            {user && (
              <button
                onClick={() => setMobileOpen(!mobileOpen)}
                className="md:hidden p-1.5 rounded-md text-slate-500 hover:bg-slate-50"
                aria-label="Toggle menu"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  {mobileOpen ? (
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  ) : (
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                  )}
                </svg>
              </button>
            )}
          </div>
        </div>

        {mobileOpen && user && (
          <div className="md:hidden border-t border-slate-100 py-2 pb-3">
            {visibleLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                onClick={() => setMobileOpen(false)}
                className={`block px-3 py-2 rounded-md text-sm font-medium ${
                  isActive(link.href)
                    ? "bg-blue-50 text-blue-700"
                    : "text-slate-600 hover:bg-slate-50"
                }`}
              >
                {link.label}
              </Link>
            ))}
          </div>
        )}
      </div>
    </nav>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/Navbar.tsx
git commit -m "feat: add responsive role-aware navbar component"
```

---

### Task 8: Frontend — Layout Integration & Route Protection

**Files:**
- Modify: `frontend/src/app/layout.tsx` (wrap with AuthProvider, use Navbar)
- Create: `frontend/src/components/AdminGuard.tsx`

- [ ] **Step 1: Create AdminGuard component**

Create `frontend/src/components/AdminGuard.tsx`:

```tsx
"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";

interface AdminGuardProps {
  children: React.ReactNode;
}

export default function AdminGuard({ children }: AdminGuardProps) {
  const { user, isAdmin } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!user) {
      router.replace("/login");
    } else if (!isAdmin) {
      router.replace("/");
    }
  }, [user, isAdmin, router]);

  if (!user || !isAdmin) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <p className="text-slate-500 text-sm">Checking access...</p>
      </div>
    );
  }

  return <>{children}</>;
}
```

- [ ] **Step 2: Update layout.tsx**

Replace the entire content of `frontend/src/app/layout.tsx`:

```tsx
import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/contexts/AuthContext";
import Navbar from "@/components/Navbar";

export const metadata: Metadata = {
  title: "AI Interview Bot",
  description: "AI-powered job interview simulator with real-time evaluation",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50">
        <AuthProvider>
          <Navbar />
          <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8">{children}</main>
        </AuthProvider>
      </body>
    </html>
  );
}
```

Note: `max-w-4xl` changed to `max-w-6xl` and `px-6` to `px-4 sm:px-6` to match the Navbar's container width for visual consistency.

- [ ] **Step 3: Start dev server and test**

Run: `cd frontend && npm run dev`

Manual checks:
- Visit `http://localhost:3000` — should see homepage with Navbar showing brand + "Sign in" link
- Click "Sign in" — should see login page with name, role selection, submit
- Login as candidate — navbar shows "Text Interview" + "Voice Interview" only
- Logout, login as admin (passphrase: "admin") — navbar shows all links including "History"
- Try visiting `/admin/history` without login — should redirect to `/login`
- Login as candidate, try visiting `/admin/history` — should redirect to `/`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AdminGuard.tsx frontend/src/app/layout.tsx
git commit -m "feat: integrate auth provider and navbar into layout, add admin guard"
```

---

### Task 9: Frontend — Admin API Service & Types

**Files:**
- Create: `frontend/src/types/admin.ts`
- Create: `frontend/src/services/admin-api.ts`

- [ ] **Step 1: Create admin types**

Create `frontend/src/types/admin.ts`:

```typescript
export interface InterviewSummary {
  session_id: string;
  candidate_name: string;
  job_role: string;
  experience_level: string;
  interview_type: string;
  overall_score: number;
  recommendation: string;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  created_at: string | null;
}

export interface InterviewListResponse {
  interviews: InterviewSummary[];
  total: number;
  page: number;
  limit: number;
}

export interface CategoryScore {
  score: number;
  explanation: string;
  evidence: string;
}

export interface InterviewDetail {
  session_id: string;
  candidate_name: string;
  job_role: string;
  experience_level: string;
  interview_type: string;
  overall_score: number;
  recommendation: string;
  strengths: string[];
  weaknesses: string[];
  summary: string;
  per_question: Array<{
    question_id?: string;
    question_text?: string;
    question?: string;
    topic?: string;
    answer_text?: string;
    answer?: string;
    score?: number | null;
    score_reasoning?: string;
    reasoning?: string;
    confidence?: number | null;
  }>;
  topic_scores: Record<string, number>;
  transcript: Array<{
    speaker: string;
    text: string;
    timestamp?: string;
    type?: string;
    turn_idx?: number;
    question_id?: string | null;
  }>;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  created_at: string | null;
  avg_transcription_confidence: number;
  avg_evaluation_confidence: number;
  qa_extraction_confidence: number;
  per_topic_confidence: Record<string, number>;
  category_scores: Record<string, CategoryScore>;
}
```

- [ ] **Step 2: Create admin API service**

Create `frontend/src/services/admin-api.ts`:

```typescript
import type { InterviewListResponse, InterviewDetail } from "@/types/admin";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const ADMIN_KEY = process.env.NEXT_PUBLIC_ADMIN_API_KEY ?? "change-me-admin-key";

class AdminApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public detail?: string
  ) {
    super(message);
    this.name = "AdminApiError";
  }
}

async function adminRequest<T>(path: string): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      "X-Admin-Key": ADMIN_KEY,
    },
  });

  if (!res.ok) {
    let detail: string | undefined;
    try {
      const body = await res.json();
      detail = body.detail ?? body.error;
    } catch {
      detail = res.statusText;
    }
    throw new AdminApiError(`HTTP ${res.status}`, res.status, detail);
  }

  return res.json() as Promise<T>;
}

export async function listInterviews(
  page: number = 1,
  limit: number = 20
): Promise<InterviewListResponse> {
  return adminRequest<InterviewListResponse>(
    `/api/v1/admin/interviews?page=${page}&limit=${limit}`
  );
}

export async function getInterviewDetail(
  sessionId: string
): Promise<InterviewDetail> {
  return adminRequest<InterviewDetail>(
    `/api/v1/admin/interviews/${sessionId}`
  );
}

export { AdminApiError };
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/admin.ts frontend/src/services/admin-api.ts
git commit -m "feat: add admin API types and service client"
```

---

### Task 10: Frontend — History Page

**Files:**
- Create: `frontend/src/app/admin/history/page.tsx`

- [ ] **Step 1: Create history page**

Create `frontend/src/app/admin/history/page.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import AdminGuard from "@/components/AdminGuard";
import ScoreBadge from "@/components/ScoreBadge";
import { listInterviews } from "@/services/admin-api";
import type { InterviewSummary } from "@/types/admin";

const RECOMMENDATION_LABELS: Record<string, { label: string; color: string }> = {
  strong_yes: { label: "Strong Yes", color: "text-green-700 bg-green-50" },
  yes: { label: "Yes", color: "text-blue-700 bg-blue-50" },
  maybe: { label: "Maybe", color: "text-yellow-700 bg-yellow-50" },
  no: { label: "No", color: "text-orange-700 bg-orange-50" },
  strong_no: { label: "Strong No", color: "text-red-700 bg-red-50" },
};

function formatDate(iso: string | null): string {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "-";
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}m ${secs}s`;
}

export default function HistoryPage() {
  const [interviews, setInterviews] = useState<InterviewSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const limit = 20;

  useEffect(() => {
    setLoading(true);
    setError("");
    listInterviews(page, limit)
      .then((data) => {
        setInterviews(data.interviews);
        setTotal(data.total);
      })
      .catch((err) => {
        setError(err.detail ?? err.message ?? "Failed to load interviews.");
      })
      .finally(() => setLoading(false));
  }, [page]);

  const totalPages = Math.ceil(total / limit);

  return (
    <AdminGuard>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Interview History</h1>
            <p className="text-sm text-slate-500 mt-1">
              {total} interview{total !== 1 ? "s" : ""} on record
            </p>
          </div>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
            {error}
          </div>
        )}

        {loading ? (
          <div className="bg-white rounded-xl border border-slate-200 p-12 text-center">
            <p className="text-slate-500 text-sm">Loading interviews...</p>
          </div>
        ) : interviews.length === 0 ? (
          <div className="bg-white rounded-xl border border-slate-200 p-12 text-center">
            <p className="text-slate-500">No interviews found.</p>
            <p className="text-sm text-slate-400 mt-1">
              Completed interviews will appear here.
            </p>
          </div>
        ) : (
          <>
            <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 bg-slate-50">
                      <th className="text-left px-4 py-3 font-medium text-slate-600">Candidate</th>
                      <th className="text-left px-4 py-3 font-medium text-slate-600">Role</th>
                      <th className="text-left px-4 py-3 font-medium text-slate-600">Type</th>
                      <th className="text-left px-4 py-3 font-medium text-slate-600">Score</th>
                      <th className="text-left px-4 py-3 font-medium text-slate-600">Recommendation</th>
                      <th className="text-left px-4 py-3 font-medium text-slate-600">Duration</th>
                      <th className="text-left px-4 py-3 font-medium text-slate-600">Date</th>
                      <th className="text-right px-4 py-3 font-medium text-slate-600"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {interviews.map((interview) => {
                      const rec = RECOMMENDATION_LABELS[interview.recommendation] ?? {
                        label: interview.recommendation,
                        color: "text-slate-700 bg-slate-50",
                      };
                      return (
                        <tr key={interview.session_id} className="hover:bg-slate-50 transition-colors">
                          <td className="px-4 py-3 font-medium text-slate-900">
                            {interview.candidate_name}
                          </td>
                          <td className="px-4 py-3 text-slate-600">
                            {interview.job_role}
                            <span className="text-slate-400 ml-1 text-xs capitalize">
                              ({interview.experience_level})
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                              interview.interview_type === "voice"
                                ? "bg-violet-50 text-violet-700"
                                : "bg-blue-50 text-blue-700"
                            }`}>
                              {interview.interview_type}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <ScoreBadge score={interview.overall_score} size="sm" />
                          </td>
                          <td className="px-4 py-3">
                            <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${rec.color}`}>
                              {rec.label}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-slate-600">
                            {formatDuration(interview.duration_seconds)}
                          </td>
                          <td className="px-4 py-3 text-slate-500">
                            {formatDate(interview.started_at)}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <Link
                              href={`/admin/analysis/${interview.session_id}`}
                              className="text-sm font-medium text-blue-600 hover:text-blue-700 transition-colors"
                            >
                              View Analysis
                            </Link>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {totalPages > 1 && (
              <div className="flex items-center justify-between">
                <p className="text-sm text-slate-500">
                  Page {page} of {totalPages}
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1}
                    className="px-3 py-1.5 text-sm rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    Previous
                  </button>
                  <button
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page >= totalPages}
                    className="px-3 py-1.5 text-sm rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </AdminGuard>
  );
}
```

- [ ] **Step 2: Test manually**

Run: `npm run dev` (both backend + frontend)

Manual checks:
- Login as admin
- Navigate to "History" in navbar
- If no interviews exist, see empty state message
- Complete a text interview, then check History again — it should appear
- Verify all columns render correctly
- Verify pagination (if >20 interviews)
- Verify "View Analysis" link points to correct URL
- Verify mobile responsiveness (table scrolls horizontally)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/admin/history/page.tsx
git commit -m "feat: add admin interview history page with paginated table"
```

---

### Task 11: Frontend — Confidence Metrics Component

**Files:**
- Create: `frontend/src/components/ConfidenceMetrics.tsx`

- [ ] **Step 1: Create ConfidenceMetrics component**

Create `frontend/src/components/ConfidenceMetrics.tsx`:

```tsx
"use client";

interface ConfidenceMetricsProps {
  avgTranscriptionConfidence: number;
  avgEvaluationConfidence: number;
  qaExtractionConfidence: number;
  interviewType: string;
}

function confidenceColor(value: number): string {
  if (value >= 0.8) return "text-green-700 bg-green-50 border-green-200";
  if (value >= 0.6) return "text-blue-700 bg-blue-50 border-blue-200";
  if (value >= 0.4) return "text-yellow-700 bg-yellow-50 border-yellow-200";
  return "text-red-700 bg-red-50 border-red-200";
}

function confidenceBarColor(value: number): string {
  if (value >= 0.8) return "bg-green-500";
  if (value >= 0.6) return "bg-blue-500";
  if (value >= 0.4) return "bg-yellow-500";
  return "bg-red-400";
}

interface MetricCardProps {
  label: string;
  value: number;
  description: string;
  trivial?: boolean;
}

function MetricCard({ label, value, description, trivial }: MetricCardProps) {
  return (
    <div className={`rounded-xl border p-4 ${confidenceColor(value)}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium">{label}</span>
        <span className="text-lg font-bold">{(value * 100).toFixed(0)}%</span>
      </div>
      <div className="h-2 bg-white/60 rounded-full overflow-hidden mb-2">
        <div
          className={`h-full rounded-full transition-all ${confidenceBarColor(value)}`}
          style={{ width: `${value * 100}%` }}
        />
      </div>
      <p className="text-xs opacity-80">
        {description}
        {trivial && " (exact for typed input)"}
      </p>
    </div>
  );
}

export default function ConfidenceMetrics({
  avgTranscriptionConfidence,
  avgEvaluationConfidence,
  qaExtractionConfidence,
  interviewType,
}: ConfidenceMetricsProps) {
  const isText = interviewType === "text";

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
      <h3 className="font-semibold text-slate-900 mb-4">Confidence Metrics</h3>
      <div className="grid sm:grid-cols-3 gap-4">
        <MetricCard
          label="Transcription"
          value={avgTranscriptionConfidence}
          description="How reliable is the input text"
          trivial={isText}
        />
        <MetricCard
          label="Q&A Extraction"
          value={qaExtractionConfidence}
          description="How well Q&A pairs were identified"
          trivial={isText}
        />
        <MetricCard
          label="Answer Evaluation"
          value={avgEvaluationConfidence}
          description="AI confidence in its scoring"
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/ConfidenceMetrics.tsx
git commit -m "feat: add confidence metrics dashboard component"
```

---

### Task 12: Frontend — Post-Interview Analysis Page

**Files:**
- Create: `frontend/src/app/admin/analysis/[sessionId]/page.tsx`

- [ ] **Step 1: Create analysis page**

Create `frontend/src/app/admin/analysis/[sessionId]/page.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import AdminGuard from "@/components/AdminGuard";
import ScoreBadge from "@/components/ScoreBadge";
import ConfidenceMetrics from "@/components/ConfidenceMetrics";
import TranscriptTimeline from "@/components/TranscriptTimeline";
import { getInterviewDetail } from "@/services/admin-api";
import type { InterviewDetail } from "@/types/admin";

const RECOMMENDATION_LABELS: Record<string, { label: string; color: string }> = {
  strong_yes: { label: "Strong Yes", color: "bg-green-100 text-green-800 border-green-200" },
  yes: { label: "Yes", color: "bg-blue-100 text-blue-800 border-blue-200" },
  maybe: { label: "Maybe", color: "bg-yellow-100 text-yellow-800 border-yellow-200" },
  no: { label: "No", color: "bg-orange-100 text-orange-800 border-orange-200" },
  strong_no: { label: "Strong No", color: "bg-red-100 text-red-800 border-red-200" },
};

function formatDate(iso: string | null): string {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function confidenceLabel(value: number | null | undefined): { text: string; color: string } {
  if (value === null || value === undefined) return { text: "N/A", color: "text-slate-400" };
  if (value >= 0.8) return { text: "High", color: "text-green-600" };
  if (value >= 0.6) return { text: "Medium", color: "text-blue-600" };
  if (value >= 0.4) return { text: "Low", color: "text-yellow-600" };
  return { text: "Very Low", color: "text-red-600" };
}

export default function AnalysisPage() {
  const params = useParams();
  const sessionId = params.sessionId as string;

  const [detail, setDetail] = useState<InterviewDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!sessionId) return;
    setLoading(true);
    setError("");
    getInterviewDetail(sessionId)
      .then(setDetail)
      .catch((err) => {
        setError(err.detail ?? err.message ?? "Failed to load interview.");
      })
      .finally(() => setLoading(false));
  }, [sessionId]);

  if (loading) {
    return (
      <AdminGuard>
        <div className="flex items-center justify-center min-h-[50vh]">
          <p className="text-slate-500 text-sm">Loading analysis...</p>
        </div>
      </AdminGuard>
    );
  }

  if (error || !detail) {
    return (
      <AdminGuard>
        <div className="space-y-4">
          <Link href="/admin/history" className="text-sm text-blue-600 hover:text-blue-700">
            &larr; Back to History
          </Link>
          <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
            <p className="text-red-700">{error || "Interview not found."}</p>
          </div>
        </div>
      </AdminGuard>
    );
  }

  const rec = RECOMMENDATION_LABELS[detail.recommendation] ?? {
    label: detail.recommendation,
    color: "bg-slate-100 text-slate-800 border-slate-200",
  };

  const durationStr = detail.duration_seconds
    ? `${Math.floor(detail.duration_seconds / 60)}m ${detail.duration_seconds % 60}s`
    : null;

  return (
    <AdminGuard>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <Link href="/admin/history" className="text-sm text-blue-600 hover:text-blue-700">
            &larr; Back to History
          </Link>
          <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
            detail.interview_type === "voice"
              ? "bg-violet-50 text-violet-700"
              : "bg-blue-50 text-blue-700"
          }`}>
            {detail.interview_type} interview
          </span>
        </div>

        {/* Header card */}
        <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-4">
            <div>
              <h1 className="text-2xl font-bold text-slate-900">
                {detail.candidate_name}
              </h1>
              <p className="text-slate-500">
                {detail.job_role} &middot; {detail.experience_level}
                {durationStr && ` · ${durationStr}`}
                {detail.started_at && ` · ${formatDate(detail.started_at)}`}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <ScoreBadge score={detail.overall_score} size="lg" />
              <span className={`text-sm font-semibold px-3 py-1.5 rounded-full border ${rec.color}`}>
                {rec.label}
              </span>
            </div>
          </div>
          {detail.summary && (
            <p className="text-slate-700 text-sm leading-relaxed bg-slate-50 rounded-lg p-4">
              {detail.summary}
            </p>
          )}
        </div>

        {/* Confidence metrics */}
        <ConfidenceMetrics
          avgTranscriptionConfidence={detail.avg_transcription_confidence}
          avgEvaluationConfidence={detail.avg_evaluation_confidence}
          qaExtractionConfidence={detail.qa_extraction_confidence}
          interviewType={detail.interview_type}
        />

        {/* Strengths & Weaknesses */}
        {(detail.strengths.length > 0 || detail.weaknesses.length > 0) && (
          <div className="grid sm:grid-cols-2 gap-4">
            {detail.strengths.length > 0 && (
              <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
                <h3 className="font-semibold text-green-700 mb-3">Strengths</h3>
                <ul className="space-y-2">
                  {detail.strengths.map((s, i) => (
                    <li key={i} className="text-sm text-slate-700 flex gap-2">
                      <span className="text-green-500 mt-0.5 shrink-0">&bull;</span>
                      {s}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {detail.weaknesses.length > 0 && (
              <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
                <h3 className="font-semibold text-orange-700 mb-3">Areas to Improve</h3>
                <ul className="space-y-2">
                  {detail.weaknesses.map((w, i) => (
                    <li key={i} className="text-sm text-slate-700 flex gap-2">
                      <span className="text-orange-400 mt-0.5 shrink-0">&bull;</span>
                      {w}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Topic Scores */}
        {Object.keys(detail.topic_scores).length > 0 && (
          <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
            <h3 className="font-semibold text-slate-900 mb-4">Scores by Topic</h3>
            <div className="space-y-3">
              {Object.entries(detail.topic_scores).map(([topic, score]) => {
                const topicConf = detail.per_topic_confidence[topic];
                const conf = confidenceLabel(topicConf);
                return (
                  <div key={topic} className="flex items-center gap-3">
                    <span className="text-sm text-slate-600 w-32 capitalize shrink-0">
                      {topic.replace(/_/g, " ")}
                    </span>
                    <div className="flex-1 h-2.5 bg-slate-100 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${
                          score >= 8 ? "bg-green-500"
                          : score >= 6 ? "bg-blue-500"
                          : score >= 4 ? "bg-yellow-500"
                          : "bg-red-400"
                        }`}
                        style={{ width: `${(score / 10) * 100}%` }}
                      />
                    </div>
                    <span className="text-sm font-medium text-slate-700 w-10 text-right">
                      {score.toFixed(1)}
                    </span>
                    {topicConf !== undefined && (
                      <span className={`text-xs w-16 text-right ${conf.color}`}>
                        {conf.text}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Category Scores (voice-mode only, when available) */}
        {Object.keys(detail.category_scores).length > 0 && (
          <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
            <h3 className="font-semibold text-slate-900 mb-4">Category Scores</h3>
            <div className="grid sm:grid-cols-2 gap-4">
              {Object.entries(detail.category_scores).map(([category, cs]) => (
                <div key={category} className="border border-slate-100 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium text-slate-800 capitalize">
                      {category.replace(/_/g, " ")}
                    </span>
                    <ScoreBadge score={cs.score} size="sm" />
                  </div>
                  {cs.explanation && (
                    <p className="text-xs text-slate-600 mb-1">{cs.explanation}</p>
                  )}
                  {cs.evidence && (
                    <p className="text-xs text-slate-400 italic">{cs.evidence}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Per-Question Breakdown */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
          <h3 className="font-semibold text-slate-900 mb-4">Question-Answer Analysis</h3>
          <div className="space-y-4">
            {detail.per_question.map((q, i) => {
              const questionText = q.question_text ?? q.question ?? `Question ${i + 1}`;
              const answerText = q.answer_text ?? q.answer ?? "";
              const reasoning = q.score_reasoning ?? q.reasoning ?? "";
              const conf = confidenceLabel(q.confidence);

              return (
                <div key={i} className="border border-slate-100 rounded-lg p-4 space-y-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-slate-800">
                        Q{i + 1}: {questionText}
                      </p>
                      {q.topic && (
                        <p className="text-xs text-slate-400 capitalize mt-0.5">
                          Topic: {q.topic.replace(/_/g, " ")}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {q.score != null && <ScoreBadge score={q.score} size="sm" />}
                      <span className={`text-xs ${conf.color}`}>
                        {conf.text}
                      </span>
                    </div>
                  </div>

                  {answerText && (
                    <div className="bg-slate-50 rounded-lg p-3">
                      <p className="text-xs text-slate-400 mb-1 font-medium">Candidate Answer</p>
                      <p className="text-sm text-slate-700">{answerText}</p>
                    </div>
                  )}

                  {reasoning && (
                    <div className="bg-blue-50 rounded-lg p-3">
                      <p className="text-xs text-blue-400 mb-1 font-medium">AI Evaluation</p>
                      <p className="text-sm text-slate-700">{reasoning}</p>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Transcript */}
        {detail.transcript.length > 0 && (
          <TranscriptTimeline transcript={detail.transcript} />
        )}
      </div>
    </AdminGuard>
  );
}
```

- [ ] **Step 2: Test manually**

Run: `npm run dev`

Manual checks:
- Login as admin, go to History, click "View Analysis" on an interview
- Verify header card shows candidate info, score, recommendation
- Verify confidence metrics dashboard shows 3 cards
- Verify strengths/weaknesses display
- Verify topic scores with per-topic confidence labels
- Verify per-question breakdown with Q, answer, evaluation, score, confidence
- Verify transcript renders at bottom
- Verify "Back to History" link works
- Test with non-existent session ID — should show error
- Test mobile layout — should stack gracefully
- Login as candidate, try to access `/admin/analysis/some-id` — should redirect

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/admin/analysis/
git commit -m "feat: add post-interview analysis page with confidence metrics"
```

---

### Task 13: Frontend — Update Home Page CTA

**Files:**
- Modify: `frontend/src/app/page.tsx` (conditional CTA based on auth state)

- [ ] **Step 1: Update home page**

Replace `frontend/src/app/page.tsx`:

```tsx
"use client";

import Link from "next/link";
import { useAuth } from "@/contexts/AuthContext";

export default function HomePage() {
  const { user, isAdmin } = useAuth();

  return (
    <div className="flex flex-col items-center justify-center min-h-[70vh] text-center">
      <div className="max-w-2xl">
        <h1 className="text-4xl font-bold text-slate-900 mb-4">
          AI-Powered Technical Interviews
        </h1>
        <p className="text-lg text-slate-600 mb-8">
          Practice realistic technical interviews with instant AI feedback.
          Get scored on your answers and receive detailed improvement tips.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-10 text-left">
          <FeatureCard
            title="Smart Questions"
            description="Role-specific questions tailored to your experience level"
          />
          <FeatureCard
            title="AI Evaluation"
            description="Claude evaluates every answer with a score and reasoning"
          />
          <FeatureCard
            title="Detailed Report"
            description="Full scorecard with strengths, weaknesses, and recommendations"
          />
        </div>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
          <Link
            href={user ? "/interview/mode-select" : "/login"}
            className="inline-block bg-blue-600 hover:bg-blue-700 text-white font-semibold px-8 py-4 rounded-xl text-lg transition-colors"
          >
            Start an Interview
          </Link>
          {isAdmin && (
            <Link
              href="/admin/history"
              className="inline-block border border-slate-300 hover:bg-slate-50 text-slate-700 font-semibold px-8 py-4 rounded-xl text-lg transition-colors"
            >
              View History
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}

function FeatureCard({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="bg-white rounded-xl p-5 border border-slate-200 shadow-sm">
      <h3 className="font-semibold text-slate-900 mb-1">{title}</h3>
      <p className="text-sm text-slate-500">{description}</p>
    </div>
  );
}
```

Note: This removes emoji icons from FeatureCard (cleaner, more professional look) and adds a "View History" CTA for admin users. The "Start an Interview" button redirects to login if not authenticated.

- [ ] **Step 2: Test manually**

- Visit home page without login — "Start an Interview" links to `/login`
- Login as candidate — "Start an Interview" links to `/interview/mode-select`, no "View History" button
- Login as admin — both buttons visible

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/page.tsx
git commit -m "feat: update home page with auth-aware CTAs"
```

---

## Acceptance Criteria

1. **Navigation**
   - [ ] Top navbar displays brand, nav links, user info, and sign-out
   - [ ] Candidates see: Text Interview, Voice Interview
   - [ ] Admins see: Text Interview, Voice Interview, History
   - [ ] Active nav link is visually highlighted
   - [ ] Mobile: hamburger menu collapses nav links
   - [ ] Unauthenticated users see "Sign in" link

2. **Auth & Roles**
   - [ ] Login page with name input and role selection (candidate/admin)
   - [ ] Admin role requires correct passphrase
   - [ ] Auth state persists in localStorage across page reloads
   - [ ] Sign-out clears auth state
   - [ ] Admin pages redirect to `/login` if not authenticated
   - [ ] Admin pages redirect to `/` if authenticated as candidate
   - [ ] Backend admin endpoints return 401 without valid `X-Admin-Key` header

3. **History Page**
   - [ ] Table shows: candidate name, role, type (text/voice), score, recommendation, duration, date
   - [ ] Paginated (20 per page) with Previous/Next controls
   - [ ] Each row links to analysis page
   - [ ] Empty state shown when no interviews exist
   - [ ] Loading state shown while fetching
   - [ ] Error state shown on API failure

4. **Analysis Page**
   - [ ] Header: candidate name, role, level, duration, date, overall score, recommendation
   - [ ] Confidence metrics dashboard: 3 cards (transcription, Q&A extraction, answer evaluation)
   - [ ] Text-mode interviews show 100% for transcription and Q&A extraction (with explanation)
   - [ ] Strengths and weaknesses listed
   - [ ] Topic scores with per-topic confidence labels
   - [ ] Category scores shown when available (voice mode)
   - [ ] Per-question breakdown: question, answer, AI evaluation/reasoning, score, confidence level
   - [ ] Full transcript with copy/export
   - [ ] "Back to History" link

5. **Scoring & Confidence**
   - [ ] Text-mode per-answer confidence captured from LLM XML response
   - [ ] All completed text interviews saved to PostgreSQL
   - [ ] Voice interview reports include interview_type="voice"
   - [ ] Confidence values are real (from LLM/STT), not fabricated
   - [ ] No fake confidence numbers — text mode honestly shows 1.0 for transcription

6. **No Regressions**
   - [ ] Text interview flow works end-to-end (start → answer → report)
   - [ ] Voice interview flow unmodified
   - [ ] Existing `/report/[sessionId]` page still works
   - [ ] All existing backend tests pass

---

## Edge Cases & Risks

| Risk | Mitigation |
|------|------------|
| **PG not running** → text-mode report save fails silently | `save_report` already logs errors and returns `False`. Interview still completes via Redis. History page will be missing that interview. |
| **Old interviews in Redis without confidence** | `QuestionResult.confidence` defaults to `None`. Analysis page shows "N/A" for missing confidence. |
| **Admin passphrase is client-side only** | This is MVP auth. The real protection is the backend `X-Admin-Key` header. A determined user could bypass the frontend passphrase check but still can't call admin API endpoints. |
| **Text-mode `Evaluation` lacks category scores** | Analysis page conditionally renders category scores only when `category_scores` dict is non-empty. Text interviews simply don't show that section. |
| **Voice-mode `per_question` has different field names** | `InterviewDetail.per_question` type uses `question_text ?? question`, `answer_text ?? answer`, `score_reasoning ?? reasoning` fallback pattern. Analysis page handles both. |
| **Large transcript performance** | TranscriptTimeline already has `max-h-96 overflow-y-auto`. No change needed. |
| **localStorage not available (SSR)** | AuthProvider returns `null` until `useEffect` runs (client-side), preventing hydration mismatch. |
| **Concurrent text interview completions writing to PG** | `save_report` uses `ON CONFLICT (session_id) DO UPDATE`, so duplicate writes are safe. |

---

## Questions & Assumptions Needing Confirmation

1. **Admin passphrase approach**: The plan uses a simple client-side passphrase + backend API key. Is this acceptable for MVP, or do you want a proper username/password auth system with a users table? (The plan is designed to be extensible — AuthContext can be wired to a real auth backend later.)

2. **Home page emoji removal**: The plan removes emoji icons from feature cards for a cleaner SaaS look. Keep the emojis or remove them?

3. **`max-w-6xl` layout width**: The plan widens the main content from `max-w-4xl` to `max-w-6xl` so the history table has room. This affects all pages. Acceptable, or should only admin pages be wider?

4. **Text-mode confidence availability**: The LLM already returns a `<confidence>` field in its XML response for text mode, and `response_parser.py` extracts it. But the prompt doesn't explicitly instruct the LLM to produce accurate confidence values — it may be returning a fixed value or inconsistent numbers. Want to verify by checking a sample response, or add explicit confidence instructions to the system prompt?

5. **Existing interviews**: Interviews completed before this change won't be in PostgreSQL (they were Redis-only with 4hr TTL). The history page will only show interviews completed after deployment. Is this acceptable?

6. **Voice pipeline**: CLAUDE.md says "don't modify unless explicitly asked." This plan does NOT touch voice routers/WS/TTS/STT code. It only modifies `voice_evaluation.py` to populate new metric fields and set `interview_type="voice"`. Acceptable?
