ALTER TABLE job_track ADD COLUMN run_id TEXT REFERENCES analysis_run(id);
ALTER TABLE job_track ADD COLUMN analysis_json TEXT;
