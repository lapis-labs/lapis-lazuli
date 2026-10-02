"""Observe visible urgency claims against the shared fixture clock."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone, tzinfo
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from lapis_design.behavior_check.redact import path as safe_path

NAMES = ("urgency",)
_NUM = r"(\d{1,3}(?:,\d{3})+|\d+)"        # a number; one written with thousands separators is read whole
_TIME = re.compile(r"(?<!\d)(?:(\d{1,2}):)?([0-5]?\d):([0-5]\d)(?!\d)")
# Korean "N일" is a day count only before hours, 남음, or 후 마감 ("3일 5시간", "3일 남음", "2일 후 마감") and after
# 마감까지, 종료까지, or 만료까지 ("마감까지 3일"); otherwise it is a date ("9월 30일").
_DAYS = re.compile(_NUM + r"\s*(?:days?|일(?=\s*\d+\s*시간|\s*남|\s*후\s*(?:마감|종료|만료)))\s*(?:(\d+)\s*(?:hours?|hrs?|시간))?", re.I)
_DAYS_AFTER = re.compile(r"(?:마감|종료|만료)까지\s*" + _NUM + r"\s*일\s*(?:(\d+)\s*시간)?")
_HOURS = re.compile(_NUM + r"\s*(?:hours?|hrs?|시간)\s*(?:(\d+)\s*(?:minutes?|mins?|분))?", re.I)
_DATE = re.compile(r"(20\d\d)\s*[-/년.]\s*(\d{1,2})\s*[-/월.]\s*(\d{1,2})\s*(?:일|T)?\s*(?:(\d{1,2})(?::|시\s*)(\d{2})(?::(\d{2}))?)?", re.I)
_UTC = re.compile(r"\b(?:UTC|GMT)\b|\dZ\b")
# What a stock claim counts: things that can run out ("2 items left", "Only 2 sites left", "2곳 남았어요", "3명 남았어요"),
# and the count after the word ("잔여 2석", "잔여 좌석 2석", "마지막 1자리", "재고 3개"). Not progress ("3 steps left",
# "남은 2개 단계"), not a span of time, and not "2 people left a review". 개월 and 동안 are not a count of 개 or 동.
_STOCK_KO = r"(?:객실|자리|개(?!월)|점|석|장|곳|실|팀|매|동(?!안))"
_SPAN = r"(?:seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?|months?|years?)"
_PROGRESS = r"(?:steps?|characters?|attempts?|questions?|tasks?)"
_LEFT = r"(?:left(?!\s+(?:an?|the)\b)|remaining|in stock)"
_STOCK = re.compile(r"(?:(?<![\w:])" + _NUM + r"\s*(?:items?\s*)?" + _LEFT + r"\b"
                    r"|(?<![\w:])" + _NUM + r"\s+(?!" + _SPAN + r"\b|" + _PROGRESS + r"\b)\w+\s+" + _LEFT + r"\b"
                    r"|(?:재고\s*)?" + _NUM + r"\s*(?:" + _STOCK_KO + r"|명)\s*(?:남음|남았|남아|잔여|재고)"
                    r"|재고\s*" + _NUM + r"\s*" + _STOCK_KO +
                    r"|(?:잔여|남은|마지막)\s*(?:(?:좌석|수량|객실|자리|재고)\s*)?" + _NUM + r"\s*" + _STOCK_KO +
                    r"(?!\s*(?:단계|글자|시도|질문|문항|문제|리뷰|후기|댓글|항목|과제|페이지)))", re.I)
# A demand claim has people as its subject and says they are viewing or waiting for the thing. Words between the
# count and the verb are allowed only after "명이" or "명가" ("성인 2명 예약 내역 조회" is not one), and "분" (the
# honorific count) needs 이 or 께서 ("영상 3분 시청" is not one).
_DEMAND = re.compile(r"(?:\b" + _NUM + r"\s*(?:people|visitors?|users?)\s*(?:(?:are|currently|now)\s+){0,3}(?:viewing|watching|looking|waiting)\b"
                     r"|(?:현재\s*)?" + _NUM + r"\s*(?:명이?|분(?:이|께서))\s*(?:보고|구경|조회|시청|기다리)"
                     r"|" + _NUM + r"\s*(?:명[이가]|분(?:이|께서))\s+(?:[^\s.?!,]+\s+){0,3}?(?:보고|구경|조회|시청|기다리))", re.I)
# An activity notice has someone (someone, N people, 누군가, N명) who bought, ordered, reserved, or booked. "최근 주문
# 내역", "방금 주문하신 상품", and "방금 전 예약이 확정됐어요" have no one in them.
_ACTIVITY = re.compile(r"\b(?:someone|" + _NUM + r"\s*(?:people|customers?))\b.{0,40}\b(?:just\s*)?(?:bought|purchased|reserved|ordered|booked)\b"
                       r"|(?:누군가|" + _NUM + r"\s*명)(?:이|가|께서)?\s*(?:[^\s.?!,]+\s+){0,4}?"
                       r"(?:(?:구매|구입|주문|예약)(?:했|하셨|하였|됐|되었|함|(?=[\s.!?]*$))|샀|사갔)", re.I)
# A span that looks back ("최근 3시간 동안 5명이 예약했어요", "5 people booked this in the last 3 hours", "in the past
# 7 days") is not a countdown.
_LOOKBACK = re.compile(r"(?:최근|지난)\s*\d+\s*시간|\b(?:(?:in|over|within|during)\s+the\s+(?:last|past)|past)\s+\d+\s*(?:hours?|hrs?|days?)\b", re.I)
_HOLD = re.compile(r"\b(?:hold|held|reserved for you|reservation expires)\b|(?:홀드|보류|임시\s*예약|예약\s*유지|확보)", re.I)
_DEADLINE = re.compile(r"\b(?:deadline|ends?\s+(?:on|at)|expires?\s+(?:on|at)|until)\b|(?:마감|종료|까지|기한)", re.I)
# Time-of-day wording counts only where it belongs to the time: a.m. or p.m., 오전 or 오후, or a time zone beside it;
# at, from, until, or by directly before it; 부터 or 까지 directly after it; or a range of two times ("입실 14:00부터",
# "6:00 PM UTC", "Doors open at 18:30", "9:00–18:00"). Such a time is a time of day whatever else the text says.
_ZONE = r"(?:(?:UTC|GMT)(?:\s*[+\-−]\s*\d{1,2}(?::?\d{2})?)?|KST|JST|CET|CEST|BST|IST|EST|EDT|CST|CDT|MST|MDT|PST|PDT)"
_CLOCK = r"\d{1,2}:\d{2}(?::\d{2})?"
_BEFORE_TIME = re.compile(r"(?:\b(?:at|from|until|by)|오전|오후|" + _ZONE + r"|" + _CLOCK + r"\s*(?:[~–—〜-]|\bto))\s*$", re.I)
_AFTER_TIME = re.compile(r"\s*(?:부터|까지|(?<![a-z])[ap]\.?m\b|오전|오후|" + _ZONE + r"\b|(?:[~–—〜-]|\bto\b)\s*" + _CLOCK + r")|Z\b", re.I)
# What says time is running out: "Sale ends in 02:15:10", "3시간 남음", "마감까지 02:15:10".
_RUNNING_OUT = re.compile(r"\b(?:left|remaining|(?:ends?|expires?|closes?|starts?)\s+in|countdown|timer)\b"
                          r"|남음|남았|남은|남아|후\s*(?:마감|종료|만료)|(?:마감|종료|만료)까지|타이머", re.I)
# What turns a count of days or hours into time left: running out, or a deadline or cut-off ("2 days to go",
# "마감까지 3시간", "Order within the next 3 hours", "Free shipping for the next 3 hours"). A span that measures a
# quantity ("Keep 30 days of changes", "valid for 90 days", "14 days free", "24시간 고객센터", "48시간 한정") has none
# of these. Only a day count with an hour count ("2 days 4 hours", "3일 5시간") is a countdown on its own.
_COUNTS_DOWN = re.compile(_RUNNING_OUT.pattern + r"|\b(?:deadline|due|to\s+go)\b|\b(?:within|for)\s+the\s+next\b"
                          r"|\b(?:order|buy|book|reserve|claim|checkout)\s+within\b"
                          r"|시간\s*내(?:에)?\s*(?:주문|결제|구매|예약|신청)", re.I)
# A period for paying, cancelling, or refunding ("Payment due in 30 days", "24시간 내에 예약 취소 가능") is a term of
# the offer, not time left, unless the words beside it say time is running out ("5 days left").
_PAYMENT = re.compile(r"\b(?:pay(?:ment|ments|ing|able)?|paid|cancel(?:l?ation|l?ing|l?ed|s)?|refund(?:s|ed|ing|able)?|invoices?)\b"
                      r"|결제|취소|환불|납부", re.I)
_REACH = 40        # characters between the words and the span, in one sentence
_APART = re.compile(r"[.!?;。·|•—–]")


def _int(count: str) -> int:
    return int(count.replace(",", ""))


def _stock_spans(text: str) -> list[tuple[int, int]]:
    return [stock.span() for stock in _STOCK.finditer(text)]


def _apart(text: str, words: re.Match, start: int, end: int) -> bool:
    """`words` sit farther from the span `text[start:end]` than a sentence's reach."""
    between = (text[words.end():start] if words.end() <= start else
               text[end:words.start()] if words.start() >= end else "")   # "" overlaps it
    return len(between) > _REACH or bool(_APART.search(between))


