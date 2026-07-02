"""Tests for turn-taking: debounce timing, semantic detection, and control handling.

Each test encodes WHY the behavior matters, not just WHAT it does.
"""

import asyncio
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import FakeWebSocket, make_question, seed_voice_session

from src.routes.voice_ws import (
    DEBOUNCE_COMPLETE_SECS,
    DEBOUNCE_INCOMPLETE_SECS,
    DEBOUNCE_SECS,
    STT_LOW_CONFIDENCE,
    _handle_wait_request,
    _handle_control,
    _looks_complete,
    _looks_incomplete,
    _looks_wait_request,
    _speech_end_should_flush,
)
from src.services.audio.voice_session import get_voice_session, set_voice_field


# ---- Unit tests for semantic detection ----


class TestLooksComplete:
    """Completion phrases must be reliably detected — false negatives mean
    the bot waits the full 3.7s after the user already signaled they're done."""

    def test_explicit_phrases(self):
        assert _looks_complete("I think Python is great. That's my answer")
        assert _looks_complete("I used decorators for that. That's all")
        assert _looks_complete("that's it")
        assert _looks_complete("Yeah that's it")
        assert _looks_complete("I don't have anything else")
        assert _looks_complete("Sorry I may not know")
        assert _looks_complete("That is what I think")

    def test_phrase_in_last_60_chars(self):
        long_text = "x " * 40 + "That's my answer"
        assert _looks_complete(long_text)

    def test_normal_speech_not_detected(self):
        assert not _looks_complete("I think Python is a great language")
        assert not _looks_complete("I used decorators and context managers")
        assert not _looks_complete("The answer depends on the use case")
        assert not _looks_complete("")

    def test_case_insensitive(self):
        assert _looks_complete("THAT'S MY ANSWER")
        assert _looks_complete("That's All")


class TestLooksIncomplete:
    """Trailing conjunctions/prepositions mean the speaker was mid-thought.
    Flushing here produces an incoherent partial answer that gets a bad score."""

    def test_trailing_conjunctions(self):
        assert _looks_incomplete("The reason I chose Python is because")
        assert _looks_incomplete("I implemented it using and")
        assert _looks_incomplete("We needed this feature but")
        assert _looks_incomplete("I think we should use the")

    def test_complete_sentences_not_detected(self):
        assert not _looks_incomplete("I finished the project")
        assert not _looks_incomplete("That's all")
        assert not _looks_incomplete("Python is great for backend work")

    def test_strips_trailing_punctuation(self):
        assert _looks_incomplete("The reason is because,")
        assert _looks_incomplete("I used it for.")

    def test_empty_text(self):
        assert not _looks_incomplete("")


class TestLooksWaitRequest:
    """Explicit wait requests must not be treated as completed answers."""

    def test_transcript_wait_request_is_detected(self):
        assert _looks_wait_request(
            "Yeah. Give me twenty five seconds to form my answer."
        )

    def test_common_wait_phrases_are_detected(self):
        assert _looks_wait_request("Let me think for a moment.")
        assert _looks_wait_request("Can I have 20 seconds?")
        assert _looks_wait_request("I need some time to structure this.")
        assert _looks_wait_request("Hold on, I am thinking.")

    def test_answer_about_waiting_is_not_detected(self):
        assert not _looks_wait_request("The fixture had to wait for the mold to cool.")
        assert not _looks_wait_request("We reduced the cycle time by twenty seconds.")


# ---- Integration tests for debounce and control ----


@pytest.mark.asyncio
async def test_speech_start_cancels_debounce(fake_ws: FakeWebSocket):
    """If the candidate resumes speaking during the debounce window, the
    partial answer must not be flushed. Without this, the backend races:
    the flush fires on stale partial text while the user is still talking."""
    session_id = "s-cancel-debounce"
    seed_voice_session(session_id, [make_question("q1", "python")])

    debounce_task: list[Optional[asyncio.Task]] = [None]
    flushed = {"called": False}

    async def fake_flush():
        await asyncio.sleep(DEBOUNCE_SECS)
        flushed["called"] = True

    debounce_task[0] = asyncio.create_task(fake_flush())

    await _handle_control(
        fake_ws, session_id,
        {"event": "speech_start"},
        debounce_task,
    )

    # Let the event loop process the cancellation
    await asyncio.sleep(0.05)

    assert debounce_task[0].cancelled(), \
        "Debounce task should be cancelled when user resumes speaking"
    assert not flushed["called"], \
        "Debounce flush ran despite speech_start cancellation"


