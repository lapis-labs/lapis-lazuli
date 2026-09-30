const signup = document.querySelector('#signup');
const email = document.querySelector('#email');
const password = document.querySelector('#password');
const display = document.querySelector('#display');
const status = document.querySelector('#signup-status');
password.addEventListener('paste', event => event.preventDefault());
signup.addEventListener('submit', async event => {
  event.preventDefault();
  document.querySelector('#email-error').textContent = '';
  document.querySelector('#password-error').textContent = '';
  email.removeAttribute('aria-invalid');
  password.removeAttribute('aria-invalid');
  if (!email.value.includes('@')) {
    email.setAttribute('aria-invalid', 'true');
    email.setAttribute('aria-describedby', 'email-error');
    document.querySelector('#email-error').textContent = 'Email must contain @';
    email.focus(); return;
  }
  if (password.value.length < 8) {
    password.setAttribute('aria-invalid', 'true');
    password.setAttribute('aria-describedby', 'password-error');
    document.querySelector('#password-error').textContent = 'Password must contain at least 8 characters';
    password.focus(); return;
  }
  const response = await fetch('/api/accounts', {method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({email:email.value,password:password.value,name:display.value})});
  if (!response.ok) {
    email.value = ''; password.value = ''; display.value = '';
    document.querySelector('#marketing').checked = false;
    document.querySelector('#terms').checked = false;
    status.textContent = 'Account creation failed. Try again.';
    return;
  }
  status.textContent = 'Account created';
});
const instant = document.querySelector('#instant');
instant.querySelector('#alias').addEventListener('input', event => {
  const invalid = event.target.value.length > 0 && event.target.value.length < 3;
  event.target.setAttribute('aria-invalid', String(invalid));
  instant.querySelector('#alias-error').textContent = invalid ? 'At least three characters' : '';
});
instant.addEventListener('submit', event => event.preventDefault());
const results = document.querySelector('#results');
const resultsStatus = document.querySelector('#results-status');
const spinner = document.querySelector('.spinner');
async function loadResults() {
  spinner.classList.add('active');
  try {
    const response = await fetch('/api/results');
    if (!response.ok) throw new Error('unavailable');
    const records = await response.json();
    results.replaceChildren(...records.map(item => {
      const li = document.createElement('li'); li.textContent = item.name; return li;
    }));
    resultsStatus.textContent = records.length ? `${records.length} results found` : 'No results found';
  } catch (_) {
    results.replaceChildren();
    resultsStatus.textContent = 'Results unavailable. Try again.';
  } finally {
    spinner.classList.remove('active');
  }
}
document.querySelector('#retry').addEventListener('click', loadResults);
document.querySelector('#add-result').addEventListener('click', async () => {
  const response = await fetch('/api/results', {method:'POST',headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name:'result'})});
  if (response.ok) resultsStatus.textContent = 'Saved result';
});
loadResults();
