from typing import Optional
from pydantic import BaseModel, Field, field_validator
from .interview import ExperienceLevel


class InterviewSummary(BaseModel):
    session_id: str
    candidate_name: str
    job_role: str
    experience_level: str
    interview_type: str
    overall_score: float
    recommendation: str
    started_at: Optional[str]
    ended_at: Optional[str]
    duration_seconds: Optional[int]
    created_at: Optional[str]


class InterviewListResponse(BaseModel):
    interviews: list[InterviewSummary]
    total: int
    page: int
    limit: int


class InterviewDetailResponse(BaseModel):
    session_id: str
    candidate_name: str
    job_role: str
    experience_level: str
    interview_type: str
    overall_score: float
    recommendation: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    summary: str = ""
    per_question: list[dict] = Field(default_factory=list)
    topic_scores: dict[str, float] = Field(default_factory=dict)
    transcript: list[dict] = Field(default_factory=list)
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    created_at: Optional[str] = None
    avg_transcription_confidence: float = 1.0
    avg_evaluation_confidence: float = 0.0
    qa_extraction_confidence: float = 1.0
    per_topic_confidence: dict[str, float] = Field(default_factory=dict)
    category_scores: dict[str, dict] = Field(default_factory=dict)


class CreateConfigRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=100)
    experience_level: ExperienceLevel
    job_description: str = Field(min_length=1, max_length=20000)
    total_questions: int = Field(ge=4, le=20)
    core_question_ratio: float = Field(default=0.8, gt=0, lt=1)

    @field_validator("job_description")
    def jd_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("job_description must not be blank")
        return v


class ConfigResponse(BaseModel):
    id: str
    title: str
    role: str
    experience_level: str
    total_questions: int
    core_question_ratio: float
    created_at: Optional[str] = None


class ConfigListResponse(BaseModel):
    configs: list[ConfigResponse]
    total: int
