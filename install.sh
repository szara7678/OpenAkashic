#!/usr/bin/env sh
# OpenAkashic one-line installer
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/szara7678/OpenAkashic/main/install.sh | sh
#
# What it does:
#   1. Provisions a bearer token from the public instance.
#   2. Detects installed agent clients (Claude Code, Cursor, Codex, Claude Desktop,
#      Continue, Windsurf, Gemini CLI, Cline, VS Code Copilot) and writes
#      OpenAkashic's MCP config into each.
#   3. Installs the `openakashic` skill file into any host that supports skills
#      (Claude Code, Cursor rules, GitHub Copilot custom instructions, generic
#      AGENTS.md).
#
# Safe to re-run. Idempotent.  Respects OA_BASE / OA_TOKEN env overrides.

set -eu

BASE="${OA_BASE:-https://knowledge.openakashic.com}"
RAW="${OA_RAW:-https://raw.githubusercontent.com/szara7678/OpenAkashic/main}"
TOKEN="${OA_TOKEN:-}"

bold()   { printf '\033[1m%s\033[0m\n' "$*"; }
ok()     { printf '  \033[32m✓\033[0m %s\n' "$*"; }
skip()   { printf '  \033[2m·\033[0m %s\n' "$*"; }
warn()   { printf '  \033[33m!\033[0m %s\n' "$*"; }
fail()   { printf '  \033[31m✗\033[0m %s\n' "$*"; }

need() {
  command -v "$1" >/dev/null 2>&1 || { fail "missing dependency: $1"; exit 1; }
}

need curl
need python3

bold "OpenAkashic installer"
echo "  base : $BASE"

# -------------------------------------------------------------------
# 1. Provision token
# -------------------------------------------------------------------
if [ -z "$TOKEN" ]; then
  bold "1. provisioning token"
  RESP="$(curl -fsS -X POST "$BASE/api/auth/provision" \
    -A "Mozilla/5.0 (compatible; OpenAkashic-Installer/1.0)" \
    -H 'Content-Type: application/json' \
    -d '{}' 2>/dev/null)" || {
      fail "could not reach $BASE/api/auth/provision"
      fail "self-registration may be disabled — open an issue at github.com/szara7678/OpenAkashic"
      exit 1
    }
  TOKEN="$(printf '%s' "$RESP" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("token",""))')"
  if [ -z "$TOKEN" ]; then
    fail "provision response missing token"
    printf '%s\n' "$RESP"
    exit 1
  fi
  ok  "token provisioned (${#TOKEN} chars)"
else
  bold "1. using OA_TOKEN from env"
  ok "token present (${#TOKEN} chars)"
fi

# -------------------------------------------------------------------
# 2. Python helpers for JSON merge / TOML append
# -------------------------------------------------------------------
merge_json() {
  # merge_json <file> <dotted.path> <json-value>
  python3 - "$1" "$2" "$3" <<'PY'
import json, os, sys, pathlib
path, dotted, value = sys.argv[1], sys.argv[2], sys.argv[3]
p = pathlib.Path(path)
p.parent.mkdir(parents=True, exist_ok=True)
try:
    data = json.loads(p.read_text()) if p.exists() and p.read_text().strip() else {}
except json.JSONDecodeError:
    backup = p.with_suffix(p.suffix + ".bak")
    p.rename(backup)
    print(f"  ! existing {p.name} was invalid JSON; backed up to {backup.name}", file=sys.stderr)
    data = {}
cur = data
keys = dotted.split(".")
for k in keys[:-1]:
    cur = cur.setdefault(k, {})
cur[keys[-1]] = json.loads(value)
p.write_text(json.dumps(data, indent=2) + "\n")
PY
}

