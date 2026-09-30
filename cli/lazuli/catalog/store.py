"""Catalog rows in the lazuli database: sources, snapshots, raw payloads, lookup answers, and search, plus
the user's own classes (`lazuli class`), which outrank every catalog.

A snapshot replaces every row of its source in one transaction, so a failed or interrupted sync
leaves the previous rows in place. `catalog_search` rows share the rowid of their `catalog_family`
row (the FTS table has no key columns); every replacement rebuilds the whole search table from
`catalog_family`, and search joins on both rowid and family text, so the link survives a VACUUM.
"""
from __future__ import annotations

import gzip
import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from lazuli.scan import norm


@dataclass
class CatalogFont:
    postscript_name: str
    style: str | None = None
    weight: int | None = None


@dataclass
class CatalogLabel:
    kind: str                     # genre | subclass | usage | feel | property | license
    raw: str
    mapped: str | None = None
    weight: float | None = None


@dataclass
class CatalogFamily:
    source_key: str
    family: str
    names_i18n: dict[str, str] = field(default_factory=dict)      # ko, ja, zh-Hans, zh-Hant
    foundry: str | None = None
    designers: list[str] = field(default_factory=list)
    license: str | None = None
    url: str | None = None
    fonts: list[CatalogFont] = field(default_factory=list)
    labels: list[CatalogLabel] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> CatalogFamily:
        return cls(**{**data, "fonts": [CatalogFont(**f) for f in data.get("fonts", ())],
                      "labels": [CatalogLabel(**label) for label in data.get("labels", ())]})


def now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def set_meta(conn: sqlite3.Connection, key: str, value: str | None) -> None:
    if value is None:
        conn.execute("DELETE FROM meta WHERE key = ?", (key,))
    else:
        conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                     "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, value))


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def ensure_source(conn: sqlite3.Connection, module) -> int:
    """The source row of an adapter module, created or updated from its NAME, KIND, PRIORITY, TTL_DAYS."""
    conn.execute("""INSERT INTO source (name, kind, priority, ttl_days) VALUES (?, ?, ?, ?)
                    ON CONFLICT (name) DO UPDATE SET kind = excluded.kind, priority = excluded.priority,
                      ttl_days = excluded.ttl_days""",
                 (module.NAME, module.KIND, module.PRIORITY, module.TTL_DAYS))
    return conn.execute("SELECT id FROM source WHERE name = ?", (module.NAME,)).fetchone()[0]


def source_id(conn: sqlite3.Connection, name: str) -> int | None:
    row = conn.execute("SELECT id FROM source WHERE name = ?", (name,)).fetchone()
    return row[0] if row else None


