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

## Cosmic presentation refinement

The 2026-11-10 visual revision uses midnight blue, diffuse blue/violet gradients, small luminous graph nodes, fine connections and quiet translucent surfaces. The decorative starfield is deterministic SVG, capped at 180 small points, not records or evidence. It is hidden from assistive technology and never accepts pointer input. No image download, external font, additional library, or perpetual animation is required.

Overview labels now prioritize subjects. Method names appear on hover/focus, through topic/search filters, when zoomed in, or with the name-display control. Full text remains available in the existing list and reader. Existing graph objects, versions and evidence are unchanged.

Wheel bursts accumulate toward one cancellable 260ms camera transition. Fit and zoom buttons use the same transition; pointer drag and pinch take immediate control. Reduced-motion preference disables camera interpolation. The transition also stops when the document becomes hidden. Decorative gradients remain static; the existing optional graph physics settles rather than running continuously.

These are presentation and interaction refinements, not new retrieval-quality or user-effectiveness measurements.


## Second-brain reading and return paths (2026-11-10)

Inspected the actual public pages and screenshots, not only search snippets:

- [Quartz](https://github.com/jackyzha0/quartz) is MIT-licensed. Its [popover previews](https://quartz.jzhao.xyz/features/popover-previews) and [local graph / visited nodes](https://quartz.jzhao.xyz/features/graph-view) informed a preview-before-opening pattern and visible return paths.
- [Simon Späti's public Second Brain](https://www.ssp.sh/brain/) and [source repository](https://github.com/sspaeti/second-brain-public), reached from the author's [Reddit showcase](https://www.reddit.com/r/ObsidianMD/comments/1vthjv0/public_second_brain_showcase_currated_with/), use explicit search, linked reading and topic maps as starting points. This is a customized Quartz v3/Hugo site, distinct from current Quartz documentation. The showcase is design inspiration, not evidence of improved user outcomes.
- [Capacities backlinks](https://docs.capacities.io/reference/backlinks) show a reference in its original context. Capacities is a commercial product reference here, not an open-source dependency.

Applied patterns are original HTML/CSS/JS; no reference code, imagery, fonts or analytics were copied. Dependency count is unchanged. Full-screen cosmic graph remains the primary surface.

The graph preview now shows the actual stored situation, goal, method version and direct linked report count. It makes no additional request. Reading routes lead from context to procedure and recorded connections. Connections are grouped by actual neighbor types; relation labels and method-purpose snippets remain visible. No links or relevance scores are inferred from screen proximity.

Bookmarks and recent-opened records use browser-local storage key `openakashic-atlas-reading-v1`, containing only exact node IDs (100 saved / 24 recent). They are private to that browser profile and are not account storage, encrypted storage or server contributions. Missing IDs remain retained and clearly unavailable in the current loaded graph; they are never silently redirected to a different version. Either list can be cleared separately. Unavailable storage falls back to the current page session; invalid persisted input is bounded and ignored. Browser Back and shared URLs remain separate from this local shelf.

Functional verification covers pointer/keyboard previews, exact-ID persistence, grouping against real edges, storage failure/malformed data, no write requests, responsive surfaces, keyboard navigation and existing camera/graph behavior. These checks do not prove human task-success improvements or token savings.
