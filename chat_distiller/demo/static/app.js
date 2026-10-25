'use strict';

/* One timeline over the real ClaimStore. Every write below hits the same
   engine as the CLI and MCP server; the page holds no state of its own. */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const DEFAULT_BUDGET = 2048;
const LANG_KEY = 'claim-ledger-lang';

const S = {
  lang: localStorage.getItem(LANG_KEY) || 'zh',
  at: '',
  budget: DEFAULT_BUDGET,
  state: null,
  brief: null,
  pastOpen: false,
  pending: null,   // {text, topic, conflicts} while a conflict card is open
};


const t = (key) => {
  const table = I18N[S.lang];
  const value = table[key] ?? I18N.zh[key];
  return typeof value === 'function' ? value : (value ?? key);
};

const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const shortId = (id) => id ? id.slice(0, 12) : '—';
const fmtDay = (iso) => (iso ? iso.slice(5, 10).replace('-', '/') : '');

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const body = await res.json().catch(() => ({}));
  return { status: res.status, body };
}

function toast(message, isError = false) {
  const el = $('#toast');
  el.textContent = message;
  el.className = 'toast' + (isError ? ' toast--error' : '');
  el.hidden = false;
  el.style.animation = 'none';
  void el.offsetWidth;        // restart the entrance animation on each show
  el.style.animation = '';
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => { el.hidden = true; }, 3400);
}

/* ------------------------------------------------------------------ i18n */

function applyI18n() {
  const T = I18N[S.lang];
  document.documentElement.lang = S.lang === 'zh' ? 'zh-CN' : 'en';
  $('#langBtn').textContent = S.lang === 'zh' ? 'EN' : '中';
  // Declarative copy: any element with data-i18n / -ph / -title is translated
  // by walking the DOM; code never hand-updates static strings again.
  for (const el of $$('[data-i18n]')) {
    const value = T[el.dataset.i18n] ?? I18N.zh[el.dataset.i18n];
    if (typeof value === 'string') el.textContent = value;
  }
  for (const el of $$('[data-i18n-ph]')) {
    el.placeholder = T[el.dataset.i18nPh] ?? I18N.zh[el.dataset.i18nPh] ?? '';
  }
  for (const el of $$('[data-i18n-title]')) {
    const value = T[el.dataset.i18nTitle] ?? I18N.zh[el.dataset.i18nTitle] ?? '';
    el.title = value;
    el.setAttribute('aria-label', value);
  }
}


/* --------------------------------------------------------------- loading */

async function refresh() {
  const at = S.at ? `?at=${encodeURIComponent(S.at)}` : '';
  const [stateRes, briefRes] = await Promise.all([
    api(`/api/state${at}`),
    api(`/api/brief?max_bytes=${S.budget}${S.at ? `&at=${encodeURIComponent(S.at)}` : ''}`),
  ]);
  if (!stateRes.body.ok) { toast(stateRes.body.error || 'state failed', true); return; }
  S.state = stateRes.body;
  S.brief = briefRes.body;
  renderChrome();
  renderBudget();
  renderTimeline();
}

function renderChrome() {
  const st = S.state;
  $('#scenarioName').textContent = st.scenario.name;
  $('#scenarioKicker').textContent = st.scenario.kicker;
  const meta = `v${st.version} · ${st.counts.total} claims · sha ${String(st.store.sha256).slice(0, 8)} · 0 model calls`;
  $('#footMeta').textContent = meta;
}

function renderBudget() {
  const packet = S.brief && S.brief.packet;
  if (!packet) return;
  $('#budgetUsed').textContent = packet.used_bytes;
  $('#budgetMax').textContent = packet.budget_bytes;
  const pct = Math.min(100, Math.round(packet.used_bytes / packet.budget_bytes * 100));
  $('#budgetFill').style.width = pct + '%';
  const omitEl = $('#budgetOmit');
  if (packet.omitted > 0) {
    omitEl.textContent = t('omit')(packet.omitted);
    omitEl.hidden = false;
  } else { omitEl.hidden = true; }
}

/* -------------------------------------------------------------- timeline */

