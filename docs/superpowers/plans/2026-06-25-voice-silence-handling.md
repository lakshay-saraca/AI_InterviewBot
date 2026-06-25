# Smarter Voice Silence Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a voice candidate goes silent, the AI audibly checks in ("Take your time…", "Are you still there?…") and, after continued silence, deterministically advances to the next question instead of stalling.

**Architecture:** All changes live in `backend/src/services/interview/voice_turn_processor.py`. The existing single-coroutine silence monitor is upgraded so its nudges stream through TTS (the same path every other turn uses) and its final tier spawns a deterministic advance task — no LLM call, no frontend changes (the frontend already plays TTS frames and renders `turn` events).

**Tech Stack:** Python, asyncio, FastAPI WebSocket, ElevenLabs TTS client, pytest/pytest-asyncio.

**Reference spec:** `docs/superpowers/specs/2026-06-25-voice-silence-handling-design.md`

**Test invocation note:** Run only the target file — `cd backend && python -m pytest tests/test_voice_turn_processor.py -v`. (The full suite is known to hang on orphaned aiosqlite threads after passing; the single file avoids that and runs in well under a second.)

---

## File Structure

- **Modify:** `backend/src/services/interview/voice_turn_processor.py`
  - Timing constants `SILENCE_PROMPT_SECS` / `SILENCE_CHECKIN_SECS` / `SILENCE_STRIKE_SECS` → 8 / 18 / 30.
  - New spoken-wording constants.
  - New top-level imports: `json`, `Question`.
  - New method `VoiceTurnState._speak_silence_prompt(text)` — voices a nudge via TTS without restarting the monitor.
  - New method `VoiceTurnState._advance_after_silence()` — deterministically advances the question (or enters wrap-up).
  - Rewritten `VoiceTurnState._silence_monitor()` — speaks the two nudges, then increments the strike and spawns the advance task.
  - Updated module docstring.
- **Modify (add tests):** `backend/tests/test_voice_turn_processor.py`

---

### Task 1: Audible nudges (timing + `_speak_silence_prompt` + monitor rewrite)

**Files:**
- Modify: `backend/src/services/interview/voice_turn_processor.py`
- Test: `backend/tests/test_voice_turn_processor.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_voice_turn_processor.py`:

```python
import src.services.interview.voice_turn_processor as vtp
from tests.conftest import make_question
from src.services.audio.voice_session import increment_voice_field


class _RecordingTTS:
    """Captures each sentence handed to TTS so tests can assert what was spoken."""

    def __init__(self) -> None:
        self.spoken: list[str] = []

    async def stream_sentence(self, text: str, ws) -> None:
        self.spoken.append(text)


@pytest.mark.asyncio
async def test_silence_monitor_speaks_both_nudges(fake_ws, monkeypatch):
    """The check-ins must be SPOKEN (streamed to TTS), not just emitted as JSON.
    The original bug was that prompts were sent as text-only events the candidate
    never heard — a test asserting only the JSON event would have passed against it."""
    monkeypatch.setattr(vtp, "SILENCE_PROMPT_SECS", 0.01)
    monkeypatch.setattr(vtp, "SILENCE_CHECKIN_SECS", 0.02)
    monkeypatch.setattr(vtp, "SILENCE_STRIKE_SECS", 100)  # never reach advance here

    seed_voice_session("s-nudge", [make_question("q1", "python"), make_question("q2", "sql")])
    state = vtp.VoiceTurnState("s-nudge", fake_ws)
    tts = _RecordingTTS()
    state.tts = tts  # type: ignore[assignment]

    state._start_silence_monitor()
    await asyncio.sleep(0.1)
    state.cancel_silence_monitor()

    joined = " ".join(tts.spoken)
    assert "Take your time" in joined, "first nudge was not spoken"
    assert "Are you still there" in joined, "second nudge was not spoken"


@pytest.mark.asyncio
async def test_speech_start_cancels_pending_nudges(fake_ws, monkeypatch):
    """A candidate who resumes speaking mid-ladder must not be talked over by a
    queued nudge or advance — cancel_silence_monitor stops the rest of the ladder."""
    monkeypatch.setattr(vtp, "SILENCE_PROMPT_SECS", 0.01)
    monkeypatch.setattr(vtp, "SILENCE_CHECKIN_SECS", 0.05)
    monkeypatch.setattr(vtp, "SILENCE_STRIKE_SECS", 0.09)

    seed_voice_session("s-cancel", [make_question("q1", "python"), make_question("q2", "sql")])
    state = vtp.VoiceTurnState("s-cancel", fake_ws)
    tts = _RecordingTTS()
    state.tts = tts  # type: ignore[assignment]

    state._start_silence_monitor()
    await asyncio.sleep(0.02)   # first nudge has fired, second has not
    state.cancel_silence_monitor()
    await asyncio.sleep(0.1)    # give any (wrongly) pending nudge time to fire

    joined = " ".join(tts.spoken)
    assert "Take your time" in joined
    assert "Are you still there" not in joined, "second nudge fired after cancel"
    assert int(get_voice_session("s-cancel")["current_question_idx"]) == 0, "advanced after cancel"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_voice_turn_processor.py::test_silence_monitor_speaks_both_nudges tests/test_voice_turn_processor.py::test_speech_start_cancels_pending_nudges -v`
