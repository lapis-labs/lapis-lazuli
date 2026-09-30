Notification.requestPermission().catch(() => {});
navigator.geolocation.getCurrentPosition(()=>{},()=>{});
navigator.clipboard.readText().catch(()=>{});
navigator.storage.persist().catch(()=>{});
const $ = id => document.getElementById(id);
$('cookieManage').onclick = () => { $('settings').style.display = 'block'; };
$('cookieReject').onclick = () => { $('cookie').style.display = 'none';sessionStorage.setItem('cookieDecision','reject'); };
$('cookieAccept').onclick = () => { $('cookie').style.display = 'none';sessionStorage.setItem('cookieDecision','accept'); };
if(sessionStorage.getItem('cookieDecision')) $('cookie').style.display='none';
$('confirmOpen').onclick = () => { $('confirm').showModal();$('confirmCancel').focus(); };
$('confirmCancel').onclick = () => $('confirm').close();
$('confirmYes').onclick = () => $('confirm').close();
$('devicePermissions').onclick = () => {
 navigator.geolocation.getCurrentPosition(()=>{},()=>{});
 navigator.mediaDevices.getUserMedia({audio:true,video:true}).catch(()=>{});
 navigator.clipboard.readText().catch(()=>{});
 navigator.storage.persist().catch(()=>{});
};
$('notifyOpen').onclick = () => { $('permissionPreprompt').style.display='block';$('permissionContinue').focus(); };
$('permissionContinue').onclick = () => { Notification.requestPermission().catch(() => {});$('permissionPreprompt').style.display='none'; };
$('permissionClose').onclick = () => { $('permissionPreprompt').style.display='none'; };
setTimeout(() => { if (!sessionStorage.getItem('newsletterAccepted')) { $('newsletter').classList.add('open'); $('newsletterDecline').focus(); } }, 5000);
$('newsletterDecline').onclick = () => { $('newsletter').classList.remove('open');sessionStorage.setItem('newsletterDeclined','yes'); };
$('newsletterAccept').onclick = () => { $('newsletter').classList.remove('open');sessionStorage.setItem('newsletterAccepted','yes'); };
let left=false;
document.addEventListener('mouseout', event => { if (!event.relatedTarget && event.clientY <= 0 && !left) {
 left=true; $('offer').classList.add('open');$('offerDecline').focus();
}});
$('offerDecline').onclick = () => $('offer').classList.remove('open');
$('offerAccept').onclick = () => $('offer').classList.remove('open');
// The context is created at load (suspended until a gesture) and started from the click.
const ctx = new AudioContext();
let tone;
$('playTone').onclick = () => {
 ctx.resume();
 tone = ctx.createOscillator();
 tone.frequency.value = 440;
 tone.connect(ctx.destination);
 tone.start();
};
$('stopTone').onclick = () => { if (tone) { tone.stop(); tone = null; } };
