"""Observe playback, sound and keyboard/pointer access to media controls."""
from __future__ import annotations
import re

from lapis_design.behavior_check.probes._decision import (
    MEDIA_CONTROL, MEDIA_HALT, advance, dialogs, names, reopen_with, response)
from lapis_design.behavior_check.probes.permissions import INIT as PERMISSIONS_INIT
from lapis_design.render.ids import DOM_PATH_JS, box_id


def _audio_nodes(driver):
    missing = driver.page.evaluate("() => {" + DOM_PATH_JS + """
      return [...document.querySelectorAll('audio,video')].map((el,index)=>({el,index}))
        .filter(({el})=>!el.hasAttribute('data-lapis-box') && el.getBoundingClientRect().width)
        .map(({el,index})=>{const r=el.getBoundingClientRect();return {
          index,steps:path(el),name:el.getAttribute('aria-label'),
          rect:{x:r.x+scrollX,y:r.y+scrollY,w:r.width,h:r.height}}});
    }""")
    for item in missing:
        identifier = box_id(item["steps"])
        driver.page.evaluate("""([index,id]) =>
          document.querySelectorAll('audio,video')[index].setAttribute('data-lapis-box',id)""",
                             [item["index"], identifier])
        driver.session.node(identifier, role="media", name=driver.clean(item["name"] or ""),
                            rect=item["rect"], context=driver.ctx_id, appears="load")


NAMES = ("media",)

INIT = """(() => {
 const records=[];window.__lapisMedia=records;
 function track(el){
   if(el.__lapisTracked)return;el.__lapisTracked=true;
   const row={element:el,autoplay:false,user_gesture:false,playing:false,audible_ms:0,last:Date.now()};
   records.push(row);
   function update(){const now=Date.now();if(row.playing&&!el.muted&&el.volume>0)
     row.audible_ms+=Math.max(0,now-row.last);row.last=now}
   row.update=update;
   el.addEventListener('playing',()=>{update();row.playing=true;
     if(!row.user_gesture)row.autoplay=true});
   for(const name of ['pause','ended','volumechange'])el.addEventListener(name,()=>{
     update();if(name!=='volumechange')row.playing=false;
   });
 }
 const play=HTMLMediaElement.prototype.play;
 HTMLMediaElement.prototype.play=function(...args){track(this);
   if(navigator.userActivation?.isActive) {
     const row=records.find(r=>r.element===this);row.user_gesture=true;
   }
   return play.apply(this,args)
 };
 new MutationObserver(()=>document.querySelectorAll('video,audio').forEach(track))
   .observe(document,{subtree:true,childList:true});
 document.addEventListener('DOMContentLoaded',()=>document.querySelectorAll('video,audio').forEach(track));
 try {
   const proto=window.AudioNode?.prototype,connect=proto?.connect;
   if(connect)proto.connect=function(target,...args){
     if(target instanceof AudioDestinationNode){
       const ctx=this.context;
       if(!ctx.__lapisOutput){ctx.__lapisOutput={connected:false,starts:0,active:0,gesture:false,audible_ms:0,last:Date.now()};
         (window.__lapisAudioContexts||= []).push(ctx)}
       ctx.__lapisOutput.connected=true;
     }
     return connect.call(this,target,...args)
   };
   const source=window.AudioScheduledSourceNode?.prototype,start=source?.start;
   if(start)source.start=function(...args){
     const state=this.context.__lapisOutput;
     if(state){state.starts++;state.active++;state.gesture=!!navigator.userActivation?.isActive;
       this.addEventListener('ended',()=>{if(!this.__lapisEnded){this.__lapisEnded=true;
         const now=Date.now();if(this.context.state==='running')state.audible_ms+=Math.max(0,now-state.last);
         state.last=now;state.active=Math.max(0,state.active-1)}})}
     return start.apply(this,args)
   };
 }catch(_){}
})()"""

