param(
    [string]$Claim = "",
    [switch]$ClaimNext,
    [string]$Complete = "",
    [string]$Fail = "",
    [string]$Message = ""
)

$ErrorActionPreference = "Stop"
$systemPython = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $systemPython -or $systemPython.Source -like "*WindowsApps*") {
    throw "未找到Python。请安装Python 3.11以上版本。"
}
$python = $systemPython.Source

$arguments = @("run_phase2.py")
if ($ClaimNext) {
    $arguments += "--claim-next"
} elseif ($Claim) {
    $arguments += @("--claim", $Claim)
} elseif ($Complete) {
    $arguments += @("--complete", $Complete)
} elseif ($Fail) {
    $arguments += @("--fail", $Fail, "--message", $Message)
}

& $python @arguments
exit $LASTEXITCODE
