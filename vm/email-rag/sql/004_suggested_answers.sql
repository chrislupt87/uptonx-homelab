-- Add AI-suggested answer columns to suggested_questions
ALTER TABLE suggested_questions ADD COLUMN IF NOT EXISTS suggested_answer TEXT;
ALTER TABLE suggested_questions ADD COLUMN IF NOT EXISTS suggested_category TEXT;
ALTER TABLE suggested_questions ADD COLUMN IF NOT EXISTS suggested_subject TEXT;
