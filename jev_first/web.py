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
    --bg: #f7f7f8; --card: #ffffff; --border: #e5e5e5; --border-hover: #d0d0d0;
    --text: #1a1a1a; --muted: #6b6b6b; --faint: #9a9a9a;
    --accent: #10a37f; --accent-soft: #e6f7f1;
    --warn-bg: #fff8eb; --warn-border: #f5d98a; --warn-text: #92690a;
    --danger-bg: #fef2f2; --danger-border: #fecaca; --danger-text: #b91c1c;
    --info-bg: #eff6ff; --info-border: #bfdbfe; --info-text: #1d4ed8;
    --radius: 12px; --radius-sm: 8px;
    --shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
    --shadow-md: 0 4px 12px rgba(0,0,0,0.08);
    --mono: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
    --sans: -apple-system, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: var(--sans); background: var(--bg); color: var(--text);
         min-height: 100vh; }
  .app { max-width: 720px; margin: 0 auto; padding: 0 16px 64px; }

  /* header */
  .header { display: flex; align-items: center; justify-content: space-between;
            padding: 16px 0; }
  .header .brand { display: flex; align-items: center; gap: 10px;
                   font-weight: 600; font-size: 15px; }
  .header .brand svg { width: 28px; height: 28px; }
  .header .chains { display: flex; gap: 12px; font-size: 12px; color: var(--muted); }
  .header .chains .dot { width: 7px; height: 7px; border-radius: 50%;
                         background: var(--accent); display: inline-block; margin-right: 4px; }

  /* task input */
  .task-box { background: var(--card); border: 1px solid var(--border);
              border-radius: var(--radius); box-shadow: var(--shadow); padding: 4px;
              display: flex; gap: 8px; align-items: flex-end; }
  .task-box textarea { flex: 1; border: none; outline: none; resize: none;
                       font: 15px/1.4 var(--sans); color: var(--text);
                       padding: 10px 12px; min-height: 44px; background: transparent; }
  .task-box textarea::placeholder { color: var(--faint); }
  .task-box button { background: var(--text); color: #fff; border: none;
                     border-radius: var(--radius-sm); padding: 9px 18px;
                     font: 600 14px var(--sans); cursor: pointer; white-space: nowrap; }
  .task-box button:disabled { opacity: 0.5; cursor: default; }
  .task-box button:hover:not(:disabled) { background: #333; }
  .meta { font: 11px var(--mono); color: var(--faint); padding: 6px 4px 0; }

  /* cards */
  .card { background: var(--card); border: 1px solid var(--border);
          border-radius: var(--radius); box-shadow: var(--shadow);
          margin-top: 14px; overflow: hidden; }
  .card-head { padding: 12px 16px; border-bottom: 1px solid var(--border);
               font: 600 13px var(--sans); display: flex; align-items: center; gap: 8px; }
  .card-body { padding: 14px 16px; }

  /* section blocks inside brief */
  .section { border-radius: var(--radius-sm); padding: 12px 14px; margin-bottom: 10px; }
  .section:last-child { margin-bottom: 0; }
  .section.active { background: var(--accent-soft); border: 1px solid #c3e6d8; }
  .section.needs-review { background: var(--warn-bg); border: 1px solid var(--warn-border); }
  .section.conflict { background: var(--danger-bg); border: 1px solid var(--danger-border); }
  .section.degraded { background: #f0f0f0; border: 1px solid var(--border); }
  .section-title { font: 600 12px var(--sans); text-transform: uppercase;
                   letter-spacing: 0.4px; margin-bottom: 6px; }
  .section.active .section-title { color: #0d7a5f; }
  .section.needs-review .section-title { color: var(--warn-text); }
  .section.conflict .section-title { color: var(--danger-text); }
  .section.degraded .section-title { color: var(--muted); }
  .section ul { list-style: none; }
  .section li { padding: 4px 0; font-size: 14px; display: flex; align-items: baseline; gap: 6px; }
  .section li::before { content: "·"; font-weight: 700; }
  .pill { display: inline-block; font: 600 10px var(--sans); text-transform: uppercase;
          letter-spacing: 0.3px; padding: 2px 7px; border-radius: 99px; vertical-align: 1px; }
  .pill.green { background: #c3e6d8; color: #0d7a5f; }
  .pill.amber { background: #fde9c3; color: var(--warn-text); }
  .pill.red { background: #fecaca; color: var(--danger-text); }
  .pill.gray { background: #e5e5e5; color: var(--muted); }

  /* record rows */
  .rec { display: flex; align-items: flex-start; gap: 12px; padding: 10px 0;
         border-bottom: 1px solid #f0f0f0; }
  .rec:last-child { border-bottom: none; }
  .rec .body { flex: 1; }
  .rec .body .text { font-size: 14px; }
  .rec .body .flags { margin-top: 3px; }
  .rec .outcome { display: flex; gap: 6px; flex-shrink: 0; }
  .rec .outcome button { font: 500 11px var(--sans); padding: 4px 10px;
                         border-radius: 99px; border: 1.5px solid var(--border);
                         background: var(--card); cursor: pointer; color: var(--muted); }
  .rec .outcome button:hover { border-color: var(--text); color: var(--text); }
  .rec .outcome button.sel { background: var(--text); color: #fff;
                             border-color: var(--text); }

  /* calibration strip */
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
           gap: 10px; }
  .stat { background: var(--bg); border: 1px solid var(--border);
          border-radius: var(--radius-sm); padding: 10px 12px; }
  .stat .val { font: 700 20px var(--mono); color: var(--text); }
  .stat .lbl { font: 11px var(--sans); color: var(--muted); margin-top: 2px; }
  .bucket-row { display: flex; align-items: center; gap: 8px; padding: 3px 0;
                font: 12px var(--mono); }
  .bucket-bar { height: 8px; border-radius: 4px; background: var(--accent);
                min-width: 2px; }

  .empty { color: var(--faint); font-size: 14px; text-align: center; padding: 20px; }
  .spinner { display: inline-block; width: 14px; height: 14px;
             border: 2px solid var(--border); border-top-color: var(--text);
             border-radius: 50%; animation: spin 0.6s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .hidden { display: none !important; }
</style></head><body>
<div class="app">
  <div class="header">
    <div class="brand">
      <svg viewBox="0 0 256 256" width="28" height="28"><rect x="28" y="28" width="200" height="200" rx="30" fill="none" stroke="#1a1a1a" stroke-width="14"/><line x1="58" y1="82" x2="70" y2="82" stroke="#1a1a1a" stroke-width="10"/><line x1="58" y1="130" x2="70" y2="130" stroke="#1a1a1a" stroke-width="10"/><line x1="58" y1="178" x2="70" y2="178" stroke="#1a1a1a" stroke-width="10"/><rect x="76" y="68" width="112" height="28" rx="9" fill="#1a1a1a"/><rect x="76" y="116" width="72" height="28" rx="9" fill="#1a1a1a"/><rect x="76" y="164" width="36" height="28" rx="9" fill="#1a1a1a"/><circle cx="200" cy="200" r="50" fill="#10a37f"/><polyline points="179,201 194,216 222,187" fill="none" stroke="#ffffff" stroke-width="14" stroke-linecap="round" stroke-linejoin="round"/></svg>
      ClaimLedger
    </div>
    <div class="chains" id="chains"></div>
  </div>

  <div class="task-box">
    <textarea id="task" rows="1" placeholder="Describe a task, and the memory layer will surface relevant constraints…" autofocus></textarea>
    <button id="btn" onclick="decide()">Judge</button>
  </div>
  <div class="meta" id="meta"></div>

  <div id="result" class="hidden"></div>

  <div class="card" id="cal-card">
    <div class="card-head">Calibration</div>
    <div class="card-body" id="calibration"><div class="empty">outcomes will land here as you review records.</div></div>
  </div>
</div>

<script>
let lastJudgment = null;
const $ = id => document.getElementById(id);
const esc = s => { const d = document.createElement("div"); d.textContent = s ?? ""; return d.innerHTML; };

async function api(path, body) {
  const opt = body ? {method: "POST", headers: {"Content-Type": "application/json"},
                      body: JSON.stringify(body)} : {};
  const res = await fetch(path, opt);
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  return data;
}

async function decide() {
  const task = $("task").value.trim();
  if (!task) return;
  $("btn").disabled = true;
  $("btn").innerHTML = '<span class="spinner"></span>';
  $("result").classList.add("hidden");
  try {
    lastJudgment = await api("/api/decide?task=" + encodeURIComponent(task));
    render(lastJudgment);
    $("result").classList.remove("hidden");
    $("meta").textContent =
      `${lastJudgment.model} · ${lastJudgment.requests} requests · ` +
      `${lastJudgment.latency_ms} ms · sealed ${lastJudgment.judgment_hash.slice(0,10)}…` +
      (lastJudgment.degraded ? " · ⚠ degraded" : "");
    refreshChains();
  } catch (e) {
    $("meta").textContent = "error: " + e.message;
  } finally {
    $("btn").disabled = false;
    $("btn").textContent = "Judge";
  }
}

function render(j) {
  const byId = Object.fromEntries(j.entries.map(e => [e.record_id, e]));
  const admitted = j.entries.filter(e => e.action === "admit" && e.included);
  const review = j.entries.filter(e => e.action === "review" && e.included);
  const excluded = j.entries.filter(e => e.action === "exclude");
  let html = "";

  /* brief card */
  html += '<div class="card"><div class="card-head">Brief</div><div class="card-body">';
  if (admitted.length) {
    html += '<div class="section active"><div class="section-title">✓ Active constraints</div><ul>' +
      admitted.map(e => `<li>${esc(e.text)}${e.governing ? ' <span class="pill green">governing</span>' : ""}${e.low_margin ? ' <span class="pill amber">thin margin</span>' : ""}</li>`).join("") + "</ul></div>";
  } else {
    html += '<div class="section active"><div class="section-title">Active constraints</div><div style="font-size:14px;color:var(--muted)">none admitted for this task.</div></div>';
  }
  if (review.length) {
    html += '<div class="section needs-review"><div class="section-title">⚠ Needs human review</div><ul>' +
      review.map(e => `<li>${esc(e.text)} <span class="pill amber">${e.conflicted ? "conflict" : e.low_margin ? "thin margin" : "review"}</span></li>`).join("") + "</ul></div>";
  }
  if ((j.conflicts || []).length) {
    html += '<div class="section conflict"><div class="section-title">⛔ Unresolved conflicts</div><ul>' +
      j.conflicts.map(p => `<li>${esc(byId[p[0]]?.text || p[0])} <span style="color:var(--danger-text)">⟂</span> ${esc(byId[p[1]]?.text || p[1])}</li>`).join("") + "</ul></div>";
  }
  if (j.degraded) {
    html += '<div class="section degraded"><div class="section-title">⚠ Degraded</div><div style="font-size:13px">Judgment provider unreachable — every record is review. Do not act without human confirmation.</div></div>';
  }
  html += "</div></div>";

  /* records card */
  const order = {admit: 0, review: 1, exclude: 2};
  const sorted = [...j.entries].sort((a, b) => (order[a.action] - order[b.action]) || ((b.p_admit ?? 0) - (a.p_admit ?? 0)));
  html += '<div class="card"><div class="card-head">Records &amp; outcomes</div><div class="card-body">';
  html += sorted.map(e => {
    const cls = e.action === "admit" ? "green" : e.action === "review" ? "amber" : "gray";
    const flags = [
      e.governing ? '<span class="pill green">governing</span>' : "",
      e.conflicted ? '<span class="pill red">conflicted</span>' : "",
      e.low_margin ? '<span class="pill amber">thin margin</span>' : ""
    ].filter(Boolean).join(" ");
    const outcome = (j.outcomes && j.outcomes[e.record_id]) || "";
    const buttons = outcome
      ? `<span class="pill ${outcome === "upheld" ? "green" : outcome === "overturned" ? "red" : "gray"}">${outcome}</span>`
      : ["upheld", "overturned", "unclear"].map(v =>
          `<button onclick="postOutcome('${e.record_id}','${v}')">${v}</button>`).join(" ");
    return `<div class="rec"><div class="body"><div class="text">${esc(e.text)}</div>` +
      `<div class="flags"><span class="pill ${cls}">${e.action}</span> ` +
      `<span style="font:11px var(--mono);color:var(--faint)">p(admit) ${e.p_admit ?? "—"}</span> ${flags}</div></div>` +
      `<div class="outcome">${buttons}</div></div>`;
  }).join("");
  html += "</div></div>";

  $("result").innerHTML = html;
  refreshCalibration();
}

async function postOutcome(recordId, verdict) {
  await api("/api/outcome", {record_id: recordId, verdict: verdict,
                             judgment_hash: lastJudgment.judgment_hash, by: "console-human"});
  lastJudgment.outcomes = lastJudgment.outcomes || {};
  lastJudgment.outcomes[recordId] = verdict;
  render(lastJudgment);
}

async function refreshCalibration() {
  const report = await api("/api/calibrate");
  const el = $("calibration");
  if (!report.n_scored) {
    el.innerHTML = '<div class="empty">no scoreable outcomes yet — click upheld / overturned above.</div>';
    return;
  }
  let html = '<div class="stats">' +
    `<div class="stat"><div class="val">${report.n_scored}</div><div class="lbl">scored</div></div>` +
    `<div class="stat"><div class="val">${report.overall_upheld_rate ?? "—"}</div><div class="lbl">upheld rate</div></div>` +
    `<div class="stat"><div class="val">${report.brier ?? "—"}</div><div class="lbl">Brier score</div></div></div>`;
  const bucketRows = Object.entries(report.buckets).filter(([k, v]) => v.n > 0);
  if (bucketRows.length) {
    html += '<div style="margin-top:10px">';
    for (const [bucket, data] of bucketRows) {
      const rate = data.upheld_rate != null ? `${(data.upheld_rate * 100).toFixed(0)}%` : "—";
      html += `<div class="bucket-row"><span style="width:80px">${bucket}</span>` +
        `<div class="bucket-bar" style="width:${(data.upheld_rate ?? 0) * 120}px"></div>` +
        `<span>${data.n} · ${rate}</span></div>`;
    }
    html += "</div>";
  }
  el.innerHTML = html;
}

async function refreshChains() {
  const chains = await api("/api/audit");
  $("chains").innerHTML =
    `<span><span class="dot"></span>${chains.records} records</span>` +
    `<span><span class="dot"></span>${chains.judgments} judgments</span>` +
    `<span><span class="dot"></span>${chains.outcomes} outcomes</span>` +
    (chains.degraded ? `<span style="color:var(--danger-text)">⚠ ${chains.degraded} degraded</span>` : "");
}
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