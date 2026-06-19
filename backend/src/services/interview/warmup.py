import random
from typing import Callable, Optional

_TEMPLATES: list[Callable[[str, str], str]] = [
    lambda name, _role: f"How are you, {name}? How did your day go?",
    lambda name, _role: f"Before we dive in, {name} — what was your most recent role, and what brought you here today?",
    lambda name, role: f"To kick things off, {name} — where did you study, and how did you get into {role}?",
    lambda name, _role: f"Good to meet you, {name}. Anything exciting going on before we get started?",
]

_FOLLOWUP_TEMPLATES: list[Callable[[str, str], str]] = [
    lambda name, role: f"That's great to hear, {name}. What are you most looking forward to in your next {role} role?",
    lambda name, _role: f"Love it. And {name}, what kind of work gets you most excited these days?",
    lambda name, _role: f"Nice! {name}, outside of work — anything you've been enjoying lately, or just keeping busy?",
    lambda name, role: f"Sounds good, {name}. What first got you interested in {role} work?",
]


def generate_warmup_question(candidate_name: str, job_role: str) -> str:
    template = random.choice(_TEMPLATES)
    return template(candidate_name, job_role)


def generate_warmup_followup(candidate_name: str, job_role: str) -> str:
    template = random.choice(_FOLLOWUP_TEMPLATES)
    return template(candidate_name, job_role)


def generate_transition_message(candidate_name: str) -> str:
    return f"Thanks for sharing that, {candidate_name}! Now let's get into the technical questions."


def estimate_session_minutes(total_questions: int) -> int:
    """Round total_questions * 6 min/question to the nearest 5 minutes."""
    return round(total_questions * 6 / 5) * 5


def generate_introduction(candidate_name: str, job_role: str, total_questions: int) -> str:
    duration = estimate_session_minutes(total_questions)
    return (
        f"Hi {candidate_name}! I'm your AI interviewer today. "
        f"We have a {job_role} session lined up — {total_questions} technical questions "
        f"after a quick warm-up. The whole thing should take about {duration} minutes."
    )


# Only these resume fields are ever read into warmup text. Everything else
# (phone, email, linkedin_url, current_location, country_code) is PII and is
# never touched — enforced here and asserted in tests.
_WARMUP_WHITELIST = ("skills", "current_company")


def personalize_warmup(
    candidate_name: str,
    job_role: str,
    details: Optional[dict],
) -> str:
    """Build one warmup line from whitelisted resume fields, or fall back generic.

    No LLM. Reads ONLY `skills` and `current_company`.
    """
    if not details:
        return generate_warmup_question(candidate_name, job_role)

    company = (details.get("current_company") or "").strip()
    skills = details.get("skills") or []
    top_skill = (skills[0].strip() if skills and isinstance(skills[0], str) else "")

    if company and top_skill:
        return (
            f"Hi {candidate_name}! Before we dig in — I see you've been at {company} "
            f"working with {top_skill}. What have you most enjoyed building there?"
        )
    if company:
        return (
            f"Hi {candidate_name}! Before we dig in — I see you've been at {company}. "
            f"What have you most enjoyed working on there?"
        )
    # No usable whitelisted field → generic, still name-personalized.
    return generate_warmup_question(candidate_name, job_role)