@pytest.mark.asyncio
async def test_speech_end_does_not_set_processing(fake_ws: FakeWebSocket):
    """Browser VAD fires speech_end on short pauses. If it triggers PROCESSING,
    the state machine gets confused during mid-answer pauses. Only the debounce
    flush should transition to PROCESSING."""
    session_id = "s-no-processing"
    seed_voice_session(session_id, [make_question("q1", "python")])
    set_voice_field(session_id, "state", "CANDIDATE_SPEAKING")

    await _handle_control(fake_ws, session_id, {"event": "speech_end"})

    session = get_voice_session(session_id)
    assert session["state"] != "PROCESSING", \
        "speech_end should not set state to PROCESSING"


@pytest.mark.asyncio
async def test_speech_end_flushes_buffered_transcript_without_waiting_for_more_audio(
    fake_ws: FakeWebSocket,
):
    """When browser VAD reports end-of-speech, any buffered transcript must be
    handed off to the turn processor. Otherwise the bot waits forever if
    Deepgram does not emit another final event until the candidate speaks again.
    """
    session_id = "s-speech-end-flush"
    seed_voice_session(session_id, [make_question("q1", "python")])
    set_voice_field(session_id, "state", "CANDIDATE_SPEAKING")

    flushed = {"called": False}

    async def flush_accumulated_now():
        flushed["called"] = True

    await _handle_control(
        fake_ws,
        session_id,
        {"event": "speech_end"},
        [None],
        flush_accumulated_now,
    )

    assert flushed["called"], (
        "speech_end must flush buffered transcript; waiting only for a later "
        "Deepgram final event strands the turn until the candidate speaks again"
    )
    session = get_voice_session(session_id)
    assert session["state"] != "PROCESSING", (
        "speech_end itself should delegate to the flush path, not directly set PROCESSING"
    )


@pytest.mark.asyncio
async def test_speech_start_cancels_silence_monitor(fake_ws: FakeWebSocket):
    """If the silence monitor runs while the user is actively speaking, it
    sends a 'Take your time' prompt mid-answer — confusing and disruptive."""
    session_id = "s-cancel-silence"
    seed_voice_session(session_id, [make_question("q1", "python")])

    from src.services.interview.voice_turn_processor import get_or_create_turn_state
    turn_state = get_or_create_turn_state(session_id, fake_ws)
    turn_state._start_silence_monitor()

    assert turn_state._silence_task is not None

    await _handle_control(
        fake_ws, session_id,
        {"event": "speech_start"},
        [None],
    )

    assert turn_state._silence_task is None, \
        "Silence monitor should be cancelled when user starts speaking"


@pytest.mark.asyncio
async def test_transcript_activity_cancels_silence_monitor(fake_ws: FakeWebSocket):
    """A Deepgram transcript proves the candidate is speaking, so the silence
    ladder must stop — even when the browser VAD never sent speech_start.

    This is the regression guard for the reported bug: the candidate spoke for
    ~12s but the energy-fallback VAD missed speech_start, so the monitor was never
    cancelled and the bot interrupted with 'Are you still there?'. _note_candidate_
    activity must cancel the monitor on transcript regardless of the VAD signal.
    """
    session_id = "s-transcript-cancels-silence"
    seed_voice_session(session_id, [make_question("q1", "python")])

    from src.routes.voice_ws import _note_candidate_activity
    from src.services.interview.voice_turn_processor import get_or_create_turn_state

    turn_state = get_or_create_turn_state(session_id, fake_ws)
    turn_state._start_silence_monitor()
    assert turn_state._silence_task is not None

    # Simulate Deepgram returning an interim partial while the candidate talks,
    # with NO preceding speech_start control frame (the failure condition).
    _note_candidate_activity(session_id, fake_ws)

    assert turn_state._silence_task is None, (
        "silence monitor must be cancelled the moment a transcript arrives — "
        "otherwise the bot nags over a candidate the client VAD failed to detect"
    )


@pytest.mark.asyncio
async def test_transcript_during_bot_speech_triggers_barge_in(fake_ws: FakeWebSocket):
    """Deepgram hearing the candidate while the bot is mid-utterance must stop the
    bot immediately.

    This is the core fix for "the bot talks over me": barge-in previously fired
    ONLY on the browser VAD's speech_start, which echo cancellation routinely
    suppresses during double-talk (you + bot speaking at once). Deepgram returning
    a transcript is the AEC-independent proof of a real interruption, so it must
    cut the bot's TTS without waiting for the slow debounce -> process_voice_turn
    path (seconds of overtalk).
    """
    session_id = "s-transcript-barge-in"
    seed_voice_session(session_id, [make_question("q1", "python")])

    from src.routes.voice_ws import _maybe_barge_in_on_transcript
    from src.services.interview.voice_turn_processor import get_or_create_turn_state

    turn_state = get_or_create_turn_state(session_id, fake_ws)
    turn_state.bot_speaking = True  # bot mid-utterance

    # Candidate interrupts; the browser VAD never sent speech_start (double-talk).
    # last_flushed_text is empty: this is genuinely new speech, not a stale tail.
    await _maybe_barge_in_on_transcript(
        session_id, fake_ws, "actually wait I want to add something", ""
    )

    assert turn_state.bot_speaking is False, (
        "a Deepgram transcript during bot speech must stop the bot — barge-in "
        "cannot depend on the browser VAD it routinely misses in double-talk"
    )
    assert any(m.get("event") == "barge_in" for m in fake_ws.json_messages), (
        "client must receive a barge_in stop_tts signal"
    )


