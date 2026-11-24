'use strict';

const $ = sel => document.querySelector(sel);
const state = {
  offerId: null,       // выбранный оффер в форме создания
  busy: false,
};

const COUNTRIES = {
  US:'США',GB:'Великобритания',DE:'Германия',FR:'Франция',ES:'Испания',IT:'Италия',
  NL:'Нидерланды',PL:'Польша',BR:'Бразилия',MX:'Мексика',AR:'Аргентина',CL:'Чили',
  CO:'Колумбия',CA:'Канада',AU:'Австралия',NZ:'Новая Зеландия',IN:'Индия',ID:'Индонезия',
  PH:'Филиппины',VN:'Вьетнам',TH:'Таиланд',MY:'Малайзия',SG:'Сингапур',JP:'Япония',
  KR:'Южная Корея',CN:'Китай',HK:'Гонконг',TW:'Тайвань',AE:'ОАЭ',SA:'Саудовская Аравия',
  EG:'Египет',NG:'Нигерия',KE:'Кения',ZA:'ЮАР',UA:'Украина',TR:'Турция',KZ:'Казахстан',
  RU:'Россия',BY:'Беларусь',RO:'Румыния',CZ:'Чехия',HU:'Венгрия',PT:'Португалия',
  SE:'Швеция',NO:'Норвегия',DK:'Дания',FI:'Финляндия',CH:'Швейцария',AT:'Австрия',
  BE:'Бельгия',IE:'Ирландия',GR:'Греция',IL:'Израиль',PK:'Пакистан',BD:'Бангладеш',
};

// ---------- утилиты ----------

function showError(msg) {
  const el = $('#error');
  if (msg) { el.textContent = msg; el.classList.remove('hidden'); }
  else el.classList.add('hidden');
}
function showNotice(msg) {
  const el = $('#notice');
  if (msg) { el.textContent = msg; el.classList.remove('hidden'); }
  else el.classList.add('hidden');
}

async function api(path, body) {
  const opts = body === undefined
    ? {}
    : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const res = await fetch('/api/' + path, opts);
  let data = null;
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) {
    const detail = data && data.detail ? data.detail : `HTTP ${res.status}`;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return data;
}

function setBusy(b) {
  state.busy = b;
  document.querySelectorAll('button').forEach(btn => { btn.disabled = b; });
}

async function run(fn) {
  if (state.busy) return;
  setBusy(true);
  showError(''); showNotice('');
  try { await fn(); } catch (e) { showError(e.message); } finally { setBusy(false); }
}

// ---------- автокомплит офферов ----------

// общий datalist для всех полей выбора оффера (id один — можно переиспользовать)
function offerListEl() {
  let el = document.getElementById('offer-options');
  if (!el) {
    el = document.createElement('datalist');
    el.id = 'offer-options';
    document.body.appendChild(el);
  }
  return el;
}

function makeOfferAutocomplete(input, onPick) {
  input.setAttribute('list', 'offer-options');
  const list = offerListEl();

  let matches = [];
  let timer = null;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    const q = input.value.trim();
    onPick(null);
    if (!q) { list.innerHTML = ''; return; }
    timer = setTimeout(async () => {
      try {
        matches = await api('offers?q=' + encodeURIComponent(q));
        list.innerHTML = matches.map(o =>
          `<option value="${escapeHtml(o.name)} #${o.id}"></option>`).join('');
      } catch (_) { list.innerHTML = ''; matches = []; }
    }, 250);
  });

  input.addEventListener('change', () => {
    const picked = matches.find(o => `${o.name} #${o.id}` === input.value.trim());
    input.setCustomValidity(picked || !input.value.trim() ? '' : 'Выберите оффер из списка');
    onPick(picked || null);
  });
  return {
    reset() {
      input.value = '';
      list.innerHTML = '';
      onPick(null);
      input.setCustomValidity('');
    },
  };
}

function renderCampaign(c) {
  $('#editor-hint').classList.add('hidden');
  const root = $('#campaign-view');
  root.innerHTML = '';

  const head = document.createElement('h2');
  head.innerHTML = `${escapeHtml(c.name)} <small>#${c.id}</small>`;
  root.appendChild(head);

  for (const s of c.streams) {
    root.appendChild(renderStream(s));
  }
}

