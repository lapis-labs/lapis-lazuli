"""Record browser permission requests at their call site without granting access."""
from __future__ import annotations

import re

from lapis_design.behavior_check.probes._decision import REFUSE, advance, dialogs, reopen_with

NAMES = ("permissions",)

INIT = """(() => {
 const calls=[];window.__lapisPermissionCalls=calls;
 const denied=new Set();
 function record(api){
   const pre=[...document.querySelectorAll('dialog,[role="dialog"],[role="alertdialog"],[aria-modal]')]
     .find(el=>{const r=el.getBoundingClientRect();return r.width&&r.height&&
       getComputedStyle(el).visibility!=='hidden'&&
       /permission|allow|enable|notification|location|camera|microphone|clipboard|storage|권한|허용|활성화|알림|위치|카메라|마이크|클립보드|저장소/i
         .test((el.innerText||'')+' '+(el.getAttribute('aria-label')||''))});
   calls.push({api,user_gesture:!!navigator.userActivation?.isActive,after_denial:denied.has(api),
     preprompt:pre?.getAttribute('data-lapis-box')||null,t_ms:performance.now()});
   denied.add(api);
 }
 try {Notification.requestPermission=function(callback){record('notifications');
   const result=Promise.resolve('denied');if(callback)result.then(callback);return result};}catch(_){}
 try {const geo=navigator.geolocation;
   for(const method of ['getCurrentPosition','watchPosition']){
     const original=geo[method];if(!original)continue;
     Object.defineProperty(geo,method,{configurable:true,value:function(success,error){
       record('geolocation');queueMicrotask(()=>error?.({code:1,message:'Permission denied',PERMISSION_DENIED:1}));
       return method==='watchPosition'?0:undefined;
     }});
   }}catch(_){}
 try {const devices=navigator.mediaDevices;
   if(devices?.getUserMedia){Object.defineProperty(devices,'getUserMedia',{configurable:true,value:function(constraints){
     const video=!!constraints?.video,audio=!!constraints?.audio;
     if(video)record('camera');if(audio)record('microphone');
     if(!video&&!audio)record('other');
     return Promise.reject(new DOMException('Permission denied','NotAllowedError'));
   }});}}catch(_){}
 try {const clipboard=navigator.clipboard;
   for(const method of ['read','readText']) if(clipboard?.[method]){
     Object.defineProperty(clipboard,method,{configurable:true,value:function(){
       record('clipboard-read');return Promise.reject(new DOMException('Permission denied','NotAllowedError'));
     }});
   }}catch(_){}
 try {const store=navigator.storage;
   if(store?.persist)Object.defineProperty(store,'persist',{configurable:true,value:async function(){
     record('persistent-storage');return false;
   }});
 }catch(_){}
})()"""


def run(session, open_driver):
    count = 0
    issues = []
    for ctx_id in session.matrix:
        driver = open_driver(ctx_id)
        try:
            reopen_with(driver, INIT)
            def drain():
                nonlocal count
                driver.boxes()
                rows = driver.page.evaluate("window.__lapisPermissionCalls.splice(0)")
                for row in rows:
                    entry = {"context": ctx_id, "api": row["api"], "user_gesture": row["user_gesture"],
                             "after_denial": row["after_denial"], "t_ms": round(row["t_ms"], 2)}
                    if row["preprompt"] in session.nodes:
                        entry["preprompt"] = row["preprompt"]
                    session.add_probe("permissions", entry)
                    count += 1
            drain()
            for control in driver.interactive():
                if not re.search(r"notif|permission|location|camera|microphone|clipboard|storage|allow|"
                                 r"알림|권한|위치|카메라|마이크|클립보드|저장소|허용", control["name"] or "", re.I):
                    continue
                if not driver.locate(control["id"]).is_visible():
                    continue
                try:
                    driver.act({"kind": "click", "target": control["id"]})
                    drain()
                    for prompt in dialogs(driver):
                        button = next((button for button in prompt["controls"] if re.search(
                            r"allow|continue|enable|허용|계속|활성화|켜기", button["text"], re.I)
                            and not re.search(REFUSE, button["text"], re.I)), None)
                        if button and session.meta["backend"] == "stub":
                            driver.act({"kind": "click", "target": button["id"]})
                            drain()
                except Exception:
                    issues.append(f"permission control {control['id']} could not be activated")
            advance(driver, 5500)
            drain()
        finally:
            driver.close()
    session.cover("permissions", "partial" if issues else "ran" if count else "not-applicable",
                  contexts=list(session.matrix), reason="; ".join(dict.fromkeys(issues)) if issues else None)
