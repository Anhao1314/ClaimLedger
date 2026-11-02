"""memory console — a local, single-user view over the Jev-first layer.

This is not a product surface. It exists for one reason: **to collect
outcomes**. A human works through this console, clicks upheld / overturned on
real decisions, and the calibration view finally has data. If it ever drifts
into decoration, cut it again (same rule that removed the old demo).

stdlib only. Binds to 127.0.0.1. Every number on the page comes from a live
engine call or a committed log — nothing hardcoded.
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import parse_qs, urlparse

from . import log as jlog
from .brief import render_brief
from .cache import Cache
from .calibration import calibrate
from .judge import DEFAULT_BUDGET_BYTES, judge
from .outcomes import append_outcome, read as read_outcomes, verify as verify_outcomes
from .records import RecordStore
from .select import select_candidates

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>ClaimLedger</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root {
    --bg: #f7f7f8; --card: #ffffff; --border: #e5e5e5;
    --text: #1a1a1a; --muted: #6b6b6b; --faint: #9a9a9a;
    --accent: #10a37f; --accent-soft: #e6f7f1;
    --warn-bg: #fff8eb; --warn-border: #f5d98a; --warn-text: #92690a;
    --danger-bg: #fef2f2; --danger-border: #fecaca; --danger-text: #b91c1c;
    --radius: 12px; --radius-sm: 8px;
    --shadow: 0 1px 3px rgba(0,0,0,0.06);
    --mono: ui-monospace, 'SF Mono', Menlo, monospace;
    --sans: -apple-system, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
  }
  [data-theme="dark"] {
    --bg: #141414; --card: #1e1e1e; --border: #333;
    --text: #f2f2f2; --muted: #9a9a9a; --faint: #666;
    --accent: #10a37f; --accent-soft: #0d2818;
    --warn-bg: #2a2210; --warn-border: #5a4a1a; --warn-text: #e5c04a;
    --danger-bg: #2a1515; --danger-border: #5a2a2a; --danger-text: #f87171;
    --shadow: 0 1px 4px rgba(0,0,0,0.4);
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system,'Segoe UI','Helvetica Neue',Arial,sans-serif;
         background: var(--bg); color: var(--text); min-height: 100vh;
         transition: background .2s,color .2s; }
  .app { max-width: 720px; margin: 0 auto; padding: 0 16px 64px; }
  .header { display: flex; align-items: center; justify-content: space-between; padding: 16px 0; }
  .brand { display: flex; align-items: center; gap: 10px; font-weight: 600; font-size: 15px; }
  .brand svg { width: 28px; height: 28px; }
  .right { display: flex; align-items: center; gap: 14px; }
  .chains { display: flex; gap: 12px; font-size: 12px; color: var(--muted); }
  .chains .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); display: inline-block; margin-right: 4px; }
  .theme-toggle { background: none; border: 1.5px solid var(--border); border-radius: 8px; width: 32px; height: 32px; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 15px; color: var(--text); }
  .theme-toggle:hover { border-color: var(--text); }
  .task-box { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); padding: 4px; display: flex; gap: 8px; align-items: flex-end; }
  .task-box textarea { flex: 1; border: none; outline: none; resize: none; font: 15px/1.4 var(--sans); color: var(--text); padding: 10px 12px; min-height: 44px; background: transparent; }
  .task-box textarea::placeholder { color: var(--faint); }
  .task-box button { background: var(--text); color: var(--bg); border: none; border-radius: 8px; padding: 9px 18px; font: 600 14px var(--sans); cursor: pointer; white-space: nowrap; }
  .task-box button:disabled { opacity: .5; cursor: default; }
  .meta { font: 11px var(--mono); color: var(--faint); padding: 6px 4px 0; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); margin-top: 14px; overflow: hidden; animation: fadeIn .3s ease; }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
  .card-head { padding: 12px 16px; border-bottom: 1px solid var(--border); font: 600 13px var(--sans); display: flex; align-items: center; gap: 8px; }
  .card-body { padding: 14px 16px; }
  .section { border-radius: 8px; padding: 12px 14px; margin-bottom: 10px; }
  .section:last-child { margin-bottom: 0; }
  .section.active { background: var(--accent-soft); border: 1px solid #c3e6d8; }
  .section.needs-review { background: var(--warn-bg); border: 1px solid var(--warn-border); }
  .section.conflict { background: var(--danger-bg); border: 1px solid var(--danger-border); }
  .section.degraded { background: var(--bg); border: 1px solid var(--border); }
  .section-title { font: 600 12px var(--sans); text-transform: uppercase; letter-spacing: .4px; margin-bottom: 6px; }
  .section.active .section-title { color: #0d7a5f; }
  .section.needs-review .section-title { color: var(--warn-text); }
  .section.conflict .section-title { color: var(--danger-text); }
  .section.degraded .section-title { color: var(--muted); }
  .section ul { list-style: none; }
  .section li { padding: 4px 0; font-size: 14px; }
  .pill { display: inline-block; font: 600 10px var(--sans); text-transform: uppercase; letter-spacing: .3px; padding: 2px 7px; border-radius: 99px; vertical-align: 1px; }
  .pill.green { background: #c3e6d8; color: #0d7a5f; }
  .pill.amber { background: #fde9c3; color: var(--warn-text); }
  .pill.red { background: #fecaca; color: var(--danger-text); }
  .pill.gray { background: #e5e5e5; color: var(--muted); }
  [data-theme="dark"] .pill.green { background: #0d2818; color: #34d399; }
  [data-theme="dark"] .pill.amber { background: #2a2210; color: #fbbf24; }
  [data-theme="dark"] .pill.red { background: #2a1515; color: #f87171; }
  [data-theme="dark"] .pill.gray { background: #3a3a3a; color: #9a9a9a; }
  .rec { display: flex; align-items: flex-start; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--border); }
  .rec:last-child { border-bottom: none; }
  .rec .body { flex: 1; }
  .rec .text { font-size: 14px; }
  .rec .flags { margin-top: 3px; }
  .rec .outcome { display: flex; gap: 6px; flex-shrink: 0; }
  .rec .outcome button { font: 500 11px var(--sans); padding: 4px 10px; border-radius: 99px; border: 1.5px solid var(--border); background: var(--card); cursor: pointer; color: var(--muted); }
  .rec .outcome button:hover { border-color: var(--text); color: var(--text); }
  .rec .outcome button.sel { background: var(--text); color: var(--bg); border-color: var(--text); }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }
  .stat { background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
  .stat .val { font: 700 20px var(--mono); color: var(--text); }
  .stat .lbl { font: 11px var(--sans); color: var(--muted); margin-top: 2px; }
  .bucket-row { display: flex; align-items: center; gap: 8px; padding: 3px 0; font: 12px var(--mono); }
  .bucket-bar { height: 8px; border-radius: 4px; background: var(--accent); min-width: 2px; }
  .empty { color: var(--faint); font-size: 14px; text-align: center; padding: 20px; }
  .explain { font: 12px var(--sans); color: var(--muted); margin-top: 8px; padding: 8px 10px; background: var(--bg); border-radius: 8px; }
  .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid var(--border); border-top-color: var(--text); border-radius: 50%; animation: spin .6s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .hidden { display: none !important; }
  .add-rec { display: flex; gap: 6px; margin-top: 8px; align-items: center; }
  .add-rec input { flex: 1; font: 13px var(--sans); border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; background: var(--card); color: var(--text); outline: none; }
  .add-rec input:focus { border-color: var(--accent); }
  .add-rec button { font: 500 12px var(--sans); padding: 6px 12px; border-radius: 8px; border: 1px solid var(--border); background: var(--card); color: var(--muted); cursor: pointer; }
  .add-rec button:hover { border-color: var(--accent); color: var(--accent); }
</style></head><body>
<div class="app">
  <div class="header">
    <div class="brand"><svg viewBox="0 0 256 256" width="28" height="28"><rect x="28" y="28" width="200" height="200" rx="30" fill="none" stroke="currentColor" stroke-width="14"/><line x1="58" y1="82" x2="70" y2="82" stroke="currentColor" stroke-width="10"/><line x1="58" y1="130" x2="70" y2="130" stroke="currentColor" stroke-width="10"/><line x1="58" y1="178" x2="70" y2="178" stroke="currentColor" stroke-width="10"/><rect x="76" y="68" width="112" height="28" rx="9" fill="currentColor"/><rect x="76" y="116" width="72" height="28" rx="9" fill="currentColor"/><rect x="76" y="164" width="36" height="28" rx="9" fill="currentColor"/><circle cx="200" cy="200" r="50" fill="#10a37f"/><polyline points="179,201 194,216 222,187" fill="none" stroke="#fff" stroke-width="14" stroke-linecap="round" stroke-linejoin="round"/></svg> ClaimLedger</div>
    <div class="right"><div class="chains" id="chains"></div><button class="theme-toggle" onclick="toggleTheme()" title="toggle theme">◐</button></div>
  </div>
  <div class="task-box"><textarea id="task" rows="1" placeholder="Describe a task, and the memory layer will surface relevant constraints…" autofocus></textarea><button id="btn" onclick="decide()">Judge</button></div>
  <div class="meta" id="meta"></div>
  <div id="result" class="hidden"></div>
  <div class="card" id="add-rec-card"><div class="card-head">Add record</div><div class="card-body"><div class="add-rec"><input id="new-text" placeholder="a standalone decision or constraint…"><input id="new-scope" placeholder="scope" style="max-width:140px"><button onclick="addRecord()">+ Add</button></div></div></div>
  <div class="card" id="cal-card"><div class="card-head">◈ Calibration</div><div class="card-body" id="calibration"><div class="empty">outcomes will land here as you review records.</div></div></div>
</div>
<script>
let lastJudgment=null;const $=id=>document.getElementById(id);
const esc=s=>{const d=document.createElement("div");d.textContent=s??"";return d.innerHTML};
function toggleTheme(){const h=document.documentElement;const n=h.getAttribute("data-theme")==="dark"?"":"dark";h.setAttribute("data-theme",n);localStorage.setItem("theme",n)}
(function(){const s=localStorage.getItem("theme");const pd=window.matchMedia("(prefers-color-scheme: dark)").matches;if(s==="dark"||(!s&&pd))document.documentElement.setAttribute("data-theme","dark")})();
$("task").addEventListener("keydown",e=>{if((e.metaKey||e.ctrlKey)&&e.key==="Enter")decide()});
async function api(p,b){const o=b?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)}:{};const r=await fetch(p,o);const d=await r.json();if(d.error)throw new Error(d.error);return d}
async function decide(){const t=$("task").value.trim();if(!t)return;$("btn").disabled=true;$("btn").innerHTML='<span class="spinner"></span>';$("result").classList.add("hidden");try{lastJudgment=await api("/api/decide?task="+encodeURIComponent(t));render(lastJudgment);$("result").classList.remove("hidden");$("meta").textContent=`${lastJudgment.model} · ${lastJudgment.requests} requests · ${lastJudgment.latency_ms} ms · sealed ${lastJudgment.judgment_hash.slice(0,10)}…`+(lastJudgment.degraded?" · ⚠ degraded":"");refreshChains()}catch(e){$("meta").textContent="error: "+e.message}finally{$("btn").disabled=false;$("btn").textContent="Judge"}}
function render(j){const byId=Object.fromEntries(j.entries.map(e=>[e.record_id,e]));const admitted=j.entries.filter(e=>e.action==="admit"&&e.included);const review=j.entries.filter(e=>e.action==="review"&&e.included);let html="";
html+='<div class="card"><div class="card-head">📋 Brief</div><div class="card-body">';
if(admitted.length){html+='<div class="section active"><div class="section-title">✓ Active constraints</div><ul>'+admitted.map(e=>`<li>${esc(e.text)}${e.governing?' <span class="pill green">governing</span>':""}${e.low_margin?' <span class="pill amber">thin margin</span>':""}</li>`).join("")+"</ul></div>"}else{html+='<div class="section active"><div class="section-title">✓ Active constraints</div><div style="font-size:14px;color:var(--muted)">none admitted for this task.</div></div>'}
if(review.length){html+='<div class="section needs-review"><div class="section-title">⚠ Needs human review</div><ul>'+review.map(e=>`<li>${esc(e.text)} <span class="pill amber">${e.conflicted?"conflict":e.low_margin?"thin margin":"review"}</span></li>`).join("")+"</ul></div>"}
if((j.conflicts||[]).length){const byId=Object.fromEntries(j.entries.map(e=>[e.record_id,e.text]));html+='<div class="section conflict"><div class="section-title">⛔ Unresolved conflicts</div><ul>'+j.conflicts.map(p=>`<li>${esc(byId[p[0]]||p[0])} <span style="color:var(--danger-text)">⟂</span> ${esc(byId[p[1]]||p[1])}</li>`).join("")+"</ul></div>"}
if(j.degraded){html+='<div class="section degraded"><div class="section-title">⚠ Degraded</div><div style="font-size:13px">Judge unreachable — every record is review.</div></div>'}
html+="</div></div>";
const order={admit:0,review:1,exclude:2};const sorted=[...j.entries].sort((a,b)=>(order[a.action]-order[b.action])||((b.p_admit??0)-(a.p_admit??0)));
html+='<div class="card"><div class="card-head">☰ Records & outcomes</div><div class="card-body">';
html+=sorted.map(e=>{const cls=e.action==="admit"?"green":e.action==="review"?"amber":"gray";const flags=[e.governing?'<span class="pill green">governing</span>':"",e.conflicted?'<span class="pill red">conflicted</span>':"",e.low_margin?'<span class="pill amber">thin margin</span>':""].filter(Boolean).join(" ");const outcome=(j.outcomes&&j.outcomes[e.record_id])||"";const buttons=outcome?`<span class="pill ${outcome==="upheld"?"green":outcome==="overturned"?"red":"gray"}">${outcome}</span>`:["upheld","overturned","unclear"].map(v=>`<button onclick="postOutcome('${e.record_id}','${v}')">${v}</button>`).join(" ");return `<div class="rec"><div class="body"><div class="text">${esc(e.text)}</div><div class="flags"><span class="pill ${cls}">${e.action}</span> <span style="font:11px var(--mono);color:var(--faint)">p(admit) ${e.p_admit??"—"}</span> ${flags}</div></div><div class="outcome">${buttons}</div></div>`}).join("");
html+="</div></div>";$("result").innerHTML=html;refreshCalibration();setTimeout(()=>$("result").scrollIntoView({behavior:"smooth",block:"start"}),50)}
async function postOutcome(rid,v){await api("/api/outcome",{record_id:rid,verdict:v,judgment_hash:lastJudgment.judgment_hash,by:"console-human"});lastJudgment.outcomes=lastJudgment.outcomes||{};lastJudgment.outcomes[rid]=v;render(lastJudgment);setTimeout(()=>$("cal-card").scrollIntoView({behavior:"smooth",block:"nearest"}),50)}
async function addRecord(){const t=$("new-text").value.trim();if(!t)return;await api("/api/record",{text:t,source:"console",scope:$("new-scope").value.trim()||null});$("new-text").value="";$("new-scope").value="";refreshChains()}
async function refreshCalibration(){const r=await api("/api/calibrate");const el=$("calibration");if(!r.n_scored){let m="no scoreable outcomes yet — click upheld / overturned on an admit entry.";if(r.n_outcomes>0&&r.unsupported>0)m=`${r.n_outcomes} outcome${r.n_outcomes>1?"s":""} recorded, ${r.unsupported} on review entries (calibration v1 scores admit only).`;el.innerHTML=`<div class="empty">${m}</div>`;return}
let h='<div class="stats">'+`<div class="stat"><div class="val">${r.n_scored}</div><div class="lbl">scored</div></div>`+`<div class="stat"><div class="val">${r.overall_upheld_rate??"—"}</div><div class="lbl">upheld rate</div></div>`+`<div class="stat"><div class="val">${r.brier??"—"}</div><div class="lbl">Brier score</div></div></div>`;
const br=Object.entries(r.buckets).filter(([k,v])=>v.n>0);if(br.length){h+='<div style="margin-top:10px">';for(const[b,d]of br){const rate=d.upheld_rate!=null?`${(d.upheld_rate*100).toFixed(0)}%`:"—";h+=`<div class="bucket-row"><span style="width:80px">${b}</span><div class="bucket-bar" style="width:${(d.upheld_rate??0)*120}px"></div><span>${d.n} · ${rate}</span></div>`}h+="</div>"}
el.innerHTML=h}
async function refreshChains(){const c=await api("/api/audit");$("chains").innerHTML=`<span><span class="dot"></span>${c.records} records</span><span><span class="dot"></span>${c.judgments} judgments</span><span><span class="dot"></span>${c.outcomes} outcomes</span>`+(c.degraded?`<span style="color:var(--danger-text)">⚠ ${c.degraded} degraded</span>`:"")}
refreshChains();
</script></body></html>"""