@pytest.mark.asyncio
async def test_trailing_tail_transcript_does_not_barge_in(fake_ws: FakeWebSocket):
    """A late Deepgram final echoing the answer we just flushed must NOT cut the
    bot's reply.

    After the candidate stops and we flush their answer, the bot starts speaking.
    Deepgram can still emit a trailing final for that same (already-processed)
    utterance. Without a guard, that stale tail would barge-in and truncate the
    bot's response — randomly swallowing questions. Only genuinely new speech may
    interrupt.
    """
    session_id = "s-trailing-tail"
    seed_voice_session(session_id, [make_question("q1", "python")])

    from src.routes.voice_ws import _maybe_barge_in_on_transcript
    from src.services.interview.voice_turn_processor import get_or_create_turn_state

    turn_state = get_or_create_turn_state(session_id, fake_ws)
    turn_state.bot_speaking = True

    flushed = "I would use a hash map because lookups are constant time"
    # A late final repeating the tail of what we already sent to the LLM.
    await _maybe_barge_in_on_transcript(
        session_id, fake_ws, "lookups are constant time", flushed
    )

    assert turn_state.bot_speaking is True, (
        "a stale final echoing the just-flushed answer must not cut the bot's reply"
    )
    assert not any(m.get("event") == "barge_in" for m in fake_ws.json_messages), (
        "no barge_in should be sent for a trailing tail of the flushed turn"
    )


@pytest.mark.asyncio
async def test_tts_complete_opens_candidate_turn_and_starts_silence_monitor(
    fake_ws: FakeWebSocket,
):
    """The silence timer starts only after browser playback completion."""
    session_id = "s-tts-complete"
    seed_voice_session(session_id, [make_question("q1", "python")])

    from src.services.interview.voice_turn_processor import get_or_create_turn_state

    turn_state = get_or_create_turn_state(session_id, fake_ws)
    assert turn_state._silence_task is None

    await _handle_control(fake_ws, session_id, {"event": "tts_complete"}, [None])

    session = get_voice_session(session_id)
    assert session["state"] == "WAITING_FOR_CANDIDATE"
    assert turn_state._silence_task is not None
    turn_state.cancel_silence_monitor()
    assert any(
        message.get("event") == "turn" and message.get("speaker") == "candidate"
        for message in fake_ws.json_messages
    )


@pytest.mark.asyncio
async def test_wait_request_does_not_advance_or_score(fake_ws: FakeWebSocket):
    """A candidate asking for thinking time is not an answer. It must not be
    evaluated by the LLM or advance the active question."""
    session_id = "s-wait-request"
    seed_voice_session(
        session_id,
        [make_question("q1", "creo"), make_question("q2", "gdt")],
    )

    from src.services.interview.voice_turn_processor import get_or_create_turn_state

    class RecordingTTS:
        def __init__(self) -> None:
            self.spoken: list[str] = []

        async def stream_sentence(self, text: str, ws) -> None:
            self.spoken.append(text)

    turn_state = get_or_create_turn_state(session_id, fake_ws)
    tts = RecordingTTS()
    turn_state.tts = tts  # type: ignore[assignment]

    await _handle_wait_request(
        fake_ws,
        session_id,
        "Yeah. Give me twenty five seconds to form my answer.",
    )

    session = get_voice_session(session_id)
    assert int(session["current_question_idx"]) == 0
    assert int(session["turn_count"]) == 0
    assert session["state"] == "WAITING_FOR_CANDIDATE"
    assert "take your time" in " ".join(tts.spoken).lower()
    assert any(
        message.get("event") == "turn" and message.get("speaker") == "candidate"
        for message in fake_ws.json_messages
    )

    # _handle_wait_request now leaves a live silence monitor running (to avoid
    # dead air if the candidate never speaks again). Cancel it so pytest does
    # not see an orphaned task and raise a RuntimeWarning.
    turn_state.cancel_silence_monitor()