READ = """() => ({media:(window.__lapisMedia||[]).filter(row=>row.element.isConnected).map(row=>{
 row.update();const el=row.element;
 return {id:el.getAttribute('data-lapis-box'),autoplay:row.autoplay,gesture:row.user_gesture,
   audible:row.audible_ms>0,audible_s:Math.min(10,row.audible_ms/1000),playing:row.playing,
   controls:el.controls,media_id:el.id,paused:el.paused,
   parent:el.parentElement?.getAttribute('data-lapis-box')};
 }),audio:(window.__lapisAudioContexts||[]).map(ctx=>{const output=ctx.__lapisOutput,now=Date.now();
   if(ctx.state==='running'&&output.active)output.audible_ms+=Math.max(0,now-output.last);
   output.last=now;
   return {running:ctx.state==='running',connected:output.connected,starts:output.starts,
     audible_s:Math.min(10,output.audible_ms/1000),gesture:output.gesture};
 })})"""


def _controls(driver, item, named):
    # Native controls are exposed on the media element; keyboard reachability needs a tab stop.
    if item["controls"] and driver.page.locator(f'[data-lapis-box="{item["id"]}"]').evaluate(
            "el => el.tabIndex >= 0"):
        return True
    # Otherwise a control beside the media or naming it in `aria-controls`, read by accessible name.
    candidates = driver.page.evaluate("""(id) => {
      const el=document.querySelector('[data-lapis-box="'+id+'"]');
      if(!el)return [];
      return [...document.querySelectorAll('button,[role="button"],input[type="range"]')].filter(c=>{
        const r=c.getBoundingClientRect(),s=getComputedStyle(c);
        return r.width>0&&r.height>0&&s.visibility!=='hidden'&&!c.disabled&&c.tabIndex>=0&&
         (c.getAttribute('aria-controls')===el.id||(el.parentElement&&
           !el.parentElement.matches('body,main,[role=main],article,section')&&el.parentElement.contains(c)))
      }).map(c=>c.getAttribute('data-lapis-box')).filter(Boolean)
    }""", item["id"])
    return any(re.search(MEDIA_CONTROL, named.get(control, ""), re.I) for control in candidates)


def run(session, open_driver):
    observed = 0
    for ctx_id in session.matrix:
        driver = open_driver(ctx_id)
        try:
            # Deny device permissions as the permissions probe does, so a page that asks for the
            # camera or microphone never holds a real device while playback is observed.
            reopen_with(driver, PERMISSIONS_INIT, INIT)
            driver.boxes()
            advance(driver, 10000)
            driver.boxes()
            _audio_nodes(driver)
            values = driver.page.evaluate(READ)
            named = names(driver) if values["media"] else {}
            for item in values["media"]:
                if item["id"] not in session.nodes:
                    continue
                record = {"box": item["id"], "context": ctx_id, "autoplay": item["autoplay"],
                          "audible": item["audible"], "audible_s": round(item["audible_s"], 2),
                          "controls": _controls(driver, item, named), "user_gesture": item["gesture"]}
                session.add_probe("media", record)
                observed += 1
            owner_id = None
            if session.meta["backend"] == "stub":
                for dialog in dialogs(driver):
                    _, decline = response(dialog["controls"])
                    if decline:
                        driver.act({"kind": "click", "target": decline["id"]})
                for control in driver.interactive():
                    if re.search(r"play (?:audio|sound|tone)|start (?:audio|sound|tone)", control["name"] or "", re.I):
                        driver.act({"kind": "click", "target": control["id"]})
                        owner_id = control["id"]
                        advance(driver, 1000)
                        values["audio"] = driver.page.evaluate(READ)["audio"]
                        break
            for item in values["audio"]:
                if not item["starts"] or not item["connected"]:
                    continue
                # An AudioContext has no DOM element: associate output with its initiating
                # media/control or the visible page root, rather than inventing an id.
                boxes = driver.boxes()
                owner = next((box for box in boxes if box["id"] == owner_id), None)
                if owner is None:
                    owner = next((box for box in boxes if box["role"] in ("media", "button")), None)
                if owner is None:
                    owner = next((box for box in boxes if box["tag"] == "body"), None)
                if owner:
                    session.add_probe("media", {"box": owner["id"], "context": ctx_id,
                        "autoplay": not item["gesture"] and item["running"],
                        "audible": item["audible_s"] > 0,
                        "audible_s": round(item["audible_s"], 2), "user_gesture": item["gesture"],
                        "controls": bool(owner_id and any(
                            re.search(MEDIA_HALT, box["name"] or "", re.I)
                            and box["interactive"] and box["focusable"] and box["enabled"]
                            for box in boxes))})
                    observed += 1
        finally:
            driver.close()
    session.cover("media", "ran" if observed else "not-applicable", contexts=list(session.matrix))
