// Synthetic decision screens. The texts follow <html lang>; Korean and English mean the same thing and
// the markup is identical, so any difference in how the driver treats the two is about the words.
const say = {
  ko: {account: '내 계정', signup: '가입하기', signedUp: '가입이 완료됐어요', notSignedUp: '가입하지 않았어요',
       termsTitle: '이용약관', termsAsk: '서비스 이용약관에 동의해 주세요', agree: '동의하고 계속', no: '아니요',
       mixTitle: '가입 동의', mixRequired: '[필수] 이용약관에 동의합니다', mixOptional: '[선택] 마케팅 정보 수신에 동의합니다',
       mktTitle: '소식 받기', mktAsk: '[선택] 마케팅 정보 수신에 동의하시겠어요?', yes: '동의',
       cancelSub: '구독 취소', cancelSubHaeji: '구독 해지하기', sure: '정말 구독을 취소하시겠어요?', cancel: '취소',
       confirm: '확인', ok: '확인', cancelled: '구독이 취소됐어요', cancelledHaeji: '구독이 해지됐어요',
       retentionTitle: '해지하기 전에 잠깐만요', retentionBody: '지금 계속 이용하시면 다음 달 이용료를 50% 할인해 드려요',
       benefit: '혜택 받고 계속 이용하기', declineCancel: '해지하기', benefitApplied: '혜택을 적용했어요',
       saveChanges: '변경 저장', reserve: '좌석 예약하기', next: '다음', reserved: '예약이 완료됐어요', cancelledNext: '취소했어요',
       later: '다음에 할게요', laterDone: '나중에 다시 안내해 드릴게요',
       noticeTitle: '점검 안내', noticeBody: '오늘 밤 12시에 점검이 있어요', close: '닫기', seats: '남은 좌석이 있어요',
       againDialog: '알림 안내', okay: '확인',
       delete: '삭제', undo: '되돌리기', undoAlt: '실행 취소', restore: '복원하기', deleted: '기록을 삭제했어요', record: '기록'},
  en: {account: 'My account', signup: 'Sign up', signedUp: 'Sign-up complete', notSignedUp: 'Not signed up',
       termsTitle: 'Terms of Service', termsAsk: 'Please agree to the Terms', agree: 'Agree and continue', no: 'No thanks',
       mixTitle: 'Sign-up agreements', mixRequired: '[Required] I agree to the Terms of Service',
       mixOptional: '[Optional] Send me marketing emails',
       mktTitle: 'Stay in touch', mktAsk: '[Optional] Would you like marketing emails?', yes: 'Yes please',
       cancelSub: 'Cancel subscription', cancelSubHaeji: 'Cancel subscription', sure: 'Are you sure you want to cancel your subscription?',
       cancel: 'Cancel', confirm: 'Confirm', ok: 'OK', cancelled: 'Subscription cancelled', cancelledHaeji: 'Subscription cancelled',
       retentionTitle: 'Before you cancel', retentionBody: 'Special offer: keep your plan and get 50% off next month',
       benefit: 'Keep my plan and get 50% off', declineCancel: 'Cancel subscription', benefitApplied: 'Discount applied',
       saveChanges: 'Save changes', reserve: 'Reserve a seat', next: 'Next', reserved: 'Reservation complete', cancelledNext: 'Cancelled',
       later: 'Maybe later', laterDone: 'We will ask again later',
       noticeTitle: 'Maintenance notice', noticeBody: 'Maintenance starts at midnight tonight', close: 'Close', seats: 'Seats are still open',
       againDialog: 'Notice', okay: 'OK',
       delete: 'Delete', undo: 'Undo', undoAlt: 'Undo', restore: 'Bring it back', deleted: 'Record deleted', record: 'Record'},
}[document.documentElement.lang];
const main = document.querySelector('main');
const show = html => { main.innerHTML = html; };
const post = path => fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
const modal = html => {
  document.body.insertAdjacentHTML('beforeend', `<dialog>${html}</dialog>`);
  const dialog = document.body.lastElementChild;
  dialog.showModal();
  return dialog;
};
const on = (selector, handler, root = document) => { root.querySelector(selector).onclick = handler; };

