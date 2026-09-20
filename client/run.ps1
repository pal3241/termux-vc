$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path .venv\Scripts\python.exe)) {
  throw "Run .\client\install.ps1 first."
}
& .\.venv\Scripts\python.exe client\app.py