def _runs_out(text: str, span: tuple[int, int] | None = None) -> bool:
    """The text says time is running out (beside `span`, if one is given). The "left" of a stock claim
    ("5 spots left") belongs to its count."""
    owned = _stock_spans(text)
    return any(not any(start <= words.start() < end for start, end in owned) and (span is None or not _apart(text, words, *span))
               for words in _RUNNING_OUT.finditer(text))


def _time_of_day(text: str, start: int, end: int) -> bool:
    """The clock time at `text[start:end]` is a time of day: the words that make it one sit right beside it."""
    return bool(_BEFORE_TIME.search(text, 0, start) or _AFTER_TIME.match(text, end))


def _sentence(text: str, at: int) -> tuple[int, int]:
    """The span of `text` between sentence breaks that holds the position `at`."""
    return (max((apart.end() for apart in _APART.finditer(text, 0, at)), default=0),
            next((apart.start() for apart in _APART.finditer(text, at)), len(text)))


def _time_left(patterns, text: str, hold: bool, pair: bool = False):
    """The first span of `patterns` that is time left rather than a quantity: words in its sentence within reach
    say time is running out or a deadline is near, the page names a hold, or (`pair`) it gives days and hours.
    The "left" of a stock claim ("5 spots left") belongs to its count, not to a span beside it. A deadline or
    cut-off word in a sentence about paying, cancelling, or refunding does not make a span time left."""
    owned = _stock_spans(text)
    for match in sorted((found for pattern in patterns for found in pattern.finditer(text)), key=lambda found: found.start()):
        if hold or (pair and match[2]):
            return match
        for words in _COUNTS_DOWN.finditer(text):
            if any(start <= words.start() < end for start, end in owned):
                continue
            if _apart(text, words, match.start(), match.end()):
                continue
            if not _RUNNING_OUT.fullmatch(words[0]):
                start, end = _sentence(text, match.start())
                if _PAYMENT.search(text[start:words.start()] + " " + text[words.end():end]):
                    continue
            return match
    return None


