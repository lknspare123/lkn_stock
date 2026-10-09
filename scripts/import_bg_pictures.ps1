<#
Import the pictures saved on this PC (named <item code>_bg.png, e.g. 12003_bg.png) to the cloud and link them to the items.
Reads DATABASE_URL and R2_* from the .env file in the project folder.

    .\scripts\import_bg_pictures.ps1 -Folder "D:\LKN\bg_pictures" -DryRun     # look first, changes nothing
    .\scripts\import_bg_pictures.ps1 -Folder "D:\LKN\bg_pictures"             # do it
    -Force         also replace items that already have a background-removed picture
    -OnlyMissing   only items that have no picture at all
    -AsIs          do not trim / centre the picture
#>
param(
    [Parameter(Mandatory = $true)][string]$Folder,
    [switch]$DryRun,
    [switch]$Force,
    [switch]$OnlyMissing,
    [switch]$AsIs
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
$py = if (Test-Path (Join-Path $root ".venv\Scripts\python.exe")) { Join-Path $root ".venv\Scripts\python.exe" } else { "python" }

$argsList = @("scripts/import_bg_pictures.py", $Folder)
if ($DryRun)      { $argsList += "--dry-run" }
if ($Force)       { $argsList += "--force" }
if ($OnlyMissing) { $argsList += "--only-missing" }
if ($AsIs)        { $argsList += "--as-is" }
& $py @argsList
