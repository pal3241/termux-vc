$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path .venv\Scripts\python.exe)) {
  throw "Run client/install.ps1 first."
}
& .\.venv\Scripts\python.exe -m pip install pyinstaller
& .\.venv\Scripts\pyinstaller.exe --noconfirm --clean --windowed --name TermuxVC --paths client client\app.py
Write-Host "GUI build: dist\TermuxVC\TermuxVC.exe"
Write-Host "Keep .converter-venv and .toolchain next to the project if you want .pth auto-import in a source checkout."
