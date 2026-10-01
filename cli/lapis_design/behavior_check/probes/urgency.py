"""Observe visible urgency claims against the shared fixture clock."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone, tzinfo
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from lapis_design.behavior_check.redact import path as safe_path

NAMES = ("urgency",)
_TIME = re.compile(r"(?<!\d)(?:(\d{1,2}):)?([0-5]?\d):([0-5]\d)(?!\d)")
# Korean "N일" is a day count only before hours or 남음 ("3일 5시간", "3일 남음"); otherwise it is a date.
_DAYS = re.compile(r"(\d+)\s*(?:days?|일(?=\s*\d+\s*시간|\s*남))\s*(?:(\d+)\s*(?:hours?|hrs?|시간))?", re.I)
_HOURS = re.compile(r"(\d+)\s*(?:hours?|hrs?|시간)\s*(?:(\d+)\s*(?:minutes?|mins?|분))?", re.I)
_DATE = re.compile(r"(20\d\d)\s*[-/년.]\s*(\d{1,2})\s*[-/월.]\s*(\d{1,2})\s*(?:일|T)?\s*(?:(\d{1,2})(?::|시\s*)(\d{2})(?::(\d{2}))?)?", re.I)
_UTC = re.compile(r"\b(?:UTC|GMT)\b|\dZ\b")
# What a stock claim counts: "2 items left", "Only 2 sites left" (any noun but a span of time), "2곳 남았어요", and
# the count after the word: "잔여 2석", "마지막 1자리". 개월 and 동안 are not a count of 개 or 동.
_STOCK_KO = r"(?:객실|자리|개(?!월)|점|석|장|곳|실|팀|매|동(?!안))"
_SPAN = r"(?:seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?|months?|years?)"
_STOCK = re.compile(rf"(?:\b(\d+)\s*(?:items?\s*)?(?:left|remaining|in stock)\b"
                    rf"|\b(\d+)\s+(?!{_SPAN}\b)\w+\s+(?:left|remaining|in stock)\b"
                    rf"|(?:재고\s*)?(\d+)\s*{_STOCK_KO}\s*(?:남음|남았|남아|잔여|재고)"
                    rf"|(?:잔여|남은|마지막)\s*(\d+)\s*{_STOCK_KO})", re.I)
_DEMAND = re.compile(r"(?:\b(\d+)\s*(?:people|visitors?|users?)\s*(?:(?:are|currently|now)\s+){0,3}(?:viewing|watching|looking)\b"
                     r"|(?:현재\s*)?(\d+)\s*(?:명|분)이?\s*(?:보고|구경|조회|시청)"
                     r"|(\d+)\s*명이?\s+(?:[^\s.?!,]+\s+){0,3}?(?:보고|구경|조회|시청))", re.I)
_ACTIVITY = re.compile(r"(?:\b(?:someone|\d+\s*(?:people|customers?))\b.{0,40}\b(?:just\s*)?(?:bought|purchased|reserved|ordered|booked)\b|(?:방금|최근).{0,40}(?:구매|주문|예약))", re.I)
# A span that looks back ("최근 3시간 동안 5명이 예약했어요", "5 people booked this in the last 3 hours", "in the past
# 7 days") is not a countdown.
_LOOKBACK = re.compile(r"(?:최근|지난)\s*\d+\s*시간|\b(?:(?:in|over|within|during)\s+the\s+(?:last|past)|past)\s+\d+\s*(?:hours?|hrs?|days?)\b", re.I)
_HOLD = re.compile(r"\b(?:hold|held|reserved for you|reservation expires)\b|(?:홀드|보류|임시\s*예약|예약\s*유지|확보)", re.I)
_DEADLINE = re.compile(r"\b(?:deadline|ends?\s+(?:on|at)|expires?\s+(?:on|at)|until)\b|(?:마감|종료|까지|기한)", re.I)
# `mm:ss` that names a time of day is a clock time, not a countdown ("입실 14:00부터", "11:00까지", "6:00 PM UTC",
# "6:00–7:00 PM"), unless the text also says time is running out ("ends in 14:00", "남은 시간 14:00").
_TIME_OF_DAY = re.compile(r"(?<![a-z])[ap]\.?m\b\.?|오전|오후|부터|까지|입실|퇴실|체크\s*(?:인|아웃)|\b(?:UTC|GMT|KST)\b"
                          r"|\b(?:at|from|until|opens?|closes?|check-?in|check-?out|daily)\b(?!\s+in\b)"
                          r"|\d:\d\d\s*[~–—-]\s*\d{1,2}:\d\d", re.I)
_RUNNING_OUT = re.compile(r"\b(?:left|remaining|(?:ends?|expires?|closes?|starts?)\s+in|countdown|timer)\b"
                          r"|남음|남았|남은|남아|후\s*(?:마감|종료|만료)|타이머", re.I)


def _time_of_day(text: str) -> bool:
    """The text gives a clock time of day rather than time left."""
    return bool(_TIME_OF_DAY.search(text)) and not _RUNNING_OUT.search(text)


def _claim(text: str, now_ms: int, zone: tzinfo = timezone.utc):
    """(kind, value, resolution_s, unit) for one claim. Absolute times that do not name UTC are
    read in `zone`, the context's time zone, with that zone's offset on the claimed date."""
    text = " ".join(text.split())
    if len(text) > 180:
        return None
    hold = bool(_HOLD.search(text))
    ticking = _LOOKBACK.sub(" ", text)
    date = _DATE.search(text)
    if date and _DEADLINE.search(text):
        year, month, day, hour, minute, second = (int(part) if part else None for part in date.groups())
        try:
            instant = datetime(year, month, day, hour or 0, minute or 0, second or 0,
                               tzinfo=timezone.utc if _UTC.search(text) else zone)
        except ValueError:
            return None
        # A date without a time runs to the end of that day (the next local midnight).
        resolution = 86400 if hour is None else 60 if second is None else 1
        end_ms = (instant + timedelta(days=1 if hour is None else 0)).timestamp() * 1000
        return ("deadline", max(0, (end_ms - now_ms) / 1000), resolution, "seconds")
    match = _TIME.search(ticking)
    if match and not _time_of_day(ticking):
        value = (int(match[1] or 0) * 3600 + int(match[2]) * 60 + int(match[3]))
        return ("hold" if hold else "countdown", value, 1, "seconds")
    match = _DAYS.search(ticking)
    if match:
        return ("hold" if hold else "countdown", int(match[1]) * 86400 + int(match[2] or 0) * 3600,
                3600 if match[2] else 86400, "seconds")
    match = _HOURS.search(ticking)
    if match:
        return ("hold" if hold else "countdown", int(match[1]) * 3600 + int(match[2] or 0) * 60,
                60 if match[2] else 3600, "seconds")
    for kind, pattern, unit in (("stock", _STOCK, "items"), ("demand", _DEMAND, "people")):
        match = pattern.search(text)
        if match:
            return (kind, int(next(group for group in match.groups() if group is not None)), 0, unit)
    if _ACTIVITY.search(text):
        count = re.search(r"\b(\d+)\s*(?:people|customers?)\b|(\d+)\s*(?:명|분)", text, re.I)
        return ("activity", int(count[1] or count[2]) if count else 1, 0, "events")
    return None


def _visible(driver):
    driver.boxes()
    # One browser round trip. Parent wrappers are ignored if a child already describes the claim.
    return driver.page.evaluate("""() => [...document.querySelectorAll('[data-lapis-box]')]
      .filter(el => {const r=el.getBoundingClientRect(); const s=getComputedStyle(el);
          return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none';})
      .map(el => ({id:el.getAttribute('data-lapis-box'), text:(el.innerText||el.textContent||'').trim(),
          children:[...el.querySelectorAll('[data-lapis-box]')].map(child=>child.getAttribute('data-lapis-box'))}))""")


def _zone(driver) -> ZoneInfo:
    return ZoneInfo(driver.ctx.get("timezone", "UTC"))


def run(session, open_driver):
    drivers = {}
    missing = []
    locales = list(dict.fromkeys((session.plan or {}).get("brief", {}).get("locales", [])))
    targets = list(session.matrix)
    if locales:
        for base in session.matrix:
            session.contexts[base].setdefault("locale", locales[0])
        for index, locale in enumerate(locales[1:], 1):
            for base in session.matrix:
                overrides = {key: value for key, value in session.contexts[base].items() if key != "id"}
                overrides["locale"] = locale
                targets.append(session.context(f"u{index}{base}", **overrides))
    try:
        for ctx in targets:
            driver = open_driver(ctx)
            drivers[ctx] = driver
            route = urlsplit(session.source["url"]).path or "/"
            if driver.page is None or urlsplit(driver.page.url).path != route:
                driver.open(route)
        start = session.clock.now_ms()
        claims = []
        for ctx, driver in drivers.items():
            candidates = _visible(driver)
            parsed = {item["id"]: _claim(item["text"], start, _zone(driver)) for item in candidates}
            # The nearest enclosing box: a time set apart in its own element ("입실 <b>14:00</b>부터") is read
            # with the words around it.
            enclosing = {}
            for item in sorted(candidates, key=lambda candidate: len(candidate["children"])):
                for child in item["children"]:
                    enclosing.setdefault(child, item)
            for item in candidates:
                result = parsed[item["id"]]
                if not result or any(parsed.get(child) for child in item["children"]):
                    continue
                outer = " ".join(enclosing.get(item["id"], {}).get("text", "").split())
                if (result[0] in ("countdown", "hold") and _TIME.search(item["text"]) and len(outer) <= 180
                        and _time_of_day(outer)):
                    continue
                kind, value, resolution, unit = result
                entry = {"box": item["id"], "context": ctx, "kind": kind,
                         "path": safe_path(driver.page.url, session.fixture_values),
                         "readings": [{"when": "load", "value": value, "unit": unit,
                                       "resolution_s": resolution, "elapsed_ms": 0}]}
                if session.engine is not None and session.meta["backend"] == "stub":
                    entry["backed"] = session.engine.backed(kind, value, now_ms=start, resolution_s=resolution)
                session.add_probe("urgency", entry)
                claims.append((driver, item["id"], entry, item["text"]))
        if not claims:
            session.cover("urgency", "not-applicable", contexts=drivers)
            return

        def read_when(when):
            now = session.clock.now_ms()
            visible = {driver: {item["id"]: item for item in _visible(driver)} for driver in drivers.values()}
            for driver, box, entry, _ in claims:
                current = visible[driver].get(box)
                match = _claim(current["text"], now, _zone(driver)) if current else None
                if match and match[0] == entry["kind"]:
                    entry["readings"].append({"when": when, "value": match[1], "unit": match[3],
                                              "resolution_s": match[2], "elapsed_ms": now - start})
                else:
                    missing.append(f"{entry['context']}:{box}:{when} claim not visible")

        session.advance_clock(30_000, jump=True)
        read_when("later")
        resolution = max(item[2]["readings"][0]["resolution_s"] for item in claims)
        interval = min(7 * 86400_000, max(120_000, round(2 * resolution * 1000)))
        session.advance_clock(interval, jump=True)
        for driver in drivers.values():
            driver.reload(reset_storage=False)
        read_when("reload")
        session.advance_clock(interval, jump=True)
        for driver in drivers.values():
            driver.open(urlsplit(session.source["url"]).path or "/", storage="fresh")
        read_when("fresh-profile")
        clock_elapsed = session.clock.now_ms() - start
        for driver, box, entry, initial_text in claims:
            if entry["kind"] in ("countdown", "deadline", "hold") and entry["readings"][0]["value"] > 7 * 86400:
                entry["at_expiry"] = "not-reached"
        targets = [entry["readings"][0]["value"] * 1000 for _, _, entry, _ in claims
                   if entry["kind"] in ("countdown", "deadline", "hold") and
                   entry["readings"][0]["value"] <= 7 * 86400]
        if targets:
            session.advance_clock(max(0, round(max(targets) + 5000 - clock_elapsed)), jump=True)
            now = session.clock.now_ms()
            visible = {driver: {item["id"]: item for item in _visible(driver)} for driver in drivers.values()}
            for driver, box, entry, initial_text in claims:
                if entry["kind"] not in ("countdown", "deadline", "hold") or "at_expiry" in entry:
                    continue
                current = visible[driver].get(box)
                match = _claim(current["text"], now, _zone(driver)) if current else None
                if match and match[0] == entry["kind"]:
                    entry["readings"].append({"when": "after-expiry", "value": match[1], "unit": match[3],
                                              "resolution_s": match[2], "elapsed_ms": now - start})
                entry["at_expiry"] = ("restarts" if match and match[0] == entry["kind"] and
                                      match[1] > max(2, match[2]) else
                                      "offer-ends" if not current or (not match and current["text"] != initial_text) else
                                      "unchanged")
        if session.meta["backend"] != "stub":
            missing.append("Backing cannot be verified without a stub fixture")
        session.cover("urgency", "partial" if missing else "ran", contexts=drivers,
                      reason="; ".join(missing) if missing else None)
    finally:
        for driver in drivers.values():
            driver.close()
