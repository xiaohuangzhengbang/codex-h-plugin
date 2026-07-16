$ErrorActionPreference = "Stop"
$ForwardedArgs = $args
$Launcher = Join-Path $PSScriptRoot "h_run.py"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Test-HPython {
    param(
        [string]$Executable,
        [string[]]$Prefix = @()
    )
    if (-not $Executable) {
        return $false
    }
    try {
        & $Executable @Prefix -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function Start-H {
    param(
        [string]$Executable,
        [string[]]$Prefix,
        [string]$Source
    )
    $env:H_BOOTSTRAP_PYTHON_SOURCE = $Source
    & $Executable @Prefix $Launcher @ForwardedArgs
    exit $LASTEXITCODE
}

$BundledCandidates = @(
    (Join-Path $HOME ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"),
    (Join-Path $HOME ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\bin\python.exe")
)

foreach ($Candidate in $BundledCandidates) {
    if ((Test-Path -LiteralPath $Candidate) -and (Test-HPython $Candidate)) {
        Start-H -Executable $Candidate -Prefix @() -Source "codex-bundled"
    }
}

$RuntimeRoot = Join-Path $HOME ".cache\codex-runtimes"
if (Test-Path -LiteralPath $RuntimeRoot) {
    $Discovered = Get-ChildItem -LiteralPath $RuntimeRoot -Filter "python.exe" -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match "[\\/]dependencies[\\/]python[\\/]" }
    foreach ($Item in $Discovered) {
        if (Test-HPython $Item.FullName) {
            Start-H -Executable $Item.FullName -Prefix @() -Source "codex-bundled-discovered"
        }
    }
}

$PyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
if ($PyLauncher -and (Test-HPython $PyLauncher.Source @("-3"))) {
    Start-H -Executable $PyLauncher.Source -Prefix @("-3") -Source "system-py-launcher"
}

foreach ($Name in @("python.exe", "python3.exe")) {
    $Command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($Command -and (Test-HPython $Command.Source)) {
        Start-H -Executable $Command.Source -Prefix @() -Source "system-path"
    }
}

$Winget = Get-Command "winget.exe" -ErrorAction SilentlyContinue
if ($Winget) {
    Write-Output "H bootstrap: Python was not found; installing a private user-scoped Python runtime..."
    & $Winget.Source install --id Python.Python.3.12 --exact --scope user --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
    $PythonRoot = Join-Path $env:LOCALAPPDATA "Programs\Python"
    if (Test-Path -LiteralPath $PythonRoot) {
        $Installed = Get-ChildItem -LiteralPath $PythonRoot -Filter "python.exe" -File -Recurse -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending
        foreach ($Item in $Installed) {
            if (Test-HPython $Item.FullName) {
                Start-H -Executable $Item.FullName -Prefix @() -Source "winget-user-install"
            }
        }
    }
}

Write-Error "H could not find the Codex Python runtime or automatically install Python 3.12. Repair Codex Desktop and invoke H again."
exit 1
