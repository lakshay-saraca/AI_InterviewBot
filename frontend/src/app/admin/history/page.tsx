"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import AdminGuard from "@/components/AdminGuard";
import ScoreBadge from "@/components/ScoreBadge";
import { listInterviews } from "@/services/admin-api";
import type { InterviewSummary } from "@/types/admin";

const RECOMMENDATION_LABELS: Record<string, { label: string; color: string }> = {
  strong_yes: { label: "Strong Yes", color: "text-green-700 bg-green-50" },
  yes: { label: "Yes", color: "text-blue-700 bg-blue-50" },
  maybe: { label: "Maybe", color: "text-yellow-700 bg-yellow-50" },
  no: { label: "No", color: "text-orange-700 bg-orange-50" },
  strong_no: { label: "Strong No", color: "text-red-700 bg-red-50" },
};

function formatDate(iso: string | null): string {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleDateString("en-US", {
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

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "-";
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}m ${secs}s`;
}

export default function HistoryPage() {
  const [interviews, setInterviews] = useState<InterviewSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const limit = 20;

  useEffect(() => {
    setLoading(true);
    setError("");
    listInterviews(page, limit)
      .then((data) => {
        setInterviews(data.interviews);
        setTotal(data.total);
      })
      .catch((err) => {
        setError(err.detail ?? err.message ?? "Failed to load interviews.");
      })
      .finally(() => setLoading(false));
  }, [page]);

  const totalPages = Math.ceil(total / limit);

  return (
    <AdminGuard>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Interview History</h1>
            <p className="text-sm text-slate-500 mt-1">
              {total} interview{total !== 1 ? "s" : ""} on record
            </p>
          </div>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
            {error}
          </div>
        )}

        {loading ? (
          <div className="bg-white rounded-xl border border-slate-200 p-12 text-center">
            <p className="text-slate-500 text-sm">Loading interviews...</p>
          </div>
        ) : interviews.length === 0 ? (
          <div className="bg-white rounded-xl border border-slate-200 p-12 text-center">
            <p className="text-slate-500">No interviews found.</p>
            <p className="text-sm text-slate-400 mt-1">
              Completed interviews will appear here.
            </p>
          </div>
        ) : (
          <>
            <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 bg-slate-50">
                      <th className="text-left px-4 py-3 font-medium text-slate-600">Candidate</th>
                      <th className="text-left px-4 py-3 font-medium text-slate-600">Role</th>
                      <th className="text-left px-4 py-3 font-medium text-slate-600">Type</th>
                      <th className="text-left px-4 py-3 font-medium text-slate-600">Score</th>
                      <th className="text-left px-4 py-3 font-medium text-slate-600">Recommendation</th>
                      <th className="text-left px-4 py-3 font-medium text-slate-600">Duration</th>
                      <th className="text-left px-4 py-3 font-medium text-slate-600">Date</th>
                      <th className="text-right px-4 py-3 font-medium text-slate-600"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {interviews.map((interview) => {
                      const rec = RECOMMENDATION_LABELS[interview.recommendation] ?? {
                        label: interview.recommendation,
                        color: "text-slate-700 bg-slate-50",
                      };
                      return (
                        <tr key={interview.session_id} className="hover:bg-slate-50 transition-colors">
                          <td className="px-4 py-3 font-medium text-slate-900">
                            {interview.candidate_name}
                          </td>
                          <td className="px-4 py-3 text-slate-600">
                            {interview.job_role}
                            <span className="text-slate-400 ml-1 text-xs capitalize">
                              ({interview.experience_level})
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                              interview.interview_type === "voice"
                                ? "bg-violet-50 text-violet-700"
                                : "bg-blue-50 text-blue-700"
                            }`}>
                              {interview.interview_type}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <ScoreBadge score={interview.overall_score} size="sm" />
                          </td>
                          <td className="px-4 py-3">
                            <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${rec.color}`}>
                              {rec.label}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-slate-600">
                            {formatDuration(interview.duration_seconds)}
                          </td>
                          <td className="px-4 py-3 text-slate-500">
                            {formatDate(interview.started_at)}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <Link
                              href={`/admin/analysis/${interview.session_id}`}
                              className="text-sm font-medium text-blue-600 hover:text-blue-700 transition-colors"
                            >
                              View Analysis
                            </Link>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {totalPages > 1 && (
              <div className="flex items-center justify-between">
                <p className="text-sm text-slate-500">
                  Page {page} of {totalPages}
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1}
                    className="px-3 py-1.5 text-sm rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    Previous
                  </button>
                  <button
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page >= totalPages}
                    className="px-3 py-1.5 text-sm rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </AdminGuard>
  );
}
