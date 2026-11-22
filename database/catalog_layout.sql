ALTER TABLE seasons ADD COLUMN sort_order BIGINT;
ALTER TABLE episodes ADD COLUMN sort_order BIGINT;
ALTER TABLE standalone_videos ADD COLUMN sort_order BIGINT;
ALTER TABLE standalone_videos ADD COLUMN season_id BIGINT REFERENCES seasons(id) ON DELETE SET NULL;
ALTER TABLE standalone_videos ADD COLUMN poster_file_id TEXT;
CREATE INDEX idx_standalone_season ON standalone_videos(season_id);
