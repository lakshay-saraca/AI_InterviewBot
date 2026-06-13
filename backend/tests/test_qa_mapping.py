"""
Tests for Q/A history mapping correctness.

Root cause being tested:
  In voice mode, candidate answers (the `transcript` parameter to run_llm_turn)
  are never appended to the session transcript.  The final voice evaluation
  therefore has no candidate text to work with, causing the LLM to hallucinate
  or reuse the same placeholder answer_text for every question.

Requirements verified here:
  - Each question maps to the correct candidate answer in the transcript
  - No candidate answer is silently dropped
  - Multiple Q/A pairs in one session are each persisted with the right pairing
  - Similar-but-distinct answers are stored without collapsing or reuse
  - question_id is attached to each candidate turn so extraction is deterministic
"""

import json

import pytest

from tests.conftest import make_question, seed_voice_session
from src.services.audio.voice_session import get_voice_session
from src.services.interview import voice_llm_orchestrator
from src.services.interview.voice_llm_orchestrator import run_llm_turn


# ---------------------------------------------------------------------------
# LLM stub plumbing (same pattern as existing tests)
# ---------------------------------------------------------------------------

class _Content:
    def __init__(self, text: str) -> None:
        self.text = text


class _Response:
    def __init__(self, text: str) -> None:
        self.content = [_Content(text)]


class _Messages:
    def __init__(self, text: str) -> None:
        self._text = text

    async def create(self, **_: object) -> _Response:
        return _Response(self._text)


class FakeAsyncAnthropic:
    def __init__(self, text: str) -> None:
        self.messages = _Messages(text)


def _patch_llm(monkeypatch, xml: str) -> None:
    monkeypatch.setattr(
        voice_llm_orchestrator,
        "get_async_anthropic_client",
        lambda: FakeAsyncAnthropic(xml),
    )


ACKNOWLEDGE_XML = """
<interviewer_response>
  <action>acknowledge</action>
  <spoken_text>Good answer.</spoken_text>
  <internal_notes>clear</internal_notes>
  <score_update><topic>python</topic><score>8</score><reasoning>solid</reasoning></score_update>
  <confidence>0.9</confidence>
  <next_state>questioning</next_state>
  <flags></flags>
</interviewer_response>
"""

ACKNOWLEDGE_DB_XML = """
<interviewer_response>
  <action>acknowledge</action>
  <spoken_text>Good answer on databases.</spoken_text>
  <internal_notes>clear</internal_notes>
  <score_update><topic>databases</topic><score>7</score><reasoning>ok</reasoning></score_update>
  <confidence>0.85</confidence>
  <next_state>questioning</next_state>
  <flags></flags>
</interviewer_response>
"""


# ---------------------------------------------------------------------------
# Bug 1: Candidate answers not stored in voice transcript
# ---------------------------------------------------------------------------