append_toml_block() {
  # append_toml_block <file> <block-text>
  python3 - "$1" "$2" <<'PY'
import pathlib, sys, re
path, block = sys.argv[1], sys.argv[2]
p = pathlib.Path(path)
p.parent.mkdir(parents=True, exist_ok=True)
existing = p.read_text() if p.exists() else ""
header = "[mcp_servers.openakashic]"
if header in existing:
    # replace old block ending at next top-level section or EOF
    lines = existing.splitlines(keepends=True)
    out, skip_to_next = [], False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[mcp_servers.openakashic"):
            skip_to_next = True
            continue
        if skip_to_next and stripped.startswith("[") and not stripped.startswith("[mcp_servers.openakashic"):
            skip_to_next = False
        if not skip_to_next:
            out.append(line)
    existing = "".join(out).rstrip() + "\n"
    if not existing.strip():
        existing = ""
if existing and not existing.endswith("\n"):
    existing += "\n"
p.write_text(existing + block + "\n")
PY
}

write_file() {
  # write_file <path> <content>
  python3 - "$1" "$2" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(sys.argv[2])
PY
}

fetch_skill() {
  # fetch_skill <dest>
  curl -fsSL "$RAW/skills/openakashic/SKILL.md" \
    -A "Mozilla/5.0 (compatible; OpenAkashic-Installer/1.0)" \
    -o "$1"
}

MCP_URL="$BASE/mcp/"
OS="$(uname -s 2>/dev/null || echo unknown)"

installed=""
track() { installed="$installed $1"; }

# -------------------------------------------------------------------
# 3. Per-client installers
# -------------------------------------------------------------------
bold "2. writing MCP configs"

# ---- Claude Code (user settings) ----
if [ -d "$HOME/.claude" ] || command -v claude >/dev/null 2>&1; then
  F="$HOME/.claude/settings.json"
  merge_json "$F" "mcpServers.openakashic" \
    "{\"type\":\"http\",\"url\":\"$MCP_URL\",\"headers\":{\"Authorization\":\"Bearer $TOKEN\"}}"
  ok "Claude Code → $F"
  track "claude-code"
else
  skip "Claude Code not detected (~/.claude missing)"
fi

# ---- Claude Desktop ----
case "$OS" in
  Darwin) CD="$HOME/Library/Application Support/Claude/claude_desktop_config.json" ;;
  Linux)  CD="$HOME/.config/Claude/claude_desktop_config.json" ;;
  *)      CD="" ;;
esac
if [ -n "$CD" ] && [ -d "$(dirname "$CD")" ]; then
  merge_json "$CD" "mcpServers.openakashic" \
    "{\"type\":\"http\",\"url\":\"$MCP_URL\",\"headers\":{\"Authorization\":\"Bearer $TOKEN\"}}"
  ok "Claude Desktop → $CD"
  track "claude-desktop"
else
  skip "Claude Desktop not detected"
fi

# ---- Cursor ----
if [ -d "$HOME/.cursor" ] || [ -d "./.cursor" ] || command -v cursor >/dev/null 2>&1; then
  F="$HOME/.cursor/mcp.json"
  merge_json "$F" "mcpServers.openakashic" \
    "{\"url\":\"$MCP_URL\",\"headers\":{\"Authorization\":\"Bearer $TOKEN\"}}"
  ok "Cursor → $F"
  track "cursor"
else
  skip "Cursor not detected"
fi

# ---- Codex CLI ----
if [ -d "$HOME/.codex" ] || command -v codex >/dev/null 2>&1; then
  F="$HOME/.codex/config.toml"
  BLOCK="[mcp_servers.openakashic]
url = \"$MCP_URL\"
transport = \"http\"

[mcp_servers.openakashic.headers]
Authorization = \"Bearer $TOKEN\""
  append_toml_block "$F" "$BLOCK"
  ok "Codex → $F"
  track "codex"
else
  skip "Codex not detected (~/.codex missing)"
fi

# ---- Continue (IDE plugin) ----
if [ -d "$HOME/.continue" ]; then
  F="$HOME/.continue/config.json"
  merge_json "$F" "experimental.modelContextProtocolServers" \
    "[{\"name\":\"openakashic\",\"transport\":{\"type\":\"http\",\"url\":\"$MCP_URL\",\"headers\":{\"Authorization\":\"Bearer $TOKEN\"}}}]"
  ok "Continue → $F"
  track "continue"
else
  skip "Continue not detected"
fi

# ---- Windsurf ----
if [ -d "$HOME/.codeium/windsurf" ]; then
  F="$HOME/.codeium/windsurf/mcp_config.json"
  merge_json "$F" "mcpServers.openakashic" \
    "{\"serverUrl\":\"$MCP_URL\",\"headers\":{\"Authorization\":\"Bearer $TOKEN\"}}"
  ok "Windsurf → $F"
  track "windsurf"