def _read(text: str, now_ms: int, zone: tzinfo = timezone.utc, outer: str = ""):
    """((kind, value, resolution_s, unit) or None, tentative) for one box. `tentative`: the claim is a clock time
    whose words do not say time is running out ("09:30", "10:30 예약 가능"), which is a countdown only if its value
    goes down between the `load` and `later` readings. `outer` is the text of the box around this one: a time set
    apart in its own element ("입실 <b>14:00</b>부터") is read with the words around it.
    Absolute times that do not name UTC are read in `zone`, the context's time zone, with that zone's offset on
    the claimed date."""
    text = " ".join(text.split())
    if len(text) > 180:
        return None, False
    outer = " ".join(outer.split())
    if len(outer) > 180:
        outer = ""
    hold = bool(_HOLD.search(text))
    ticking = _LOOKBACK.sub(" ", text)
    date = _DATE.search(text)
    if date and _DEADLINE.search(text):
        year, month, day, hour, minute, second = (int(part) if part else None for part in date.groups())
        try:
            instant = datetime(year, month, day, hour or 0, minute or 0, second or 0,
                               tzinfo=timezone.utc if _UTC.search(text) else zone)
        except ValueError:
            return None, False
        # A date without a time runs to the end of that day (the next local midnight).
        resolution = 86400 if hour is None else 60 if second is None else 1
        end_ms = (instant + timedelta(days=1 if hour is None else 0)).timestamp() * 1000
        return ("deadline", max(0, (end_ms - now_ms) / 1000), resolution, "seconds"), False
    bare = None
    for match in _TIME.finditer(ticking):
        where = outer.find(match[0])          # the same time in the box around this one
        span = (where, where + len(match[0]))
        if _time_of_day(ticking, *match.span()) or (where >= 0 and _time_of_day(outer, *span)):
            continue
        value = (int(match[1] or 0) * 3600 + int(match[2]) * 60 + int(match[3]))
        held = hold or (where >= 0 and any(not _apart(outer, found, *span) for found in _HOLD.finditer(outer)))
        if held or _runs_out(ticking) or (where >= 0 and _runs_out(outer, span)):
            return ("hold" if held else "countdown", value, 1, "seconds"), False
        bare = ("countdown", value, 1, "seconds")
        break
    match = _time_left((_DAYS, _DAYS_AFTER), ticking, hold, pair=True)
    if match:
        return (("hold" if hold else "countdown", _int(match[1]) * 86400 + int(match[2] or 0) * 3600,
                 3600 if match[2] else 86400, "seconds"), False)
    match = _time_left((_HOURS,), ticking, hold)
    if match:
        return (("hold" if hold else "countdown", _int(match[1]) * 3600 + int(match[2] or 0) * 60,
                 60 if match[2] else 3600, "seconds"), False)
    for kind, pattern, unit in (("stock", _STOCK, "items"), ("demand", _DEMAND, "people")):
        match = pattern.search(text)
        if match:
            return (kind, _int(next(group for group in match.groups() if group is not None)), 0, unit), False
    match = _ACTIVITY.search(text)
    if match:
        count = next((group for group in match.groups() if group), None)
        return ("activity", _int(count) if count else 1, 0, "events"), False
    return bare, bare is not None