def _insert_family(conn: sqlite3.Connection, sid: int, family: CatalogFamily) -> None:
    conn.execute("""INSERT INTO catalog_family (source_id, source_key, family, family_norm, names_i18n_json,
                      foundry, designers_json, license, url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                 (sid, family.source_key, family.family, norm(family.family) or "",
                  json.dumps(family.names_i18n, ensure_ascii=False) if family.names_i18n else None,
                  family.foundry, json.dumps(family.designers, ensure_ascii=False) if family.designers else None,
                  family.license, family.url))
    conn.executemany("INSERT OR IGNORE INTO catalog_font (source_id, source_key, postscript_name, style, weight) "
                     "VALUES (?, ?, ?, ?, ?)",
                     [(sid, family.source_key, f.postscript_name, f.style, f.weight) for f in family.fonts])
    conn.executemany("INSERT INTO catalog_label (source_id, source_key, kind, raw, mapped, weight) VALUES (?, ?, ?, ?, ?, ?)",
                     [(sid, family.source_key, lb.kind, lb.raw, lb.mapped, lb.weight) for lb in family.labels])


def _delete_family(conn: sqlite3.Connection, sid: int, source_key: str | None = None) -> None:
    where, args = ("source_id = ?", (sid,)) if source_key is None else ("source_id = ? AND source_key = ?", (sid, source_key))
    for table in ("catalog_label", "catalog_font", "catalog_family"):
        conn.execute(f"DELETE FROM {table} WHERE {where}", args)


def rebuild_search(conn: sqlite3.Connection) -> None:
    """Every `catalog_search` row from `catalog_family` (names, labels raw and mapped, foundry, designers)."""
    conn.execute("DELETE FROM catalog_search")
    conn.execute("""
        INSERT INTO catalog_search (rowid, family, names_i18n, labels, foundry)
        SELECT cf.rowid, cf.family,
               COALESCE((SELECT group_concat(j.value, ' ') FROM json_each(cf.names_i18n_json) j), ''),
               COALESCE((SELECT group_concat(cl.raw || COALESCE(' ' || cl.mapped, ''), ' ') FROM catalog_label cl
                         WHERE cl.source_id = cf.source_id AND cl.source_key = cf.source_key), ''),
               trim(COALESCE(cf.foundry, '') || ' ' ||
                    COALESCE((SELECT group_concat(j.value, ' ') FROM json_each(cf.designers_json) j), ''))
        FROM catalog_family cf""")


def replace_snapshot(conn: sqlite3.Connection, module, families: list[CatalogFamily]) -> int:
    """Replace every family, font, and label of the module's source in one transaction; returns the count."""
    keys = [f.source_key for f in families]
    if len(set(keys)) != len(keys):
        raise ValueError(f"{module.NAME}: duplicate source_key in the snapshot")
    with conn:
        sid = ensure_source(conn, module)
        _delete_family(conn, sid)
        for family in families:
            _insert_family(conn, sid, family)
        rebuild_search(conn)
        conn.execute("UPDATE source SET fetched_at = ?, status = 'ok' WHERE id = ?", (_iso(now()), sid))
        set_meta(conn, f"status_reason.{module.NAME}", None)
    return len(families)


def mark(conn: sqlite3.Connection, module, status: str, reason: str | None = None) -> None:
    """Set a source's status (failed | stale | disabled, or ok) and keep the reason; rows stay as they are."""
    with conn:
        ensure_source(conn, module)
        conn.execute("UPDATE source SET status = ? WHERE name = ?", (status, module.NAME))
        set_meta(conn, f"status_reason.{module.NAME}", reason)


def reason(conn: sqlite3.Connection, name: str) -> str | None:
    return get_meta(conn, f"status_reason.{name}")


def save_raw(conn: sqlite3.Connection, source: str, request_key: str, body: bytes) -> None:
    sid = source_id(conn, source)
    if sid is None:
        raise LookupError(f"source {source!r} has no row; call store.ensure_source first")
    with conn:
        conn.execute("""INSERT INTO raw_payload (source_id, request_key, fetched_at, body_gz) VALUES (?, ?, ?, ?)
                        ON CONFLICT (source_id, request_key) DO UPDATE SET fetched_at = excluded.fetched_at,
                          body_gz = excluded.body_gz""",
                     (sid, request_key, _iso(now()), gzip.compress(body, mtime=0)))


def load_raw(conn: sqlite3.Connection, source: str, request_key: str) -> bytes | None:
    """A kept response body, so mapping rules can be re-applied without fetching again."""
    row = conn.execute("""SELECT rp.body_gz FROM raw_payload rp JOIN source s ON s.id = rp.source_id
                          WHERE s.name = ? AND rp.request_key = ?""", (source, request_key)).fetchone()
    return gzip.decompress(row[0]) if row else None


def save_lookup(conn: sqlite3.Connection, module, query_key: str, family: CatalogFamily | None, ttl_days: int) -> None:
    """Cache one lookup answer (a family, or None for "not in this catalog") for ttl_days.

    A found family also becomes the source's catalog row under its source_key, so matching and
    label resolution treat lookup answers like snapshot rows.
    """
    moment = now()
    with conn:
        sid = ensure_source(conn, module)
        conn.execute("""INSERT INTO lookup_cache (source, query_key, response, fetched_at, expires_at) VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT (source, query_key) DO UPDATE SET response = excluded.response,
                          fetched_at = excluded.fetched_at, expires_at = excluded.expires_at""",
                     (module.NAME, query_key, json.dumps(asdict(family) if family else None, ensure_ascii=False),
                      _iso(moment), _iso(moment + timedelta(days=ttl_days))))
        if family is not None:
            _delete_family(conn, sid, family.source_key)
            _insert_family(conn, sid, family)
            rebuild_search(conn)
        conn.execute("UPDATE source SET fetched_at = ? WHERE id = ?", (_iso(moment), sid))


def cached_lookup(conn: sqlite3.Connection, module, query_key: str) -> CatalogFamily | None | Literal["miss"]:
    """The cached answer while it is fresh (a family or None), or "miss" when there is none or it expired."""
    row = conn.execute("SELECT response, expires_at FROM lookup_cache WHERE source = ? AND query_key = ?",
                       (module.NAME, query_key)).fetchone()
    if row is None or datetime.fromisoformat(row[1]) <= now():
        return "miss"
    data = json.loads(row[0])
    return CatalogFamily.from_dict(data) if data else None


def search(conn: sqlite3.Connection, text: str, *, limit: int = 20) -> list[sqlite3.Row]:
    """Catalog families whose names, labels, foundry, or designers contain `text`.

    Three or more characters use the FTS5 trigram index (substrings, CJK included); shorter text has no
    trigram, so it falls back to LIKE over the same columns.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) >= 3:
        where, args = "catalog_search MATCH ?", ['"' + text.replace('"', '""') + '"']
        order = "rank"
    else:
        pattern = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where = " OR ".join(f"catalog_search.{c} LIKE ? ESCAPE '\\'" for c in ("family", "names_i18n", "labels", "foundry"))
        args, order = [pattern] * 4, "s.priority, cf.family"
    return conn.execute(f"""
        SELECT s.name AS source, s.priority, cf.source_key, cf.family, cf.names_i18n_json, cf.foundry, cf.license, cf.url
        FROM catalog_search
        JOIN catalog_family cf ON cf.rowid = catalog_search.rowid AND cf.family = catalog_search.family
        JOIN source s ON s.id = cf.source_id
        WHERE {where} ORDER BY {order} LIMIT ?""", (*args, limit)).fetchall()


# ---------------------------------------------------------------- user classes (`lazuli class`)

USER_SOURCE = "user"
# Ahead of every catalog (adapter priorities start at 10); `v_font_label` (migration 0003) uses the same
USER_PRIORITY = 0
_USER_FIELDS = ("family", "genre", "subclass", "url", "recorded_at")


def user_labels(conn: sqlite3.Connection) -> dict[str, dict]:
    """The user's labels by normalized family name: {"family", "genre", "subclass", "url", "recorded_at"}."""
    return {row["family_norm"]: {k: row[k] for k in _USER_FIELDS}
            for row in conn.execute("SELECT * FROM user_label ORDER BY family, family_norm")}


def user_label_rows(label: dict | None) -> list[dict]:
    """A user class as rows shaped like `v_font_label` for `labels.resolve`: source `user`, first priority."""
    if label is None:
        return []
    return [{"kind": kind, "mapped": value, "raw": value, "source": USER_SOURCE, "priority": USER_PRIORITY,
             "confidence": 1.0}
            for kind, value in (("genre", label["genre"]), ("subclass", label["subclass"])) if value]
