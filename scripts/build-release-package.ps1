[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BuiltAppDir,

    [Parameter(Mandatory = $true)]
    [string]$OutputDir,

    [string]$MetadataPath = '',
    [string]$UpdaterPath = '',
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($MetadataPath)) {
    $MetadataPath = Join-Path $scriptDir '..\release.json'
}
if ([string]::IsNullOrWhiteSpace($UpdaterPath)) {
    $UpdaterPath = Join-Path $scriptDir '..\packaging\updater\ShulianUpdater.ps1'
}

function Resolve-FullPath([string]$Path) {
    return [System.IO.Path]::GetFullPath($Path)
}

function Get-Sha256Hex([string]$Path) {
    $stream = [System.IO.File]::OpenRead($Path)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha256.ComputeHash($stream)
        return ([System.BitConverter]::ToString($digest)).Replace(
            '-',
            ''
        ).ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
        $stream.Dispose()
    }
}

function Write-Utf8Json([string]$Path, [object]$Value) {
    $json = $Value | ConvertTo-Json -Depth 10
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $json, $utf8)
}

$BuiltAppDir = Resolve-FullPath $BuiltAppDir
$OutputDir = Resolve-FullPath $OutputDir
$MetadataPath = Resolve-FullPath $MetadataPath
$UpdaterPath = Resolve-FullPath $UpdaterPath
$builtExe = Join-Path $BuiltAppDir 'Shulian.exe'
$builtInternal = Join-Path $BuiltAppDir '_internal'
$bundledRelease = Join-Path $builtInternal 'release.json'

foreach ($required in @(
    $BuiltAppDir,
    $builtExe,
    $builtInternal,
    $bundledRelease,
    $MetadataPath,
    $UpdaterPath
)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "发布输入不完整：$required"
    }
}

$metadata = Get-Content -LiteralPath $MetadataPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
$bundledMetadata = Get-Content -LiteralPath $bundledRelease -Raw -Encoding UTF8 |
    ConvertFrom-Json
$versionText = [string]$metadata.version
$buildIdText = [string]$metadata.buildId
$bundledVersionText = [string]$bundledMetadata.version
$bundledBuildIdText = [string]$bundledMetadata.buildId

if ($metadata.schemaVersion -ne 1 -or
    [string]::IsNullOrWhiteSpace([string]$metadata.version) -or
    [string]::IsNullOrWhiteSpace([string]$metadata.buildId)) {
    throw 'release.json 缺少 schemaVersion、version 或 buildId。'
}
if ($versionText -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$') {
    throw "release.json 版本号不是语义版本：$($metadata.version)"
}
if ($versionText -ne $bundledVersionText -or
    $buildIdText -ne $bundledBuildIdText) {
    throw '构建内 release.json 与源码发布身份不一致。'
}

$protected = @($metadata.protectedPaths | ForEach-Object {
    ([string]$_).Trim().Trim([char[]]@(92, 47)).ToLowerInvariant()
})
foreach ($name in $protected) {
    if ($name -and (Test-Path -LiteralPath (Join-Path $BuiltAppDir $name))) {
        throw "构建产物包含受保护的用户路径：$name"
    }
}
$unsafeBuiltFiles = @(
    Get-ChildItem -LiteralPath $BuiltAppDir -Recurse -File -Force |
        Where-Object {
            $relative = $_.FullName.Substring($BuiltAppDir.Length).TrimStart(
                [char[]]@(92, 47)
            ).Replace([char]92, [char]47).ToLowerInvariant()
            $leaf = [System.IO.Path]::GetFileName($relative)
            $root = $relative.Split('/')[0]
            $protected -contains $root -or
                $leaf -eq '.env' -or
                $leaf.StartsWith('.env.')
        }
)
if ($unsafeBuiltFiles) {
    throw "构建产物包含禁止发布的配置或用户文件：$($unsafeBuiltFiles[0].FullName)"
}

if ($ValidateOnly) {
    [pscustomobject]@{
        version = [string]$metadata.version
        buildId = [string]$metadata.buildId
        builtAppDir = $BuiltAppDir
        outputDir = $OutputDir
        updater = $UpdaterPath
    } | ConvertTo-Json
    return
}

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$workRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
    'shulian-release-' + [Guid]::NewGuid().ToString('N')
)
$payloadRoot = Join-Path $workRoot 'payload'
$manifestPath = Join-Path $workRoot 'release-manifest.json'
$workUpdater = Join-Path $workRoot 'ShulianUpdater.ps1'

try {
    New-Item -ItemType Directory -Path $payloadRoot -Force | Out-Null
    Copy-Item -LiteralPath $builtExe -Destination (Join-Path $payloadRoot 'Shulian.exe')
    Copy-Item -LiteralPath $builtInternal -Destination $payloadRoot -Recurse
    Copy-Item -LiteralPath $UpdaterPath -Destination $workUpdater

    $files = @(
        Get-ChildItem -LiteralPath $payloadRoot -Recurse -File -Force |
            ForEach-Object {
                $relative = $_.FullName.Substring($payloadRoot.Length).TrimStart(
                    [char[]]@(92, 47)
                )
                [pscustomobject]@{
                    path = $relative.Replace([char]92, [char]47)
                    bytes = [int64]$_.Length
                    sha256 = Get-Sha256Hex $_.FullName
                }
            } |
            Sort-Object path
    )
    if ($files.Count -lt 2) {
        throw '发布包文件清单异常。'
    }

    $manifest = [ordered]@{
        schemaVersion = 1
        productId = [string]$metadata.productId
        displayName = [string]$metadata.displayName
        version = [string]$metadata.version
        buildId = [string]$metadata.buildId
        channel = [string]$metadata.channel
        platform = [string]$metadata.platform
        entrypoint = [string]$metadata.entrypoint
        healthPath = [string]$metadata.healthPath
        minUpdaterVersion = [string]$metadata.minUpdaterVersion
        protectedPaths = @($metadata.protectedPaths)
        managedPaths = @($metadata.managedPaths)
        createdAt = [DateTime]::UtcNow.ToString('o')
        files = $files
    }
    Write-Utf8Json $manifestPath $manifest

    $archiveName = "Shulian-$($metadata.version)-win-x64.zip"
    $archivePath = Join-Path $OutputDir $archiveName
    if (Test-Path -LiteralPath $archivePath) {
        Remove-Item -LiteralPath $archivePath -Force
    }
    Compress-Archive -Path @($payloadRoot, $manifestPath, $workUpdater) `
        -DestinationPath $archivePath -CompressionLevel Optimal

    $archiveHash = Get-Sha256Hex $archivePath
    $checksumPath = "$archivePath.sha256"
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText(
        $checksumPath,
        "$archiveHash  $archiveName`n",
        $utf8
    )

    [pscustomobject]@{
        ok = $true
        version = [string]$metadata.version
        buildId = [string]$metadata.buildId
        archive = $archivePath
        sha256 = $archiveHash
        checksum = $checksumPath
        fileCount = $files.Count
    } | ConvertTo-Json
}
finally {
    if (Test-Path -LiteralPath $workRoot) {
        Remove-Item -LiteralPath $workRoot -Recurse -Force
    }
}
