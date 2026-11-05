"""A2A smoke test: two agent identities round-trip through governed memory.

    python scripts/a2a_smoke.py --dir /tmp/jev-a2a

Runs the full two-agent loop through the PRODUCT code paths (the same MCP
handler Doubao Work calls, the same console API a human confirms through):

    zcode proposes ──► human confirms ──► doubao-work reads it in a brief
    doubao-work proposes ──► human confirms ──► zcode reads it
    zcode + doubao-work records conflict ──► edge proposed ──► human confirms

Uses a throwaway directory: the 14-day real-use store is never touched.
Requires TYPESAFE_API_KEY (the judgment provider) for the read half.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jev_first import contracts, edges as edge_log  # noqa: E402
from jev_first import proposals as proposal_log  # noqa: E402
from jev_first.log import read as read_log  # noqa: E402
from jev_first.mcp_server import MemoryServer  # noqa: E402
from jev_first.records import RecordStore  # noqa: E402
from jev_first.web import Console  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))


def mcp(server: MemoryServer, tool: str, args: dict) -> dict:
    resp = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": tool, "arguments": args}})
    body = json.loads(resp["result"]["content"][0]["text"])
    if resp["result"].get("isError"):
        raise RuntimeError(f"{tool}: {body}")
    return body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="/tmp/jev-a2a")
    parser.add_argument("--env-file", default="~/.config/claimledger/jev.env")
    args = parser.parse_args()

    for line in Path(os.path.expanduser(args.env_file)).read_text().splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.replace("export", "").strip(),
                                  v.strip().strip("'\""))

    base = Path(args.dir)
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)
    server = MemoryServer(base)
    console = Console(base / "records.jsonl", base)

    print("== setup: two agent identities ==")
    for name in ("zcode", "doubao-work"):
        console.api_register_agent({"name": name, "kind": "agent"})
    agents = console.api_agents()
    check("both identities registered",
          {a["name"] for a in agents} == {"zcode", "doubao-work"},
          str([a["name"] for a in agents]))

    print("\n== step 1: zcode proposes, human confirms ==")
    proposed = mcp(server, "memory_propose",
                   {"text": "All storage must use PostgreSQL.",
                    "source": "zcode"})
    check("zcode write is a proposal, not a record",
          proposed.get("created") is True
          and proposed["proposal"]["source"] == "zcode"
          and len(console.store.load()) == 0,
          f"proposal {proposed['proposal']['proposal_id']}")
    confirmed = console.api_confirm({"proposal_id": proposed["proposal"]["proposal_id"],
                                     "decision": "confirm", "by": "console-human"})
    record_pg = confirmed["record"]
    check("human confirmation creates the record, attribution preserved",
          record_pg["source"] == "zcode", f"record source={record_pg['source']}")

    print("\n== step 2: doubao-work reads zcode's record ==")
    brief_d = mcp(server, "memory_brief", {"task": "write a storage adapter"})
    check("doubao-work's brief carries zcode's constraint",
          "All storage must use PostgreSQL." in brief_d["brief"])
    check("the read is sealed to the log", "judgment_hash" in brief_d)

    print("\n== step 3: doubao-work proposes, human confirms, zcode reads ==")
    proposed2 = mcp(server, "memory_propose",
                    {"text": "Secrets must never be logged.", "source": "doubao-work"})
    check("doubao-work proposes with its own attribution",
          proposed2["proposal"]["source"] == "doubao-work")
    confirmed2 = console.api_confirm({"proposal_id": proposed2["proposal"]["proposal_id"],
                                      "decision": "confirm", "by": "console-human"})
    check("second record carries doubao-work as source",
          confirmed2["record"]["source"] == "doubao-work")
    brief_z = mcp(server, "memory_brief", {"task": "review logging of secrets"})
    check("zcode's brief carries doubao-work's constraint",
          "Secrets must never be logged." in brief_z["brief"])

    print("\n== step 4: a cross-agent conflict becomes a proposed edge ==")
    proposed3 = mcp(server, "memory_propose",
                    {"text": "Deployments must happen only on Tuesdays.", "source": "zcode"})
    console.api_confirm({"proposal_id": proposed3["proposal"]["proposal_id"],
                         "decision": "confirm", "by": "console-human"})
    proposed4 = mcp(server, "memory_propose",
                    {"text": "The production release train departs on Friday.", "source": "doubao-work"})
    console.api_confirm({"proposal_id": proposed4["proposal"]["proposal_id"],
                         "decision": "confirm", "by": "console-human"})
    decide = mcp(server, "memory_decide", {"task": "Deployments and the release train: choose a day"})
    edge_proposals = decide.get("edges") or []
    check("judge proposes an edge from the cross-agent conflict",
          any(e["edge_type"] == "contradicts" for e in edge_proposals),
          str([(e["edge_type"], e["confidence"]) for e in edge_proposals]))
    if edge_proposals:
        eid = edge_proposals[0]["edge_id"]
        check("edge waits for the human gate (pending, with direction when needed)",
              edge_log.statuses(base / "edges.jsonl").get(eid) == "pending",
              eid)
        console.api_edge_confirm({"edge_id": eid, "decision": "confirm",
                                  "by": "console-human"})
        check("edge confirmed into the graph",
              edge_log.statuses(base / "edges.jsonl").get(eid) == "confirmed")

    print("\n== step 5: chain integrity and audit surfaces ==")
    check("proposal chain verifies", proposal_log.verify(base / "proposals.jsonl") > 0)
    check("edge chain verifies", base.joinpath("edges.jsonl").exists()
          and edge_log.verify(base / "edges.jsonl") >= 1)
    check("records chain verifies",
          len(RecordStore(base / "records.jsonl").load()) == 4)
    audit = mcp(server, "memory_audit", {})
    check("audit counts both identities' work",
          audit.get("n_judgments", 0) >= 3, f"judgments={audit.get('n_judgments')}")
    props = mcp(server, "memory_proposals", {})
    check("nothing left pending after the gates", props["count"] == 0
          and props["pending_edge_count"] == 0)

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n== a2a smoke: {passed}/{total} checks passed ==")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())