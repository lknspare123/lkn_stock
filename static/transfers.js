/* Branch transfers — mirrors the desktop BranchTransferPage (cost resolver, per-line supplier/sell/remark, payments, history). */
(function () {
  const {$, $$, esc, num, money, qty, dmy, api, toast, modal, confirm, alert, selectable, payState, payPill, PAY} = UI;
  const ITEMS = JSON.parse($('#items-data').textContent), VIEW = JSON.parse($('#view-data').textContent);
  const byId = new Map(ITEMS.map(i => [i.id, i]));
  let cart = [], editing = null, allowed = {}, paidTouched = false, HIST = [], curDetail = null;
  const showTab = UI.tabs($('#root'), id => { if (id === 'p-hist') loadHistory(); });
  const limit = id => allowed[id] ?? (byId.get(id) || {}).remain ?? 0;
  const costOf = async (id, supplier) => api('/api/transfers/cost?item_id=' + id + (supplier ? '&supplier=' + encodeURIComponent(supplier) : ''));

  const total = () => cart.reduce((s, l) => s + l.qty * l.unit_cost, 0);
  function totals() {
    const t = total(), p = num($('#t-paid').value), st = payState(t, p), el = $('#pay-status');
    $('#g-total').textContent = money(t); el.className = 'paystat ' + st;
    el.textContent = t <= 0 && p <= 0 ? '' : (st === 'paid' ? PAY.paid : st === 'partial' ? `${PAY.partial} · នៅខ្វះ ${money(t - p)}` : PAY.unpaid);
  }
  $('#t-paid').addEventListener('input', () => { paidTouched = true; totals(); });
  $('#pay-full').addEventListener('click', () => { $('#t-paid').value = total().toFixed(2); paidTouched = true; totals(); });
  $('#pay-zero').addEventListener('click', () => { $('#t-paid').value = 0; paidTouched = true; totals(); });

  // ── search ─────────────────────────────────────────────────────────────
  let results = [];
  function search() {
    const q = $('#it-search').value.toLowerCase().trim();
    results = (q ? ITEMS.filter(i => (i.code + ' ' + i.kh + ' ' + i.en).toLowerCase().includes(q)) : ITEMS).slice(0, 25);
    $('#results').innerHTML = results.map((i, n) => `<tr data-key="${i.id}" class="${n === 0 && q ? 'sel' : ''}"><td><b>${esc(i.code)}</b></td><td>${esc(i.kh || i.en)}</td><td class="num">${i.remain > 0 ? qty(i.remain) : '<span class="pill low">អស់ស្តុក</span>'}</td><td class="num">${i.cost_lo == null ? '–' : money(i.cost_lo)}</td></tr>`).join('') ||
      '<tr><td colspan="4" class="muted">រកមិនឃើញទំនិញ</td></tr>';
  }
  $('#it-search').addEventListener('input', UI.debounce(search, 100));
  $('#it-search').addEventListener('keydown', e => { if (e.key !== 'Enter') return; e.preventDefault(); const q = $('#it-search').value.trim().toLowerCase(); const it = ITEMS.find(i => i.code.toLowerCase() === q) || results[0]; if (it) { add(it); $('#it-search').select(); } });
  $('#results').addEventListener('dblclick', e => { const tr = e.target.closest('tr[data-key]'); if (tr) add(byId.get(tr.dataset.key)); });
  $('#results').addEventListener('click', e => { const tr = e.target.closest('tr[data-key]'); if (tr) $$('#results tr').forEach(r => r.classList.toggle('sel', r === tr)); });

  async function add(it) {
    const ex = cart.find(l => l.item_id === it.id), want = (ex ? ex.qty : 0) + 1;
    if (want > limit(it.id) + 1e-9) return alert(`ស្តុកមិនគ្រប់គ្រាន់សម្រាប់ "${it.code}" (សល់ ${qty(limit(it.id))})`);
    if (ex) { ex.qty = want; return drawCart(); }
    let c = {cost: 0, supplier: ''}; try { c = await costOf(it.id); } catch (e) {}
    cart.push({item_id: it.id, code: it.code, name: it.kh || it.en, qty: 1, unit_cost: c.cost, sell_price: it.sell_price || c.cost, supplier: c.supplier, remark: ''});
    drawCart();
  }

  // ── cart ───────────────────────────────────────────────────────────────
  selectable($('#cart'), {onDouble: k => editLine(+k)});
  function drawCart() {
    $('#cart').innerHTML = cart.map((l, i) => `<tr data-key="${i}"><td><b>${esc(l.code)}</b></td><td>${esc(l.name)}</td><td class="num">${qty(l.qty)}</td><td class="num" style="${l.unit_cost <= 0 ? 'color:var(--bad)' : ''}">${money(l.unit_cost)}</td><td class="num">${money(l.sell_price)}</td><td>${esc(l.supplier) || '–'}</td><td>${esc(l.remark) || '–'}</td><td class="num">${money(l.qty * l.unit_cost)}</td><td class="num"><button class="btn-x" data-del="${i}">✕</button></td></tr>`).join('') ||
      '<tr><td colspan="9" class="muted">កន្ត្រកទទេ</td></tr>';
    $('#cart-count').textContent = cart.length ? `(${cart.length} មុខ)` : ''; if (!paidTouched && !editing) $('#t-paid').value = 0; totals();
  }
  $('#cart').addEventListener('click', e => { const b = e.target.closest('[data-del]'); if (b) { cart.splice(+b.dataset.del, 1); drawCart(); } });
  $('#refresh-prices').addEventListener('click', async () => {
    if (!cart.length) return; let n = 0;
    for (const l of cart) { const c = await costOf(l.item_id, l.supplier); if (c.cost > 0 && c.cost !== l.unit_cost) { l.unit_cost = c.cost; if (!l.supplier) l.supplier = c.supplier; n++; } }
    drawCart(); toast(n ? `បានធ្វើបច្ចុប្បន្នភាពថ្លៃដើម ${n} មុខ។` : 'ថ្លៃដើមត្រូវបានធ្វើបច្ចុប្បន្នភាពរួចហើយ។');
  });
  async function editLine(i) {
    const l = cart[i]; if (!l) return; let sup = []; try { sup = await api('/api/transfers/suppliers?item_id=' + l.item_id); } catch (e) {}
    const m = modal({title: '✏ កែប្រែទំនិញ — ' + esc(l.code), width: 480, body: `<div class="row2"><div class="fld"><label>បរិមាណ (អតិបរមា ${qty(limit(l.item_id))})</label><input id="e-q" type="number" step="any" min="0" value="${l.qty}"></div>
      <div class="fld"><label>ថ្លៃដើម/ឯកតា ($)</label><input id="e-c" type="number" step="any" min="0" value="${l.unit_cost}"></div></div>
      <div class="row2"><div class="fld"><label>តម្លៃលក់/ឯកតា ($)</label><input id="e-s" type="number" step="any" min="0" value="${l.sell_price}"></div>
      <div class="fld"><label>អ្នកផ្គត់ផ្គង់</label><input id="e-sup" list="e-sl" value="${esc(l.supplier)}"><datalist id="e-sl">${sup.map(s => `<option value="${esc(s)}">`).join('')}</datalist></div></div>
      <div class="fld"><label>កំណត់សម្គាល់</label><input id="e-r" value="${esc(l.remark)}"></div>
      <button type="button" class="btn sec sm" id="e-latest">↻ ប្រើថ្លៃដើមចុងក្រោយតាមអ្នកផ្គត់ផ្គង់</button>`,
      enter: d => $('.btn:not(.sec)', d.el).click(), buttons: [{label: 'បោះបង់', cls: 'sec'}, {label: 'រក្សាទុក', cls: '', onClick: d => {
        const q = num($('#e-q', d.el).value); if (q <= 0) { toast('បរិមាណត្រូវតែធំជាងសូន្យ។', 'error'); return false; }
        if (q > limit(l.item_id) + 1e-9) { toast(`ស្តុកមិនគ្រប់គ្រាន់ (សល់ ${qty(limit(l.item_id))})`, 'error'); return false; }
        Object.assign(l, {qty: q, unit_cost: num($('#e-c', d.el).value), sell_price: num($('#e-s', d.el).value), supplier: $('#e-sup', d.el).value.trim(), remark: $('#e-r', d.el).value.trim()}); drawCart(); }}]});
    $('#e-latest', m.el).addEventListener('click', async () => {
      const c = await costOf(l.item_id, $('#e-sup', m.el).value.trim()); if (c.cost > 0) { $('#e-c', m.el).value = c.cost; if (!$('#e-sup', m.el).value.trim()) $('#e-sup', m.el).value = c.supplier; } else toast('រកមិនឃើញថ្លៃដើមសម្រាប់អ្នកផ្គត់ផ្គង់នេះទេ។', 'error'); });
    $('#e-sup', m.el).addEventListener('change', async () => { const s = $('#e-sup', m.el).value.trim(); if (!s) return; const c = await costOf(l.item_id, s); if (c.cost > 0) $('#e-c', m.el).value = c.cost; });
  }

  // ── branches ───────────────────────────────────────────────────────────
  async function reloadBranches(sel) {
    const bs = await api('/api/branches'); $('#t-branch').innerHTML = '<option value="">— ជ្រើសរើសសាខា —</option>' + bs.map(b => `<option>${esc(b.name)}</option>`).join(''); if (sel) $('#t-branch').value = sel; return bs;
  }
  $('#b-manage').addEventListener('click', async () => {
    const m = modal({title: '⚙ គ្រប់គ្រងសាខា', width: 460, sticky: true, body: '<div id="bl"></div><div style="display:flex;gap:8px;margin-top:12px"><input id="b-new" placeholder="ឈ្មោះសាខាថ្មី" style="flex:1"><button class="btn" id="b-add">＋ បន្ថែម</button></div>', buttons: [{label: 'បិទ', cls: ''}]});
    const draw = async () => { const bs = await reloadBranches($('#t-branch').value); $('#bl', m.el).innerHTML = '<div class="tw short"><table><tbody>' + bs.map(b => `<tr><td>${esc(b.name)}</td><td class="num"><button class="btn-x" data-id="${b.id}">🗑</button></td></tr>`).join('') + '</tbody></table></div>';
      $$('[data-id]', m.el).forEach(x => x.addEventListener('click', async () => { if (await confirm('លុបសាខានេះ?', {danger: true, yes: 'លុប'})) { await api('/api/branches/' + x.dataset.id + '/delete', {}); draw(); } })); };
    $('#b-add', m.el).addEventListener('click', async () => { try { await api('/api/branches', {name: $('#b-new', m.el).value}); $('#b-new', m.el).value = ''; draw(); } catch (e) { toast(e.message, 'error'); } }); draw();
  });

  // ── save / clear / edit ────────────────────────────────────────────────
  function reset() {
    cart = []; editing = null; allowed = {}; paidTouched = false; ['#t-driver', '#t-note', '#it-search'].forEach(s => $(s).value = ''); $('#t-paid').value = 0; $('#t-branch').value = '';
    $('#t-date').value = new Date(Date.now() + 7 * 3600e3).toISOString().slice(0, 10); $('#edit-banner').hidden = true; $('#cancel-edit').hidden = true; $('#save').innerHTML = '💾 រក្សាទុក'; drawCart(); search();
  }
  $('#clear').addEventListener('click', async () => { if (!cart.length || await confirm('សម្អាតកន្ត្រកទំនិញទាំងអស់?')) reset(); });
  $('#cancel-edit').addEventListener('click', reset);
  async function save(print) {
    if (!cart.length) return alert('សូមស្វែងរក/ជ្រើសរើសមុខទំនិញចូលទៅក្នុងកន្ត្រកជាមុនសិន!');
    if (!$('#t-branch').value) return alert('សូមជ្រើសរើសសាខាគោលដៅ!');
    const zero = cart.filter(l => l.unit_cost <= 0).map(l => l.code);
    if (zero.length && !await confirm(`មុខទំនិញខាងក្រោមមិនទាន់មានថ្លៃដើម៖\n${zero.join(', ')}\nបន្តរក្សាទុកឬទេ?`)) return;
    if (num($('#t-paid').value) > total() + 0.005 && !await confirm('ទឹកប្រាក់បានបង់ច្រើនជាងសរុប។ បន្តរក្សាទុក?')) return;
    const w = print ? window.open('', '_blank') : null, btns = $$('#save,#save-print'); btns.forEach(b => b.disabled = true);
    try {
      const r = await api('/api/transfers/save', {editing_code: editing, branch: $('#t-branch').value, date: $('#t-date').value, driver: $('#t-driver').value, note: $('#t-note').value, paid_amount: num($('#t-paid').value),
        items: cart.map(l => ({item_id: l.item_id, qty: l.qty, unit_cost: l.unit_cost, sell_price: l.sell_price, supplier: l.supplier, remark: l.remark}))});
      toast(r.editing ? `បានកែប្រែប័ណ្ណ ${r.code} រួចរាល់។` : `បានរក្សាទុកប័ណ្ណ ${r.code} រួចរាល់។`);
      if (w) w.location = `/transfers/${encodeURIComponent(r.code)}/print`; setTimeout(() => { location.href = '/transfers'; }, w ? 600 : 400);
    } catch (e) { if (w) w.close(); alert(e.message); } finally { btns.forEach(b => b.disabled = false); }
  }
  $('#save').addEventListener('click', () => save(false)); $('#save-print').addEventListener('click', () => save(true));

  async function loadForEdit(code) {
    const t = await api('/api/transfers/' + encodeURIComponent(code)); editing = t.code; paidTouched = true; allowed = {};
    cart = t.lines.map(l => { allowed[l.item_id] = l.remain; return {item_id: l.item_id, code: l.code, name: l.name, qty: l.qty, unit_cost: l.unit_cost, sell_price: l.sell_price, supplier: l.supplier, remark: l.remark}; });
    if (![...$('#t-branch').options].some(o => o.value === t.branch)) $('#t-branch').add(new Option(t.branch, t.branch));
    $('#t-branch').value = t.branch; $('#t-date').value = (t.date || '').slice(0, 10); $('#t-driver').value = t.driver; $('#t-note').value = t.note; $('#t-paid').value = t.paid;
    const b = $('#edit-banner'); b.hidden = false; b.textContent = `✏ កំពុងកែប្រែប័ណ្ណផ្ទេរ៖ ${t.code}`; $('#cancel-edit').hidden = false; $('#save').innerHTML = '💾 រក្សាទុកការកែប្រែ'; drawCart(); search(); showTab('p-new');
  }

  // ── history ────────────────────────────────────────────────────────────
  const hsel = selectable($('#h-body'), {multi: true, onChange: k => showDetail(k.length === 1 ? k[0] : null), onDouble: k => UI.openPrint('/transfers/' + encodeURIComponent(k) + '/print')});
  async function loadHistory() {
    const p = new URLSearchParams({search: $('#h-q').value.trim(), start: $('#h-start').value, end: $('#h-end').value, paid: $('#h-paid').value});
    HIST = await api('/api/transfers/list?' + p); const keep = hsel.get();
    $('#h-body').innerHTML = HIST.map(r => `<tr data-key="${esc(r.code)}"><td><b>${esc(r.code)}</b></td><td>${esc(r.branch)}</td><td>${esc(r.driver) || '–'}</td><td class="num">${money(r.total)}</td><td class="num">${money(r.paid)}</td><td class="num" style="color:${r.balance > 0.005 ? 'var(--bad)' : 'inherit'}">${money(r.balance)}</td><td>${payPill(r.state, r.label)}</td><td>${dmy(r.date)}</td></tr>`).join('') ||
      '<tr><td colspan="8" class="muted">មិនមានទិន្នន័យ</td></tr>';
    hsel.set(keep.filter(k => HIST.some(r => r.code === k))); $('#h-count').textContent = `${HIST.length} ប័ណ្ណ`;
  }
  async function showDetail(code) {
    curDetail = code; if (!code) { $('#d-body').innerHTML = '<tr><td colspan="7" class="muted">ជ្រើសរើសប័ណ្ណ</td></tr>'; $('#d-title').textContent = 'មុខទំនិញក្នុងប័ណ្ណ'; return; }
    const t = await api('/api/transfers/' + encodeURIComponent(code)); if (curDetail !== code) return; $('#d-title').textContent = `${t.code} — ${t.branch}`;
    $('#d-body').innerHTML = t.lines.map(l => `<tr><td>${esc(l.code)}</td><td>${esc(l.name)}</td><td class="num">${qty(l.qty)}</td><td class="num">${money(l.unit_cost)}</td><td class="num">${money(l.sell_price)}</td><td>${esc(l.supplier) || '–'}</td><td>${esc(l.remark) || '–'}</td></tr>`).join('');
  }
  $('#h-load').addEventListener('click', loadHistory); $('#h-q').addEventListener('keydown', e => { if (e.key === 'Enter') loadHistory(); });
  ['#h-start', '#h-end', '#h-paid'].forEach(s => $(s).addEventListener('change', loadHistory));
  $('#h-summary').addEventListener('click', () => UI.summaryDialog('transfers', $('#h-start').value, $('#h-end').value, 'សាខា'));
  const one = () => { const k = hsel.get(); if (k.length !== 1) { alert('សូមជ្រើសរើសប័ណ្ណតែមួយជាមុនសិន។'); return null; } return k[0]; };
  $('#a-print').addEventListener('click', () => { const c = one(); c && UI.openPrint('/transfers/' + encodeURIComponent(c) + '/print'); });
  $('#a-edit').addEventListener('click', async () => { const c = one(); if (!c) return; if (cart.length && !editing && !await confirm('កន្ត្រកបច្ចុប្បន្ននឹងត្រូវជំនួស។ បន្ត?')) return; loadForEdit(c); });
  $('#a-pay').addEventListener('click', async () => { const c = one(); if (!c) return; const t = await api('/api/transfers/' + encodeURIComponent(c)); UI.paymentDialog('transfers', t, ['សាខា', t.branch], loadHistory); });
  $('#a-paid').addEventListener('click', async () => {
    const k = hsel.get(); if (!k.length) return alert('សូមជ្រើសរើសប័ណ្ណជាមុនសិន។'); if (!await confirm(`ដាក់ប័ណ្ណចំនួន ${k.length} ថាបានទូទាត់ពេញ?`)) return;
    const r = await api('/api/transfers/mark-paid', {codes: k}); toast(`បានធ្វើបច្ចុប្បន្នភាព ${r.count} ប័ណ្ណ។`); loadHistory(); });
  $('#a-del').addEventListener('click', async () => {
    const c = one(); if (!c) return; if (!await confirm(`លុបប័ណ្ណផ្ទេរ ${c}?\nស្តុកនឹងត្រូវបន្ថែមត្រឡប់មកវិញ។`, {danger: true, yes: 'លុប'})) return;
    await api('/api/transfers/' + encodeURIComponent(c) + '/delete', {}); toast('បានលុបរួចរាល់។'); if (editing === c) reset(); loadHistory(); showDetail(null); });

  drawCart(); search(); if (VIEW) { showTab('p-hist'); loadHistory().then(() => hsel.set([VIEW])); }
})();
