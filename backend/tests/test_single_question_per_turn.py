"""Tests for the single-question-per-turn guardrail.

Covers:
- validate_single_question in response_parser.py
- System prompt rule presence
"""

import os

import pytest

from src.services.llm.response_parser import validate_single_question

# ---------------------------------------------------------------------------
# validate_single_question — core cases
# ---------------------------------------------------------------------------


def test_single_question_passes_through():
    """A plain single question must be returned unchanged."""
    text = "Can you describe your Python experience?"
    assert validate_single_question(text) == text


def test_compound_question_with_and_also_truncated():
    """Two unrelated questions joined by 'and also' must be truncated."""
    text = "Describe your Python experience, and also tell me about a challenging project?"
    result = validate_single_question(text)
    assert result == "Describe your Python experience?"


def test_and_also_compound_detected():
    """'and also' is a compound conjunction — second question must be dropped."""
    text = "What is your notice period, and also are you open to relocation?"
    result = validate_single_question(text)
    assert result == "What is your notice period?"


def test_as_well_as_compound_detected():
    """'as well as' between two questions must cause truncation after the first '?'."""
    text = "Can you describe your leadership style? As well as how do you handle conflict?"
    result = validate_single_question(text)
    assert result == "Can you describe your leadership style?"


def test_along_with_compound_detected():
    """'along with' between two questions must cause truncation after the first '?'."""
    text = "What is your preferred tech stack, along with why did you choose it?"
    result = validate_single_question(text)
    assert result == "What is your preferred tech stack?"


def test_clarifying_subclause_not_truncated():
    """A single question with a clarifying sub-clause (one '?') must be unchanged."""
    text = "Can you explain X, specifically how Y works?"
    result = validate_single_question(text)
    assert result == text


def test_multiple_question_marks_without_conjunction_truncated():
    """Two '?' with no conjunction keyword still get truncated after the first."""
    text = "Tell me about Python? What frameworks have you used?"
    result = validate_single_question(text)
    assert result == "Tell me about Python?"


def test_empty_string_unchanged():
    """Empty string must pass through without error."""
    assert validate_single_question("") == ""


def test_no_question_mark_unchanged():
    """A bot acknowledgement with no '?' must pass through unchanged."""
    text = "Thank you for your answer. Let's move on."
    assert validate_single_question(text) == text


def test_bare_and_not_falsely_truncated():
    """Bare 'and' in a single question must NOT trigger truncation.
    'What experience do you have with React and Node?' is one question."""
    text = "What experience do you have with React and Node?"
    assert validate_single_question(text) == text


def test_bare_and_listing_two_topics_unchanged():
    """A question listing related items with 'and' is a single question."""
    text = "Can you describe your experience with microservices and distributed systems?"
    assert validate_single_question(text) == text


# ---------------------------------------------------------------------------
# validate_single_question — broadened multi-ask detection (planner-shaped)
#
# The planner is allowed to author a question in "one or two sentences", so the
# compound questions that actually reach candidates are period-separated asks
# and imperatives with 0-1 '?', which the original heuristic (2+ '?' or a short
# conjunction list) never caught.
# ---------------------------------------------------------------------------


def test_imperative_stack_reduced_to_first_ask():
    """Three stacked asks (a subordinate-clause imperative, an imperative, and a
    '?') must be reduced to only the first ask. This is the exact shape that
    reached candidates on the acknowledge_advance hand-off."""
    text = (
        "When you're working on a drawing in Creo, walk me through what that "
        "process typically looks like for you. Tell me about your experience "
        "applying GD&T to engineering drawings. Can you describe a specific "
        "situation where you had to define tolerances or geometric controls to "
        "meet functional requirements?"
    )
    result = validate_single_question(text)
    assert result == (
        "When you're working on a drawing in Creo, walk me through what that "
        "process typically looks like for you."
    )


def test_broad_question_then_example_request_reduced():
    """A broad ask followed by a specific-example ask (two sentences, one '?')
    must keep only the first ask."""
    text = (
        "Walk me through your testing process. Can you give a specific example "
        "where a test caught a real bug?"
    )
    assert validate_single_question(text) == "Walk me through your testing process."


def test_two_imperative_asks_without_question_mark_reduced():
    """Two imperative asks with no '?' at all must be reduced to the first."""
    text = "Walk me through your deployment pipeline. Describe a rollback you ran."
    assert validate_single_question(text) == "Walk me through your deployment pipeline."


def test_also_connector_truncated():
    """'also' attaching a second question after a comma must be truncated."""
    text = "What testing framework do you use, also how do you structure suites?"
    assert validate_single_question(text) == "What testing framework do you use?"


def test_in_addition_connector_truncated():
    """'in addition' attaching a second question after a clause boundary must be
    truncated."""
    text = "How do you handle retries; in addition, how do you handle timeouts?"
    assert validate_single_question(text) == "How do you handle retries?"


def test_scenario_setup_plus_one_question_not_truncated():
    """A scenario-setup sentence followed by a SINGLE question is one ask and must
    be preserved in full — guards against over-clamping."""
    text = "You're given a legacy service with no tests. How would you start adding coverage?"
    assert validate_single_question(text) == text


def test_also_mid_question_not_truncated():
    """'also' used mid-question (not after a clause boundary) must be preserved."""
    text = "How do you also handle edge cases in your tests?"
    assert validate_single_question(text) == text


# ---------------------------------------------------------------------------
# System prompt rule presence
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "src",
    "prompts",
    "system_prompt.txt",
)


def test_system_prompt_contains_single_question_rule():
    """The system prompt must contain an explicit one-question-per-turn rule."""
    with open(_SYSTEM_PROMPT_PATH, encoding="utf-8") as fh:
        content = fh.read()
    assert "ONE question per turn" in content or "exactly ONE question" in content, (
        "system_prompt.txt is missing the single-question-per-turn rule. "
        "Add rule 6 to the ## INTERVIEW RULES section."
    )


_PLANNER_PROMPT_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "src",
    "prompts",
    "interview_planner_prompt.txt",
)


def test_planner_prompt_requires_one_question_per_item():
    """The planner authors the actual questions and its output reaches candidates
    verbatim, so it must be told each question_text asks exactly one thing."""
    with open(_PLANNER_PROMPT_PATH, encoding="utf-8") as fh:
        content = fh.read().lower()
    assert "exactly one question" in content or "one question per" in content, (
        "interview_planner_prompt.txt is missing the single-question constraint. "
        "The planner must be told each question_text asks exactly ONE thing."
    )
