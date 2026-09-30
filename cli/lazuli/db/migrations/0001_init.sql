-- LapisLazuli lazuli DB — migration 0001 (v0 draft)
-- Location: user cache (e.g. ~/.cache/lazuli/lazuli.db), never inside a synced folder.
-- Everything here can be rebuilt by re-syncing catalogs and re-scanning fonts.
-- Requires SQLite >= 3.34 for the FTS5 trigram tokenizer.


-- ---------------------------------------------------------------- sources
CREATE TABLE source (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,            -- google-fonts, fontsource, fontshare, adobe-cjk, noonnu, sandoll, anshim, system-table
  kind        TEXT NOT NULL CHECK (kind IN ('snapshot', 'lookup', 'bundled')),
  priority    INTEGER NOT NULL,                -- lower wins (original sources before supplements)
  fetched_at  TEXT,                            -- ISO 8601
  ttl_days    INTEGER,
  status      TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'stale', 'failed', 'disabled'))
);

-- Raw responses kept compressed so mapping rules can be re-applied without re-fetching
CREATE TABLE raw_payload (
  source_id   INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  request_key TEXT NOT NULL,
  fetched_at  TEXT NOT NULL,
  body_gz     BLOB NOT NULL,
  PRIMARY KEY (source_id, request_key)
);

-- ---------------------------------------------------------------- catalogs
CREATE TABLE catalog_family (
  source_id       INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  source_key      TEXT NOT NULL,               -- the catalog's own id or slug
  family          TEXT NOT NULL,
  family_norm     TEXT NOT NULL,               -- lowercased, punctuation and spaces removed
  names_i18n_json TEXT,                        -- {"ko": "...", "ja": "..."}
  foundry         TEXT,
  designers_json  TEXT,
  license         TEXT,
  url             TEXT,
  PRIMARY KEY (source_id, source_key)
);
CREATE INDEX catalog_family_norm ON catalog_family(family_norm);

CREATE TABLE catalog_font (
  source_id       INTEGER NOT NULL,
  source_key      TEXT NOT NULL,
  postscript_name TEXT NOT NULL,
  style           TEXT,
  weight          INTEGER,
  PRIMARY KEY (source_id, source_key, postscript_name),
  FOREIGN KEY (source_id, source_key) REFERENCES catalog_family(source_id, source_key) ON DELETE CASCADE
);
CREATE INDEX catalog_font_ps ON catalog_font(postscript_name);

CREATE TABLE catalog_label (
  source_id  INTEGER NOT NULL,
  source_key TEXT NOT NULL,
  kind       TEXT NOT NULL CHECK (kind IN ('genre', 'subclass', 'usage', 'feel', 'property', 'license')),
  raw        TEXT NOT NULL,                    -- the catalog's own label
  mapped     TEXT,                             -- our vocabulary (vocab/type.yaml), null if unmapped
  weight     REAL,                             -- e.g. Google Fonts tag weights (0-100)
  FOREIGN KEY (source_id, source_key) REFERENCES catalog_family(source_id, source_key) ON DELETE CASCADE
);
CREATE INDEX catalog_label_key ON catalog_label(source_id, source_key);

-- Name and tag search. trigram handles CJK substrings; queries shorter than 3 characters use LIKE.
CREATE VIRTUAL TABLE catalog_search USING fts5(
  family, names_i18n, labels, foundry,
  tokenize = 'trigram'
);

-- ---------------------------------------------------------------- local fonts
CREATE TABLE local_font (
  id              INTEGER PRIMARY KEY,
  path            TEXT NOT NULL,
  size            INTEGER NOT NULL,
  mtime           TEXT NOT NULL,
  face_index      INTEGER NOT NULL DEFAULT 0,  -- index inside TTC collections
  postscript_name TEXT,
  family          TEXT,
  family_norm     TEXT,
  subfamily       TEXT,
  names_i18n_json TEXT,
  manufacturer    TEXT,                        -- name ID 8
  vendor_id       TEXT,                        -- OS/2 achVendID
  designer        TEXT,                        -- name ID 9
  coverage_json   TEXT,                        -- {"hangul_syllables": 11172, "kana": 189, ...}
  origin          TEXT NOT NULL CHECK (origin IN ('adobe-sync', 'system', 'user')),
  UNIQUE (path, face_index)                    -- a TTC collection holds several faces in one file
);
CREATE INDEX local_font_family ON local_font(family_norm);
CREATE INDEX local_font_ps ON local_font(postscript_name);

CREATE TABLE measurement (
  local_font_id    INTEGER NOT NULL REFERENCES local_font(id) ON DELETE CASCADE,
  measurer_version TEXT NOT NULL,              -- re-measure only fonts measured by older versions
  family_kind      TEXT,                       -- text | hand | decorative | symbol
  panose_json      TEXT,                       -- {"weight": "book", "contrast": "none", ...}
  cjk_json         TEXT,                       -- {"bu_ratio": 1.02, "square_spread": 0.02, ...}
  metrics_json     TEXT,
  measured_at      TEXT NOT NULL,
  PRIMARY KEY (local_font_id, measurer_version)
);

CREATE TABLE match (
  local_font_id INTEGER NOT NULL REFERENCES local_font(id) ON DELETE CASCADE,
  source_id     INTEGER NOT NULL,
  source_key    TEXT NOT NULL,
  method        TEXT NOT NULL CHECK (method IN ('exact_ps', 'exact_family', 'fuzzy')),
  confidence    REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  PRIMARY KEY (local_font_id, source_id, source_key)
);

-- Style embeddings (optional models). One space version per model family.
CREATE TABLE embedding (
  local_font_id     INTEGER NOT NULL REFERENCES local_font(id) ON DELETE CASCADE,
  model             TEXT NOT NULL,             -- lazuli-1B | lazuli-0.3B | lazuli-0.09B | custom
  model_version     TEXT NOT NULL,
  space_version     TEXT NOT NULL,             -- compare only within the same space version
  specimen_version  TEXT NOT NULL,
  dims              INTEGER NOT NULL,
  vector_f16        BLOB NOT NULL,             -- Matryoshka: prefixes of the vector are usable
  computed_at       TEXT NOT NULL,
  PRIMARY KEY (local_font_id, model, model_version)
);

-- Per-font lookups for on-demand catalogs (noonnu, sandoll)
CREATE TABLE lookup_cache (
  source      TEXT NOT NULL,
  query_key   TEXT NOT NULL,
  response    TEXT NOT NULL,                   -- JSON
  fetched_at  TEXT NOT NULL,
  expires_at  TEXT NOT NULL,
  PRIMARY KEY (source, query_key)
);

CREATE TABLE meta (
  key   TEXT PRIMARY KEY,                      -- inventory_fingerprint, last_sync.<source>, ...
  value TEXT NOT NULL
);

-- ---------------------------------------------------------------- resolved view
-- Labels resolved by source priority (original sources before supplements).
-- Precedence rules live in this view so changing them never requires a re-sync.
CREATE VIEW v_font_label AS
SELECT lf.id AS local_font_id, lf.family, cl.kind, cl.mapped, cl.raw, s.name AS source, s.priority, m.confidence
FROM local_font lf
JOIN match m ON m.local_font_id = lf.id
JOIN source s ON s.id = m.source_id
JOIN catalog_label cl ON cl.source_id = m.source_id AND cl.source_key = m.source_key;

PRAGMA user_version = 1;
