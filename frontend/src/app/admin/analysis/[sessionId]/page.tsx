"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import AdminGuard from "@/components/AdminGuard";
import ScoreBadge from "@/components/ScoreBadge";
import ConfidenceMetrics from "@/components/ConfidenceMetrics";
import TranscriptTimeline from "@/components/TranscriptTimeline";
import { getInterviewDetail } from "@/services/admin-api";
import type { InterviewDetail } from "@/types/admin";

const RECOMMENDATION_LABELS: Record<string, { label: string; color: string }> = {
  strong_yes: { label: "Strong Yes", color: "bg-green-100 text-green-800 border-green-200" },
  yes: { label: "Yes", color: "bg-blue-100 text-blue-800 border-blue-200" },
  maybe: { label: "Maybe", color: "bg-yellow-100 text-yellow-800 border-yellow-200" },
  no: { label: "No", color: "bg-orange-100 text-orange-800 border-orange-200" },
  strong_no: { label: "Strong No", color: "bg-red-100 text-red-800 border-red-200" },
};

function formatDate(iso: string | null): string {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function confidenceLabel(value: number | null | undefined): { text: string; color: string } {
  if (value === null || value === undefined) return { text: "N/A", color: "text-slate-400" };
  if (value >= 0.8) return { text: "High", color: "text-green-600" };
  if (value >= 0.6) return { text: "Medium", color: "text-blue-600" };
  if (value >= 0.4) return { text: "Low", color: "text-yellow-600" };
  return { text: "Very Low", color: "text-red-600" };
}

export default function AnalysisPage() {
  const params = useParams();
  const sessionId = params.sessionId as string;

  const [detail, setDetail] = useState<InterviewDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!sessionId) return;
    setLoading(true);
    setError("");
    getInterviewDetail(sessionId)
      .then(setDetail)
      .catch((err) => {
        setError(err.detail ?? err.message ?? "Failed to load interview.");
      })
      .finally(() => setLoading(false));
  }, [sessionId]);

  if (loading) {
    return (
      <AdminGuard>
        <div className="flex items-center justify-center min-h-[50vh]">
          <p className="text-slate-500 text-sm">Loading analysis...</p>
        </div>
      </AdminGuard>
    );
  }

  if (error || !detail) {
    return (
      <AdminGuard>
        <div className="space-y-4">
          <Link href="/admin/history" className="text-sm text-blue-600 hover:text-blue-700">
            &larr; Back to History
          </Link>
          <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
            <p className="text-red-700">{error || "Interview not found."}</p>
          </div>
        </div>
      </AdminGuard>
    );
  }

  const rec = RECOMMENDATION_LABELS[detail.recommendation] ?? {
    label: detail.recommendation,
    color: "bg-slate-100 text-slate-800 border-slate-200",
  };

  const durationStr = detail.duration_seconds
    ? `${Math.floor(detail.duration_seconds / 60)}m ${detail.duration_seconds % 60}s`
    : null;

  return (
    <AdminGuard>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <Link href="/admin/history" className="text-sm text-blue-600 hover:text-blue-700">
            &larr; Back to History
          </Link>
          <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
            detail.interview_type === "voice"
              ? "bg-violet-50 text-violet-700"
              : "bg-blue-50 text-blue-700"
          }`}>
            {detail.interview_type} interview
          </span>
        </div>

        {/* Header card */}
        <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-4">
            <div>
              <h1 className="text-2xl font-bold text-slate-900">
                {detail.candidate_name}
              </h1>
              <p className="text-slate-500">
                {detail.job_role} &middot; {detail.experience_level}
                {durationStr && ` · ${durationStr}`}
                {detail.started_at && ` · ${formatDate(detail.started_at)}`}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <ScoreBadge score={detail.overall_score} size="lg" />
              <span className={`text-sm font-semibold px-3 py-1.5 rounded-full border ${rec.color}`}>
                {rec.label}
              </span>
            </div>
          </div>
          {detail.summary && (
            <p className="text-slate-700 text-sm leading-relaxed bg-slate-50 rounded-lg p-4">
              {detail.summary}
            </p>
          )}
        </div>

        {/* Confidence metrics */}
        <ConfidenceMetrics
          avgTranscriptionConfidence={detail.avg_transcription_confidence}
          avgEvaluationConfidence={detail.avg_evaluation_confidence}
          qaExtractionConfidence={detail.qa_extraction_confidence}
          interviewType={detail.interview_type}
        />

        {/* Strengths & Weaknesses */}
        {(detail.strengths.length > 0 || detail.weaknesses.length > 0) && (
          <div className="grid sm:grid-cols-2 gap-4">
            {detail.strengths.length > 0 && (
              <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
                <h3 className="font-semibold text-green-700 mb-3">Strengths</h3>
                <ul className="space-y-2">
                  {detail.strengths.map((s, i) => (
                    <li key={i} className="text-sm text-slate-700 flex gap-2">
                      <span className="text-green-500 mt-0.5 shrink-0">&bull;</span>
                      {s}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {detail.weaknesses.length > 0 && (
              <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
                <h3 className="font-semibold text-orange-700 mb-3">Areas to Improve</h3>
                <ul className="space-y-2">
                  {detail.weaknesses.map((w, i) => (
                    <li key={i} className="text-sm text-slate-700 flex gap-2">
                      <span className="text-orange-400 mt-0.5 shrink-0">&bull;</span>
                      {w}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Topic Scores */}
        {Object.keys(detail.topic_scores).length > 0 && (
          <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
            <h3 className="font-semibold text-slate-900 mb-4">Scores by Topic</h3>
            <div className="space-y-3">
              {Object.entries(detail.topic_scores).map(([topic, score]) => {
                const topicConf = detail.per_topic_confidence[topic];
                const conf = confidenceLabel(topicConf);
                return (
                  <div key={topic} className="flex items-center gap-3">
                    <span className="text-sm text-slate-600 w-32 capitalize shrink-0">
                      {topic.replace(/_/g, " ")}
                    </span>
                    <div className="flex-1 h-2.5 bg-slate-100 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${
                          score >= 8 ? "bg-green-500"
                          : score >= 6 ? "bg-blue-500"
                          : score >= 4 ? "bg-yellow-500"
                          : "bg-red-400"
                        }`}
                        style={{ width: `${(score / 10) * 100}%` }}
                      />
                    </div>
                    <span className="text-sm font-medium text-slate-700 w-10 text-right">
                      {score.toFixed(1)}
                    </span>
                    {topicConf !== undefined && (
                      <span className={`text-xs w-16 text-right ${conf.color}`}>
                        {conf.text}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Category Scores (voice-mode only, when available) */}
        {Object.keys(detail.category_scores).length > 0 && (
          <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
            <h3 className="font-semibold text-slate-900 mb-4">Category Scores</h3>
            <div className="grid sm:grid-cols-2 gap-4">
              {Object.entries(detail.category_scores).map(([category, cs]) => (
                <div key={category} className="border border-slate-100 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium text-slate-800 capitalize">
                      {category.replace(/_/g, " ")}
                    </span>
                    <ScoreBadge score={cs.score} size="sm" />
                  </div>
                  {cs.explanation && (
                    <p className="text-xs text-slate-600 mb-1">{cs.explanation}</p>
                  )}
                  {cs.evidence && (
                    <p className="text-xs text-slate-400 italic">{cs.evidence}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Per-Question Breakdown */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
          <h3 className="font-semibold text-slate-900 mb-4">Question-Answer Analysis</h3>
          {detail.per_question.length === 0 ? (
            <p className="text-sm text-slate-500">No question data available.</p>
          ) : (
            <div className="space-y-4">
              {detail.per_question.map((q, i) => {
                const questionText = q.question_text ?? q.question ?? `Question ${i + 1}`;
                const answerText = q.answer_text ?? q.answer ?? "";
                const reasoning = q.score_reasoning ?? q.reasoning ?? "";
                const conf = confidenceLabel(q.confidence);

                return (
                  <div key={i} className="border border-slate-100 rounded-lg p-4 space-y-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-medium text-slate-800">
                          Q{i + 1}: {questionText}
                        </p>
                        {q.topic && (
                          <p className="text-xs text-slate-400 capitalize mt-0.5">
                            Topic: {q.topic.replace(/_/g, " ")}
                          </p>
                        )}
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {q.score != null && <ScoreBadge score={q.score} size="sm" />}
                        <span className={`text-xs ${conf.color}`}>
                          {conf.text}
                        </span>
                      </div>
                    </div>

                    {answerText && (
                      <div className="bg-slate-50 rounded-lg p-3">
                        <p className="text-xs text-slate-400 mb-1 font-medium">Candidate Answer</p>
                        <p className="text-sm text-slate-700">{answerText}</p>
                      </div>
                    )}

                    {reasoning && (
                      <div className="bg-blue-50 rounded-lg p-3">
                        <p className="text-xs text-blue-400 mb-1 font-medium">AI Evaluation</p>
                        <p className="text-sm text-slate-700">{reasoning}</p>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Transcript */}
        {detail.transcript.length > 0 && (
          <TranscriptTimeline transcript={detail.transcript} />
        )}
      </div>
    </AdminGuard>
  );
}
