-- Add interview_type to distinguish text vs voice interviews

ALTER TABLE interview_reports
    ADD COLUMN IF NOT EXISTS interview_type VARCHAR(16) NOT NULL DEFAULT 'text';

CREATE INDEX IF NOT EXISTS idx_interview_reports_type ON interview_reports(interview_type);
