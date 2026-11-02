#!/usr/bin/env python3
"""Render the evidence charts (SVG) from the real experiment result files.

Every number in the charts is read from committed result JSON — the renderer
contains no hardcoded accuracy values. Deterministic output: same results in,
same SVG out.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "img"
REL2 = ROOT / "experiments" / "relation_002" / "results.json"

INK = "#111111"
MUTED = "#8a8a8a"
GRID = "#d9d9d9"
PALETTE = {"lexical": "#9a9a9a", "jev": "#111111", "deepseek": "#5a5a5a"}
NAMES = {"lexical": "lexical baseline", "jev": "Jev (judgment layer)",
         "deepseek": "deepseek-flash"}
TIERS = (("E", "clean"), ("HN", "looks-conflict, isn't"),
         ("HP", "looks-compatible, conflicts"), ("S", "one-word flips"))


def _text(x, y, s, size=12, fill=INK, anchor="middle", weight="normal"):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="ui-monospace,Menlo,monospace" '
            f'font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
            f'font-weight="{weight}">{s}</text>')


def _bars_chart(tiers: list, methods: list, values: dict) -> str:
    W, H = 760, 360
    left, top, right, bottom = 56, 46, 16, 76
    plot_w, plot_h = W - left - right, H - top - bottom
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
             f'viewBox="0 0 {W} {H}" role="img">']
    parts.append(f'<rect width="{W}" height="{H}" fill="white"/>')
    for pct in (0, 25, 50, 75, 100):
        y = top + plot_h * (1 - pct / 100)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{W - right}" y2="{y:.1f}" '
                     f'stroke="{GRID}" stroke-width="1"/>')
        parts.append(_text(left - 8, y + 4, f"{pct}%", 11, MUTED, anchor="end"))
    group_w = plot_w / len(tiers)
    bar_w = group_w / (len(methods) + 1)
    for gi, (tier, label) in enumerate(tiers):
        gx = left + gi * group_w
        parts.append(_text(gx + group_w / 2, H - bottom + 34, label, 11, INK))
        parts.append(_text(gx + group_w / 2, H - bottom + 50, f"tier {tier}", 11,
                           MUTED))
        for mi, method in enumerate(methods):
            v = values[method][tier]
            if v is None:
                continue
            h = plot_h * (v / 100.0)
            x = gx + bar_w * (mi + 0.5)
            y = top + plot_h - h
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w * 0.72:.1f}" '
                         f'height="{h:.1f}" fill="{PALETTE[method]}"/>')
            parts.append(_text(x + bar_w * 0.36, y - 6, f"{v:.2f}".rstrip("0")
                               .rstrip(".") if isinstance(v, float) else str(v),
                               11, INK))
    parts.append(f'<line x1="{left}" y1="{top + plot_h}" x2="{W - right}" '
                 f'y2="{top + plot_h}" stroke="{INK}" stroke-width="1.5"/>')
    lx = left
    for method in methods:
        parts.append(f'<rect x="{lx}" y="14" width="11" height="11" '
                     f'fill="{PALETTE[method]}"/>')
        parts.append(_text(lx + 16, 24, NAMES[method], 11, INK, anchor="start"))
        lx += 18 + len(NAMES[method]) * 6.6
    parts.append("</svg>")
    return "".join(parts)


def _ablation_chart(ablation: dict) -> str:
    W, H = 760, 340
    left, top, right, bottom = 56, 40, 24, 64
    plot_w, plot_h = W - left - right, H - top - bottom
    deltas = sorted(ablation, key=float)
    xs = {d: left + plot_w * i / (len(deltas) - 1) for i, d in enumerate(deltas)}

    def y(v):
        return top + plot_h * (1 - v)

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
             f'viewBox="0 0 {W} {H}" role="img">']
    parts.append(f'<rect width="{W}" height="{H}" fill="white"/>')
    for pct in (0, 25, 50, 75, 100):
        yy = top + plot_h * (1 - pct / 100)
        parts.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{W - right}" y2="{yy:.1f}" '
                     f'stroke="{GRID}" stroke-width="1"/>')
        parts.append(_text(left - 8, yy + 4, f"{pct}%", 11, MUTED, anchor="end"))
    for d in deltas:
        parts.append(_text(xs[d], top + plot_h + 20, f"δ={d}", 11, INK))

    default_x = xs["0.2"]
    parts.append(f'<line x1="{default_x}" y1="{top}" x2="{default_x}" '
                 f'y2="{top + plot_h}" stroke="{MUTED}" stroke-width="1" '
                 f'stroke-dasharray="4 3"/>')
    parts.append(_text(default_x, top - 6, "policy default δ=0.2", 11, MUTED))

    def series(kind, color):
        pts = []
        for d in deltas:
            v = ablation[d].get(kind)
            if v is None:
                continue
            pts.append(f'{xs[d]:.1f},{y(v):.1f}')
        return (f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" '
                f'stroke-width="2"/>')

    parts.append(series("recall", INK))
    parts.append(series("precision", MUTED))
    for d in deltas:
        parts.append(f'<circle cx="{xs[d]:.1f}" cy="{y(ablation[d]["recall"]):.1f}" '
                     f'r="3.5" fill="{INK}"/>')
    parts.append(_text(W - right, y(1.0) - 8, "precision", 11, MUTED, anchor="end"))
    parts.append(_text(left + 4, y(0.8846) - 10, "recall", 11, INK, anchor="start"))
    parts.append(_text(left, H - bottom + 34,
                       "margin ablation: confirmed-conflict precision/recall vs δ "
                       "(Jev probability maps, 60 pairs)", 11, MUTED, anchor="start"))
    parts.append("</svg>")
    return "".join(parts)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rel2 = json.loads(REL2.read_text(encoding="utf-8"))
    tiers = [t for t, _ in TIERS]
    values = {m: {t: rel2["per_tier"][m][t] for t in tiers}
              for m in ("lexical", "jev", "deepseek")}
    per_tier_pct = {m: {t: (v * 100 if v is not None else 0) for t, v in d.items()}
                    for m, d in values.items()}
    chart1 = _bars_chart([(t, label) for t, label in TIERS],
                         ("lexical", "jev", "deepseek"), per_tier_pct)
    (OUT / "relation002-tiers.svg").write_text(chart1, encoding="utf-8")
    chart2 = _ablation_chart(rel2["margin_ablation_jev"])
    (OUT / "margin-ablation.svg").write_text(chart2, encoding="utf-8")
    print(f"rendered: {OUT / 'relation002-tiers.svg'}, {OUT / 'margin-ablation.svg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())