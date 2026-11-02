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

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>jev-memory console</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root { color-scheme: light; }
  body { font: 14px/1.5 ui-monospace, Menlo, Consolas, monospace; color: #111;
         background: #fff; max-width: 880px; margin: 24px auto; padding: 0 16px; }
  h1 { font-size: 18px; } h2 { font-size: 14px; border-bottom: 2px solid #111;
       padding-bottom: 4px; margin-top: 28px; }
  .muted { color: #8a8a8a; } .warn { color: #111; background: #f0f0f0; padding: 2px 6px; }
  button { font: inherit; border: 1.5px solid #111; background: #fff; padding: 4px 10px;
           cursor: pointer; }
  button:hover { background: #111; color: #fff; }
  input, select { font: inherit; border: 1.5px solid #111; padding: 4px 8px; width: 60%; }
  table { border-collapse: collapse; width: 100%; margin: 8px 0; }
  th, td { border: 1px solid #d9d9d9; padding: 5px 8px; text-align: left; }
  .admit { font-weight: 700; } .review { color: #555; } .exclude { color: #9a9a9a; }
  .flag { background: #f0f0f0; padding: 1px 5px; margin-left: 6px; }
  pre { background: #f7f7f7; border: 1px solid #d9d9d9; padding: 10px; white-space: pre-wrap; }
  .row { display: flex; gap: 10px; margin: 8px 0; align-items: center; }
  .ok { color: #111; font-weight: 700; } .err { color: #8a8a8a; }
  dl { display: grid; grid-template-columns: 140px 1fr; gap: 2px 12px; }
  dt { color: #8a8a8a; } dd { margin: 0; }
</style></head><body>
<h1>jev-memory console</h1>
<p class="muted">local single-user view · every number below comes from a live
engine call or the sealed log · the buttons exist to collect outcomes</p>

<h2>1 · task</h2>
<div class="row"><input id="task" placeholder="task for the agent, e.g. write a storage adapter for analytics">
<button onclick="decide()">judge</button><span id="decide-meta" class="muted"></span></div>

<h2>2 · brief</h2>
<div id="brief" class="muted">run a judgment to see the brief.</div>

<h2>3 · records &amp; outcomes</h2>
<p class="muted">click a verdict per record: was the system's action for this record right?
this is the only input calibration trusts.</p>
<table id="entries"><thead><tr>
  <th>record</th><th>action</th><th>p(admit)</th><th>flags</th><th>outcome</th></tr></thead>
  <tbody></tbody></table>

<h2>4 · calibration</h2>
<div id="calibration" class="muted">outcomes will land here.</div>

<h2>5 · chains</h2>
<div id="chains" class="muted"></div>

<script>
let lastJudgment = null;
const $ = id => document.getElementById(id);
async function api(path, body) {
  const opt = body ? {method: "POST", headers: {"Content-Type": "application/json"},
                      body: JSON.stringify(body)} : {};
  const res = await fetch(path, opt);
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  return data;
}
function esc(s) { const d = document.createElement("div"); d.textContent = s ?? ""; return d.innerHTML; }
async function decide() {
  const task = $("task").value.trim();
  if (!task) return;
  try {
    lastJudgment = await api("/api/decide?task=" + encodeURIComponent(task));
    renderBrief(lastJudgment);
    renderEntries(lastJudgment);
    $("decide-meta").textContent =
      `${lastJudgment.model} · requests ${lastJudgment.requests} · ` +
      `${lastJudgment.latency_ms} ms · sealed ${lastJudgment.judgment_hash.slice(0,12)}…` +
      (lastJudgment.degraded ? " · DEGRADED (judge unreachable)" : "");
    refreshChains();
  } catch (e) { $("decide-meta").textContent = "error: " + e.message; }
}
function renderBrief(j) {
  let html = "";
  const active = j.entries.filter(e => e.action === "admit" && e.included);
  html += active.length
    ? "<b>ACTIVE CONSTRAINTS (must follow):</b><ul>" +
      active.map(e => `<li>${esc(e.text)}${e.governing ? " [governing]" : ""}${e.low_margin ? " [thin margin]" : ""}</li>`).join("") + "</ul>"
    : "<b>ACTIVE CONSTRAINTS:</b> none admitted for this task.";
  const review = j.entries.filter(e => e.action === "review" && e.included);
  if (review.length) {
    html += "<b>NEEDS HUMAN REVIEW (do not rely yet):</b><ul>" +
      review.map(e => `<li>${esc(e.text)} [${e.conflicted ? "conflicts with another record" : e.low_margin ? "thin margin" : "model asked for review"}]</li>`).join("") + "</ul>";
  }
  if ((j.conflicts || []).length) {
    const byId = Object.fromEntries(j.entries.map(e => [e.record_id, e.text]));
    html += "<b>UNRESOLVED CONFLICTS:</b><ul>" +
      j.conflicts.map(p => `<li>${esc(byId[p[0]])} ⟂ ${esc(byId[p[1]])}</li>`).join("") + "</ul>";
  }
  if (j.degraded) html += "<p class='warn'>DEGRADED: judge unreachable — do not act without a human.</p>";
  $("brief").innerHTML = html;
}
function renderEntries(j) {
  const order = {admit: 0, review: 1, exclude: 2};
  const rows = [...j.entries].sort((a, b) => (b.p_admit ?? 0) - (a.p_admit ?? 0));
  $("entries").querySelector("tbody").innerHTML = rows.map(e => {
    const flags = [
      e.governing ? "governing" : "",
      e.conflicted ? "conflicted" : "",
      e.low_margin ? "thin margin" : ""].filter(Boolean).map(f => `<span class="flag">${f}</span>`).join("");
    const outcome = (j.outcomes && j.outcomes[e.record_id]) || "";
    return `<tr><td>${esc(e.text)}</td>` +
      `<td class="${e.action}">${e.action}</td>` +
      `<td>${e.p_admit ?? ""}</td><td>${flags}</td>` +
      `<td>${outcome || `<button onclick="postOutcome('${e.record_id}','upheld')">upheld</button> ` +
        `<button onclick="postOutcome('${e.record_id}','overturned')">overturned</button> ` +
        `<button onclick="postOutcome('${e.record_id}','unclear')">unclear</button>`}</td></tr>`;
  }).join("");
}
async function postOutcome(recordId, verdict) {
  await api("/api/outcome", {record_id: recordId, verdict: verdict,
                             judgment_hash: lastJudgment.judgment_hash, by: "console-human"});
  await decide();
  await refreshCalibration();
}
async function refreshCalibration() {
  const report = await api("/api/calibrate");
  if (!report.n_scored) { $("calibration").textContent = "no scoreable outcomes yet."; return; }
  let html = `<dl><dt>scored</dt><dd>${report.n_scored} of ${report.n_outcomes}</dd>` +
    `<dt>upheld rate</dt><dd>${report.overall_upheld_rate}</dd>` +
    `<dt>Brier</dt><dd>${report.brier ?? "-"}</dd></dl>` +
    "<table><tr><th>p(admit) bucket</th><th>n</th><th>upheld rate</th></tr>" +
    Object.entries(report.buckets).filter(([k, v]) => v.n > 0)
      .map(([k, v]) => `<tr><td>${k}</td><td>${v.n}</td><td>${v.upheld_rate}</td></tr>`).join("") +
    "</table>";
  $("calibration").innerHTML = html;
}
async function refreshChains() {
  const chains = await api("/api/audit");
  $("chains").innerHTML =
    `<dl><dt>record chain</dt><dd>${chains.records} records, verified</dd>` +
    `<dt>judgment chain</dt><dd>${chains.judgments} judgments, verified</dd>` +
    `<dt>outcome chain</dt><dd>${chains.outcomes} outcomes, verified</dd>` +
    `<dt>degraded</dt><dd>${chains.degraded}</dd>` +
    `<dt>confirmed conflicts</dt><dd>${chains.confirmed_conflicts}</dd></dl>`;
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