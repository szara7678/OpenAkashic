# Atlas UI design references

The atlas remains a full-viewport, read-only graph of methods and their recorded situation, goal, outcomes and revisions. It is not a landing-page redesign.

## Open-source guide actually used

[UI UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill), MIT, pinned at [`b7d5353e0130feb8c5574ef1251f8a1db1873ccb`](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/tree/b7d5353e0130feb8c5574ef1251f8a1db1873ccb), was run locally as a design-reference tool. Its `SKILL.md`, `references/quick-reference.md`, and graph/UX search results informed this revision. No upstream runtime, analytics script, external font, or global skill installation is required by the site.

Reproducible reference queries from that repository:

```sh
python3 .claude/skills/ui-ux-pro-max/scripts/search.py 'knowledge discovery workspace' --design-system --density 7 --variance 3 -p OpenAkashic
python3 .claude/skills/ui-ux-pro-max/scripts/search.py 'network relationships exploration' --domain chart -n 2
python3 .claude/skills/ui-ux-pro-max/scripts/search.py 'progressive disclosure touch keyboard' --domain ux -n 5
```

The first query suggested a generic landing-page hero and orange palette. Those suggestions were rejected because this product is an exploratory workspace. The specific graph/UX guidance was more applicable.

## Applied decisions

- Keep the canvas dominant. Collapse discovery when following a topic, and start mobile with compact discovery. Do not silently remove methods from the archive.
- Use semantic dark/light colors, restrained surfaces, consistent outline icons, legible body text, and generous primary controls. Show selected, focused and disabled states.
- Search offers real matching methods, their subject and situation, with keyboard selection and an explicit route to all results. It does not generate an answer or promise suitability.
- Separate overview, execution steps and recorded connections. Conditions, success criteria and limitations stay with the procedure; evidence remains attributed.
- On small screens, prioritize category labels in the overview. Reveal more detail through zoom, topic selection or search. Collision and panel-boundary checks reduce clipping; labels remain available through focus/details/list navigation.
- Preserve wheel/pinch zoom, drag, zoom/fit buttons, keyboard movement, browser back, deep links, reduced-motion preference and a read-only list alternative.
- Keep dependencies unchanged. The existing SVG renderer is suitable for this bounded overview. Larger corpora will require measured rendering/level-of-detail work; this change does not claim unbounded graph performance.

## Validation boundary

Browser interaction checks, visual inspections and public asset readback are release checks. They do not establish improved task completion, accessibility certification, graph retrieval quality, business value or model-token savings. Mobile viewport emulation does not replace physical-device testing. Original evaluation evidence is unchanged.
