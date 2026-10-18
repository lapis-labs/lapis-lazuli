"""The fixed text of the owner summary, in the owner's language (`owner.py`).

The summary is what the owner reads in chat, so its headings, the `Decision:` line, and the fixed phrases around what the
records say are written in the language of the owner's request (`owner_language.request_language`). Two catalogs exist,
`en` and `ko` (Korean in 해요체). Japanese and Chinese owners get the English text: a known limit, not a decision that
those languages need none. A key a catalog lacks falls back to English, and a test holds the two catalogs to the same keys.

Only the CLI's own words are here. What a record says (a requirement row, a finding, a rule id, a path, a plan value, the
release verdict, the lines `gaps.py` writes) is copied as it is: the questions check compares the summary verbatim, against
the text of this language, so what the CLI wrote is what has to be pasted.

Stdlib only: the stop hook imports `waiting`, which reads `TITLES`.
"""
from __future__ import annotations

from pathlib import Path

EN: dict[str, str] = {
    "title": "Owner summary",
    "decision.label": "Decision",
    "decision.done": "accept this result, or name what to fix first.",
    "decision.direction": "pick or change what the direction items name.",
    "decision.direction.settles": "pick or change what the direction items name; your answer also settles {what}.",
    "decision.approval": "approve this build or say what to change.",
    "decision.approval.settles": "approve this build or say what to change; your answer also settles {what}.",
    "settles.gaps": "the {n} decisions you have not made above",
    "settles.core": "the {n} open core findings above",
    "settles.join": " and ",
    "heading.changed": "Changed since your last word",
    "heading.gaps": "Decisions you have not made",
    "heading.gaps.unattended": "Decisions made without you",
    "heading.defects": "Defects of the build shown",
    "heading.release": "Release",
    "heading.fonts": "Fonts and rights",
    "heading.shown": "Shown",
    "none.open": "- none open.",
    "full.block": "Full block: {artifact} ({chars} characters: the requirement outcome row by row, the facts with their "
                  "sources, integrity, disputes, and what did not run).",
    "changed.drop": "- you dropped: \"{row}\" ({words})",
    "changed.narrow": "- you narrowed: \"{row}\" ({words})",
    "changed.added": "- now in your requirements: \"{text}\"",
    "changed.removed": "- no longer in your requirements: \"{text}\"",
    "changed.slice": "- changed since you approved the slice: {pointer}",
    "changed.more": "- and {n} more in the full block",
    "label.whole": "the whole page",
    "label.page": "the page {url}",
    "state.met": "met",
    "state.partly": "partly",
    "state.missing": "missing",
    "state.not-in-slice": "not-in-slice",
    "state.not-observable": "not-observable",
    "state.not-judged": "not judged",
    "req.counts": "- requirements, {label}: {parts} of {total}",
    "req.none-judged-counts": "none judged",
    "req.row": "- {state} {id} \"{text}\"",
    "req.partly": "- partly: {ids}",
    "req.no-report": "- {n} requirement rows not judged: {why}.",
    "req.unreadable": "- {label}: the critic report {path} cannot be read; {n} requirement rows not judged.",
    "why.note": "requirements not judged: {reason}",
    "why.none": "no critic report yet",
    "fault.line": "- {label}, critic report {path}: {problem}",
    "fault.more": "- {label}, critic report {path}: and {n} more gaps",
    "heading.checks": "Checks not finished for the build shown",
    "checks.kind.render": "render",
    "checks.kind.behavior": "behavior",
    "checks.running": "- {kind} check: still running since {since} (report {out}); it has not finished, so its result is not "
                      "in this summary.",
    "checks.not-run": "- {kind} check: no result for the build shown ({url}, build {build}); it has not been run for this "
                      "build.",
    "unreviewed.line": "- The slice budget ran out ({why}), so you see the slice before its review is current; nothing here "
                       "is approved by being shown.",
    "unreviewed.error": "  - {error}",
    "unreviewed.more": "  - and {n} more",
    "font.line": "{role}{scripts}: {family} — source {source}; {lock}",
    "font.unsaid": "not said",
    "font.no-lock": "no fonts lock entry yet, so no license is recorded",
    "font.lock": "fonts lock: channel {channel}, license {kind} ({state})",
    "font.needs": " — needs your word",
    "shown.page": "- {url} at {widths}",
    "shown.page-unknown": "- {url} at unknown widths",
    "shown.captures": "; captures, which open without a server: {captures}",
    "shown.file": "; the page as a file: {file}",
    "shown.support": "- supporting evidence ({kind}) {path}, sha256 {sha}: {claim}",
    "heading.roughs": "Rough first views",
    "rough.role.headline": "headline",
    "rough.role.body": "body",
    "rough.face": "{role} {shown}",
    "rough.face.card": "{role} {shown} (card: {named})",
    "rough.type": "- Rough {candidate} type, as rendered: {faces}{says}",
    "rough.type.says": "; answers the owner's type words: \"{words}\"",
    "rough.style": "- Rough {candidate} style items, {parts}",
    "rough.style.shown": "carried and shown: {items}",
    "rough.style.none": "none",
    "rough.style.claimed": "claimed, not shown: {items}",
    "rough.style.dead": "claimed, matches no element: {items}",
    "rough.style.missing": "not on the card: {items}",
    "rough.drift": "- Rough {line}",
    "rough.no-text": "no text read",
}

