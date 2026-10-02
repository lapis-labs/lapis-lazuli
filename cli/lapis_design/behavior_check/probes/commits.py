"""Commit retries, duplicate activations, failure claims, and destructive recovery."""
from __future__ import annotations

import re
from time import sleep

from lapis_design.behavior import EXIT_KINDS
from lapis_design.behavior_check import settle
from lapis_design.behavior_check.probes._decision import (
    BACK_OUT, CLOSE, CONFIRM, DECLINE, EXIT_ACTION, NEGATES_EXIT, NOT_A_RESULT, RESUBMIT, WAITING, claim_table, names)
from lapis_design.behavior_check.probes._decision import new_text as _new_text
from lapis_design.behavior_check.probes.controls import element, fresh

NAMES = ("commits",)
_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_MODES = ("none", "fail-5xx", "fail-network", "hang", "forbidden")

_UNDO = re.compile(r"\bundo\b|실행 ?취소|되돌리", re.I)

def _requests(effect):
    return [req for req in effect.get("requests", ()) if req["method"] in _METHODS and not req.get("blocked")]


def _resolve(driver, box_id):
    """The live id of a recorded box: the id itself when an element carries it after a fresh
    snapshot, else the one visible box with the recorded accessible name and role. None if absent."""
    boxes = driver.boxes()
    if any(box["id"] == box_id for box in boxes) and element(driver, box_id).is_visible():
        driver._box_alias.pop(box_id, None)
        return box_id
    node = driver.session.nodes.get(box_id, {})
    matches = [box["id"] for box in boxes if node.get("name") and box["name"] == node["name"]
               and box["role"] == node.get("role") and box["enabled"]]
    matches = [bid for bid in matches if driver.page.locator(f'[data-lapis-box="{bid}"]').first.is_visible()]
    if len(matches) != 1:
        return None
    driver._box_alias[box_id] = matches[0]
    return matches[0]


def _live(driver, box_id):
    return getattr(driver, "_box_alias", {}).get(box_id, box_id)


def _reach(driver, target):
    """Restore a fresh page and replay the actions that exposed a control: its control path, or the
    flow steps before its commit action (after the pair's run for an exit flow). False when the
    control cannot be reached."""
    try:
        flow_path = getattr(driver.session, "_flow_commit_paths", {}).get((driver.ctx_id, target))
        path = getattr(driver.session, "_control_paths", {}).get((driver.ctx_id, target))
        if path is not None and not (flow_path and len(flow_path) > 1):
            fresh(driver)
            for box_id in path:
                live = _resolve(driver, box_id)
                if live is None:
                    return False
                driver.act({"kind": "tap" if driver.ctx["pointer"] == "coarse" else "click", "target": live})
            if _resolve(driver, target) is None:
                return False
            return path[-1] if path else None
        # Flow commits: the flow's steps before the commit action, after the pair's run for an exit flow.
        if flow_path is None:
            return False
        for position, (start, actions) in enumerate(flow_path):
            if ":id" in start:
                return False
            if position == 0:
                fresh(driver, start)
            else:
                # The next flow starts where its pair started, in the state the pair left behind.
                driver.act({"kind": "navigate", "path": start})
            for action in actions:
                action = dict(action)
                action.pop("t_ms", None)
                if "target" in action:
                    live = _resolve(driver, action["target"])
                    if live is None:
                        return False
                    action["target"] = live
                driver.act(action)
        return None if _resolve(driver, target) is not None else False
    except Exception:
        # Playwright timeouts and detached elements: the control is unreachable on this replay.
        return False


def _region(driver, target):
    """The texts of the control's region and of any toast, status, or dialog, one per element."""
    return element(driver, target).evaluate("""el => {
      const region=el.closest('form,section,[role=region],dialog')||el.parentElement;
      const visible=e=>e && e.getClientRects().length && getComputedStyle(e).visibility!=='hidden';
      return [region,...document.querySelectorAll('[role=status],[role=alert],.toast,.snackbar,dialog')]
        .filter(visible).map(e=>e.innerText||'');
    }""")