Expected: FAIL — the current `_silence_monitor` only sends JSON `interviewer_prompt` events, so `tts.spoken` is empty and `"Take your time"` is not found.

- [ ] **Step 3: Update timing constants and add wording constants**

In `voice_turn_processor.py`, replace the existing constants block:

```python
SILENCE_PROMPT_SECS = 15
SILENCE_CHECKIN_SECS = 30
SILENCE_STRIKE_SECS = 45
COMPLETION_WAIT_TIMEOUT_SECS = 90.0
COMPLETION_POLL_INTERVAL_SECS = 0.25
```

with:

```python
SILENCE_PROMPT_SECS = 8     # first gentle nudge
SILENCE_CHECKIN_SECS = 18   # "are you still there / facing an issue" check-in
SILENCE_STRIKE_SECS = 30    # strike + advance to next question
COMPLETION_WAIT_TIMEOUT_SECS = 90.0
COMPLETION_POLL_INTERVAL_SECS = 0.25

# Spoken silence check-ins (deterministic — never LLM-generated).
SILENCE_PROMPT_1 = "Take your time — I'm here whenever you're ready."
SILENCE_PROMPT_2 = "Are you still there? Is everything okay, or are you running into any issues?"
SILENCE_ADVANCE = "No problem — let's move on to the next question."
```

- [ ] **Step 4: Add the `json` and `Question` imports**

In `voice_turn_processor.py`, change the top imports. Replace:

```python
import asyncio
import logging
from typing import Any, Optional
```

with:

```python
import asyncio
import json
import logging
from typing import Any, Optional
```

and add, after the existing `from src.services.audio.voice_session import (...)` block:

```python
from src.types.interview import Question
```

- [ ] **Step 5: Add the `_speak_silence_prompt` method**

In class `VoiceTurnState`, add this method (place it directly above `_start_silence_monitor`):

```python
    async def _speak_silence_prompt(self, text: str) -> None:
        """Voice a silence check-in through TTS.

        Streams via the same TTS path as a normal turn so the candidate actually
        HEARS the prompt. Deliberately does NOT restart the silence monitor —
        the single monitor coroutine keeps walking its ladder, and reusing
        stream_response (which restarts the monitor) would cancel the very
        coroutine that called this.
        """
        sentences = split_into_sentences(text)
        if not sentences:
            return

        self.bot_speaking = True
        set_voice_field(self.session_id, "state", "BOT_SPEAKING")
        await _send_json(self.ws, {
            "event": "interviewer_prompt",
            "text": text,
            "type": "silence_prompt",
        })
        append_transcript_turn(self.session_id, "bot", text, entry_type="silence_prompt")
        try:
            for sentence in sentences:
                await self.tts.stream_sentence(sentence, self.ws)
        finally:
            self.bot_speaking = False
            set_voice_field(self.session_id, "state", "WAITING_FOR_CANDIDATE")
```

- [ ] **Step 6: Rewrite `_silence_monitor` to speak the nudges and spawn the advance**

Replace the entire existing `_silence_monitor` method:

```python
    async def _silence_monitor(self) -> None:
        try:
            await asyncio.sleep(SILENCE_PROMPT_SECS)
            await self._speak_silence_prompt(SILENCE_PROMPT_1)

            await asyncio.sleep(SILENCE_CHECKIN_SECS - SILENCE_PROMPT_SECS)
            await self._speak_silence_prompt(SILENCE_PROMPT_2)

            await asyncio.sleep(SILENCE_STRIKE_SECS - SILENCE_CHECKIN_SECS)
            strikes = increment_voice_field(self.session_id, "silence_strikes")
            logger.info("Silence strike %d session=%s", strikes, self.session_id)
            await _send_json(self.ws, {
                "event": "silence_strike",
                "count": strikes,
                "action": "advance_question",
            })
            # Run the advance in its own task so this coroutine returns cleanly:
            # the advance's stream_response starts a fresh silence monitor, which
            # would otherwise cancel this still-running coroutine mid-await and
            # cut off the next question's audio.
            asyncio.create_task(self._advance_after_silence())
        except asyncio.CancelledError:
            pass
```

