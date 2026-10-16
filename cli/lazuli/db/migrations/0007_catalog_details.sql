-- LapisLazuli lazuli DB — migration 0007: what a catalog says about a family beyond its labels
-- `details_json` holds source-specific facts a search shows next to a candidate (CatalogFamily.details): a
-- listing's page for the usage conditions, a repository's description, homepage, download address, and where its
-- license was read. It stays NULL for rows synced before this migration until their source syncs again.
ALTER TABLE catalog_family ADD COLUMN details_json TEXT;

PRAGMA user_version = 7;
