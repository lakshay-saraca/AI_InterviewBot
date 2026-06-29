# Smarter Voice Silence Handling — Design

**Date:** 2026-06-25
**Status:** Approved
**Scope:** `backend/src/services/interview/voice_turn_processor.py` only (backend-only, no LLM calls, no frontend changes)

---

## Problem

In a voice interview, when the candidate stops speaking the AI appears to "just wait" silently. Two distinct defects cause this:

1. **Silent nudges.** A three-tier silence monitor already exists in `_silence_monitor` (`voice_turn_processor.py`). It emits `interviewer_prompt` / `silence_strike` JSON events carrying text, but the text is **never routed through TTS**. The candidate never *hears* "Are you still there?" — the prompt only appends to the persisted transcript.

2. **Auto-advance is a no-op.** At the final timeout the monitor only increments the `silence_strikes` counter and emits a `silence_strike` event with `action: "advance_question"`. It does **not** bump `current_question_idx`, speak the next question, or call the orchestrator. The frontend (`VoiceInterviewRoom.tsx`) has **no handler** for `silence_strike`. Result: after the final timeout the interview stalls silently with a counter bumped.

## Goal

When the candidate is silent, the AI should *audibly* check in ("Take your time…", "Are you still there? …"), and after continued silence should *actually* move the interview forward by speaking the next question — all deterministically (CLAUDE.md Rule 5: code handles deterministic transforms, not the LLM).

## Non-Goals

- No frontend changes. The frontend already buffers/plays TTS audio frames and renders `turn` events; speaking nudges and the next question reuses those existing paths.
- No LLM involvement in silence handling.
- No change to barge-in, debounce, STT-confidence, or evaluation logic.
- No change to the forward-only state machine semantics.

---

## Design

All changes are in `backend/src/services/interview/voice_turn_processor.py` and its module docstring.

### 1. Timing constants (more responsive)

```
SILENCE_PROMPT_SECS   = 8     # was 15 — first gentle nudge
SILENCE_CHECKIN_SECS  = 18    # was 30 — check-in nudge
SILENCE_STRIKE_SECS   = 30    # was 45 — strike + advance
```

The monitor preserves its single-coroutine sequential-sleep structure
(`sleep(8)` → nudge → `sleep(10)` → nudge → `sleep(12)` → advance), so the
absolute thresholds above are realized as successive relative sleeps.

### 2. Audible nudges — `_speak_silence_prompt(text)`

A new method on `VoiceTurnState` that voices a silence prompt:

- streams `text` through `self.tts.stream_sentence(...)` (the same TTS path
  `stream_response` uses), so the candidate hears it;
- sets `bot_speaking = True` for the duration and restores it after, so a
  candidate who speaks during the nudge triggers normal barge-in;
- emits the existing `interviewer_prompt` event with `type: "silence_prompt"`
  (frontend suppresses it from the live view by design) and appends the prompt
  to the transcript via `append_transcript_turn(..., entry_type="silence_prompt")`
  exactly as today;
- restores session state to `WAITING_FOR_CANDIDATE` afterward;
- **does NOT** restart the silence monitor. The single monitor coroutine keeps
  walking its ladder; reusing `stream_response` (which calls
  `_start_silence_monitor`) here would cancel the very coroutine that invoked it.

Spoken wording:

| Timeout | Spoken line |
|---------|-------------|
| 8s  | `Take your time — I'm here whenever you're ready.` |
| 18s | `Are you still there? Is everything okay, or are you running into any issues?` |

The 18s line satisfies the "are you facing an issue?" requirement.

### 3. Real auto-advance at the final timeout

Replace the dead counter-bump + event with deterministic progression. At 30s:

1. `increment_voice_field(session_id, "silence_strikes")` — kept; feeds the
   evaluation metrics (`silence_strikes`).
2. Speak a brief transition via `_speak_silence_prompt`:
   `No problem — let's move on to the next question.`
