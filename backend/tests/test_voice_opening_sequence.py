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
