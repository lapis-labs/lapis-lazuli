for (const list of document.querySelectorAll('ul')) {
  let held = null;
  list.addEventListener('dragstart', event => { held = event.target; });
  list.addEventListener('dragover', event => event.preventDefault());
  list.addEventListener('drop', event => {
    event.preventDefault();
    const target = event.target.closest('li');
    if (target && target !== held) target.after(held);
  });
  list.addEventListener('pointerdown', event => { held = event.target.closest('li'); });
  list.addEventListener('pointerup', event => {
    const target = event.target.closest('li');
    if (held && target && held !== target) target.after(held);
  });
}
document.querySelector('#move-up').onclick = () => {
  const list = document.querySelector('#good-list'); list.prepend(list.lastElementChild);
};
document.querySelector('#move-down').onclick = () => {
  const list = document.querySelector('#good-list'); list.append(list.firstElementChild);
};
document.querySelector('#slider').oninput = event => {
  document.querySelector('#value').textContent = event.target.value;
};
const swipe=document.querySelector('#swipe');
let swipeStart=0;
swipe.addEventListener('touchstart',event=>{swipeStart=event.touches[0].clientX});
swipe.addEventListener('touchend',event=>{
  if(event.changedTouches[0].clientX-swipeStart>50)swipe.querySelector('span').textContent='Swiped';
});
document.querySelector('#swipe-menu').onclick=()=>swipe.querySelector('span').textContent='Swiped';
const pinch=document.querySelector('#pinch');
pinch.addEventListener('touchmove',event=>{
  if(event.touches.length===2)pinch.querySelector('span').textContent='Magnified';
});
for (const [button,tip,withFocus] of [
  ['hover-only','only-tip',false],['focus-too','focus-tip',true]]) {
  const trigger=document.getElementById(button), content=document.getElementById(tip);
  const show=()=>{content.hidden=false}, hide=()=>{content.hidden=true};
  trigger.addEventListener('mouseenter',show);
  trigger.parentElement.addEventListener('mouseleave',()=>{hide();delete trigger.dataset.dismissed});
  if (withFocus) {
    trigger.addEventListener('focus',show);
    trigger.addEventListener('blur',hide);
    trigger.addEventListener('keydown',event=>{if(event.key==='Escape'){hide();trigger.dataset.dismissed='true'}});
    trigger.addEventListener('mouseenter',()=>{if(trigger.dataset.dismissed==='true')hide()});
  }
}
document.querySelector('#pause').onclick=()=>{
  document.querySelector('#carousel').style.animationPlayState='paused';
};
const observer=new IntersectionObserver(entries=>{
  for(const entry of entries) if(entry.isIntersecting)
    setTimeout(()=>entry.target.classList.add('readable'),250);
});
observer.observe(document.querySelector('#reveal'));
// Moving media that ignores reduced motion: a muted autoplay background video (fed from a
// script-drawn canvas stream), a decorative particle canvas, and a named live chart canvas.
const source=document.createElement('canvas');source.width=120;source.height=60;
const sourceContext=source.getContext('2d');let sourceTick=0;
setInterval(()=>{sourceTick++;sourceContext.fillStyle=sourceTick%2?'#000':'#fff';sourceContext.fillRect(0,0,120,60);},100);
const video=document.querySelector('#bg-video');video.srcObject=source.captureStream(10);video.play().catch(()=>{});
const particles=document.querySelector('#particles').getContext('2d');let particleTick=0;
(function particle(){particleTick++;particles.fillStyle=particleTick%12<6?'#f0f':'#0f0';particles.fillRect(0,0,120,60);requestAnimationFrame(particle);})();
const chart=document.querySelector('#live-chart').getContext('2d');let chartTick=0;
setInterval(()=>{chartTick++;chart.fillStyle=chartTick%2?'#036':'#fc0';chart.fillRect(0,0,120,60);},150);