function renderStream(s) {
  const card = document.createElement('article');
  card.className = 'card stream' + (s.dirty ? ' dirty' : '');

  const title = document.createElement('h3');
  title.innerHTML = `${escapeHtml(s.name)} <small>Keitaro stream #${s.id}</small>`;
  card.appendChild(title);
  if (s.dirty) {
    const warn = document.createElement('p');
    warn.className = 'warn';
    warn.textContent = 'Есть неопубликованные изменения';
    card.appendChild(warn);
  }

  // поток офферов определяется по schema='landings' из Keitaro;
  // запасные признаки — наличие связей или имя (для старых записей без schema)
  const hasOffers = Array.isArray(s.offers) && s.offers.length > 0;
  const name = (s.name || '').toLowerCase();
  const isOfferStream = s.schema === 'landings' || hasOffers
    || name.includes('оффер') || name.includes('offer');

  if (!isOfferStream) {
    const p = document.createElement('p');
    p.className = 'hint';
    p.textContent = 'Поток без привязанных офферов (например, GEO-редирект). Редактируется в Keitaro.';
    card.appendChild(p);
    return card;
  }

  // таблица офферов
  const wrap = document.createElement('div');
  wrap.className = 'table-wrap';
  const table = document.createElement('table');
  table.innerHTML = `<thead><tr>
    <th>Оффер</th><th>Доля</th><th>Закрепить</th><th></th>
  </tr></thead><tbody></tbody>`;
  const tbody = table.querySelector('tbody');

  const totalActive = s.offers
    .filter(o => o.state === 'active')
    .reduce((a, o) => a + (o.share ?? 0), 0);

  for (const o of s.offers) {
    const tr = document.createElement('tr');
    if (o.state === 'removed') tr.className = 'archived';
    tr.innerHTML = `
      <td>${escapeHtml(o.name)}${o.state === 'removed' ? ' <span class="tag">[removed]</span>' : ''} <small class="oid">#${o.id}</small></td>
      <td class="share">${(o.share ?? 0)}%</td>
      <td class="pin-cell"></td>
      <td class="row-actions"></td>`;

    const pinCell = tr.querySelector('.pin-cell');
    const actions = tr.querySelector('.row-actions');

    if (o.state === 'active') {
      const pinWrap = document.createElement('span');
      pinWrap.className = 'pin-wrap';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = !!o.pin;
      cb.title = 'Закрепить долю';
      cb.addEventListener('change', () =>
        run(async () => {
          const view = await api(`streams/${s.id}/offers/${cb.checked ? 'pin' : 'unpin'}`, { offer_id: o.id });
          renderCampaign(view);
        }));
      pinWrap.appendChild(cb);
      if (o.pin) {
        const num = document.createElement('input');
        num.type = 'number'; num.min = 0; num.max = 100; num.value = o.share;
        num.className = 'pin-pct';
        const btn = document.createElement('button');
        btn.textContent = 'Применить';
        btn.addEventListener('click', () => {
          const pct = num.value === '' ? NaN : Number(num.value);
          if (!Number.isFinite(pct) || pct < 0 || pct > 100) {
            showError('Введите долю закрепления: число от 0 до 100');
            return;
          }
          run(async () => {
            const view = await api(`streams/${s.id}/offers/pin`, { offer_id: o.id, percent: pct });
            renderCampaign(view);
          });
        });
        pinWrap.append(num, btn);
      }
      pinCell.appendChild(pinWrap);
    }

    const btn = document.createElement('button');
    btn.className = 'ghost';
    btn.textContent = o.state === 'removed' ? 'Bring back' : 'Remove';
    btn.addEventListener('click', () =>
      run(async () => {
        const view = await api(`streams/${s.id}/offers/${o.state === 'removed' ? 'restore' : 'remove'}`, { offer_id: o.id });
        renderCampaign(view);
      }));
    actions.appendChild(btn);
    tbody.appendChild(tr);
  }

  const sumTr = document.createElement('tr');
  sumTr.className = 'sum-row';
  sumTr.innerHTML = `<td colspan="4">Сумма активных долей: <b>${totalActive}%</b>${totalActive === 100 ? '' : ' — не 100%'}</td>`;
  tbody.appendChild(sumTr);
  wrap.appendChild(table);
  card.appendChild(wrap);

  // добавление оффера
  const addForm = document.createElement('form');
  addForm.className = 'add-offer';
  const input = document.createElement('input');
  input.required = true; input.autocomplete = 'off';
  input.placeholder = 'ID или название оффера';
  const addBtn = document.createElement('button');
  addBtn.textContent = 'Добавить оффер';
  let picked = null;
  const ac = makeOfferAutocomplete(input, o => { picked = o; });
  addForm.append(input, addBtn);
  addForm.addEventListener('submit', ev => {
    ev.preventDefault();
    if (!picked) { input.setCustomValidity('Выберите оффер из списка'); input.reportValidity(); return; }
    run(async () => {
      const view = await api(`streams/${s.id}/offers/add`, { offer_id: picked.id });
      ac.reset();
      renderCampaign(view);
    });
  });
  card.appendChild(addForm);

  // Push / Cancel
  if (s.dirty) {
    const foot = document.createElement('div');
    foot.className = 'actions';
    const pushBtn = document.createElement('button');
    pushBtn.textContent = 'Push to KT';
    pushBtn.addEventListener('click', () =>
      run(async () => {
        const view = await api(`streams/${s.id}/push`, {});
        renderCampaign(view);
        showNotice('Изменения опубликованы в Keitaro');
      }));
    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'ghost';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', () =>
      run(async () => {
        const view = await api(`streams/${s.id}/cancel`, {});
        renderCampaign(view);
      }));
    foot.append(pushBtn, cancelBtn);
    card.appendChild(foot);
  }
  return card;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