@pytest.mark.asyncio
async def test_wait_request_starts_silence_monitor(fake_ws: FakeWebSocket):
    """After _handle_wait_request the silence monitor must be running.

    Regression guard for the dead-air-after-thinking bug: before the fix,
    wait-request cancelled the monitor and never restarted it, so a candidate
    who asked for thinking time and then stayed silent would sit in dead air
    forever — never nudged, never advanced.
    """
    session_id = "s-wait-monitor"
    seed_voice_session(
        session_id,
        [make_question("q1", "creo"), make_question("q2", "gdt")],
    )

    from src.services.interview.voice_turn_processor import get_or_create_turn_state

    class NoopTTS:
        async def stream_sentence(self, text: str, ws) -> None:
            return None

    turn_state = get_or_create_turn_state(session_id, fake_ws)
    turn_state.tts = NoopTTS()  # type: ignore[assignment]

    await _handle_wait_request(
        fake_ws,
        session_id,
        "Give me a moment to think.",
    )

    assert turn_state._silence_task is not None, (
        "silence monitor must be running after a wait request — "
        "without it the candidate sits in dead air if they never speak again"
    )
    turn_state.cancel_silence_monitor()


# ---- Tests for adaptive debounce timing ----


class TestAdaptiveDebounce:
    """The debounce delay must adapt to transcript content. A fixed delay
    either responds too slowly (completion phrases) or interrupts mid-thought
    (trailing conjunctions)."""

    def test_completion_phrase_gets_short_delay(self):
        assert DEBOUNCE_COMPLETE_SECS < DEBOUNCE_SECS, \
            "Completion phrase debounce should be shorter than standard"
        assert DEBOUNCE_COMPLETE_SECS <= 1.0, \
            "Completion phrase should trigger fast response"

    def test_incomplete_phrase_gets_long_delay(self):
        assert DEBOUNCE_INCOMPLETE_SECS > DEBOUNCE_SECS, \
            "Incomplete phrase debounce should be longer than standard"

    def test_standard_debounce_tolerates_thinking_pause(self):
        # Deepgram speech_final is now distinct from intermediate final segments,
        # so the normal response timer can be much shorter without flushing every
        # finalized sentence fragment.
        assert 0.8 <= DEBOUNCE_SECS <= 1.5, \
            "standard speech-final debounce should be short enough for conversational latency"


class TestSpeechEndDeferral:
    """The browser VAD's speech_end is a crude fixed-silence verdict. It must not
    pre-empt the Deepgram-final-driven adaptive debounce and flush a mid-thought
    partial — that was a direct cause of the bot talking over the candidate."""

    def test_defers_to_pending_adaptive_debounce(self):
        # The false-EOT bug: speech_end short-circuited a pending debounce (which
        # may be holding 5s for incomplete-trailing text) and flushed early.
        assert _speech_end_should_flush(debounce_pending=True, force=False) is False, \
            "speech_end must let an in-flight adaptive debounce own EOT timing"

    def test_flushes_interim_only_when_no_debounce(self):
        # Deepgram produced only partials (no final → no debounce). speech_end is
        # the safety net that keeps the turn from being stranded until the
        # candidate speaks again.
        assert _speech_end_should_flush(debounce_pending=False, force=False) is True, \
            "speech_end must flush interim-only buffered text when nothing else will"

    def test_session_end_force_flushes_even_with_pending_debounce(self):
        # On end_session the candidate's last answer must reach the report even if
        # a debounce is still mid-flight.
        assert _speech_end_should_flush(debounce_pending=True, force=True) is True, \
            "session end must force a flush so the final answer is not lost"


# ---- Tests for confidence thresholds ----


class TestConfidenceThresholds:
    """Aggressive repeat requests frustrate candidates. The threshold should
    only trigger on genuinely failed transcriptions, not slightly imperfect ones."""

    def test_low_confidence_threshold_is_conservative(self):
        assert STT_LOW_CONFIDENCE <= 0.55, \
            "Low confidence threshold too high — will trigger repeat requests on usable transcripts"

    @pytest.mark.asyncio
    async def test_low_confidence_repeat_fires_only_once(self, fake_ws: FakeWebSocket):
        """After one repeat request, the bot should process with what it has.
        Multiple 'please repeat' messages waste interview time and frustrate candidates."""
        session_id = "s-repeat-once"
        seed_voice_session(session_id, [make_question("q1", "python")])

        from src.routes.voice_ws import MAX_REPEAT_REQUESTS
        assert MAX_REPEAT_REQUESTS == 1, \
            "MAX_REPEAT_REQUESTS should be 1 to avoid frustrating candidates"