(The `_advance_after_silence` method it references is added in Task 2. Until then this references an undefined method — that's expected; Task 1's two tests never reach the strike tier because they cancel first or set `SILENCE_STRIKE_SECS=100`.)

- [ ] **Step 7: Run Task 1 tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_voice_turn_processor.py::test_silence_monitor_speaks_both_nudges tests/test_voice_turn_processor.py::test_speech_start_cancels_pending_nudges -v`
Expected: PASS (2 passed).

- [ ] **Step 8: Commit**

```bash
git add backend/src/services/interview/voice_turn_processor.py backend/tests/test_voice_turn_processor.py
git commit -m "feat(voice): speak silence check-ins through TTS"
```

---

### Task 2: Deterministic auto-advance on the final timeout

**Files:**
- Modify: `backend/src/services/interview/voice_turn_processor.py`
- Test: `backend/tests/test_voice_turn_processor.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_voice_turn_processor.py`:

```python
@pytest.mark.asyncio
async def test_advance_after_silence_moves_to_next_question(fake_ws):
    """Continued silence must actually progress the interview: bump the question
    index and SPEAK the next question. A test that only checked silence_strikes
    would have passed against the old no-op."""
    seed_voice_session("s-adv", [make_question("q1", "python"), make_question("q2", "sql")])
    state = vtp.VoiceTurnState("s-adv", fake_ws)
    tts = _RecordingTTS()
    state.tts = tts  # type: ignore[assignment]

    await state._advance_after_silence()
    state.cancel_silence_monitor()  # stop the fresh monitor stream_response started

    assert int(get_voice_session("s-adv")["current_question_idx"]) == 1, "did not advance"
    assert "sql" in " ".join(tts.spoken).lower(), "next question was not spoken"


@pytest.mark.asyncio
async def test_advance_after_silence_enters_wrap_up_at_last_question(fake_ws):
    """When the last question times out, the AI wraps up instead of advancing into
    an empty question list."""
    seed_voice_session("s-wrap", [make_question("q1", "python")])
    state = vtp.VoiceTurnState("s-wrap", fake_ws)
    tts = _RecordingTTS()
    state.tts = tts  # type: ignore[assignment]

    await state._advance_after_silence()
    state.cancel_silence_monitor()

    assert get_voice_session("s-wrap")["interview_phase"] == "wrap_up"
    joined = " ".join(tts.spoken).lower()
    assert "anything you'd like to ask" in joined, "wrap-up invite was not spoken"


@pytest.mark.asyncio
async def test_silence_monitor_triggers_advance_and_strike(fake_ws, monkeypatch):
    """The monitor's final tier must increment silence_strikes AND hand off to the
    advance path — proving the strike counter and progression are wired together."""
    monkeypatch.setattr(vtp, "SILENCE_PROMPT_SECS", 0.01)
    monkeypatch.setattr(vtp, "SILENCE_CHECKIN_SECS", 0.02)
    monkeypatch.setattr(vtp, "SILENCE_STRIKE_SECS", 0.03)

    seed_voice_session("s-trig", [make_question("q1", "python"), make_question("q2", "sql")])
    state = vtp.VoiceTurnState("s-trig", fake_ws)
    tts = _RecordingTTS()
    state.tts = tts  # type: ignore[assignment]

    advanced = asyncio.Event()

    async def fake_advance() -> None:
        advanced.set()

    state._advance_after_silence = fake_advance  # type: ignore[method-assign]

    state._start_silence_monitor()
    await asyncio.wait_for(advanced.wait(), timeout=1)
    state.cancel_silence_monitor()

    assert int(get_voice_session("s-trig")["silence_strikes"]) == 1
    assert any(m.get("event") == "silence_strike" for m in fake_ws.json_messages)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_voice_turn_processor.py::test_advance_after_silence_moves_to_next_question tests/test_voice_turn_processor.py::test_advance_after_silence_enters_wrap_up_at_last_question tests/test_voice_turn_processor.py::test_silence_monitor_triggers_advance_and_strike -v`
Expected: FAIL — `_advance_after_silence` does not exist yet (`AttributeError`).

- [ ] **Step 3: Add the `_advance_after_silence` method**

In class `VoiceTurnState`, add this method directly below `_speak_silence_prompt`:

```python
    async def _advance_after_silence(self) -> None:
        """Deterministically advance to the next question after the candidate
        stays silent through the full nudge ladder. No LLM call — mirrors the
        advance branch of run_llm_turn using code only.
        """
        try:
            voice_data = get_voice_session(self.session_id)
            if voice_data is None:
                return

            questions = [Question(**q) for q in json.loads(voice_data.get("questions", "[]"))]
            current_idx = int(voice_data.get("current_question_idx", 0))
            next_idx = current_idx + 1
            set_voice_field(self.session_id, "current_question_idx", next_idx)
            set_voice_field(self.session_id, "follow_up_count", 0)

            # Lazy import: voice_llm_orchestrator imports this module's siblings;
            # importing it at module load risks a circular import (same pattern as
            # the lazy run_llm_turn import in process_voice_turn).
            from src.services.interview.voice_llm_orchestrator import (
                _enter_wrap_up,
                _compose_next_question,
            )

            if next_idx >= len(questions):
                invite = _enter_wrap_up(self.session_id, voice_data, lead_in=SILENCE_ADVANCE)
                await self.stream_response(invite, entry_type="wrap_up_invite")
                return

            next_q = questions[next_idx]
            append_transcript_turn(
                self.session_id, "bot", next_q.question_text, entry_type="question"
            )
            spoken = _compose_next_question(SILENCE_ADVANCE, next_q)
            await self.stream_response(spoken)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Silence advance failed session=%s: %s", self.session_id, exc)
            await _send_json(self.ws, {
                "event": "error",
                "message": "I had trouble moving to the next question.",
            })
            set_voice_field(self.session_id, "state", "WAITING_FOR_CANDIDATE")
