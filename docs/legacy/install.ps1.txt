# OpenAkashic one-line installer (Windows PowerShell)
# Usage:
#   iwr -useb https://raw.githubusercontent.com/szara7678/OpenAkashic/main/install.ps1 | iex
#
# Safe to re-run. Honours $env:OA_BASE / $env:OA_TOKEN overrides.

$ErrorActionPreference = 'Stop'
$Base  = if ($env:OA_BASE)  { $env:OA_BASE }  else { 'https://knowledge.openakashic.com' }
$Raw   = if ($env:OA_RAW)   { $env:OA_RAW }   else { 'https://raw.githubusercontent.com/szara7678/OpenAkashic/main' }
$Token = $env:OA_TOKEN
$McpUrl = "$Base/mcp/"
$Installed = @()

function OK($m)   { Write-Host "  ✓ $m" -ForegroundColor Green }
function SKIP($m) { Write-Host "  · $m" -ForegroundColor DarkGray }
function WARN($m) { Write-Host "  ! $m" -ForegroundColor Yellow }
function FAIL($m) { Write-Host "  ✗ $m" -ForegroundColor Red }

Write-Host "OpenAkashic installer" -ForegroundColor Cyan
Write-Host "  base : $Base"

# --- 1. provision token --------------------------------------------
if (-not $Token) {
  Write-Host "1. provisioning token" -ForegroundColor Cyan
  try {
    $resp = Invoke-RestMethod -Method POST -Uri "$Base/api/auth/provision" `
      -Headers @{ 'User-Agent' = 'Mozilla/5.0 (compatible; OpenAkashic-Installer/1.0)'; 'Content-Type' = 'application/json' } `
      -Body '{}'
    $Token = $resp.token
  } catch {
    FAIL "could not reach $Base/api/auth/provision — $_"
    exit 1
  }
  if (-not $Token) { FAIL "response missing token"; exit 1 }
  OK "token provisioned ($($Token.Length) chars)"
} else {
  Write-Host "1. using OA_TOKEN from env" -ForegroundColor Cyan
  OK "token present"
}

# --- helpers --------------------------------------------------------
function Merge-Json {
  param([string]$Path, [string]$Dotted, [hashtable]$Value)
  $dir = Split-Path -Parent $Path
  if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  $data = @{}
  if (Test-Path $Path) {
    $raw = (Get-Content $Path -Raw -ErrorAction SilentlyContinue)
    if ($raw -and $raw.Trim()) {
      try { $data = $raw | ConvertFrom-Json -AsHashtable } catch {
        Copy-Item $Path "$Path.bak" -Force
        WARN "existing $(Split-Path $Path -Leaf) invalid JSON; backed up to $(Split-Path $Path -Leaf).bak"
        $data = @{}
      }
    }
  }
  $keys = $Dotted -split '\.'
  $cur = $data
  for ($i = 0; $i -lt $keys.Count - 1; $i++) {
    if (-not $cur.ContainsKey($keys[$i]) -or -not ($cur[$keys[$i]] -is [hashtable])) {
      $cur[$keys[$i]] = @{}
    }
    $cur = $cur[$keys[$i]]
  }
  $cur[$keys[-1]] = $Value
  ($data | ConvertTo-Json -Depth 20) | Set-Content -Path $Path -Encoding UTF8
}

function Append-Toml {
  param([string]$Path, [string]$Block)
  $dir = Split-Path -Parent $Path
  if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  $existing = if (Test-Path $Path) { Get-Content $Path -Raw } else { "" }
  if ($existing -match '\[mcp_servers\.openakashic') {
    # naive strip: remove our block between header and next top-level section
    $existing = [regex]::Replace($existing, '(?ms)\[mcp_servers\.openakashic.*?(?=^\[(?!mcp_servers\.openakashic)|\z)', '')
  }
  if ($existing -and -not $existing.EndsWith("`n")) { $existing += "`n" }
  ($existing + $Block + "`n") | Set-Content -Path $Path -Encoding UTF8
}

# --- 2. per-client --------------------------------------------------
Write-Host "2. writing MCP configs" -ForegroundColor Cyan

# Claude Code
if (Test-Path "$HOME\.claude") {
  $f = "$HOME\.claude\settings.json"
  Merge-Json $f "mcpServers.openakashic" @{ type = "http"; url = $McpUrl; headers = @{ Authorization = "Bearer $Token" } }
  OK "Claude Code → $f"; $Installed += "claude-code"
} else { SKIP "Claude Code not detected" }

