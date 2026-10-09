/* Items page — mirrors the desktop ItemsPage: list, search, low-stock filter, add/edit, supplier & customer price matrices. */
(function () {
  const {$, $$, esc, num, money, qty, dmy, api, toast, modal, confirm, alert, selectable, menu} = UI;
  const D = JSON.parse($('#items-data').textContent);
  let ROWS = D.rows;
  const range = (a, b) => a == null ? '–' : (a === b ? money(a) : money(a) + ' - ' + money(b));
  const COLS = [
    ['កូដទំនិញ', '', r => '<b>' + esc(r.code) + '</b>'], ['ឈ្មោះខ្មែរ', '', r => esc(r.kh)], ['ឈ្មោះអង់គ្លេស', '', r => esc(r.en)],
    ['ជាន់', 'c', r => esc(r.floor)], ['ជួរ', 'c', r => esc(r.corner)],
    ['ថ្លៃដើមរួម', 'num', r => range(r.u0, r.u1)], ['អ្នកផ្គត់ផ្គង់', '', r => esc(r.suppliers) || '–'], ['តម្លៃលក់រួម', 'num', r => range(r.s0, r.s1)],
    ['បរិមាណដើមដំបូង', 'num', r => qty(r.original)], ['បរិមាណក្នុងស្តុក', 'num', r => qty(r.on_hand)], ['បរិមាណលក់ចេញ', 'num', r => qty(r.sold)],
    ['បរិមាណនៅសល់', 'num', r => '<span class="pill ' + (r.remain <= 5 ? 'low' : 'ok') + '">' + qty(r.remain) + '</span>'],
  ];
  $('#thead').innerHTML = COLS.map(c => `<th class="${c[1]}">${c[0]}</th>`).join('');
  const sel = selectable($('#tbody'), {onDouble: id => editItem(id)});
  const cur = () => ROWS.find(r => r.id === sel.get()[0]);

  function filtered() {
    const q = $('#q').value.toLowerCase().trim(), low = $('#low').checked;
    return ROWS.filter(r => (!low || r.remain <= 5) && (!q || [r.code, r.kh, r.en, r.suppliers, r.floor, r.corner].join(' ').toLowerCase().includes(q)));
  }
  function render() {
    const keep = sel.get(), rows = filtered();
    $('#tbody').innerHTML = rows.map(r => `<tr data-key="${r.id}">` + COLS.map(c => `<td class="${c[1]}">${c[2](r)}</td>`).join('') + '</tr>').join('') ||
      `<tr><td colspan="12" class="muted">មិនមានទិន្នន័យ</td></tr>`;
    sel.set(keep.filter(k => rows.some(r => r.id === k)));
    $('#count').textContent = `ចំនួន: ${rows.length} / ${ROWS.length} មុខ`;
  }
  const refresh = async (selectId) => { ROWS = await api('/items/api/list'); render(); if (selectId) sel.set([selectId]); };
  $('#q').addEventListener('input', UI.debounce(render, 120)); $('#low').addEventListener('change', render);

  $('#tbody').addEventListener('contextmenu', e => {
    const tr = e.target.closest('tr[data-key]'); if (!tr) return; e.preventDefault();
    sel.set([tr.dataset.key]);
    menu(e.clientX, e.clientY, [
      {label: '🖼 មើលរូបភាព', fn: () => viewImage(tr.dataset.key)}, {label: 'ℹ ពត៌មានលម្អិត', fn: () => details(tr.dataset.key)}, '-',
      {label: '✏ កែប្រែ', fn: () => editItem(tr.dataset.key)}, {label: '🏭 ថ្លៃដើមតាមអ្នកផ្គត់ផ្គង់', fn: () => matrix(tr.dataset.key, 'distributor')},
      {label: '👥 តម្លៃលក់តាមអតិថិជន', fn: () => matrix(tr.dataset.key, 'customer')}, {label: '🕘 ប្រវត្តិទិញចូល', fn: () => history(tr.dataset.key)}, '-',
      {label: '🗑 លុបមុខទំនិញ', danger: true, fn: () => del(tr.dataset.key)}]);
  });

  // ── image / details / history ──────────────────────────────────────────
  function bigImg(u) { return u && u.includes('/upload/') ? u.replace('/upload/', '/upload/c_limit,w_1000,q_auto,f_auto/') : u; }
  function viewImage(id) {
    const r = ROWS.find(x => x.id === id); if (!r) return;
    if (!r.image) return alert('មិនមានឯកសាររូបភាពត្រូវបានផ្ទុកឡើងសម្រាប់ទំនិញនេះទេ។');
    modal({title: esc(r.code) + ' — ' + esc(r.kh), width: 760, body: `<div style="text-align:center"><img class="itemimg" src="${esc(bigImg(r.image))}" alt=""></div>`, buttons: [{label: 'បិទ', cls: ''}]});
  }
  function details(id) {
    const r = ROWS.find(x => x.id === id); if (!r) return;
    const row = (k, v) => `<div class="mrow"><span>${k}</span><b>${v}</b></div>`;
    modal({title: 'ℹ ពត៌មានលម្អិតមុខទំនិញ', width: 560, body:
      (r.image ? `<div style="text-align:center;margin-bottom:10px"><img class="itemimg" style="max-height:200px" src="${esc(bigImg(r.image))}"></div>` : '') +
      row('កូដទំនិញ', esc(r.code)) + row('ឈ្មោះខ្មែរ', esc(r.kh)) + row('ឈ្មោះអង់គ្លេស', esc(r.en)) + row('ទីតាំង', `ជាន់ ${esc(r.floor) || '-'} / ជួរ ${esc(r.corner) || '-'}`) +
      row('ថ្លៃដើមរួម', range(r.u0, r.u1)) + row('តម្លៃលក់រួម', range(r.s0, r.s1)) + row('អ្នកផ្គត់ផ្គង់', esc(r.suppliers) || '–') +
      row('បរិមាណដើមដំបូង', qty(r.original)) + row('បរិមាណទទួលបន្ថែម', qty(r.added)) + row('បរិមាណក្នុងស្តុក', qty(r.on_hand)) +
      row('បរិមាណលក់ចេញ', qty(r.sold)) + row('បរិមាណវេរចេញ', qty(r.transferred)) + row('បរិមាណនៅសល់', `<span class="${r.remain <= 5 ? 'hl' : ''}">${qty(r.remain)}</span>`),
      buttons: [{label: 'បិទ', cls: ''}]});
  }
  async function history(id) {
    const r = ROWS.find(x => x.id === id); if (!r) return;
    const rows = await api(`/api/items/${id}/history`);
    modal({title: '🕘 ប្រវត្តិទិញចូល — ' + esc(r.code), width: 760, body: '<div class="tw short"><table><thead><tr><th>កាលបរិច្ឆេទ</th><th>វិក្កយបត្រ</th><th>អ្នកផ្គត់ផ្គង់</th><th class="num">បរិមាណ</th><th class="num">ថ្លៃដើម</th><th class="num">សរុប</th></tr></thead><tbody>' +
      (rows.map(h => `<tr><td>${dmy(h.date)}</td><td><a href="/receive/${encodeURIComponent(h.invoice)}">${esc(h.invoice)}</a></td><td>${esc(h.distributor)}</td><td class="num">${qty(h.qty)}</td><td class="num">${money(h.price)}</td><td class="num">${money(h.qty * h.price)}</td></tr>`).join('') ||
        '<tr><td colspan="6" class="muted">មិនទាន់មានការទិញចូល</td></tr>') + '</tbody></table></div>', buttons: [{label: 'បិទ', cls: ''}]});
  }

  // ── add / edit ─────────────────────────────────────────────────────────
  function editItem(id) {
    const r = id ? ROWS.find(x => x.id === id) : null;
    const v = k => r ? esc(r[k]) : '';
    const m = modal({title: r ? '✏ កែប្រែមុខទំនិញ' : '＋ បន្ថែមមុខទំនិញថ្មី', width: 640, sticky: true, body: `
      <div class="fg"><div><label>កូដទំនិញ *</label><input id="f-code" value="${v('code')}" ${r ? 'readonly' : ''}></div>
        <div><label>បរិមាណដើមដំបូង (Opening qty)</label><input id="f-orig" type="number" step="any" value="${r ? r.original : 0}"></div>
        <div><label>ឈ្មោះខ្មែរ *</label><input id="f-kh" value="${v('kh')}"></div>
        <div><label>ឈ្មោះអង់គ្លេស *</label><input id="f-en" value="${v('en')}"></div>
        <div><label>ជាន់ (Floor)</label><input id="f-floor" value="${v('floor')}"></div>
        <div><label>ជួរ (Corner)</label><input id="f-corner" value="${v('corner')}"></div>
        <div><label>តម្លៃលក់លំនាំដើម ($) <span class="small-note">ស្រេចចិត្ត</span></label><input id="f-sell" type="number" step="any" min="0" value="${r ? r.sell_price : 0}"></div>
        <div><label>ថ្លៃដើមលំនាំដើម ($) <span class="small-note">ស្រេចចិត្ត</span></label><input id="f-unit" type="number" step="any" min="0" value="${r ? r.unit_price : 0}"></div></div>
      <label>រូបភាពទំនិញ</label>
      <div style="display:flex;gap:12px;align-items:center"><div class="p-img" style="width:110px;height:90px;margin:0;cursor:default" id="f-prev">${r && r.image ? `<img src="${esc(bigImg(r.image))}">` : '<span class="img-ph">គ្មានរូបភាព</span>'}</div>
        <div><input type="file" id="f-file" accept="image/*">${r && r.image ? '<label style="margin-top:8px;display:flex;gap:6px;align-items:center"><input type="checkbox" id="f-rm"> លុបរូបភាពចេញ</label>' : ''}</div></div>
      <p class="small-note" style="margin-top:10px">ថ្លៃដើម និងតម្លៃលក់តាមអ្នកផ្គត់ផ្គង់/អតិថិជន ត្រូវកំណត់តាមរយៈម៉ឺនុយចុចខាងស្តាំ ឬវិក្កយបត្រទទួលស្តុក។</p>`,
      buttons: [{label: 'បោះបង់', cls: 'sec'}, {label: '💾 រក្សាទុក', cls: '', close: false, onClick: async d => {
        const fd = new FormData();
        if (r) fd.append('id', r.id);
        fd.append('item_code', $('#f-code', d.el).value.trim()); fd.append('name_khmer', $('#f-kh', d.el).value.trim()); fd.append('name_english', $('#f-en', d.el).value.trim());
        fd.append('floor', $('#f-floor', d.el).value.trim()); fd.append('corner', $('#f-corner', d.el).value.trim()); fd.append('original_qty', $('#f-orig', d.el).value || 0);
        fd.append('sell_price', $('#f-sell', d.el).value || 0); fd.append('unit_price', $('#f-unit', d.el).value || 0);
        const file = $('#f-file', d.el).files[0]; if (file) fd.append('image', file); if ($('#f-rm', d.el) && $('#f-rm', d.el).checked) fd.append('remove_image', '1');
        const res = await fetch('/items/api/save', {method: 'POST', body: fd}); let j = {};
        try { j = await res.json(); } catch (e) { throw new Error('Server error ' + res.status); }
        if (res.status === 401) { location.href = '/items/unlock?next=/items'; return false; }
        if (!res.ok || j.ok === false) throw new Error(j.error || 'Error');
        d.close(); toast(r ? 'បានកែប្រែទំនិញរួចរាល់។' : 'បានបន្ថែមទំនិញថ្មីរួចរាល់។'); await refresh(j.id);
      }}]});
    $('#f-file', m.el).addEventListener('change', e => { const f = e.target.files[0]; if (f) $('#f-prev', m.el).innerHTML = `<img src="${URL.createObjectURL(f)}">`; });
  }

  async function del(id) {
    const r = ROWS.find(x => x.id === id); if (!r) return;
    if (!await confirm(`តើអ្នកពិតជាចង់លុបទំនិញ "${r.code} — ${r.kh}" មែនទេ?\nប្រតិបត្តិការទិញចូល និងលក់ទាំងអស់របស់ទំនិញនេះនឹងត្រូវលុបដែរ។`, {danger: true, yes: 'លុប'})) return;
    try { await api(`/items/api/${id}/delete`, {}); toast('បានលុបទំនិញរួចរាល់។'); await refresh(); } catch (e) { alert(e.message); }
  }

  // ── supplier cost / customer price matrices ───────────────────────────
  async function matrix(id, kind) {
    const r = ROWS.find(x => x.id === id); if (!r) return;
    const isD = kind === 'distributor';
    const m = modal({title: (isD ? '🏭 ថ្លៃដើមតាមអ្នកផ្គត់ផ្គង់ — ' : '👥 តម្លៃលក់តាមអតិថិជន — ') + esc(r.code), width: 680, sticky: true,
      body: '<div id="mx"></div>', buttons: [{label: 'បិទ', cls: ''}], onClose: () => refresh(id)});
    let data = await api(`/items/api/${id}/matrix`);
    const draw = () => {
      const list = isD ? data.distributors : data.customers, names = isD ? data.suppliers : data.customer_names;
      $('#mx', m.el).innerHTML = `<div class="tw short"><table><thead><tr><th>${isD ? 'អ្នកផ្គត់ផ្គង់' : 'អតិថិជន'}</th><th class="num">${isD ? 'ថ្លៃដើម' : 'តម្លៃលក់'}</th><th>កាលបរិច្ឆេទ</th><th></th></tr></thead><tbody>` +
        (list.map(x => `<tr data-n="${esc(x.name)}"><td>${esc(x.name)}</td><td class="num">${money(x.price)}</td><td>${dmy(x.date)}</td><td class="num"><button class="btn sec sm" data-e>កែ</button> <button class="btn-x" data-d>🗑</button></td></tr>`).join('') ||
          '<tr><td colspan="4" class="muted">មិនទាន់មានទិន្នន័យ</td></tr>') + `</tbody></table></div>
        <div class="fg" style="margin-top:14px;grid-template-columns:2fr 1fr 1fr auto;align-items:end"><div><label>${isD ? 'អ្នកផ្គត់ផ្គង់' : 'អតិថិជន'}</label><input id="mx-n" list="mx-l" autocomplete="off"><datalist id="mx-l">${names.map(n => `<option value="${esc(n)}">`).join('')}</datalist></div>
        <div><label>${isD ? 'ថ្លៃដើម ($)' : 'តម្លៃលក់ ($)'}</label><input id="mx-p" type="number" min="0" step="any"></div>
        <div><label>កាលបរិច្ឆេទ</label><input id="mx-d" type="date" value="${new Date().toISOString().slice(0, 10)}"></div><button class="btn" id="mx-s">រក្សាទុក</button></div>`;
      $$('[data-e]', m.el).forEach(b => b.addEventListener('click', () => { const x = list.find(y => y.name === b.closest('tr').dataset.n); $('#mx-n', m.el).value = x.name; $('#mx-p', m.el).value = x.price; $('#mx-d', m.el).value = (x.date || '').slice(0, 10); $('#mx-p', m.el).focus(); }));
      $$('[data-d]', m.el).forEach(b => b.addEventListener('click', async () => {
        const n = b.closest('tr').dataset.n; if (!await confirm(`លុប "${n}" ចេញពីម៉ាទ្រីស?`, {danger: true, yes: 'លុប'})) return;
        await api(`/items/api/${id}/${kind}/delete`, {name: n}); data = await api(`/items/api/${id}/matrix`); draw(); }));
      $('#mx-s', m.el).addEventListener('click', async () => {
        try { await api(`/items/api/${id}/${kind}`, {name: $('#mx-n', m.el).value, price: $('#mx-p', m.el).value, date: $('#mx-d', m.el).value}); toast('បានរក្សាទុករួចរាល់។'); data = await api(`/items/api/${id}/matrix`); draw(); }
        catch (e) { toast(e.message, 'error'); } });
    };
    draw();
  }

  $('#new').addEventListener('click', () => editItem());
  $('#print').addEventListener('click', () => window.print());
  $('#export').addEventListener('click', () => {
    const cell = v => '"' + String(v ?? '').replace(/"/g, '""') + '"';
    const head = COLS.map(c => c[0]), lines = [head.map(cell).join(',')].concat(filtered().map(r => [r.code, r.kh, r.en, r.floor, r.corner, range(r.u0, r.u1), r.suppliers, range(r.s0, r.s1), r.original, r.on_hand, r.sold, r.remain].map(cell).join(',')));
    UI.download('items.csv', '\ufeff' + lines.join('\r\n'));
  });
  render();
  if (D.open_new) editItem(); else if (D.open_edit) { sel.set([D.open_edit]); editItem(D.open_edit); }
})();
