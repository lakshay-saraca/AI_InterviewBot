export interface InterviewSummary {
  session_id: string;
  candidate_name: string;
  job_role: string;
  experience_level: string;
  interview_type: string;
  overall_score: number;
  recommendation: string;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  created_at: string | null;
}

export interface InterviewListResponse {
  interviews: InterviewSummary[];
  total: number;
  page: number;
  limit: number;
}

export interface CategoryScore {
  score: number;
  explanation: string;
  evidence: string;
}

export interface InterviewDetail {
  session_id: string;
  candidate_name: string;
  job_role: string;
  experience_level: string;
  interview_type: string;
  overall_score: number;
  recommendation: string;
  strengths: string[];
  weaknesses: string[];
  summary: string;
  per_question: Array<{
    question_id?: string;
    question_text?: string;
    question?: string;
    topic?: string;
    answer_text?: string;
    answer?: string;
    score?: number | null;
    score_reasoning?: string;
    reasoning?: string;
    confidence?: number | null;
  }>;
  topic_scores: Record<string, number>;
  transcript: Array<{
    speaker: string;
    text: string;
    timestamp?: string;
    type?: string;
    turn_idx?: number;
    question_id?: string | null;
  }>;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  created_at: string | null;
  avg_transcription_confidence: number;
  avg_evaluation_confidence: number;
  qa_extraction_confidence: number;
  per_topic_confidence: Record<string, number>;
  category_scores: Record<string, CategoryScore>;
}