```

- [ ] **Step 4: Run Task 2 tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_voice_turn_processor.py::test_advance_after_silence_moves_to_next_question tests/test_voice_turn_processor.py::test_advance_after_silence_enters_wrap_up_at_last_question tests/test_voice_turn_processor.py::test_silence_monitor_triggers_advance_and_strike -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the full file to confirm no regressions**

Run: `cd backend && python -m pytest tests/test_voice_turn_processor.py -v`
Expected: PASS — all tests in the file (the 2 original + 5 new) pass.

- [ ] **Step 6: Commit**

```bash
git add backend/src/services/interview/voice_turn_processor.py backend/tests/test_voice_turn_processor.py
git commit -m "feat(voice): advance to next question after sustained silence"
```

---

### Task 3: Update the module docstring

**Files:**
- Modify: `backend/src/services/interview/voice_turn_processor.py:10-13`

- [ ] **Step 1: Update the "Silence timeouts" docstring block**

Replace these lines in the module docstring:

```
Silence timeouts (managed via _silence_monitor):
  15s  → gentle prompt
  30s  → "Are you still there?"
  45s  → silence_strike++, advance question
```

with:

```
Silence timeouts (managed via _silence_monitor, all spoken via TTS):
  8s   → gentle nudge ("Take your time…")
  18s  → check-in ("Are you still there? … running into any issues?")
  30s  → silence_strike++, then deterministically advance to the next question
         (or enter wrap-up if none remain) — no LLM call
```

- [ ] **Step 2: Run the file once more to confirm nothing broke**

Run: `cd backend && python -m pytest tests/test_voice_turn_processor.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/src/services/interview/voice_turn_processor.py
git commit -m "docs(voice): update silence-monitor docstring for new behavior"
```

---

## Self-Review

**Spec coverage:**
- Timing 8/18/30 → Task 1 Step 3. ✓
- Audible nudges via `_speak_silence_prompt` → Task 1 Steps 5–6. ✓
- Real auto-advance (bump idx, speak next question, wrap-up fallback) → Task 2 Step 3. ✓
- Self-cancel avoidance via separate task → Task 1 Step 6 + Task 2 Step 3. ✓
- Barge-in interplay unchanged (no new code) → relies on existing `cancel_silence_monitor`, covered by `test_speech_start_cancels_pending_nudges`. ✓
- Tests for all four spec scenarios → Tasks 1–2 (nudges spoken; advance; wrap-up; cancel). ✓
- Docstring update → Task 3. ✓

**Placeholder scan:** No TBD/TODO/"add error handling" placeholders — every code step shows full code. ✓

**Type/name consistency:** `_speak_silence_prompt`, `_advance_after_silence`, `_silence_monitor`, `SILENCE_PROMPT_1/2`, `SILENCE_ADVANCE`, `_enter_wrap_up(session_id, voice_data, lead_in=...)`, `_compose_next_question(spoken, next_q)` used consistently across tasks and match the existing orchestrator signatures verified in `voice_llm_orchestrator.py`. ✓