class Console:
    """Stateful view over one store + one directory of chain files."""

    def __init__(self, store_path: Path, directory: Path):
        self.store = RecordStore(store_path)
        self.cache = Cache(directory / "cache.jsonl")
        self.log_path = directory / "judgments.jsonl"
        self.outcomes_path = directory / "outcomes.jsonl"
        self.last: Optional[Dict[str, Any]] = None

    # ---- endpoints ---------------------------------------------------------

    def api_decide(self, params: Mapping[str, str]) -> Dict[str, Any]:
        task = (params.get("task") or "").strip()
        if not task:
            return {"error": "task is required"}
        records = self.store.load()
        if not records:
            return {"error": "record store is empty — add records first"}
        limit = min(max(int(params.get("limit", 6)), 1), 6)
        candidates, stats = select_candidates(records, task,
                                              scope=params.get("scope"),
                                              limit=limit)
        if not candidates:
            return {"error": "no candidates in scope for this task"}
        budget = int(params.get("budget", DEFAULT_BUDGET_BYTES))
        judgment = judge(task, candidates, budget_bytes=budget,
                         on_error="review", cache=self.cache)
        brief = render_brief(judgment)
        sealed = jlog.append_judgment(self.log_path, judgment.to_dict())
        outcomes = {o["record_id"]: o["verdict"]
                    for o in read_outcomes(self.outcomes_path)
                    if o.get("judgment_hash") == sealed["judgment_hash"]}
        self.last = sealed
        return {
            "task": task, "model": judgment.model,
            "question_set_version": judgment.question_set_version,
            "policy": judgment.policy, "degraded": judgment.degraded,
            "latency_ms": judgment.latency_ms, "requests": judgment.requests,
            "entries": judgment.to_dict()["entries"],
            "conflicts": judgment.conflicts,
            "uncertain_pairs": judgment.uncertain_pairs,
            "governing": judgment.governing,
            "used_bytes": judgment.used_bytes, "budget_bytes": judgment.budget_bytes,
            "omitted": judgment.omitted, "selection": stats,
            "brief_text": brief["text"], "brief_bytes": brief["bytes"],
            "judgment_hash": sealed["judgment_hash"], "outcomes": outcomes,
        }

    def api_record(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        record = self.store.append(str(body["text"]), str(body.get("source", "console")),
                                   scope=body.get("scope"))
        return {"record": record, "total_records": len(self.store.load())}

    def api_records(self) -> List[Dict[str, Any]]:
        return self.store.load()

    def api_outcome(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        judgment_hash = body.get("judgment_hash") or (
            self.last["judgment_hash"] if self.last else None)
        if not judgment_hash:
            return {"error": "no judgment to attach the outcome to"}
        return {"outcome": append_outcome(
            self.outcomes_path, judgment_hash=str(judgment_hash),
            record_id=str(body["record_id"]), verdict=str(body["verdict"]),
            by=str(body.get("by", "console-human")),
            note=str(body.get("note", "")))}

    def api_calibrate(self) -> Dict[str, Any]:
        return calibrate(jlog.read(self.log_path),
                         read_outcomes(self.outcomes_path), action="admit")

    def api_audit(self) -> Dict[str, Any]:
        records = len(self.store.load())
        judgments = jlog.verify(self.log_path)
        outcomes = verify_outcomes(self.outcomes_path)
        summary = {
            "records": records, "judgments": judgments, "outcomes": outcomes,
            "degraded": sum(1 for r in jlog.read(self.log_path) if r.get("degraded")),
            "confirmed_conflicts": sum(len(r.get("conflicts", []))
                                       for r in jlog.read(self.log_path)),
        }
        return summary


def make_handler(console: Console):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, payload: Dict[str, Any], status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            try:
                self._route_get()
            except Exception as exc:  # noqa: BLE001 - the console must never crash
                self._send({"error": f"{type(exc).__name__}: {exc}"}, 500)

        def _route_get(self) -> None:
            route = urlparse(self.path)
            if route.path == "/":
                page = PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
            elif route.path == "/api/records":
                self._send(console.api_records())
            elif route.path == "/api/calibrate":
                self._send(console.api_calibrate())
            elif route.path == "/api/audit":
                self._send(console.api_audit())
            elif route.path == "/api/decide":
                self._send(console.api_decide(
                    {k: v[0] for k, v in parse_qs(route.query).items()}))
            else:
                self._send({"error": "not found"}, 404)

        def do_POST(self) -> None:  # noqa: N802
            try:
                self._route_post()
            except Exception as exc:  # noqa: BLE001
                self._send({"error": f"{type(exc).__name__}: {exc}"}, 500)

        def _route_post(self) -> None:
            route = urlparse(self.path)
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except json.JSONDecodeError:
                self._send({"error": "body is not JSON"}, 400)
                return
            if route.path == "/api/record":
                self._send(console.api_record(body))
            elif route.path == "/api/outcome":
                self._send(console.api_outcome(body))
            else:
                self._send({"error": "not found"}, 404)

        def log_message(self, fmt: str, *args: Any) -> None:
            pass  # keep stdout clean; errors surface in the page

    return Handler


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="jev_first.console",
                                     description="local memory console (single user)")
    parser.add_argument("--store", required=True, help="records.jsonl path")
    parser.add_argument("--dir", default="~/.jev-memory",
                        help="directory for log/cache/outcomes")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args(argv)
    directory = Path(args.dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    console = Console(Path(args.store).expanduser(), directory)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(console))
    print(f"jev-memory console on http://127.0.0.1:{args.port}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())