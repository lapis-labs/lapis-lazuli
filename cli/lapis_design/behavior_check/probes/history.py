"""Exercise browser Back, POST reload, and the signed-out deep-link return path."""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from lapis_design.behavior_check.probes._decision import names
from lapis_design.behavior_check.redact import path as safe_path

NAMES = ("history",)
_PRIVATE = re.compile(r"(?:account|profile|private|protected|dashboard|checkout|orders?|예약\s*내역|마이\s*페이지)", re.I)
_FILTER = re.compile(r"(?:filter|category|sort|필터|분류|정렬)", re.I)
_PAGE = re.compile(r"(?:page|next|previous|페이지|다음|이전)", re.I)


def _path(driver):
    return safe_path(driver.page.url, driver.session.fixture_values)


def _state(driver):
    named = names(driver)                       # a link's wording is its accessible name (alt, aria-label), not its text
    return driver.page.evaluate("""named => ({scroll:scrollY,
      fields:[...document.querySelectorAll('input,textarea,select')]
        .filter(el=>el.type!=='hidden' && el.getBoundingClientRect().width)
        .map(el=>({id:el.getAttribute('data-lapis-box'),name:el.id||el.name||'',type:el.type,
          value:el.value,checked:el.checked,selected:el.selectedIndex})),
      selected:[...document.querySelectorAll('[aria-selected=true],[aria-pressed=true],[aria-current=page]')]
        .map(el=>el.getAttribute('data-lapis-box')),
      pages:[...document.querySelectorAll('[aria-current=page]')]
        .map(el=>el.textContent.trim()),
      dialogs:[...document.querySelectorAll('dialog[open],[role=dialog],[aria-modal=true]')]
        .filter(el=>el.getBoundingClientRect().width).length,
      links:[...document.querySelectorAll('a[href]')]
        .filter(el=>el.getBoundingClientRect().width && el.getBoundingClientRect().height)
        .map(el=>({id:el.getAttribute('data-lapis-box'),href:el.href,
          name:(named[el.getAttribute('data-lapis-box')]||el.innerText||el.getAttribute('aria-label')||'').trim()}))})""", named)


def _restore(before, after):
    result = {}
    fields = {field["id"]: field for field in after["fields"]}
    typed = [field for field in before["fields"] if field["type"] not in ("checkbox", "radio", "select-one") and field["value"]]
    filters = [field for field in before["fields"] if _FILTER.search(field["name"]) and
               (field["checked"] or field["value"])]
    selections = [field for field in before["fields"] if field["type"] in ("radio", "select-one") and
                  (field["checked"] or field["selected"] > 0)]
    if filters:
        result["filters"] = all(field["id"] in fields and
                                fields[field["id"]]["value"] == field["value"] and
                                fields[field["id"]]["checked"] == field["checked"] for field in filters)
    if typed:
        result["input"] = all(field["id"] in fields and fields[field["id"]]["value"] == field["value"] for field in typed)
    if selections or before["selected"]:
        result["selection"] = all(field["id"] in fields and fields[field["id"]]["value"] == field["value"] and
                                  fields[field["id"]]["checked"] == field["checked"] for field in selections) and \
                              before["selected"] == after["selected"]
    if before["pages"]:
        result["page"] = before["pages"] == after["pages"]
    if before["scroll"] > 100:
        result["scroll"] = abs(before["scroll"] - after["scroll"]) <= 100
    return result


def _local_link(driver, links, *, private=False):
    origin = urlsplit(driver.page.url)
    for link in links:
        url = urlsplit(link["href"])
        if (url.scheme not in ("http", "https") or url.netloc != origin.netloc or
                url.path == origin.path or not link["id"]):
            continue
        if bool(_PRIVATE.search(url.path + " " + link["name"])) == private:
            return link
    return None