function claimSections() {
  const st = S.state;
  const byId = new Map(st.claims.map(c => [c.claim_id, c]));
  const unmotivated = new Map((st.unmotivated || []).map(u => [u.claim_id, u]));
  const statusAt = S.at;   // when set, each claim carries status_at
  const current = [], attention = [], past = [];
  for (const claim of st.claims) {
    if (claim.redacted_at) continue;
    if (statusAt) {
      const key = claim.status_at;
      if (key === '现行') current.push(claim);
      else if (key === '有争议') attention.push(claim);
      else if (key === '已过期') past.push(claim);
    } else {
      const flagged = unmotivated.get(claim.claim_id);
      if (flagged) { attention.push(Object.assign({ _broken: flagged.broken_dependencies }, claim)); }
      else if (claim.status === '现行') current.push(claim);
      else if (claim.status === '有争议') attention.push(claim);
      else past.push(claim);
    }
  }
  const order = (a, b) => (a.created_at < b.created_at ? 1 : -1);
  current.sort(order); attention.sort(order); past.sort(order);
  return { current, attention, past, byId, unmotivated };
}

function renderTimeline() {
  const { current, attention, past, byId } = claimSections();
  const isAt = Boolean(S.at);

  $('#currentTitle').textContent = isAt ? t('atPrefix')(S.at.slice(0, 10)) : t('current');
  $('#currentCount').textContent = current.length;
  $('#attentionCount').textContent = attention.length;
  $('#pastCount').textContent = past.length;

  $('#listCurrent').innerHTML = current.map(c => claimCard(c, byId, isAt)).join('') || '';
  $('#listAttention').innerHTML = attention.map(c => claimCard(c, byId, isAt)).join('') || '';
  $('#listPast').innerHTML = past.map(c => claimCard(c, byId, isAt)).join('') || '';
  $('#secAttention').hidden = attention.length === 0;
  $('#secPast').hidden = past.length === 0;

  const totalVisible = current.length + attention.length + past.length;
  $('#timelineEmpty').hidden = totalVisible > 0;

  $$('.claim__row').forEach(row => {
    row.addEventListener('click', () => {
      const card = row.closest('.claim');
      const detail = card.querySelector('.claim__detail');
      if (detail) {
        detail.hidden = !detail.hidden;
        card.classList.toggle('is-open', !detail.hidden);
      }
    });
  });
  wireResolveButtons(byId);
}

function claimCard(claim, byId, isAt) {
  const isDisputed = isAt ? claim.status_at === '有争议' : claim.status === '有争议';
  const isUnmotivated = Boolean(claim._broken);
  const isCurrent = isAt ? claim.status_at === '现行' : claim.status === '现行';
  const isPast = isAt ? claim.status_at === '已过期' : claim.status === '已过期';
  const fromDoubao = /doubao/i.test(claim.source || '') || /doubao/i.test(claim.session_hint || '');

  const badges = [];
  if (isUnmotivated) badges.push(`<span class="claim__badge badge--unmotivated">${esc(t('unmotivatedBadge'))}</span>`);
  else if (isDisputed) badges.push(`<span class="claim__badge badge--disputed">${esc(t('disputedBadge'))}</span>`);
  if (fromDoubao && !isPast) badges.push(`<span class="claim__badge badge--doubao">${esc(t('doubao'))}</span>`);

  const cls = isCurrent ? 'claim--current' : isPast ? 'claim--past' : 'claim--attention';
  const dot = isUnmotivated ? 'dot--unmotivated' : isDisputed ? 'dot--disputed'
    : isPast ? 'dot--superseded' : 'dot--current';
  const depNames = (claim._broken || claim.depends_on || []).map(id => {
    const dep = byId.get(id);
    return esc(dep ? dep.text : id);
  });
  const rows = [];
  rows.push(['dt', t('recordedAt')], ['dd', `${fmtDay(claim.created_at)} · ${shortId(claim.claim_id)}`]);
  if (claim.source) rows.push(['dt', t('source')], ['dd', esc(claim.source)]);
  if (claim.quote) rows.push(['dt', t('quote')], ['dd', esc(claim.quote), 'q']);
  if (claim._broken) rows.push(['dt', t('brokenDeps')], ['dd', depNames.join('；')]);
  else if (claim.depends_on && claim.depends_on.length) rows.push(['dt', t('dependsOn')], ['dd', depNames.join('；')]);
  if (claim.superseded_by) {
    const next = byId.get(claim.superseded_by);
    rows.push(['dt', t('supersededBy')], ['dd', esc(next ? next.text : claim.superseded_by)]);
  }
  const dl = rows.map(([tag, text, cls]) =>
    `<${tag}${cls ? ` class="${cls}"` : ''}>${text}</${tag}>`).join('');

  const resolveUi = (isDisputed && !isAt) ? resolveControls(claim) : '';

  return `<li class="claim ${cls}" data-id="${esc(claim.claim_id)}">
    <div class="claim__row" role="button" tabindex="0">
      <i class="dot ${dot}"></i>
      <span class="claim__text">${esc(claim.text)}</span>
      ${badges.join('')}
      <span class="claim__topic">${esc(claim.topic)}</span>
      <span class="claim__chev" aria-hidden="true">▸</span>
    </div>
    <div class="claim__detail" hidden><dl>${dl}</dl>${resolveUi}</div>
  </li>`;
}

