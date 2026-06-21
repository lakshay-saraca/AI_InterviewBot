# Grill Notes — Voice JD/Resume Interview Redesign

Working doc for the grill-me session. Records decisions as we resolve them so the
thread survives summarization. Source request: fix the JD-voice interview output —
deterministic intro, admin-selectable question count, resume questions, difficulty
ramp, proper closing.

---

## 2026-06-21 — Checkpoint 1

### Decisions resolved
1. **Counting model** — The admin's number = **technical questions only** (5–10,
   default 5). Behavioral (disagreement), project deep-dive, and resume questions
   are **additive**, outside that count. Breaks current `plan_math` where
   `RESERVED_SLOTS = total − 2`.
2. **Resume questions source** — There is NO resume anywhere in the voice flow
   today (the file field is the JD). To add resume questions we add a resume
   upload + a resume-analysis step (reuse `jd_extract` for PDF/DOCX → text; the
   resume→questions LLM step is net-new). Resume is **optional** — slots omitted
   when absent.
3. **Opening sequence** — Root cause of "question in the introduction" found:
   `voice_session.py:74` glues `intro_text + first_q_text` into ONE bot turn
   tagged `type:"question"`. Fix = split into 3 turns: (1) deterministic intro
   STATEMENT, no question; (2) deterministic merged ease-in = "whenever you're
   ready, let's start with…" + an EASY first question; (3) Q2 onward. No real
   gated "are you ready?" pause (avoids an extra round-trip).

4. **Document model = Resume primary + JD optional (decision C).** Resume is the
   primary upload (drives personalized questions, optional). JD becomes an
   OPTIONAL second upload that tops up role-specific technical questions. The
   question bank (role dropdown + level) is the always-on technical base. The JD
   is NOT deleted — it's demoted to optional filler. Confirmed user's instinct:
   core technical questions already come from the dropdown via the bank
   (`question_bank.py:39-56`); JD only added extra on top.

### Known constraint (fail-loud, not hidden)
- **Bank is tiny: 15 questions total; only 5 eligible for `junior`** (3 junior +
  2 "all"; mid/senior/staff filtered out for a junior candidate). So
  junior + no JD + count>5 → InsufficientQuestionsError or repeats.
  AGREED handling: when no JD uploaded, **cap selectable count to bank capacity
  for that level** (junior→5); full 5–10 unlocked once a JD is attached.
  Expanding `questions.json` is noted as separate future work.
- mid level has 11 eligible → 10 is fine there.

### Open branches
- Count math — rewrite `plan_math` for the additive model + the no-JD cap.
- Resume analysis — new LLM step mirroring `analyze_jd`; what fields/questions.
- Admin count selector UI + the no-JD cap behavior.

### Next questions
- Resume analysis output shape (last big unknown).

---

## 2026-06-21 — Checkpoint 2

### Decisions resolved (continued)
5. **Difficulty ramp** — strictly the **first two technical slots are the two
   easiest eligible** questions (prefer `easy`, then `junior`-level); the rest
   keep current ordering. NOT a gradual whole-interview ramp. The Q3 ease-in turn
   uses slot 1. Resume questions are **medium**, placed after the easy openers.
6. **Closing** — Root cause of "ends immediately": the tested **WRAP_UP outro is
   wired into the TEXT flow only** (`interview.py:161-209`); the voice
   orchestrator returns `COMPLETION_MESSAGE` + triggers eval instantly
   (`voice_llm_orchestrator.py:106,183,210`). FIX = **port the full WRAP_UP outro
   into the voice orchestrator**, 3 beats: (1) deterministic wind-down + "any
   questions for me about the role/team?"; (2) candidate Q&A via existing
   `outro.answer_candidate_question`, cap `MAX_OUTRO_QUESTIONS=3`, JD-context only,
   recruiter-fallback; (3) deterministic next-steps + warm sign-off → THEN eval.

### Canonical candidate-experienced sequence (assembled from decisions 1–6)
1. Intro STATEMENT (deterministic, no question)
2. Ease-in turn = "whenever you're ready…" + EASY Q1
3. EASY Q2
4. Remaining technical (bank core + JD questions if JD uploaded), medium+
5. Resume questions (medium) interleaved in the middle
6. Behavioral (disagreement) — fixed
7. Project deep-dive (proud project) — fixed
8. WRAP_UP outro: wind-down → candidate Q&A (≤3) → next-steps sign-off
9. Evaluation

### Next questions
- Resume analysis output shape (extract what; how many Qs; PII guard; skills merge).

---

## 2026-06-21 — FINAL DESIGN (stands alone as the spec)

Goal: fix the admin-triggered voice interview (`/voice/session/start-from-jd`) so
it opens deterministically, is resume-personalized, lets the admin choose how many
technical questions, ramps difficulty for juniors, and closes properly instead of
cutting to evaluation. All work lives in the voice pipeline (explicitly authorized
by the user despite the CLAUDE.md "don't touch" default).

