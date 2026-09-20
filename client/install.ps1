$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Find-Python {
  if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($v in @("-3.11", "-3.12")) {
      & py $v --version *> $null
      if ($LASTEXITCODE -eq 0) { return @("py", $v) }
    }
  }
  if (Get-Command python -ErrorAction SilentlyContinue) {
    & python --version *> $null
    if ($LASTEXITCODE -eq 0) { return @("python") }
  }
  throw "Python 3.11/3.12 not found. Install Python first."
}

$Py = Find-Python
function Invoke-BasePython([string[]]$ArgsList) {
  $Exe = $Py[0]
  if ($Py.Length -eq 2) {
    $Version = $Py[1]
    & $Exe $Version @ArgsList
  } else {
    & $Exe @ArgsList
  }
  if ($LASTEXITCODE -ne 0) { throw "Python command failed" }
}

Write-Host "[1/5] Client environment"
Invoke-BasePython @("-m", "venv", ".venv")
& .\.venv\Scripts\python.exe -m pip install -U pip setuptools wheel
& .\.venv\Scripts\python.exe -m pip install -r client\requirements.txt

Write-Host "[2/5] Converter environment"
Invoke-BasePython @("-m", "venv", ".converter-venv")
& .\.converter-venv\Scripts\python.exe -m pip install -U pip setuptools wheel
& .\.converter-venv\Scripts\python.exe -m pip install "torch>=2.4" "onnx>=1.17" "onnxscript>=0.1" "numpy>=1.26" "scipy>=1.14" "librosa>=0.10"

Write-Host "[3/5] RVC ONNX exporter"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  throw "Git is required. Install Git for Windows."
}
New-Item -ItemType Directory -Force .toolchain | Out-Null
if (-not (Test-Path .toolchain\rvc.onnx\scripts\convert_rvc_to_onnx.py)) {
  git clone --depth 1 https://github.com/SUC-DriverOld/rvc.onnx.git .toolchain\rvc.onnx
  if ($LASTEXITCODE -ne 0) { throw "Failed to clone RVC ONNX exporter" }
}

Write-Host "[4/5] Android Platform Tools"
$PlatformDir = Join-Path $Root ".toolchain\platform-tools"
if (-not (Test-Path (Join-Path $PlatformDir "adb.exe"))) {
  $Zip = Join-Path $env:TEMP "platform-tools-latest-windows.zip"
  Invoke-WebRequest "https://dl.google.com/android/repository/platform-tools-latest-windows.zip" -OutFile $Zip
  $Extract = Join-Path $Root ".toolchain\platform-tools-extract"
  if (Test-Path $Extract) { Remove-Item $Extract -Recurse -Force }
  Expand-Archive $Zip -DestinationPath $Extract -Force
  if (Test-Path $PlatformDir) { Remove-Item $PlatformDir -Recurse -Force }
  Move-Item (Join-Path $Extract "platform-tools") $PlatformDir
  Remove-Item $Extract -Recurse -Force
  Remove-Item $Zip -Force
}

Write-Host "[5/5] Done"
Write-Host "Run: .\client\run.ps1"
Write-Host "On Android, start server/run_server.sh, connect USB, enable USB debugging, then click USB ADB Forward."
