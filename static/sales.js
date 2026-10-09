/* Sales page — mirrors the desktop SalesPage (cart, discount %, payments, customers, edit mode, history, A5 invoice). */
(function () {
  const {$, $$, esc, num, money, qty, dmy, api, toast, modal, confirm, alert, selectable, payState, payPill, PAY} = UI;
  const ITEMS = JSON.parse($('#items-data').textContent), GENERAL = document.body.dataset.general || $('#s-cust').options[0].value;
  const VIEW = JSON.parse($('#view-data').textContent);
  const byId = new Map(ITEMS.map(i => [i.id, i]));
  let cart = [], editing = null, allowed = {}, paidTouched = false, HIST = [], curDetail = null;
  const showTab = UI.tabs($('#root'), id => { if (id === 'p-hist') loadHistory(); });
  const customer = () => $('#s-cust').value;
  const priceFor = it => { const c = customer() !== GENERAL && it.customers.find(x => x.name === customer()); return c ? c.price : (it.sell_price || 0); };
  const costFor = it => it.unit_price || it.min_cost || 0;
  const limit = id => allowed[id] ?? (byId.get(id) || {}).remain ?? 0;

  // ── totals ─────────────────────────────────────────────────────────────
  const subtotal = () => cart.reduce((s, l) => s + l.qty * l.sell_price, 0);
  const disc = () => Math.min(Math.max(num($('#s-disc').value), 0), 100);
  const grand = () => subtotal() * (1 - disc() / 100);
  function totals() {
    const sub = subtotal(), g = grand(), p = num($('#s-paid').value), st = payState(g, p), el = $('#pay-status');
    $('#g-sub').textContent = money(sub); $('#g-disc').textContent = '-' + money(sub - g); $('#g-total').textContent = money(g);
    el.className = 'paystat ' + st; el.textContent = g <= 0 && p <= 0 ? '' : (st === 'paid' ? PAY.paid : st === 'partial' ? `${PAY.partial} · នៅខ្វះ ${money(g - p)}` : PAY.unpaid);
  }
  $('#s-disc').addEventListener('input', totals); $('#s-paid').addEventListener('input', () => { paidTouched = true; totals(); });
  $$('[data-disc]').forEach(b => b.addEventListener('click', () => { $('#s-disc').value = b.dataset.disc; totals(); }));
  $('#pay-full').addEventListener('click', () => { $('#s-paid').value = grand().toFixed(2); paidTouched = true; totals(); });
  $('#pay-zero').addEventListener('click', () => { $('#s-paid').value = 0; paidTouched = true; totals(); });

  // ── search / results ───────────────────────────────────────────────────
  let results = [];
  function search() {
    const q = $('#it-search').value.toLowerCase().trim();
    results = (q ? ITEMS.filter(i => (i.code + ' ' + i.kh + ' ' + i.en).toLowerCase().includes(q)) : ITEMS).slice(0, 25);
    $('#results').innerHTML = results.map((i, n) => `<tr data-key="${i.id}" class="${n === 0 && q ? 'sel' : ''}"><td><b>${esc(i.code)}</b></td><td>${esc(i.kh || i.en)}</td><td class="num">${i.remain > 0 ? qty(i.remain) : '<span class="pill low">អស់ស្តុក</span>'}</td><td class="num">${money(priceFor(i))}</td></tr>`).join('') ||
      '<tr><td colspan="4" class="muted">រកមិនឃើញទំនិញ</td></tr>';
  }
  $('#it-search').addEventListener('input', UI.debounce(search, 100));
  $('#it-search').addEventListener('keydown', e => {
    if (e.key !== 'Enter') return; e.preventDefault(); const q = $('#it-search').value.trim().toLowerCase();
    const it = ITEMS.find(i => i.code.toLowerCase() === q) || results[0]; if (it) { add(it); $('#it-search').select(); }
  });
  $('#results').addEventListener('dblclick', e => { const tr = e.target.closest('tr[data-key]'); if (tr) add(byId.get(tr.dataset.key)); });
  $('#results').addEventListener('click', e => { const tr = e.target.closest('tr[data-key]'); if (tr) { $$('#results tr').forEach(r => r.classList.toggle('sel', r === tr)); } });

  function add(it) {
    const ex = cart.find(l => l.item_id === it.id), want = (ex ? ex.qty : 0) + 1;
    if (want > limit(it.id) + 1e-9) return alert(`ស្តុកមិនគ្រប់គ្រាន់សម្រាប់ "${it.code}" (សល់ ${qty(limit(it.id))})`);
    if (ex) ex.qty = want; else cart.push({item_id: it.id, code: it.code, name: it.kh || it.en, qty: 1, sell_price: priceFor(it), unit_price: costFor(it), manual: false});
    drawCart();
  }

  // ── cart ───────────────────────────────────────────────────────────────
  const csel = selectable($('#cart'), {onDouble: k => editLine(+k)});
  function drawCart() {
    $('#cart').innerHTML = cart.map((l, i) => `<tr data-key="${i}"><td><b>${esc(l.code)}</b></td><td>${esc(l.name)}</td><td class="num">${qty(l.qty)}</td><td class="num">${money(l.sell_price)}</td><td class="num">${money(l.qty * l.sell_price)}</td><td class="num"><button class="btn-x" data-del="${i}">✕</button></td></tr>`).join('') ||
      '<tr><td colspan="6" class="muted">កន្ត្រកទទេ</td></tr>';
    $('#cart-count').textContent = cart.length ? `(${cart.length} មុខ)` : ''; if (!paidTouched && !editing) $('#s-paid').value = 0; totals();
  }
  $('#cart').addEventListener('click', e => { const b = e.target.closest('[data-del]'); if (b) { cart.splice(+b.dataset.del, 1); drawCart(); } });
  document.addEventListener('keydown', e => { if (e.key === 'Delete' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) && !$('#p-new').hidden && csel.get().length) { cart.splice(+csel.get()[0], 1); drawCart(); } });
  function editLine(i) {
    const l = cart[i]; if (!l) return;
    modal({title: '✏ កែប្រែទំនិញ — ' + esc(l.code), width: 400, body: `<div class="fld"><label>បរិមាណ (អតិបរមា ${qty(limit(l.item_id))})</label><input id="e-q" type="number" step="any" min="0" value="${l.qty}"></div><div class="fld"><label>តម្លៃលក់ ($)</label><input id="e-p" type="number" step="any" min="0" value="${l.sell_price}"></div>` +
      (customer() !== GENERAL ? `<p class="small-note">តម្លៃនេះនឹងត្រូវរក្សាទុកជាតម្លៃពិសេសសម្រាប់ "${esc(customer())}"។</p>` : ''),
      enter: d => $('.btn:not(.sec)', d.el).click(), buttons: [{label: 'បោះបង់', cls: 'sec'}, {label: 'រក្សាទុក', cls: '', onClick: async d => {
        const q = num($('#e-q', d.el).value), p = num($('#e-p', d.el).value);
        if (q <= 0) { toast('បរិមាណត្រូវតែធំជាងសូន្យ។', 'error'); return false; }
        if (q > limit(l.item_id) + 1e-9) { toast(`ស្តុកមិនគ្រប់គ្រាន់ (សល់ ${qty(limit(l.item_id))})`, 'error'); return false; }
        l.qty = q; if (Math.abs(p - l.sell_price) > 1e-9) { l.sell_price = p; l.manual = true;
          if (customer() !== GENERAL) { await api('/api/sales/customer-price', {item_id: l.item_id, customer: customer(), price: p}); const it = byId.get(l.item_id), c = it.customers.find(x => x.name === customer()); if (c) c.price = p; else it.customers.push({name: customer(), price: p}); } }
        drawCart(); search(); }}]});
  }
  $('#s-cust').addEventListener('change', () => { cart.forEach(l => { if (!l.manual) l.sell_price = priceFor(byId.get(l.item_id)); }); drawCart(); search(); });

  // ── customers ──────────────────────────────────────────────────────────
  function setCustomers(names, select) {
    $('#s-cust').innerHTML = [GENERAL].concat(names).map(n => `<option>${esc(n)}</option>`).join(''); if (select) $('#s-cust').value = select;
  }
  $('#c-add').addEventListener('click', () => modal({title: '＋ បន្ថែមអតិថិជនថ្មី', width: 400, body: '<div class="fld"><label>ឈ្មោះអតិថិជន</label><input id="c-name"></div>',
    enter: d => $('.btn:not(.sec)', d.el).click(), buttons: [{label: 'បោះបង់', cls: 'sec'}, {label: 'រក្សាទុក', cls: '', onClick: async d => {
      const n = $('#c-name', d.el).value.trim(); await api('/api/customers', {name: n}); setCustomers(await api('/api/customers'), n); drawCart(); toast('បានបន្ថែមអតិថិជនរួចរាល់។'); }}]}));
  $('#c-ren').addEventListener('click', () => {
    const old = customer(); if (old === GENERAL) return alert(`'${GENERAL}' ជាអតិថិជនលំនាំដើមរបស់ប្រព័ន្ធ មិនអាចកែឈ្មោះបានទេ។`);
    modal({title: '✏ កែឈ្មោះអតិថិជន', width: 420, body: `<div class="fld"><label>ឈ្មោះបច្ចុប្បន្ន</label><input value="${esc(old)}" readonly></div><div class="fld"><label>ឈ្មោះថ្មី</label><input id="c-new" value="${esc(old)}"></div>
      <label style="display:flex;gap:8px;align-items:center;cursor:pointer"><input type="checkbox" id="c-inv" checked> ប្តូរឈ្មោះក្នុងវិក្កយបត្រចាស់ៗផងដែរ</label>`,
      enter: d => $('.btn:not(.sec)', d.el).click(), buttons: [{label: 'បោះបង់', cls: 'sec'}, {label: 'រក្សាទុក', cls: '', onClick: async d => {
        const n = $('#c-new', d.el).value.trim(); await api('/api/customers/rename', {old, new: n, update_invoices: $('#c-inv', d.el).checked});
        ITEMS.forEach(i => i.customers.forEach(c => { if (c.name === old) c.name = n; })); setCustomers(await api('/api/customers'), n); drawCart(); toast('បានកែឈ្មោះរួចរាល់។'); }}]});
  });

  // ── save / clear / edit ────────────────────────────────────────────────
  function reset() {
    cart = []; editing = null; allowed = {}; paidTouched = false; ['#s-s1', '#s-s2', '#s-r1', '#s-r2', '#s-note', '#it-search'].forEach(s => $(s).value = '');
    $('#s-disc').value = 0; $('#s-paid').value = 0; $('#s-cust').value = GENERAL; $('#s-date').value = new Date(Date.now() + 7 * 3600e3).toISOString().slice(0, 10);
    $('#edit-banner').hidden = true; $('#cancel-edit').hidden = true; $('#save').innerHTML = '💾 រក្សាទុក'; drawCart(); search();
  }
  $('#clear').addEventListener('click', async () => { if (!cart.length || await confirm('សម្អាតកន្ត្រកទំនិញទាំងអស់?')) reset(); });
  $('#cancel-edit').addEventListener('click', reset);
  async function save(print) {
    if (!cart.length) return alert('សូមបញ្ចូលទំនិញក្នុងកន្ត្រកជាមុនសិន!');
    const zero = cart.filter(l => l.sell_price <= 0).map(l => l.code);
    if (zero.length && !await confirm(`មុខទំនិញខាងក្រោមមិនទាន់មានតម្លៃលក់៖\n${zero.join(', ')}\nបន្តរក្សាទុកឬទេ?`)) return;
    if (num($('#s-paid').value) > grand() + 0.005 && !await confirm('ទឹកប្រាក់បានបង់ច្រើនជាងសរុបវិក្កយបត្រ។ បន្តរក្សាទុក?')) return;
    const w = print ? window.open('', '_blank') : null, btns = $$('#save,#save-print'); btns.forEach(b => b.disabled = true);
    try {
      const r = await api('/api/sales/save', {editing_code: editing, date: $('#s-date').value, customer: customer(), sender1: $('#s-s1').value, sender2: $('#s-s2').value,
        receiver1: $('#s-r1').value, receiver2: $('#s-r2').value, notes: $('#s-note').value, discount_percent: disc(), paid_amount: num($('#s-paid').value),
        items: cart.map(l => ({item_id: l.item_id, qty: l.qty, unit_price: l.unit_price, sell_price: l.sell_price}))});
      toast(r.editing ? `បានកែប្រែវិក្កយបត្រ ${r.code} រួចរាល់។` : `បានរក្សាទុកវិក្កយបត្រ ${r.code} រួចរាល់។`);
      if (w) w.location = `/sales/${encodeURIComponent(r.code)}/print`; setTimeout(() => { location.href = '/sales'; }, w ? 600 : 400);
    } catch (e) { if (w) w.close(); alert(e.message); } finally { btns.forEach(b => b.disabled = false); }
  }
  $('#save').addEventListener('click', () => save(false)); $('#save-print').addEventListener('click', () => save(true));

  async function loadForEdit(code) {
    const s = await api('/api/sales/' + encodeURIComponent(code)); editing = s.code; paidTouched = true; allowed = {};
    cart = s.lines.map(l => { allowed[l.item_id] = l.remain; return {item_id: l.item_id, code: l.code, name: l.name, qty: l.qty, sell_price: l.sell_price, unit_price: l.unit_price, manual: true}; });
    if (![...$('#s-cust').options].some(o => o.value === s.customer)) $('#s-cust').add(new Option(s.customer, s.customer));
    $('#s-cust').value = s.customer; $('#s-date').value = (s.date || '').slice(0, 10); $('#s-s1').value = s.sender1; $('#s-s2').value = s.sender2; $('#s-r1').value = s.receiver1; $('#s-r2').value = s.receiver2;
    $('#s-note').value = s.notes; $('#s-disc').value = s.discount_percent; $('#s-paid').value = s.paid;
    const b = $('#edit-banner'); b.hidden = false; b.textContent = `✏ កំពុងកែប្រែវិក្កយបត្រ៖ ${s.code}`; $('#cancel-edit').hidden = false; $('#save').innerHTML = '💾 រក្សាទុកការកែប្រែ'; drawCart(); search(); showTab('p-new');
  }

  // ── history ────────────────────────────────────────────────────────────
  const hsel = selectable($('#h-body'), {multi: true, onChange: k => showDetail(k.length === 1 ? k[0] : null), onDouble: k => UI.openPrint('/sales/' + encodeURIComponent(k) + '/print')});
  async function loadHistory() {
    const p = new URLSearchParams({search: $('#h-q').value.trim(), start: $('#h-start').value, end: $('#h-end').value, paid: $('#h-paid').value});
    HIST = await api('/api/sales/list?' + p); const keep = hsel.get();
    $('#h-body').innerHTML = HIST.map(r => `<tr data-key="${esc(r.code)}"><td><b>${esc(r.code)}</b></td><td>${esc(r.customer)}</td><td class="c">${r.discount > 0 ? r.discount + '%' : '–'}</td><td class="num">${money(r.total)}</td><td class="num">${money(r.paid)}</td><td class="num" style="color:${r.balance > 0.005 ? 'var(--bad)' : 'inherit'}">${money(r.balance)}</td><td>${payPill(r.state, r.label)}</td><td>${dmy(r.date)}</td></tr>`).join('') ||
      '<tr><td colspan="8" class="muted">មិនមានទិន្នន័យ</td></tr>';
    hsel.set(keep.filter(k => HIST.some(r => r.code === k))); $('#h-count').textContent = `${HIST.length} វិក្កយបត្រ`;
  }
  async function showDetail(code) {
    curDetail = code; if (!code) { $('#d-body').innerHTML = '<tr><td colspan="5" class="muted">ជ្រើសរើសវិក្កយបត្រ</td></tr>'; $('#d-title').textContent = 'មុខទំនិញក្នុងវិក្កយបត្រ'; return; }
    const s = await api('/api/sales/' + encodeURIComponent(code)); if (curDetail !== code) return;
    $('#d-title').textContent = `${s.code} — ${s.customer}`;
    $('#d-body').innerHTML = s.lines.map(l => `<tr><td>${esc(l.code)}</td><td>${esc(l.name)}</td><td class="num">${qty(l.qty)}</td><td class="num">${money(l.sell_price)}</td><td class="num">${money(l.qty * l.sell_price)}</td></tr>`).join('');
  }
  $('#h-load').addEventListener('click', loadHistory); $('#h-q').addEventListener('keydown', e => { if (e.key === 'Enter') loadHistory(); });
  ['#h-start', '#h-end', '#h-paid'].forEach(s => $(s).addEventListener('change', loadHistory));
  $('#h-summary').addEventListener('click', () => UI.summaryDialog('sales', $('#h-start').value, $('#h-end').value, 'អតិថិជន'));
  const one = () => { const k = hsel.get(); if (k.length !== 1) { alert('សូមជ្រើសរើសវិក្កយបត្រតែមួយជាមុនសិន។'); return null; } return k[0]; };
  $('#a-print').addEventListener('click', () => { const c = one(); c && UI.openPrint('/sales/' + encodeURIComponent(c) + '/print'); });
  $('#a-edit').addEventListener('click', async () => { const c = one(); if (!c) return; if (cart.length && !editing && !await confirm('កន្ត្រកបច្ចុប្បន្ននឹងត្រូវជំនួស។ បន្ត?')) return; loadForEdit(c); });
  $('#a-pay').addEventListener('click', async () => { const c = one(); if (!c) return; const s = await api('/api/sales/' + encodeURIComponent(c)); UI.paymentDialog('sales', s, ['អតិថិជន', s.customer], loadHistory); });
  $('#a-paid').addEventListener('click', async () => {
    const k = hsel.get(); if (!k.length) return alert('សូមជ្រើសរើសវិក្កយបត្រជាមុនសិន។'); if (!await confirm(`ដាក់វិក្កយបត្រចំនួន ${k.length} ថាបានទូទាត់ពេញ?`)) return;
    const r = await api('/api/sales/mark-paid', {codes: k}); toast(`បានធ្វើបច្ចុប្បន្នភាព ${r.count} វិក្កយបត្រ។`); loadHistory(); });
  $('#a-del').addEventListener('click', async () => {
    const c = one(); if (!c) return; if (!await confirm(`លុបវិក្កយបត្រ ${c}?\nស្តុកនឹងត្រូវបន្ថែមត្រឡប់មកវិញ។`, {danger: true, yes: 'លុប'})) return;
    await api('/api/sales/' + encodeURIComponent(c) + '/delete', {}); toast('បានលុបរួចរាល់។'); if (editing === c) reset(); loadHistory(); showDetail(null); });

  drawCart(); search(); if (VIEW) { showTab('p-hist'); loadHistory().then(() => hsel.set([VIEW])); }
})();
