fetch('/api/results').then(response => {
  if (!response.ok) throw new Error('unavailable');
  return response.json();
}).then(records => {
  const list = document.querySelector('#items');
  for (const record of records) {
    const item = document.createElement('li');
    item.textContent = record.name;
    list.append(item);
  }
}).catch(() => {});
