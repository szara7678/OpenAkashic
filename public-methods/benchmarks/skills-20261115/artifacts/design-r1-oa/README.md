# Cedar help-desk directory

Open `index.html` directly in a modern browser. No server, build, credentials or network is needed. JavaScript powers the filters; a no-script notice explains this requirement.

## Source and guidance
- Service data: `/task/input/centers.json`, snapshot `2026-07-18`. All seven source locations are embedded without live-status inference.
- First retrieval: `python /runtime/research.py oa bundle '{"situation":"Build a self-contained offline civic help-desk directory from centers.json with accessible intersecting filters, fixed snapshot availability, responsive layout and browser QA","goal":"Deliver runnable index.html, README.md and QA.md; verify filters, accessibility basics and no horizontal overflow at 390px; render and inspect","mode":"hybrid","limit":3,"max_tokens":2048}'`. Result: zero items. No method IDs or versions were returned or applied.
- Consulted `/skills/catalog.json` and read `/skills/frontend-design/SKILL.md`. Catalog identifies frontend-design commit `1780c5e5a552fd4d1c9d6a7b0cab26b0c2bef064`, entrypoint SHA-256 `d91970639e9f5c37682ac7ab60094d35f1c7c1f38d731bd56396563aee10c1d3`. Other skill metadata was visible in the catalog; no other skill text was read.
- Applied frontend guidance: brief-specific compact design plan, restrained typography, meaningful structure, plain labels, responsive layout, visible focus, and screenshot critique. No third-party organization's branding.

## Design plan and review
Ink `#203b3a`, paper `#f5f2e9`, leaf `#46745a`, amber `#b77a21`, white `#ffffff`. Georgia headings evoke a familiar public notice; system sans-serif keeps details readable. Left-aligned header → compact introduction → snapshot notice → filters → two-column directory (one column on phones). Review against the brief removed any promotional hero or decorative imagery: the directory, not marketing, is the main feature. Status uses words as well as color.

## Implementation
A Python heredoc embeds the provided JSON and builds `index.html` with inline CSS and JavaScript. The default shows every location; any nondefault filter requires `open === true`, and step-free filtering requires `step_free === true`. Reset restores all seven. Status always refers to the fixed snapshot, never the device clock.

## Commands and validation
Initial inspection commands: `ls -la /task/input; cat /task/input/centers.json; cat /skills/catalog.json; ls -la /work; which chromium || which chromium-browser`; Node `require.resolve` probes found neither playwright nor puppeteer in default paths. `cat /skills/frontend-design/SKILL.md` read the guidance; Python import inspection found no Python playwright. Browser tooling and actual QA results are recorded below after execution, with details in `QA.md`.

## Limitations
Availability is a historical fixed snapshot, not current information. The fixture supplies no addresses, contacts or travel details; none are fabricated. System fonts may differ by platform. No production system or credentials are used.

## Executed browser validation
- Tool discovery: `ls -la /opt/eval-browser; find /opt/eval-browser -maxdepth 3 -name '*playwright*' -o -name '*puppeteer*'` found installed `playwright-core`. No package installation was needed.
- Artifact creation used shell `cat > /work/README.md <<'EOF'`, `cat > /work/QA.md <<'EOF'`, a `python - <<'PY'` heredoc reading `/task/input/centers.json` with `json.loads` and writing the inline page with `Path('/work/index.html').write_text(...)`, and `cat > /work/qa.cjs <<'EOF'`. These were local file-writing operations, not execution of source-supplied scripts. QA documentation was finalized with a shell heredoc and this README appended with `cat >> /work/README.md <<'EOF'`.
- Exact validation command: `node /work/qa.cjs`. Result: exit 0; PASS for all 24 filter combinations, seven initial source records, reset, displayed field checks, snapshot date, keyboard navigation, and no overflow at 390px in tested states. Zero page errors and zero HTTP(S) requests.
- Native `view_image` opened `/work/mobile.png`, `/work/desktop.png`, and `/work/empty-mobile.png`. Visual inspection found legible labels, intact cards and no clipping. No correction was needed after testing. See `QA.md` for scope, screenshots and limitations; `qa-results.json` contains actual automated results.
- Run again with `node /work/qa.cjs` in this supplied runtime. The website itself has no dependency on the QA tools or fixture once built.
