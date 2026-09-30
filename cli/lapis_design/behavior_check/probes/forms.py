"""Fresh-load form experiments using only synthetic fixture values."""
from __future__ import annotations

import re


NAMES = ("forms",)

_CHOICES = {"checkbox", "radio", "switch", "select"}


def _forms(driver):
    driver.boxes()
    return driver.page.evaluate("""() => [...document.querySelectorAll('form,[role=form]')]
      .filter(el => el.getClientRects().length && el.querySelector('input,select,textarea,[role=switch]'))
      .map(el => el.getAttribute('data-lapis-box')).filter(Boolean)""")


def _field_data(driver, form_id):
    driver.boxes()
    return driver.locate(form_id).evaluate("""(form) => [...form.querySelectorAll(
      'input:not([type=hidden]):not([type=submit]):not([type=button]),select,textarea,[role=switch]')]
      .filter(el => el.getClientRects().length && el.hasAttribute('data-lapis-box')).map(el => {
        const style = node => node && node.getClientRects().length &&
          getComputedStyle(node).visibility !== 'hidden' && getComputedStyle(node).display !== 'none';
        const labels = [...el.labels || []].filter(style);
        const explicit = el.getAttribute('aria-labelledby')?.split(/\\s+/).map(id => document.getElementById(id)).filter(style) || [];
        const texts = [...labels, ...explicit].map(node => node.innerText.trim()).filter(Boolean);
        const named = !!(texts.length || el.getAttribute('aria-label'));
        const kind = el.getAttribute('role') === 'switch' ? 'switch' : el.tagName === 'SELECT' ? 'select' :
          el.tagName === 'TEXTAREA' ? 'textarea' : (el.type === 'email' ? 'email' : el.type === 'tel' ? 'tel' :
          ['password','number','date','checkbox','radio','file'].includes(el.type) ? el.type : 'text');
        return {box:el.getAttribute('data-lapis-box'), kind, required:el.required || el.getAttribute('aria-required') === 'true',
          sensitive:el.type === 'password' || /(?:otp|one.time|verification|card|cvc|cvv|expir)/i.test(
            [el.name,el.id,el.autocomplete].join(' ')), checked:el.checked,
          prefilled:!!el.value && !['checkbox','radio'].includes(kind),
          label:{visible:!!texts.length, programmatic:named},
          text: [el.name, el.id, ...texts].join(' ').toLowerCase(),
          autocomplete:el.autocomplete || '', value:el.value};
      })""")


def _purpose(text):
    if re.search(r"marketing|newsletter|promotions?|offers?|emails? about|마케팅|뉴스레터|광고성|홍보|혜택", text):
        return "marketing"
    if re.search(r"terms|conditions|agreement|privacy policy|약관|개인 ?정보 ?처리 ?방침", text):
        return "terms"
    if re.search(r"add.on|insurance|extra|upgrade|gift.wrap|추가 ?상품|보험|업그레이드|선물 ?포장", text):
        return "add-on"
    if re.search(r"consent|permission|agree|opt.in|동의|권한|허용|수신 ?신청", text):
        return "consent"
    return "data"


def _errors(driver, form_id):
    return driver.locate(form_id).evaluate("""form => {
      const fields = [...form.querySelectorAll('input,select,textarea,[role=switch]')];
      const visible = el => !!el && !!el.getClientRects().length &&
        getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none';
      const messages = [...form.querySelectorAll('[role=alert],[aria-live],.error,.field-error,[id*=error], [data-error]')]
        .filter(el => visible(el) && el.innerText?.trim() &&
          ![...el.children].some(child => visible(child) && child.matches('[role=alert],.error,.field-error,[id*=error]')));
      const invalid = fields.filter(el => el.getAttribute('aria-invalid') === 'true');
      return {messages:messages.map(el => ({text:el.innerText.trim(), id:el.id,
        associated:fields.some(field => [field.getAttribute('aria-describedby'), field.getAttribute('aria-errormessage')]
          .some(ids => ids?.split(/\\s+/).includes(el.id) && el.id) || [...field.labels || []].some(label => label.contains(el)))})),
        invalid:invalid.map(el => el.getAttribute('data-lapis-box')).filter(Boolean),
        focus:document.activeElement?.getAttribute('data-lapis-box') || null};
    }""")