function signup(kind) {
  // Sign-up opens a dialog. A terms dialog asks for what the flow needs (No leaves the flow); a
  // marketing dialog is an optional offer (both answers finish the sign-up).
  show(`<h1>${say.account}</h1><button id="signup">${say.signup}</button>`);
  on('#signup', () => {
    const optional = kind === 'marketing';
    const body = kind === 'terms' ? `<h2>${say.termsTitle}</h2><p>${say.termsAsk}</p>` :
      kind === 'combined' ? `<h2>${say.mixTitle}</h2><p>${say.mixRequired}</p><p>${say.mixOptional}</p>` :
      `<h2>${say.mktTitle}</h2><p>${say.mktAsk}</p>`;
    const dialog = modal(`${body}<button id="yes">${optional ? say.yes : say.agree}</button><button id="no">${say.no}</button>`);
    const finish = async () => { await post('/api/signups'); dialog.close(); show(`<h2>${say.signedUp}</h2>`); };
    on('#yes', finish, dialog);
    on('#no', optional ? finish : () => { dialog.close(); show(`<h2>${say.notSignedUp}</h2>`); }, dialog);
  });
}
function cancelConfirm(second) {
  // Cancelling asks once more, with the cancel control first.
  show(`<h1>${say.account}</h1><button id="cancel-sub">${say.cancelSub}</button>`);
  on('#cancel-sub', () => {
    const dialog = modal(`<p>${say.sure}</p><button id="dialog-cancel">${say.cancel}</button>` +
      `<button id="dialog-confirm">${second === 'ok' ? say.ok : say.confirm}</button>`);
    on('#dialog-cancel', () => dialog.close(), dialog);
    on('#dialog-confirm', async () => { await post('/api/cancellations'); dialog.close(); show(`<h2>${say.cancelled}</h2>`); }, dialog);
  });
}
function retention() {
  // A retention offer whose benefit comes first; the way out says only what it does.
  show(`<h1>${say.account}</h1><button id="cancel-sub">${say.cancelSubHaeji}</button>`);
  on('#cancel-sub', () => {
    const dialog = modal(`<h2>${say.retentionTitle}</h2><p>${say.retentionBody}</p>` +
      `<button id="benefit">${say.benefit}</button><button id="decline-cancel">${say.declineCancel}</button>`);
    on('#benefit', () => { dialog.close(); show(`<h2>${say.benefitApplied}</h2>`); }, dialog);
    on('#decline-cancel', async () => { await post('/api/cancellations'); dialog.close(); show(`<h2>${say.cancelledHaeji}</h2>`); }, dialog);
  });
}
function cancelSave() {
  show(`<h1>${say.account}</h1><button id="save">${say.saveChanges}</button><button id="cancel-sub">${say.cancelSub}</button>`);
  on('#save', () => {});
  on('#cancel-sub', async () => { await post('/api/cancellations'); show(`<h2>${say.cancelled}</h2>`); });
}
function backOut(second, done) {
  // A step whose first control backs out and whose second goes on; backing out is a dead end.
  show(`<h1>${say.reserve}</h1><button id="first">${second.first}</button><button id="second">${second.second}</button>`);
  on('#first', () => show(`<h2>${second.firstDone}</h2>`));
  on('#second', async () => { await post('/api/signups'); show(`<h2>${done}</h2>`); });
}
function payOffer() {
  show(`<h1>Print shop</h1><button id="buy">Buy</button>`);
  on('#buy', () => {
    const dialog = modal(`<h2>Special offer</h2><p>Add a frame for $10 and get 20% off.</p>` +
      `<button id="now">Pay now</button><button id="later">Pay later</button><button id="save">Save for later</button>`);
    on('#now', async () => { await post('/api/orders'); dialog.close(); show(`<h2>Order placed</h2>`); }, dialog);
    for (const id of ['#later', '#save']) on(id, () => { dialog.close(); show(`<h2>Payment postponed</h2>`); }, dialog);
  });
}
function notice() {
  // A modal outside <main> whose only control is an icon button named by its aria-label.
  show(`<h1>${say.account}</h1>`);
  const dialog = modal(`<h2>${say.noticeTitle}</h2><p>${say.noticeBody}</p><button id="close" aria-label="${say.close}">✕</button>`);
  on('#close', () => { dialog.close(); main.insertAdjacentHTML('beforeend', `<p>${say.seats}</p>`); }, dialog);
}
function again() {
  show(`<h1>${say.account}</h1>`);
  modal(`<h2>${say.againDialog}</h2><label><input type="checkbox" id="again"> <span id="again-text">${say.noticeBody}</span></label>` +
    `<button id="okay">${say.okay}</button>`);
}
function deletion(label) {
  // Deleting acts at once and offers an undo in a toast; the undo brings the record back.
  show(`<section id="record"><h1>${say.record}</h1><button id="delete">${say.delete}</button></section>` +
    `<div id="toast" role="status" hidden></div>`);
  on('#delete', async () => {
    const response = await post('/api/actions');
    if (!response.ok) return;
    document.querySelector('#record').hidden = true;
    const toast = document.querySelector('#toast');
    toast.hidden = false;
    toast.innerHTML = `${say.deleted} <button id="undo">${label}</button>`;
    on('#undo', async () => {
      const restore = await post('/api/actions');
      if (restore.ok) { document.querySelector('#record').hidden = false; toast.hidden = true; }
    }, toast);
  });
}

const routes = {
  '/terms': () => signup('terms'), '/terms-marketing': () => signup('combined'), '/marketing': () => signup('marketing'),
  '/cancel-confirm': () => cancelConfirm('confirm'), '/cancel-ok': () => cancelConfirm('ok'),
  '/retention': retention, '/cancel-save': cancelSave,
  '/cancel-next': () => backOut({first: say.cancel, firstDone: say.cancelledNext, second: say.next}, say.reserved),
  '/next-time': () => backOut({first: say.later, firstDone: say.laterDone, second: say.next}, say.reserved),
  '/pay-offer': payOffer, '/notice': notice, '/again': again,
  '/undo': () => deletion(say.undo), '/undo-alt': () => deletion(say.undoAlt), '/undo-unread': () => deletion(say.restore),
};
// The front page shows the screen the page names (data-home), so probes that reload at "/" find it.
const front = document.documentElement.dataset.home;
(routes[location.pathname === '/' && front ? front : location.pathname] || (() => show('<h1>?</h1>')))();
