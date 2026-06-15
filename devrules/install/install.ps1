# devrules installer for Windows (PowerShell).
# Wires the devrules MCP + read/write hooks into EVERY Claude config dir for the
# current user (all accounts, not just the default). Run once per machine.
#
#   powershell -ExecutionPolicy Bypass -File install.ps1
#   powershell -ExecutionPolicy Bypass -File install.ps1 "$env:USERPROFILE\.claude-account1"
#
# Override the server with $env:DEVRULES_URL = 'http://host:port'
param([string[]]$ConfigDirs)

$ErrorActionPreference = 'Stop'

$scriptDir = $PSScriptRoot
$share = Join-Path $env:USERPROFILE '.devrules\hooks'
$base = if ($env:DEVRULES_URL) { $env:DEVRULES_URL } else { 'http://100.87.156.88:8799' }
$url = $base.TrimEnd('/') + '/mcp'

# Find a Python launcher (prefer the 'py' launcher on Windows) and the claude CLI.
$py = $null
foreach ($c in 'py', 'python', 'python3') {
  $g = Get-Command $c -ErrorAction SilentlyContinue
  if ($g) { $py = $g.Source; break }
}
if (-not $py) { throw "Python not found. Install Python 3 and re-run." }
$claude = (Get-Command claude -ErrorAction SilentlyContinue).Source
if (-not $claude) { throw "claude CLI not found on PATH." }

# 1. Install the hook scripts to a shared location.
New-Item -ItemType Directory -Force -Path $share | Out-Null
Copy-Item (Join-Path $scriptDir '..\hooks\session-start.py') (Join-Path $share 'devrules-session-start.py') -Force
Copy-Item (Join-Path $scriptDir '..\hooks\session-stop.py')  (Join-Path $share 'devrules-session-stop.py')  -Force
$startScript = Join-Path $share 'devrules-session-start.py'
$stopScript  = Join-Path $share 'devrules-session-stop.py'
$start = '"{0}" "{1}"' -f $py, $startScript
$stop  = '"{0}" "{1}"' -f $py, $stopScript
Write-Host "Hooks installed -> $share"

# 2. Pick the config dirs to wire.
if ($ConfigDirs) {
  $dirs = $ConfigDirs
} else {
  $dirs = Get-ChildItem -Path $env:USERPROFILE -Directory -Force -ErrorAction SilentlyContinue |
          Where-Object { $_.Name -eq '.claude' -or $_.Name -like '.claude-*' } |
          ForEach-Object { $_.FullName }
}
if (-not $dirs) { $dirs = @(Join-Path $env:USERPROFILE '.claude') }

Write-Host ("Wiring {0} config dir(s) -> {1}" -f $dirs.Count, $url)
$applySettings = Join-Path $scriptDir 'apply_settings.py'
$defaultDir = Join-Path $env:USERPROFILE '.claude'
foreach ($d in $dirs) {
  Write-Host "== $d =="
  New-Item -ItemType Directory -Force -Path $d | Out-Null
  if ($d -eq $defaultDir) {
    # Default config dir: user-scope MCP must be written with CLAUDE_CONFIG_DIR
    # UNSET (that's what a bare `claude` and the VSCode extension read).
    Remove-Item Env:CLAUDE_CONFIG_DIR -ErrorAction SilentlyContinue
  } else {
    $env:CLAUDE_CONFIG_DIR = $d
  }
  & $claude mcp remove devrules --scope user 2>$null | Out-Null
  & $claude mcp add --transport http devrules $url --scope user | Out-Null
  Write-Host "  MCP registered"
  & $py $applySettings (Join-Path $d 'settings.json') $start $stop
}
Remove-Item Env:CLAUDE_CONFIG_DIR -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Done. Start a fresh session in any account; verify with: claude mcp list"