def _prepare(driver, engine):
    state = _state(driver)
    for field in state["fields"]:
        if field["type"] == "checkbox" and _FILTER.search(field["name"]) and not field["checked"]:
            driver.act({"kind": "click", "target": field["id"]})
            break
    for field in state["fields"]:
        if field["type"] in ("search", "text") and engine is not None and not field["value"]:
            try:
                value_id = engine.values_for("search" if field["type"] == "search" else "text", "valid")
                driver.act({"kind": "paste", "target": field["id"], "value_id": value_id})
            except KeyError:
                pass
            break
    page_button = next((box for box in driver.boxes() if box["role"] == "button" and
                        (_PAGE.search(box["name"] or "") or (box["name"] or "").isdigit())), None)
    if page_button and not _PRIVATE.search(page_button["name"] or ""):
        driver.act({"kind": "click", "target": page_button["id"]})
    driver.page.evaluate("scrollTo(0,Math.min(350,document.documentElement.scrollHeight-innerHeight))")


def _navigation_back(session, driver):
    driver.open(urlsplit(session.source["url"]).path or "/")
    _prepare(driver, session.values_engine)
    before = _state(driver)
    link = _local_link(driver, before["links"])
    if not link:
        return False
    driver.act({"kind": "click", "target": link["id"]})
    if _path(driver) == safe_path(session.source["url"], session.fixture_values):
        return False
    from_path = _path(driver)
    driver.page.go_back(wait_until="domcontentloaded", timeout=3000)
    driver.boxes()
    session.add_probe("history", {"context": driver.ctx_id, "action": "back", "from": from_path,
                                  "to": _path(driver), "presses": 1,
                                  "left_page": _path(driver) != from_path,
                                  "restored": _restore(before, _state(driver))})
    return True


def _entry_back(session, driver):
    driver.open(urlsplit(session.source["url"]).path or "/")
    driver.page.goto("about:blank", wait_until="domcontentloaded")
    blank_length = driver.page.evaluate("history.length")
    driver.page.goto(session.start_url, wait_until="domcontentloaded")
    driver.boxes()
    initial = _state(driver)
    page_path = _path(driver)
    pushed = max(0, driver.page.evaluate("history.length") - blank_length - 1)
    overlay = initial["dialogs"] > 0
    opened_by = "page" if overlay else None
    if not overlay:
        opener = driver.page.locator('button[aria-haspopup="dialog"],button[aria-haspopup="menu"]').first
        if opener.count():
            box = opener.get_attribute("data-lapis-box")
            if box:
                driver.act({"kind": "click", "target": box})
                if _state(driver)["dialogs"]:
                    opened_by = "user"
    presses = 0
    closed = False
    for _ in range(3):
        presses += 1
        prior = _state(driver)["dialogs"]
        previous = driver.page.url
        previous_state = driver.page.evaluate("JSON.stringify(history.state)")
        response = driver.page.go_back(wait_until="domcontentloaded", timeout=3000)
        if driver.page.url == "about:blank":
            break
        current_dialogs = _state(driver)["dialogs"]
        if presses == 1 and prior and current_dialogs < prior:
            closed = True
        if response is None and driver.page.url == previous and current_dialogs == prior and \
                driver.page.evaluate("JSON.stringify(history.state)") == previous_state:
            break
    entry = {"context": driver.ctx_id, "action": "back", "from": page_path,
             "presses": presses, "left_page": driver.page.url == "about:blank",
             "pushed_entries": pushed, "overlay_closed_first": closed}
    if driver.page.url != "about:blank":
        entry["to"] = _path(driver)
    if closed:
        entry["overlay_opened_by"] = opened_by
    session.add_probe("history", entry)