3. Advance deterministically (mirrors `run_llm_turn`'s advance branch, **no LLM
   call**):
   - load `questions` and `current_question_idx` from the Redis voice session;
   - `next_idx = current_idx + 1`; `set_voice_field("current_question_idx", next_idx)`;
     `set_voice_field("follow_up_count", 0)`;
   - if `next_idx >= len(questions)` → enter wrap-up via the orchestrator's
     `_enter_wrap_up(...)` (lazy import to avoid a circular import, matching the
     existing lazy `run_llm_turn` import pattern) and **speak** the returned
     invite;
   - else → append the next question to the transcript
     (`entry_type="question"`) and **speak** it, composed with resume-question
     framing via the orchestrator's `_compose_next_question(...)` so
     `resume_generated` questions keep their bridge line.
4. The spoken next question / wrap-up invite goes through `stream_response`
   (`signal_turn_end=True`), which sets `WAITING_FOR_CANDIDATE` and starts a
   **fresh** silence monitor for the new question.

**Self-cancel avoidance:** the advance work runs in its own task
(`asyncio.create_task(...)`), and the monitor coroutine returns immediately
after scheduling it. This prevents `stream_response`'s `_start_silence_monitor`
from cancelling the still-running monitor coroutine mid-await (which would cut
off the next question's audio).

### Barge-in / interplay (unchanged)

While any nudge or the advance line plays, `bot_speaking = True`. A candidate
who starts speaking triggers `speech_start` → `cancel_silence_monitor()` (kills
the whole ladder and the advance task path) plus normal barge-in in
`process_voice_turn`. No new barge-in code.

### Docstring

Update the module docstring's "Silence timeouts" block (currently 15/30/45) to
reflect 8/18/30 and the now-audible, now-advancing behavior.

---

## Data flow

```
WAITING_FOR_CANDIDATE
  └─ _silence_monitor (one coroutine)
       ├─ sleep 8s  → _speak_silence_prompt("Take your time …")        [TTS]
       ├─ sleep 10s → _speak_silence_prompt("Are you still there? …")  [TTS]
       └─ sleep 12s → silence_strikes++; create_task(_advance_after_silence)
                        ├─ _speak_silence_prompt("No problem — let's move on …")
                        ├─ bump current_question_idx (Redis)
                        ├─ next question? → stream_response(next_q text)  [TTS] → fresh monitor
                        └─ no more?       → _enter_wrap_up → stream_response(invite) [TTS]

speech_start at any point → cancel_silence_monitor() → ladder + advance abort
```

## Error handling

- `_speak_silence_prompt` swallows WS send failures the same way existing
  `_send_json` does; a failed TTS stream must not crash the monitor.
- The advance task wraps its body so a failure surfaces an `error` event and
  leaves state at `WAITING_FOR_CANDIDATE` rather than silently dying (Rule 9).
- Redis writes for `current_question_idx` / `follow_up_count` are followed by
  the existing serialization in `set_voice_field` (no new persistence path).

## Testing (Rule 7 — encode WHY)

In `backend/tests/test_voice_turn_processor.py` (match existing conventions):

1. **Nudges are spoken, not just emitted.** At 8s and 18s, assert the TTS
   stream is invoked with the expected wording — proves the candidate would
   *hear* the check-in (the actual bug). A test that only checked the JSON
   event would have passed against the broken code.
2. **Final timeout advances.** Assert `current_question_idx` increments and the
   next question's text is spoken — proves the interview actually progresses,
   not just that a counter moved.
3. **Final timeout at last question enters wrap-up.** Assert wrap-up invite is
   spoken and `interview_phase` becomes `wrap_up` — proves the end-of-bank path.
4. **`speech_start` mid-ladder cancels everything.** Assert no further nudge or
   advance fires after `cancel_silence_monitor()` — proves a candidate who
   resumes speaking isn't talked over by a pending nudge/advance.

---

## Files touched

- `backend/src/services/interview/voice_turn_processor.py` — constants, new
  `_speak_silence_prompt`, rewritten `_silence_monitor`, new advance task,
  docstring.
- `backend/tests/test_voice_turn_processor.py` — new/updated tests above.