def _claimed(text, leaving=False):
    """What `text` claims about a commit's result. `leaving`: the commit leaves something (see `_exits`), so
    the completed forms of leaving (unsubscribed, cancelled, 해지됐어요) are a success."""
    text = NOT_A_RESULT.sub(" ", text.lower())
    return next((claim for claim, words in claim_table(leaving) if re.search(words, text)), "none")


# A control that cancels or deletes (the probe's kind), is named for what it leaves ("Unsubscribe", "구독 해지"),
# starts with Cancel, or ends with 취소 ("Cancel reservation", "예약 취소") leaves something, whatever noun the kind
# went by. A booking button that mentions "free cancellation" does not, and neither does a name that negates or
# cancels the exit ("Don't cancel", "취소 안 함", "해지 취소").
_LEAVES = re.compile(rf"{EXIT_ACTION}|^\W*cancel\b|취소(?:하기)?\W*$", re.I)
# The kinds of a control named for the exit, tried before any other kind so that "Unsubscribe", "구독 해지",
# "Delete subscription", and "주문 취소" are not read as the subscription, order, or reservation they end. "Stop" and
# a "해지" inside a longer name are left out: "Non-stop flights: book" books.
_EXIT_FIRST = ((r"\b(?:unsubscribe|withdraw)\b|^\W*cancel\b|(?:해지|탈퇴|철회|수신 ?거부|취소)(?:하기)?\W*$", "cancel"),
               (r"^\W*(?:delete|remove)\b|(?:삭제|제거)(?:하기)?\W*$", "delete"))


def _exits(name, kind):
    if re.search(NEGATES_EXIT, name, re.I):
        return False
    return kind in ("cancel", "delete") or bool(_LEAVES.search(name))


def _kind(name, request):
    label = name.lower()
    if _UNDO.search(label):
        return "save" if request.get("method") in _METHODS else "other"
    negated = bool(re.search(NEGATES_EXIT, label))             # "Don't cancel" is no cancel
    if not negated:
        for pattern, result in _EXIT_FIRST:
            if re.search(pattern, label):
                return result
    # Stems, so "Confirm reservation" and /api/subscriptions classify like "Reserve" and "subscribe".
    for pattern, result in ((r"purchas|\bbuy\b|\bpay\b|\bcheckout|\border now|구매|구입|결제|지불|주문", "purchase"),
                            (r"subscri|구독", "subscribe"), (r"reserv|\bbook|예약", "reserve"),
                            (r"\bcancel|취소|해지|철회", "cancel"), (r"\bdelet|\bremov|삭제|제거|지우", "delete"),
                            (r"\bpublish|게시|발행", "publish"), (r"\bsend\b|\bsent\b|전송|발송|보내", "send"),
                            (r"\bsave|저장", "save"), (r"\btoggle|전환", "toggle"), (r"\bsubmit|제출|신청", "submit")):
        if negated and result in ("cancel", "delete"):
            continue
        if re.search(pattern, label):
            return result
    path = request.get("path", "").lower()
    if request.get("method") == "DELETE":
        return "delete"
    for stem, result in (("purchas", "purchase"), ("order", "purchase"), ("subscri", "subscribe"),
                         ("reserv", "reserve"), ("booking", "reserve"), ("cancel", "cancel"),
                         ("publish", "publish"), ("send", "send"), ("save", "save")):
        if stem in path:
            return result
    return "submit" if request.get("method") in _METHODS else "other"


