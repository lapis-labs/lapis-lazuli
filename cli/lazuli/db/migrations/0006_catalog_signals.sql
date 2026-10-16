-- LapisLazuli lazuli DB — migration 0006: how familiar or new a catalog says each family is
-- `signals_json` holds the source's own popularity rank, trending rank, dates, and flags (CatalogFamily.signals).
-- It stays NULL for rows synced before this migration until their source is re-mapped from the kept responses
-- (`lazuli catalog remap`, no request) or synced again; NULL reads as unknown familiarity, never as obscure.
ALTER TABLE catalog_family ADD COLUMN signals_json TEXT;

PRAGMA user_version = 6;
