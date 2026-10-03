param(
    [Parameter(Mandatory = $true)]
    [string]$PlanPath
)

$ErrorActionPreference = 'Stop'

function Remove-VerifiedPath([string]$Path, [string]$ExpectedParent, [switch]$Recurse) {
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path)) { return }
    $resolved = [System.IO.Path]::GetFullPath($Path)
    $parent = [System.IO.Path]::GetFullPath($ExpectedParent).TrimEnd('\')
    if ([System.IO.Path]::GetDirectoryName($resolved).TrimEnd('\') -ne $parent) {
        throw "拒绝删除未验证的路径：$resolved"
    }
    if ($Recurse) { Remove-Item -LiteralPath $resolved -Recurse -Force }
    else { Remove-Item -LiteralPath $resolved -Force }
}

$planFile = [System.IO.Path]::GetFullPath($PlanPath)
$plan = Get-Content -LiteralPath $planFile -Raw -Encoding UTF8 | ConvertFrom-Json
if ([int]$plan.schemaVersion -ne 1 -or [string]$plan.productId -ne 'shulian') {
    throw '卸载计划身份无效。'
}

$appDir = [System.IO.Path]::GetFullPath([string]$plan.appDir).TrimEnd('\')
$appExe = [System.IO.Path]::GetFullPath([string]$plan.appExe)
if ([System.IO.Path]::GetDirectoryName($appExe).TrimEnd('\') -ne $appDir -or
    [System.IO.Path]::GetFileName($appExe) -ne 'Shulian.exe') {
    throw '卸载目标不是经过验证的数恋程序目录。'
}
$releasePath = Join-Path $appDir '_internal\release.json'
if (-not (Test-Path -LiteralPath $releasePath)) {
    throw '找不到数恋发布身份，已停止卸载。'
}
$release = Get-Content -LiteralPath $releasePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$release.productId -ne 'shulian') {
    throw '数恋发布身份不匹配，已停止卸载。'
}

$processId = [int]$plan.processId
if ($processId -gt 0) {
    try { Wait-Process -Id $processId -Timeout 30 -ErrorAction Stop } catch { }
    if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
        Stop-Process -Id $processId -Force
        Start-Sleep -Milliseconds 600
    }
}

Remove-VerifiedPath -Path (Join-Path $appDir '_internal') -ExpectedParent $appDir -Recurse
Remove-VerifiedPath -Path $appExe -ExpectedParent $appDir

if ([bool]$plan.removeUserData) {
    foreach ($name in @('webview-data', 'media')) {
        Remove-VerifiedPath -Path (Join-Path $appDir $name) -ExpectedParent $appDir -Recurse
    }
    foreach ($name in @('.env', 'shulian-debug.log')) {
        Remove-VerifiedPath -Path (Join-Path $appDir $name) -ExpectedParent $appDir
    }
    $localDataDir = [System.IO.Path]::GetFullPath([string]$plan.localDataDir).TrimEnd('\')
    $expectedLocalData = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Shulian')).TrimEnd('\')
    if ($localDataDir -ne $expectedLocalData) {
        throw '本机数据目录未通过校验，程序文件已移除但用户数据已保留。'
    }
    if (Test-Path -LiteralPath $localDataDir) {
        Remove-Item -LiteralPath $localDataDir -Recurse -Force
    }
}

if ((Test-Path -LiteralPath $appDir) -and -not (Get-ChildItem -LiteralPath $appDir -Force | Select-Object -First 1)) {
    Remove-Item -LiteralPath $appDir -Force
}

Remove-Item -LiteralPath $planFile -Force -ErrorAction SilentlyContinue
