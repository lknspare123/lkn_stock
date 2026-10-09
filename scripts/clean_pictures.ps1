<#
Remove the background of ALL your item pictures in one go and save them to R2 + Neon.
Uses the ClearBackdrop API when CLEARBACKDROP_API_KEY is in .env (nothing to install; free limit 80 pictures a day, 40 an hour), otherwise rembg on this PC.

Run from the project folder:
    .\scripts\clean_pictures.ps1 -Limit 5          # test on 5 pictures first, then look at them in the app
    .\scripts\clean_pictures.ps1                   # all pictures that are not cleaned yet
    .\scripts\clean_pictures.ps1 -Model u2net      # slower, better edges (u2netp is the default, fastest)

It reads your secrets from the .env file in the project folder (DATABASE_URL, R2_*), so you do not type them each time.
It is safe to run again and again: finished pictures are skipped, failed ones are listed in images_failed.txt.
#>
param(
    [int]$Limit = 0,
    [string]$Engine = "",        # clearbackdrop | rembg   (default: clearbackdrop when CLEARBACKDROP_API_KEY is set in .env, else rembg)
    [string]$Model = "u2netp",   # rembg on this PC only
    [int]$Size = 768,
    [string]$Only = "",
    [switch]$Force
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) { throw "No .env file in $root. Copy .env.example to .env and fill DATABASE_URL and the R2_* values." }
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$' -and -not $_.TrimStart().StartsWith('#')) {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2].Trim().Trim('"').Trim("'"), "Process")
    }
}
if (-not $Engine) { $Engine = if ($env:CLEARBACKDROP_API_KEY) { "clearbackdrop" } else { "rembg" } }
$env:BG_REMOVER = $Engine
$env:REMBG_MODEL = $Model
$env:REMBG_SIZE = "$Size"

$py = if (Test-Path (Join-Path $root ".venv\Scripts\python.exe")) { Join-Path $root ".venv\Scripts\python.exe" } else { "python" }
if ($Engine -eq "rembg") {
    & $py -c "import rembg, onnxruntime" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing rembg (one time)..."
        & $py -m pip install -r requirements.txt -r requirements-rembg.txt
    }
}

$argsList = @("scripts/migrate_images_to_r2.py", "--ai")
if ($Limit -gt 0) { $argsList += @("--limit", "$Limit") }
if ($Only)        { $argsList += @("--only", $Only) }
if ($Force)       { $argsList += "--force" }
if ($Engine -eq "clearbackdrop") { Write-Host "Engine: ClearBackdrop API (free: 80 a day, 40 an hour - use -Limit 40 for one hour)" } else { Write-Host "Engine: rembg on this PC   model: $Model   input size: $Size px" }
& $py @argsList
