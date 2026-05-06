-- Add admin-assigned primary lecturer to courses.
-- Safe to run multiple times.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_name='courses' AND column_name='lecturer_id'
  ) THEN
    ALTER TABLE courses
      ADD COLUMN lecturer_id BIGINT NULL REFERENCES lecturers(id) ON DELETE SET NULL;
    CREATE INDEX IF NOT EXISTS idx_courses_lecturer_id ON courses(lecturer_id);
  END IF;
END $$;

