"""The console page template, kept separate from the server for readability."""

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>ClaimLedger</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root {
    --bg: #ffffff; --side: #f6f6f7; --card: #ffffff; --border: #e6e6e6;
    --text: #1a1a1a; --muted: #6b6b6b; --faint: #9a9a9a;
    --accent: #10a37f; --accent-soft: #e8f7f1;
    --warn-bg: #fff8eb; --warn-border: #f5d98a; --warn-text: #92690a;
    --danger-bg: #fef2f2; --danger-border: #fecaca; --danger-text: #b91c1c;
    --radius: 12px; --radius-sm: 8px;
    --mono: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
    --sans: -apple-system, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
  }
  [data-theme="dark"] {
    --bg: #0f0f0f; --side: #171717; --card: #1e1e1e; --border: #2f2f2f;
    --text: #f2f2f2; --muted: #9a9a9a; --faint: #666;
    --accent: #10a37f; --accent-soft: #0d2818;
    --warn-bg: #2a2210; --warn-border: #5a4a1a; --warn-text: #e5c04a;
    --danger-bg: #2a1515; --danger-border: #5a2a2a; --danger-text: #f87171;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; }
  body { font-family: -apple-system,'Segoe UI','Helvetica Neue',Arial,sans-serif;
         background: var(--bg); color: var(--text); overflow: hidden; }
  .shell { display: flex; height: 100vh; }

  /* ---------- sidebar ---------- */
  .side { width: 264px; flex-shrink: 0; background: var(--side);
          border-right: 1px solid var(--border); display: flex;
          flex-direction: column; }
  .brand { display: flex; align-items: center; gap: 9px; padding: 16px 16px 12px;
           font-weight: 650; font-size: 14px; }
  .brand svg { width: 24px; height: 24px; }
  .new-btn { margin: 0 12px 12px; padding: 9px 12px; border: 1px solid var(--border);
             background: var(--card); color: var(--text); border-radius: 9px;
             font: 500 13px var(--sans); cursor: pointer; text-align: left; }
  .new-btn:hover { border-color: var(--text); }
  .agents { padding: 0 8px 6px; }
  .agent { display: flex; align-items: center; gap: 6px; padding: 6px 9px;
           border-radius: 8px; cursor: pointer; font-size: 12px; }
  .agent:hover { background: rgba(0,0,0,.04); }
  [data-theme="dark"] .agent:hover { background: rgba(255,255,255,.05); }
  .agent.sel { background: var(--accent-soft); }
  .agent .kind { font: 9.5px var(--mono); color: var(--faint); }
  .agent .unreg { font: 9.5px var(--mono); color: var(--warn-text); }
  .agent .count { margin-left: auto; font: 10px var(--mono); color: var(--faint); }
  .agent-reg { display: flex; gap: 4px; padding: 0 8px 10px; }
  .agent-reg input { flex: 1; min-width: 0; font: 11px var(--sans);
                     border: 1px solid var(--border); border-radius: 6px;
                     padding: 4px 6px; background: var(--card); color: var(--text);
                     outline: none; }
  .agent-reg input:focus { border-color: var(--accent); }
  .agent-reg select { font: 10.5px var(--sans); border: 1px solid var(--border);
                      border-radius: 6px; background: var(--card); color: var(--text); }
  .agent-reg button { font: 500 10.5px var(--sans); padding: 4px 7px;
                      border-radius: 6px; border: 1px solid var(--border);
                      background: var(--card); color: var(--muted); cursor: pointer; }
  .agent-reg button:hover { border-color: var(--accent); color: var(--accent); }
  .side-label { padding: 4px 16px 6px; font: 600 10px var(--sans);
                text-transform: uppercase; letter-spacing: .6px; color: var(--faint); }
  .history { flex: 1; overflow-y: auto; padding: 0 8px 8px; }
  .hist { padding: 8px 9px; border-radius: 8px; cursor: pointer; margin-bottom: 2px; }
  .hist:hover { background: rgba(0,0,0,.04); }
  [data-theme="dark"] .hist:hover { background: rgba(255,255,255,.05); }
  .hist.active { background: var(--accent-soft); }
  .hist .t { font-size: 12.5px; line-height: 1.35; overflow: hidden;
             display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
  .hist .m { margin-top: 3px; font: 10.5px var(--mono); color: var(--faint);
             display: flex; gap: 6px; align-items: center; }
  .hist .badge { color: var(--danger-text); }
  .hist .deg { color: var(--warn-text); }
  .side-foot { border-top: 1px solid var(--border); padding: 10px 12px 12px; }
  .add-rec { display: flex; gap: 5px; margin-bottom: 10px; }
  .add-rec input { flex: 1; min-width: 0; font: 11.5px var(--sans);
                   border: 1px solid var(--border); border-radius: 7px;
                   padding: 5px 7px; background: var(--card); color: var(--text);
                   outline: none; }
  .add-rec input:focus { border-color: var(--accent); }
  .add-rec button { font: 500 11px var(--sans); padding: 5px 8px; border-radius: 7px;
                    border: 1px solid var(--border); background: var(--card);
                    color: var(--muted); cursor: pointer; }
  .add-rec button:hover { border-color: var(--accent); color: var(--accent); }
  .chains { font: 10.5px var(--mono); color: var(--muted); display: flex;
            flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
  .chains .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent);
                 display: inline-block; margin-right: 3px; }
  .cal-mini { font: 10.5px var(--mono); color: var(--muted); }
  .cal-mini b { color: var(--text); font-weight: 650; }

  /* ---------- main ---------- */
  .main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
  .topbar { height: 48px; flex-shrink: 0; display: flex; align-items: center;
            justify-content: space-between; padding: 0 18px;
            border-bottom: 1px solid var(--border); }
  .topbar .title { font: 500 12.5px var(--sans); color: var(--muted);
                   white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .topbar .right { display: flex; gap: 8px; align-items: center; }
  .icon-btn { width: 30px; height: 30px; border: 1px solid var(--border);
              border-radius: 8px; background: transparent; color: var(--text);
              cursor: pointer; font-size: 13px; }
  .icon-btn:hover { border-color: var(--text); }

  .canvas { flex: 1; overflow-y: auto; padding: 26px 22px 12px; }
  .canvas-inner { max-width: 700px; margin: 0 auto; }
  .empty-state { height: 100%; display: flex; flex-direction: column;
                 align-items: center; justify-content: center; gap: 10px;
                 color: var(--faint); text-align: center; padding-bottom: 40px; }
  .empty-state h2 { font: 600 17px var(--sans); color: var(--muted); }
  .empty-state p { font-size: 13px; max-width: 360px; line-height: 1.5; }

  .card { background: var(--card); border: 1px solid var(--border);
          border-radius: var(--radius); margin-bottom: 14px; overflow: hidden;
          animation: fadeIn .25s ease; }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); }
                      to { opacity: 1; transform: none; } }
  .card-head { padding: 11px 15px; border-bottom: 1px solid var(--border);
               font: 600 12.5px var(--sans); display: flex; align-items: center;
               justify-content: space-between; }
  .card-head .sub { font: 10.5px var(--mono); color: var(--faint); font-weight: 400; }
  .card-body { padding: 13px 15px; }

  .section { border-radius: var(--radius-sm); padding: 11px 13px; margin-bottom: 9px; }
  .section:last-child { margin-bottom: 0; }
  .section.active { background: var(--accent-soft); border: 1px solid #c3e6d8; }
  .section.review { background: var(--warn-bg); border: 1px solid var(--warn-border); }
  .section.conflict { background: var(--danger-bg); border: 1px solid var(--danger-border); }
  .section.degraded { background: var(--side); border: 1px solid var(--border); }
  .section-title { font: 600 11px var(--sans); text-transform: uppercase;
                   letter-spacing: .4px; margin-bottom: 5px; }
  .section.active .section-title { color: #0d7a5f; }
  .section.review .section-title { color: var(--warn-text); }
  .section.conflict .section-title { color: var(--danger-text); }
  .section.degraded .section-title { color: var(--muted); }
  .section ul { list-style: none; }
  .section li { padding: 3px 0; font-size: 13px; line-height: 1.45; }

  .pill { display: inline-block; font: 600 9.5px var(--sans); text-transform: uppercase;
          letter-spacing: .3px; padding: 2px 6px; border-radius: 99px; }
  .pill.green { background: #c3e6d8; color: #0d7a5f; }
  .pill.amber { background: #fde9c3; color: var(--warn-text); }
  .pill.red { background: #fecaca; color: var(--danger-text); }
  .pill.gray { background: #e5e5e5; color: var(--muted); }
  [data-theme="dark"] .pill.green { background: #0d2818; color: #34d399; }
  [data-theme="dark"] .pill.amber { background: #2a2210; color: #fbbf24; }
  [data-theme="dark"] .pill.red { background: #2a1515; color: #f87171; }
  [data-theme="dark"] .pill.gray { background: #333; color: #9a9a9a; }

  .rec { display: flex; align-items: flex-start; gap: 10px; padding: 9px 0;
         border-bottom: 1px solid var(--border); }
  .rec:last-child { border-bottom: none; }
  .rec .body { flex: 1; min-width: 0; }
  .rec .text { font-size: 13px; line-height: 1.45; }
  .rec .flags { margin-top: 3px; display: flex; gap: 5px; align-items: center;
                flex-wrap: wrap; }
  .rec .p { font: 10px var(--mono); color: var(--faint); }
  .rec .out { display: flex; gap: 5px; flex-shrink: 0; }
  .rec .out button { font: 500 10.5px var(--sans); padding: 3px 8px;
                     border-radius: 99px; border: 1px solid var(--border);
                     background: var(--card); color: var(--muted); cursor: pointer; }
  .rec .out button:hover { border-color: var(--text); color: var(--text); }

  /* ---------- composer ---------- */
  .composer-wrap { flex-shrink: 0; padding: 8px 22px 16px; }
  .composer { max-width: 700px; margin: 0 auto; background: var(--card);
              border: 1px solid var(--border); border-radius: 14px;
              box-shadow: 0 2px 10px rgba(0,0,0,.05); padding: 6px;
              display: flex; gap: 8px; align-items: flex-end; }
  .composer:focus-within { border-color: var(--accent); }
  .composer textarea { flex: 1; border: none; outline: none; resize: none;
                       background: transparent; color: var(--text);
                       font: 14px/1.45 var(--sans); padding: 8px 10px;
                       min-height: 40px; max-height: 140px; }
  .composer textarea::placeholder { color: var(--faint); }
  .composer .send { width: 34px; height: 34px; border: none; border-radius: 9px;
                    background: var(--text); color: var(--bg); cursor: pointer;
                    font-size: 15px; display: flex; align-items: center;
                    justify-content: center; }
  .composer .send:disabled { opacity: .45; cursor: default; }
  .composer-meta { max-width: 700px; margin: 6px auto 0; font: 10.5px var(--mono);
                   color: var(--faint); display: flex; justify-content: space-between; }
  .spinner { display: inline-block; width: 13px; height: 13px;
             border: 2px solid var(--border); border-top-color: var(--text);
             border-radius: 50%; animation: spin .6s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .hidden { display: none !important; }
  @media (max-width: 760px) { .side { display: none; } }
</style></head><body>
<div class="shell">
  <aside class="side">
    <div class="brand">
      <svg viewBox="0 0 256 256"><rect x="28" y="28" width="200" height="200" rx="30" fill="none" stroke="currentColor" stroke-width="14"/><line x1="58" y1="82" x2="70" y2="82" stroke="currentColor" stroke-width="10"/><line x1="58" y1="130" x2="70" y2="130" stroke="currentColor" stroke-width="10"/><line x1="58" y1="178" x2="70" y2="178" stroke="currentColor" stroke-width="10"/><rect x="76" y="68" width="112" height="28" rx="9" fill="currentColor"/><rect x="76" y="116" width="72" height="28" rx="9" fill="currentColor"/><rect x="76" y="164" width="36" height="28" rx="9" fill="currentColor"/><circle cx="200" cy="200" r="50" fill="#10a37f"/><polyline points="179,201 194,216 222,187" fill="none" stroke="#fff" stroke-width="14" stroke-linecap="round" stroke-linejoin="round"/></svg>
      ClaimLedger
    </div>
    <button class="new-btn" onclick="newTask()">+ New task</button>
    <div class="side-label">Agents</div>
    <div class="agents" id="agents"></div>
    <div class="agent-reg">
      <input id="agent-name" placeholder="name">
      <select id="agent-kind"><option value="agent">agent</option><option value="human">human</option></select>
      <button onclick="registerAgent()" title="register identity">+</button>
    </div>
    <div class="side-label">History</div>
    <div class="history" id="history"></div>
    <div class="side-foot">
      <div class="add-rec">
        <input id="new-text" placeholder="record a decision…">
        <button onclick="addRecord()">+</button>
      </div>
      <div class="chains" id="chains"></div>
      <div class="cal-mini" id="cal-mini">calibration: no scored outcomes yet</div>
    </div>
  </aside>

  <main class="main">
    <div class="topbar">
      <div class="title" id="top-title">New task</div>
      <div class="right">
        <button class="icon-btn" onclick="toggleTheme()" title="toggle theme">◐</button>
      </div>
    </div>
    <div class="canvas" id="canvas">
      <div class="canvas-inner" id="canvas-inner">
        <div class="empty-state">
          <h2>What should the agent do?</h2>
          <p>Describe a task. The memory layer selects the relevant records,
             judges which constraints still apply, and returns a brief.</p>
        </div>
      </div>
    </div>
    <div class="composer-wrap">
      <div class="composer">
        <textarea id="task" rows="1" placeholder="Describe a task…  (⌘↵ to judge)" autofocus></textarea>
        <button class="send" id="send" onclick="decide()" title="judge">↑</button>
      </div>
      <div class="composer-meta">
        <span id="meta-left">jev-first memory · model proposes, the ledger decides</span>
        <span id="meta-right"></span>
      </div>
    </div>
  </main>
</div>

<script>
let current = null;        // the judgment being shown
let agents = [];           // registered identities
let currentAgent = localStorage.getItem("agent") || null;
let historyCache = [];     // sidebar items, newest first
const $ = id => document.getElementById(id);
const esc = s => { const d = document.createElement("div"); d.textContent = s ?? ""; return d.innerHTML; };

function toggleTheme() {
  const h = document.documentElement;
  const next = h.getAttribute("data-theme") === "dark" ? "" : "dark";
  h.setAttribute("data-theme", next);
  localStorage.setItem("theme", next);
}
(function() {
  const saved = localStorage.getItem("theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  if (saved === "dark" || (!saved && prefersDark))
    document.documentElement.setAttribute("data-theme", "dark");
})();

$("task").addEventListener("keydown", e => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") decide();
});
$("task").addEventListener("input", e => {
  e.target.style.height = "auto";
  e.target.style.height = Math.min(e.target.scrollHeight, 140) + "px";
});

async function api(path, body) {
  const opt = body ? {method: "POST", headers: {"Content-Type": "application/json"},
                      body: JSON.stringify(body)} : {};
  const res = await fetch(path, opt);
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  return data;
}

function newTask() {
  current = null;
  $("canvas-inner").innerHTML =
    '<div class="empty-state"><h2>What should the agent do?</h2>' +
    '<p>Describe a task. The memory layer selects the relevant records, ' +
    'judges which constraints still apply, and returns a brief.</p></div>';
  $("top-title").textContent = "New task";
  $("meta-right").textContent = "";
  document.querySelectorAll(".hist").forEach(el => el.classList.remove("active"));
  $("task").focus();
}

async function loadAgents() {
  agents = await api("/api/agents");
  if (!currentAgent && agents.length) {
    currentAgent = agents[0].name;
    localStorage.setItem("agent", currentAgent);
  }
  const el = $("agents");
  if (!agents.length) {
    el.innerHTML = '<div style="padding:6px 9px;font-size:11px;color:var(--faint)">no identities yet</div>';
    return;
  }
  el.innerHTML = agents.map(a => {
    const sel = currentAgent === a.name ? " sel" : "";
    const marker = a.registered
      ? `<span class="kind">${esc(a.kind)}</span>`
      : '<span class="unreg">unregistered</span>';
    const safe = String(a.name).replace(/'/g, "");
    return `<div class="agent${sel}" onclick="selectAgent('${safe}')">` +
      `<span>${esc(a.name)}</span>${marker}` +
      `<span class="count">${a.records}</span></div>`;
  }).join("");
}

function selectAgent(name) {
  currentAgent = name;
  localStorage.setItem("agent", name);
  loadAgents();
}

async function registerAgent() {
  const name = $("agent-name").value.trim();
  if (!name) return;
  try {
    await api("/api/agents", {name: name, kind: $("agent-kind").value});
    $("agent-name").value = "";
    currentAgent = name;
    localStorage.setItem("agent", name);
    await loadAgents();
    refreshSide();
  } catch (e) {
    $("meta-right").textContent = "register: " + e.message;
  }
}

async function loadHistory() {
  historyCache = await api("/api/history?limit=40");
  const el = $("history");
  if (!historyCache.length) {
    el.innerHTML = '<div style="padding:8px 9px;font-size:11.5px;color:var(--faint)">no judgments yet</div>';
    return;
  }
  el.innerHTML = historyCache.map(j => {
    const time = (j.created_at || "").slice(5, 16).replace("T", " ");
    const conflict = (j.conflicts || []).length
      ? `<span class="badge">${j.conflicts.length} ⟂</span>` : "";
    const deg = j.degraded ? '<span class="deg">⚠</span>' : "";
    const active = current && current.judgment_hash === j.judgment_hash ? " active" : "";
    return `<div class="hist${active}" data-hash="${j.judgment_hash}" onclick="selectJudgment('${j.judgment_hash}')">` +
      `<div class="t">${esc(j.task)}</div>` +
      `<div class="m"><span>${time}</span>${conflict}${deg}</div></div>`;
  }).join("");
}

function selectJudgment(hash) {
  const j = historyCache.find(x => x.judgment_hash === hash);
  if (!j) return;
  current = j;
  render(j);
  document.querySelectorAll(".hist").forEach(el =>
    el.classList.toggle("active", el.dataset.hash === hash));
  $("top-title").textContent = j.task;
}

async function decide() {
  const task = $("task").value.trim();
  if (!task) return;
  $("send").disabled = true;
  $("send").innerHTML = '<span class="spinner"></span>';
  try {
    const j = await api("/api/decide?task=" + encodeURIComponent(task));
    current = j;
    render(j);
    $("top-title").textContent = task;
    $("meta-right").textContent =
      `${j.model} · ${j.requests} req · ${j.latency_ms} ms · ${String(j.judgment_hash).slice(0,10)}…` +
      (j.degraded ? " · degraded" : "");
    $("task").value = "";
    $("task").style.height = "auto";
    await loadHistory();
    refreshSide();
  } catch (e) {
    $("meta-right").textContent = "error: " + e.message;
  } finally {
    $("send").disabled = false;
    $("send").textContent = "↑";
  }
}

function render(j) {
  const byId = Object.fromEntries((j.entries || []).map(e => [e.record_id, e]));
  const admitted = (j.entries || []).filter(e => e.action === "admit" && e.included);
  const review = (j.entries || []).filter(e => e.action === "review" && e.included);
  const conflicts = j.conflicts || [];
  const outcomes = j.outcomes || {};
  let html = "";

  html += '<div class="card"><div class="card-head">Brief</div><div class="card-body">';
  html += admitted.length
    ? '<div class="section active"><div class="section-title">✓ Active constraints</div><ul>' +
      admitted.map(e => `<li>${esc(e.text)}${e.governing ? ' <span class="pill green">governing</span>' : ""}${e.low_margin ? ' <span class="pill amber">thin margin</span>' : ""}</li>`).join("") + "</ul></div>"
    : '<div class="section active"><div class="section-title">✓ Active constraints</div>' +
      '<div style="font-size:12.5px;color:var(--muted)">none admitted for this task.</div></div>';
  if (review.length) {
    html += '<div class="section review"><div class="section-title">⚠ Needs human review</div><ul>' +
      review.map(e => `<li>${esc(e.text)} <span class="pill amber">${e.conflicted ? "conflict" : e.low_margin ? "thin margin" : "review"}</span></li>`).join("") + "</ul></div>";
  }
  if (conflicts.length) {
    html += '<div class="section conflict"><div class="section-title">⛔ Unresolved conflicts</div><ul>' +
      conflicts.map(p => `<li>${esc(byId[p[0]]?.text || p[0])} <span style="color:var(--danger-text)">⟂</span> ${esc(byId[p[1]]?.text || p[1])}</li>`).join("") + "</ul></div>";
  }
  if (j.degraded) {
    html += '<div class="section degraded"><div class="section-title">⚠ Degraded</div>' +
      '<div style="font-size:12.5px">Judge unreachable — every record is review.</div></div>';
  }
  html += "</div></div>";

  const order = {admit: 0, review: 1, exclude: 2};
  const sorted = [...(j.entries || [])].sort((a, b) =>
    (order[a.action] - order[b.action]) || ((b.p_admit ?? 0) - (a.p_admit ?? 0)));
  html += '<div class="card"><div class="card-head">Records &amp; outcomes' +
    '<span class="sub">click a verdict to calibrate</span></div><div class="card-body">';
  html += sorted.map(e => {
    const cls = e.action === "admit" ? "green" : e.action === "review" ? "amber" : "gray";
    const flags = [
      e.governing ? '<span class="pill green">governing</span>' : "",
      e.conflicted ? '<span class="pill red">conflicted</span>' : "",
      e.low_margin ? '<span class="pill amber">thin margin</span>' : ""
    ].filter(Boolean).join(" ");
    const outcome = outcomes[e.record_id];
    const buttons = outcome
      ? `<span class="pill ${outcome === "upheld" ? "green" : outcome === "overturned" ? "red" : "gray"}">${outcome}</span>`
      : ["upheld", "overturned", "unclear"].map(v =>
          `<button onclick="postOutcome('${e.record_id}','${v}')">${v}</button>`).join(" ");
    return `<div class="rec"><div class="body"><div class="text">${esc(e.text)}</div>` +
      `<div class="flags"><span class="pill ${cls}">${e.action}</span>` +
      `<span class="p">p(admit) ${e.p_admit ?? "—"}</span>${flags}</div></div>` +
      `<div class="out">${buttons}</div></div>`;
  }).join("");
  html += "</div></div>";

  $("canvas-inner").innerHTML = html;
  $("canvas").scrollTop = 0;
}

async function postOutcome(recordId, verdict) {
  if (!current) return;
  await api("/api/outcome", {record_id: recordId, verdict: verdict,
                             judgment_hash: current.judgment_hash, by: currentAgent || "console-human"});
  current.outcomes = current.outcomes || {};
  current.outcomes[recordId] = verdict;
  render(current);
  await loadHistory();
  refreshSide();
}

async function addRecord() {
  const text = $("new-text").value.trim();
  if (!text) return;
  await api("/api/record", {text: text, source: currentAgent || "console"});
  $("new-text").value = "";
  refreshSide();
}

async function refreshSide() {
  const c = await api("/api/audit");
  $("chains").innerHTML =
    `<span><span class="dot"></span>${c.records} records</span>` +
    `<span><span class="dot"></span>${c.judgments} judgments</span>` +
    `<span><span class="dot"></span>${c.outcomes} outcomes</span>` +
    (c.degraded ? `<span style="color:var(--warn-text)">⚠ ${c.degraded}</span>` : "");
  const r = await api("/api/calibrate");
  if (r.n_scored) {
    const authors = Object.entries(r.by_author || {})
      .map(([a, d]) => `${esc(a)} ${d.n}·${d.upheld_rate}`)
      .slice(0, 3).join(" · ");
    $("cal-mini").innerHTML =
      `calibration: <b>${r.n_scored}</b> scored · upheld <b>${r.overall_upheld_rate}</b> · Brier <b>${r.brier}</b>` +
      (authors ? `<div style="margin-top:3px">by author: ${authors}</div>` : "");
  } else {
    $("cal-mini").innerHTML =
      `calibration: no scored outcomes yet (${r.n_outcomes} recorded, ${r.unsupported} on review)`;
  }
}

loadAgents();
loadHistory();
refreshSide();
</script></body></html>"""