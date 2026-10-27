#!/usr/bin/env python3
"""Check repository links and execute the README examples with an installed CLI.

The demo uses handwritten synthetic cards in a temporary directory. No model,
network request, user vault, or native host-compaction event is exercised.
"""
import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
README_FILES = ("README.md", "README.zh-CN.md")


def example(text, name, language):
    pattern = r"<!-- verify:" + re.escape(name) + r" -->\s*```" + re.escape(language) + r"\n(.*?)\n```"
    matches = re.findall(pattern, text, re.S)
    if len(matches) != 1:
        raise ValueError("expected one example: " + name)
    return matches[0]


def _read_demo_path(tmp, filename):
    """Read a path emitted by Git Bash, translating POSIX /tmp on Windows."""
    raw = (Path(tmp) / filename).read_text().strip()
    if os.name == "nt" and raw.startswith("/"):
        converted = subprocess.run(
            ["bash", "-c", 'cygpath -w "$1"', "_", raw],
            capture_output=True, text=True)
        if converted.returncode == 0 and converted.stdout.strip():
            raw = converted.stdout.strip()
    return Path(raw).resolve()


def anchors(text):
    """Heading IDs for the subset used here, plus explicit HTML anchors."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    found = set(re.findall(r'<[^>]+(?:id|name)=[\"\']([^\"\']+)', text))
    counts = {}
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.M):
        heading = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", heading)
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        found.add(slug + ("-" + str(count) if count else ""))
    return found


def check_links(root, files):
    """Validate local targets/Markdown fragments; external HTTP links are not fetched."""
    root = Path(root).resolve()
    checked = 0
    external = 0
    for relative in files:
        path = root / relative
        text = path.read_text(encoding="utf-8")
        visible = re.sub(r"```.*?```", "", text, flags=re.S)
        links = re.findall(r"\]\(([^\s)]+)(?:\s+\"[^\"]*\")?\)", visible)
        links += re.findall(r'<[^>]+(?:href|src)=[\"\']([^\"\']+)', visible)
        for link in links:
            url = urlsplit(html.unescape(link.strip("<>")))
            if url.scheme or url.netloc:
                if url.scheme not in ("https", "http", "mailto"):
                    raise ValueError(f"{relative}: unexpected link scheme: {link}")
                external += 1
                continue
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"{relative}: link escapes repository: {link}") from exc
            if not target.exists():
                raise ValueError(f"{relative}: missing link target: {link}")
            if url.fragment and target.suffix == ".md":
                if unquote(url.fragment) not in anchors(target.read_text(encoding="utf-8")):
                    raise ValueError(f"{relative}: missing fragment: {link}")
            checked += 1
    return {"local_links_checked": checked, "external_links_not_fetched": external}


def summarize(packet):
    return {"status": packet["status"], "intent": packet["intent"],
            "memory_count": len(packet["memories"]), "used_bytes": packet["used_bytes"],
            "budget_bytes": packet["budget_bytes"], "requires_review": packet["requires_review"],
            "expired_count": sum(m["status"] == "已过期" for m in packet["memories"])}


def demo_svg(cases):
    """Static display projection of executed results, not a terminal recording."""
    bg, panel_a, panel_b, line = '#000000', '#0b0b0b', '#080808', '#242424'
    ink, soft = '#f2f2f2', '#9a9a9a'
    chip = {'ready': '#ffffff', 'no_match': '#6f6f6f', 'budget_exhausted': '#ffffff'}
    labels = (('current', 'Current retrieval · 现行检索'),
              ('historical', 'Historical intent · 历史意图'),
              ('unknown', 'No match · 未命中'),
              ('budget', 'Tight budget · 预算过小'))
    rows = []
    for i, (key, label) in enumerate(labels):
        case = cases[key]
        y = 150 + i * 50
        color = chip.get(case['status'], soft)
        width = int(len(case['status']) * 7.3) + 26
        rows.append(f'<rect x="28" y="{y-24}" width="984" height="42" fill="{panel_a if i % 2 == 0 else panel_b}"/>')
        rows.append(f'<text x="42" y="{y+5}" fill="{ink}" font-size="15">{html.escape(label)}</text>')
        rows.append(f'<rect x="420" y="{y-13}" width="{width}" height="24" fill="{color}" opacity=".16"/>')
        rows.append(f'<text x="{420 + width // 2}" y="{y+4}" fill="{color}" font-size="13" font-family="ui-monospace,monospace" text-anchor="middle">{html.escape(case["status"])}</text>')
        values = ((620, str(case['memory_count'])), (740, str(case['expired_count'])),
                  (850, str(case['used_bytes']) + ' B'))
        for x, value in values:
            fill = ink
            rows.append(f'<text x="{x}" y="{y+5}" fill="{fill}" font-size="15" font-family="ui-monospace,monospace">{html.escape(value)}</text>')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1040 382" role="img" aria-labelledby="title desc">
<title id="title">ClaimLedger: executed recovery demo</title>
<desc id="desc">One synthetic question, four honest outcomes: current hit, historical intent, honest no-match, exhausted budget. A display projection of actual CLI output, not a model evaluation.</desc>
<rect width="1040" height="382" fill="{bg}"/>
<g font-family="Arial, Helvetica, sans-serif">
<text x="42" y="42" fill="{soft}" font-size="12" letter-spacing="2">CLAIMLEDGER / EXECUTED DEMO · 实跑演示</text>
<text x="42" y="78" fill="#ffffff" font-size="24" font-weight="600">One question, four honest outcomes.</text>
<g fill="{soft}" font-size="12" letter-spacing="1">
<text x="42" y="118">SCENARIO · 场景</text><text x="420" y="118">STATUS · 状态</text>
<text x="620" y="118">RECORDS · 记录</text><text x="740" y="118">EXPIRED · 过期</text><text x="850" y="118">SIZE · 字节</text>
</g>
{chr(10).join(rows)}
<text x="42" y="366" fill="{soft}" font-size="13">Handwritten synthetic cards · real CLI execution, not a model evaluation · 合成数据，CLI 实跑，非模型评测</text>
</g>
</svg>
'''


def verify_demo(root):
    texts = [(root / f).read_text(encoding="utf-8") for f in README_FILES]
    for name, language in (("quickstart", "bash"), ("sdk", "python"), ("expected", "json"), ("wiki", "bash")):
        if example(texts[0], name, language) != example(texts[1], name, language):
            raise ValueError("bilingual example drift: " + name)
    entry = shutil.which("chat-distiller")
    python = shutil.which("python")
    if not entry or not python or not shutil.which("bash"):
        raise ValueError("activate an installed chat-distiller environment with Python and Bash")
    with tempfile.TemporaryDirectory(prefix="readme-proof-") as tmp:
        env = dict(os.environ, TMPDIR=tmp, RECEIPT_DIR=tmp)
        env.pop("PYTHONPATH", None)
        # Run the literal Markdown shell block and Python block in the same shell.
        # Source checkout is cwd for the relative example fixture, not the SDK import.
        script = example(texts[0], "quickstart", "bash")
        script += '\n' + example((root / 'docs/ingestion.md').read_text(encoding='utf-8'), 'ingestion', 'bash') + '\n'
        script += "\n" + example(texts[0], "wiki", "bash") + "\n"
        script += '\nprintf "%s" "$DEMO_DIR" > "$RECEIPT_DIR/demo-path"\n'
        script += 'cd "$DEMO_DIR"\npython - <<\'README_PY\'\n'
        script += example(texts[0], "sdk", "python") + '\nREADME_PY\n'
        proc = subprocess.run(["bash", "-euo", "pipefail", "-c", script], cwd=root,
                              env=env, capture_output=True, text=True, timeout=90)
        if proc.returncode:
            raise AssertionError(proc.stdout + proc.stderr)
        base = _read_demo_path(tmp, "demo-path")
        # macOS mktemp -d ignores TMPDIR, so the demo directory may sit beside the
        # proof directory inside the system temp root; contain it there and clean up.
        try:
            base.relative_to(Path(tempfile.gettempdir()).resolve())
        except ValueError:
            # Last-resort Windows check: only the mktemp child created inside this
            # proof run may be cleaned up.
            if os.name != "nt" or not (base.parent.name == Path(tmp).name and base.name.startswith("tmp.")):
                raise
        try:
            knowledge = json.loads((base / "knowledge.json").read_text(encoding="utf-8"))
            if knowledge["schema_version"] != 2 or not knowledge["knowledge"]:
                raise AssertionError("wiki README example did not return knowledge")
            if not (base / "wiki-view/manifest.json").is_file():
                raise AssertionError("wiki README export is incomplete")
            # Verify that subprocesses use the installed distribution, not cwd or PYTHONPATH.
            imported = subprocess.check_output([python, "-c", "import chat_distiller; print(chat_distiller.__file__)"],
                                               cwd=base, env=env, text=True).strip()
            if root in Path(imported).resolve().parents:
                raise AssertionError("example imported source checkout instead of installed package")
            lint = json.loads((base / "lint.json").read_text(encoding="utf-8"))
            if not lint["ok"] or lint["structure_issues"] or lint["index_issues"]:
                raise AssertionError("ingestion example failed validation")
            packets = {"current": json.loads((base / "recovery.json").read_text(encoding="utf-8"))}

            def recover(query, *options):
                run = subprocess.run([entry, "recover", "--vault", str(base / "vault"), "--query", query,
                                      *options], cwd=base, env=env, capture_output=True, text=True, timeout=60)
                if run.returncode:
                    raise AssertionError(run.stdout + run.stderr)
                packet = json.loads(run.stdout)
                if len(run.stdout.encode("utf-8")) != packet["used_bytes"]:
                    raise AssertionError("wire byte count does not match")
                if packet["used_bytes"] > packet["budget_bytes"]:
                    raise AssertionError("wire exceeds budget")
                return packet
            packets["historical"] = recover("database", "--intent", "historical", "--max-bytes", "4096")
            packets["unknown"] = recover("quasarzzz", "--max-bytes", "4096")
            packets["budget"] = recover("database", "--max-bytes", "800")
            old = next(m for m in packets["historical"]["memories"] if m["status"] == "已过期")
            current_ids = {m["memory_id"] for m in packets["current"]["memories"] if m["is_current"]}
            if old["superseded_by"] not in current_ids:
                raise AssertionError("historical example lost its successor")
            actual = packets["current"]
            expected = json.loads(example(texts[0], "expected", "json"))
            if expected != {k: actual[k] for k in expected}:
                raise AssertionError("README output excerpt differs from executed result")
            if packets["unknown"]["status"] != "no_match" or packets["budget"]["status"] != "budget_exhausted":
                raise AssertionError("demo no longer demonstrates distinct recovery outcomes")
            return {"fixture_sha256": hashlib.sha256((root / "examples/recovery/distill.json").read_bytes()).hexdigest(),
                    "scope": "synthetic CLI display projection; no model or host compaction",
                    "cases": {k: summarize(v) for k, v in packets.items()}}
        finally:
            shutil.rmtree(base, ignore_errors=True)


def lifecycle_projection(root, run):
    """Project stable facts from raw CLI receipts, not from a claimed summary alone."""
    root, run = Path(root), Path(run)
    def read(name):
        return json.loads((run / name).read_text(encoding="utf-8"))
    report = read("summary.json")
    expected_steps = ["01-register", "02-render", "03-prepare", "04-validate", "05-publish",
                      "06-current", "07-history", "08-recovery", "09-export", "10-update-memory",
                      "11-stale", "12-fallback", "13-prepare-refresh", "14-refresh", "15-archive", "16-export"]
    if (report.get("ok") is not True or report.get("model_calls") != 0
            or report.get("commands_executed") != len(expected_steps)
            or report.get("receipts") != expected_steps
            or len(report.get("checks", {})) != 12
            or not all(value is True for value in report["checks"].values())):
        raise AssertionError("Wiki lifecycle summary changed or contains a failed check")
    for name in expected_steps:
        read(name + ".json")
    published, current = read("05-publish.json"), read("06-current.json")
    stale, fallback = read("11-stale.json"), read("12-fallback.json")
    refreshed, archive = read("14-refresh.json"), read("15-archive.json")
    if read("04-validate.json")["applied"] is not False:
        raise AssertionError("Wiki validation unexpectedly wrote state")
    page = current["results"][0]
    if (published["page_revision"] != 1 or published["applied"] is not True
            or published["requires_review"] is not True
            or page["freshness"] != "fresh"
            or {c["status"] for c in page["claims"]} != {"current", "disputed"}
            or not any("SQLite" in c["text"] for c in page["claims"] if c["status"] == "current")):
        raise AssertionError("Wiki publication no longer matches the illustrated fixture")
    if (stale["stale"] != 1 or fallback["knowledge"] != []
            or fallback["stale_pages_excluded"] != 1
            or not any("PostgreSQL" in m["body"] for m in fallback["memories"] if m["status"] == "现行")):
        raise AssertionError("Wiki fallback failed freshness or updated-memory checks")
    if (refreshed["applied"] is not True or refreshed["page_revision"] != 2
            or published["knowledge_id"] != refreshed["knowledge_id"]
            or archive["knowledge_id"] != published["knowledge_id"]
            or archive["revision"] != 1 or archive["archived"] is not True):
        raise AssertionError("Wiki refresh lost the identity or old revision")
    for name in ("08-recovery.json", "12-fallback.json"):
        packet = read(name)
        if len((run / name).read_bytes()) != packet["used_bytes"] or packet["used_bytes"] > packet["budget_bytes"]:
            raise AssertionError("Wiki demo packet violates its byte contract")
    for folder in ("wiki-v1", "wiki-v2"):
        manifest = read(folder + "/manifest.json")
        for filename, digest in manifest["files"].items():
            path = (run / folder / filename).resolve()
            path.relative_to((run / folder).resolve())
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise AssertionError("Wiki export digest mismatch: " + filename)
    return {
        "scope": "synthetic CLI lifecycle; prewritten synthesis; extractive refresh; no model evaluation",
        "inputs_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                          for name in ("examples/recovery/distill.json", "examples/wiki/synthesis.json")},
        "commands_executed": report["commands_executed"], "checks_passed": len(report["checks"]),
        "model_calls": report["model_calls"],
        "published": {"revision": published["page_revision"], "current_value": "SQLite", "dispute_retained": True},
        "source_changed": {"stale_pages": stale["stale"]},
        "fallback": {"current_value": "PostgreSQL", "stale_wiki_returned": len(fallback["knowledge"])},
        "refreshed": {"revision": refreshed["page_revision"], "identity_preserved": True,
                      "old_revision_retained": archive["archived"]},
    }


def verify_lifecycle(root):
    """Execute the literal README lifecycle block in an isolated temporary directory."""
    root = Path(root)
    texts = [(root / name).read_text(encoding="utf-8") for name in README_FILES]
    for name, language in (("lifecycle", "bash"), ("lifecycle-expected", "json")):
        if example(texts[0], name, language) != example(texts[1], name, language):
            raise ValueError("bilingual example drift: " + name)
    with tempfile.TemporaryDirectory(prefix="wiki-readme-proof-") as tmp:
        env = dict(os.environ, TMPDIR=tmp, RECEIPT_DIR=tmp)
        env.pop("PYTHONPATH", None)
        script = example(texts[0], "lifecycle", "bash")
        script += '\nprintf "%s" "$WIKI_DEMO_PARENT" > "$RECEIPT_DIR/lifecycle-path"\n'
        proc = subprocess.run(["bash", "-euo", "pipefail", "-c", script], cwd=root,
                              env=env, capture_output=True, text=True, timeout=90)
        if proc.returncode:
            raise AssertionError(proc.stdout + proc.stderr)
        parent = _read_demo_path(tmp, "lifecycle-path")
        run = parent / "run"
        # macOS mktemp -d ignores TMPDIR; contain and clean the demo parent explicitly.
        parent.relative_to(Path(tempfile.gettempdir()).resolve())
        try:
            report = json.loads((run / "summary.json").read_text(encoding="utf-8"))
            expected = json.loads(example(texts[0], "lifecycle-expected", "json"))
            if not expected or expected != {key: report[key] for key in expected}:
                raise AssertionError("README lifecycle excerpt differs from execution")
            return lifecycle_projection(root, run)
        finally:
            shutil.rmtree(parent, ignore_errors=True)


def lifecycle_svg(receipt, language="en"):
    """Bilingual, script-free presentation of the checked lifecycle receipt."""
    if language not in ("en", "zh-CN"):
        raise ValueError("unsupported lifecycle illustration language")
    if (receipt["refreshed"]["identity_preserved"] is not True
            or receipt["refreshed"]["old_revision_retained"] is not True
            or receipt["published"]["dispute_retained"] is not True):
        raise ValueError("receipt does not support lifecycle illustration")
    published, changed, fallback, refreshed = [receipt[k] for k in ("published", "source_changed", "fallback", "refreshed")]
    bg, line, ink, soft = '#000000', '#242424', '#ffffff', '#9a9a9a'
    green, amber, blue = '#ffffff', '#bdbdbd', '#ffffff'
    if language == "en":
        kicker = "CLAIMLEDGER / KNOWLEDGE LIFECYCLE"
        desc = "Executed synthetic lifecycle: publish, mark stale, fall back to updated memory, and recompile. No model evaluation."
        heading = "Knowledge changes. Keep the trail."
        rows = [("01 / PUBLISH", f'{published["current_value"]} · rev {published["revision"]}', "Citations + dispute", green, False),
                ("02 / SOURCE UPDATE", f'{changed["stale_pages"]} stale page', "Recheck before reuse", amber, True),
                ("03 / FALLBACK", fallback["current_value"], f'{fallback["stale_wiki_returned"]} stale Wiki pages served', blue, False),
                ("04 / RECOMPILE", f'rev {refreshed["revision"]} · same ID', "Old revision retained", green, False)]
        footer = f'{receipt["commands_executed"]} CLI steps · {receipt["checks_passed"]} checks · synthetic data · no model'
    else:
        kicker = "CLAIMLEDGER / 知识生命周期"
        desc = "实跑的合成生命周期：发布、标记失效、回退到最新记忆、重新编译。不是模型评测。"
        heading = "知识会变化，来路不丢失。"
        rows = [("01 / 发布知识", f'{published["current_value"]} · 版本 {published["revision"]}', "保留引用与未决争议", green, False),
                ("02 / 来源更新", f'{changed["stale_pages"]} 个旧页失效', "复核之前不默认复用", amber, True),
                ("03 / 原子回退", fallback["current_value"], f'返回 {fallback["stale_wiki_returned"]} 个过时 Wiki 页', blue, False),
                ("04 / 重新编译", f'版本 {refreshed["revision"]} · 身份不变', "旧版本仍可检查", green, False)]
        footer = f'{receipt["commands_executed"]} 步 CLI · {receipt["checks_passed"]} 项检查 · 合成数据 · 无模型调用'
    parts = [f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 440" role="img" aria-labelledby="title desc" lang="{language}">
<title id="title">{html.escape(heading)}</title>
<desc id="desc">{html.escape(desc)}</desc>
<rect width="680" height="440" fill="{bg}"/>
<g font-family="system-ui, -apple-system, 'Noto Sans CJK SC', sans-serif">
<text x="28" y="38" fill="{soft}" font-size="12" letter-spacing="1.5">{html.escape(kicker)}</text>
<text x="28" y="76" fill="#ffffff" font-size="25" font-weight="600">{html.escape(heading)}</text>
<line x1="46" y1="106" x2="46" y2="368" stroke="{line}" stroke-width="2"/>''']
    for index, (label, value, note, color, struck) in enumerate(rows):
        y = 128 + index * 74
        strike = ''
        if struck:
            strike = f'<line x1="66" y1="{y-4}" x2="{66 + int(len(value) * 12.5)}" y2="{y+6}" stroke="{soft}" stroke-width="2" opacity=".7"/>'
        parts += [f'<circle cx="46" cy="{y}" r="8" fill="{color}"/>',
                  f'<text x="68" y="{y-18}" fill="{color}" font-size="12" font-weight="700" letter-spacing="1.4">{html.escape(label)}</text>',
                  f'<text x="68" y="{y+8}" fill="#ffffff" font-size="24" font-weight="600">{html.escape(value)}</text>',
                  strike,
                  f'<text x="644" y="{y+6}" fill="{soft}" font-size="15" text-anchor="end">{html.escape(note)}</text>']
    parts += [f'<text x="28" y="416" fill="{soft}" font-size="15">{html.escape(footer)}</text>', '</g>\n</svg>\n']
    return "\n".join(parts)


def check_evidence_tables(root):
    """Keep both README metric tables synchronized with the inspectable reports."""
    root = Path(root)
    bench = json.loads((root / "benchmarks/wiki/results.json").read_text(encoding="utf-8"))
    summary = bench["summary"]
    rows = [(summary["invalid_proposals_blocked"], summary["invalid_proposals_total"]),
            (summary["exact_budget_passes"], summary["exact_budget_total"]),
            (summary["stale_served_gate_disabled"], summary["topics"]),
            (summary["stale_served_gate_enabled"], summary["topics"]),
            (sum(c["identity_preserved_after_refresh"] and c["old_revision_inspectable"] for c in bench["cases"]), summary["topics"])]
    retrieval = json.loads((root / "benchmarks/benchmark-results.json").read_text(encoding="utf-8"))
    expected_retrieval = []
    for method in ("Baseline", "Structured Memory", "Status-aware Memory"):
        values = retrieval["results"][method]["metrics"]
        expected_retrieval.append([f'{values[k]:.4f}' for k in ("Recall@1", "Recall@5", "MRR", "stale-hit@5")])
    for name in README_FILES:
        text = (root / name).read_text(encoding="utf-8")
        observed = [(int(a), int(b)) for a, b in re.findall(r'^\|[^\n]*\|\s*(\d+) / (\d+)\s*\|$', text, re.M)]
        if observed != rows:
            raise AssertionError(name + ": Wiki metric table differs from committed report")
        observed_retrieval = []
        for line in text.splitlines():
            if line.startswith("|") and len(re.findall(r'\d+\.\d{4}', line)) == 4:
                observed_retrieval.append(re.findall(r'\d+\.\d{4}', line))
        if observed_retrieval != expected_retrieval:
            raise AssertionError(name + ": retrieval metric table differs from committed report")
    return {"metric_tables_checked": 4}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write-demo", action="store_true", help="regenerate fixture-derived JSON/SVG after execution")
    args = ap.parse_args()
    files = ["README.md", "README.zh-CN.md", "CONTRIBUTING.md", "CHANGELOG.md"]
    files += [str(p.relative_to(ROOT)) for folder in ("docs", "references") for p in sorted((ROOT / folder).glob("*.md"))]
    demo = verify_demo(ROOT)
    lifecycle = verify_lifecycle(ROOT)
    metrics = check_evidence_tables(ROOT)
    outputs = {"examples/recovery/expected.json": json.dumps(demo, ensure_ascii=False, indent=2) + "\n",
               "assets/recovery-demo.svg": demo_svg(demo["cases"]),
               "examples/wiki/lifecycle.expected.json": json.dumps(lifecycle, ensure_ascii=False, indent=2) + "\n",
               "assets/wiki-lifecycle.svg": lifecycle_svg(lifecycle),
               "assets/wiki-lifecycle.zh-CN.svg": lifecycle_svg(lifecycle, "zh-CN")}
    for name, content in outputs.items():
        path = ROOT / name
        if args.write_demo:
            path.write_text(content, encoding="utf-8")
        elif path.read_text(encoding="utf-8") != content:
            raise AssertionError("stale demo artifact: " + name)
    report = dict(ok=True, **check_links(ROOT, files), **metrics, readme_languages=2,
                  executed_examples=["quickstart", "ingestion", "wiki", "sdk", "lifecycle"], recovery_scenarios=len(demo["cases"]),
                  wiki_lifecycle_commands=lifecycle["commands_executed"], wiki_lifecycle_checks=lifecycle["checks_passed"],
                  generated_assets_match=True, data=demo["scope"])
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
