-- LapisLazuli lazuli DB — migration 0005: design-choice metadata for every local face
-- NULL marks old rows for a metadata refresh on the next scan, even when size/mtime or the Core Text
-- version token did not change. Refreshing metadata alone keeps measurements, matches, embeddings,
-- catalogs, and the user's color records and classes. New scans store an object even for empty metadata.
ALTER TABLE local_font ADD COLUMN metadata_json TEXT;

-- Prompt a scan at session start; the old fingerprint did not account for the missing metadata.
DELETE FROM meta WHERE key = 'inventory_fingerprint';

PRAGMA user_version = 5;