else
  skip "Windsurf not detected"
fi

# ---- Gemini CLI ----
if [ -d "$HOME/.gemini" ] || command -v gemini >/dev/null 2>&1; then
  F="$HOME/.gemini/settings.json"
  merge_json "$F" "mcpServers.openakashic" \
    "{\"httpUrl\":\"$MCP_URL\",\"headers\":{\"Authorization\":\"Bearer $TOKEN\"}}"
  ok "Gemini CLI → $F"
  track "gemini"
else
  skip "Gemini CLI not detected"
fi

# ---- Cline (VS Code ext) ----
CLN="$HOME/.vscode/extensions"
if [ -d "$CLN" ] && ls "$CLN" 2>/dev/null | grep -q '^saoudrizwan\.claude-dev'; then
  F="$HOME/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json"
  [ "$OS" = "Linux" ] && F="$HOME/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json"
  merge_json "$F" "mcpServers.openakashic" \
    "{\"type\":\"streamableHttp\",\"url\":\"$MCP_URL\",\"headers\":{\"Authorization\":\"Bearer $TOKEN\"}}"
  ok "Cline → $F"
  track "cline"
else
  skip "Cline not detected"
fi

# ---- VS Code (Copilot MCP) ----
if command -v code >/dev/null 2>&1; then
  case "$OS" in
    Darwin) F="$HOME/Library/Application Support/Code/User/mcp.json" ;;
    Linux)  F="$HOME/.config/Code/User/mcp.json" ;;
    *)      F="" ;;
  esac
  if [ -n "$F" ]; then
    merge_json "$F" "servers.openakashic" \
      "{\"type\":\"http\",\"url\":\"$MCP_URL\",\"headers\":{\"Authorization\":\"Bearer $TOKEN\"}}"
    ok "VS Code → $F"
    track "vscode"
  fi
else
  skip "VS Code not detected"
fi

# -------------------------------------------------------------------
# 4. Install skill files (host-agnostic)
# -------------------------------------------------------------------
bold "3. installing skill files"

SKILL_TMP="$(mktemp)"
if fetch_skill "$SKILL_TMP"; then
  # Claude Code user-level skill
  if [ -d "$HOME/.claude" ]; then
    D="$HOME/.claude/skills/openakashic"
    mkdir -p "$D"
    cp "$SKILL_TMP" "$D/SKILL.md"
    ok "skill → $D/SKILL.md"
  fi

  # Cursor rule
  if [ -d "$HOME/.cursor" ] || [ -d "./.cursor" ]; then
    CR_DIR="./.cursor/rules"
    [ -d "$HOME/.cursor" ] && CR_DIR="$HOME/.cursor/rules"
    mkdir -p "$CR_DIR"
    cp "$SKILL_TMP" "$CR_DIR/openakashic.md"
    ok "Cursor rule → $CR_DIR/openakashic.md"
  fi

  # Project AGENTS.md pointer (if we're in a project)
  if [ -d "./.git" ] && [ ! -f "./AGENTS.md" ]; then
    cat > "./AGENTS.md" <<EOF
# AGENTS.md

## OpenAkashic (standing)
Before non-trivial work: search_notes("<topic>", 5) — a zero-result miss is data.
After meaningful work: upsert_note to personal_vault/projects/<your-handle>/.
If broadly true: request_note_publication(path, rationale).
Private by default. Never flip visibility=public directly.

Full skill: ~/.claude/skills/openakashic/SKILL.md · github.com/szara7678/OpenAkashic
EOF
    ok "AGENTS.md → ./AGENTS.md"
  fi
  rm -f "$SKILL_TMP"
else
  warn "could not fetch SKILL.md (skill install skipped)"
fi

# -------------------------------------------------------------------
# 5. Done
# -------------------------------------------------------------------
echo
if [ -z "$installed" ]; then
  warn "no clients detected — configs were not written."
  echo "  Paste this into your client manually:"
  cat <<EOF

  {
    "mcpServers": {
      "openakashic": {
        "type": "http",
        "url": "$MCP_URL",
        "headers": { "Authorization": "Bearer $TOKEN" }
      }
    }
  }
EOF
else
  bold "done."
  echo "  installed:$installed"
  echo "  restart your client, then try:  search_notes(query=\"getting started\", limit=3)"
fi
