-- LapisLazuli lazuli DB — migration 0004: Adobe Fonts are read through the operating system, not from files
-- Adobe's terms allow reaching an activated font only through the operating system's font API, so lazuli no
-- longer opens the files in Adobe's CoreSync folders. Every `adobe-sync` row so far came from opening those
-- files: its names, coverage, and measurements go, and the next `lazuli local fonts` collects Adobe faces
-- again through Core Text (macOS), or not at all (Windows and Linux). Rows of other origins, the user's
-- own records (`color_record`) and classes (`user_label`), and every catalog stay as they are.
-- The children are deleted first so that this holds whether or not foreign keys are enforced.

DELETE FROM embedding WHERE local_font_id IN (SELECT id FROM local_font WHERE origin = 'adobe-sync');
DELETE FROM match WHERE local_font_id IN (SELECT id FROM local_font WHERE origin = 'adobe-sync');
DELETE FROM measurement WHERE local_font_id IN (SELECT id FROM local_font WHERE origin = 'adobe-sync');
DELETE FROM local_font WHERE origin = 'adobe-sync';

-- The inventory fingerprint counted those files, so the next session says the fonts changed and asks for a scan.
DELETE FROM meta WHERE key = 'inventory_fingerprint';

PRAGMA user_version = 4;
