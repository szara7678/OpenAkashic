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


## Selection dismissal and current archive review (2026-11-14)

Closing a record now dismisses its selection, rather than only hiding its reader. X and Escape invalidate pending detail requests, clear local depth, selected/dim/neighbor states, tooltip, trail and selected URL parameters, then fit the overview and focus the map. Explicit text/topic filters and browser-local saved records remain. Browser Back can restore the prior selection. Hide-only reader behavior remains internal when opening another surface.

The graph search previously matched only literal substrings, although the existing hybrid situation/goal endpoint was available. A deliberate button or Enter after no literal matches now requests hybrid search; typing alone does not call embeddings. Exact returned method ID/version pairs are checked against loaded graph nodes. Results follow API order and still respect explicit topic/report filters. Stale responses after editing, dismissing or navigating are ignored. A source-sharing section traverses two actual documented_by edges and labels that relationship explicitly; it does not add asserted prerequisite, alternative or outcome relationships.

Read-only archive inspection found 61 methods, 270 nodes and 284 relationships, with no duplicate IDs, dangling endpoints, orphan nodes or report/opinion version mismatches. All methods contain situation, goal, conditions, steps, criteria and limitations. However, only 9 methods have 10 reported outcomes; these are synthetic/model reports (9 partial, 1 success), not independent field trials. There are no failure/correction/version-change paths yet. All 61 situations and 61 goals are unique. Removing editorial topic nodes leaves 44 components, 34 containing one method. Twelve source nodes are shared across methods. Nineteen methods are classified as Other. These facts limit claims about a rich reusable experience graph.

Source completeness also needs work: 58 documented methods contain 72 citations across 55 unique URLs, but 66 citations have no quote. Of six nonempty quotes checked against source text, one is exact raw text, four match after Markdown formatting is removed, and one is a paraphrase. One legacy opinion contains irrecoverable literal question-mark corruption already present in its original publication receipt. Original records were preserved; they were not silently repaired or counted as validated evidence.

A small corpus-aware diagnostic froze expected IDs and required fields before querying: 9 in-corpus paraphrased situations/goals and 1 out-of-scope question. Literal search returned none of the 9 expected methods; semantic and hybrid search each ranked all 9 first, and the out-of-scope question returned no results. Repeating the same fixed questions through a single combined input also ranked 9/9 first. The question author had seen the corpus, so this is a regression diagnostic, not independent general accuracy or agent task success. The semantic endpoint reported all 61 methods indexed with no stale/missing entries. Exact immutable ID/version and method fields matched for 9/9. At packing budget 1024, only 6/9 target methods were complete in bundle output; at 4096, all 9 were complete. Omitted feedback remains explicitly omitted.

Historical evaluation receipts were rechecked separately. A prior 18-run Sol experiment on 9 technical questions and an 18-source pool achieved strict 9/9 in both direct and source-prefetch conditions, with provider-reported tokens 394,907 versus 117,358 (70.28% fewer) and mean online times 30.57s versus 19.61s. This measures that source-prefetch experiment; it does not isolate the current graph UI or establish human productivity, transfer to unrelated work, or currency savings. Earlier failures remain part of the archive. Browser checks and retrieval diagnostics cannot substitute for a controlled graph-versus-baseline task evaluation or real usage reports.
