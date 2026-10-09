/* Shared UI toolkit for the LKN Stock web app: formatting, API calls, modal dialogs, toasts,
   multi-select tables, autocomplete and the payment dialog (mirrors the desktop pop-ups). */
(function (W) {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const num = v => { const n = parseFloat(String(v ?? '').replace(/,/g, '')); return isFinite(n) ? n : 0; };
  const money = n => '$' + (Number(n) || 0).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const qty = n => { n = Number(n || 0); return Number.isInteger(n) ? n.toLocaleString('en-US') : n.toLocaleString('en-US', {maximumFractionDigits: 2}); };
  const dmy = d => /^\d{4}-\d\d-\d\d/.test(d || '') ? d.slice(8, 10) + '/' + d.slice(5, 7) + '/' + d.slice(0, 4) : (d || '–');
  const EPS = 0.005;
  const payState = (t, p) => p <= EPS ? 'unpaid' : (p >= t - EPS ? 'paid' : 'partial');
  const PAY = {paid: '✅ បានទូទាត់', partial: '🟡 បង់ខ្លះ', unpaid: '❌ មិនទាន់ទូទាត់'};
  const payPill = (state, label) => `<span class="pay ${state}">${esc(label || PAY[state])}</span>`;

  async function api(url, data, method) {
    const opt = {method: method || (data === undefined ? 'GET' : 'POST'), headers: {}};
    if (data !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(data); }
    let r, j;
    try { r = await fetch(url, opt); } catch (e) { throw new Error('មិនអាចតភ្ជាប់ទៅម៉ាស៊ីនបម្រើបានទេ (network error)'); }
    if (r.status === 401) {
      try { j = await r.json(); } catch (e) { j = {}; }
      if (j.locked) { location.href = '/items/unlock?next=' + encodeURIComponent(location.pathname); } else { location.href = '/login'; }
      throw new Error(j.error || 'Session expired');
    }
    try { j = await r.json(); } catch (e) { throw new Error('Server error (' + r.status + ')'); }
    if (!r.ok || j.ok === false) throw new Error(j.error || ('Error ' + r.status));
    return j;
  }

  // ── Toast ──────────────────────────────────────────────────────────────
  function toast(msg, kind) {
    let box = $('#toasts'); if (!box) { box = document.createElement('div'); box.id = 'toasts'; document.body.appendChild(box); }
    const t = document.createElement('div'); t.className = 'toast ' + (kind || 'ok'); t.textContent = msg; box.appendChild(t);
    setTimeout(() => t.classList.add('out'), 3200); setTimeout(() => t.remove(), 3700);
  }

  // ── Modal ──────────────────────────────────────────────────────────────
  const stack = [];
  function modal(o) {
    const ov = document.createElement('div'); ov.className = 'modal dlg';
    ov.innerHTML = `<div class="mbox card" style="width:min(${o.width || 520}px,100%)"><div class="chead"><b>${o.title || ''}</b><button type="button" class="btn-x" data-x>✕</button></div>
      <div class="dlg-body"></div><div class="dlg-foot"></div></div>`;
    const body = $('.dlg-body', ov), foot = $('.dlg-foot', ov);
    if (typeof o.body === 'string') body.innerHTML = o.body; else if (o.body) body.appendChild(o.body);
    const api_ = {el: ov, body, close(v) { const i = stack.indexOf(api_); if (i >= 0) stack.splice(i, 1); ov.remove(); if (o.onClose) o.onClose(v); }};
    (o.buttons || []).forEach(b => {
      const el = document.createElement('button'); el.type = 'button'; el.className = 'btn ' + (b.cls || 'sec'); el.innerHTML = b.label;
      el.addEventListener('click', async () => {
        if (b.onClick) { el.disabled = true; try { const r = await b.onClick(api_, el); if (r === false) { el.disabled = false; return; } } catch (e) { el.disabled = false; toast(e.message || e, 'error'); return; } el.disabled = false; }
        if (b.close !== false) api_.close(b.value);
      });
      foot.appendChild(el);
    });
    if (!(o.buttons || []).length) foot.remove();
    $('[data-x]', ov).addEventListener('click', () => api_.close());
    ov.addEventListener('mousedown', e => { if (e.target === ov && !o.sticky) api_.close(); });
    document.body.appendChild(ov); stack.push(api_);
    const first = $('[autofocus],input:not([type=hidden]):not([readonly]),select,textarea', body); if (first && !o.noFocus) setTimeout(() => { first.focus(); if (first.select) first.select(); }, 30);
    body.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.tagName === 'INPUT' && o.enter) { e.preventDefault(); o.enter(api_); } });
    return api_;
  }
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && stack.length) stack[stack.length - 1].close(); });

  const alert_ = (msg, title) => new Promise(res => modal({title: title || 'ជូនដំណឹង', body: `<p class="dlg-msg">${esc(msg).replace(/\n/g, '<br>')}</p>`, width: 440,
    buttons: [{label: 'យល់ព្រម', cls: '', value: true}], onClose: res}));
  const confirm_ = (msg, o = {}) => new Promise(res => { let ans = false; modal({title: o.title || 'បញ្ជាក់', width: 460, body: `<p class="dlg-msg">${esc(msg).replace(/\n/g, '<br>')}</p>`,
    buttons: [{label: o.no || 'បោះបង់', cls: 'sec', onClick: () => { ans = false; }}, {label: o.yes || 'បាទ/ចាស', cls: o.danger ? 'bad' : '', onClick: () => { ans = true; }}], onClose: () => res(ans)}); });

  // ── Table helpers ──────────────────────────────────────────────────────
  /* Multi-select rows (click / ctrl-click / shift-click / Ctrl+A). Rows need data-key. */
  function selectable(tbody, o = {}) {
    let last = null; const sel = new Set();
    const paint = () => $$('tr[data-key]', tbody).forEach(tr => tr.classList.toggle('sel', sel.has(tr.dataset.key)));
    tbody.addEventListener('click', e => {
      if (e.target.closest('a,button,input,select')) return;
      const tr = e.target.closest('tr[data-key]'); if (!tr) return;
      const key = tr.dataset.key, rows = $$('tr[data-key]', tbody);
      if (o.multi && e.shiftKey && last) {
        const a = rows.findIndex(r => r.dataset.key === last), b = rows.findIndex(r => r.dataset.key === key);
        sel.clear(); rows.slice(Math.min(a, b), Math.max(a, b) + 1).forEach(r => sel.add(r.dataset.key));
      } else if (o.multi && (e.ctrlKey || e.metaKey)) { sel.has(key) ? sel.delete(key) : sel.add(key); last = key; }
      else { sel.clear(); sel.add(key); last = key; }
      paint(); if (o.onChange) o.onChange([...sel]);
    });
    if (o.onDouble) tbody.addEventListener('dblclick', e => { const tr = e.target.closest('tr[data-key]'); if (tr) o.onDouble(tr.dataset.key, e); });
    if (o.multi) document.addEventListener('keydown', e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a' && tbody.closest('.pane, body') && tbody.offsetParent && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) {
        e.preventDefault(); $$('tr[data-key]', tbody).forEach(r => sel.add(r.dataset.key)); paint(); if (o.onChange) o.onChange([...sel]);
      }
    });
    return {get: () => [...sel], clear() { sel.clear(); paint(); if (o.onChange) o.onChange([]); }, set(keys) { sel.clear(); keys.forEach(k => sel.add(k)); paint(); if (o.onChange) o.onChange([...sel]); }, repaint: paint};
  }

  /* Right-click / button context menu */
  function menu(x, y, items) {
    $$('.ctx').forEach(m => m.remove());
    const m = document.createElement('div'); m.className = 'ctx';
    items.forEach(it => {
      if (it === '-') { m.appendChild(Object.assign(document.createElement('hr'), {})); return; }
      const b = document.createElement('button'); b.type = 'button'; b.textContent = it.label; if (it.danger) b.className = 'danger';
      b.addEventListener('click', () => { m.remove(); it.fn(); }); m.appendChild(b);
    });
    document.body.appendChild(m);
    const r = m.getBoundingClientRect(); m.style.left = Math.min(x, innerWidth - r.width - 8) + 'px'; m.style.top = Math.min(y, innerHeight - r.height - 8) + 'px';
    const off = e => { if (!m.contains(e.target)) { m.remove(); document.removeEventListener('mousedown', off, true); } };
    setTimeout(() => document.addEventListener('mousedown', off, true), 0);
  }

  /* Autocomplete dropdown under an input. list(query) -> [{html, value, data}] ; pick(entry) */
  function combo(input, list, pick, o = {}) {
    const box = document.createElement('div'); box.className = 'combo'; box.hidden = true;
    input.parentElement.style.position = 'relative'; input.parentElement.appendChild(box);
    let items = [], idx = -1;
    const show = () => {
      const q = input.value; items = list(q) || []; idx = items.length && o.autoFirst ? 0 : -1;
      box.innerHTML = items.map((it, i) => `<div class="opt${i === idx ? ' on' : ''}" data-i="${i}">${it.html}</div>`).join('');
      box.hidden = !items.length;
    };
    const hl = () => $$('.opt', box).forEach((e, i) => { e.classList.toggle('on', i === idx); if (i === idx) e.scrollIntoView({block: 'nearest'}); });
    const choose = i => { const it = items[i]; if (!it) return; box.hidden = true; if (o.fill !== false) input.value = it.value ?? input.value; pick(it); };
    input.addEventListener('input', show);
    input.addEventListener('focus', () => { if (o.onFocusShow) show(); });
    input.addEventListener('keydown', e => {
      if (box.hidden && e.key === 'ArrowDown') { show(); return; }
      if (e.key === 'ArrowDown') { e.preventDefault(); idx = Math.min(idx + 1, items.length - 1); hl(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); idx = Math.max(idx - 1, 0); hl(); }
      else if (e.key === 'Enter') { if (!box.hidden && idx >= 0) { e.preventDefault(); e.stopPropagation(); choose(idx); } else if (o.onEnter) o.onEnter(items); }
      else if (e.key === 'Escape') box.hidden = true;
    });
    box.addEventListener('mousedown', e => { const el = e.target.closest('.opt'); if (el) { e.preventDefault(); choose(+el.dataset.i); } });
    input.addEventListener('blur', () => setTimeout(() => { box.hidden = true; }, 120));
    return {hide() { box.hidden = true; }, refresh: show, items: () => items};
  }

  /* Payment dialog shared by Receive / Sales / Transfers history.
     kind: 'receive' | 'sales' | 'transfers' ; inv: {code,total,paid,balance,state,label} */
  function paymentDialog(kind, inv, who, done) {
    const html = `<div class="paybox"><div class="mrow"><span>លេខកូដ</span><b>${esc(inv.code)}</b></div>${who ? `<div class="mrow"><span>${esc(who[0])}</span><b>${esc(who[1])}</b></div>` : ''}
      <div class="mrow"><span>ទឹកប្រាក់សរុប</span><b>${money(inv.total)}</b></div>
      <div class="mrow"><span>បានបង់រួច</span><b style="color:var(--ok)">${money(inv.paid)}</b></div>
      <div class="mrow"><span>នៅខ្វះ</span><b style="color:var(--bad)" id="pd-bal">${money(inv.balance)}</b></div>
      <label style="margin-top:12px">ទឹកប្រាក់បង់ឥឡូវនេះ ($)</label>
      <div style="display:flex;gap:8px"><input id="pd-amt" type="number" min="0" step="any" value="${inv.balance > 0 ? inv.balance.toFixed(2) : ''}" style="flex:1"><button type="button" class="btn sec sm" id="pd-full">បង់ពេញ</button></div>
      <div class="muted" id="pd-after" style="margin-top:8px"></div></div>`;
    const m = modal({title: '💵 កត់ត្រាការទូទាត់', body: html, width: 440,
      buttons: [{label: 'បោះបង់', cls: 'sec'}, {label: 'រក្សាទុកការទូទាត់', cls: '', close: false, onClick: async d => {
        const amt = num($('#pd-amt', d.el).value);
        if (amt < 0) throw new Error('ទឹកប្រាក់មិនអាចតូចជាងសូន្យបានទេ។');
        const r = await api(`/api/${kind}/${encodeURIComponent(inv.code)}/payment`, {amount: amt});
        d.close(); toast('បានកត់ត្រាការទូទាត់រួចរាល់។'); done && done(r);
      }}], enter: () => $('.btn:not(.sec)', m.el).click()});
    const upd = () => { const a = num($('#pd-amt', m.el).value), nb = Math.max(inv.balance - a, 0); $('#pd-after', m.el).innerHTML = a ? `បន្ទាប់ពីបង់៖ នៅខ្វះ <b>${money(nb)}</b>` : ''; };
    $('#pd-amt', m.el).addEventListener('input', upd); $('#pd-full', m.el).addEventListener('click', () => { $('#pd-amt', m.el).value = inv.balance.toFixed(2); upd(); }); upd();
    return m;
  }

  /* Period summary dialog (Receive / Sales / Transfers) */
  async function summaryDialog(kind, start, end, labels) {
    const j = await api(`/api/summary/${kind}?start=${start}&end=${end}`);
    const row = (k, v, c) => `<div class="mrow"><span style="flex:0 0 220px">${k}</span><b style="color:${c || 'inherit'}">${v}</b></div>`;
    let h = `<div class="muted" style="margin-bottom:8px">ចន្លោះពេល៖ ${dmy(j.start)} ដល់ ${dmy(j.end)}</div>` +
      row('ចំនួនវិក្កយបត្រសរុប', j.count_all) + row('ទឹកប្រាក់សរុប', money(j.total_all)) + (kind === 'sales' ? row('សរុបបញ្ចុះតម្លៃ', money(j.total_discount), 'var(--warn)') : '') +
      row('បានទូទាត់រួច', money(j.total_paid), 'var(--ok)') + row('នៅជំពាក់សរុប', money(j.total_unpaid), 'var(--bad)') +
      row('មិនទាន់ទូទាត់ / បង់ខ្លះ', `${j.count_unpaid} / ${j.count_partial}`);
    if (j.rows.length) h += `<div class="tw" style="margin-top:12px;max-height:240px"><table><thead><tr><th>កូដ</th><th>${esc(labels)}</th><th>កាលបរិច្ឆេទ</th><th class="num">សរុប</th><th class="num">នៅខ្វះ</th></tr></thead><tbody>` +
      j.rows.map(r => `<tr><td>${esc(r.code)}</td><td>${esc(r.name)}</td><td>${dmy(r.date)}</td><td class="num">${money(r.total)}</td><td class="num" style="color:var(--bad)">${money(r.balance)}</td></tr>`).join('') + '</tbody></table></div>';
    modal({title: '📊 សង្ខេបរបាយការណ៍', body: h, width: 720, buttons: [
      {label: '🖨 បោះពុម្ព / PDF', cls: 'sec', close: false, onClick: () => { window.open(`/print/summary/${kind}?start=${start}&end=${end}`, '_blank'); }},
      {label: 'បិទ', cls: ''}]});
  }

  const openPrint = url => window.open(url, '_blank');
  const debounce = (fn, ms = 150) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  /* Tabs: buttons[data-pane] toggle .pane elements */
  function tabs(root, onShow) {
    const btns = $$('.ptab', root), panes = $$('.pane', root);
    const show = id => { btns.forEach(b => b.classList.toggle('on', b.dataset.pane === id)); panes.forEach(p => { p.hidden = p.id !== id; }); onShow && onShow(id); };
    btns.forEach(b => b.addEventListener('click', () => show(b.dataset.pane)));
    return show;
  }
  const download = (name, text, type) => { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], {type: type || 'text/csv;charset=utf-8'})); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 500); };

  // ── Touch: press-and-hold, and hover / hold note bubble ────────────────
  let lastTouchAt = 0;
  document.addEventListener('touchstart', () => { lastTouchAt = Date.now(); }, {passive: true, capture: true});
  const touchedRecently = () => Date.now() - lastTouchAt < 1200;

  /* Press and hold a row (~0.55 s) on a phone/tablet -> handler(rowElement, x, y). Scrolling or lifting early cancels it. */
  function longPress(root, sel, handler, ms = 550) {
    let timer = null, fired = false, sx = 0, sy = 0;
    const cancel = () => { clearTimeout(timer); timer = null; };
    root.addEventListener('touchstart', e => {
      const row = e.target.closest(sel); if (!row || e.touches.length !== 1) return;
      fired = false; sx = e.touches[0].clientX; sy = e.touches[0].clientY;
      timer = setTimeout(() => { fired = true; timer = null; try { navigator.vibrate && navigator.vibrate(15); } catch (_) {} handler(row, sx, sy); }, ms);
    }, {passive: true});
    root.addEventListener('touchmove', e => { const t = e.touches[0]; if (timer && t && (Math.abs(t.clientX - sx) > 10 || Math.abs(t.clientY - sy) > 10)) cancel(); }, {passive: true});
    root.addEventListener('touchend', e => { cancel(); if (fired) { fired = false; if (e.cancelable) e.preventDefault(); } }, {passive: false});   // no "click" after a hold
    root.addEventListener('touchcancel', () => { cancel(); fired = false; }, {passive: true});
    // the phone's own long-press menu / text selection must not fight with ours
    root.addEventListener('contextmenu', e => { if (e.target.closest(sel) && touchedRecently()) e.preventDefault(); });
  }

  let tipEl = null, tipTimer = null;
  function tipHide() { clearTimeout(tipTimer); if (tipEl) { tipEl.remove(); tipEl = null; } }
  function tipShow(x, y, html, autoHideMs, above) {
    tipHide(); tipEl = document.createElement('div'); tipEl.className = 'tip'; tipEl.innerHTML = html; document.body.appendChild(tipEl);
    const r = tipEl.getBoundingClientRect();
    let top = above ? y - r.height - 26 : y + 18; if (top < 8) top = y + 26; if (top + r.height > innerHeight - 8) top = Math.max(8, y - r.height - 14);
    tipEl.style.left = Math.max(8, Math.min(x + 12, innerWidth - r.width - 8)) + 'px'; tipEl.style.top = top + 'px';
    if (autoHideMs) tipTimer = setTimeout(tipHide, autoHideMs);
  }
  /* Show getHtml(row) in a bubble: on hover with a mouse, or on press-and-hold with a finger. */
  function rowTip(root, sel, getHtml) {
    let cur = null, wait = null;
    root.addEventListener('mouseover', e => {
      if (touchedRecently()) return; const row = e.target.closest(sel); if (!row || row === cur) return;
      cur = row; clearTimeout(wait); const x = e.clientX, y = e.clientY;
      wait = setTimeout(() => { const h = getHtml(row); if (h) tipShow(x, y, h); }, 220);
    });
    root.addEventListener('mousemove', e => { if (tipEl && !touchedRecently()) { const r = tipEl.getBoundingClientRect(); tipEl.style.left = Math.max(8, Math.min(e.clientX + 12, innerWidth - r.width - 8)) + 'px'; } });
    root.addEventListener('mouseout', e => { if (!e.relatedTarget || !root.contains(e.relatedTarget) || e.relatedTarget.closest(sel) !== cur) { clearTimeout(wait); cur = null; tipHide(); } });
    longPress(root, sel, (row, x, y) => { const h = getHtml(row); if (h) tipShow(x, y, h, 4500, true); });
    document.addEventListener('touchstart', e => { if (tipEl && !e.target.closest('.tip')) tipHide(); }, {passive: true, capture: true});
    window.addEventListener('scroll', tipHide, {passive: true, capture: true});
  }

  W.UI = {$, $$, esc, num, money, qty, dmy, api, toast, modal, alert: alert_, confirm: confirm_, selectable, menu, combo, longPress, rowTip, tipHide, paymentDialog, summaryDialog,
          payState, payPill, PAY, EPS, openPrint, debounce, tabs, download};
})(window);
