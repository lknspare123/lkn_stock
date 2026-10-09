/* Main Stock — master/detail view (client-side search, sort, filter, detail panel). */
(function () {
  const D = JSON.parse(document.getElementById('stock-data').textContent);
  const ROWS = D.rows;
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const money = n => '$' + Number(n || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const qty = n => { n = Number(n || 0); return Number.isInteger(n) ? n.toLocaleString() : n.toLocaleString(undefined, {maximumFractionDigits: 2}); };
  const dmy = d => /^\d{4}-\d\d-\d\d/.test(d || '') ? d.slice(8, 10) + '/' + d.slice(5, 7) + '/' + d.slice(0, 4) : (d || '–');
  const range = (a, b) => a == null ? '–' : (a === b ? money(a) : money(a) + ' – ' + money(b));

  ROWS.forEach(r => {
    r.suppliers = r.distributors.map(d => d.name).join(', ');
    r.unitTxt = range(r.u0, r.u1); r.sellTxt = range(r.s0, r.s1);
    r.blob = [r.code, r.kh, r.en, r.suppliers, r.floor, r.corner].join(' ').toLowerCase();
  });

  // key, Khmer label, English tooltip, align, sort value, cell renderer
  const COLS = [
    ['code', 'កូដទំនិញ', 'Item code', '', r => r.code, r => '<b>' + esc(r.code) + '</b>'],
    ['kh', 'ឈ្មោះខ្មែរ', 'Khmer name', '', r => r.kh, r => esc(r.kh)],
    ['en', 'ឈ្មោះអង់គ្លេស', 'English name', '', r => r.en, r => esc(r.en)],
    ['floor', 'ជាន់', 'Floor', 'c', r => r.floor, r => esc(r.floor)],
    ['corner', 'ជួរ', 'Corner', 'c', r => r.corner, r => esc(r.corner)],
    ['original', 'បរិមាណដើមដំបូង', 'Opening qty', 'num', r => r.original, r => qty(r.original)],
    ['added', 'បរិមាណបញ្ចូលស្តុកបន្ថែម', 'Received', 'num', r => r.added, r => qty(r.added)],
    ['on_hand', 'បរិមាណក្នុងស្តុកសរុប', 'Total on hand', 'num', r => r.on_hand, r => qty(r.on_hand)],
    ['sold', 'បរិមាណលក់ចេញ', 'Sold', 'num', r => r.sold, r => qty(r.sold)],
    ['transferred', 'បរិមាណវេរចេញ', 'Transferred out', 'num', r => r.transferred, r => qty(r.transferred)],
    ['remain', 'បរិមាណនៅសល់', 'Remaining', 'num', r => r.remain,
      r => '<span class="pill ' + (r.remain <= 5 ? 'low' : 'ok') + '">' + qty(r.remain) + '</span>'],
    ['unit', 'ថ្លៃដើមរួម', 'Cost (range)', 'num', r => r.u0 ?? -1,
      r => '<span data-dbl="d"' + (r.u_default ? ' class="muted" title="Default cost (no distributor yet)"' : '') + '>' + r.unitTxt + '</span>'],
    ['sup', 'អ្នកផ្គត់ផ្គង់', 'Distributors', '', r => r.suppliers, r => '<span data-dbl="d">' + (esc(r.suppliers) || '–') + '</span>'],
    ['sell', 'តម្លៃលក់រួម', 'Sell price (range)', 'num', r => r.s0 ?? -1,
      r => '<span data-dbl="c"' + (r.s_default ? ' class="muted" title="Default price (no customer price yet)"' : '') + '>' + r.sellTxt + '</span>'],
    ['tcost', 'តម្លៃដើមសរុប', 'Total cost', 'num', r => r.total_cost, r => money(r.total_cost)],
    ['tsell', 'តម្លៃលក់សរុប', 'Total sell', 'num', r => r.total_sell, r => money(r.total_sell)],
  ];

  const st = {q: '', level: '', sort: 'code', dir: 1, sel: D.sel || '', tab: 'd'};

  $('#thead').innerHTML = COLS.map(c =>
    `<th class="${c[3] === 'num' ? 'num' : ''} sortable" data-k="${c[0]}" title="${esc(c[2])}">${c[1]}<i></i></th>`).join('');

  function filtered() {
    const q = st.q.toLowerCase().trim();
    let rows = ROWS.filter(r => (!q || r.blob.includes(q)) &&
      (!st.level || (st.level === 'out' ? r.remain <= 0 : st.level === 'low' ? r.remain <= 5 : r.remain > 0)));
    const col = COLS.find(c => c[0] === st.sort), f = col[4];
    rows.sort((a, b) => {
      const x = f(a), y = f(b);
      return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), undefined, {numeric: true})) * st.dir;
    });
    return rows;
  }

  function render() {
    const rows = filtered();
    $('#tbody').innerHTML = rows.map(r =>
      `<tr data-id="${r.id}" class="${r.id === st.sel ? 'sel' : ''}">` +
      COLS.map(c => `<td class="${c[3]}" data-c="${c[0]}">${c[5](r)}</td>`).join('') + '</tr>').join('') ||
      `<tr><td colspan="${COLS.length}" class="muted">មិនមានទិន្នន័យ — no items match.</td></tr>`;
    document.querySelectorAll('#thead th').forEach(th => {
      th.classList.toggle('asc', th.dataset.k === st.sort && st.dir === 1);
      th.classList.toggle('desc', th.dataset.k === st.sort && st.dir === -1);
    });
    const filtering = st.q.trim() || st.level;
    $('#s-items').textContent = (filtering ? `បង្ហាញ ${rows.length} / ` : '') + `ចំនួនមុខទំនិញសរុប: ${ROWS.length} មុខ`;
  }

  // Global KPIs (all items, like the desktop summary row)
  $('#s-cost').textContent = money(ROWS.reduce((s, r) => s + r.total_cost, 0));
  $('#s-sell').textContent = money(ROWS.reduce((s, r) => s + r.total_sell, 0));

  // ── detail panel ──────────────────────────────────────────────────────────
  const cur = () => ROWS.find(r => r.id === st.sel);
  function bigImg(u) { return u && u.includes('/upload/') ? u.replace('/upload/', '/upload/c_limit,w_900,q_auto,f_auto/') : u; }
  function smallImg(u) { return u && u.includes('/upload/') ? u.replace('/upload/', '/upload/c_limit,w_600,h_260,q_auto,f_auto/') : u; }

  function renderMatrix() {
    const r = cur(); if (!r) return;
    const q = $('#p-search').value.toLowerCase().trim();
    const isD = st.tab === 'd';
    $('#p-th').innerHTML = isD ? '<tr><th>អ្នកផ្គត់ផ្គង់</th><th class="num">ថ្លៃដើមផ្គត់ង់</th><th>កាលបរិច្ឆេទ</th></tr>'
                               : '<tr><th>អតិថិជន</th><th class="num">តម្លៃលក់កំណត់</th><th>កាលបរិច្ឆេទ</th></tr>';
    const list = (isD ? r.distributors : r.customers).filter(x => !q || x.name.toLowerCase().includes(q));
    $('#p-list').innerHTML = list.map(x => `<tr><td>${esc(x.name)}</td><td class="num">${money(isD ? x.cost : x.price)}</td><td class="muted">${dmy(x.date)}</td></tr>`).join('') ||
      '<tr><td colspan="3" class="muted">–</td></tr>';
    document.querySelectorAll('.tab').forEach(t => t.classList.toggle('on', t.dataset.tab === st.tab));
  }

  function select(id, scroll) {
    st.sel = id; const r = cur(); if (!r) return;
    document.querySelectorAll('#tbody tr').forEach(tr => tr.classList.toggle('sel', tr.dataset.id === id));
    $('#p-empty').hidden = true; $('#p-body').hidden = false;
    $('#p-title').textContent = 'កូដទំនិញ៖ ' + r.code;
    $('#p-img').innerHTML = r.image ? `<img src="${esc(smallImg(r.image))}" alt="">` : '<span class="muted">មិនមានឯកសាររូបភាពត្រូវបានផ្ទុកឡើងឡើយ</span>';
    const meta = (k, v, cls) => `<div class="mrow"><span>${k}</span><b class="${cls || ''}">${v}</b></div>`;
    $('#p-meta').innerHTML = meta('ឈ្មោះខ្មែរ', esc(r.kh) || '–') + meta('ឈ្មោះអង់គ្លេស', esc(r.en) || '–') +
      meta('ទីតាំងផ្ទុក', `ជាន់ ${esc(r.floor) || '-'} / ជួរ ${esc(r.corner) || '-'}`) +
      meta('អ្នកផ្គត់ផ្គង់', esc(r.suppliers) || '–') + meta('បរិមាណស្តុក', `នៅសល់ ${qty(r.remain)} ឯកតា`, r.remain <= 5 ? 'bad' : 'info');
    const f = $('#p-open'); f.action = `/stock/${r.id}/original`; f.original_qty.value = r.original;
    $('#p-edit').href = `/items/${r.id}`;
    $('#p-search').value = ''; renderMatrix();
    if (scroll) { const tr = document.querySelector(`#tbody tr[data-id="${id}"]`); tr && tr.scrollIntoView({block: 'center'}); }
  }

  // ── events ────────────────────────────────────────────────────────────────
  let timer; $('#q').addEventListener('input', e => { clearTimeout(timer); timer = setTimeout(() => { st.q = e.target.value; render(); }, 120); });
  $('#level').addEventListener('change', e => { st.level = e.target.value; render(); });
  $('#thead').addEventListener('click', e => {
    const th = e.target.closest('th'); if (!th) return;
    st.dir = st.sort === th.dataset.k ? -st.dir : 1; st.sort = th.dataset.k; render();
  });
  $('#tbody').addEventListener('click', e => { const tr = e.target.closest('tr[data-id]'); tr && select(tr.dataset.id); });
  $('#tbody').addEventListener('dblclick', e => {
    const tr = e.target.closest('tr[data-id]'); if (!tr) return;
    select(tr.dataset.id);
    const c = e.target.closest('td').dataset.c;
    if (c === 'kh' || c === 'en') openLightbox();
    else if (['unit', 'sup', 'sell'].includes(c)) { st.tab = c === 'sell' ? 'c' : 'd'; renderMatrix(); $('#p-search').focus(); $('#side').scrollIntoView({behavior: 'smooth', block: 'nearest'}); }
  });
  document.querySelectorAll('.tab').forEach(t => t.addEventListener('click', () => { st.tab = t.dataset.tab; renderMatrix(); }));
  $('#p-search').addEventListener('input', renderMatrix);

  function openLightbox() { const r = cur(); if (!r || !r.image) return; $('#lb-img').src = bigImg(r.image); $('#lb').hidden = false; }
  $('#p-img').addEventListener('click', openLightbox);
  $('#lb').addEventListener('click', () => { $('#lb').hidden = true; });

  $('#p-hist').addEventListener('click', async () => {
    const r = cur(); if (!r) return;
    $('#hm-title').textContent = 'ប្រវត្តិទិញលម្អិត — ' + r.code;
    $('#hm-body').innerHTML = '<tr><td colspan="6" class="muted">Loading…</td></tr>'; $('#hm').hidden = false;
    try {
      const rows = await (await fetch(`/api/items/${r.id}/history`)).json();
      $('#hm-body').innerHTML = rows.map(h => `<tr><td>${dmy(h.date)}</td><td><a href="/receive/${encodeURIComponent(h.invoice)}">${esc(h.invoice)}</a></td><td>${esc(h.distributor)}</td><td class="num">${qty(h.qty)}</td><td class="num">${money(h.price)}</td><td class="num">${money(h.qty * h.price)}</td></tr>`).join('') ||
        '<tr><td colspan="6" class="muted">No purchases recorded.</td></tr>';
    } catch (e) { $('#hm-body').innerHTML = '<tr><td colspan="6" class="muted">Could not load history.</td></tr>'; }
  });
  $('#hm-x').addEventListener('click', () => { $('#hm').hidden = true; });
  $('#hm').addEventListener('click', e => { if (e.target.id === 'hm') $('#hm').hidden = true; });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { $('#lb').hidden = true; $('#hm').hidden = true; } });

  $('#export').addEventListener('click', () => {
    const head = ['Code', 'Khmer', 'English', 'Floor', 'Corner', 'Opening', 'Received', 'On hand', 'Sold', 'Transferred', 'Remain', 'Cost', 'Distributors', 'Sell', 'Total cost', 'Total sell'];
    const cell = v => '"' + String(v ?? '').replace(/"/g, '""') + '"';
    const lines = [head.map(cell).join(',')].concat(filtered().map(r => [r.code, r.kh, r.en, r.floor, r.corner, r.original, r.added, r.on_hand, r.sold, r.transferred, r.remain,
      r.unitTxt, r.suppliers, r.sellTxt, r.total_cost.toFixed(2), r.total_sell.toFixed(2)].map(cell).join(',')));
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob(['\ufeff' + lines.join('\r\n')], {type: 'text/csv;charset=utf-8'}));
    a.download = 'main-stock.csv'; a.click(); URL.revokeObjectURL(a.href);
  });

  render();
  if (st.sel && cur()) select(st.sel, true);
})();
