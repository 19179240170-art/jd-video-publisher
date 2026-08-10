param(
    [string]$Config = ".\config.json",
    [string]$AnalysisFile = "",
    [switch]$SyncFeishu,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$systemPython = Get-Command python -ErrorAction SilentlyContinue
if ($null -ne $systemPython -and $systemPython.Source -notlike "*WindowsApps*") {
    $python = $systemPython.Source
} else {
    throw "未找到Python。请安装Python 3.11以上版本。"
}

$arguments = @("run_phase1.py", "--config", $Config)
if ($AnalysisFile) { $arguments += @("--analysis-file", $AnalysisFile) }
if ($SyncFeishu) { $arguments += "--sync-feishu" }
if ($Force) { $arguments += "--force" }

Push-Location $projectRoot
try {
    & $python @arguments
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
