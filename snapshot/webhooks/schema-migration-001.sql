-- Migration 001: Phase 4.1 R2-binding refactor
--
-- Adds columns needed for the Worker-served /api/pdf/:token pattern
-- (replaces R2 S3-presigned URLs).
--
-- Apply to existing D1:
--   wrangler d1 execute securva-snapshot --remote --file=./schema-migration-001.sql
--
-- Safe to run multiple times (IF NOT EXISTS guards).

ALTER TABLE jobs ADD COLUMN pdf_r2_key TEXT;
ALTER TABLE jobs ADD COLUMN download_token TEXT;

CREATE INDEX IF NOT EXISTS idx_jobs_download_token ON jobs(download_token);
