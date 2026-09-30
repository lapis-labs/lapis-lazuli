-- LapisLazuli lazuli DB — migration 0003: font classes the user gave (`lazuli class`)
-- A user class is one family's genre, and optionally a subclass of it, as the user read it somewhere (for
-- example on a catalog page lazuli never collects from), with an optional link to that page. It holds only
-- those values: no font files and no page content, and the link is never opened. Like `color_record`,
-- these rows cannot be rebuilt; they live in the user cache only and never go into a project or the
-- repository.

CREATE TABLE user_label (
  family_norm  TEXT PRIMARY KEY,               -- the family name normalized like local_font.family_norm
  family       TEXT NOT NULL,                  -- the family as labeled (the lazuli DB's name when it knows one)
  genre        TEXT NOT NULL,                  -- a genre or Hangul class id (vocab/type.yaml via catalog/labels.py)
  subclass     TEXT,                           -- a `genre.subclass` id of that genre, or null
  url          TEXT,                           -- where the user read the class (http or https), or null
  recorded_at  TEXT NOT NULL,                  -- ISO 8601
  CHECK (subclass IS NULL OR substr(subclass, 1, length(genre) + 1) = genre || '.'),
  CHECK (url IS NULL OR url LIKE 'http://%' OR url LIKE 'https://%')
);

-- The user's label outranks every catalog: the resolved view gives it for the installed faces of that family
-- as source `user` with priority 0 (catalog priorities start at 10; `store.USER_PRIORITY`) and full confidence.
-- `labels.resolve` takes genre and subclass together from one source, so the label replaces a catalog's
-- class and leaves its other kinds (license, scripts) in place.
DROP VIEW v_font_label;
CREATE VIEW v_font_label AS
SELECT lf.id AS local_font_id, lf.family, cl.kind, cl.mapped, cl.raw, s.name AS source, s.priority, m.confidence
FROM local_font lf
JOIN match m ON m.local_font_id = lf.id
JOIN source s ON s.id = m.source_id
JOIN catalog_label cl ON cl.source_id = m.source_id AND cl.source_key = m.source_key
UNION ALL
SELECT lf.id, lf.family, 'genre', ul.genre, ul.genre, 'user', 0, 1.0
FROM local_font lf JOIN user_label ul ON ul.family_norm = lf.family_norm
UNION ALL
SELECT lf.id, lf.family, 'subclass', ul.subclass, ul.subclass, 'user', 0, 1.0
FROM local_font lf JOIN user_label ul ON ul.family_norm = lf.family_norm
WHERE ul.subclass IS NOT NULL;

PRAGMA user_version = 3;
