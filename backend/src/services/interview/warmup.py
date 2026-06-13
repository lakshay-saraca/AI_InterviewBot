import random
from typing import Callable

_TEMPLATES: list[Callable[[str, str], str]] = [
    lambda name, _role: f"How are you, {name}? How did your day go?",
    lambda name, _role: f"Before we dive in, {name} — what was your most recent role, and what brought you here today?",
    lambda name, role: f"To kick things off, {name} — where did you study, and how did you get into {role}?",
    lambda name, _role: f"Good to meet you, {name}. Anything exciting going on before we get started?",
]


def generate_warmup_question(candidate_name: str, job_role: str) -> str:
    template = random.choice(_TEMPLATES)
    return template(candidate_name, job_role)