KO: dict[str, str] = {
    "title": "확인 요약",
    "decision.label": "결정",
    "decision.done": "이 결과를 받아들이거나, 먼저 고칠 점을 알려 주세요.",
    "decision.direction": "방향 항목에 적힌 것 중에서 고르거나 바꿔 주세요.",
    "decision.direction.settles": "방향 항목에 적힌 것 중에서 고르거나 바꿔 주세요. 이 답으로 아래의 {what}도 함께 정해져요.",
    "decision.approval": "지금 만든 화면을 승인하거나, 바꿀 점을 알려 주세요.",
    "decision.approval.settles": "지금 만든 화면을 승인하거나, 바꿀 점을 알려 주세요. 이 답으로 아래의 {what}도 함께 정해져요.",
    "settles.gaps": "정하지 않으신 결정 {n}개",
    "settles.core": "열려 있는 핵심 지적 {n}개",
    "settles.join": "와 ",
    "heading.changed": "지난번 답 이후 바뀐 것",
    "heading.gaps": "아직 정하지 않으신 결정",
    "heading.gaps.unattended": "사용자 없이 정한 결정",
    "heading.defects": "보여 드린 화면의 문제",
    "heading.release": "릴리스",
    "heading.fonts": "폰트와 사용 권리",
    "heading.shown": "보여 드린 것",
    "none.open": "- 열려 있는 문제는 없어요.",
    "full.block": "전체 기록: {artifact} ({chars}자. 요구사항별 결과, 근거와 출처, 무결성, 이의 제기, 실행하지 않은 것이 "
                  "들어 있어요).",
    "changed.drop": "- 빼기로 하신 것: \"{row}\" ({words})",
    "changed.narrow": "- 좁히기로 하신 것: \"{row}\" ({words})",
    "changed.added": "- 요구사항에 새로 들어간 것: \"{text}\"",
    "changed.removed": "- 요구사항에서 빠진 것: \"{text}\"",
    "changed.slice": "- 슬라이스를 승인한 뒤 바뀐 것: {pointer}",
    "changed.more": "- 그 밖에 {n}개는 전체 기록에 있어요",
    "label.whole": "전체 화면",
    "label.page": "화면 {url}",
    "state.met": "충족",
    "state.partly": "일부 충족",
    "state.missing": "빠짐",
    "state.not-in-slice": "이번 슬라이스 밖",
    "state.not-observable": "확인할 수 없음",
    "state.not-judged": "아직 판단 못 함",
    "req.counts": "- 요구사항, {label}: {parts} (전체 {total}개)",
    "req.none-judged-counts": "판단된 것 없음",
    "req.row": "- {state} {id} \"{text}\"",
    "req.partly": "- 일부 충족: {ids}",
    "req.no-report": "- 요구사항 {n}개를 아직 판단하지 못했어요: {why}.",
    "req.unreadable": "- {label}: 비평 보고서({path})를 읽을 수 없어서, 요구사항 {n}개를 판단하지 못했어요.",
    "why.note": "판단하지 못한 이유: {reason}",
    "why.none": "아직 비평 보고서가 없어요",
    "fault.line": "- {label}, 비평 보고서 {path}: {problem}",
    "fault.more": "- {label}, 비평 보고서 {path}: 그 밖에 {n}개 더",
    "heading.checks": "끝나지 않은 검사",
    "checks.kind.render": "화면 캡처(render)",
    "checks.kind.behavior": "동작(behavior)",
    "checks.running": "- {kind} 검사가 {since}부터 아직 돌고 있어요(보고서 {out}). 끝나지 않아서 이 요약에는 결과가 없어요.",
    "checks.not-run": "- {kind} 검사: 보여 드린 화면({url}, 빌드 {build})에 대한 결과가 없어요. 이 빌드에는 아직 돌리지 "
                      "않았어요.",
    "unreviewed.line": "- 슬라이스 시간 한도가 지나서({why}) 검토가 끝나기 전의 슬라이스를 보여 드려요. 보여 드렸다고 해서 "
                       "승인된 것은 아니에요.",
    "unreviewed.error": "  - {error}",
    "unreviewed.more": "  - 그 밖에 {n}개",
    "font.line": "{role}{scripts}: {family} — 출처 {source}; {lock}",
    "font.unsaid": "밝히지 않음",
    "font.no-lock": "fonts lock에 아직 항목이 없어서 기록된 라이선스가 없어요",
    "font.lock": "fonts lock 기록: 경로 {channel}, 라이선스 {kind} ({state})",
    "font.needs": " — 사용자의 확인이 필요해요",
    "shown.page": "- {url} ({widths} 너비에서 확인)",
    "shown.page-unknown": "- {url} (확인한 너비를 알 수 없어요)",
    "shown.captures": "; 서버 없이 열리는 캡처: {captures}",
    "shown.file": "; 파일로 바로 여는 화면: {file}",
    "shown.support": "- 뒷받침 자료({kind}) {path}, sha256 {sha}: {claim}",
    "heading.roughs": "러프 첫 화면",
    "rough.role.headline": "제목",
    "rough.role.body": "본문",
    "rough.face": "{role} {shown}",
    "rough.face.card": "{role} {shown}(카드에는 {named})",
    "rough.type": "- 러프 {candidate} 글자(화면에 그려진 대로): {faces}{says}",
    "rough.type.says": "; 사용자의 글자 이야기에 대한 답: \"{words}\"",
    "rough.style": "- 러프 {candidate} 스타일 항목, {parts}",
    "rough.style.shown": "담고 보여 주는 것: {items}",
    "rough.style.none": "없음",
    "rough.style.claimed": "카드에는 있지만 캡처에 안 보이는 것: {items}",
    "rough.style.dead": "카드에는 있지만 맞는 요소가 없는 것: {items}",
    "rough.style.missing": "카드에 없는 것: {items}",
    "rough.drift": "- 러프 {line}",
    "rough.no-text": "읽은 글자 없음",
}

CATALOGS: dict[str, dict[str, str]] = {"en": EN, "ko": KO}
TITLES: tuple[str, ...] = tuple(catalog["title"] for catalog in CATALOGS.values())


def language(root: Path, task: str) -> str:
    """`ko` for an owner whose request is clearly Korean, else `en`: a Japanese or Chinese request gets the English text
    (the known limit above)."""
    from lapis_design import owner_language

    found = owner_language.request_language(owner_language.request_texts(root, task))
    return "ko" if found == "Korean" else "en"


def say(lang: str, key: str, **values: object) -> str:
    """The text of `key` in `lang`, filled in with `values`."""
    return (CATALOGS.get(lang) or EN).get(key, EN[key]).format(**values)