def _claim(text: str, now_ms: int, zone: tzinfo = timezone.utc, outer: str = ""):
    """(kind, value, resolution_s, unit) for one claim, or None. A bare clock time is not a claim until its value
    goes down (see `_read`)."""
    claim, tentative = _read(text, now_ms, zone, outer)
    return None if tentative else claim


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
        claims = []            # (driver, box, entry, text) of every box that reads as a claim, in page order
        bare = set()           # id(entry) of a bare clock time: a claim only if its value goes down (`_read`)
        for ctx, driver in drivers.items():
            candidates = _visible(driver)
            # The nearest enclosing box: a time set apart in its own element ("입실 <b>14:00</b>부터") is read
            # with the words around it.
            enclosing = {}
            for item in sorted(candidates, key=lambda candidate: len(candidate["children"])):
                for child in item["children"]:
                    enclosing.setdefault(child, item)
            parsed = {item["id"]: _read(item["text"], start, _zone(driver), enclosing.get(item["id"], {}).get("text", ""))
                      for item in candidates}
            for item in candidates:
                result, tentative = parsed[item["id"]]
                # A wrapper is skipped if a child already describes the claim; a bare clock time in a child
                # does not hide a wrapper's own claim, and a bare wrapper gives way to a bare child.
                if not result or any(not inner[1] or tentative for inner in
                                     (parsed[child] for child in item["children"] if child in parsed and parsed[child][0])):
                    continue
                kind, value, resolution, unit = result
                entry = {"box": item["id"], "context": ctx, "kind": kind,
                         "path": safe_path(driver.page.url, session.fixture_values),
                         "readings": [{"when": "load", "value": value, "unit": unit,
                                       "resolution_s": resolution, "elapsed_ms": 0}]}
                if session.engine is not None and session.meta["backend"] == "stub":
                    entry["backed"] = session.engine.backed(kind, value, now_ms=start, resolution_s=resolution)
                claims.append((driver, item["id"], entry, item["text"]))
                if tentative:
                    bare.add(id(entry))
        if not claims:
            session.cover("urgency", "not-applicable", contexts=drivers)
            return

        def read_when(when):
            now = session.clock.now_ms()
            visible = {driver: {item["id"]: item for item in _visible(driver)} for driver in drivers.values()}
            for driver, box, entry, _ in claims:
                current = visible[driver].get(box)
                match = _read(current["text"], now, _zone(driver))[0] if current else None
                if match and match[0] == entry["kind"]:
                    entry["readings"].append({"when": when, "value": match[1], "unit": match[3],
                                              "resolution_s": match[2], "elapsed_ms": now - start})
                elif id(entry) not in bare:
                    missing.append(f"{entry['context']}:{box}:{when} claim not visible")

        session.advance_clock(30_000, jump=True)
        read_when("later")
        # A bare clock time that did not go down is not a claim. The rest are claims from here on.
        claims = [claim for claim in claims if id(claim[2]) not in bare or
                  any(reading["when"] == "later" and reading["value"] < claim[2]["readings"][0]["value"]
                      for reading in claim[2]["readings"])]
        bare.clear()
        if not claims:
            session.cover("urgency", "not-applicable", contexts=drivers)
            return
        for _, _, entry, _ in claims:
            session.add_probe("urgency", entry)
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
                match = _read(current["text"], now, _zone(driver))[0] if current else None
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
