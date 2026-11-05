"""The console page template, kept separate from the server for readability.

Design record: docs/console-design.md. The page serves five user jobs:
ask what applies, record a decision, review a verdict, check calibration,
and look back at yesterday. Anything that serves none of them is absent.
"""

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

  /* sidebar */
  .side { width: 250px; flex-shrink: 0; background: var(--side);
          border-right: 1px solid var(--border); display: flex; flex-direction: column; }
  .brand { display: flex; align-items: center; gap: 9px; padding: 16px 16px 12px;
           font-weight: 650; font-size: 14px; }
  .brand svg { width: 24px; height: 24px; }
  .new-btn { margin: 0 12px 12px; padding: 9px 12px; border: 1px solid var(--border);
             background: var(--card); color: var(--text); border-radius: 9px;
             font: 500 13px var(--sans); cursor: pointer; text-align: left; }
  .new-btn:hover { border-color: var(--text); }
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
  .chains { font: 10.5px var(--mono); color: var(--muted); display: flex;
            flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
  .chains .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent);
                 display: inline-block; margin-right: 3px; }
  .settings-toggle { width: 100%; text-align: left; background: none; border: none;
                     color: var(--muted); font: 500 11.5px var(--sans);
                     cursor: pointer; padding: 4px 0; }
  .settings-toggle:hover { color: var(--text); }
  .settings { padding-top: 6px; }
  .agent { display: flex; align-items: center; gap: 6px; padding: 5px 6px;
           border-radius: 7px; cursor: pointer; font-size: 11.5px; }
  .agent:hover { background: rgba(0,0,0,.04); }
  [data-theme="dark"] .agent:hover { background: rgba(255,255,255,.05); }
  .agent.sel { background: var(--accent-soft); }
  .agent .kind { font: 9.5px var(--mono); color: var(--faint); }
  .agent .unreg { font: 9.5px var(--mono); color: var(--warn-text); }
  .agent .count { margin-left: auto; font: 10px var(--mono); color: var(--faint); }
  .agent-reg { display: flex; gap: 4px; padding: 6px 0 2px; }
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

  /* main */
  .main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
  .topbar { height: 48px; flex-shrink: 0; display: flex; align-items: center;
            justify-content: space-between; padding: 0 14px 0 18px;
            border-bottom: 1px solid var(--border); gap: 10px; }
  .topbar .title { font: 500 12.5px var(--sans); color: var(--muted);
                   white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .topbar .right { display: flex; gap: 6px; align-items: center; flex-shrink: 0; }
  .tool { font: 500 11.5px var(--sans); padding: 5px 10px; border-radius: 7px;
          border: 1px solid var(--border); background: transparent; color: var(--muted);
          cursor: pointer; }
  .tool:hover:not(:disabled) { border-color: var(--text); color: var(--text); }
  .tool:disabled { opacity: .4; cursor: default; }
  .icon-btn { width: 30px; height: 30px; border: 1px solid var(--border);
              border-radius: 7px; background: transparent; color: var(--text);
              cursor: pointer; font-size: 13px; }
  .icon-btn:hover { border-color: var(--text); }

  .canvas { flex: 1; overflow-y: auto; padding: 24px 20px 10px; }
  .canvas-inner { max-width: 700px; margin: 0 auto; }

  /* first run */
  .first-run { max-width: 460px; margin: 8vh auto 0; }
  .first-run h2 { font: 600 17px var(--sans); margin-bottom: 4px; }
  .first-run .lead { font-size: 13px; color: var(--muted); line-height: 1.55;
                     margin-bottom: 18px; }
  .step { display: flex; gap: 11px; padding: 11px 0; border-top: 1px solid var(--border); }
  .step .n { width: 22px; height: 22px; border-radius: 50%; border: 1.5px solid var(--border);
             display: flex; align-items: center; justify-content: center;
             font: 600 11px var(--mono); color: var(--muted); flex-shrink: 0; }
  .step.done .n { border-color: var(--accent); color: var(--accent); }
  .step .body { flex: 1; }
  .step .body b { font-size: 13px; font-weight: 600; }
  .step .body p { font-size: 12px; color: var(--muted); margin-top: 2px; line-height: 1.45; }
  .step .actions { margin-top: 8px; display: flex; gap: 6px; }
  .step .actions button { font: 500 11.5px var(--sans); padding: 5px 10px;
                          border-radius: 7px; border: 1px solid var(--border);
                          background: var(--card); color: var(--text); cursor: pointer; }
  .step .actions button:hover { border-color: var(--accent); color: var(--accent); }
  .step .actions button.primary { background: var(--text); color: var(--bg);
                                  border-color: var(--text); }
  .step .actions button.primary:hover { opacity: .9; color: var(--bg); }

  /* cards */
  .card { background: var(--card); border: 1px solid var(--border);
          border-radius: var(--radius); margin-bottom: 14px; overflow: hidden;
          animation: fadeIn .25s ease; }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); }
                      to { opacity: 1; transform: none; } }
  .card-head { padding: 10px 14px; border-bottom: 1px solid var(--border);
               font: 600 12.5px var(--sans); display: flex; align-items: center;
               justify-content: space-between; gap: 8px; }
  .card-head .sub { font: 10.5px var(--mono); color: var(--faint); font-weight: 400; }
  .card-head button { font: 500 10.5px var(--sans); padding: 3px 8px;
                      border-radius: 6px; border: 1px solid var(--border);
                      background: transparent; color: var(--muted); cursor: pointer; }
  .card-head button:hover { border-color: var(--text); color: var(--text); }
  .card-body { padding: 12px 14px; }

  .section { border-radius: var(--radius-sm); padding: 10px 12px; margin-bottom: 8px; }
  .section:last-child { margin-bottom: 0; }
  .section.active { background: var(--accent-soft); border: 1px solid #c3e6d8; }
  .section.review { background: var(--warn-bg); border: 1px solid var(--warn-border); }
  .section.conflict { background: var(--danger-bg); border: 1px solid var(--danger-border); }
  .section.degraded { background: var(--side); border: 1px solid var(--border); }
  .section-title { font: 600 10.5px var(--sans); text-transform: uppercase;
                   letter-spacing: .4px; margin-bottom: 4px; }
  .section.active .section-title { color: #0d7a5f; }
  .section.review .section-title { color: var(--warn-text); }
  .section.conflict .section-title { color: var(--danger-text); }
  .section.degraded .section-title { color: var(--muted); }
  .section ul { list-style: none; }
  .section li { padding: 2px 0; font-size: 12.5px; line-height: 1.45; }

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

  .rec { display: flex; align-items: flex-start; gap: 10px; padding: 9px 4px;
         border-bottom: 1px solid var(--border); cursor: pointer;
         border-radius: 6px; }
  .rec:hover { background: rgba(0,0,0,.025); }
  [data-theme="dark"] .rec:hover { background: rgba(255,255,255,.035); }
  .rec:last-child { border-bottom: none; }
  .rec .body { flex: 1; min-width: 0; }
  .rec .text { font-size: 12.5px; line-height: 1.45; }
  .rec .flags { margin-top: 3px; display: flex; gap: 5px; align-items: center;
                flex-wrap: wrap; }
  .rec .p { font: 10px var(--mono); color: var(--faint); }
  .rec .out { display: flex; gap: 4px; flex-shrink: 0; }
  .rec .out button { font: 500 10px var(--sans); padding: 3px 7px;
                     border-radius: 99px; border: 1px solid var(--border);
                     background: var(--card); color: var(--muted); cursor: pointer; }
  .rec .out button:hover { border-color: var(--text); color: var(--text); }
  .rec .out button.ghost { opacity: .45; }
  .rec .out button.ghost:hover { opacity: 1; }

  /* composer */
  .composer-wrap { flex-shrink: 0; padding: 8px 20px 14px; }
  .composer { max-width: 700px; margin: 0 auto; background: var(--card);
              border: 1px solid var(--border); border-radius: 13px;
              box-shadow: 0 2px 10px rgba(0,0,0,.05); padding: 5px;
              display: flex; gap: 7px; align-items: flex-end; }
  .composer:focus-within { border-color: var(--accent); }
  .composer textarea { flex: 1; border: none; outline: none; resize: none;
                       background: transparent; color: var(--text);
                       font: 13.5px/1.45 var(--sans); padding: 8px 9px;
                       min-height: 38px; max-height: 140px; }
  .composer textarea::placeholder { color: var(--faint); }
  .composer .send { width: 32px; height: 32px; border: none; border-radius: 8px;
                    background: var(--text); color: var(--bg); cursor: pointer;
                    font-size: 14px; display: flex; align-items: center;
                    justify-content: center; }
  .composer .send:disabled { opacity: .45; cursor: default; }
  .composer-meta { max-width: 700px; margin: 5px auto 0; font: 10px var(--mono);
                   color: var(--faint); display: flex; justify-content: space-between; }
  .spinner { display: inline-block; width: 12px; height: 12px;
             border: 2px solid var(--border); border-top-color: var(--text);
             border-radius: 50%; animation: spin .6s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* overlay */
  .overlay { position: fixed; inset: 0; background: rgba(0,0,0,.35);
             display: flex; align-items: stretch; justify-content: flex-end;
             z-index: 20; }
  .overlay.center { justify-content: center; align-items: center; }
  .panel { width: 380px; max-width: 92vw; background: var(--card);
           border-left: 1px solid var(--border); padding: 18px;
           overflow-y: auto; animation: slideIn .18s ease; }
  .overlay.center .panel { border: 1px solid var(--border); border-radius: 14px;
                           width: 420px; animation: fadeIn .18s ease; }
  @keyframes slideIn { from { transform: translateX(20px); opacity: 0; }
                       to { transform: none; opacity: 1; } }
  .panel h3 { font: 600 14px var(--sans); margin-bottom: 4px; }
  .panel .close { float: right; background: none; border: none; color: var(--muted);
                  font-size: 16px; cursor: pointer; }
  .panel .close:hover { color: var(--text); }
  .panel .p-sub { font: 11px var(--mono); color: var(--faint); margin-bottom: 14px; }
  .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;
           margin-bottom: 14px; }
  .stat { background: var(--side); border: 1px solid var(--border);
          border-radius: 8px; padding: 8px 10px; }
  .stat .val { font: 700 17px var(--mono); }
  .stat .lbl { font: 10px var(--sans); color: var(--muted); margin-top: 1px; }
  .bucket-row { display: flex; align-items: center; gap: 7px; padding: 2px 0;
                font: 11px var(--mono); }
  .bucket-bar { height: 7px; border-radius: 4px; background: var(--accent); min-width: 2px; }
  .panel table { width: 100%; border-collapse: collapse; font: 11px var(--mono); }
  .panel th { text-align: left; color: var(--muted); font-weight: 500; padding: 4px 0; }
  .panel td { padding: 3px 0; border-top: 1px solid var(--border); }
  .panel .empty-hint { font-size: 12px; color: var(--muted); line-height: 1.5; }
  .form-row { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }
  .form-row input, .form-row select, .form-row textarea { font: 12.5px var(--sans);
      border: 1px solid var(--border); border-radius: 8px; padding: 7px 9px;
      background: var(--card); color: var(--text); outline: none; }
  .form-row input:focus, .form-row select:focus, .form-row textarea:focus {
      border-color: var(--accent); }
  .form-row textarea { min-height: 70px; resize: vertical; }
  .form-row button { font: 600 12px var(--sans); padding: 8px 12px; border-radius: 8px;
                     border: none; background: var(--text); color: var(--bg); cursor: pointer; }
  .hidden { display: none !important; }
  @media (max-width: 760px) { .side { display: none; } }
</style></head><body>
<div class="shell">
  <aside class="side">
    <div class="brand">
      <svg viewBox="0 0 256 256"><rect x="28" y="28" width="200" height="200" rx="30" fill="none" stroke="currentColor" stroke-width="14"/><line x1="58" y1="82" x2="70" y2="82" stroke="currentColor" stroke-width="10"/><line x1="58" y1="130" x2="70" y2="130" stroke="currentColor" stroke-width="10"/><line x1="58" y1="178" x2="70" y2="178" stroke="currentColor" stroke-width="10"/><rect x="76" y="68" width="112" height="28" rx="9" fill="currentColor"/><rect x="76" y="116" width="72" height="28" rx="9" fill="currentColor"/><rect x="76" y="164" width="36" height="28" rx="9" fill="currentColor"/><circle cx="200" cy="200" r="50" fill="#10a37f"/><polyline points="179,201 194,216 222,187" fill="none" stroke="#fff" stroke-width="14" stroke-linecap="round" stroke-linejoin="round"/></svg>
      ClaimLedger
    </div>
    <button class="new-btn" onclick="newTask()" data-i18n="+ New task">+ New task</button>
    <div class="side-label" data-i18n="History">History</div>
    <div class="history" id="history"></div>
    <div class="side-foot">
      <div class="chains" id="chains"></div>
      <button class="settings-toggle" onclick="toggleSettings()" id="settings-toggle" data-i18n="Settings ▸">Settings ▸</button>
      <div class="settings hidden" id="settings">
        <div id="agents"></div>
        <div class="agent-reg">
          <input id="agent-name" placeholder="identity name" data-i18n-ph="identity name">
          <select id="agent-kind"><option value="agent">agent</option><option value="human">human</option></select>
          <button onclick="registerAgent()">+</button>
        </div>
        <div style="font:10px var(--sans);color:var(--faint);margin-top:6px;line-height:1.4">
          <span data-i18n="Attribution only — no keys, no signatures. New records and outcomes are signed as the selected identity.">Attribution only — no keys, no signatures. New records and outcomes are signed as the selected identity.</span>
        </div>
      </div>
    </div>
  </aside>

  <main class="main">
    <div class="topbar">
      <div class="title" id="top-title" data-i18n="New task">New task</div>
      <div class="right">
        <button class="tool" id="btn-proposals" onclick="openProposals()" disabled>Proposals</button>
        <button class="tool" id="btn-record" onclick="openRecordForm()" data-i18n="+ Record">+ Record</button>
        <button class="tool" id="btn-copy" onclick="copyBrief()" disabled data-i18n="Copy brief" data-i18n-title="Copy brief (c)">Copy brief</button>
        <button class="tool" onclick="openCalibration()" data-i18n="Calibration">Calibration</button>
        <button class="icon-btn" onclick="toggleTheme()" data-i18n-title="toggle theme" aria-label="toggle theme">◐</button>
        <button class="icon-btn" id="btn-lang" onclick="toggleLang()" title="中文 / English" aria-label="中文 / English"></button>
      </div>
    </div>
    <div class="canvas" id="canvas">
      <div class="canvas-inner" id="canvas-inner"></div>
    </div>
    <div class="composer-wrap">
      <div class="composer">
        <textarea id="task" rows="1" data-i18n-ph="Describe a task…  (/ to focus · ⌘↵ to judge)" placeholder="Describe a task…  (/ to focus · ⌘↵ to judge)" autofocus></textarea>
        <button class="send" id="send" onclick="decide()" title="judge" aria-label="judge">↑</button>
      </div>
      <div class="composer-meta">
        <span id="meta-left" data-i18n="jev-first memory · model proposes, the ledger decides">jev-first memory · model proposes, the ledger decides</span>
        <span id="meta-right"></span>
      </div>
    </div>
  </main>
</div>
<div class="overlay hidden" id="overlay" onclick="overlayClick(event)"><div class="panel" id="panel"></div></div>

<script>
const state = { records: 0, judgments: 0, outcomes: 0,
                history: [], agents: [], current: null,
                pending: 0, proposals: [],
                currentAgent: localStorage.getItem("agent") || null,
                settingsOpen: false };

/* ---------- i18n ---------- */
const LANG_KEY = "lang";
const LANG = () => localStorage.getItem(LANG_KEY) || "en";
const ZH = {
  "+ New task": "+ 新任务",
  "History": "历史",
  "Settings": "设置",
  "Settings ▸": "设置 ▸",
  "+ Record": "+ 记录",
  "identity name": "身份名称",
  "Attribution only — no keys, no signatures. New records and outcomes are signed as the selected identity.":
    "仅用于署名——不含密钥、不含签名。新记录与 outcome 以当前选中的身份签署。",
  "New task": "新任务",
  "Proposals": "提案",
  "Record": "记录",
  "Copy brief": "复制 brief",
  "Copy brief (c)": "复制 brief (c)",
  "toggle theme": "切换主题",
  "Calibration": "校准",
  "Describe a task…  (/ to focus · ⌘↵ to judge)": "描述一个任务…（/ 聚焦 · ⌘↵ 判定）",
  "jev-first memory · model proposes, the ledger decides": "jev-first 记忆层 · 模型提议，账本裁决",
  "Start in three steps": "三步开始",
  "The ledger only judges what it knows. Record decisions first, then ask what applies to a task.":
    "账本只判断它认识的东西。先录入决策，再问哪些适用于任务。",
  "Record a decision": "录入一条决策",
  " records ready.": " 条记录就绪。",
  "One standalone sentence, e.g. \u201cAll storage must use PostgreSQL.\u201d":
    "一句独立的话，例如\u201cAll storage must use PostgreSQL.\u201d",
  "Add one": "添加一条",
  "Load 5 examples": "载入 5 条示例",
  "Ask what applies": "问哪些适用",
  "Type a task below. Records are selected by overlap, judged one by one, and conflicting pairs are localized.":
    "在下方输入任务。记录按重叠度选出、逐条判断，冲突对会被定位。",
  "Type a task below and press \u2318\u21b5.": "在下方输入任务并按 \u2318\u21b5。",
  "Available once a record exists.": "录入一条记录后可用。",
  "Review the verdict": "复核判定",
  "Click upheld or overturned on admitted records. Those clicks are the calibration data.":
    "在采纳的记录上点 upheld（成立）或 overturned（推翻）。这些点击就是校准数据。",
  "error: ": "错误：",
  "judge timed out after 60s": "判定超时（60 秒）",
  "· degraded": "· 降级",
  "Brief": "判定摘要",
  "Copy": "复制",
  "✓ Active constraints": "✓ 生效约束",
  "governing": "主导",
  "thin margin": "薄边际",
  "No lexical match": "无词面匹配",
  "The judge admitted these records semantically; confirm before relying.":
    "判定器在语义上采纳了这些记录；依赖前请确认。",
  "No relevant records": "无相关记录",
  "Nothing in memory matched this task lexically. The records below were selected by recency, not relevance.":
    "记忆中没有与该任务词面匹配的内容。以下记录按近期性而非相关性选出。",
  "none admitted for this task.": "本任务无采纳项。",
  "Candidates considered (recency fallback — not admitted)": "候选（近期回退——未采纳）",
  "⚠ Needs human review": "⚠ 需人工复核",
  "conflict": "冲突",
  "review": "待审",
  "⛔ Unresolved conflicts": "⛔ 未决冲突",
  "⚠ Degraded": "⚠ 降级",
  "Judge unreachable — every record is review.": "判定服务不可达——所有记录按待审处理。",
  "Records": "记录",
  "scoreable": "可评分",
  "of": "/",
  "counts toward calibration": "计入校准",
  "recorded; v1 calibration scores admit entries only": "已记录；v1 校准只统计采纳项",
  "upheld": "成立",
  "overturned": "推翻",
  "unclear": "存疑",
  "admit": "采纳",
  "exclude": "排除",
  "view this record\u2019s judgment history": "查看该记录的判定历史",
  "no judgments yet": "尚无判定",
  "sealed": "已封存",
  "Copied ✓": "已复制 ✓",
  "Agent view — the exact text the agent reads": "Agent 视角——agent 实际读到的原文",
  "copy failed: ": "复制失败：",
  "Pending proposals": "待确认提案",
  "Agent writes wait here until a human confirms or rejects.": "agent 的写入在这里等待人确认或拒绝。",
  "Nothing waiting. Agents propose; you decide.": "没有等待项。agent 提议，你来决定。",
  "Confirm": "确认",
  "Reject": "拒绝",
  "Proposed edges": "提议的边",
  "Graph relations the judge proposes wait here too — the memory graph is judged, not written.":
    "判定器提议的图关系也在这里等待——记忆图是被判断出来的，不是写出来的。",
  "No edge proposals.": "没有待确认的边。",
  "edge rejected ": "边已拒绝 ",
  "edge confirmed ": "边已确认 ",
  "edge-confirm: ": "边确认：",
  "rejected ": "已拒绝 ",
  "confirmed → ": "已确认 → ",
  "already recorded as ": "已存在为 ",
  "confirm: ": "确认：",
  "scored": "已评分",
  "outcomes recorded": "条 outcome 已记录",
  "No scored outcomes yet. Click upheld or overturned on an\n      <b>admit</b> record — review and exclude outcomes are recorded but not scored in v1.":
    "还没有可评分的 outcome。在采纳（admit）记录上点 upheld 或 overturned——待审与排除的 outcome 会记录但 v1 不计分。",
  "upheld rate": "成立率",
  "By author": "按作者",
  "author": "作者",
  "n": "条数",
  "Export JSON": "导出 JSON",
  "This record has not appeared in a sealed judgment yet.": "该记录尚未出现在任何已封存的判定中。",
  "when": "时间",
  "action": "动作",
  "one standalone sentence — no conversation context": "一句独立的话——不带对话上下文",
  " · similarity ": " · 相似度 ",
  "record: ": "记录：",
  "no identities yet": "尚无身份",
  "unregistered": "未注册",
  "register: ": "注册：",
  "records": "条记录",
  "judgments": "次判定",
  "outcomes": "条 outcome",
};
const T = s => (LANG() === "zh" && Object.prototype.hasOwnProperty.call(ZH, s)) ? ZH[s] : s;
function toggleLang() {
  localStorage.setItem(LANG_KEY, LANG() === "zh" ? "en" : "zh");
  location.reload();
}
function applyStaticLang() {
  document.querySelectorAll("[data-i18n]").forEach(el =>
    el.textContent = T(el.getAttribute("data-i18n")));
  document.querySelectorAll("[data-i18n-ph]").forEach(el =>
    el.placeholder = T(el.getAttribute("data-i18n-ph")));
  document.querySelectorAll("[data-i18n-title]").forEach(el =>
    el.title = T(el.getAttribute("data-i18n-title")));
  const b = $("btn-lang");
  if (b) b.textContent = LANG() === "zh" ? "EN" : "中";
}

const $ = id => document.getElementById(id);
const esc = s => { const d = document.createElement("div"); d.textContent = s ?? ""; return d.innerHTML; };
const isTyping = () => ["INPUT","TEXTAREA","SELECT"].includes(document.activeElement?.tagName);

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

async function api(path, body, signal) {
  const opt = body ? {method: "POST", headers: {"Content-Type": "application/json"},
                      body: JSON.stringify(body)} : {signal};
  if (body && signal) opt.signal = signal;
  const res = await fetch(path, opt);
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  return data;
}

/* ---------- first run ---------- */
function renderFirstRun() {
  const seeded = state.records > 0;
  $("canvas-inner").innerHTML =
    `<div class="first-run">
       <h2>${T("Start in three steps")}</h2>
       <p class="lead">${T("The ledger only judges what it knows. Record decisions first, then ask what applies to a task.")}</p>
       <div class="step ${seeded ? "done" : ""}">
         <div class="n">${seeded ? "✓" : "1"}</div>
         <div class="body"><b>${T("Record a decision")}</b>
           <p>${seeded ? state.records + T(" records ready.") : T("One standalone sentence, e.g. \u201cAll storage must use PostgreSQL.\u201d")}</p>
           ${seeded ? "" : `<div class="actions">
             <button class="primary" onclick="openRecordForm()">${T("Add one")}</button>
             <button onclick="seedExamples()">${T("Load 5 examples")}</button></div>`}
         </div>
       </div>
       <div class="step">
         <div class="n">2</div>
         <div class="body"><b>${T("Ask what applies")}</b>
           <p>${seeded ? T("Type a task below and press ⌘↵.") : T("Available once a record exists.")}</p></div>
       </div>
       <div class="step">
         <div class="n">3</div>
         <div class="body"><b>${T("Review the verdict")}</b>
           <p>${T("Click upheld or overturned on admitted records. Those clicks are the calibration data.")}</p></div>
       </div>
     </div>`;
}

async function seedExamples() {
  try {
    await api("/api/seed-examples", {});
    await refreshSide();
    renderFirstRun();
  } catch (e) { $("meta-right").textContent = e.message; }
}

/* ---------- judgment ---------- */
async function decide() {
  const task = $("task").value.trim();
  if (!task) return;
  $("send").disabled = true;
  $("send").innerHTML = '<span class="spinner"></span>';
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 60000);
  try {
    const j = await api("/api/decide?task=" + encodeURIComponent(task),
                        undefined, controller.signal);
    clearTimeout(timeout);
    state.current = j;
    render(j);
    $("top-title").textContent = task;
    $("btn-copy").disabled = false;
    $("meta-right").textContent =
      `${j.model} · ${j.requests} req · ${j.latency_ms} ms · ${String(j.judgment_hash).slice(0,10)}…` +
      (j.degraded ? T("· degraded") : "");
    $("task").value = "";
    $("task").style.height = "auto";
    await loadHistory();
    await refreshSide();
  } catch (e) {
    $("meta-right").textContent = T("error: ") +
      (e.name === "AbortError" ? T("judge timed out after 60s") : e.message);
  } finally {
    clearTimeout(timeout);
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
  const scoreable = (j.entries || []).filter(e => e.action === "admit").length;
  const fallback = !!(j.selection && j.selection.fallback_to_recency);
  let html = "";

  html += `<div class="card"><div class="card-head">${T("Brief")}` +
    `<button onclick="copyBrief()">${T("Copy")}</button></div><div class="card-body">`;
  if (admitted.length) {
    html += `<div class="section active"><div class="section-title">${T("✓ Active constraints")}</div><ul>` +
      admitted.map(e => `<li>${esc(e.text)}${e.governing ? ` <span class="pill green">${T("governing")}</span>` : ""}${e.low_margin ? ` <span class="pill amber">${T("thin margin")}</span>` : ""}</li>`).join("") + "</ul></div>";
    if (fallback) {
      html += `<div class="section degraded"><div class="section-title">${T("No lexical match")}</div>` +
        `<div style="font-size:12.5px">${T("The judge admitted these records semantically; confirm before relying.")}</div></div>`;
    }
  } else if (fallback) {
    html += `<div class="section degraded"><div class="section-title">${T("No relevant records")}</div>` +
      `<div style="font-size:12.5px">${T("Nothing in memory matched this task lexically. The records below were selected by recency, not relevance.")}</div></div>`;
  } else {
    html += `<div class="section active"><div class="section-title">${T("✓ Active constraints")}</div>` +
      `<div style="font-size:12.5px;color:var(--muted)">${T("none admitted for this task.")}</div></div>`;
  }
  if (review.length) {
    const title = fallback ? T("Candidates considered (recency fallback — not admitted)")
                           : T("⚠ Needs human review");
    html += `<div class="section review"><div class="section-title">${title}</div><ul>` +
      review.map(e => `<li>${esc(e.text)} <span class="pill amber">${e.conflicted ? T("conflict") : e.low_margin ? T("thin margin") : T("review")}</span></li>`).join("") + "</ul></div>";
  }
  if (conflicts.length) {
    html += `<div class="section conflict"><div class="section-title">${T("⛔ Unresolved conflicts")}</div><ul>` +
      conflicts.map(p => `<li>${esc(byId[p[0]]?.text || p[0])} <span style="color:var(--danger-text)">⟂</span> ${esc(byId[p[1]]?.text || p[1])}</li>`).join("") + "</ul></div>";
  }
  if (j.degraded) {
    html += `<div class="section degraded"><div class="section-title">${T("⚠ Degraded")}</div>` +
      `<div style="font-size:12.5px">${T("Judge unreachable — every record is review.")}</div></div>`;
  }
  if (j.brief_text) {
    html += `<details style="margin-top:10px"><summary style="cursor:pointer;font-size:12px;color:var(--muted)">${T("Agent view — the exact text the agent reads")}</summary>` +
      `<pre style="white-space:pre-wrap;font:11.5px var(--mono);margin:8px 0 0;color:var(--muted)">${esc(j.brief_text)}</pre></details>`;
  }
  html += "</div></div>";

  const order = {admit: 0, review: 1, exclude: 2};
  const sorted = [...(j.entries || [])].sort((a, b) =>
    (order[a.action] - order[b.action]) || ((b.p_admit ?? 0) - (a.p_admit ?? 0)));
  html += `<div class="card"><div class="card-head">${T("Records")}` +
    `<span class="sub">${T("scoreable")}: ${scoreable} ${T("of")} ${(j.entries || []).length}</span></div>` +
    '<div class="card-body">';
  html += sorted.map(e => {
    const cls = e.action === "admit" ? "green" : e.action === "review" ? "amber" : "gray";
    const flags = [
      e.governing ? `<span class="pill green">${T("governing")}</span>` : "",
      e.conflicted ? `<span class="pill red">${T("conflict")}</span>` : "",
      e.low_margin ? `<span class="pill amber">${T("thin margin")}</span>` : ""
    ].filter(Boolean).join(" ");
    const outcome = outcomes[e.record_id];
    const ghost = e.action === "admit" ? "" : " ghost";
    const tip = e.action === "admit"
      ? T("counts toward calibration")
      : T("recorded; v1 calibration scores admit entries only");
    const buttons = outcome
      ? `<span class="pill ${outcome === "upheld" ? "green" : outcome === "overturned" ? "red" : "gray"}">${T(outcome)}</span>`
      : ["upheld", "overturned", "unclear"].map(v =>
          `<button class="${ghost.trim()}" title="${tip}" onclick="event.stopPropagation();postOutcome('${e.record_id}','${v}')">${T(v)}</button>`).join(" ");
    return `<div class="rec" onclick="openRecord('${e.record_id}')" title="${T("view this record\u2019s judgment history")}">` +
      `<div class="body"><div class="text">${esc(e.text)}</div>` +
      `<div class="flags"><span class="pill ${cls}">${T(e.action)}</span>` +
      `<span class="p">p(admit) ${e.p_admit ?? "—"}</span>${flags}</div></div>` +
      `<div class="out">${buttons}</div></div>`;
  }).join("");
  html += "</div></div>";

  $("canvas-inner").innerHTML = html;
  $("canvas").scrollTop = 0;
}

async function postOutcome(recordId, verdict) {
  if (!state.current) return;
  await api("/api/outcome", {record_id: recordId, verdict: verdict,
                             judgment_hash: state.current.judgment_hash,
                             by: "console-human"});
  state.current.outcomes = state.current.outcomes || {};
  state.current.outcomes[recordId] = verdict;
  render(state.current);
  await loadHistory();
  await refreshSide();
}

/* ---------- history ---------- */
async function loadHistory() {
  state.history = await api("/api/history?limit=40");
  const el = $("history");
  if (!state.history.length) {
    el.innerHTML = `<div style="padding:8px 9px;font-size:11px;color:var(--faint)">${T("no judgments yet")}</div>`;
    return;
  }
  el.innerHTML = state.history.map(j => {
    const time = (j.created_at || "").slice(5, 16).replace("T", " ");
    const conflict = (j.conflicts || []).length
      ? `<span class="badge">${j.conflicts.length} ⟂</span>` : "";
    const deg = j.degraded ? '<span class="deg">⚠</span>' : "";
    const active = state.current && state.current.judgment_hash === j.judgment_hash ? " active" : "";
    return `<div class="hist${active}" data-hash="${j.judgment_hash}" onclick="selectJudgment('${j.judgment_hash}')">` +
      `<div class="t">${esc(j.task)}</div>` +
      `<div class="m"><span>${time}</span>${conflict}${deg}</div></div>`;
  }).join("");
}

function selectJudgment(hash) {
  const j = state.history.find(x => x.judgment_hash === hash);
  if (!j) return;
  state.current = j;
  render(j);
  $("btn-copy").disabled = false;
  $("top-title").textContent = j.task;
  $("meta-right").textContent = `${j.model} · ${T("sealed")} ${String(hash).slice(0,10)}…` +
    (j.degraded ? T("· degraded") : "");
  document.querySelectorAll(".hist").forEach(el =>
    el.classList.toggle("active", el.dataset.hash === hash));
}

function newTask() {
  state.current = null;
  $("top-title").textContent = T("New task");
  $("btn-copy").disabled = true;
  $("meta-right").textContent = "";
  if (state.records) {
    $("canvas-inner").innerHTML =
      `<div class="first-run"><h2>${T("Ask what applies")}</h2>` +
      `<p class="lead">${T("Type a task below. Records are selected by overlap, judged one by one, and conflicting pairs are localized.")}</p></div>`;
  } else {
    renderFirstRun();
  }
  document.querySelectorAll(".hist").forEach(el => el.classList.remove("active"));
  $("task").focus();
}

/* ---------- copy ---------- */
async function copyBrief() {
  const text = state.current && state.current.brief_text;
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    const btn = $("btn-copy");
    const old = btn.textContent;
    btn.textContent = T("Copied ✓");
    setTimeout(() => { btn.textContent = old; }, 1200);
  } catch (e) { $("meta-right").textContent = T("copy failed: ") + e.message; }
}

/* ---------- overlays ---------- */
function showPanel(html, center) {
  $("panel").innerHTML = html;
  const ov = $("overlay");
  ov.className = "overlay" + (center ? " center" : "");
}
function overlayClick(e) { if (e.target.id === "overlay") closeOverlays(); }
function closeOverlays() { $("overlay").className = "overlay hidden"; }

async function openProposals() {
  const rows = await api("/api/proposals");
  state.proposals = rows;
  let edges = [];
  try { edges = await api("/api/edge-proposals"); } catch (e) { edges = []; }
  let html = `<button class="close" onclick="closeOverlays()">✕</button>
    <h3>${T("Pending proposals")}</h3>
    <div class="p-sub">${T("Agent writes wait here until a human confirms or rejects.")}</div>`;
  if (!rows.length) {
    html += `<div class="empty-hint">${T("Nothing waiting. Agents propose; you decide.")}</div>`;
  } else {
    html += rows.map(p => {
      const time = (p.at || "").slice(5, 16).replace("T", " ");
      return `<div class="rec" style="cursor:default">
        <div class="body"><div class="text">${esc(p.text)}</div>
        <div class="flags"><span class="p">${esc(p.proposal_id)} · ${esc(p.source)} · ${time}</span></div></div>
        <div class="out">
          <button onclick="decideProposal('${p.proposal_id}','confirm')">${T("Confirm")}</button>
          <button onclick="decideProposal('${p.proposal_id}','reject')">${T("Reject")}</button>
        </div></div>`;
    }).join("");
  }
  html += `<h3 style="margin-top:14px">${T("Proposed edges")}</h3>
    <div class="p-sub">${T("Graph relations the judge proposes wait here too — the memory graph is judged, not written.")}</div>`;
  if (!edges.length) {
    html += `<div class="empty-hint">${T("No edge proposals.")}</div>`;
  } else {
    html += edges.map(e => {
      const time = (e.at || "").slice(5, 16).replace("T", " ");
      return `<div class="rec" style="cursor:default">
        <div class="body"><div class="text"><span class="p">${esc(e.edge_type)}</span>
          ${esc(e.src)} → ${esc(e.dst)}</div>
        <div class="flags"><span class="p">${esc(e.edge_id)} · p=${esc(e.confidence)} · ${esc(e.source)} · ${time}</span></div></div>
        <div class="out">
          <button onclick="decideEdge('${e.edge_id}','confirm')">${T("Confirm")}</button>
          <button onclick="decideEdge('${e.edge_id}','reject')">${T("Reject")}</button>
        </div></div>`;
    }).join("");
  }
  showPanel(html, false);
}

async function decideEdge(id, decision) {
  try {
    const res = await api("/api/edge-confirm", {edge_id: id, decision: decision,
                                                by: "console-human"});
    $("meta-right").textContent = (decision === "reject" ? T("edge rejected ")
                                    : T("edge confirmed ")) + id;
    await refreshSide();
    await openProposals();
    if (!state.current) renderFirstRun();
  } catch (e) { $("meta-right").textContent = T("edge-confirm: ") + e.message; }
}

async function decideProposal(id, decision) {
  try {
    const res = await api("/api/confirm", {proposal_id: id, decision: decision,
                                           by: "console-human"});
    if (decision === "reject") {
      $("meta-right").textContent = T("rejected ") + id;
    } else if (res.created) {
      $("meta-right").textContent = T("confirmed → ") + res.record.record_id;
    } else {
      $("meta-right").textContent = T("already recorded as ") + res.record.record_id;
    }
    await refreshSide();
    await openProposals();
    if (!state.current) renderFirstRun();
  } catch (e) { $("meta-right").textContent = T("confirm: ") + e.message; }
}

async function openCalibration() {
  const r = await api("/api/calibrate");
  let html = `<button class="close" onclick="closeOverlays()">✕</button>
    <h3>${T("Calibration")}</h3>
    <div class="p-sub">${r.n_scored} ${T("scored")} · ${r.n_outcomes} ${T("outcomes recorded")}</div>`;
  if (!r.n_scored) {
    html += `<div class="empty-hint">${T("No scored outcomes yet. Click upheld or overturned on an <b>admit</b> record — review and exclude outcomes are recorded but not scored in v1.")}</div>`;
  } else {
    html += `<div class="stats">
      <div class="stat"><div class="val">${r.overall_upheld_rate}</div><div class="lbl">${T("upheld rate")}</div></div>
      <div class="stat"><div class="val">${r.brier}</div><div class="lbl">Brier</div></div>
      <div class="stat"><div class="val">${r.n_scored}</div><div class="lbl">${T("scored")}</div></div></div>
      <div style="margin-bottom:12px">`;
    for (const [bucket, d] of Object.entries(r.buckets)) {
      if (!d.n) continue;
      const rate = d.upheld_rate != null ? (d.upheld_rate * 100).toFixed(0) + "%" : "—";
      html += `<div class="bucket-row"><span style="width:76px">${bucket}</span>
        <div class="bucket-bar" style="width:${(d.upheld_rate ?? 0) * 90}px"></div>
        <span>${d.n} · ${rate}</span></div>`;
    }
    html += `</div>`;
    const authors = Object.entries(r.by_author || {});
    if (authors.length) {
      html += `<h3 style="margin-top:6px">${T("By author")}</h3>
        <table><tr><th>${T("author")}</th><th>${T("n")}</th><th>${T("upheld rate")}</th><th>Brier</th></tr>` +
        authors.map(([a, d]) =>
          `<tr><td>${esc(a)}</td><td>${d.n}</td><td>${d.upheld_rate}</td><td>${d.brier}</td></tr>`).join("") +
        `</table>`;
    }
    html += `<div style="margin-top:14px"><button class="tool" onclick='downloadCalibration()'>${T("Export JSON")}</button></div>`;
  }
  window.__calibration = r;
  showPanel(html, false);
}

function downloadCalibration() {
  const blob = new Blob([JSON.stringify(window.__calibration, null, 2)],
                        {type: "application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "calibration.json";
  a.click();
  URL.revokeObjectURL(a.href);
}

async function openRecord(recordId) {
  const rows = await api("/api/record-history?record_id=" + encodeURIComponent(recordId));
  const record = (state.current?.entries || []).find(e => e.record_id === recordId);
  let html = `<button class="close" onclick="closeOverlays()">✕</button>
    <h3>${esc(record?.text || recordId)}</h3>
    <div class="p-sub">${esc(recordId)}</div>`;
  if (!rows.length) {
    html += `<div class="empty-hint">${T("This record has not appeared in a sealed judgment yet.")}</div>`;
  } else {
    html += `<table><tr><th>${T("when")}</th><th>${T("action")}</th><th>p(admit)</th></tr>` +
      rows.map(r => `<tr><td>${(r.created_at || "").slice(5,16).replace("T"," ")}</td>
        <td>${r.action}</td><td>${r.p_admit ?? "—"}</td></tr>`).join("") + `</table>`;
  }
  showPanel(html, false);
}

function openRecordForm() {
  const options = state.agents.filter(a => a.registered)
    .map(a => `<option value="${esc(a.name)}" ${a.name === state.currentAgent ? "selected" : ""}>${esc(a.name)} · ${esc(a.kind)}</option>`)
    .join("");
  showPanel(`<button class="close" onclick="closeOverlays()">✕</button>
    <h3>${T("Record a decision")}</h3>
    <div class="p-sub">${T("one standalone sentence — no conversation context")}</div>
    <div class="form-row">
      <textarea id="rec-text" placeholder="All storage must use PostgreSQL."></textarea>
      <select id="rec-agent">${options || '<option value="console">console</option>'}</select>
      <button onclick="submitRecord()">${T("Record")}</button>
    </div>`, true);
  setTimeout(() => $("rec-text")?.focus(), 50);
}

async function submitRecord() {
  const text = $("rec-text").value.trim();
  if (!text) return;
  try {
    const res = await api("/api/record", {text: text, source: $("rec-agent").value,
                                           by: "console-human"});
    closeOverlays();
    await refreshSide();
    renderFirstRun();
    if (res.duplicate) {
      $("meta-right").textContent = T("already recorded as ") + res.record.record_id +
        T(" · similarity ") + res.similarity;
    }
  } catch (e) { $("meta-right").textContent = T("record: ") + e.message; }
}

/* ---------- agents ---------- */
async function loadAgents() {
  state.agents = await api("/api/agents");
  if (!state.currentAgent && state.agents.length)
    state.currentAgent = state.agents[0].name;
  if (!state.agents.length) {
    $("agents").innerHTML = `<div style="font-size:11px;color:var(--faint);padding:4px 6px">${T("no identities yet")}</div>`;
    return;
  }
  $("agents").innerHTML = state.agents.map(a => {
    const sel = state.currentAgent === a.name ? " sel" : "";
    const marker = a.registered
      ? `<span class="kind">${esc(a.kind)}</span>`
      : `<span class="unreg">${T("unregistered")}</span>`;
    const safe = String(a.name).replace(/'/g, "");
    return `<div class="agent${sel}" onclick="selectAgent('${safe}')">
      <span>${esc(a.name)}</span>${marker}<span class="count">${a.records}</span></div>`;
  }).join("");
}
function selectAgent(name) {
  state.currentAgent = name;
  localStorage.setItem("agent", name);
  loadAgents();
}
async function registerAgent() {
  const name = $("agent-name").value.trim();
  if (!name) return;
  try {
    await api("/api/agents", {name: name, kind: $("agent-kind").value});
    $("agent-name").value = "";
    state.currentAgent = name;
    localStorage.setItem("agent", name);
    await loadAgents();
  } catch (e) { $("meta-right").textContent = T("register: ") + e.message; }
}
function toggleSettings() {
  state.settingsOpen = !state.settingsOpen;
  $("settings").classList.toggle("hidden", !state.settingsOpen);
  $("settings-toggle").textContent = T("Settings") + " " + (state.settingsOpen ? "▾" : "▸");
}

/* ---------- chains ---------- */
async function refreshSide() {
  const c = await api("/api/audit");
  state.records = c.records; state.judgments = c.judgments; state.outcomes = c.outcomes;
  state.pending = (c.pending_proposals || 0) + (c.pending_edges || 0);
  const btn = $("btn-proposals");
  btn.textContent = state.pending ? `${T("Proposals")} (${state.pending})` : T("Proposals");
  btn.disabled = state.pending === 0;
  $("chains").innerHTML =
    `<span><span class="dot"></span>${c.records} ${T("records")}</span>` +
    `<span><span class="dot"></span>${c.judgments} ${T("judgments")}</span>` +
    `<span><span class="dot"></span>${c.outcomes} ${T("outcomes")}</span>` +
    (c.degraded ? `<span style="color:var(--warn-text)">⚠ ${c.degraded}</span>` : "");
}

/* ---------- keyboard ---------- */
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    if (!$("overlay").classList.contains("hidden")) { closeOverlays(); return; }
    if (isTyping()) { document.activeElement.blur(); return; }
    $("task").value = ""; $("task").style.height = "auto";
    return;
  }
  if (e.key === "/" && !isTyping()) { e.preventDefault(); $("task").focus(); return; }
  if ((e.key === "c" || e.key === "C") && !isTyping()) { copyBrief(); return; }
});
$("task").addEventListener("keydown", e => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") decide();
});
$("task").addEventListener("input", e => {
  e.target.style.height = "auto";
  e.target.style.height = Math.min(e.target.scrollHeight, 140) + "px";
});

/* ---------- init ---------- */
(async function init() {
  applyStaticLang();
  await loadAgents();
  await refreshSide();
  await loadHistory();
  if (!state.history.length) renderFirstRun();
})();
</script></body></html>"""