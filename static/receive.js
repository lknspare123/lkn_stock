/* Receive page — mirrors the desktop ReceivePage (new receive, payments, edit, history, summary, invoice). */
(function () {
  const {$, $$, esc, num, money, qty, dmy, api, toast, modal, confirm, alert, selectable, combo, payState, payPill, PAY} = UI;
  const ITEMS = JSON.parse($('#items-data').textContent), SUPPLIERS = JSON.parse($('#suppliers-data').textContent);
  const VIEW = JSON.parse($('#view-data').textContent);
  const byId = new Map(ITEMS.map(i => [i.id, i]));
  let cart = [], picked = null, editing = null, paidTouched = false, HIST = [];
  const showTab = UI.tabs($('#root'), id => { if (id === 'p-hist') loadHistory(); });

  // ── payment status text ────────────────────────────────────────────────
  const total = () => cart.reduce((s, l) => s + l.qty * l.price, 0);
  function payUI() {
    const t = total(), p = num($('#inv-paid').value), st = payState(t, p), el = $('#pay-status');
    el.className = 'paystat ' + st; el.textContent = t <= 0 && p <= 0 ? '' : (st === 'paid' ? PAY.paid : st === 'partial' ? `${PAY.partial} · នៅខ្វះ ${money(t - p)}` : PAY.unpaid);
    $('#g-bal').textContent = money(Math.max(t - p, 0));
  }
  $('#inv-paid').addEventListener('input', () => { paidTouched = true; payUI(); });
  $('#pay-full').addEventListener('click', () => { $('#inv-paid').value = total().toFixed(2); paidTouched = true; payUI(); });
  $('#pay-zero').addEventListener('click', () => { $('#inv-paid').value = 0; paidTouched = true; payUI(); });

  // ── item search ────────────────────────────────────────────────────────
  const match = q => { q = q.toLowerCase().trim(); if (!q) return []; return ITEMS.filter(i => (i.code + ' ' + i.kh + ' ' + i.en).toLowerCase().includes(q)).slice(0, 8); };
  const priceFor = it => { const d = it.distributors.find(x => x.name.toLowerCase() === $('#inv-dist').value.trim().toLowerCase()); return d ? d.cost : (it.min_cost || it.unit_price || 0); };
  function pick(it) {
    picked = it; $('#it-search').value = it.code; $('#it-picked').textContent = `${it.kh} ${it.en ? '· ' + it.en : ''} — នៅសល់ ${qty(it.remain)}`;
    $('#it-price').value = priceFor(it); $('#it-qty').focus(); $('#it-qty').select();
  }
  combo($('#it-search'), q => match(q).map(i => ({html: `<b>${esc(i.code)}</b> ${esc(i.kh)} <small>${esc(i.en)} · សល់ ${qty(i.remain)}</small>`, value: i.code, data: i})), e => pick(e.data),
    {autoFirst: true, onEnter: items => { const q = $('#it-search').value.trim().toLowerCase(); const ex = ITEMS.find(i => i.code.toLowerCase() === q); if (ex) pick(ex); else if (items[0]) pick(items[0].data); }});
  $('#it-search').addEventListener('input', () => { picked = null; $('#it-picked').textContent = ''; });
  combo($('#inv-dist'), q => SUPPLIERS.filter(s => s.toLowerCase().includes(q.toLowerCase())).slice(0, 8).map(s => ({html: esc(s), value: s})), () => {}, {onFocusShow: true});

  function addLine() {
    if (!picked) { const ex = ITEMS.find(i => i.code.toLowerCase() === $('#it-search').value.trim().toLowerCase()); if (ex) picked = ex; }
    if (!picked) return alert('សូមស្វែងរក និងជ្រើសរើសទំនិញជាមុនសិន!');
    const q = num($('#it-qty').value), p = num($('#it-price').value);
    if (q <= 0) return alert('បរិមាណត្រូវតែធំជាងសូន្យ។');
    if (p < 0) return alert('ថ្លៃដើមមិនអាចតូចជាងសូន្យបានទេ។');
    const ex = cart.find(l => l.item_id === picked.id && Math.abs(l.price - p) < 1e-9);
    if (ex) ex.qty += q; else cart.push({item_id: picked.id, code: picked.code, name: picked.kh || picked.en, qty: q, price: p});
    picked = null; $('#it-search').value = ''; $('#it-picked').textContent = ''; $('#it-qty').value = 1; $('#it-price').value = 0; $('#it-search').focus();
    drawCart();
  }
  $('#it-add').addEventListener('click', addLine);
  $('#it-qty').addEventListener('keydown', e => { if (e.key === 'Enter') $('#it-price').focus(); });
  $('#it-price').addEventListener('keydown', e => { if (e.key === 'Enter') addLine(); });

  // ── cart ───────────────────────────────────────────────────────────────
  const csel = selectable($('#cart'), {onDouble: k => editLine(+k)});
  function drawCart() {
    $('#cart').innerHTML = cart.map((l, i) => `<tr data-key="${i}"><td><b>${esc(l.code)}</b></td><td>${esc(l.name)}</td><td class="num">${qty(l.qty)}</td><td class="num">${money(l.price)}</td><td class="num">${money(l.qty * l.price)}</td><td class="num"><button class="btn-x" data-del="${i}" title="លុប">✕</button></td></tr>`).join('') ||
      '<tr><td colspan="6" class="muted">មិនទាន់មានទំនិញ</td></tr>';
    $('#g-total').textContent = money(total()); $('#cart-count').textContent = cart.length ? `(${cart.length} មុខ)` : '';
    if (!paidTouched && !editing) $('#inv-paid').value = 0; payUI();
  }
  $('#cart').addEventListener('click', e => { const b = e.target.closest('[data-del]'); if (b) { cart.splice(+b.dataset.del, 1); drawCart(); } });
  document.addEventListener('keydown', e => { if (e.key === 'Delete' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) && !$('#p-new').hidden && csel.get().length) { cart.splice(+csel.get()[0], 1); drawCart(); } });
  function editLine(i) {
    const l = cart[i]; if (!l) return;
    modal({title: '✏ កែប្រែទំនិញ — ' + esc(l.code), width: 380, body: `<div class="fld"><label>បរិមាណ</label><input id="e-q" type="number" step="any" min="0" value="${l.qty}"></div><div class="fld"><label>ថ្លៃដើម/ឯកតា ($)</label><input id="e-p" type="number" step="any" min="0" value="${l.price}"></div>`,
      enter: d => $('.btn:not(.sec)', d.el).click(), buttons: [{label: 'បោះបង់', cls: 'sec'}, {label: 'រក្សាទុក', cls: '', onClick: d => {
        const q = num($('#e-q', d.el).value), p = num($('#e-p', d.el).value); if (q <= 0) { UI.toast('បរិមាណត្រូវតែធំជាងសូន្យ។', 'error'); return false; }
        l.qty = q; l.price = p; drawCart(); }}]});
  }

  // ── save / clear / edit mode ───────────────────────────────────────────
  async function nextCode() { try { return (await api('/api/receive/next-code')).code; } catch (e) { return ''; } }
  async function reset() {
    cart = []; picked = null; editing = null; paidTouched = false; $('#inv-code').readOnly = false; $('#inv-code').value = await nextCode();
    ['#inv-dist', '#inv-notes', '#it-search'].forEach(s => $(s).value = ''); $('#inv-paid').value = 0; $('#inv-date').value = new Date(Date.now() + 7 * 3600e3).toISOString().slice(0, 10);
    $('#it-picked').textContent = ''; $('#edit-banner').hidden = true; $('#cancel-edit').hidden = true; $('#save').innerHTML = '💾 រក្សាទុកវិក្កយបត្រ'; drawCart();
  }
  $('#clear').addEventListener('click', async () => { if (!cart.length || await confirm('សម្អាតទម្រង់ និងទំនិញទាំងអស់?')) reset(); });
  $('#cancel-edit').addEventListener('click', reset);
  $('#save').addEventListener('click', async () => {
    const btn = $('#save'); if (!$('#inv-code').value.trim() || !$('#inv-dist').value.trim()) return alert('សូមបំពេញលេខវិក្កយបត្រ និងឈ្មោះអ្នកផ្គត់ផ្គង់។');
    if (!cart.length) return alert('សូមបញ្ចូលទំនិញយ៉ាងហោចណាស់មួយមុខទៅក្នុងវិក្កយបត្រ។');
    if (num($('#inv-paid').value) > total() + 0.005 && !await confirm('ទឹកប្រាក់បានបង់ច្រើនជាងសរុបវិក្កយបត្រ។ បន្តរក្សាទុក?')) return;
    btn.disabled = true;
    try {
      const r = await api('/api/receive/save', {code: $('#inv-code').value, distributor: $('#inv-dist').value, date: $('#inv-date').value, notes: $('#inv-notes').value,
        paid_amount: num($('#inv-paid').value), editing_code: editing, items: cart.map(l => ({item_id: l.item_id, qty: l.qty, price: l.price}))});
      toast(r.editing ? `បានកែប្រែវិក្កយបត្រ ${r.code} រួចរាល់។` : `បានរក្សាទុកវិក្កយបត្រ ${r.code} រួចរាល់។`);
      // refresh remaining qty + supplier price memory in the local item list
      location.href = '/receive';
    } catch (e) { alert(e.message); } finally { btn.disabled = false; }
  });

  async function loadForEdit(code) {
    const inv = await api('/api/receive/' + encodeURIComponent(code));
    cart = inv.lines.map(l => ({item_id: l.item_id, code: l.code, name: l.name, qty: l.qty, price: l.price}));
    editing = inv.code; paidTouched = true;
    $('#inv-code').value = inv.code; $('#inv-code').readOnly = true; $('#inv-dist').value = inv.distributor; $('#inv-date').value = (inv.date || '').slice(0, 10); $('#inv-notes').value = inv.notes;
    $('#inv-paid').value = inv.paid; const b = $('#edit-banner'); b.hidden = false; b.textContent = `✏ កំពុងកែប្រែវិក្កយបត្រ៖ ${inv.code}`;
    $('#cancel-edit').hidden = false; $('#save').innerHTML = '💾 រក្សាទុកការកែប្រែ'; drawCart(); showTab('p-new');
  }

  // ── history ────────────────────────────────────────────────────────────
  const hsel = selectable($('#h-body'), {multi: true, onDouble: k => viewInvoice(k), onChange: () => {}});
  async function loadHistory() { HIST = await api('/api/receive/list'); drawHistory(); }
  function filtered() {
    const words = $('#h-q').value.toLowerCase().split(/\s+/).filter(Boolean), s = $('#h-start').value, e = $('#h-end').value, p = $('#h-paid').value;
    return HIST.filter(r => {
      const blob = [r.code, r.distributor, r.notes, r.date].join(' ').toLowerCase();
      return words.every(w => blob.includes(w)) && (!s || r.date.slice(0, 10) >= s) && (!e || r.date.slice(0, 10) <= e) && (p === 'all' || r.state === p);
    });
  }
  function drawHistory() {
    const rows = filtered(), keep = hsel.get();
    $('#h-body').innerHTML = rows.map(r => `<tr data-key="${esc(r.code)}"><td><b>${esc(r.code)}</b></td><td>${esc(r.distributor)}</td><td>${dmy(r.date)}</td><td class="c">${r.item_count}</td><td class="num">${money(r.total)}</td><td class="num">${money(r.paid)}</td><td class="num" style="color:${r.balance > 0.005 ? 'var(--bad)' : 'inherit'}">${money(r.balance)}</td><td>${payPill(r.state, r.label)}</td></tr>`).join('') ||
      '<tr><td colspan="8" class="muted">មិនមានទិន្នន័យ</td></tr>';
    hsel.set(keep.filter(k => rows.some(r => r.code === k)));
    $('#h-count').textContent = `${rows.length} វិក្កយបត្រ`;
  }
  ['#h-q', '#h-start', '#h-end', '#h-paid'].forEach(s => $(s).addEventListener('input', UI.debounce(drawHistory, 120)));
  $('#h-clear').addEventListener('click', () => { $('#h-q').value = ''; $('#h-start').value = ''; $('#h-end').value = ''; $('#h-paid').value = 'all'; drawHistory(); });
  $('#h-summary').addEventListener('click', () => {
    const t = new Date(Date.now() + 7 * 3600e3).toISOString().slice(0, 10);
    UI.summaryDialog('receive', $('#h-start').value || t.slice(0, 8) + '01', $('#h-end').value || t, 'អ្នកផ្គត់ផ្គង់');
  });
  const one = () => { const k = hsel.get(); if (k.length !== 1) { alert('សូមជ្រើសរើសវិក្កយបត្រតែមួយជាមុនសិន។'); return null; } return k[0]; };

  async function viewInvoice(code) {
    const inv = await api('/api/receive/' + encodeURIComponent(code));
    const row = (k, v) => `<div class="mrow"><span>${k}</span><b>${v}</b></div>`;
    modal({title: '🔎 វិក្កយបត្រ ' + esc(inv.code), width: 720, body: row('អ្នកផ្គត់ផ្គង់', esc(inv.distributor)) + row('កាលបរិច្ឆេទ', dmy(inv.date)) + row('កំណត់សម្គាល់', esc(inv.notes) || '–') +
      row('ស្ថានភាព', payPill(inv.state, inv.label)) + row('សរុប / បានបង់ / នៅខ្វះ', `${money(inv.total)} / ${money(inv.paid)} / <span style="color:var(--bad)">${money(inv.balance)}</span>`) +
      '<div class="tw short" style="margin-top:10px"><table><thead><tr><th>កូដ</th><th>ឈ្មោះ</th><th class="num">បរិមាណ</th><th class="num">ថ្លៃដើម</th><th class="num">សរុប</th></tr></thead><tbody>' +
      inv.lines.map(l => `<tr><td>${esc(l.code)}</td><td>${esc(l.name)}</td><td class="num">${qty(l.qty)}</td><td class="num">${money(l.price)}</td><td class="num">${money(l.total)}</td></tr>`).join('') + '</tbody></table></div>',
      buttons: [{label: '🖨 បោះពុម្ព', cls: 'sec', close: false, onClick: () => UI.openPrint('/receive/' + encodeURIComponent(code) + '/print')}, {label: 'បិទ', cls: ''}]});
  }
  $('#a-view').addEventListener('click', () => { const c = one(); c && viewInvoice(c); });
  $('#a-edit').addEventListener('click', async () => { const c = one(); if (c) { if (cart.length && !editing && !await confirm('ទំនិញក្នុងទម្រង់បច្ចុប្បន្ននឹងត្រូវជំនួស។ បន្ត?')) return; loadForEdit(c); } });
  $('#a-print').addEventListener('click', () => { const c = one(); c && UI.openPrint('/receive/' + encodeURIComponent(c) + '/print'); });
  $('#a-pay').addEventListener('click', async () => { const c = one(); if (!c) return; const inv = await api('/api/receive/' + encodeURIComponent(c)); UI.paymentDialog('receive', inv, ['អ្នកផ្គត់ផ្គង់', inv.distributor], loadHistory); });
  $('#a-paid').addEventListener('click', async () => {
    const k = hsel.get(); if (!k.length) return alert('សូមជ្រើសរើសវិក្កយបត្រជាមុនសិន។');
    if (!await confirm(`ដាក់វិក្កយបត្រចំនួន ${k.length} ថាបានទូទាត់ពេញ?`)) return;
    const r = await api('/api/receive/mark-paid', {codes: k}); toast(`បានធ្វើបច្ចុប្បន្នភាព ${r.count} វិក្កយបត្រ។`); loadHistory();
  });
  $('#a-del').addEventListener('click', async () => {
    const k = hsel.get(); if (!k.length) return alert('សូមជ្រើសរើសវិក្កយបត្រជាមុនសិន។');
    if (!await confirm(`លុបវិក្កយបត្រចំនួន ${k.length}?\nបរិមាណស្តុកនឹងត្រូវកាត់ចេញវិញ។`, {danger: true, yes: 'លុប'})) return;
    await api('/api/receive/delete', {codes: k}); toast('បានលុបរួចរាល់។'); if (editing && k.includes(editing)) reset(); loadHistory();
  });

  drawCart(); if (VIEW) { showTab('p-hist'); loadHistory().then(() => viewInvoice(VIEW).catch(() => {})); }
})();
