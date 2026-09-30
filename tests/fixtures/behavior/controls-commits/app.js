const status = document.querySelector('#reservation-status');
const guest = document.querySelector('#guest');
const object = document.querySelector('#object');
const toast = document.querySelector('#toast');
const dialog = document.querySelector('#confirmation');
let pending = false;

async function reserve(button, guarded, falseSuccess = false) {
  if (guarded && pending) return;
  if (guarded) { pending = true; button.setAttribute('aria-busy', 'true'); }
  status.textContent = 'Saving reservation';
  if (guarded) await new Promise(resolve => setTimeout(resolve, 150));
  try {
    const response = await fetch('/api/reservations', {
      method: 'POST', headers: guarded ? {'Idempotency-Key': 'reservation-seat-7'} : {},
      body: JSON.stringify({guest: guest.value})
    });
    status.textContent = response.ok || falseSuccess ? 'Reservation saved' : 'Reservation failed';
  } catch (_) { status.textContent = falseSuccess ? 'Reservation saved' : 'Reservation failed'; }
  finally { if (guarded) { pending = false; button.removeAttribute('aria-busy'); } }
}
document.querySelector('#reserve').addEventListener('click', e => reserve(e.currentTarget, true));
document.querySelector('#unsafe').addEventListener('click', e => reserve(e.currentTarget, false));
document.querySelector('#false-success').addEventListener('click', e => reserve(e.currentTarget, false, true));
document.querySelector('#preview').addEventListener('click', async () => {
  const response = await fetch('/api/preview', {method: 'POST'});
  status.textContent = response.ok ? 'Preview saved' : 'Preview failed';
});
document.querySelector('#misleading').addEventListener('click', e => {
  if (e.detail) { e.preventDefault(); status.textContent = 'Details opened'; }
});
async function showObject() {
  const response = await fetch('/api/records');
  const items = await response.json();
  object.hidden = !items.some(item => item.name === 'Sample record');
}
showObject();
async function erase() {
  const response = await fetch('/api/records/sample', {method: 'DELETE'});
  if (!response.ok) { toast.hidden = false; toast.textContent = 'Delete failed'; return; }
  object.hidden = true;
  toast.hidden = false;
  toast.replaceChildren(document.createTextNode('Sample record deleted '));
  const undo = document.createElement('button');
  undo.id = 'undo'; undo.textContent = 'Undo delete';
  toast.append(undo);
  undo.addEventListener('click', async () => {
    const result = await fetch('/api/records', {method: 'POST', body: JSON.stringify({id: 'sample', name: 'Sample record'})});
    if (result.ok) { object.hidden = false; toast.hidden = true; }
  });
}
document.querySelector('#delete').addEventListener('click', () => dialog.showModal());
document.querySelector('#cancel').addEventListener('click', () => dialog.close());
document.querySelector('#confirm').addEventListener('click', () => { dialog.close(); erase(); });
document.querySelector('#delete-unsafe').addEventListener('click', erase);
