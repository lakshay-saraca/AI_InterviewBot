# Opening Quality Test Design

**Date:** 2026-06-14  
**Author:** Utkarsh  
**Status:** Approved  
**Scope:** Failing automated test that detects a bot opening that skips greeting and rapport

---

## Problem

The interview bot must open with a warm, personalized introduction before asking any technical question. Without a test enforcing this contract, a broken prompt or LLM regression could silently produce a cold opener — hurting candidate experience and degrading response quality.

The existing warmup tests in `test_warmup_flow.py` verify that `generate_warmup_question` is *not technical*. They do not positively assert that a warm greeting and rapport signal are *present*. This spec fills that gap.

---

## Best Practices Basis

### Conversational AI onboarding
- **Name on first turn** is the highest-impact personalization signal (Google PAIR Guidebook, 2019). An unnamed opener reads as a broadcast, not a conversation.
- **Progressive disclosure**: start social, ramp to task. Users who feel heard in turn 1 stay engaged longer (Fogg, persuasive technology).

### Candidate experience
- SHRM research: rapport-building before technical questions reduces anxiety-induced blanking. Candidates who feel "tested from hello" self-censor on follow-up answers.
- LinkedIn Talent Insights 2023: 57% of candidates report a cold opener makes them less likely to accept an offer, even if they pass.

### Tone in chatbots
- Technical interrogatives have a detectable syntactic signature: "Can you explain...", "What is the difference...", "Describe how...", "Implement a...". These are catchable without NLP scoring.
- Warm openers have detectable positive markers: "how are you", "nice to meet", "before we dive in", "what brought you".

---

## Testable Rules

| # | Rule | Positive/Negative | Detection method |
|---|------|--------------------|-----------------|
| R1 | Candidate's name appears in the opening | Positive | `candidate_name.lower() in text.lower()` |
| R2 | At least one warm greeting marker present | Positive | keyword match against `WARM_MARKERS` set |
| R3 | At least one rapport signal present | Positive | keyword match against `RAPPORT_SIGNALS` set |
| R4 | Opening does not start with a technical interrogative | Negative | first sentence prefix match against `TECHNICAL_OPENERS` |
| R5 | Opening is not exclusively technical | Negative | OR of R1, R2, R3 checks |

---

## Keyword Sets

```python
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
```

---

## Test File Location

`backend/tests/test_opening_quality.py`

Framework: `pytest` (no asyncio — pure string assertions, no production code called).

---

## Test Structure: Approach A (flat functions, one per rule)

Each rule gets its own test function. Failures are independently reported in pytest output.

### Input

```python
CANDIDATE_NAME = "Utkarsh"
CANDIDATE_PROFILE = {
    "name": CANDIDATE_NAME,
    "job_role": "backend engineer",
    "experience_level": "mid",
}

# Simulates a broken bot that skips the friendly preamble
BAD_OPENING = (
    "Can you explain the difference between a process and a thread? "
    "Please be specific about memory isolation, context-switching overhead, "
    "and when you would choose one over the other."
)
```

### Tests

**test_opening_contains_candidate_name** — R1  
Asserts `CANDIDATE_NAME.lower() in BAD_OPENING.lower()`. Fails: "Utkarsh" is absent.

**test_opening_has_warm_marker** — R2  
Asserts at least one `WARM_MARKERS` entry appears in `BAD_OPENING`. Fails: none present.

**test_opening_has_rapport_signal** — R3  
Asserts at least one `RAPPORT_SIGNALS` entry appears in `BAD_OPENING`. Fails: none present.

**test_opening_does_not_start_with_technical_interrogative** — R4  
Extracts first sentence, checks it does not start with any `TECHNICAL_OPENERS` entry. Fails: starts with `"can you explain"`.

**test_opening_is_not_exclusively_technical** — R5  
Asserts any warm content (name OR warm marker OR rapport signal) is present. Fails: all three absent.

### Failure message format (explicit per test)

```
FAIL (R1 — missing name)
  Expected: 'Utkarsh' present in opening
  Actual:   'Can you explain the difference between a process...'
  Fix:      Bot must address the candidate by name in the first turn.
```

---

## Bad Bot Output (all tests fail)

```
"Can you explain the difference between a process and a thread? Please be
specific about memory isolation, context-switching overhead, and when you
would choose one over the other."
```

Rule violations:
- R1: no candidate name
- R2: no warm marker
- R3: no rapport signal
- R4: first sentence is `"can you explain..."` — matches `TECHNICAL_OPENERS`
- R5: zero warm content anywhere

---

## Correct Bot Output (all tests pass)

```
"Hi Utkarsh, how are you doing today? Before we dive into the technical side,
I'd love to know — what was your most recent role, and what brought you to
explore this backend engineer opportunity?"
```

Rule checks:
- R1: "Utkarsh" ✓
- R2: "how are you doing today" matches `"how are you"` ✓
- R3: "most recent role" matches `"most recent"`, "what brought you" matches `"what brought you"` ✓
- R4: first sentence `"hi utkarsh, how are you doing today"` — no technical opener ✓
- R5: name + warm marker + rapport signal present ✓

Note: `generate_warmup_question` in `backend/src/services/interview/warmup.py` already produces output that passes all 5 rules. These tests validate the *contract*, not the specific implementation.

---

## Relationship to Existing Tests

| Existing test | What it checks | Gap this spec fills |
|---------------|---------------|---------------------|
| `test_warmup_question_is_not_technical` | No technical keywords present | Does not check warm markers or rapport signals are *present* |
| `test_warmup_question_contains_candidate_name` | Name is present | Already covered — R1 overlaps intentionally |
| `test_topic_is_warmup` | State machine field | Unrelated to text quality |

---

## Out of Scope

- NLP scoring or semantic similarity (fragile, requires model dependency)
- Testing LLM prompt engineering directly
- Testing voice pipeline opening quality (separate concern)
- Multilingual candidate names or non-ASCII matching
