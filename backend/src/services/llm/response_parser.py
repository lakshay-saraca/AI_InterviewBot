import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional
from xml.sax.saxutils import unescape


@dataclass
class ParsedLLMResponse:
    action: str
    spoken_text: str
    internal_notes: str
    score: Optional[float]
    score_topic: Optional[str]
    reasoning: Optional[str]
    next_state: str
    confidence: Optional[float] = None
    flags: list[str] = field(default_factory=list)


# A bare '&' (one not opening a valid entity like &amp; or &#39;) makes the XML
# not well-formed and crashes ET.fromstring. The interviewer LLM routinely writes
# them in free-text fields (e.g. "<topic>Performance optimization & database
# design</topic>"), so escape them before parsing instead of failing the whole
# response. Only '&' is touched — never '<'/'>' — so tag structure is preserved.
_BARE_AMP_RE = re.compile(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)")

# Extract just the candidate-facing line when the XML can't be parsed as a whole.
_SPOKEN_TEXT_RE = re.compile(
    r"<spoken_text>(.*?)</spoken_text>", re.IGNORECASE | re.DOTALL
)


def _safe_spoken_fallback(raw: str) -> str:
    """Candidate-safe text for when the XML can't be parsed.

    NEVER returns the raw blob when it contains tags — that leaks internal_notes
    and score_update to the candidate (the production incident this guards). Order:
    1. Pull out <spoken_text> if present and speak only that.
    2. If the raw is plain prose (no tags), speak it as-is (genuine non-XML reply).
    3. Otherwise speak a neutral acknowledgement rather than risk a leak.
    """
    match = _SPOKEN_TEXT_RE.search(raw)
    if match:
        return unescape(match.group(1)).strip()
    if "<" not in raw:
        return raw.strip()
    return "Thank you. Let's continue."


def _fallback(raw: str) -> ParsedLLMResponse:
    return ParsedLLMResponse(
        action="acknowledge",
        spoken_text=_safe_spoken_fallback(raw),
        internal_notes="",
        score=None,
        score_topic=None,
        reasoning=None,
        next_state="questioning",
        flags=[],
    )


def parse_xml_response(raw: str) -> ParsedLLMResponse:
    start = raw.find("<interviewer_response>")
    end = raw.find("</interviewer_response>")

    if start == -1 or end == -1:
        return _fallback(raw)

    xml_str = raw[start : end + len("</interviewer_response>")]
    xml_str = _BARE_AMP_RE.sub("&amp;", xml_str)

    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return _fallback(raw)

    score_elem = root.find("score_update")
    score: Optional[float] = None
    score_topic: Optional[str] = None
    reasoning: Optional[str] = None

    if score_elem is not None:
        raw_score = score_elem.findtext("score", "").strip()
        if raw_score:
            try:
                parsed = float(raw_score)
                if 0 <= parsed <= 10:
                    score = parsed
            except ValueError:
                pass
        score_topic = score_elem.findtext("topic", "").strip() or None
        reasoning = score_elem.findtext("reasoning", "").strip() or None

    confidence: Optional[float] = None
    raw_confidence = root.findtext("confidence", "").strip()
    if raw_confidence:
        try:
            parsed_conf = float(raw_confidence)
            if 0.0 <= parsed_conf <= 1.0:
                confidence = parsed_conf
        except ValueError:
            pass

    flags_text = root.findtext("flags", "").strip()
    flags = [f.strip() for f in flags_text.split(",") if f.strip()]

    return ParsedLLMResponse(
        action=root.findtext("action", "acknowledge").strip(),
        spoken_text=root.findtext("spoken_text", "").strip(),
        internal_notes=root.findtext("internal_notes", "").strip(),
        score=score,
        score_topic=score_topic,
        reasoning=reasoning,
        next_state=root.findtext("next_state", "questioning").strip(),
        confidence=confidence,
        flags=flags,
    )


# Pattern A: conjunction that appears *after* a '?' (Shape A — two explicit question marks).
# e.g. "What is X? And also what is Y?"
_CONJUNCTION_AFTER_QMARK_RE = re.compile(
    r"\?[\s,]*(?:and also|and|as well as|along with)\b",
    re.IGNORECASE,
)

# Pattern B: conjunction that appears in the *body* of the sentence before the final '?'
# (Shape B — one shared terminal '?').
# e.g. "What is your notice period, and also are you open to relocation?"
# We require at least a few words both before and after the conjunction so that
# innocent uses like "X and Y?" (a single question about two related things) are
# not falsely flagged.  The heuristic: 3+ non-conjunction words before the match
# and 3+ words after it before the final '?'.
_CONJUNCTION_IN_BODY_RE = re.compile(
    r"(?:\w+\W+){3,}(?P<conj>and also|as well as|along with|and)\s+(?:\w+\W+){2,}\w+\?",
    re.IGNORECASE,
)