def _pending(driver, target):
    """The control's state right after the first activation, sampled once without waiting: a
    locator would wait for a control the activation already replaced or navigated away, and the
    reading would depend on which of the two finished first. A control that is gone showed no
    pending state."""
    return driver.page.evaluate("""([id, words]) => {
      const el=document.querySelector('[data-lapis-box="'+id+'"]');
      if(!el || !el.isConnected) return {pending:false, named:null};
      const waiting=new RegExp(words,'i');
      return {
      pending:el.disabled || el.getAttribute('aria-busy')==='true' ||
        waiting.test(el.innerText||'') ||
        waiting.test((el.closest('form,section,[role=region],dialog')||el.parentElement).innerText||''),
      named:!!(el.getAttribute('aria-label')||
        el.getAttribute('aria-labelledby')?.split(/\\s+/).map(id=>document.getElementById(id)?.textContent||'').join(' ')||
        el.labels?.[0]?.textContent||el.innerText||el.getAttribute('title')||'').trim()
    }}""", [_live(driver, target), WAITING])


def _press_twice(driver, target, keyboard):
    start = len(driver.network.entries)
    before = driver.session.engine.effects_total if driver.session.engine else 0
    locator = element(driver, target)
    if keyboard:
        locator.focus()
        driver.page.keyboard.press("Enter")
    else:
        rect = locator.bounding_box()
        if rect is None:
            raise ValueError("commit control is not visible")
        x, y = rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2
        if driver.ctx["pointer"] == "coarse":
            driver.page.touchscreen.tap(x, y)
        else:
            driver.page.mouse.click(x, y)
    state = _pending(driver, target)
    sleep(.08)
    driver.advance_clock(80)
    if keyboard:
        driver.page.keyboard.press("Enter")
    elif driver.ctx["pointer"] == "coarse":
        driver.page.touchscreen.tap(x, y)
    else:
        driver.page.mouse.click(x, y)
    settle.quiet(driver, driver.page.evaluate("window.__lapisObserve.mutations"))
    requests = [req for req in driver.network.entries[start:] if req["method"] in _METHODS and not req.get("blocked")]
    result = {"requests": len(requests), "effects": driver.session.engine.effects_total - before,
              "pending_shown": state["pending"]}
    if state["pending"]:
        result["name_kept"] = state["named"]
    return result


def _inputs(driver, target):
    return element(driver, target).evaluate("""el => [...(el.closest('form,section,dialog')||el.parentElement)
      .querySelectorAll('input:not([type=hidden]),textarea,select')].map(e=>[e,e.value])
      .filter(([e,v])=>v).map(([e,v])=>({name:e.getAttribute('name')||e.id,value:v}))""")


def _seed_inputs(driver, target):
    if driver.session.values_engine is None:
        return
    fields = element(driver, target).evaluate("""el => [...(el.closest('form,section,dialog')||el.parentElement)
      .querySelectorAll('input:not([type=hidden]),textarea')].filter(e=>!e.disabled && e.getClientRects().length)
      .map(e=>({id:e.getAttribute('data-lapis-box'),kind:e.getAttribute('type')||(
        /name/i.test(e.getAttribute('name')||e.getAttribute('aria-label')||'')?'name':'text')}))""")
    for field in fields:
        if field["id"] and not element(driver, field["id"]).input_value():
            try:
                value_id = driver.session.values_engine.values_for(field["kind"], "valid")
            except KeyError:
                continue
            # Setup, not an observed action: the synthetic value is entered without a settle window
            # and is never recorded.
            element(driver, field["id"]).fill(driver.session.values_engine.value(value_id))


