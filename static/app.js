/* Shared line-item editor for Receive / Sale / Transfer pages. */
(function () {
  const dataEl = document.getElementById('items-data');
  if (!dataEl) return;
  const ITEMS = JSON.parse(dataEl.textContent);
  const mode = document.body.dataset.mode;           // receive | sale | transfer
  const SUPPLIERS = JSON.parse((document.getElementById('suppliers-data') || {textContent: '[]'}).textContent);
  const $ = (s, r = document) => r.querySelector(s);
  const money = n => '$' + (Number(n) || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const label = i => [i.code, i.kh, i.en].filter(Boolean).join(' | ');
  const byLabel = new Map(ITEMS.map(i => [label(i), i]));
  const byId = new Map(ITEMS.map(i => [i.id, i]));

  $('#itemlist').innerHTML = ITEMS.map(i => `<option value="${label(i).replace(/"/g, '&quot;')}">`).join('');
  const tbody = $('#lines tbody');

  const costFor = (it, dist) => {
    const d = it.distributors.find(x => x.name === dist);
    return d ? d.cost : (it.unit_price || it.min_cost || 0);
  };
  const sellFor = (it, cust) => {
    const c = cust && it.customers.find(x => x.name === cust);
    return c ? c.price : it.sell_price;
  };
  const header = id => (($(id) || {}).value || '').trim();

  function rowHTML() {
    const q = '<td><input class="f-qty" type="number" min="0" step="any" value="1"></td>';
    const item = '<td><input class="f-item" list="itemlist" placeholder="Search code / name…"></td><td class="f-stock muted num">–</td>';
    const tail = '<td class="f-total num">$0.00</td><td><button type="button" class="btn-x" title="Remove">✕</button></td>';
    if (mode === 'receive')
      return item + q + '<td><input class="f-price" type="number" min="0" step="any" value="0"></td>' + tail;
    if (mode === 'sale')
      return item + q + '<td><input class="f-cost" type="number" min="0" step="any" value="0"></td>' +
             '<td><input class="f-price" type="number" min="0" step="any" value="0"></td>' + tail;
    return item + q + '<td><input class="f-price" type="number" min="0" step="any" value="0"></td>' +
           '<td><select class="f-supplier"></select></td><td><input class="f-remark" placeholder="Remark"></td>' + tail;
  }

  function addRow() {
    const tr = document.createElement('tr');
    tr.innerHTML = rowHTML();
    tbody.appendChild(tr);
    $('.f-item', tr).focus();
    return tr;
  }

  function fillSuppliers(tr, it) {
    const sel = $('.f-supplier', tr); if (!sel) return;
    const own = it.distributors.map(d => d.name);
    const rest = SUPPLIERS.filter(s => !own.includes(s));
    sel.innerHTML = '<option value="">—</option>' +
      own.map(s => `<option>${s}</option>`).join('') +
      (rest.length ? '<optgroup label="Other">' + rest.map(s => `<option>${s}</option>`).join('') + '</optgroup>' : '');
    if (own.length === 1) sel.value = own[0];
  }

  function applyDefaults(tr, it, force) {
    const price = $('.f-price', tr);
    if (!force && price.dataset.manual) return;
    if (mode === 'receive') price.value = costFor(it, header('#distributor'));
    if (mode === 'sale') { price.value = sellFor(it, header('#customer')); }
    if (mode === 'transfer') {
      const sup = $('.f-supplier', tr).value;
      price.value = costFor(it, sup);
    }
  }

  function chooseItem(tr, it) {
    if (mode === 'sale' && [...tbody.rows].some(r => r !== tr && r.dataset.id === it.id)) {
      alert('That item is already on this invoice.'); $('.f-item', tr).value = ''; return;
    }
    tr.dataset.id = it.id;
    $('.f-stock', tr).textContent = it.remain;
    if (mode === 'sale') $('.f-cost', tr).value = it.unit_price || it.min_cost || 0;
    if (mode === 'transfer') fillSuppliers(tr, it);
    delete $('.f-price', tr).dataset.manual;
    applyDefaults(tr, it, true);
    recalc();
  }

  function recalc() {
    let sum = 0;
    [...tbody.rows].forEach(tr => {
      const t = (+$('.f-qty', tr).value || 0) * (+$('.f-price', tr).value || 0);
      $('.f-total', tr).textContent = money(t); sum += t;
    });
    $('#grand').textContent = money(sum);
  }

  tbody.addEventListener('change', e => {
    const tr = e.target.closest('tr');
    if (e.target.classList.contains('f-item')) {
      const it = byLabel.get(e.target.value) ||
        ITEMS.find(i => i.code.toLowerCase() === e.target.value.trim().toLowerCase());
      if (it) { e.target.value = label(it); chooseItem(tr, it); }
      else { delete tr.dataset.id; $('.f-stock', tr).textContent = '–'; }
    }
    if (e.target.classList.contains('f-supplier') && tr.dataset.id) {
      delete $('.f-price', tr).dataset.manual;
      applyDefaults(tr, byId.get(tr.dataset.id), true); recalc();
    }
  });
  tbody.addEventListener('input', e => {
    if (e.target.classList.contains('f-price')) e.target.dataset.manual = '1';
    recalc();
  });
  tbody.addEventListener('click', e => {
    if (e.target.classList.contains('btn-x')) { e.target.closest('tr').remove(); recalc(); }
  });
  const refreshAll = () => { [...tbody.rows].forEach(tr => tr.dataset.id && applyDefaults(tr, byId.get(tr.dataset.id))); recalc(); };
  ['#distributor', '#customer'].forEach(s => $(s) && $(s).addEventListener('change', refreshAll));

  $('#add-row').addEventListener('click', addRow);
  $('#save').addEventListener('click', async () => {
    const lines = [...tbody.rows].filter(tr => tr.dataset.id).map(tr => {
      const o = {item_id: tr.dataset.id, qty: $('.f-qty', tr).value};
      if (mode === 'receive') o.price = $('.f-price', tr).value;
      if (mode === 'sale') { o.unit_price = $('.f-cost', tr).value; o.sell_price = $('.f-price', tr).value; }
      if (mode === 'transfer') { o.unit_cost = $('.f-price', tr).value; o.supplier = $('.f-supplier', tr).value; o.remark = $('.f-remark', tr).value; }
      return o;
    });
    const payload = {items: lines};
    document.querySelectorAll('[data-field]').forEach(el => payload[el.dataset.field] = el.value);
    if (mode === 'sale') {
      const over = [...tbody.rows].filter(tr => tr.dataset.id && (+$('.f-qty', tr).value > +$('.f-stock', tr).textContent));
      if (over.length && !confirm(over.length + ' line(s) exceed available stock. Save anyway?')) return;
    }
    const btn = $('#save'); btn.disabled = true; btn.textContent = 'Saving…';
    try {
      const res = await fetch(location.pathname, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
      const j = await res.json();
      if (j.ok) location.href = j.redirect; else { alert(j.error || 'Could not save.'); }
    } catch (err) { alert('Network error: ' + err); }
    btn.disabled = false; btn.textContent = 'Save';
  });
  addRow();
})();
