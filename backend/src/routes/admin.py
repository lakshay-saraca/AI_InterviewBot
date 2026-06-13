import logging
from fastapi import APIRouter, HTTPException, Header, Depends, Query, status
from src.lib.settings import get_settings
from src.types.admin import InterviewListResponse, InterviewSummary, InterviewDetailResponse
from src.models.interview_report import list_reports, get_report_by_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


async def require_admin(x_admin_key: str = Header(default="")) -> None:
    settings = get_settings()
    if not x_admin_key or x_admin_key != settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin API key.",
        )


@router.get(
    "/interviews",
    response_model=InterviewListResponse,
    dependencies=[Depends(require_admin)],
)
async def list_interviews(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> InterviewListResponse:
    offset = (page - 1) * limit
    reports, total = await list_reports(limit=limit, offset=offset)

    summaries = []
    for r in reports:
        summaries.append(InterviewSummary(
            session_id=r.session_id,
            candidate_name=r.candidate_name,
            job_role=r.job_role,
            experience_level=r.experience_level,
            interview_type=r.interview_type,
            overall_score=r.analysis.overall_score,
            recommendation=r.analysis.hiring_recommendation,
            started_at=r.started_at,
            ended_at=r.ended_at,
            duration_seconds=r.duration_seconds,
            created_at=r.created_at,
        ))

    return InterviewListResponse(
        interviews=summaries,
        total=total,
        page=page,
        limit=limit,
    )


@router.get(
    "/interviews/{session_id}",
    response_model=InterviewDetailResponse,
    dependencies=[Depends(require_admin)],
)
async def get_interview_detail(session_id: str) -> InterviewDetailResponse:
    report = await get_report_by_session(session_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Interview not found.",
        )

    category_scores = {}
    for field_name in ("communication_clarity", "technical_depth", "confidence_consistency", "relevance"):
        cs = getattr(report.analysis, field_name, None)
        if cs and cs.score > 0:
            category_scores[field_name] = {
                "score": cs.score,
                "explanation": cs.explanation,
                "evidence": cs.evidence,
            }

    return InterviewDetailResponse(
        session_id=report.session_id,
        candidate_name=report.candidate_name,
        job_role=report.job_role,
        experience_level=report.experience_level,
        interview_type=report.interview_type,
        overall_score=report.analysis.overall_score,
        recommendation=report.analysis.hiring_recommendation,
        strengths=report.analysis.strengths,
        weaknesses=report.analysis.weaknesses,
        summary=report.analysis.summary,
        per_question=report.analysis.per_question,
        topic_scores=report.analysis.topic_scores,
        transcript=report.transcript,
        started_at=report.started_at,
        ended_at=report.ended_at,
        duration_seconds=report.duration_seconds,
        created_at=report.created_at,
        avg_transcription_confidence=report.metrics.avg_transcription_confidence,
        avg_evaluation_confidence=report.metrics.avg_evaluation_confidence,
        qa_extraction_confidence=report.metrics.qa_extraction_confidence,
        per_topic_confidence=report.metrics.per_topic_confidence,
        category_scores=category_scores,
    )
