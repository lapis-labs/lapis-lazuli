// Synthetic seat-reservation app. The texts follow <html lang>; Korean and English mean the same thing
// and the markup is identical, so any difference in how the driver treats the two is about the words.
const say = {
  ko: {home: '금요일 저녁', seats: '남은 좌석이 있어요', reserve: '예약하기', options: '인원을 골라 주세요', next: '다음',
       review: '예약 내용을 살펴 주세요', confirm: '확인', cancel: '취소', done: '예약이 완료됐어요',
       cancelled: '예약을 취소했어요', notice: '점검 안내', noticeBody: '오늘 밤 12시에 점검이 있어요', close: '닫기',
       offerTitle: '해지하기 전에 잠깐만요', offerBody: '지금 계속 이용하시면 다음 달 이용료를 50% 할인해 드려요',
       offerTake: '할인 받고 계속 이용하기', offerNo: '괜찮아요', offerLater: '나중에 할게요', offerDone: '제안을 사양했어요',
       seatsTitle: '좌석 현황', seatsSome: n => `좌석 ${n}개가 남았어요`, seatsNone: '아직 좌석이 없어요',
       retry: '다시 시도', add: '좌석 추가', added: '좌석을 추가했어요',
       failed: {server: '좌석 정보에 문제가 생겼어요. 다시 시도해 주세요.', network: '인터넷 연결이 끊겨 좌석을 불러오지 못했어요.',
                403: '이 좌석을 볼 권한이 없어요.', 404: '좌석을 찾을 수 없어요.'},
       bookTitle: '좌석 예약', book: '예약 확정하기', bookPending: '예약을 처리 중이에요', bookDone: '예약이 완료됐어요',
       bookFailed: '예약하지 못했어요. 다시 시도해 주세요.',
       consentTitle: '쿠키 사용 안내', consentBody: '더 나은 서비스를 위해 쿠키를 사용해요', acceptAll: '모두 수락', manage: '설정',
       rejectAll: '모두 거부', saveChoices: '선택 저장', again: '다시 보지 않기', againDays: '7일 동안 다시 보지 않기',
       consentDone: '쿠키를 사용하지 않아요',
       openSettings: '설정 열기', choosePlan: '요금제 선택', openNotice: '대화상자 열기',
       permissionOpen: '알림 권한 요청', permissionTitle: '알림 권한', permissionBody: '알림을 허용하시겠어요?',
       allow: '허용', permissionDone: '알림 권한 요청이 끝났어요',
       action: '예약', actionDone: '예약됐어요', delete: '삭제', pay: '결제',
       stepTitle: '1단계', stepField: '이름', stepDone: '2단계',
       apply: '신청하기', applyReview: '신청 내용을 확인해 주세요', applyDone: '신청이 완료됐어요',
       withdrawTitle: '알림 수신 취소', withdrawn: '알림 수신을 취소했어요',
       deleteObject: '기록 삭제', deleteAsk: '기록을 삭제할까요?', keepObject: '기록 유지',
       confirmDelete: '삭제 확인', undoDelete: '삭제 되돌리기'},
  en: {home: 'Friday evening', seats: 'Seats are still open', reserve: 'Reserve', options: 'Choose the party size', next: 'Next',
       review: 'Look over your reservation', confirm: 'Confirm', cancel: 'Cancel', done: 'Reservation complete',
       cancelled: 'Reservation cancelled', notice: 'Maintenance notice', noticeBody: 'Maintenance starts at midnight tonight', close: 'Close',
       offerTitle: 'Before you cancel', offerBody: 'Keep your plan now and get 50% off next month',
       offerTake: 'Take the discount and continue', offerNo: 'No thanks', offerLater: 'Maybe later', offerDone: 'Offer declined',
       seatsTitle: 'Seat status', seatsSome: n => `${n} seats left`, seatsNone: 'No seats yet',
       retry: 'Try again', add: 'Add a seat', added: 'Seat added',
       failed: {server: 'Seat information failed to load. Try again.', network: 'You are offline. Seats are unavailable.',
                403: 'Access to these seats is denied.', 404: 'Seats not found.'},
       bookTitle: 'Reserve a seat', book: 'Confirm booking', bookPending: 'Processing your reservation', bookDone: 'Reservation completed',
       bookFailed: 'Could not reserve. Try again.',
       consentTitle: 'Cookie notice', consentBody: 'We use cookies to improve the service', acceptAll: 'Accept all', manage: 'Manage',
       rejectAll: 'Reject all', saveChoices: 'Save choices', again: "Don't show again", againDays: "Don't show again for 7 days",
       consentDone: 'Cookies are off',
       openSettings: 'Open settings', choosePlan: 'Choose plan', openNotice: 'Open dialog',
       permissionOpen: 'Request notification permission', permissionTitle: 'Notification permission',
       permissionBody: 'Allow notifications?', allow: 'Allow', permissionDone: 'Notification request completed',
       action: 'Reserve', actionDone: 'Reservation completed', delete: 'Delete', pay: 'Pay',
       stepTitle: 'Step 1', stepField: 'Name', stepDone: 'Step 2',
       apply: 'Apply', applyReview: 'Review the application', applyDone: 'Application complete',
       withdrawTitle: 'Cancel notifications', withdrawn: 'Notifications cancelled',
       deleteObject: 'Delete record', deleteAsk: 'Delete record?', keepObject: 'Keep record',
       confirmDelete: 'Confirm deletion', undoDelete: 'Undo delete'},
}[document.documentElement.lang];
const main = document.querySelector('main');
const go = (path, render) => { history.pushState({}, '', path); render(); };
const show = html => { main.innerHTML = `<section>${html}</section>`; };