def _outcome(driver, target, request, mode, leaving=False):
    """One commit with one injected mode. `leaving`: the commit belongs to an exit flow."""
    opener = _reach(driver, target)
    if opener is False:
        return None, request
    _seed_inputs(driver, target)
    if mode != "none":
        driver.session.engine.inject(mode, method=request["method"], path=request["path"])
    initial = _inputs(driver, target)
    text_before = _region(driver, target)
    start = len(driver.network.entries)
    before_effects = driver.session.engine.effects_total if driver.session.engine else None
    effect = driver.act({"kind": "tap" if driver.ctx["pointer"] == "coarse" else "click",
                         "target": _live(driver, target)})
    requests = [r for r in driver.network.entries[start:] if r["method"] in _METHODS and not r.get("blocked")]
    request = request or next((r for r in requests if r.get("effects", 0) > 0), requests[-1] if requests else {})
    actual = ("applied" if driver.session.engine.effects_total > before_effects else "not-applied") if before_effects is not None else "unknown"
    text_after = (_region(driver, target) if element(driver, target).is_visible() else
                  driver.page.evaluate("[...document.querySelectorAll('[role=status],[role=alert],dialog,.toast')]"
                                       ".filter(e=>e.getClientRects().length).map(e=>e.innerText||'')"))
    name = driver.session.nodes.get(target, {}).get("name") or ""
    leaving = leaving or _exits(name, _kind(name, request))
    claim = _claimed(_new_text(text_before, text_after), leaving)
    item = {"injected": mode, "claimed": claim, "actual": actual,
            "auto_resent": len([r for r in requests if r["method"] == request.get("method") and
                r["path"] == request.get("path") and not r.get("idempotency_key")]) > 1,
            "announced": any(_claimed(entry.get("text", ""), leaving) not in ("none", "pending")
                             for entry in effect.get("announcements", ()))}
    if initial:
        surviving = driver.page.evaluate("""() => [...document.querySelectorAll('input,textarea,select')]
          .map(e=>({name:e.getAttribute('name')||e.id,value:e.value}))""")
        item["input_kept"] = all(field in surviving for field in initial)
    retry = driver.page.get_by_role("button", name=re.compile(RESUBMIT, re.I))
    offered = retry.count() > 0 and retry.first.is_visible()
    item["retry_offered"] = offered
    if offered:
        before = driver.session.engine.effects_total if driver.session.engine else 0
        retry.first.click()
        settle.quiet(driver, driver.page.evaluate("window.__lapisObserve.mutations"))
        item["retry_effects"] = driver.session.engine.effects_total - before if driver.session.engine else 0
    return item, request


def _confirm_and_undo(driver, target, opener):
    dialog = element(driver, target).evaluate("el => el.closest('dialog,[role=dialog],[role=alertdialog]')?.innerText||''")
    result = {"confirm": {"shown": bool(dialog)}, "undo": {"offered": False}}
    if dialog:
        opener_name = driver.session.nodes[opener].get("name", "") if opener else ""
        object_name = re.sub(r"^(?:delete|remove|cancel|erase)\s+|\s*(?:삭제|제거|취소|해지|지우기)(?:하기)?$", "",
                             opener_name, flags=re.I).strip()
        result["confirm"]["names_object"] = bool(object_name and object_name.lower() in dialog.lower())
        named = names(driver)
        focused = driver.page.evaluate("""() => {const el=document.activeElement;
          return el && !el.matches('dialog,[role=dialog],[role=alertdialog]') &&
            el.closest('dialog,[role=dialog],[role=alertdialog]') ?
            (el.closest('[data-lapis-box]')?.getAttribute('data-lapis-box')||'') : ''}""")
        focus = (named.get(focused) or "").lower()
        result["confirm"]["initial_focus"] = ("destructive" if re.search(
            rf"\b(?:remove|erase|yes)\b|삭제|제거|지우|^예$|^네$|{CONFIRM}|{EXIT_ACTION}", focus) else
            "safe" if re.search(rf"\b(?:keep|back|no)\b|유지|뒤로|{BACK_OUT}|{CLOSE}|{DECLINE}", focus) else "none")
    driver.act({"kind": "tap" if driver.ctx["pointer"] == "coarse" else "click", "target": _live(driver, target)})
    undo = driver.page.get_by_role("button", name=_UNDO)
    if not undo.count() or not undo.first.is_visible():
        return result
    result["undo"]["offered"] = True
    undo_id = undo.first.get_attribute("data-lapis-box")
    if not undo_id:
        driver.boxes()
        undo_id = undo.first.get_attribute("data-lapis-box")
    driver.page.evaluate("document.activeElement.blur()")
    reachable = False
    for _ in range(len(driver.interactive()) + 2):
        driver.page.keyboard.press("Tab")
        if driver.page.evaluate("document.activeElement?.getAttribute('data-lapis-box')") == undo_id:
            reachable = True
            break
    result["undo"]["keyboard_reachable"] = reachable
    if not reachable:
        undo.first.focus()
    if driver.ctx["pointer"] == "fine":
        undo.first.hover()
    # Toasts time out on the page clock; hold focus and hover across a typical dismissal delay.
    driver.advance_clock(10_000)
    settle.quiet(driver, driver.page.evaluate("window.__lapisObserve.mutations"))
    result["undo"]["dismissed_while_focused"] = not undo.first.is_visible()
    if result["undo"]["dismissed_while_focused"]:
        return result
    before = driver.session.engine.effects_total
    driver.act({"kind": "tap" if driver.ctx["pointer"] == "coarse" else "click", "target": undo_id})
    restored = driver.session.engine.effects_total > before and element(driver, target).is_visible() if opener is None else (
        driver.session.engine.effects_total > before and element(driver, opener).is_visible())
    result["undo"]["restores"] = restored
    driver.reload(reset_storage=False)
    result["undo"]["survives_reload"] = restored and element(driver, opener or target).is_visible()
    return result