function resolveControls(claim) {
  const noTarget = !(claim.disputes && claim.disputes.length);
  const hint = noTarget ? `<span class="resolve__hint">${esc(t('resolveHintNoTarget'))}</span>` : '';
  return `<div class="resolve" data-id="${esc(claim.claim_id)}">
    ${hint}
    <button class="btn" data-act="sustain" type="button">${esc(t('sustain'))}</button>
    <button class="btn" data-act="withdraw" type="button" ${noTarget ? 'disabled' : ''}>${esc(t('withdraw'))}</button>
    <button class="btn btn--ghost" data-act="new" type="button">${esc(t('newDecision'))}</button>
    <span class="resolve__new" hidden>
      <input type="text" data-input="new-text" placeholder="${esc(t('placeholder'))}">
      <button class="btn btn--primary" data-act="supersede" type="button">${esc(t('confirm'))}</button>
    </span>
  </div>`;
}

function wireResolveButtons() {
  $$('.resolve .btn').forEach(btn => {
    btn.addEventListener('click', async (ev) => {
      ev.stopPropagation();
      const box = btn.closest('.resolve');
      const id = box.dataset.id;
      const act = btn.dataset.act;
      if (act === 'new') { box.querySelector('.resolve__new').hidden = false; return; }
      let text;
      if (act === 'supersede') {
        text = box.querySelector('[data-input="new-text"]').value.trim();
        if (!text) return;
      }
      const { body } = await api('/api/resolve', {
        method: 'POST',
        body: JSON.stringify({ claim_id: id, outcome: act, text, topic: 'general' }),
      });
      if (!body.ok) { toast(body.error, true); return; }
      toast(t('resolvedOk'));
      refresh();
    });
  });
}

/* -------------------------------------------------------------- composer */

function wireComposer() {
  const textEl = $('#fText');
  const sendBtn = $('#recordBtn');
  const sync = () => {
    // Auto-grow up to six lines, then scroll inside — Kimi's editor behavior.
    textEl.style.height = 'auto';
    textEl.style.height = Math.min(textEl.scrollHeight, 144) + 'px';
    // The send button wakes up only with text, like Kimi's disabled gray state.
    sendBtn.disabled = !textEl.value.trim();
  };
  textEl.addEventListener('input', sync);
  textEl.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); submit(); }
  });
  $('#recordBtn').addEventListener('click', submit);

  const examples = S.state && S.state.examples ? S.state.examples : {};
  const box = $('#examples');
  box.innerHTML = '';
  for (const key of ['conflict', 'premise', 'dispute', 'clean']) {
    const ex = examples[key];
    if (!ex) continue;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'example';
    btn.textContent = t('examples')[key] || key;
    btn.addEventListener('click', () => {
      $('#fText').value = ex.text;
      $('#fTopic').value = ex.topic;
      sync();
      $('#fText').focus();
    });
    box.appendChild(btn);
  }
}

