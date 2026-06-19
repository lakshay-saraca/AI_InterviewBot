from typing import Optional
from pydantic import BaseModel, Field
from src.types.interview import ExperienceLevel, Question


class JDSummary(BaseModel):
    skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    seniority_signals: list[str] = Field(default_factory=list)


class InterviewPlan(BaseModel):
    """Frozen, ordered scored questions for a config.

    Order is fixed: [core...] -> [jd...] -> behavioral -> project_deepdive.
    warmup/outro are structural phases handled by the run flow, not entries here.
    """
    questions: list[Question] = Field(default_factory=list)
    has_warmup: bool = True
    has_outro: bool = True


class InterviewConfig(BaseModel):
    id: str
    title: str
    role: str
    experience_level: ExperienceLevel
    job_description: str
    total_questions: int
    core_question_ratio: float = 0.8
    jd_summary: JDSummary = Field(default_factory=JDSummary)
    interview_plan: InterviewPlan = Field(default_factory=InterviewPlan)
    created_at: Optional[str] = None
