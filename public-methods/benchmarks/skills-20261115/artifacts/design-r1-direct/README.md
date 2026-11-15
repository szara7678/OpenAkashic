# Cedar offline help-desk directory

Open `index.html` directly in a browser; no server, network, credentials, fonts or dependencies are required. All seven source locations are embedded, with a fixed 18 July 2026 snapshot notice. Non-default filters intersect and exclude closed locations. Reset restores the complete directory.

## Sources consulted and methods applied
- Service data: `/task/input/centers.json`, snapshot `2026-07-18`; all seven records used without changing availability, hours or access information.
- Skill consulted: `/skills/frontend-design/SKILL.md`, metadata commit `1780c5e5a552fd4d1c9d6a7b0cab26b0c2bef064`, entrypoint SHA-256 reported by discovery `d91970639e9f5c37682ac7ab60094d35f1c7c1f38d731bd56396563aee10c1d3`. No other skill body consulted. Brand-guidelines metadata appeared in discovery but its identity guidance was not applied.
- Applied: brief-first design plan, restrained typography, short line lengths, semantic hierarchy, mobile layout, visible focus, actionable empty state, and screenshot critique. Plan: ink `#203b3a`, paper `#f5f2e9`, leaf `#46745a`, amber `#b77a21`, near-white `#fffefa`; local system sans-serif with a serif C identifier; left-aligned header → snapshot → controls → two-column directory (one column on phones). Review against the brief removed any promotional hero or imagery to prioritize finding support.

## Commands and results
Commands executed from `/work` (inspection commands include absolute paths):
```sh
python /runtime/research.py skills search '{"query":"offline website accessible responsive public service directory design","limit":3}'
cat /skills/frontend-design/SKILL.md
cat /task/input/centers.json
ls -la /work
which chromium chromium-browser node
node -e "for(const m of ['playwright','puppeteer']){try{console.log(m,require.resolve(m))}catch{}}"
sed -n '45,100p' /skills/frontend-design/SKILL.md
python - <<'PY'
import importlib.util
for name in ['playwright','websocket','websockets']:
 print(name, bool(importlib.util.find_spec(name)))
PY
ls /usr/lib/node_modules /opt/node_modules 2>/dev/null
python /work/build.py
```
Discovery returned frontend-design and brand-guidelines metadata. The first combined skill read was display-truncated; the remaining design process was read progressively with `sed`. Chromium and Node are installed; Playwright, Puppeteer and Python WebSocket libraries are not. The optional `/opt/node_modules` lookup was absent (exit 1); no dependency was installed. `build.py` generated the self-contained HTML successfully. Shell heredocs created the build script and documentation.

## Validation and limitations
Validation commands and actual outcomes are recorded below after execution and in `QA.md`. The directory is a fixed snapshot, not a claim of current availability. No addresses, contact details or live services are supplied, so none are invented. Keyboard and browser automation do not substitute for assistive-technology user testing.

### Completed validation
Additional exact commands executed:
```sh
node -p "process.version + ' WebSocket=' + typeof WebSocket"
node /work/qa.mjs
```
The first returned `v24.22.3 WebSocket=function`. The second passed all 24 filter intersections, 7 source-card checks, result counts, empty states, reset, control labels, keyboard tab order and focus outlines, and overflow checks at 320/390/768/1280 pixels. It recorded zero browser exceptions and zero external requests. The script contains the exact Chromium launch flags and CDP checks, and writes `qa-results.json`, `desktop.png`, and `mobile.png`. Both screenshots were opened and visually inspected using `view_image`; no clipping or layout defects were found. See `QA.md` for scope and limitations. Documentation was written with shell heredocs, including this validation append; no production system was accessed. No functional corrections were necessary after the first test run.

## Files
- `index.html`: complete standalone deliverable; double-click to use offline.
- `build.py`: reproducible fixture-to-HTML generator; no third-party dependencies.
- `qa.mjs`: reproducible browser tests using built-in Node APIs and installed Chromium (uses local debug port 9222).
- `QA.md` / `qa-results.json`: human-readable and machine-readable executed checks.
- `desktop.png` / `mobile.png`: inspected renders.