def _values(driver, fields):
    return {f["box"]: driver.locate(f["box"]).evaluate("el => el.type === 'checkbox' || el.type === 'radio' ? el.checked : el.value")
            for f in fields}


def _preserved(driver, form_id, fields, prior, after):
    current = _values(driver, fields)
    kept = cleared = sensitive = 0
    boxes = []
    for field in fields:
        box = field["box"]
        if not prior.get(box) or isinstance(prior[box], bool):
            continue
        if current.get(box) == prior[box]:
            kept += not field["sensitive"]
        elif not current.get(box):
            boxes.append(box)
            if field["sensitive"]:
                sensitive += 1
            else:
                cleared += 1
    result = {"after": after, "kept": kept, "cleared": cleared,
              "cleared_sensitive": sensitive, "cleared_boxes": boxes}
    if sensitive:
        result["explained"] = bool(re.search(r"(clear|remov|eras).{0,35}(secur|protect|expir|session)",
                                             driver.locate(form_id).inner_text(), re.I))
    return result


def _value_kind(field):
    value_kind = {"tel": "phone", "textarea": "text", "otp": "code"}.get(field["kind"], field["kind"])
    hint = field["autocomplete"].lower()
    if "cc-number" in hint:
        value_kind = "card"
    elif "cc-exp" in hint:
        value_kind = "card-expiry"
    elif "cc-csc" in hint:
        value_kind = "card-cvc"
    elif "one-time-code" in hint:
        value_kind = "code"
    return value_kind


def _input_action(driver, field, kind, variant):
    action = {"kind": kind, "target": field["box"], "value": variant,
              "value_id": driver.session.values_engine.values_for(_value_kind(field), variant)}
    driver.act(action)
    return action


def _enter(driver, field, value="valid"):
    kind = field["kind"]
    box = field["box"]
    if kind in ("checkbox", "radio", "switch"):
        if not driver.locate(box).is_checked():
            driver.act({"kind": "check", "target": box})
        return None
    if kind == "select":
        options = driver.locate(box).locator("option").all()
        option = next((o for o in options if o.get_attribute("value") and not o.is_disabled()), None)
        if option:
            driver.locate(box).select_option(value=option.get_attribute("value"))
        return None
    if kind == "file":
        return None
    return _input_action(driver, field, "type", value).get("value_id")


def _submit(driver, form_id):
    button = driver.locate(form_id).locator('button[type=submit],input[type=submit],button:not([type])').first
    if not button.count():
        return None, None
    driver.boxes()
    box = button.get_attribute("data-lapis-box")
    if not box:
        return None, None
    return box, driver.act({"kind": "click", "target": box})


