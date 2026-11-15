# Cedar support directory

Open `index.html` directly in a browser. No server, internet connection, fonts, images, or packages are required. All seven source locations are embedded; status is explicitly a fixed 18 July 2026 snapshot, never a current-time calculation.

## Sources consulted
- `/task/input/centers.json`: complete supplied location data, snapshot `2026-07-18`; sole service-information source.
- `/skills/frontend-design/SKILL.md`: original `frontend-design`, catalog commit `1780c5e5a552fd4d1c9d6a7b0cab26b0c2bef064`, catalog SHA-256 `d91970639e9f5c37682ac7ab60094d35f1c7c1f38d731bd56396563aee10c1d3`. Read in full across initial and progressive reads. No explicit skill version is declared in the file.
- Discovery also returned `brand-guidelines` metadata; that skill was not read or applied. No other organization's identity is used.

## Applied guidance and design decisions
Use subject-specific, plain-language copy, compact layout, native labeled controls, visible focus, and helpful empty-state guidance. Palette: ink `#203b3a`, paper `#f5f2e9`, leaf `#46745a`, amber `#b77a21`, white `#ffffff`. Verdana body and a restrained Georgia Cedar wordmark use installed system fonts. Left-aligned header → notice → filters → two-column directory, reducing to one column on phones. Reviewed against the brief before implementation: no promotional hero, no decorative animation, no external assets. The provided civic palette takes precedence over generic design preferences.

All locations initially appear. Active filter intersections require source `open === true`; step-free filtering requires `step_free === true`, excluding false and unknown. Reset restores all seven. Static initial cards also remain readable without JavaScript, but filtering requires JavaScript.

## Commands and results
Exact discovery command:
`python /runtime/research.py skills search '{"query":"offline accessible civic service directory responsive website design","limit":3}'`

Source/environment inspection commands:
```
cat /skills/frontend-design/SKILL.md
ls -la /task/input
cat /task/input/centers.json
ls -la /work
node -e "for (const x of ['playwright','puppeteer']) {try {console.log(x,require.resolve(x))}catch{}}"
which chromium chromium-browser
sed -n '45,105p' /skills/frontend-design/SKILL.md
python -c "import importlib.util; print('playwright:', bool(importlib.util.find_spec('playwright')))"
ls /usr/lib/node_modules /opt/node_modules 2>/dev/null || true
node --version
python -c "import importlib.util; print({x:bool(importlib.util.find_spec(x)) for x in ['websocket','websockets','PIL']})"
sed -n '35,48p' /skills/frontend-design/SKILL.md
```
The initial combined source output was truncated; progressive reads recovered the omitted skill section. Node v24.22.3 and Chromium are available; Playwright/Puppeteer are absent. Node's built-in WebSocket permits dependency-free Chromium DevTools checks.

Files were written using shell heredocs (`cat > /work/build.py <<'PY'` and `cat > /work/README.md <<'EOF'`); the complete generation code is retained in `build.py`. Build command: `python /work/build.py` (passed; wrote self-contained `index.html`). Further actual QA commands and outcomes are recorded after execution in `QA.md`.

## Limitations
No live availability, contact details, maps, or addresses are supplied, so none are invented. Snapshot status can be outdated. System font rendering varies by platform. Automated browser checks do not replace screen-reader or resident usability testing.
