// Synthetic pottery shop. Hints use the optional data-lapis-* namespace; the test server can
// serve this file with every hint stripped to check detection on an unannotated page.
const main = document.querySelector('main');
const good = location.pathname.startsWith('/good');
const base = good ? '/good' : '';
let notices = [];
let insurance = !good;
let address = '';
let card = '';
const names = {item: 'Celadon cup', recurring: 'Studio membership', fee: 'Service fee', total: 'Total'};
const price = (key, kind, amount, extra = '') => `<li data-lapis-price="${kind}" data-lapis-key="${key}" ${extra}>${key === 'kiln-handling' ? 'Kiln handling' : key === 'insurance' ? 'Insurance' : names[kind]} $${amount}${kind === 'recurring' ? '/month' : ''}</li>`;
const cart = () => `<ul id="cart" aria-label="cart">${!good && insurance ? '<li data-lapis-cart-line="insurance" data-lapis-added-by="preselected">Insurance $5 <label><input type="checkbox" id="insurance" checked> Insurance selected</label></li>' : ''}${!good ? '<li data-lapis-cart-line="kiln-handling" data-lapis-added-by="system">Kiln handling $4</li>' : ''}</ul>`;
function home() {
  main.innerHTML = `<section><h2>This firing's pieces</h2><p>Celadon cup ready to reserve</p><ul>${price('celadon-cup', 'item', 30)}</ul><button id="start-reserve">Reserve one piece</button><button id="start-subscribe">Subscribe to firing notices</button>${notices.length ? '<button id="manage">Manage firing notices</button>' : ''}</section>`;
  document.querySelector('#start-reserve').onclick = () => go('/checkout', checkout);
  document.querySelector('#start-subscribe').onclick = () => go('/subscribe', subscribe);
  if (notices.length) document.querySelector('#manage').onclick = () => go('/manage', manage);
}
function checkout() {
  main.innerHTML = `<section><h2>Checkout: shipping and payment</h2><p data-lapis-gate="address">Shipping address is required</p><label>Address <input id="address" autocomplete="street-address" required value="${address}"></label><label data-lapis-gate="payment">Card number <input id="card" autocomplete="cc-number" inputmode="numeric" required value="${card}"></label><button id="next">Continue to review</button><button id="back">Back to pieces</button></section>`;
  document.querySelector('#next').onclick = () => {
    address = document.querySelector('#address').value;
    card = document.querySelector('#card').value;
    if (address && card) go('/review', review);
  };
  document.querySelector('#back').onclick = () => go('/', home);
}
function review() {
  main.innerHTML = `<section><h2>Review reservation</h2><p>Shipping to ${address}</p><ul>${price('celadon-cup', 'item', 30)}${!good ? price('service-fee', 'fee', 3) : ''}${insurance ? price('insurance', 'add-on', 5, 'data-lapis-mandatory="false"') : ''}${!good ? price('kiln-handling', 'add-on', 4, 'data-lapis-mandatory="true"') : ''}${price('order-total', 'total', good ? 30 : insurance ? 42 : 37)}</ul>${cart()}${!good ? '<p data-lapis-disclosure="fee">Service fee $3</p>' : ''}<p data-lapis-disclosure="total">Review the total above before reserving.</p><button id="commit">Confirm reservation</button><button id="edit">Edit address</button></section>`;
  document.querySelector('#commit').onclick = async () => {
    const response = await fetch('/api/reservations', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({piece: 'p1', address})});
    if (response.ok) go('/reservations/r-2409-031', doneReservation);
  };
  document.querySelector('#edit').onclick = () => go('/checkout', checkout);
  if (insurance) document.querySelector('#insurance').onchange = event => {insurance = event.target.checked; review()};
}
function doneReservation() {main.innerHTML = '<section><h2>Reservation number r-2409-031</h2><p>Saved your reservation</p></section>'}
function subscribe() {
  main.innerHTML = `<section><h2>Firing notices</h2><p>Get an email when the next firing's pieces go up</p><label>Email <input type="email" id="email" required></label><button id="confirm-subscribe">Subscribe firing notices</button><button id="back">Back to pieces</button></section>`;
  document.querySelector('#confirm-subscribe').onclick = async () => {
    const email = document.querySelector('#email').value;
    if (!email) return;
    const response = await fetch('/api/firing-notices', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({email})});
    if (response.ok) {notices = await (await fetch('/api/firing-notices')).json(); go('/notices/active', () => {main.innerHTML = '<section><h2>알림을 신청했어요</h2></section>'})}
  };
  document.querySelector('#back').onclick = () => go('/', home);
}
function manage() {
  main.innerHTML = `<section><h2>Manage firing notices</h2><button id="cancel">Cancel firing notices</button><button id="back">Back to pieces</button></section>`;
  document.querySelector('#back').onclick = () => go('/', home);
  document.querySelector('#cancel').onclick = () => good ? go('/cancel', cancel) : go('/retention', retention);
}
function retention() {
  main.innerHTML = `<section data-lapis-offer="retention" data-lapis-blocks="true"><h2>Before you cancel</h2><p>Stay and get early kiln previews</p><button id="no-thanks">No thanks, continue cancellation</button><button id="stay">Stay subscribed</button></section>`;
  document.querySelector('#no-thanks').onclick = () => go('/cancel', cancel);
  document.querySelector('#stay').onclick = () => go('/', home);
}
function cancel() {
  main.innerHTML = `<section><h2>Cancel firing notices</h2>${good ? '' : '<p data-lapis-gate="contact">Only by phone: call studio support to complete cancellation.</p>'}<button id="finish">${good ? 'Confirm cancel notices' : 'Call phone support to cancel'}</button><button id="back">Back to notices</button></section>`;
  document.querySelector('#back').onclick = () => go('/manage', manage);
  document.querySelector('#finish').onclick = async () => {
    const response = await fetch(`/api/firing-notices/${notices[0].id}`, {method: 'DELETE'});
    if (response.ok) {notices = []; go('/notices/stopped', () => {main.innerHTML = '<section><h2>알림을 껐어요</h2></section>'})}
  };
}
function membership() {
  const clear = location.pathname.endsWith('-good');
  main.innerHTML = `<section><h2>Studio membership</h2><p>Free trial first month</p><ul>${price('studio-membership', 'recurring', 10, 'data-lapis-cadence="month"')}</ul>${clear ? '<p data-lapis-disclosure="renewal-price">Renewal price $10 per month</p><p data-lapis-disclosure="cadence">Billed monthly</p><p data-lapis-disclosure="cancellation-method">Cancel by phone</p><p data-lapis-disclosure="trial-end">Trial ends after one month</p><p data-lapis-disclosure="trial-conversion">Trial converts to paid plan after one month</p>' : ''}<button id="join-membership">Subscribe to studio membership</button></section>`;
  document.querySelector('#join-membership').onclick = async () => {
    const response = await fetch('/api/memberships', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({plan: 'monthly'})});
    if (response.ok) main.innerHTML = '<section><h2>Membership started</h2></section>';
  };
}
function offerDialog() {
  const clear = location.pathname.endsWith('-good');
  main.innerHTML = `<section><h2>Reserve a piece</h2></section><dialog data-lapis-offer="upsell" data-lapis-blocks="true"><h2>Optional upsell offer</h2>${clear ? '<button id="decline-offer">No thanks</button>' : ''}<button id="accept-offer">Accept and continue</button></dialog>`;
  const dialog = document.querySelector('dialog');
  dialog.showModal();
  if (clear) document.querySelector('#decline-offer').onclick = () => {
    dialog.close(); main.innerHTML = '<section><h2>Offer declined</h2></section>';
  };
  document.querySelector('#accept-offer').onclick = () => {};
}
function inlineShipping() {
  let shipping = false;
  const render = () => {
    main.innerHTML = `<section><h2>Delivery checkout</h2><ul>${price('celadon-cup', 'item', 30)}${shipping ? '<li data-lapis-price="shipping" data-lapis-key="express-shipping">Express shipping $6</li>' : ''}${price('order-total', 'total', shipping ? 36 : 30)}</ul>${shipping ? '<button id="done-delivery">Continue checkout</button>' : '<button id="choose-shipping">Choose express shipping</button>'}</section>`;
    if (shipping) document.querySelector('#done-delivery').onclick = () => {main.innerHTML = '<section><h2>Delivery chosen</h2></section>'};
    else document.querySelector('#choose-shipping').onclick = () => {shipping = true; render()};
  };
  render();
}
function hinted() {
  // The fee's mandatory and placement hints, the disclosure, the gate, and the offer's blocks hint
  // disagree with what the page shows; the item and total hints agree.
  main.innerHTML = `<section><h2>Hinted checkout</h2><ul>${price('celadon-cup', 'item', 30)}<li data-lapis-price="fee" data-lapis-key="studio-fee" data-lapis-mandatory="false" data-lapis-placement="secondary">Studio fee $2</li>${price('order-total', 'total', 32)}</ul><p data-lapis-disclosure="renewal-price">Pick up your piece at the studio</p><p data-lapis-gate="payment" data-lapis-skippable="true">Card details come later</p><button id="buy-hinted">Continue to pay</button></section><section data-lapis-offer="upsell" data-lapis-blocks="true"><h2>Upgrade your piece</h2><p>Upgrade to a gift box at the studio</p></section>`;
  document.querySelector('#buy-hinted').onclick = async () => {
    const response = await fetch('/api/reservations', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({piece: 'p1'})});
    if (response.ok) main.innerHTML = '<section><h2>Purchased</h2></section>';
  };
}
let loopCount = 0;
function loop() {
  main.innerHTML = `<section><h2>Recovery step ${loopCount}</h2><button id="continue-loop">Continue recovery</button></section>`;
  document.querySelector('#continue-loop').onclick = () => {loopCount += 1; go(`/loop/${loopCount}`, loop)};
}
function go(path, render) {history.pushState({}, '', base + path); render()}
async function initial() {
  notices = await (await fetch('/api/firing-notices')).json();
  const path = location.pathname.slice(base.length);
  if (path === '/dead-end') {main.innerHTML = '<section><h2>No recovery available</h2></section>'; return}
  if (path === '/silent-buy') {
    main.innerHTML = '<section><h2>Mystery piece</h2><button id="buy">Buy now</button></section>';
    document.querySelector('#buy').onclick = async () => {
      const response = await fetch('/api/reservations', {method: 'POST'});
      if (response.ok) main.innerHTML = '<section><h2>Purchased</h2></section>';
    };
    return;
  }
  if (path.startsWith('/dialog-')) {offerDialog(); return}
  if (path === '/inline-shipping') {inlineShipping(); return}
  if (path.startsWith('/loop')) {loop(); return}
  if (path.startsWith('/membership')) {membership(); return}
  if (path === '/hinted') {hinted(); return}
  if (path.startsWith('/reservations/')) doneReservation();
  else if (path === '/checkout') checkout();
  else if (path === '/review') review();
  else if (path === '/subscribe') subscribe();
  else if (path === '/manage') manage();
  else if (path === '/retention') retention();
  else if (path === '/cancel') cancel();
  else home();
}
initial();
