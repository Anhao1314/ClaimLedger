# ClaimLedger / 续迹: visual and naming system

**The continuity skill for AI agents.**

Your work continues. Keep the decisions. Bring the evidence.

ClaimLedger is a local-first, Skill-first developer tool. The public name is **ClaimLedger**, the machine-readable Skill and preferred CLI are **claim**. Avoid names that imply universal history access, automatic truth verification or measured task success.

## Visual direction

One hue carries the whole identity: **black paper, white ink, gray history**. The ledger is drawn, not colored — the current claim is a solid white line, the superseded claim is a struck gray line, the disputed claim is a dashed line. A 1-bit checker dither gives depth without a second color. Hard edges everywhere, one monospace type family, no gradients and no rounded panels.

Status is the only semantic the palette needs to express, so the palette is the smallest one that can express it:

| Token | Value | Use |
| --- | --- | --- |
| Surface | `#000000` | Page and panel background |
| Panel | `#0a0a0a` / `#0d0d0d` | Raised cards, terminals, chips |
| Line | `#242424` | Borders and structure |
| Ink | `#ffffff` | Headlines, current state, primary actions |
| Secondary ink | `#9a9a9a` | Labels, captions, superseded text |
| Struck | `#6f6f6f` | Superseded bars and stale metrics |

Screenshots of the real product are unretouched pixels shown in grayscale: the color in them belongs to the product, not to this page. The headline is always static text. The optional decorative bars draw in once over 1.1 seconds and stop. Independent static SVGs are the default fallback; README `<picture>` opts into motion only for `prefers-reduced-motion: no-preference`. Artwork is illustrative, not an experiment replay.

```bash
python tools/build_brand_assets.py --check
```

## Lineage of the visual system

This is the second visual system the repository has had. The first — cream and deep-blue surfaces, a lime trace, a cyan evidence point — was retired in October 2026; its bytes stay inspectable in git history, which is where superseded things belong. The current system is a deliberate study of [Moonshot AI's careers site](https://careers.kimi.com/): one hue, one type family, dithering instead of gradients, restraint instead of ornament. No affiliation.

## Migration boundary

Update current branding, navigation and repository links. Preserve historical evidence and old public interfaces where compatibility matters. The small “formerly chat-distiller” label belongs on the overview and migration guide, not on every heading. See [migration contracts](brand-migration.md).

## Primary references consulted

- [Agent Skills specification](https://agentskills.io/specification): name/parent-directory alignment and progressive disclosure.
- [PyPA entry points](https://packaging.python.org/en/latest/specifications/entry-points/): independent console command names over the same distribution.
- [GitHub repository renaming](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository): redirects and explicit remote updates.