// ---------- страницы ----------

function showPage(page) {
  $('#page-create').classList.toggle('hidden', page !== 'create');
  $('#page-editor').classList.toggle('hidden', page !== 'editor');
  document.querySelectorAll('nav button').forEach(b =>
    b.classList.toggle('active', b.dataset.page === page));
}

document.querySelectorAll('nav button').forEach(b =>
  b.addEventListener('click', () => showPage(b.dataset.page)));

// ---------- init ----------

async function init() {
  try {
    const meta = await api('meta');
    if (meta.demo) $('#demo-badge').classList.remove('hidden');
  } catch (e) {
    showError('Не удалось связаться с API: ' + e.message);
  }

  // страны для datalist
  $('#countries').innerHTML = Object.entries(COUNTRIES)
    .map(([code, name]) => `<option value="${code}">${name}</option>`).join('');

  // справочники для формы создания
  try {
    const opt = await api('options');
    const fill = (sel, rows) => {
      $(sel).innerHTML = '<option value="">—</option>' +
        rows.map(r => `<option value="${r.id}">${escapeHtml(r.name)}</option>`).join('');
    };
    fill('#sel-domain', opt.domains);
    fill('#sel-group', opt.groups);
    fill('#sel-source', opt.sources);
  } catch (e) {
    showError('Не удалось загрузить справочники Keitaro: ' + e.message);
  }

  // локальные кампании
  try {
    const camps = await api('campaigns');
    $('#local-campaigns').innerHTML = '<option value="">—</option>' +
      camps.map(c => `<option value="${c.id}">${escapeHtml(c.name)} #${c.id}</option>`).join('');
    if (camps.length) {
      const last = localStorage.getItem('adrobot-campaign');
      const pick = camps.find(c => String(c.id) === last) || camps[camps.length - 1];
      $('#local-campaigns').value = String(pick.id);
      renderCampaign(await api('campaigns/' + pick.id));
    }
  } catch (e) {
    showError('Не удалось загрузить локальные кампании: ' + e.message);
  }

  $('#local-campaigns').addEventListener('change', ev => {
    const id = ev.target.value;
    if (!id) return;
    localStorage.setItem('adrobot-campaign', id);
    run(async () => renderCampaign(await api('campaigns/' + id)));
  });

  // форма создания
  const offerInput = $('#offer-input');
  const createAc = makeOfferAutocomplete(offerInput, o => { state.offerId = o; });

  $('#create-form').addEventListener('submit', ev => {
    ev.preventDefault();
    if (!state.offerId) {
      offerInput.setCustomValidity('Выберите оффер из списка');
      offerInput.reportValidity();
      return;
    }
    const fd = new FormData(ev.target);
    const body = {
      name: fd.get('name'),
      country: fd.get('country').toUpperCase(),
      offer_id: state.offerId.id,
      domain_id: Number(fd.get('domain_id')),
      group_id: Number(fd.get('group_id')),
      traffic_source_id: Number(fd.get('traffic_source_id')),
    };
    run(async () => {
      const view = await api('campaigns', body);
      createAc.reset();
      state.offerId = null;
      ev.target.reset();
      await refreshCampaignList();
      $('#local-campaigns').value = String(view.id);
      localStorage.setItem('adrobot-campaign', view.id);
      renderCampaign(view);
      showPage('editor');
      showNotice('Кампания создана и включена в Keitaro');
    });
  });

  // загрузка потоков по ID
  $('#fetch-form').addEventListener('submit', ev => {
    ev.preventDefault();
    const cid = Number(new FormData(ev.target).get('cid'));
    run(async () => {
      const view = await api(`campaigns/${cid}/fetch`, {});
      await refreshCampaignList();
      $('#local-campaigns').value = String(cid);
      renderCampaign(view);
    });
  });
}

async function refreshCampaignList() {
  const camps = await api('campaigns');
  const sel = $('#local-campaigns');
  sel.innerHTML = '<option value="">—</option>' +
    camps.map(c => `<option value="${c.id}">${escapeHtml(c.name)} #${c.id}</option>`).join('');
  return camps;
}

init();