# Claude Desktop
$cd = "$env:APPDATA\Claude\claude_desktop_config.json"
if (Test-Path (Split-Path $cd -Parent)) {
  Merge-Json $cd "mcpServers.openakashic" @{ type = "http"; url = $McpUrl; headers = @{ Authorization = "Bearer $Token" } }
  OK "Claude Desktop → $cd"; $Installed += "claude-desktop"
} else { SKIP "Claude Desktop not detected" }

# Cursor
if ((Test-Path "$HOME\.cursor") -or (Get-Command cursor -ErrorAction SilentlyContinue)) {
  $f = "$HOME\.cursor\mcp.json"
  Merge-Json $f "mcpServers.openakashic" @{ url = $McpUrl; headers = @{ Authorization = "Bearer $Token" } }
  OK "Cursor → $f"; $Installed += "cursor"
} else { SKIP "Cursor not detected" }

# Codex
if ((Test-Path "$HOME\.codex") -or (Get-Command codex -ErrorAction SilentlyContinue)) {
  $f = "$HOME\.codex\config.toml"
  $block = @"
[mcp_servers.openakashic]
url = "$McpUrl"
transport = "http"

[mcp_servers.openakashic.headers]
Authorization = "Bearer $Token"
"@
  Append-Toml $f $block
  OK "Codex → $f"; $Installed += "codex"
} else { SKIP "Codex not detected" }

# Continue
if (Test-Path "$HOME\.continue") {
  $f = "$HOME\.continue\config.json"
  Merge-Json $f "experimental.modelContextProtocolServers" @(@{
    name = "openakashic"
    transport = @{ type = "http"; url = $McpUrl; headers = @{ Authorization = "Bearer $Token" } }
  })
  OK "Continue → $f"; $Installed += "continue"
} else { SKIP "Continue not detected" }

# Windsurf
if (Test-Path "$HOME\.codeium\windsurf") {
  $f = "$HOME\.codeium\windsurf\mcp_config.json"
  Merge-Json $f "mcpServers.openakashic" @{ serverUrl = $McpUrl; headers = @{ Authorization = "Bearer $Token" } }
  OK "Windsurf → $f"; $Installed += "windsurf"
} else { SKIP "Windsurf not detected" }

# Gemini CLI
if ((Test-Path "$HOME\.gemini") -or (Get-Command gemini -ErrorAction SilentlyContinue)) {
  $f = "$HOME\.gemini\settings.json"
  Merge-Json $f "mcpServers.openakashic" @{ httpUrl = $McpUrl; headers = @{ Authorization = "Bearer $Token" } }
  OK "Gemini CLI → $f"; $Installed += "gemini"
} else { SKIP "Gemini CLI not detected" }

# VS Code
if (Get-Command code -ErrorAction SilentlyContinue) {
  $f = "$env:APPDATA\Code\User\mcp.json"
  Merge-Json $f "servers.openakashic" @{ type = "http"; url = $McpUrl; headers = @{ Authorization = "Bearer $Token" } }
  OK "VS Code → $f"; $Installed += "vscode"
} else { SKIP "VS Code not detected" }

# --- 3. skill -------------------------------------------------------
Write-Host "3. installing skill files" -ForegroundColor Cyan
try {
  $skill = Invoke-RestMethod -Uri "$Raw/skills/openakashic/SKILL.md" -Headers @{ 'User-Agent' = 'OpenAkashic-Installer/1.0' }
  if (Test-Path "$HOME\.claude") {
    $d = "$HOME\.claude\skills\openakashic"
    New-Item -ItemType Directory -Force -Path $d | Out-Null
    $skill | Set-Content -Path "$d\SKILL.md" -Encoding UTF8
    OK "skill → $d\SKILL.md"
  }
  if (Test-Path "$HOME\.cursor") {
    $d = "$HOME\.cursor\rules"
    New-Item -ItemType Directory -Force -Path $d | Out-Null
    $skill | Set-Content -Path "$d\openakashic.md" -Encoding UTF8
    OK "Cursor rule → $d\openakashic.md"
  }
} catch {
  WARN "could not fetch SKILL.md ($_)"
}

Write-Host ""
if ($Installed.Count -eq 0) {
  WARN "no clients detected — paste this manually:"
  Write-Host ""
  Write-Host ('{"mcpServers":{"openakashic":{"type":"http","url":"' + $McpUrl + '","headers":{"Authorization":"Bearer ' + $Token + '"}}}}')
} else {
  Write-Host "done." -ForegroundColor Cyan
  Write-Host ("  installed: " + ($Installed -join ", "))
  Write-Host '  restart your client, then try:  search_notes(query="getting started", limit=3)'
}
