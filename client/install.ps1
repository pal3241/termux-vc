$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Test-PythonCommand {
  param(
    [string]$Exe,
    [string[]]$PrefixArgs = @()
  )

  try {
    $Output = & $Exe @PrefixArgs -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    $Version = ($Output | Select-Object -Last 1).Trim()
    return $Version -in @("3.11", "3.12")
  } catch {
    return $false
  }
}

function Find-Python {
  $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
  if ($PyLauncher) {
    foreach ($v in @("-3.11", "-3.12")) {
      if (Test-PythonCommand -Exe $PyLauncher.Source -PrefixArgs @($v)) {
        return @($PyLauncher.Source, $v)
      }
    }
  }

  $PythonExe = Get-Command python -ErrorAction SilentlyContinue
  if ($PythonExe -and (Test-PythonCommand -Exe $PythonExe.Source)) {
    return @($PythonExe.Source)
  }

  $Python3Exe = Get-Command python3 -ErrorAction SilentlyContinue
  if ($Python3Exe -and (Test-PythonCommand -Exe $Python3Exe.Source)) {
    return @($Python3Exe.Source)
  }

  $Message = @"
Python 3.11 or 3.12 was not found.

Recommended install:
  winget install -e --id Python.Python.3.11

After installation:
  close this PowerShell window
  open a new PowerShell
  cd $Root
  .\client\install.ps1

If 'py' exists but says 'No suitable Python runtime found', that only means
the Windows Python Launcher is installed without a compatible Python runtime.
"@
  throw $Message
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

Write-Host "Using Python:" -ForegroundColor Cyan
if ($Py.Length -eq 2) {
  & $Py[0] $Py[1] --version
} else {
  & $Py[0] --version
}

Write-Host "[1/5] Client environment"
Invoke-BasePython @("-m", "venv", ".venv")
& .\.venv\Scripts\python.exe -m pip install -U pip setuptools wheel
& .\.venv\Scripts\python.exe -m pip install -r client\requirements.txt

Write-Host "[2/5] Converter environment"
Invoke-BasePython @("-m", "venv", ".converter-venv")
& .\.converter-venv\Scripts\python.exe -m pip install -U pip setuptools wheel
& .\.converter-venv\Scripts\python.exe -m pip install "torch>=2.4,<2.6" "onnx>=1.17" "onnxscript>=0.1" "numpy>=1.26" "scipy>=1.14" "librosa>=0.10"

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