async function submit() {
  const text = $('#fText').value.trim();
  if (!text) return;
  const payload = { text, topic: $('#fTopic').value.trim() || 'general' };
  const { status, body } = await api('/api/record', {
    method: 'POST', body: JSON.stringify(payload),
  });
  if (status === 409 && body.error_type === 'Conflict') {
    S.pending = { payload, conflicts: body.conflicts || [] };
    showConflict(S.pending);
    return;
  }
  if (!body.ok) { toast(body.error, true); return; }
  $('#fText').value = '';
  $('#recordBtn').disabled = true;
  $('#fText').style.height = '';
  toast(t('recorded')(shortId(body.receipt.claim_id)));
  refresh();
}

function showConflict(pending) {
  const card = $('#conflictCard');
  $('#conflictList').innerHTML = pending.conflicts.map(c =>
    `<li><i class="dot dot--current"></i> ${esc(c.text)}<span class="mono">${esc(shortId(c.claim_id))}</span></li>`).join('');
  card.hidden = false;
  card.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function hideConflict() {
  $('#conflictCard').hidden = true;
  S.pending = null;
}

async function resolveConflict(mode) {
  const pending = S.pending;
  if (!pending) return;
  const supersedes = mode === 'supersede'
    ? pending.conflicts.map(c => c.claim_id) : undefined;
  const { body } = await api('/api/record', {
    method: 'POST',
    body: JSON.stringify(Object.assign({}, pending.payload, {
      supersedes, dispute: mode === 'dispute',
    })),
  });
  if (!body.ok) { toast(body.error, true); return; }
  $('#fText').value = '';
  $('#recordBtn').disabled = true;
  hideConflict();
  toast(mode === 'supersede'
    ? t('supersededOk')(body.receipt.superseded_claims.map(shortId).join(', '))
    : t('recorded')(shortId(body.receipt.claim_id)));
  refresh();
}

/* ------------------------------------------------------------ when / at */

function wireWhen() {
  const select = $('#whenSelect');
  const dateEl = $('#whenDate');
  select.addEventListener('change', () => {
    if (select.value === '__date') { dateEl.hidden = false; dateEl.focus(); return; }
    dateEl.hidden = true;
    S.at = select.value;
    refresh();
  });
  dateEl.addEventListener('change', () => {
    if (!dateEl.value) { S.at = ''; refresh(); return; }
    S.at = `${dateEl.value}T00:00:00Z`;
    refresh();
  });
}

/* ------------------------------------------------------------- developer */

function wireDev() {
  $('#devToggle').addEventListener('click', () => {
    const drawer = $('#devDrawer');
    drawer.hidden = !drawer.hidden;
    if (!drawer.hidden && !$('#devEvidenceOut').textContent) loadEvidence();
  });
  $$('#devTabs .dev__tab').forEach(tab => {
    tab.addEventListener('click', () => {
      $$('#devTabs .dev__tab').forEach(x => x.classList.toggle('is-on', x === tab));
      $$('.dev__panel').forEach(p => { p.hidden = p.id !== 'dev-' + tab.dataset.dev; });
    });
  });
  $('#devSearchBtn').addEventListener('click', runSearch);
  $('#devQ').addEventListener('keydown', e => { if (e.key === 'Enter') runSearch(); });
  $('#devCtxBtn').addEventListener('click', runContext);
  $('#devBriefBtn').addEventListener('click', async () => {
    const at = S.at ? `&at=${encodeURIComponent(S.at)}` : '';
    const { body } = await api(`/api/brief?max_bytes=${S.budget}${at}`);
    if (body.ok) $('#devBriefWire').textContent = body.wire;
  });
  $('#devBackupBtn').addEventListener('click', async () => {
    const { body } = await api('/api/backup', { method: 'POST', body: '{}' });
    toast(body.ok ? t('backupDone') : body.error, !body.ok);
  });
  $('#devAuditBtn').addEventListener('click', async () => {
    const { body } = await api('/api/audit');
    if (!body.ok) { toast(body.error, true); return; }
    $('#devSafetyOut').innerHTML = `<pre>${esc(JSON.stringify(body.entries.slice(0, 5), null, 1))}</pre>`;
  });
  $('#devRedactBtn').addEventListener('click', async () => {
    const claim_id = $('#devRedactId').value.trim();
    if (!claim_id) return;
    const { body } = await api('/api/redact', {
      method: 'POST', body: JSON.stringify({ claim_id, confirm: true }),
    });
    toast(body.ok ? t('redact') + ' · ' + shortId(claim_id) : body.error, !body.ok);
    if (body.ok) refresh();
  });
  $('#devResetBtn').addEventListener('click', async () => {
    const { body } = await api('/api/reset', { method: 'POST', body: '{}' });
    toast(body.ok ? t('resetDone') : body.error, !body.ok);
    if (body.ok) { await refresh(); wireComposer(); }
  });
}

async function runSearch() {
  const q = $('#devQ').value.trim();
  const raw = $('#devRaw').checked ? 1 : 0;
  const { body } = await api(`/api/search?q=${encodeURIComponent(q)}&include_superseded=${raw}`);
  if (!body.ok) { toast(body.error, true); return; }
  const note = body.stale_in_results > 0
    ? `<p class="dev__hint">⚠ ${body.stale_in_results} 条已替代的结果混进来了——这就是要解决的失败模式。</p>`
    : '';
  $('#devSearchOut').innerHTML = note + body.results.slice(0, 8).map(r =>
    `<div class="hit"><b>#${r.rank} · ${r.score}</b>${esc(r.text)} <span class="claim__topic">${esc(r.status)}</span></div>`
  ).join('');
}

async function runContext() {
  const q = $('#devCtxQ').value.trim();
  const intent = $('#devCtxIntent').value;
  const { body } = await api(`/api/context?q=${encodeURIComponent(q)}&intent=${intent}`);
  if (!body.ok) { toast(body.error, true); return; }
  $('#devCtxOut').innerHTML = `<pre>${esc(body.wire)}</pre>`;
}

async function loadEvidence() {
  const { body } = await api('/api/evidence');
  if (!body.ok) return;
  const methods = body.retrieval.methods || [];
  $('#devEvidenceOut').innerHTML =
    '<table><tr><th>method</th><th>R@1</th><th>R@5</th><th>MRR</th><th>stale@5</th></tr>' +
    methods.map(m => `<tr><td>${esc(m.label)}</td><td>${m.recall1 ?? '—'}</td><td>${m.recall5 ?? '—'}</td>` +
      `<td>${m.mrr ?? '—'}</td><td>${m.stale5 ?? '—'}</td></tr>`).join('') +
    '</table><p class="dev__hint">synthetic fixture · every number replayed in CI · 0 model calls</p>';
}

/* --------------------------------------------------------------- preview */

async function previewProposal() {
  const text = $('#fText').value.trim();
  if (!text) return;
  const { body } = await api('/api/suggest', {
    method: 'POST',
    body: JSON.stringify({ text, topic: $('#fTopic').value.trim() || 'general' }),
  });
  if (!body.ok) { toast(body.error, true); return; }
  toast(t('previewDone') + ' · ' + shortId(body.proposal.claim_id || ''));
}

/* ------------------------------------------------------------------ boot */

async function boot() {
  applyI18n();
  setTimeout(() => document.body.classList.remove('first-paint'), 700);
  wireWhen();
  wireDev();
  $('#langBtn').addEventListener('click', () => {
    S.lang = S.lang === 'zh' ? 'en' : 'zh';
    localStorage.setItem(LANG_KEY, S.lang);
    applyI18n();
    renderTimeline();
    wireComposer();
  });
  $('#pastToggle').addEventListener('click', () => {
    S.pastOpen = !S.pastOpen;
    $('#listPast').hidden = !S.pastOpen;
    $('#pastToggle').classList.toggle('is-open', S.pastOpen);
  });
  $('#budgetRange').addEventListener('input', (ev) => {
    S.budget = Number(ev.target.value);
    $('#budgetMax').textContent = S.budget;
    renderBudgetSoon();
  });
  $('#conflictSupersede').addEventListener('click', () => resolveConflict('supersede'));
  $('#conflictDispute').addEventListener('click', () => resolveConflict('dispute'));
  $('#conflictCancel').addEventListener('click', hideConflict);
  $('#previewBtn').addEventListener('click', previewProposal);

  await refresh();
  wireComposer();
}

let _budgetTimer = null;
function renderBudgetSoon() {
  clearTimeout(_budgetTimer);
  _budgetTimer = setTimeout(refresh, 220);
}

boot();
