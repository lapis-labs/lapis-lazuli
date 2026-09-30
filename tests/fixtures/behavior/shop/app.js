const products = document.querySelector('#products');
const status = document.querySelector('#status');
fetch('/api/products').then(response => response.json()).then(items => {
  for (const item of items) {
    const row = document.createElement('li');
    row.textContent = item.name;
    products.append(row);
  }
});
document.querySelector('#add').addEventListener('click', async () => {
  const response = await fetch('/api/cart', {method:'POST',headers:{'Content-Type':'application/json'},
    body: JSON.stringify({product:'p1'})});
  if (response.ok) status.textContent = 'Added to cart (1 item)';
});
document.querySelector('#expand').addEventListener('click', () => {
  document.querySelector('#animated').style.width = '240px';
});
document.querySelector('#expand-instant').addEventListener('click', () => {
  document.querySelector('#instant').style.width = '240px';
});
document.querySelector('#expand-quick').addEventListener('click', () => {
  document.querySelector('#quick').style.width = '240px';
});
document.querySelector('#grow').addEventListener('click', () => {
  document.querySelector('#growing').animate([{height: '20px'}, {height: '80px'}],
    {duration: 300, fill: 'forwards'});
});
document.querySelector('#dialog-opener').addEventListener('click', () =>
  document.querySelector('#shipping').showModal());
document.querySelector('#dismiss').addEventListener('click', () =>
  document.querySelector('#shipping').close());
document.querySelector('#second').addEventListener('click', event => {
  event.preventDefault(); history.pushState({}, '', '/second');
});
document.querySelector('#reserve').addEventListener('click', async () => {
  const response = await fetch('/api/reservations', {method:'POST',headers:{'Content-Type':'application/json'},
    body: JSON.stringify({product:'p1'})});
  if (response.ok) {
    const toast = document.querySelector('#toast'); toast.hidden = false; toast.textContent = 'Reservation saved';
  }
});