function home() {
  show(`<h1>${say.home}</h1><p>${say.seats}</p><button id="reserve">${say.reserve}</button>`);
  document.querySelector('#reserve').onclick = () => go('/options', options);
}
function options() {
  show(`<h2>${say.options}</h2><button id="next">${say.next}</button>`);
  document.querySelector('#next').onclick = () => go('/review', review);
}
function review() {
  // The step button stays on the last step and does nothing; the way out is confirm or cancel.
  show(`<h2>${say.review}</h2><button id="step">${say.next}</button><button id="confirm">${say.confirm}</button><button id="cancel">${say.cancel}</button>`);
  document.querySelector('#confirm').onclick = async () => {
    const response = await fetch('/api/reservations', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
    if (response.ok) go('/done', done);
  };
  document.querySelector('#cancel').onclick = () => go('/cancelled', cancelled);
}
const done = () => show(`<h2>${say.done}</h2>`);
const cancelled = () => show(`<h2>${say.cancelled}</h2>`);
function notice() {
  // A modal outside <main> whose only control is its close button; closing it shows the seats.
  show(`<h1>${say.home}</h1>`);
  document.body.insertAdjacentHTML('beforeend',
    `<dialog id="notice"><h2>${say.notice}</h2><p>${say.noticeBody}</p><button id="close">${say.close}</button></dialog>`);
  const dialog = document.querySelector('#notice');
  dialog.showModal();
  document.querySelector('#close').onclick = () => {
    dialog.close();
    main.firstElementChild.insertAdjacentHTML('beforeend', `<p>${say.seats}</p>`);
  };
}
function offer(turnDown) {
  // A retention offer outside <main>. Taking it changes nothing; turning it down closes it and ends the visit.
  show(`<h1>${say.home}</h1>`);
  document.body.insertAdjacentHTML('beforeend',
    `<dialog id="offer"><h2>${say.offerTitle}</h2><p>${say.offerBody}</p><button id="take">${say.offerTake}</button><button id="turn-down">${turnDown}</button></dialog>`);
  const dialog = document.querySelector('#offer');
  dialog.showModal();
  document.querySelector('#take').onclick = () => {};
  document.querySelector('#turn-down').onclick = () => { dialog.close(); show(`<h2>${say.offerDone}</h2>`); };
}
function seats() {
  // A data surface: its list comes from /api/seats, every failure says what went wrong, and the
  // retry button is always there (an offline visitor can only find out by pressing it).
  main.innerHTML = `<h1>${say.home}</h1><section id="seats" data-state-surface="seats"><h2>${say.seatsTitle}</h2>` +
    `<p id="seat-status" role="status"></p><ul id="seat-list"></ul><button id="retry">${say.retry}</button>` +
    `<button id="add-seat">${say.add}</button></section>`;
  const status = document.querySelector('#seat-status'), list = document.querySelector('#seat-list');
  async function load() {
    try {
      const response = await fetch('/api/seats');
      if (!response.ok) throw new Error(response.status >= 500 ? 'server' : String(response.status));
      const rows = await response.json();
      list.replaceChildren(...rows.map(row => Object.assign(document.createElement('li'), {textContent: row.name})));
      status.textContent = rows.length ? say.seatsSome(rows.length) : say.seatsNone;
    } catch (error) {
      list.replaceChildren();
      status.textContent = say.failed[error instanceof TypeError ? 'network' : error.message];
    }
  }
  document.querySelector('#retry').onclick = load;
  document.querySelector('#add-seat').onclick = async () => {
    const response = await fetch('/api/seats', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{"name":"A3"}'});
    if (response.ok) status.textContent = say.added;
  };
  load();
}
function book() {
  // A commit that says its result in words: pending while the request is out, then done, or failed
  // with a retry button. The button stays enabled, so "pending" is only in the words.
  main.innerHTML = `<h1>${say.home}</h1><section id="book"><h2>${say.bookTitle}</h2>` +
    `<button id="book-seat">${say.book}</button><p id="book-status" role="status"></p></section>`;
  const status = document.querySelector('#book-status');
  let busy = false;
  async function commit() {
    if (busy) return;
    busy = true;
    document.querySelector('#book-retry')?.remove();
    status.textContent = say.bookPending;
    try {
      await new Promise(resolve => setTimeout(resolve, 150));
      const response = await fetch('/api/reservations', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
      if (!response.ok) throw new Error(String(response.status));
      status.textContent = say.bookDone;
    } catch (error) {
      status.textContent = say.bookFailed;
      status.insertAdjacentHTML('afterend', `<button id="book-retry">${say.retry}</button>`);
      document.querySelector('#book-retry').onclick = commit;
    } finally {
      busy = false;
    }
  }
  document.querySelector('#book-seat').onclick = commit;
}
function consent() {
  // A cookie dialog outside <main>: accept all, or manage, which swaps in reject all and save choices.
  show(`<h1>${say.home}</h1>`);
  document.body.insertAdjacentHTML('beforeend',
    `<dialog id="consent"><h2>${say.consentTitle}</h2><p>${say.consentBody}</p>` +
    `<label><input type="checkbox" id="again"> ${say.againDays}</label>` +
    `<div id="first"><button id="accept-all">${say.acceptAll}</button><button id="manage">${say.manage}</button></div>` +
    `<div id="second" hidden><button id="reject-all">${say.rejectAll}</button><button id="save-choices">${say.saveChoices}</button></div></dialog>`);
  const dialog = document.querySelector('#consent');
  dialog.showModal();
  const answer = () => { dialog.close(); show(`<h2>${say.consentDone}</h2>`); };
  for (const id of ['accept-all', 'reject-all', 'save-choices']) document.querySelector('#' + id).onclick = answer;
  document.querySelector('#manage').onclick = () => {
    document.querySelector('#first').hidden = true;
    document.querySelector('#second').hidden = false;
  };
}

function opener(kind) {
  show(`<h1>${say.home}</h1><button id="open">${kind === 'plan' ? say.choosePlan :
    kind === 'dialog' ? say.openNotice : say.openSettings}</button>`);
  document.querySelector('#open').onclick = () => {
    document.body.insertAdjacentHTML('beforeend',
      `<dialog id="opened"><h2>${kind === 'plan' ? say.choosePlan : say.consentTitle}</h2>` +
      `<button id="dismiss">${say.cancel}</button></dialog>`);
    document.querySelector('#opened').showModal();
    document.querySelector('#dismiss').onclick = () => document.querySelector('#opened').close();
  };
}
function permission() {
  show(`<h1>${say.home}</h1><button id="ask">${say.permissionOpen}</button>`);
  document.querySelector('#ask').onclick = () => {
    document.body.insertAdjacentHTML('beforeend',
      `<dialog id="permission"><h2>${say.permissionTitle}</h2><p>${say.permissionBody}</p>` +
      `<button id="allow">${say.allow}</button></dialog>`);
    document.querySelector('#permission').showModal();
    document.querySelector('#allow').onclick = async () => {
      await Notification.requestPermission();
      document.querySelector('#permission').close();
      show(`<h2>${say.permissionDone}</h2>`);
    };
  };
}
function actions() {
  show(`<h1>${say.home}</h1><button id="delete">${say.delete}</button>` +
    `<button id="pay">${say.pay}</button>`);
  for (const id of ['delete', 'pay']) document.querySelector('#' + id).onclick =
    () => fetch('/api/actions', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
}
function action() {
  show(`<h1>${say.home}</h1><button id="action">${say.action}</button><p id="result" role="status"></p>`);
  document.querySelector('#action').onclick = async () => {
    const response = await fetch('/api/actions', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
    if (response.ok) document.querySelector('#result').textContent = say.actionDone;
  };
}
function steps() {
  main.innerHTML = `<form id="step-form"><h1>${say.stepTitle}</h1>` +
    `<label>${say.stepField}<input name="name"></label><button type="submit">${say.saveChoices}</button>` +
    `<button type="button" id="step-next">${say.next}</button><p id="step-status" role="status"></p></form>`;
  const form = document.querySelector('#step-form');
  form.onsubmit = async event => { event.preventDefault();
    const response = await fetch('/api/actions', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
    form.querySelector('#step-status').textContent = response.ok ? say.stepDone : say.bookFailed;
  };
  document.querySelector('#step-next').onclick = () => {
    history.pushState({}, '', '/step-two');
    form.querySelector('h1').textContent = say.stepDone;
  };
}

function apply() {
  show(`<h1>${say.home}</h1><button id="apply">${say.apply}</button>`);
  document.querySelector('#apply').onclick = () => go('/apply-review', applyReview);
}
function applyReview() {
  show(`<h2>${say.applyReview}</h2><button id="apply-cancel">${say.cancel}</button>` +
    `<button id="apply-confirm">${say.confirm}</button>`);
  document.querySelector('#apply-cancel').onclick = () => go('/apply-cancelled', cancelled);
  document.querySelector('#apply-confirm').onclick = async () => {
    const response = await fetch('/api/applications', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
    if (response.ok) go('/apply-done', () => show(`<h2>${say.applyDone}</h2>`));
  };
}
function withdraw() {
  show(`<h1>${say.withdrawTitle}</h1><button id="withdraw">${say.cancel}</button>`);
  document.querySelector('#withdraw').onclick = async () => {
    const response = await fetch('/api/withdrawals', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
    if (response.ok) go('/withdrawn', () => show(`<h2>${say.withdrawn}</h2>`));
  };
}

function destructive() {
  show(`<section id="record"><h1>${say.home}</h1><button id="delete-record">${say.deleteObject}</button></section>` +
    `<div id="toast" role="status" hidden></div>`);
  document.body.insertAdjacentHTML('beforeend',
    `<dialog id="confirm-delete"><p>${say.deleteAsk}</p><button id="keep">${say.keepObject}</button>` +
    `<button id="confirm-delete-button">${say.confirmDelete}</button></dialog>`);
  const dialog = document.querySelector('#confirm-delete');
  document.querySelector('#delete-record').onclick = () => { dialog.showModal(); document.querySelector('#keep').focus(); };
  document.querySelector('#keep').onclick = () => dialog.close();
  document.querySelector('#confirm-delete-button').onclick = async () => {
    dialog.close();
    const response = await fetch('/api/actions', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
    if (!response.ok) return;
    document.querySelector('#record').hidden = true;
    const toast = document.querySelector('#toast');
    toast.hidden = false;
    toast.innerHTML = `<button id="undo">${say.undoDelete}</button>`;
    document.querySelector('#undo').onclick = async () => {
      const restore = await fetch('/api/actions', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
      if (restore.ok) { document.querySelector('#record').hidden = false; toast.hidden = true; }
    };
  };
}

// The front page opens with the notice, or with the cookie dialog when the page says so (data-home);
// the reservation starts at /reserve.
const routes = {'/': notice, '/options': options, '/review': review, '/done': done, '/cancelled': cancelled,
                '/offer': () => offer(say.offerNo), '/offer-later': () => offer(say.offerLater), '/seats': seats, '/book': book,
                '/consent': consent, '/settings-dialog': () => opener('settings'), '/choice-opener': () => opener('plan'),
                '/dialog-opener': () => opener('dialog'), '/permission': permission, '/actions': actions,
                '/action': action, '/steps': steps, '/step-two': steps, '/apply': apply,
                '/apply-review': applyReview, '/withdraw': withdraw, '/destructive': destructive};
const front = document.documentElement.dataset.home;
(routes[location.pathname === '/' && front ? front : location.pathname] || home)();
