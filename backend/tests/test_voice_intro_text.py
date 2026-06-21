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
