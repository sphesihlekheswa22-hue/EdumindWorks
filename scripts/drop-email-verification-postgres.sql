-- Drop legacy email verification + OTP reset schema (Postgres).
-- Safe to run multiple times (uses IF EXISTS).
--
-- Run this against your Render Postgres database using psql or Render's shell.
-- Example:
--   psql "$DATABASE_URL" -f scripts/drop-email-verification-postgres.sql

BEGIN;

-- OTP table (used for email OTP flows)
DROP TABLE IF EXISTS otps CASCADE;

-- Users table columns that are no longer used by the app.
ALTER TABLE IF EXISTS users
  DROP COLUMN IF EXISTS email_verified,
  DROP COLUMN IF EXISTS email_verification_token,
  DROP COLUMN IF EXISTS email_verification_expires_at,
  DROP COLUMN IF EXISTS reset_token,
  DROP COLUMN IF EXISTS reset_token_expires_at;

COMMIT;

