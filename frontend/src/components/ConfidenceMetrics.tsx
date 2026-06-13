"use client";

interface ConfidenceMetricsProps {
  avgTranscriptionConfidence: number;
  avgEvaluationConfidence: number;
  qaExtractionConfidence: number;
  interviewType: string;
}

function confidenceColor(value: number): string {
  if (value >= 0.8) return "text-green-700 bg-green-50 border-green-200";
  if (value >= 0.6) return "text-blue-700 bg-blue-50 border-blue-200";
  if (value >= 0.4) return "text-yellow-700 bg-yellow-50 border-yellow-200";
  return "text-red-700 bg-red-50 border-red-200";
}

function confidenceBarColor(value: number): string {
  if (value >= 0.8) return "bg-green-500";
  if (value >= 0.6) return "bg-blue-500";
  if (value >= 0.4) return "bg-yellow-500";
  return "bg-red-400";
}

interface MetricCardProps {
  label: string;
  value: number;
  description: string;
  trivial?: boolean;
}

function MetricCard({ label, value, description, trivial }: MetricCardProps) {
  return (
    <div className={`rounded-xl border p-4 ${confidenceColor(value)}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium">{label}</span>
        <span className="text-lg font-bold">{(value * 100).toFixed(0)}%</span>
      </div>
      <div className="h-2 bg-white/60 rounded-full overflow-hidden mb-2">
        <div
          className={`h-full rounded-full transition-all ${confidenceBarColor(value)}`}
          style={{ width: `${value * 100}%` }}
        />
      </div>
      <p className="text-xs opacity-80">
        {description}
        {trivial && " (exact for typed input)"}
      </p>
    </div>
  );
}

export default function ConfidenceMetrics({
  avgTranscriptionConfidence,
  avgEvaluationConfidence,
  qaExtractionConfidence,
  interviewType,
}: ConfidenceMetricsProps) {
  const isText = interviewType === "text";

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
      <h3 className="font-semibold text-slate-900 mb-4">Confidence Metrics</h3>
      <div className="grid sm:grid-cols-3 gap-4">
        <MetricCard
          label="Transcription"
          value={avgTranscriptionConfidence}
          description="How reliable is the input text"
          trivial={isText}
        />
        <MetricCard
          label="Q&A Extraction"
          value={qaExtractionConfidence}
          description="How well Q&A pairs were identified"
          trivial={isText}
        />
        <MetricCard
          label="Answer Evaluation"
          value={avgEvaluationConfidence}
          description="AI confidence in its scoring"
        />
      </div>
    </div>
  );
}
