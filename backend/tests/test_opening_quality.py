"""Failing tests for AI interviewer opening quality.

WHY: Jumping straight to technical questions increases candidate anxiety and
     degrades response authenticity. The bot MUST greet by name, signal warmth,
     and ask at least one rapport question before any technical content.

All five tests are intentionally FAILING against BAD_OPENING. They turn green
once the bot produces a proper warm opener.

Spec: docs/superpowers/specs/2026-06-14-opening-quality-test-design.md
"""

CANDIDATE_NAME = "Utkarsh"

# Simulates a broken interviewer that skips the warm preamble entirely.
BAD_OPENING = (
    "Can you explain the difference between a process and a thread? "
    "Please be specific about memory isolation, context-switching overhead, "
    "and when you would choose one over the other."
)

WARM_MARKERS = frozenset({
    "how are you",
    "how's your day",
    "how did your day",
    "nice to meet",
    "good to meet",
    "great to meet",
    "glad to",
    "welcome",
    "before we dive in",
})

RAPPORT_SIGNALS = frozenset({
    "your day",
    "recent role",
    "last job",
    "most recent",
    "where did you study",
    "what brought you",
    "how did you get into",
    "what's new",
    "exciting",
    "anything going on",
})

TECHNICAL_OPENERS = frozenset({
    "can you explain",
    "what is the difference",
    "describe how",
    "implement",
    "write a",
    "what are the",
    "how does",
    "define ",
})


# R1 — Candidate name must appear in the opening

def test_opening_contains_candidate_name():
    """Bot must address the candidate by name on the first turn.

    WHY: An unnamed opener is impersonal and signals the bot is ignoring
         candidate metadata. Minimum bar for personalization.
    """
    assert CANDIDATE_NAME.lower() in BAD_OPENING.lower(), (
        f"FAIL (R1 — missing name)\n"
        f"  Expected: '{CANDIDATE_NAME}' present in opening\n"
        f"  Actual:   {BAD_OPENING!r}\n"
        f"  Fix:      Bot must address the candidate by name in the first turn."
    )


# R2 — At least one warm greeting marker must be present

def test_opening_has_warm_marker():
    """Bot must include a recognisable warm greeting phrase.

    WHY: Warm markers signal 'conversation mode', not 'test mode'. Absence of
         any warm marker makes the experience interrogative from word one.
    """
    _text = BAD_OPENING.lower()
    matched = [m for m in WARM_MARKERS if m in _text]
    assert matched, (
        f"FAIL (R2 — no warm marker)\n"
        f"  Expected: at least one of {sorted(WARM_MARKERS)}\n"
        f"  Actual:   {BAD_OPENING!r}\n"
        f"  Matched:  none\n"
        f"  Fix:      Add a greeting phrase before the first question."
    )


# R3 — At least one rapport signal must be present

def test_opening_has_rapport_signal():
    """Bot must ask at least one rapport-building question.

    WHY: Rapport questions lower anxiety and establish trust before technical
         probing begins (SHRM interviewing guidelines).
    """
    _text = BAD_OPENING.lower()
    matched = [s for s in RAPPORT_SIGNALS if s in _text]
    assert matched, (
        f"FAIL (R3 — no rapport signal)\n"
        f"  Expected: at least one of {sorted(RAPPORT_SIGNALS)}\n"
        f"  Actual:   {BAD_OPENING!r}\n"
        f"  Matched:  none\n"
        f"  Fix:      Ask about well-being, last role, or background before "
        f"any technical question."
    )


# R4 — Opening must NOT start with a technical interrogative

def test_opening_does_not_start_with_technical_interrogative():
    """The first sentence must not open with a technical question pattern.

    WHY: The first sentence sets the entire tone. A cold technical opener has
         already signalled 'you are being tested' before any warmth can land.
    """
    first_sentence = BAD_OPENING.split(".")[0].split("?")[0].lower().strip()
    matched = [t for t in TECHNICAL_OPENERS if first_sentence.startswith(t)]
    assert not matched, (
        f"FAIL (R4 — technical interrogative opener)\n"
        f"  Expected: first sentence does not start with a technical pattern\n"
        f"  First sentence: {first_sentence!r}\n"
        f"  Matched:        {matched}\n"
        f"  Fix:            Lead with a greeting or rapport question, not a technical probe."
    )


# R5 — Opening must not be exclusively technical (composite of R1–R3)

def test_opening_is_not_exclusively_technical():
    """Opening with zero social content always fails.

    WHY: Makes the 'exclusively technical' verdict explicit in test output
         rather than requiring the reader to infer it from three separate failures.
    """
    _text = BAD_OPENING.lower()
    has_any_warm_content = (
        CANDIDATE_NAME.lower() in _text
        or any(m in _text for m in WARM_MARKERS)
        or any(s in _text for s in RAPPORT_SIGNALS)
    )
    assert has_any_warm_content, (
        f"FAIL (R5 — exclusively technical opening)\n"
        f"  Expected: name, warm marker, or rapport signal present\n"
        f"  Actual:   {BAD_OPENING!r}\n"
        f"  Fix:      Bot output must contain a greeting, name, or rapport "
        f"question before technical content."
    )
