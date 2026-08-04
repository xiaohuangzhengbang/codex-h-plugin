$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$ForwardedArgs = $args
$Launcher = Join-Path $PSScriptRoot "h_run.py"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$CodexHome = if ([string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
    Join-Path $HOME ".codex"
}
else {
    $env:CODEX_HOME
}
$RuntimeId = "portable-20260804031849"
$RuntimeRoot = Join-Path $CodexHome "cache\h\github-runtime\$RuntimeId"
$RuntimeLauncher = Join-Path $RuntimeRoot "runtime\h_launcher.exe"
$RuntimeCore = Join-Path $RuntimeRoot "runtime\h_core.exe"
$RuntimeAsset = "H-Codex-Plugin-Windows-x64.zip"
$RuntimePackageRoot = "H-Codex-Plugin-Windows-x64"
$RuntimeUrl = "https://github.com/xiaohuangzhengbang/codex-h-plugin/releases/download/v0.4.0-portable.20260804031849/$RuntimeAsset"
$RuntimeSha256 = "8a8d07118a1b8e1859bd605973a77aededa7cb03af83fb5e967e07eafbd7bdf4"

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

function Test-HRuntime {
    return (Test-Path -LiteralPath $RuntimeLauncher -PathType Leaf) -and
        (Test-Path -LiteralPath $RuntimeCore -PathType Leaf)
}

function Get-HFileSha256 {
    param([string]$Path)
    $Stream = [System.IO.File]::OpenRead($Path)
    try {
        $Hasher = [System.Security.Cryptography.SHA256]::Create()
        try {
            $Bytes = $Hasher.ComputeHash($Stream)
            return [System.BitConverter]::ToString($Bytes).Replace("-", "").ToLowerInvariant()
        }
        finally {
            $Hasher.Dispose()
        }
    }
    finally {
        $Stream.Dispose()
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

function Start-HRuntime {
    param([string]$Source)
    $env:H_BOOTSTRAP_PYTHON_SOURCE = $Source
    & $RuntimeLauncher @ForwardedArgs
    exit $LASTEXITCODE
}

function Install-HGithubRuntime {
    if (Test-HRuntime) {
        return
    }

    $TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "h-github-runtime-$PID-$(Get-Random)"
    $Archive = Join-Path $TempRoot $RuntimeAsset
    $ExtractRoot = Join-Path $TempRoot "extracted"
    $StagingRoot = "$RuntimeRoot.installing-$PID"
    New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null

    try {
        $PackageOverride = $env:H_RUNTIME_PACKAGE_PATH
        if (-not [string]::IsNullOrWhiteSpace($PackageOverride)) {
            if (-not (Test-Path -LiteralPath $PackageOverride -PathType Leaf)) {
                throw "H_RUNTIME_PACKAGE_PATH does not point to a file."
            }
            Copy-Item -LiteralPath $PackageOverride -Destination $Archive -Force
        }
        else {
            $DownloadUrl = if ([string]::IsNullOrWhiteSpace($env:H_RUNTIME_PACKAGE_URL)) {
                $RuntimeUrl
            }
            else {
                $env:H_RUNTIME_PACKAGE_URL
            }
            Write-Output "H bootstrap: downloading the verified Windows runtime from GitHub..."
            Invoke-WebRequest -UseBasicParsing -Uri $DownloadUrl -OutFile $Archive -Headers @{ "User-Agent" = "H-Codex-Plugin" }
        }

        $ExpectedHash = if ([string]::IsNullOrWhiteSpace($env:H_RUNTIME_PACKAGE_SHA256)) {
            $RuntimeSha256
        }
        else {
            $env:H_RUNTIME_PACKAGE_SHA256.Trim().ToLowerInvariant()
        }
        $ActualHash = Get-HFileSha256 -Path $Archive
        if ($ActualHash -ne $ExpectedHash) {
            throw "Downloaded H runtime failed SHA-256 verification."
        }

        New-Item -ItemType Directory -Path $ExtractRoot -Force | Out-Null
        Expand-Archive -LiteralPath $Archive -DestinationPath $ExtractRoot -Force
        $Payload = Join-Path $ExtractRoot "$RuntimePackageRoot\payload"
        if (-not (Test-Path -LiteralPath (Join-Path $Payload "runtime\h_launcher.exe") -PathType Leaf) -or
            -not (Test-Path -LiteralPath (Join-Path $Payload "runtime\h_core.exe") -PathType Leaf)) {
            throw "Downloaded H runtime archive is missing its executables."
        }

        New-Item -ItemType Directory -Path (Split-Path -Parent $RuntimeRoot) -Force | Out-Null
        if (Test-Path -LiteralPath $StagingRoot) {
            Remove-Item -LiteralPath $StagingRoot -Recurse -Force
        }
        Move-Item -LiteralPath $Payload -Destination $StagingRoot

        if (-not (Test-HRuntime)) {
            if (Test-Path -LiteralPath $RuntimeRoot) {
                Remove-Item -LiteralPath $RuntimeRoot -Recurse -Force
            }
            try {
                Move-Item -LiteralPath $StagingRoot -Destination $RuntimeRoot
            }
            catch {
                if (-not (Test-HRuntime)) {
                    throw
                }
            }
        }

        if (-not (Test-HRuntime)) {
            throw "H runtime installation did not complete."
        }
    }
    finally {
        if (Test-Path -LiteralPath $StagingRoot) {
            Remove-Item -LiteralPath $StagingRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $TempRoot) {
            Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

if (Test-HRuntime) {
    Start-HRuntime -Source "github-runtime-cache"
}

if ($env:H_FORCE_GITHUB_RUNTIME -eq "1") {
    Install-HGithubRuntime
    Start-HRuntime -Source "github-runtime-download"
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

$RuntimeSearchRoot = Join-Path $HOME ".cache\codex-runtimes"
if (Test-Path -LiteralPath $RuntimeSearchRoot) {
    $Discovered = Get-ChildItem -LiteralPath $RuntimeSearchRoot -Filter "python.exe" -File -Recurse -ErrorAction SilentlyContinue |
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

$RuntimeFailure = $null
try {
    Install-HGithubRuntime
    Start-HRuntime -Source "github-runtime-download"
}
catch {
    $RuntimeFailure = $_.Exception.Message
    Write-Warning "H could not download its GitHub runtime; trying the operating-system fallback."
}

$Winget = Get-Command "winget.exe" -ErrorAction SilentlyContinue
if ($Winget) {
    Write-Output "H bootstrap: installing a private user-scoped Python runtime with winget..."
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

$FailurePayload = @{
    ready = $false
    state = "setup-error"
    error_category = "runtime"
    display_text = "H could not prepare its runtime from GitHub. Check network access and invoke H again; no Kie task was submitted."
    reason = $RuntimeFailure
}
$FailurePayload | ConvertTo-Json -Compress
exit 0
