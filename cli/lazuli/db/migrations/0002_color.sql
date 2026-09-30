-- LapisLazuli lazuli DB — migration 0002: the user's own color values (`lazuli color record`)
-- Unlike catalogs and scans, these rows cannot be rebuilt: they are values the user recorded for a
-- color system code (a provider's published value, a measurement, or a screen sample). They live in
-- the user cache only and never go into a project or the repository.

CREATE TABLE color_record (
  id           INTEGER PRIMARY KEY,
  system       TEXT NOT NULL,                  -- vocab/color.yaml systems id (pantone, ral-classic, ncs, ...)
  code         TEXT NOT NULL,                  -- normalized code, e.g. "185 C", "RAL 3020", "NCS S 1040-R20B"
  source_class TEXT NOT NULL CHECK (source_class IN ('provider', 'screen-sample', 'measured')),
  use          TEXT NOT NULL CHECK (use IN ('spec', 'detection_only')),
  l            REAL NOT NULL,                  -- OKLCH lightness, 0..1
  c            REAL NOT NULL,                  -- OKLCH chroma
  h            REAL,                           -- OKLCH hue in degrees; null when chroma is powerless
  hex          TEXT,                           -- the sRGB value as given, when the user gave one
  note         TEXT,
  recorded_at  TEXT NOT NULL,                  -- ISO 8601
  UNIQUE (system, code, source_class),         -- recording again replaces the value of that class
  CHECK (source_class != 'screen-sample' OR use = 'detection_only')   -- a screen sample never becomes a spec
);

PRAGMA user_version = 2;