def run(session, open_driver):
    coverage = []
    session._flow_commit_paths = {}
    for ctx_id in session.matrix:
        controls = [item for item in session.probes.get("controls", ()) if item["context"] == ctx_id]
        flow_targets = {}
        exit_targets = set()               # commit controls of exit flows
        unseeded = {}
        plan_flows = {flow["id"]: flow for flow in (session.plan or {}).get("flows", [])}
        runs = {run["id"]: run for run in session.flows if run["context"] == ctx_id}

        def all_actions(run):
            return [dict(action) for step in sorted(run["steps"], key=lambda s: s["index"])
                    for action in step.get("actions", ())]

        for flow in session.flows:
            if flow["context"] != ctx_id or "commit_step" not in flow:
                continue
            index = flow["commit_step"]
            steps = sorted(flow["steps"], key=lambda step: step["index"])
            step = next((step for step in steps if step["index"] == index), None)
            activations = [position for position, action in enumerate(step.get("actions", ())) if action.get("target") and
                           not action.get("choice") and action["kind"] in ("click", "tap", "key", "check", "uncheck")] if step else []
            if not activations:
                continue
            target = step["actions"][activations[-1]]["target"]
            flow_targets[target] = flow["id"]
            if flow.get("kind") in EXIT_KINDS:
                exit_targets.add(target)
            prior = [dict(action) for earlier in steps if earlier["index"] < index
                     for action in earlier.get("actions", ())]
            prior += [dict(action) for action in step["actions"][:activations[-1]]]
            segments = [(steps[0]["path"], prior)]
            pair_id = plan_flows.get(flow["id"], {}).get("pair")
            if pair_id:
                # DERIVED: an exit flow starts where its pair starts, so its state is the pair's result.
                pair = runs.get(pair_id)
                if pair is None or pair["status"] != "completed" or not pair["steps"]:
                    unseeded[target] = (f"flow {flow['id']}: pair run {pair_id} "
                                        f"{'missing' if pair is None else pair['status']}; exit commit state cannot be seeded")
                    continue
                first = min(pair["steps"], key=lambda s: s["index"])
                segments.insert(0, (first["path"], all_actions(pair)))
            session._flow_commit_paths[(ctx_id, target)] = segments
        if session.meta["backend"] == "local-dev" and session.meta.get("outbound") != "none":
            coverage.append((ctx_id, "skipped", "local-dev outbound is not none"))
            continue
        candidates = [item for item in controls if item["box"] in flow_targets or
                      (ctx_id, item["box"]) in getattr(session, "_control_commit_requests", ()) or
                      any(req.get("effects", 0) > 0 for req in _requests(item["effect"]))]
        observed_boxes = {item["box"] for item in candidates}
        candidates += [{"box": target, "context": ctx_id, "effect": {}} for target in flow_targets
                       if target not in observed_boxes and target in session.nodes]
        if not candidates:
            unexplained = any(_requests(item["effect"]) for item in controls)
            reason = ("flow commit targets were not described as nodes" if flow_targets else
                      "state-changing requests observed without attributable backend effects" if unexplained else
                      "controls not observed; commit controls cannot be discovered" if not controls else None)
            coverage.append((ctx_id, "partial" if reason else "not-applicable", reason))
            continue
        driver = open_driver(ctx_id)
        skipped = []
        if session.engine is None:
            skipped.append("local-dev has no stub effect counter or failure injection; double activation and failure modes not measured")
        try:
            for control in candidates:
                target = control["box"]
                writes = _requests(control["effect"])
                request = next((r for r in writes if r.get("effects", 0) > 0), writes[-1] if writes else {})
                name = session.nodes[target].get("name") or ""
                kind = _kind(name, request)
                destructive = (kind in ("delete", "cancel") or control.get("promise") == "destructive") and not _UNDO.search(name)
                if destructive and session.meta["backend"] != "stub":
                    skipped.append(f"{name or target}: destructive commits require stub")
                    continue
                if target in unseeded:
                    skipped.append(unseeded[target])
                    continue
                if _reach(driver, target) is False:
                    skipped.append(f"{name or target}: control could not be reached from a fresh load")
                    continue
                probe = {"box": target, "context": ctx_id, "kind": kind, "destructive": destructive}
                if target in flow_targets:
                    probe["flow"] = flow_targets[target]
                label = name or target
                if session.engine:
                    try:
                        modes = [_press_twice(driver, target, False)]
                        # Keyboard only when the pointer reading could still get worse.
                        if modes[0]["effects"] < 2 or modes[0]["pending_shown"]:
                            if _reach(driver, target) is False:
                                skipped.append(f"{label}: keyboard double activation control unavailable")
                            else:
                                modes.append(_press_twice(driver, target, True))
                        probe["double_activation"] = max(modes, key=lambda row: (row["effects"], row["requests"],
                            not row["pending_shown"], not row.get("name_kept", False)))
                    except Exception as exc:
                        skipped.append(f"{label}: double activation failed ({type(exc).__name__})")
                outcomes = []
                for mode in _MODES if session.engine else ("none",):
                    if mode != "none" and not request:
                        skipped.append(f"{label}: no state-changing request observed to target {mode}")
                        continue
                    try:
                        observed, request = _outcome(driver, target, request, mode, target in exit_targets)
                    except Exception as exc:
                        if session.engine is not None:
                            session.engine.clear_injections()
                        skipped.append(f"{label}: {mode} outcome failed ({type(exc).__name__})")
                        continue
                    if observed is None:
                        skipped.append(f"{label}: {mode} could not reach control")
                        continue
                    outcomes.append(observed)
                    if mode == "none" and "kind" in probe and not writes:
                        probe["kind"] = _kind(name, request)
                if outcomes:
                    probe["outcomes"] = outcomes
                if destructive and session.engine:
                    opener = _reach(driver, target)
                    if opener is False:
                        skipped.append(f"{label}: confirmation/undo unavailable")
                    else:
                        try:
                            probe.update(_confirm_and_undo(driver, target, opener))
                        except Exception as exc:
                            skipped.append(f"{label}: confirmation/undo failed ({type(exc).__name__})")
                session.add_probe("commits", probe)
            coverage.append((ctx_id, "partial" if skipped else "ran", "; ".join(skipped) if skipped else None))
        finally:
            driver.close()
    statuses = {status for _, status, _ in coverage}
    status = next(iter(statuses)) if len(statuses) == 1 else "partial"
    reasons = [f"{ctx_id}: {reason or result}" for ctx_id, result, reason in coverage if result != "ran"]
    session.cover("commits", status, contexts=list(session.matrix),
                  reason="; ".join(reasons) if status in ("partial", "skipped") else None)
