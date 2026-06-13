from typing import Optional
from pydantic import BaseModel, Field


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
