/* Label printing — mirrors the desktop LabelPrintPage: scan queue, font size, 21 labels per A4 page (3 x 7). */
(function () {
  const {$, $$, esc, money, dmy, toast, alert, combo} = UI;
  const ITEMS = JSON.parse($('#items-data').textContent), PER = 21;
  let queue = [], page = 0;   // queue: [{id, n}] ; one entry per item with a count
  const byId = new Map(ITEMS.map(i => [i.id, i]));
  const today = new Date(Date.now() + 7 * 3600e3).toISOString().slice(0, 10);

  const match = q => { q = q.toLowerCase().trim(); return q ? ITEMS.filter(i => (i.code + ' ' + i.kh + ' ' + i.en).toLowerCase().includes(q)).slice(0, 8) : []; };
  function addItem(it) {
    const e = queue.find(x => x.id === it.id); if (e) e.n++; else queue.push({id: it.id, n: 1});
    $('#scan').value = ''; draw(); toast(`បានបន្ថែមស្លាក៖ ${it.code}`);
  }
  combo($('#scan'), q => match(q).map(i => ({html: `<b>${esc(i.code)}</b> ${esc(i.kh)} <small>${esc(i.en)}</small>`, value: i.code, data: i})), e => addItem(e.data), {autoFirst: true, fill: false,
    onEnter: () => { const q = $('#scan').value.trim().toLowerCase(); const it = ITEMS.find(i => i.code.toLowerCase() === q) || match(q)[0]; if (it) addItem(it); else if (q) alert(`រកមិនឃើញទំនិញកូដ "${$('#scan').value}" ទេ។`); }});

  function labelHTML(it) {
    const fs = +$('#fs').value, name = esc(it.kh || it.en).replace(/(\d+)/g, '<span class="r">$1</span>');
    const price = it.cost_lo == null ? '' : (it.cost_lo === it.cost_hi ? money(it.cost_lo) : `${money(it.cost_lo)} - ${money(it.cost_hi)}`);
    return `<div class="lbl"><div class="nm" style="font-size:${fs}px">${name}</div><div class="sp">${esc(it.suppliers)}</div><div class="pr" style="font-size:${fs + 1}px">${price}</div><div class="cd">${esc(it.code)} | ${dmy(it.price_date || today)}</div></div>`;
  }
  const flat = () => queue.flatMap(e => Array(e.n).fill(byId.get(e.id)));
  const pages = list => { const out = []; for (let i = 0; i < list.length; i += PER) out.push(list.slice(i, i + PER)); return out.length ? out : [[]]; };
  const sheet = items => `<div class="lbl-sheet">${items.map(labelHTML).join('')}</div>`;

  function draw() {
    const list = flat(), pg = pages(list); page = Math.min(page, pg.length - 1);
    $('#total').textContent = list.length;
    $('#queue').innerHTML = queue.map((e, i) => { const it = byId.get(e.id); return `<tr><td><b>${esc(it.code)}</b></td><td>${esc(it.kh || it.en)}</td><td class="num"><input type="number" min="1" value="${e.n}" data-i="${i}" style="width:70px"></td><td class="num"><button class="btn-x" data-del="${i}">✕</button></td></tr>`; }).join('') || '<tr><td colspan="4" class="muted">មិនទាន់មានស្លាក</td></tr>';
    $('#preview').innerHTML = sheet(pg[page]); $('#pg').textContent = `${page + 1} / ${pg.length}`;
    $('#print-area').innerHTML = pg.map(sheet).join('');
  }
  $('#queue').addEventListener('input', e => { const i = e.target.dataset.i; if (i != null) { queue[+i].n = Math.max(1, parseInt(e.target.value) || 1); const pos = e.target.selectionStart; draw(); const inp = $(`[data-i="${i}"]`); inp && inp.focus(); } });
  $('#queue').addEventListener('click', e => { const b = e.target.closest('[data-del]'); if (b) { queue.splice(+b.dataset.del, 1); draw(); } });
  $('#fs').addEventListener('change', draw);
  $('#prev').addEventListener('click', () => { if (page > 0) { page--; draw(); } });
  $('#next').addEventListener('click', () => { if (page < pages(flat()).length - 1) { page++; draw(); } });
  $('#clear').addEventListener('click', () => { queue = []; page = 0; draw(); });
  const doPrint = () => { if (!queue.length) return alert('សូមស្កែនទំនិញយ៉ាងហោចណាស់មួយមុនបោះពុម្ព។'); window.print(); };
  $('#print').addEventListener('click', doPrint); $('#pdf').addEventListener('click', doPrint);
  draw();
})();