class TestCandidateAnswerStoredInTranscript:
    """After run_llm_turn processes a candidate's speech, the candidate's answer
    text must appear in the session transcript.  Without this, the voice
    evaluation pipeline has no candidate answers to extract Q/A pairs from."""

    @pytest.mark.asyncio
    async def test_candidate_answer_appears_in_transcript(self, monkeypatch):
        """run_llm_turn must store the candidate's transcript in the voice session."""
        questions = [make_question("q1", "python"), make_question("q2", "databases")]
        seed_voice_session("s-qa-store", questions)
        _patch_llm(monkeypatch, ACKNOWLEDGE_XML)

        candidate_answer = "I use decorators for memoization and caching."
        await run_llm_turn("s-qa-store", candidate_answer)

        session = get_voice_session("s-qa-store")
        transcript = json.loads(session["transcript"])

        candidate_turns = [t for t in transcript if t.get("speaker") == "candidate"]

        # FAILS before fix: candidate answer is never appended to transcript
        assert len(candidate_turns) >= 1, (
            f"Candidate answer was never stored in transcript. "
            f"transcript={[t.get('speaker') for t in transcript]}"
        )
        assert any(candidate_answer in t.get("text", "") for t in candidate_turns), (
            f"Expected '{candidate_answer}' in candidate turns, "
            f"got: {[t.get('text') for t in candidate_turns]}"
        )

    @pytest.mark.asyncio
    async def test_multiple_answers_all_stored(self, monkeypatch):
        """Each distinct candidate answer must be stored separately.
        This test catches shallow/index-based bugs where only the last answer survives."""
        questions = [
            make_question("q1", "python"),
            make_question("q2", "databases"),
        ]
        seed_voice_session("s-qa-multi", questions)

        answers_given = [
            "I use list comprehensions for conciseness.",
            "I normalise tables to third normal form.",
        ]

        # First answer — q1
        _patch_llm(monkeypatch, ACKNOWLEDGE_XML)
        await run_llm_turn("s-qa-multi", answers_given[0])

        # Second answer — q2
        _patch_llm(monkeypatch, ACKNOWLEDGE_DB_XML)
        await run_llm_turn("s-qa-multi", answers_given[1])

        session = get_voice_session("s-qa-multi")
        transcript = json.loads(session["transcript"])

        candidate_turns = [t for t in transcript if t.get("speaker") == "candidate"]
        stored_texts = [t.get("text", "") for t in candidate_turns]

        # FAILS before fix: only bot turns are ever stored
        assert len(candidate_turns) == 2, (
            f"Expected 2 candidate turns, got {len(candidate_turns)}. "
            f"Stored texts: {stored_texts}"
        )

        for answer in answers_given:
            assert any(answer in text for text in stored_texts), (
                f"Answer '{answer}' was not stored. Stored: {stored_texts}"
            )

    @pytest.mark.asyncio
    async def test_similar_answers_stored_distinctly(self, monkeypatch):
        """Two similar-but-not-identical answers must not be collapsed.
        This catches shallow-equality bugs."""
        questions = [
            make_question("q1", "python"),
            make_question("q2", "python_advanced"),
        ]
        seed_voice_session("s-qa-similar", questions)

        # Intentionally similar answers — only differ at the end
        answer_1 = "Python uses reference counting for memory management."
        answer_2 = "Python uses reference counting and a cyclic garbage collector."

        _patch_llm(monkeypatch, ACKNOWLEDGE_XML)
        await run_llm_turn("s-qa-similar", answer_1)

        _patch_llm(monkeypatch, ACKNOWLEDGE_XML)
        await run_llm_turn("s-qa-similar", answer_2)

        session = get_voice_session("s-qa-similar")
        transcript = json.loads(session["transcript"])

        candidate_turns = [t for t in transcript if t.get("speaker") == "candidate"]
        stored_texts = [t.get("text", "") for t in candidate_turns]

        assert len(candidate_turns) == 2, (
            f"Expected 2 distinct candidate turns, got {len(candidate_turns)}. "
            f"Similar answers were collapsed or one was dropped. Stored: {stored_texts}"
        )

        # Both distinct values must be present
        assert answer_1 in stored_texts, f"First answer missing. Stored: {stored_texts}"
        assert answer_2 in stored_texts, f"Second answer missing. Stored: {stored_texts}"
        assert answer_1 != answer_2, "Answers are identical — test is invalid"


# ---------------------------------------------------------------------------
# Bug 2: Candidate turns lack question_id — prevents deterministic extraction
# ---------------------------------------------------------------------------

