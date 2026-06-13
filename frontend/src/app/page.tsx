"use client";

import Link from "next/link";
import { useAuth } from "@/contexts/AuthContext";

export default function HomePage() {
  const { user, isAdmin } = useAuth();

  return (
    <div className="flex flex-col items-center justify-center min-h-[70vh] text-center">
      <div className="max-w-2xl">
        <h1 className="text-4xl font-bold text-slate-900 mb-4">
          AI-Powered Technical Interviews
        </h1>
        <p className="text-lg text-slate-600 mb-8">
          Practice realistic technical interviews with instant AI feedback.
          Get scored on your answers and receive detailed improvement tips.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-10 text-left">
          <FeatureCard
            title="Smart Questions"
            description="Role-specific questions tailored to your experience level"
          />
          <FeatureCard
            title="AI Evaluation"
            description="Claude evaluates every answer with a score and reasoning"
          />
          <FeatureCard
            title="Detailed Report"
            description="Full scorecard with strengths, weaknesses, and recommendations"
          />
        </div>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
          <Link
            href={user ? "/interview/mode-select" : "/login"}
            className="inline-block bg-blue-600 hover:bg-blue-700 text-white font-semibold px-8 py-4 rounded-xl text-lg transition-colors"
          >
            Start an Interview
          </Link>
          {isAdmin && (
            <Link
              href="/admin/history"
              className="inline-block border border-slate-300 hover:bg-slate-50 text-slate-700 font-semibold px-8 py-4 rounded-xl text-lg transition-colors"
            >
              View History
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}

function FeatureCard({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="bg-white rounded-xl p-5 border border-slate-200 shadow-sm">
      <h3 className="font-semibold text-slate-900 mb-1">{title}</h3>
      <p className="text-sm text-slate-500">{description}</p>
    </div>
  );
}
