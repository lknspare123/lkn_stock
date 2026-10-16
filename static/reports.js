/* Reports — stock / receives / sales / transfers / distributors / customers / branches (+ profit), Excel export, detail pop-ups. */
(function () {
  const {$, $$, esc, money, qty, dmy, api, toast, modal, selectable, openPrint} = UI;
  let tab = 'stock', DATA = null;
  const GROUPS = ['distributors', 'customers', 'branches'], PRINTABLE = {receives: 'receive', sales: 'sales', transfers: 'transfers'};
  const sel = selectable($('#r-body'), {onDouble: () => (GROUPS.includes(tab) ? detail() : viewInvoice())});
  const params = () => new URLSearchParams({start: $('#r-start').value, end: $('#r-end').value, paid: $('#r-paid').value});

  async function load() {
    $('#r-sum').className = 'sumbox accent'; $('#r-sum').textContent = 'កំពុងផ្ទុក…';
    DATA = await api(`/api/reports/${tab}?${params()}`);
    $('#r-sum').textContent = DATA.summary; $('#r-sum').className = 'sumbox ' + (DATA.level || 'accent');
    $('#r-head').innerHTML = DATA.cols.map(c => `<th class="${c[2] === 'e' ? 'num' : c[2] === 'c' ? 'c' : ''}">${esc(c[1])}</th>`).join('');
    $('#r-body').innerHTML = DATA.rows.map((r, i) => `<tr data-key="${i}">` + DATA.cols.map(c => `<td class="${c[2] === 'e' ? 'num' : c[2] === 'c' ? 'c' : ''}">${esc(r[c[0]])}</td>`).join('') + '</tr>').join('') ||
      `<tr><td colspan="${DATA.cols.length}" class="muted">មិនមានទិន្នន័យ</td></tr>`;
    sel.clear(); toolbar();
  }
  function toolbar() {
    const isStock = tab === 'stock';
    $('#r-start').disabled = $('#r-end').disabled = isStock; $('#r-paid').disabled = isStock || ['stock', 'profit'].includes(tab);
    $('#r-view').hidden = !PRINTABLE[tab]; $('#r-detail').hidden = !GROUPS.includes(tab);
    $('#r-hint').textContent = GROUPS.includes(tab) ? 'ចុចទ្វេដងលើជួរ ដើម្បីមើលវិក្កយបត្រ និងមុខទំនិញលម្អិត' : PRINTABLE[tab] ? 'ជ្រើសរើសជួរ រួចចុច «មើលវិក្កយបត្រ» (ឬចុចទ្វេដង)' : '';
    $('#export').href = `/reports/export?tab=${tab}&${params()}`;
  }
  $('#tabs').addEventListener('click', e => { const b = e.target.closest('.ptab'); if (!b) return; tab = b.dataset.t; $$('.ptab').forEach(x => x.classList.toggle('on', x === b)); load(); });
  $('#r-go').addEventListener('click', load); ['#r-start', '#r-end', '#r-paid'].forEach(s => $(s).addEventListener('change', load));
  ['#r-start', '#r-end', '#r-paid'].forEach(s => $(s).addEventListener('change', toolbar));
  $('#r-print').addEventListener('click', () => window.print());
  $('#export').addEventListener('click', toolbar);

  const row = () => { const k = sel.get()[0]; return k == null ? null : DATA.rows[+k]; };
  function viewInvoice() {
    const r = row(); if (!r) return UI.alert('សូមជ្រើសរើសជួរជាមុនសិន។');
    const path = {receives: 'receive', sales: 'sales', transfers: 'transfers'}[tab]; if (path) openPrint(`/${path}/${encodeURIComponent(r._code)}/print`);
  }
  $('#r-view').addEventListener('click', viewInvoice);

  async function detail() {
    const r = row(); if (!r) return UI.alert('សូមជ្រើសរើសជួរជាមុនសិន។');
    const p = params(); p.set('name', r._name);
    const g = await api(`/api/reports/group/${tab}?${p}`);
    const html = `<div class="kpi" style="margin-bottom:12px"><div><small>វិក្កយបត្រ</small><div class="big">${g.invoice_count}</div></div><div><small>សរុប</small><div class="big">${money(g.total)}</div></div>
      <div><small>បានទូទាត់</small><div class="big" style="color:var(--ok)">${money(g.paid)}</div></div><div><small>មិនទាន់ទូទាត់</small><div class="big" style="color:var(--bad)">${money(g.unpaid)}</div></div></div>` +
      g.invoices.map(iv => `<div class="card flat" style="padding:12px;margin-bottom:10px"><div class="chead" style="margin-bottom:6px"><b>${esc(g.info.code_label)} ${esc(iv.code)} · ${dmy(iv.date)}</b><span>${esc(iv.status)} · <b>${money(iv.total)}</b></span></div>
        <table><thead><tr><th>កូដ</th><th>ឈ្មោះ</th><th class="num">បរិមាណ</th><th class="num">${esc(g.info.price_label)}</th><th class="num">សរុប</th></tr></thead><tbody>` +
        iv.lines.map(l => `<tr><td>${esc(l.item_code)}</td><td>${esc(l.name)}</td><td class="num">${qty(l.qty)}</td><td class="num">${money(l.price)}</td><td class="num">${money(l.total)}</td></tr>`).join('') + '</tbody></table></div>').join('');
    modal({title: `${g.info.icon} ${esc(g.info.entity)}៖ ${esc(g.name)}`, width: 860, body: html, buttons: [
      {label: '🖨 បោះពុម្ព / PDF', cls: 'sec', close: false, onClick: () => openPrint(`/reports/group/print?kind=${tab}&${p}`)}, {label: 'បិទ', cls: ''}]});
  }
  $('#r-detail').addEventListener('click', detail);
  load();
})();
