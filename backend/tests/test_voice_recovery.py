"""Recovery and state-continuity tests for the voice interview pipeline.

These tests cover the failure mode where a temporary silence/stall is followed
by a wake phrase such as "hello". A wake phrase must recover the current
question state; it must never be treated as an answer that advances the
interview.
"""

import asyncio
import json

import pytest

from tests.conftest import FakeWebSocket, make_question, seed_voice_session

from src.services.audio.voice_session import get_voice_session, set_voice_field
from src.services.interview import voice_llm_orchestrator
from src.services.interview.voice_llm_orchestrator import run_llm_turn
from src.services.interview.voice_turn_processor import VoiceTurnState


class _Content:
    def __init__(self, text: str) -> None:
        self.text = text


class _Response:
    def __init__(self, text: str) -> None:
        self.content = [_Content(text)]


class _Messages:
    def __init__(self, text: str) -> None:
        self._text = text
        self.called = False

    async def create(self, **_: object) -> _Response:
        self.called = True
        return _Response(self._text)


class _FakeAsyncAnthropic:
    def __init__(self, messages: _Messages) -> None:
        self.messages = messages


def _ack_xml() -> str:
    return """
<interviewer_response>
  <action>acknowledge_advance</action>
  <spoken_text>Thanks.</spoken_text>
  <internal_notes>test</internal_notes>
  <score_update><topic>python</topic><score>8</score><reasoning>ok</reasoning></score_update>
  <confidence>0.9</confidence>
  <next_state>questioning</next_state>
  <flags></flags>
</interviewer_response>
"""


@pytest.mark.asyncio
async def test_wake_phrase_reasks_current_question_without_llm_or_advance(monkeypatch):
    """A wake phrase after silence is a recovery signal, not an answer.

    If "hello" enters the normal LLM path, the model can acknowledge it and the
    orchestrator advances to a fresh question. That is the state-loss bug users
    experience after reviving a silent bot.
    """
    questions = [make_question("q1", "python"), make_question("q2", "sql")]
    seed_voice_session("s-wake-recover", questions)
    messages = _Messages(_ack_xml())
    monkeypatch.setattr(
        voice_llm_orchestrator,
        "get_async_anthropic_client",
        lambda: _FakeAsyncAnthropic(messages),
    )

    spoken = await run_llm_turn("s-wake-recover", "hello")

    session = get_voice_session("s-wake-recover")
    assert int(session["current_question_idx"]) == 0, (
        "wake phrases must not advance the current question"
    )
    assert json.loads(session["running_scores"]) == {}, (
        "wake phrases must not produce scores"
    )
    assert messages.called is False, (
        "wake phrase recovery should be deterministic and should not call the LLM"
    )
    assert "Tell me about python." in spoken
    assert "still waiting" in spoken.lower()

    transcript = json.loads(session["transcript"])
    assert transcript[-2]["type"] == "wake_phrase"
    assert transcript[-1]["type"] == "recovery_prompt"


@pytest.mark.asyncio
async def test_wake_phrase_during_failed_pending_answer_preserves_question(monkeypatch):
    """If a prior answer failed processing, "are you there" must recover on the
    same question instead of becoming a new answer and advancing.
    """
    seed_voice_session(
        "s-wake-failed",
        [make_question("q1", "python"), make_question("q2", "sql")],
    )
    set_voice_field("s-wake-failed", "pending_answer_text", "Decorators wrap functions.")
    set_voice_field("s-wake-failed", "pending_answer_question_id", "q1")
    set_voice_field("s-wake-failed", "pending_answer_status", "failed")

    messages = _Messages(_ack_xml())
    monkeypatch.setattr(
        voice_llm_orchestrator,
        "get_async_anthropic_client",
        lambda: _FakeAsyncAnthropic(messages),
    )

    spoken = await run_llm_turn("s-wake-failed", "are you there")

    session = get_voice_session("s-wake-failed")
    assert int(session["current_question_idx"]) == 0
    assert messages.called is False
    assert "Tell me about python." in spoken
    assert "trouble processing" in spoken.lower()
    assert session["pending_answer_status"] == "failed"


@pytest.mark.asyncio
async def test_silence_strike_reasks_current_question_without_advancing(fake_ws):
    """Passive silence is not an explicit skip.

    The silence ladder may recover or remind, but it must not move to the next
    question unless the candidate answered, skipped, or explicitly completed the
    current question.
    """
    questions = [make_question("q1", "python"), make_question("q2", "sql")]
    seed_voice_session("s-silence-reask", questions)
    state = VoiceTurnState("s-silence-reask", fake_ws)

    class RecordingTTS:
        def __init__(self) -> None:
            self.spoken: list[str] = []

        async def stream_sentence(self, text: str, ws) -> None:
            self.spoken.append(text)

    tts = RecordingTTS()
    state.tts = tts  # type: ignore[assignment]

    await state._advance_after_silence()
    state.cancel_silence_monitor()

    session = get_voice_session("s-silence-reask")
    assert int(session["current_question_idx"]) == 0, (
        "silence recovery must not skip the unanswered current question"
    )
    joined = " ".join(tts.spoken)
    assert "Tell me about python." in joined
    assert "Tell me about sql." not in joined


@pytest.mark.asyncio
async def test_playback_ack_watchdog_recovers_candidate_turn(fake_ws, monkeypatch):
    """If the frontend never sends tts_complete, the server must not remain in
    BOT_SPEAKING forever with the mic closed.
    """
    import src.services.interview.voice_turn_processor as vtp

    monkeypatch.setattr(vtp, "PLAYBACK_ACK_TIMEOUT_SECS", 0.01)
    seed_voice_session("s-playback-watchdog", [make_question("q1", "python")])
    state = VoiceTurnState("s-playback-watchdog", fake_ws)

    class NoopTTS:
        async def stream_sentence(self, text: str, ws) -> None:
            return None

    state.tts = NoopTTS()  # type: ignore[assignment]

    await state.stream_response("Please answer this question.", entry_type="question")
    assert get_voice_session("s-playback-watchdog")["state"] == "BOT_SPEAKING"

    await asyncio.sleep(0.05)

    session = get_voice_session("s-playback-watchdog")
    assert session["state"] == "WAITING_FOR_CANDIDATE"
    assert int(session.get("playback_recoveries", 0)) == 1
    assert any(
        message.get("event") == "turn"
        and message.get("speaker") == "candidate"
        and message.get("recovered") is True
        for message in fake_ws.json_messages
    )
    state.cancel_silence_monitor()