def _reload_post(session, driver):
    driver.open(urlsplit(session.source["url"]).path or "/")
    if session.meta["backend"] != "stub" and session.meta.get("outbound") != "none":
        return "Form submission not safe without stub or local-dev outbound none"
    form = driver.page.locator("form[method=post],form[method=POST]").first
    if not form.count():
        return None
    if not form.locator("button[type=submit],input[type=submit]").count():
        return "POST form has no submit control"
    if form.locator("input[required]:not([type=hidden])").count():
        return "POST form requires input; no general fixture-to-form mapping"
    action = form.get_attribute("action") or driver.page.url
    if urlsplit(urljoin(driver.page.url, action)).netloc != urlsplit(session.source["url"]).netloc:
        return "POST form targets a different host"
    source_path = _path(driver)
    button = form.locator("button[type=submit],input[type=submit]").first
    target = button.get_attribute("data-lapis-box")
    driver.act({"kind": "click", "target": target})
    if _path(driver) == source_path and driver.page.evaluate("performance.getEntriesByType('navigation')[0]?.type") != "navigate":
        return "POST form did not navigate to a submitted document"
    submitted = _path(driver)
    # A browser offers to resend a form exactly when reloading the current entry repeats its POST
    # (no redirect to a GET after submission). Automation confirms that offer without a visible
    # dialog, so the reload's document request method is the observation.
    methods = []
    def on_request(request):
        if request.is_navigation_request() and request.frame == driver.page.main_frame:
            methods.append(request.method)
    driver.page.on("request", on_request)
    try:
        driver.page.reload(wait_until="domcontentloaded", timeout=5000)
    finally:
        driver.page.remove_listener("request", on_request)
    session.add_probe("history", {"context": driver.ctx_id, "action": "reload", "from": submitted,
                                  "to": _path(driver), "resubmit_prompt": "POST" in methods})
    return None


def _deep_link(session, driver):
    if session.meta["backend"] != "stub" or session.engine is None:
        return "Deep-link sign-in requires stub backend"
    account = session.engine.account()
    if not account:
        return None
    driver.open(urlsplit(session.source["url"]).path or "/")
    state = _state(driver)
    private = _local_link(driver, state["links"], private=True)
    paths = [flow.get("start", "/") for flow in (session.plan or {}).get("flows", [])]
    target = private["href"] if private else next((path for path in paths if _PRIVATE.search(path)), None)
    if target is None:
        return "Synthetic account exists, but no protected route is discoverable"
    driver.open(urlsplit(urljoin(session.source["url"], target)).path)
    login = driver.page.locator("form").filter(has=driver.page.locator('input[type=password]')).first
    if not login.count():
        return "Protected route did not show a sign-in form"
    username = login.locator('input:not([type=hidden]):not([type=password])').first
    password = login.locator('input[type=password]').first
    submit = login.locator('button[type=submit],input[type=submit]').first
    if not username.count() or not password.count() or not submit.count():
        return "Sign-in form lacks identifier, password, or submit"
    driver.boxes()
    driver.act({"kind": "paste", "target": username.get_attribute("data-lapis-box"),
                "value_id": account["username"]})
    driver.act({"kind": "paste", "target": password.get_attribute("data-lapis-box"),
                "value_id": account["password"]})
    driver.act({"kind": "click", "target": submit.get_attribute("data-lapis-box")})
    landed = _path(driver)
    wanted = safe_path(urljoin(session.source["url"], target), session.fixture_values)
    home = safe_path(session.source["url"], session.fixture_values)
    session.add_probe("history", {"context": driver.ctx_id, "action": "deep-link-after-sign-in",
                                  "from": wanted, "to": landed,
                                  "landed": "target" if landed == wanted else "home" if landed == home else "other"})
    return None


def run(session, open_driver):
    incomplete = []
    count = 0
    for ctx in session.matrix:
        driver = open_driver(ctx)
        try:
            for name, fn in (("navigation", _navigation_back), ("entry", _entry_back),
                             ("reload", _reload_post), ("deep-link", _deep_link)):
                try:
                    before = len(session.probes.get("history", []))
                    result = fn(session, driver)
                    count += len(session.probes.get("history", [])) - before
                    if result is False or isinstance(result, str):
                        incomplete.append(f"{ctx}:{name}: {result if isinstance(result, str) else 'no navigable link'}")
                except Exception as exc:
                    incomplete.append(f"{ctx}:{name}: {type(exc).__name__}: {exc}")
        finally:
            driver.close()
    session.cover("history", "partial" if incomplete else "ran" if count else "not-applicable",
                  contexts=list(session.matrix), reason="; ".join(incomplete) if incomplete else None)
