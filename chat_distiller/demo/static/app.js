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

const I18N = {
  zh: {
    lede: '周五在豆包定下的方案，周一的 Codex 接着干。这个页面就是两台 Agent 之间那份「什么才算数」。',
    now: '现在', pickDate: '选一个日期…', time: '时间',
    brief: '开工简报', current: '现在什么算数', attention: '需要你', past: '已替代',
    empty: '还没有任何决定。记下第一条。',
    omit: n => `预算不够，如实省略 ${n} 条`,
    record: '记录', topic: '主题', cancel: '取消',
    placeholder: '记一条决定…',
    note: '写入真实的 JSONL 台账 · 冲突会被拒绝并摊开',
    conflictTitle: '这条和现行决定撞上了',
    conflictHint: '台账不悄悄改写历史。你来定：新的替代旧的，还是先记为有争议？',
    supersede: '替代旧的', disputeBtn: '记为有争议',
    examples: { conflict: '试一条冲突', clean: '记一条普通的', dispute: '试一条争议', premise: '抽掉前提' },
    needYouHint: '这些不能冒充定论：争议待收场，或前提已坍塌待复审。',
    resolve: '收场', sustain: '维持异议', withdraw: '撤回', newDecision: '新决定…', confirm: '收场',
    resolveHintNoTarget: '这条争议没有对立的现行决定：可以维持它，或用一条新决定收场。',
    brokenDeps: '前提已坍塌', disputedBadge: '有争议', unmotivatedBadge: '待复审',
    doubao: '豆包导入', source: '出处', recordedAt: '记录于', quote: '原话',
    id: 'ID', dependsOn: '依赖前提', supersededBy: '被替代为',
    recorded: id => `已记录 ${id}`, supersededOk: ids => `已替代 ${ids}`,
    resolvedOk: '争议已收场',
    dev: '开发者视图 ▾', search: '检索', context: 'Context / RAG', rawBrief: '原始简报',
    evidence: '证据', safety: '安全', rerender: '重新渲染',
    rawToggle: '关掉状态过滤（模拟把历史喂回去）',
    buildCtx: '构建证据包', searchBtn: '检索',
    redact: '脱敏（保留墓碑）', backup: '备份', audit: '审计', resetDemo: '重置演示',
    preview: '预览提案（不写入）', previewDone: '提案已生成，未写入台账',
    resetDone: '演示已重置', backupDone: '备份完成', auditTitle: '审计记录',
    atPrefix: d => `${d} 当时算数`, notYet: '尚未记录',
    doubaoLede: '豆包导入',
  },
  en: {
    lede: 'What Doubao decided on Friday, Codex picks up on Monday. This page is the “what still counts” between two agents.',
    now: 'Now', pickDate: 'Pick a date…', time: 'When',
    brief: 'Handoff brief', current: 'What counts now', attention: 'Needs you', past: 'Superseded',
    empty: 'No decisions yet. Record the first one.',
    omit: n => `${n} omitted — the budget is honest`,
    record: 'Record', topic: 'topic', cancel: 'Cancel',
    placeholder: 'Record one decision…',
    note: 'Writes a real JSONL line · conflicts are refused, not merged',
    conflictTitle: 'This collides with a standing decision',
    conflictHint: 'The ledger never rewrites history silently. Your call: replace the old one, or record as disputed.',
    supersede: 'Replace the old', disputeBtn: 'Record as disputed',
    examples: { conflict: 'Try a conflict', clean: 'A clean one', dispute: 'Try a dispute', premise: 'Pull the premise' },
    needYouHint: 'These must not pass as settled: open disputes, or decisions whose premise has fallen.',
    resolve: 'Resolve', sustain: 'Sustain', withdraw: 'Withdraw', newDecision: 'New decision…', confirm: 'Resolve',
    resolveHintNoTarget: 'This dispute has no standing target: sustain it, or close it with a new decision.',
    brokenDeps: 'premise fell', disputedBadge: 'disputed', unmotivatedBadge: 'review',
    doubao: 'Doubao import', source: 'Source', recordedAt: 'Recorded', quote: 'Quote',
    id: 'ID', dependsOn: 'Depends on', supersededBy: 'Superseded by',
    recorded: id => `recorded ${id}`, supersededOk: ids => `superseded ${ids}`,
    resolvedOk: 'dispute resolved',
    dev: 'Developer views ▾', search: 'Search', context: 'Context / RAG', rawBrief: 'Raw brief',
    evidence: 'Evidence', safety: 'Safety', rerender: 'Render',
    rawToggle: 'status filter off (feeding history back)',
    buildCtx: 'Build packet', searchBtn: 'Search',
    redact: 'Redact (tombstone)', backup: 'Backup', audit: 'Audit', resetDemo: 'Reset demo',
    preview: 'Preview proposal (no write)', previewDone: 'Proposal generated; nothing written',
    resetDone: 'demo reset', backupDone: 'backup done', auditTitle: 'Audit log',
    atPrefix: d => `What counted on ${d}`, notYet: 'not yet recorded',
    doubaoLede: 'Doubao import',
  },
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
  $('#lede').textContent = T.lede;
  $('#budgetName').textContent = T.brief;
  $('#currentTitle').textContent = T.current;
  $('#attentionTitle').textContent = T.attention;
  $('#pastTitle').textContent = T.past;
  $('#timelineEmpty').textContent = T.empty;
  $('#whenLabel').textContent = T.time;
  $('#conflictTitle').textContent = T.conflictTitle;
  $('#conflictHint').textContent = T.conflictHint;
  $('#conflictSupersede').textContent = T.supersede;
  $('#conflictDispute').textContent = T.disputeBtn;
  $('#conflictCancel').textContent = T.cancel;
  $('#recordBtn').textContent = T.record;
  $('#fText').placeholder = T.placeholder;
  $('#composerNote').textContent = T.note;
  $('#previewBtn').textContent = T.preview;
  $('#devToggle').textContent = T.dev;
  $('#devRawLabel').textContent = T.rawToggle;
  $('#devSearchBtn').textContent = T.searchBtn;
  $('#devCtxBtn').textContent = T.buildCtx;
  $('#devBriefBtn').textContent = T.rerender;
  $('#devRedactBtn').textContent = T.redact;
  $('#devBackupBtn').textContent = T.backup;
  $('#devAuditBtn').textContent = T.audit;
  $('#devResetBtn').textContent = T.resetDemo;
  $$('#devTabs .dev__tab').forEach(tab => {
    const map = { search: 'search', context: 'context', brief: 'rawBrief', evidence: 'evidence', safety: 'safety' };
    tab.textContent = T[map[tab.dataset.dev]];
  });
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
