"""Regenerate the README evidence figures from committed experiment JSONs.

Every figure is a projection of committed results — this script makes that
claim executable:

    python scripts/render_figures.py --check   # diff regenerated vs committed
    python scripts/render_figures.py --write   # rewrite docs/img/*.svg

Sources:
    margin-ablation.svg   <- experiments/relation_002/results.json (margin_ablation_jev)
    relation002-tiers.svg <- experiments/relation_002/results.json (per_tier)
    e2e002-arms.svg       <- experiments/e2e_002/results/score.json  (strata)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "docs" / "img"

FONT = ("ui-monospace,Menlo,monospace")
GRAY = "#8a8a8a"
DARK = "#111111"
MID = "#5a5a5a"
LIGHT = "#9a9a9a"
FAINT = "#c9c9c9"
GRID = "#d9d9d9"


def _text(x, y, label, *, fill=DARK, anchor="middle", size=11):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" '
            f'font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
            f'font-weight="normal">{label}</text>')


def _gridlines(y0: float, step: float, x0: float, x1: float) -> str:
    out = []
    for i, pct in enumerate((0, 25, 50, 75, 100)):
        y = y0 - i * step
        out.append(f'<line x1="{x0:g}" y1="{y:.1f}" x2="{x1:g}" y2="{y:.1f}" '
                   f'stroke="{GRID}" stroke-width="1"/>')
        out.append(_text(x0 - 8, y + 4, f"{pct}%", fill=GRAY, anchor="end"))
    return "".join(out)


def render_margin(results: dict) -> str:
    sweep = sorted(results["margin_ablation_jev"].items(),
                   key=lambda kv: float(kv[0]))
    deltas = [k for k, _ in sweep]
    precision = [v["precision"] for _, v in sweep]
    recall = [v["recall"] for _, v in sweep]
    y0, y1 = 276.0, 40.0          # 0% .. 100%
    x0, x1 = 56.0, 736.0
    n = len(deltas)
    step_x = (x1 - x0) / (n - 1)
    xs = [x0 + i * step_x for i in range(n)]

    def y(v):
        return y0 - v * (y0 - y1)

    default_i = deltas.index("0.2")
    dx = xs[default_i]

    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="760" height="340" '
           'viewBox="0 0 760 340" role="img"><rect width="760" height="340" '
           'fill="white"/>']
    out.append(_gridlines(y0, (y0 - y1) / 4, x0, x1))
    for i, d in enumerate(deltas):
        out.append(_text(xs[i], 296, f"δ={d}", fill=DARK))
    out.append(f'<line x1="{dx!r}" y1="40" x2="{dx!r}" y2="276" '
               f'stroke="{GRAY}" stroke-width="1" stroke-dasharray="4 3"/>')
    out.append(_text(dx, 34.0, "policy default δ=0.2", fill=GRAY))
    pts_r = " ".join(f"{x:.1f},{y(v):.1f}" for x, v in zip(xs, recall))
    pts_p = " ".join(f"{x:.1f},{y(v):.1f}" for x, v in zip(xs, precision))
    out.append(f'<polyline points="{pts_r}" fill="none" stroke="{DARK}" '
               f'stroke-width="2"/>')
    out.append(f'<polyline points="{pts_p}" fill="none" stroke="{GRAY}" '
               f'stroke-width="2"/>')
    for x, v in zip(xs, recall):
        out.append(f'<circle cx="{x:.1f}" cy="{y(v):.1f}" r="3.5" '
                   f'fill="{DARK}"/>')
    out.append(_text(x1, 32.0, "precision", fill=GRAY, anchor="end"))
    out.append(_text(xs[0] + 4.0, y(recall[0]) - 10.0, "recall", anchor="start"))
    out.append(_text(x0, 310.0, "margin ablation: confirmed-conflict "
                     "precision/recall vs δ (Jev probability maps, 60 pairs)",
                     fill=GRAY, anchor="start"))
    return "".join(out) + "</svg>"


TIERS = (("E", "clean"), ("HN", "looks-conflict, isn't"),
         ("HP", "looks-compatible, conflicts"), ("S", "one-word flips"))


def render_tiers(results: dict) -> str:
    per_tier = results["per_tier"]
    series = (("lexical baseline", LIGHT, "lexical"),
              ("Jev (judgment layer)", DARK, "jev"),
              ("deepseek-flash", MID, "deepseek"))
    y0, y1 = 284.0, 46.0
    x0, x1 = 56.0, 744.0
    centers = [x0 + (i + 0.5) * (x1 - x0) / len(TIERS) for i in range(len(TIERS))]
    bar_w, gap = 31.0, 12.0
    step = bar_w + gap
    offsets = [(i - len(series) / 2) * step for i in range(len(series))]

    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="760" height="360" '
           'viewBox="0 0 760 360" role="img"><rect width="760" height="360" '
           'fill="white"/>']
    out.append(_gridlines(y0, (y0 - y1) / 4, x0, x1))
    for gi, (tier, label) in enumerate(TIERS):
        c = centers[gi]
        out.append(_text(c, 318, label, fill=DARK))
        out.append(_text(c, 334, f"tier {tier}", fill=GRAY))
        for (name, color, key), off in zip(series, offsets):
            v = per_tier[key][tier]
            h = v * (y0 - y1)
            out.append(f'<rect x="{c + off:.1f}" y="{y0 - h:.1f}" '
                       f'width="{bar_w:.1f}" height="{h:.1f}" fill="{color}"/>')
            out.append(_text(c + off + bar_w / 2, y0 - h - 6.0,
                             f"{v * 100:g}", fill=DARK))
    out.append(f'<line x1="{x0:g}" y1="{y0:g}" x2="{x1:g}" y2="{y0:g}" '
               f'stroke="{DARK}" stroke-width="1.5"/>')
    for lx, (name, color, _) in zip((56.0, 179.6, 329.6), series):
        out.append(f'<rect x="{lx:g}" y="14" width="11" height="11" '
                   f'fill="{color}"/>')
        out.append(_text(lx + 16, 24.0, name, fill=DARK, anchor="start"))
    return "".join(out) + "</svg>"


STRATA = (("constraint", "constraint", "must follow"),
          ("conflict_explicit", "explicit conflict", "designed pairs"),
          ("conflict_natural", "natural conflict", "corpus pairs"),
          ("irrelevant", "irrelevant", "distractor memory"),
          ("control", "control", "no memory needed"))


def render_e2e002(score: dict) -> str:
    strata = score["strata"]
    arms = (("A · no memory", LIGHT, "A"),
            ("B · all records", MID, "B"),
            ("C · judged brief", DARK, "C"),
            ("D · irrelevant (matched)", FAINT, "D"))
    y0, y1 = 284.0, 46.0
    x0, x1 = 56.0, 744.0
    centers = [x0 + (i + 0.5) * (x1 - x0) / len(STRATA) for i in range(len(STRATA))]
    bar_w, gap = 26.0, 8.0
    step = bar_w + gap
    offsets = [(i - len(arms) / 2) * step for i in range(len(arms))]

    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="760" height="360" '
           'viewBox="0 0 760 360" role="img"><rect width="760" height="360" '
           'fill="white"/>']
    out.append(_gridlines(y0, (y0 - y1) / 4, x0, x1))
    for gi, (key, label, sub) in enumerate(STRATA):
        c = centers[gi]
        out.append(_text(c, 318, label, fill=DARK))
        out.append(_text(c, 334, sub, fill=GRAY))
        for (name, color, arm), off in zip(arms, offsets):
            v = strata[key][arm]["passes"] / strata[key][arm]["n"]
            h = v * (y0 - y1)
            out.append(f'<rect x="{c + off:.1f}" y="{y0 - h:.1f}" '
                       f'width="{bar_w:.1f}" height="{h:.1f}" fill="{color}"/>')
            out.append(_text(c + off + bar_w / 2, y0 - h - 6.0,
                             f"{v * 100:g}", fill=DARK))
    out.append(f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y0}" '
               f'stroke="{DARK}" stroke-width="1.5"/>')
    lx = x0
    for name, color, _ in arms:
        out.append(f'<rect x="{lx:g}" y="14" width="11" height="11" '
                   f'fill="{color}"/>')
        out.append(_text(lx + 16, 24.0, name, fill=DARK, anchor="start"))
        lx += 16 + len(name) * 6.7 + 8
    out.append(_text(x0, 310.0, "e2e_002 v8: task success by stratum × arm — "
                     "40 tasks × 3 runs (A and D are the controls)",
                     fill=GRAY, anchor="start"))
    return "".join(out) + "</svg>"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="verify regenerated figures are byte-identical")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if not args.check and not args.write:
        parser.error("one of --check/--write is required")

    relation = json.loads(
        (ROOT / "experiments/relation_002/results.json").read_text())
    e2e = json.loads(
        (ROOT / "experiments/e2e_002/results/score.json").read_text())
    figures = {
        "margin-ablation.svg": render_margin(relation),
        "relation002-tiers.svg": render_tiers(relation),
        "e2e002-arms.svg": render_e2e002(e2e),
    }

    ok = True
    for name, content in figures.items():
        path = IMG / name
        if args.check:
            if not path.exists():
                print(f"MISSING {name}")
                ok = False
                continue
            committed = path.read_text(encoding="utf-8")
            same = committed == content
            print(f"{'IDENTICAL' if same else 'DIFFERS'}: {name}")
            if not same:
                ok = False
        if args.write:
            path.write_text(content, encoding="utf-8")
            print(f"wrote {path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