def _one(driver, form_id, session, gaps):
    outer_gaps = gaps
    gaps = set()
    fields = _field_data(driver, form_id)
    form = driver.locate(form_id)
    desc = " ".join([form.get_attribute("id") or "", form.get_attribute("aria-label") or "",
                     form.inner_text()[:150]]).lower()
    purpose = next((name for name, pattern in (("sign-in", r"sign.in|log.in"), ("signup", r"sign.up|register|create.account"),
              ("checkout", r"checkout|payment"), ("reservation", r"reserv"), ("search", r"search"),
              ("contact", r"contact"), ("settings", r"settings"), ("consent", r"consent"))
              if re.search(pattern, desc)), "other")
    safe_submit = session.meta["backend"] == "stub" or (purpose == "search" and
                                                          (form.get_attribute("method") or "get").lower() == "get")
    entry = {"box": form_id, "context": driver.ctx_id, "purpose": purpose, "fields": []}
    first = _errors(driver, form_id)
    for f in fields:
        row = {key: f[key] for key in ("box", "kind", "required", "sensitive", "prefilled", "label")}
        row["label"]["programmatic"] = bool(session.nodes.get(f["box"], {}).get("name"))
        row["purpose"] = _purpose(f["text"]) if f["kind"] in _CHOICES else "data"
        if f["kind"] in ("checkbox", "switch", "radio"):
            row["checked_on_load"] = bool(f["checked"])
        entry["fields"].append(row)
    entry["validation"] = {"untouched_invalid_on_load": bool(first["messages"] or first["invalid"]),
                           "first_error": "load" if first["messages"] or first["invalid"] else "never"}
    for field, row in zip(fields, entry["fields"]):
        if field["kind"] in _CHOICES or field["kind"] == "file":
            continue
        driver.reload()
        before = _errors(driver, form_id)
        if session.values_engine is None:
            gaps.add("synthetic values unavailable for typing/paste")
            continue
        try:
            # Input events are observed during the driver's per-character typing, before its settle window.
            driver.locate(field["box"]).evaluate("""el => {
              el.dataset.lapisFirstError='';
              el.addEventListener('input', () => {if(!el.dataset.lapisFirstError &&
                (el.getAttribute('aria-invalid')==='true' || el.form?.querySelector('[role=alert]:not(:empty),.error:not(:empty)')))
                el.dataset.lapisFirstError='keystroke'});
            }""")
            action = _input_action(driver, field, "type", "invalid")
            row["value_id"] = action["value_id"]
            observed = next((f for f in _field_data(driver, form_id) if f["box"] == field["box"]), None)
            if observed:
                row["label"]["persists_after_input"] = observed["label"]["visible"]
            else:
                gaps.add(f"{driver.ctx_id}: {field['kind']} label no longer observable after input")
            during = driver.locate(field["box"]).get_attribute("data-lapis-first-error")
            if during:
                stage = "keystroke"
            else:
                driver.act({"kind": "key", "key": "Tab"})
                blurred = _errors(driver, form_id)
                stage = "blur" if (blurred["messages"], blurred["invalid"]) != (before["messages"], before["invalid"]) else "never"
            if stage == "never" and safe_submit and _submit(driver, form_id)[1] is not None:
                submitted = _errors(driver, form_id)
                if (submitted["messages"], submitted["invalid"]) != (before["messages"], before["invalid"]):
                    stage = "submit"
            if entry["validation"]["first_error"] != "load":
                order = {"keystroke": 0, "blur": 1, "submit": 2, "never": 3}
                if order[stage] < order[entry["validation"]["first_error"]]:
                    entry["validation"]["first_error"] = stage
        except (KeyError, ValueError) as exc:
            gaps.add(f"{field['kind']} typing unavailable: {exc}")
        driver.reload()
        try:
            pasted = _input_action(driver, field, "paste", "valid")
            row["paste_blocked"] = driver.locate(field["box"]).input_value() != session.values_engine.value(pasted["value_id"])
        except (KeyError, ValueError) as exc:
            gaps.add(f"{field['kind']} paste unavailable: {exc}")
    for field, row in zip(fields, entry["fields"]):
        if field["kind"] not in _CHOICES:
            continue
        if not safe_submit and row["purpose"] != "data":
            gaps.add(f"{driver.ctx_id}: {row['purpose']} change could commit on local-dev backend")
            continue
        driver.reload()
        before_focus = driver.page.evaluate("document.activeElement?.getAttribute('data-lapis-box')")
        before_url = driver.page.url
        before_popups = driver._popups
        before_requests = len(driver.network.entries)
        before_dialogs = driver.page.locator("dialog[open],[role=dialog][open],[role=alertdialog][open]").count()
        if field["kind"] == "select":
            opts = driver.locate(field["box"]).locator("option").all()
            current = driver.locate(field["box"]).input_value()
            option = next((o for o in opts if o.get_attribute("value") != current and not o.is_disabled()), None)
            if not option:
                gaps.add("select has no alternative option")
                continue
            driver.locate(field["box"]).select_option(value=option.get_attribute("value"))
            driver.page.wait_for_timeout(500)
            current_focus = driver.page.evaluate("document.activeElement?.getAttribute('data-lapis-box')")
            row["on_change"] = ("new-window" if driver._popups > before_popups else
                "navigated" if driver.page.url != before_url else
                "submitted" if any(r["method"] != "GET" for r in driver.network.entries[before_requests:]) else
                "dialog-opened" if driver.page.locator("dialog[open],[role=dialog][open],[role=alertdialog][open]").count() > before_dialogs else
                "focus-moved" if current_focus not in (None, before_focus, field["box"]) else "none")
            effect = None
        else:
            effect = driver.act({"kind": "uncheck" if field["checked"] else "check", "target": field["box"]})
        if effect:
            row["on_change"] = ("new-window" if effect["navigation"] == "new-window" else
                "navigated" if effect["navigation"] in ("document", "same-document") else
                "submitted" if any(r["method"] != "GET" for r in effect["requests"]) else
                "dialog-opened" if effect.get("dialog_opened") else
                "focus-moved" if effect["focus_to"] not in (before_focus, field["box"]) and effect["focus_to"] else "none")
        if driver.page.locator(f'[data-lapis-box="{field["box"]}"]').count() and driver.page.locator(f'[data-lapis-box="{form_id}"]').count():
            observed = next((f for f in _field_data(driver, form_id) if f["box"] == field["box"]), None)
            if observed:
                row["label"]["persists_after_input"] = observed["label"]["visible"]
        else:
            gaps.add(f"{driver.ctx_id}: {field['kind']} label no longer observable after change")
    driver.reload()
    button = driver.locate(form_id).locator('button[type=submit],input[type=submit],button:not([type])').first
    can_fill = session.values_engine is not None
    if can_fill:
        for field in fields:
            if field["kind"] in _CHOICES or field["kind"] == "file":
                if field["kind"] == "file" and field["required"]:
                    gaps.add(f"{driver.ctx_id}: required file input has no synthetic upload")
                    can_fill = False
                continue
            try:
                session.values_engine.values_for(_value_kind(field), "valid")
            except (KeyError, ValueError) as exc:
                can_fill = False
                gaps.add(f"{driver.ctx_id}: no synthetic {field['kind']} value ({exc})")
    else:
        gaps.add(f"{driver.ctx_id}: no synthetic fixture values for form input")
    if button.count():
        driver.boxes()
        button_box = button.get_attribute("data-lapis-box")
        disabled = button.is_disabled() or button.get_attribute("aria-disabled") == "true"
        submit = {"box": button_box}
        if disabled:
            submit["reason_visible"] = bool(re.search(r"(required|must|please|missing|complete|enter|fill)",
                                                       driver.locate(form_id).inner_text(), re.I))
            if safe_submit:
                requests = len(driver.network.entries)
                if button.is_disabled():
                    button.evaluate("el => el.click()")
                else:
                    driver.act({"kind": "click", "target": button_box})
                submit["disabled_sends"] = any(r["method"] != "GET" for r in driver.network.entries[requests:])
            else:
                gaps.add(f"{driver.ctx_id}: disabled submit activation unavailable on local-dev backend")
            if can_fill:
                driver.reload()
                for field in fields:
                    if field["kind"] != "file":
                        try:
                            _enter(driver, field)
                        except (KeyError, ValueError) as exc:
                            gaps.add(f"{driver.ctx_id}: valid value unavailable for {field['kind']}: {exc}")
                submit["disabled_until_valid"] = not (button.is_disabled() or button.get_attribute("aria-disabled") == "true")
                driver.reload()
            else:
                gaps.add(f"{driver.ctx_id}: cannot verify disabled-until-valid without synthetic values")
        else:
            submit["disabled_until_valid"] = False
        entry["submit"] = submit
    if safe_submit and can_fill and button.count() and not button.is_disabled():
        driver.reload()
        invalid_field = next((f for f in fields if f["kind"] not in _CHOICES and f["kind"] != "file"), None)
        if invalid_field is None:
            invalid_field = next((f for f in fields if f["required"] and f["kind"] in ("checkbox", "switch")), None)
        if invalid_field is None:
            gaps.add(f"{driver.ctx_id}: no field with an inducible invalid value in form")
        def field_colors():
            return driver.locate(invalid_field["box"]).evaluate(
                "el => {const s=getComputedStyle(el);return [s.color,s.borderColor,s.backgroundColor]}")
        initial_colors = field_colors() if invalid_field else None
        for field in fields:
            if field is invalid_field and field["kind"] in ("checkbox", "switch"):
                if driver.locate(field["box"]).is_checked():
                    driver.act({"kind": "uncheck", "target": field["box"]})
            elif field["kind"] != "file":
                _enter(driver, field, "invalid" if field is invalid_field else "valid")
        prior = _values(driver, fields)
        before_text = driver.locate(form_id).inner_text().lower()
        button_box, effect = _submit(driver, form_id)
        if effect is not None:
            errors = _errors(driver, form_id)
            color_changed = bool(invalid_field and initial_colors != field_colors())
            focused = errors["focus"]
            entry["invalid_submit"] = {"errors": len(errors["messages"]),
                "described_in_text": bool(errors["messages"]),
                "associated": bool(errors["messages"]) and all(m["associated"] for m in errors["messages"]),
                "color_only": color_changed and not errors["messages"],
                "focus_to": "first-error" if focused in errors["invalid"] else
                  "submit" if focused == button_box else "summary" if focused and focused != button_box and
                  focused not in [f["box"] for f in fields] else "body" if not focused else "other",
                "announced": bool(effect["announcements"]),
                "new_requirement": any(bool(re.search(r"(at least|characters?|format|length|digits?|must contain)", m["text"], re.I))
                                       and m["text"].lower() not in before_text for m in errors["messages"])}
            entry["preservation"] = [_preserved(driver, form_id, fields, prior, "invalid-submit")]
        if session.meta["backend"] == "stub":
            driver.reload()
            for field in fields:
                if field["kind"] != "file":
                    _enter(driver, field)
            prior = _values(driver, fields)
            session.engine.inject("fail-5xx", method="POST", times=1)
            try:
                _, effect = _submit(driver, form_id)
                if effect and any(r.get("injected") == "fail-5xx" for r in effect["requests"]):
                    entry.setdefault("preservation", []).append(_preserved(driver, form_id, fields, prior, "server-error"))
                else:
                    gaps.add("form submit did not reach a POST stub route for fail-5xx")
            finally:
                session.engine.clear_injections()
        else:
            gaps.add("server-error preservation requires stub backend")
        field_boxes = {field["box"] for field in fields}
        multi_step = any(flow["context"] == driver.ctx_id and len(flow["steps"]) > 1 and
                         any(action.get("target") in field_boxes
                             for step in flow["steps"] for action in step.get("actions", []))
                         for flow in session.flows)
        if multi_step or re.search(r"(draft|save.progress|continue|next step|step [0-9]|임시 ?저장|이어 ?하기|다음 ?단계|[0-9]+ ?단계)", desc):
            driver.reload()
            for field in fields:
                if field["kind"] != "file":
                    _enter(driver, field)
            prior = _values(driver, fields)
            driver.reload(reset_storage=False)
            entry.setdefault("preservation", []).append(_preserved(driver, form_id, fields, prior, "reload"))
            driver.reload()
            for field in fields:
                if field["kind"] != "file":
                    _enter(driver, field)
            prior = _values(driver, fields)
            next_control = driver.locate(form_id).locator("button,a").filter(
                has_text=re.compile(r"next|continue|review|step|다음|계속|검토|단계", re.I)).first
            if next_control.count():
                driver.boxes()
                next_box = next_control.get_attribute("data-lapis-box")
                if next_box:
                    effect = driver.act({"kind": "click", "target": next_box})
                    if effect["navigation"] in ("same-document", "document"):
                        driver.act({"kind": "back"})
                        if driver.page.locator(f'[data-lapis-box="{form_id}"]').count():
                            entry["preservation"].append(_preserved(driver, form_id, fields, prior, "back"))
                        else:
                            gaps.add(f"{driver.ctx_id}: form was not reachable after Back")
                    else:
                        gaps.add(f"{driver.ctx_id}: next step did not create browser history for Back")
                else:
                    gaps.add(f"{driver.ctx_id}: next step has no observable box id")
            else:
                gaps.add(f"{driver.ctx_id}: no next step available to induce Back")
            auth = getattr(session.engine, "fixture", {}).get("auth") if session.engine is not None else None
            if auth:
                driver.reload()
                for field in fields:
                    if field["kind"] != "file":
                        _enter(driver, field)
                prior = _values(driver, fields)
                driver.context.clear_cookies()
                account = session.engine.account()
                credentials = {key: session.engine.value(account[key]) for key in ("username", "password")}
                signed_in = driver.page.evaluate("""async ({path,credentials}) => {
                  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},
                    body:JSON.stringify(credentials)});
                  return response.ok;
                }""", {"path": auth["sign_in"]["path"], "credentials": credentials})
                if signed_in:
                    driver.reload(reset_storage=False)
                    entry["preservation"].append(_preserved(driver, form_id, fields, prior, "reauth"))
                else:
                    gaps.add(f"{driver.ctx_id}: synthetic forced re-sign-in failed")
            else:
                gaps.add(f"{driver.ctx_id}: forced re-sign-in unavailable without a stub auth fixture")
    else:
        reason = "local-dev safety" if not safe_submit else "synthetic values or enabled submit control missing"
        gaps.add(f"{driver.ctx_id}: invalid submit/preservation unavailable ({reason})")
    if purpose == "sign-in":
        text = desc
        test = next((name for name, regex in (("puzzle", r"puzzle|captcha"), ("transcription", r"transcrib"),
             ("object-recognition", r"select.*images|recognize.*object"),
             ("personal-content", r"personal.*question"), ("memory", r"security.question|mother.s.maiden"))
             if re.search(regex, text)), "none")
        entry["auth"] = {"cognitive_test": test, "alternative": bool(re.search(r"(passkey|magic link|other method|sign in with)", text))}
    if (session.plan or {}).get("flows") and not session.flows:
        gaps.add("flow field repetitions unavailable: flow runs have not been recorded")
    for flow in session.flows:
        if flow["context"] != driver.ctx_id:
            continue
        own = {f["box"]: f for f in entry["fields"]}
        previous = {}
        belongs = False
        for step in flow["steps"]:
            for action in step.get("actions", []):
                box, value_id = action.get("target"), action.get("value_id")
                if not value_id or action["kind"] not in ("type", "paste", "select"):
                    continue
                value_id = value_id.split(":")[0]
                if box in own:
                    belongs = True
                    own[box]["value_id"] = value_id
                    if value_id in previous and previous[value_id] != box:
                        own[box]["repeats"] = previous[value_id]
                        own[box]["same_as_offered"] = bool(re.search(r"same as|copy from|use previous", desc))
                previous.setdefault(value_id, box)
        if belongs:
            entry["flow"] = flow["id"]
            break
    session.add_probe("forms", entry)
    outer_gaps.update(f"{driver.ctx_id}/{form_id}: {reason}" for reason in gaps)


def run(session, open_driver):
    contexts = list(session.matrix)
    found = False
    gaps = set()
    for ctx in contexts:
        driver = open_driver(ctx)
        try:
            for box in _forms(driver):
                found = True
                driver.reload()
                _one(driver, box, session, gaps)
        finally:
            driver.close()
    session.cover("forms", "partial" if gaps else "ran" if found else "not-applicable",
                  contexts=contexts, reason="; ".join(sorted(gaps)) if gaps else None)