# Imperative "ask" verbs that request the candidate to produce an answer now.
# Matched only at a clause head (sentence start, or just after a comma/semicolon)
# so mid-sentence uses ("...and explain why") never false-trigger. Scenario-framing
# verbs (imagine / suppose / consider) are deliberately EXCLUDED — they set up a
# single question, they are not a second ask.
_ASK_VERB_HEAD_RE = re.compile(
    r"(?:^|[,;])\s*"
    r"(walk|tell|describe|explain|give|share|outline|discuss|elaborate|provide|talk)\b",
    re.IGNORECASE,
)

# Extra connectors that attach a second question. Unlike the Shape B list, these
# are only treated as compound-splitters when they follow a clause boundary
# (comma or semicolon), so mid-question adverbs ("how do you also handle X?") and
# subordinating uses are preserved.
_BOUNDARY_CONNECTORS = ("in addition", "also")


def _is_ask_sentence(sentence: str) -> bool:
    """A sentence is an 'ask' if it ends in '?' or opens (at a clause head) with an
    imperative request verb ("Walk me through...", "..., describe...")."""
    s = sentence.strip()
    if not s:
        return False
    if s.endswith("?"):
        return True
    return bool(_ASK_VERB_HEAD_RE.search(s))


def validate_single_question(spoken_text: str) -> str:
    """Enforce that spoken_text contains only one question per turn.

    Three shapes of compound questions are detected and repaired:

    Shape A — multiple '?' (the LLM included two explicit question sentences):
        Truncated after the first '?' regardless of conjunction presence.

    Shape C — multiple asks spread across sentences with 0-1 '?', e.g. an
    imperative "Walk me through X." followed by "Describe Y." or a
    "Can you give an example?" These are the planner-shaped compounds (the
    planner writes questions in "one or two sentences"): kept up to and including
    the FIRST ask, later asks dropped. An ask is a sentence ending in '?' or one
    opening with an imperative request verb; scenario-setup sentences are not asks,
    so "You're on a legacy codebase. How would you test it?" is left intact.

    Shape B — single shared terminal '?' with a compound conjunction in the body
    ("and also", "as well as", "along with"; plus "in addition"/"also" when they
    follow a clause boundary):
        Truncated before the conjunction, then a '?' is appended to preserve
        the first question's interrogative nature.

    Single questions — including those with clarifying sub-clauses that use
    a single '?', and single questions with a scenario-setup sentence — are
    returned unchanged.

    Edge cases:
    - Empty string → returned unchanged.
    """
    if not spoken_text:
        return spoken_text

    question_mark_count = spoken_text.count("?")

    # Shape A: two or more explicit question marks → truncate after first.
    if question_mark_count >= 2:
        first_q = spoken_text.find("?")
        return spoken_text[: first_q + 1].rstrip()

    # Shape C: multiple asks across sentences (0-1 '?'). Keep up to the first ask.
    sentences = re.split(r"(?<=[.!?])\s+", spoken_text.strip())
    if len(sentences) > 1:
        ask_indices = [i for i, s in enumerate(sentences) if _is_ask_sentence(s)]
        if len(ask_indices) >= 2:
            return " ".join(sentences[: ask_indices[0] + 1]).strip()

    if question_mark_count == 0:
        # No question at all — pass through (acknowledgement, statement, etc.).
        return spoken_text

    # question_mark_count == 1 from here.
    # Shape B: single terminal '?' with a compound conjunction in the body.
    # Order matters: check longer/more-specific conjunctions before shorter ones
    # to avoid "and also" being split on "and".
    text_lower = spoken_text.lower()
    for conj in ["and also", "as well as", "along with"]:
        idx = text_lower.find(conj)
        if idx == -1:
            continue
        # Verify there is meaningful content before the conjunction (heuristic:
        # at least one word of 3+ chars before it) and meaningful content after
        # it before the final '?' (at least one word of 3+ chars after it).
        before = spoken_text[:idx].strip(" ,")
        after = spoken_text[idx + len(conj):].strip(" ,?")
        before_words = [w for w in before.split() if len(w) >= 3]
        after_words = [w for w in after.split() if len(w) >= 3]
        if len(before_words) >= 2 and len(after_words) >= 2:
            # Truncate before the conjunction and re-add '?'.
            return before.rstrip(" ,") + "?"

    # Boundary connectors ("in addition", "also") — only when they follow a comma
    # or semicolon, so mid-question adverbs are not falsely split.
    for conj in _BOUNDARY_CONNECTORS:
        m = re.search(r"[,;]\s*" + re.escape(conj) + r"\b", text_lower)
        if not m:
            continue
        before = spoken_text[: m.start()].strip(" ,;")
        after = spoken_text[m.end():].strip(" ,;?")
        before_words = [w for w in before.split() if len(w) >= 3]
        after_words = [w for w in after.split() if len(w) >= 3]
        if len(before_words) >= 2 and len(after_words) >= 2:
            return before.rstrip(" ,;") + "?"

    return spoken_text