### 1. Documents & inputs (form + endpoint)
- **Resume upload** — PRIMARY, OPTIONAL. Drives personalized questions + skills.
- **JD upload** — OPTIONAL filler. Adds role-specific technical questions + skills.
- **Role dropdown + experience level** — always-on; drive bank question selection.
- **Question-count selector** — NEW. Min 5, max 10, default 5. Counts TECHNICAL
  questions only.
- Endpoint route name kept (`/voice/session/start-from-jd`); form RELABELED
  (resume first, JD second, + count selector). Reuse `jd_extract` (PDF/DOCX→text)
  for the resume too.

### 2. Counting model (additive)
- Admin's number N (5–10) = **technical questions only**.
- Behavioral (disagreement), project deep-dive, and the 2 resume questions are
  **ADDITIVE** — they sit OUTSIDE N.
- Rewrite `plan_math`: drop `RESERVED_SLOTS = total − 2`. New total session =
  N technical + 2 resume (if resume) + behavioral + project.
- When JD uploaded: split N between bank-core and JD questions via
  **`core_ratio = 0.7`** (~70% bank / 30% JD).
- When NO JD: all N from the bank.

### 3. Bank capacity guard (fail-loud)
- Bank = 15 questions total; **junior candidate has only 5 eligible** (3 junior +
  2 "all"). So junior + no JD caps technical at 5.
- Behavior: when no JD is uploaded, **cap the selectable count to the level's bank
  capacity** (junior→5); unlock full 5–10 once a JD is attached.
- Expanding `questions.json` = separate future work, NOT in this change.

### 4. Resume analysis (NEW LLM step, mirrors `analyze_jd`)
- Extract `skills[]` (merged with JD skills — union — to feed the bank) +
  `experiences[]` (recent roles/projects the candidate can speak to).
- Generate **exactly 2** resume questions (fixed), difficulty **medium**.
- PII guard: mirror the JD prompt prohibition (never family/age/gender/nationality/
  religion/etc.); reference work/projects ONLY (same posture as warmup whitelist).
- Runs at session creation, frozen into the plan. Omitted entirely if no resume.

### 5. Opening sequence (fixes intro+Q1 glue at `voice_session.py:74`)
Split the single glued opening turn into THREE turns:
1. Intro STATEMENT — deterministic, NO question. Also fix `generate_introduction`
   text (remove the false "after a quick warm-up" promise).
2. Ease-in turn — deterministic "whenever you're ready, let's start with…" +
   EASY Q1 (merged "are you ready", no separate gated pause).
3. EASY Q2, then the rest.

### 6. Difficulty ramp
- Strictly the **first two technical slots = the two easiest eligible** questions
  (prefer `easy`, then `junior`-level). Rest keep current ordering. NOT a gradual
  whole-interview ramp.

### 7. Closing (port WRAP_UP outro into voice)
- The tested WRAP_UP outro exists in the TEXT flow only (`interview.py:161-209`);
  voice just returns `COMPLETION_MESSAGE` + evaluates instantly. Port all 3 beats
  into `voice_llm_orchestrator`:
  1. Deterministic wind-down + "any questions for me about the role/team?"
  2. Candidate Q&A via `outro.answer_candidate_question`, cap
     `MAX_OUTRO_QUESTIONS=3`, answered from job context, recruiter-fallback.
  3. Deterministic next-steps + warm sign-off → THEN trigger evaluation.

### Canonical candidate-experienced sequence
intro statement → ease-in + EASY Q1 → EASY Q2 → remaining technical (bank +
JD-if-present) → 2 resume questions (medium) → behavioral (disagreement) →
project deep-dive → WRAP_UP outro (wind-down → candidate Q&A ≤3 → sign-off) →
evaluation.

### Files in scope (anticipated)
- `routes/voice_api.py` — accept resume + count; build plan; (no JD required).
- `services/llm/resume_analysis.py` (NEW) + `prompts/resume_analysis_prompt.txt`
  (NEW).
- `services/interview/plan_math.py` — additive rewrite + no-JD cap.
- `services/interview/plan_builder.py` — resume slots, difficulty ordering,
  optional JD.
- `services/interview/special_questions.py` — resume question builder.
- `services/audio/voice_session.py:74` — split intro/ease-in/Q1 seeding.
- `services/interview/warmup.py` — intro text fix; ease-in builder.
- `services/interview/voice_llm_orchestrator.py` — WRAP_UP outro port.
- `services/interview/voice_turn_processor.py` — outro turn handling.
- `frontend/.../interview/voice/start/page.tsx` + `services/voice-api.ts` — resume
  field, count selector, relabel.
- Tests across all of the above (TDD; tests encode WHY per CLAUDE.md rule 7).

### Open items deferred (NOT in this change)
- Expanding `questions.json` for deeper junior/mid coverage.
- Any change to the text/config flow (this is voice-only).