class TestCandidateAnswerHasQuestionId:
    """Each candidate turn in the transcript must carry the question_id of the
    question it was answering.  Without this, the evaluation pipeline has to
    infer pairing from position, which is wrong when follow-ups occur."""

    @pytest.mark.asyncio
    async def test_candidate_turn_includes_question_id(self, monkeypatch):
        """After run_llm_turn, the stored candidate turn must include
        question_id matching the question that was active at the time."""
        questions = [make_question("q1", "python"), make_question("q2", "databases")]
        seed_voice_session("s-qa-qid", questions)
        _patch_llm(monkeypatch, ACKNOWLEDGE_XML)

        await run_llm_turn("s-qa-qid", "Decorators wrap functions at definition time.")

        session = get_voice_session("s-qa-qid")
        transcript = json.loads(session["transcript"])

        candidate_turns = [t for t in transcript if t.get("speaker") == "candidate"]

        # FAILS before fix: candidate turns never have question_id
        assert len(candidate_turns) >= 1, "No candidate turn found in transcript"

        first_candidate_turn = candidate_turns[0]
        assert "question_id" in first_candidate_turn, (
            f"Candidate turn has no question_id field. "
            f"Turn: {first_candidate_turn}. "
            f"Without question_id, answer extraction during evaluation is ambiguous."
        )
        assert first_candidate_turn["question_id"] == "q1", (
            f"Expected question_id='q1' (active question), "
            f"got '{first_candidate_turn.get('question_id')}'"
        )

    @pytest.mark.asyncio
    async def test_each_answer_tagged_with_correct_question_id(self, monkeypatch):
        """Across a multi-question session, each candidate turn must be tagged
        with the question_id of the question it was answering, not the next
        one or a stale previous one."""
        questions = [
            make_question("q1", "python"),
            make_question("q2", "databases"),
        ]
        seed_voice_session("s-qa-qid-multi", questions)

        _patch_llm(monkeypatch, ACKNOWLEDGE_XML)
        await run_llm_turn("s-qa-qid-multi", "Answer to Q1.")

        _patch_llm(monkeypatch, ACKNOWLEDGE_DB_XML)
        await run_llm_turn("s-qa-qid-multi", "Answer to Q2.")

        session = get_voice_session("s-qa-qid-multi")
        transcript = json.loads(session["transcript"])

        candidate_turns = [t for t in transcript if t.get("speaker") == "candidate"]

        assert len(candidate_turns) == 2, (
            f"Expected 2 candidate turns, got {len(candidate_turns)}"
        )

        q_ids = [t.get("question_id") for t in candidate_turns]

        # First answer must be tagged with q1, second with q2
        assert q_ids[0] == "q1", (
            f"First candidate answer should be tagged with 'q1', got '{q_ids[0]}'"
        )
        assert q_ids[1] == "q2", (
            f"Second candidate answer should be tagged with 'q2', got '{q_ids[1]}'"
        )


# ---------------------------------------------------------------------------
# Integration: correct answer stored at correct position in Q/A history
# ---------------------------------------------------------------------------

class TestQAHistoryOrder:
    """Verify that Q/A pairs can be extracted in order from the transcript
    and that each question has its own distinct candidate answer."""

    @pytest.mark.asyncio
    async def test_qa_pairs_extractable_in_order(self, monkeypatch):
        """The transcript must allow correct positional extraction of Q/A pairs:
        question N → immediately followed by the answer to question N."""
        questions = [
            make_question("q1", "python"),
            make_question("q2", "databases"),
        ]
        seed_voice_session("s-qa-order", questions)

        answers = ["Python answer here.", "Databases answer here."]

        _patch_llm(monkeypatch, ACKNOWLEDGE_XML)
        await run_llm_turn("s-qa-order", answers[0])

        _patch_llm(monkeypatch, ACKNOWLEDGE_DB_XML)
        await run_llm_turn("s-qa-order", answers[1])

        session = get_voice_session("s-qa-order")
        transcript = json.loads(session["transcript"])

        # Build question_id → answer_text mapping from transcript
        qa_map: dict[str, str] = {}
        for turn in transcript:
            if turn.get("speaker") == "candidate" and turn.get("question_id"):
                qa_map[turn["question_id"]] = turn["text"]

        assert "q1" in qa_map, f"q1 answer not mapped. qa_map={qa_map}"
        assert "q2" in qa_map, f"q2 answer not mapped. qa_map={qa_map}"

        assert qa_map["q1"] == answers[0], (
            f"Q1 mapped to wrong answer. Expected '{answers[0]}', got '{qa_map['q1']}'"
        )
        assert qa_map["q2"] == answers[1], (
            f"Q2 mapped to wrong answer. Expected '{answers[1]}', got '{qa_map['q2']}'"
        )
