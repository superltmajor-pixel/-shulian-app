[CmdletBinding(DefaultParameterSetName = 'Install')]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'Install')]
    [string]$PackagePath,

    [Parameter(Mandatory = $true)]
    [string]$AppDir,

    [Parameter(ParameterSetName = 'Install')]
    [string]$ExpectedPackageSha256 = '',

    [Parameter(Mandatory = $true, ParameterSetName = 'Rollback')]
    [switch]$Rollback,

    [Parameter(ParameterSetName = 'Rollback')]
    [string]$BackupId = '',

    [switch]$AllowDowngrade,
    [switch]$NoLaunch,

    [Parameter(DontShow = $true)]
    [switch]$SkipProcessControl
)

$ErrorActionPreference = 'Stop'
$UpdaterVersion = '1.0.3'
$ProtectedRoots = @('.env', 'webview-data', 'media', 'shulian-debug.log')
$ManagedRoots = @('Shulian.exe', '_internal')

if ($SkipProcessControl -and
    (-not $NoLaunch -or $env:SHULIAN_UPDATER_TEST_MODE -ne '1')) {
    throw 'SkipProcessControl 只允许在显式无启动测试模式下使用。'
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

function Resolve-SafeRelativePath([string]$Root, [string]$Relative) {
    if ([string]::IsNullOrWhiteSpace($Relative) -or
        [System.IO.Path]::IsPathRooted($Relative) -or
        $Relative -match '(^|[\\/])\.\.([\\/]|$)' -or
        $Relative.Contains(':')) {
        throw "更新清单包含不安全路径：$Relative"
    }
    $rootFull = Resolve-FullPath $Root
    $candidate = Resolve-FullPath (Join-Path $rootFull $Relative)
    $prefix = $rootFull.TrimEnd([char[]]@(92, 47)) +
        [System.IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "更新路径越界：$Relative"
    }
    return $candidate
}

function Get-RelativeRoot([string]$Relative) {
    return (($Relative -replace '\\', '/').Split('/')[0]).ToLowerInvariant()
}

function Assert-ManagedRelativePath([string]$Relative) {
    $normalized = ($Relative -replace '\\', '/').ToLowerInvariant()
    $root = Get-RelativeRoot $Relative
    $leaf = [System.IO.Path]::GetFileName($normalized)
    if ($ProtectedRoots -contains $root) {
        throw "更新包试图覆盖用户数据：$Relative"
    }
    if ($leaf -eq '.env' -or $leaf.StartsWith('.env.')) {
        throw "更新包包含禁止发布的环境配置：$Relative"
    }
    $allowed = @($ManagedRoots | ForEach-Object { $_.ToLowerInvariant() })
    if ($allowed -notcontains $root) {
        throw "更新包包含未托管路径：$Relative"
    }
}

function Write-Utf8Json([string]$Path, [object]$Value) {
    $json = $Value | ConvertTo-Json -Depth 10
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $json, $utf8)
}

function Get-ShulianProcesses([string]$TargetAppDir) {
    $expectedPath = Resolve-FullPath (Join-Path $TargetAppDir 'Shulian.exe')
    $matches = @()
    foreach ($process in @(Get-Process -Name 'Shulian' -ErrorAction SilentlyContinue)) {
        try {
            $processPath = Resolve-FullPath ([string]$process.Path)
            if ($processPath.Equals($expectedPath, [StringComparison]::OrdinalIgnoreCase)) {
                $matches += $process
            }
        }
        catch {
            # 进程可能恰好正在退出；下一轮轮询会重新确认。
        }
    }
    return @($matches)
}

function Wait-ShulianExit([string]$TargetAppDir, [int]$TimeoutSeconds) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        if (@(Get-ShulianProcesses $TargetAppDir).Count -eq 0) {
            return $true
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    return $false
}

function Stop-Shulian([string]$TargetAppDir) {
    $running = @(Get-ShulianProcesses $TargetAppDir)
    foreach ($process in $running) {
        try { [void]$process.CloseMainWindow() } catch { }
    }
    if ($running.Count -gt 0 -and (Wait-ShulianExit $TargetAppDir 8)) {
        return
    }

    $remaining = @(Get-ShulianProcesses $TargetAppDir)
    foreach ($process in $remaining) {
        try { Stop-Process -Id $process.Id -Force -ErrorAction Stop } catch { }
    }
    if (-not (Wait-ShulianExit $TargetAppDir 8)) {
        $remainingIds = @(
            Get-ShulianProcesses $TargetAppDir | ForEach-Object { [string]$_.Id }
        ) -join ', '
        throw "数恋仍在运行，更新已停止。进程号：$remainingIds"
    }
}

function Read-ReleaseIdentity([string]$Root) {
    $path = Join-Path $Root '_internal\release.json'
    if (-not (Test-Path -LiteralPath $path)) {
        return [pscustomobject]@{ version = '0.0.0'; buildId = 'legacy' }
    }
    try {
        return Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "现有客户端发布身份损坏：$path"
    }
}

function Compare-SemVer([string]$Left, [string]$Right) {
    try {
        $leftVersion = [Version]($Left.Split('-')[0])
        $rightVersion = [Version]($Right.Split('-')[0])
        return $leftVersion.CompareTo($rightVersion)
    }
    catch {
        throw "无法比较版本号：$Left / $Right"
    }
}

function Test-PackagePayload([string]$PackageRoot, [object]$Manifest) {
    $manifestProductId = [string]$Manifest.productId
    $manifestPlatform = [string]$Manifest.platform
    $manifestVersion = [string]$Manifest.version
    $manifestBuildId = [string]$Manifest.buildId
    if ($Manifest.schemaVersion -ne 1 -or
        $manifestProductId -ne 'shulian' -or
        $manifestPlatform -ne 'windows-x64' -or
        [string]::IsNullOrWhiteSpace($manifestVersion) -or
        [string]::IsNullOrWhiteSpace($manifestBuildId)) {
        throw '更新清单身份无效。'
    }
    if ($manifestVersion -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$') {
        throw "更新清单版本号无效：$($Manifest.version)"
    }
    $minimumUpdater = [string]$Manifest.minUpdaterVersion
    if ([string]::IsNullOrWhiteSpace($minimumUpdater) -or
        (Compare-SemVer $UpdaterVersion $minimumUpdater) -lt 0) {
        throw "更新包要求更新器版本 $minimumUpdater，当前为 $UpdaterVersion。"
    }

    $payloadRoot = Join-Path $PackageRoot 'payload'
    if (-not (Test-Path -LiteralPath $payloadRoot)) {
        throw '更新包缺少 payload。'
    }
    $entries = @($Manifest.files)
    if ($entries.Count -lt 2 -or $entries.Count -gt 100000) {
        throw "更新清单文件数异常：$($entries.Count)"
    }

    $declared = @{}
    foreach ($entry in $entries) {
        $relative = [string]$entry.path
        Assert-ManagedRelativePath $relative
        $key = ($relative -replace '\\', '/').ToLowerInvariant()
        if ($declared.ContainsKey($key)) {
            throw "更新清单包含重复路径：$relative"
        }
        $target = Resolve-SafeRelativePath $payloadRoot $relative
        if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
            throw "更新包缺少文件：$relative"
        }
        $actualLength = (Get-Item -LiteralPath $target).Length
        if ([int64]$entry.bytes -ne $actualLength) {
            throw "更新文件大小不匹配：$relative"
        }
        $actualHash = Get-Sha256Hex $target
        if ($actualHash -ne ([string]$entry.sha256).ToLowerInvariant()) {
            throw "更新文件哈希不匹配：$relative"
        }
        $declared[$key] = $true
    }

    $actualFiles = @(
        Get-ChildItem -LiteralPath $payloadRoot -Recurse -File -Force
    )
    if ($actualFiles.Count -ne $declared.Count) {
        throw '更新包含有未列入清单的额外文件。'
    }
    foreach ($file in $actualFiles) {
        $relative = $file.FullName.Substring($payloadRoot.Length).TrimStart(
            [char[]]@(92, 47)
        )
        $key = ($relative -replace '\\', '/').ToLowerInvariant()
        if (-not $declared.ContainsKey($key)) {
            throw "更新包额外文件未列入清单：$relative"
        }
    }

    $bundledRelease = Get-Content `
        -LiteralPath (Join-Path $payloadRoot '_internal\release.json') `
        -Raw -Encoding UTF8 | ConvertFrom-Json
    $bundledVersion = [string]$bundledRelease.version
    $bundledBuildId = [string]$bundledRelease.buildId
    if ($bundledVersion -ne $manifestVersion -or
        $bundledBuildId -ne $manifestBuildId) {
        throw 'payload 发布身份与更新清单不一致。'
    }
    return $payloadRoot
}

function New-Backup([string]$SourceRoot, [string]$BackupsRoot, [string]$Reason) {
    $identity = Read-ReleaseIdentity $SourceRoot
    $backupId = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' +
        [Guid]::NewGuid().ToString('N').Substring(0, 8)
    $backupRoot = Join-Path $BackupsRoot $backupId
    $payload = Join-Path $backupRoot 'payload'
    New-Item -ItemType Directory -Path $payload -Force | Out-Null
    foreach ($managed in $ManagedRoots) {
        $source = Join-Path $SourceRoot $managed
        if (Test-Path -LiteralPath $source) {
            Copy-Item -LiteralPath $source -Destination $payload -Recurse -Force
        }
    }
    Write-Utf8Json (Join-Path $backupRoot 'backup.json') ([ordered]@{
        schemaVersion = 1
        backupId = $backupId
        createdAt = [DateTime]::UtcNow.ToString('o')
        reason = $Reason
        version = [string]$identity.version
        buildId = [string]$identity.buildId
    })
    return $backupRoot
}

function New-Stage([string]$SourcePayload, [string]$TargetAppDir) {
    $stage = Join-Path $TargetAppDir (
        '.shulian-update-stage-' + [Guid]::NewGuid().ToString('N')
    )
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    foreach ($managed in $ManagedRoots) {
        $source = Join-Path $SourcePayload $managed
        if (-not (Test-Path -LiteralPath $source)) {
            throw "更新源缺少托管路径：$managed"
        }
        Copy-Item -LiteralPath $source -Destination $stage -Recurse -Force
    }
    return $stage
}

function Switch-ManagedPayload([string]$Stage, [string]$TargetAppDir) {
    $transaction = Join-Path $TargetAppDir (
        '.shulian-update-transaction-' + [Guid]::NewGuid().ToString('N')
    )
    $old = Join-Path $transaction 'old'
    New-Item -ItemType Directory -Path $old -Force | Out-Null
    try {
        foreach ($managed in $ManagedRoots) {
            $target = Join-Path $TargetAppDir $managed
            if (Test-Path -LiteralPath $target) {
                Move-Item -LiteralPath $target -Destination $old
            }
        }
        foreach ($managed in $ManagedRoots) {
            Move-Item -LiteralPath (Join-Path $Stage $managed) -Destination $TargetAppDir
        }
    }
    catch {
        foreach ($managed in $ManagedRoots) {
            $target = Join-Path $TargetAppDir $managed
            if (Test-Path -LiteralPath $target) {
                Remove-Item -LiteralPath $target -Recurse -Force
            }
            $oldTarget = Join-Path $old $managed
            if (Test-Path -LiteralPath $oldTarget) {
                Move-Item -LiteralPath $oldTarget -Destination $TargetAppDir
            }
        }
        throw
    }
    finally {
        if (Test-Path -LiteralPath $Stage) {
            Remove-Item -LiteralPath $Stage -Recurse -Force
        }
    }
    Remove-Item -LiteralPath $transaction -Recurse -Force
}

function Wait-ForHealthyBuild([string]$ExpectedBuildId) {
    $script:LastHealthFailure = '健康接口尚未响应。'
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $request = [System.Net.HttpWebRequest]::Create(
                'http://127.0.0.1:8770/api/self-check'
            )
            $request.Proxy = $null
            $request.Timeout = 1500
            $response = $request.GetResponse()
            $reader = New-Object System.IO.StreamReader(
                $response.GetResponseStream()
            )
            $payload = $reader.ReadToEnd() | ConvertFrom-Json
            $reader.Dispose()
            $response.Dispose()
            $servedBuildId = [string]$payload.backend.build_id
            $script:LastHealthFailure = (
                "backend=$([bool]$payload.backend.ok), " +
                "web=$([bool]$payload.web.ok), " +
                "storage=$([bool]$payload.storage.ok), " +
                "release=$([bool]$payload.release.ok), " +
                "servedBuild=$servedBuildId, expectedBuild=$ExpectedBuildId"
            )
            if ($payload.backend.ok -and
                $payload.web.ok -and
                $payload.storage.ok -and
                $payload.release.ok -and
                $servedBuildId -eq $ExpectedBuildId) {
                return $true
            }
        }
        catch { }
    }
    return $false
}

function Start-Shulian([string]$TargetAppDir) {
    $exe = Join-Path $TargetAppDir 'Shulian.exe'
    $hadInheritedBuildId = Test-Path Env:\SHULIAN_BUILD_ID
    $inheritedBuildId = [string]$env:SHULIAN_BUILD_ID
    try {
        # 更新器通常由旧客户端启动，不能把旧 Build ID 传给新版 EXE。
        Remove-Item Env:\SHULIAN_BUILD_ID -ErrorAction SilentlyContinue
        Start-Process -FilePath $exe -WorkingDirectory $TargetAppDir | Out-Null
    }
    finally {
        if ($hadInheritedBuildId) {
            $env:SHULIAN_BUILD_ID = $inheritedBuildId
        }
        else {
            Remove-Item Env:\SHULIAN_BUILD_ID -ErrorAction SilentlyContinue
        }
    }
}

function Refresh-ShulianDesktopShortcut([string]$TargetAppDir) {
    $desktop = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::Desktop
    )
    if ([string]::IsNullOrWhiteSpace($desktop) -or
        -not (Test-Path -LiteralPath $desktop -PathType Container)) {
        return $false
    }

    $shell = $null
    $shortcut = $null
    try {
        $exe = Join-Path $TargetAppDir 'Shulian.exe'
        $brandIcon = Join-Path $TargetAppDir '_internal\shulian.ico'
        $icon = if (Test-Path -LiteralPath $brandIcon -PathType Leaf) {
            $brandIcon
        }
        else {
            $exe
        }
        $shortcutPath = Join-Path $desktop '数字恋人.lnk'
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $exe
        $shortcut.WorkingDirectory = $TargetAppDir
        $shortcut.IconLocation = "$icon,0"
        $shortcut.Description = '数恋 · 数字恋人'
        $shortcut.Save()

        try {
            Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ShulianShellIconRefresh {
    [DllImport("shell32.dll")]
    private static extern void SHChangeNotify(
        uint eventId,
        uint flags,
        IntPtr item1,
        IntPtr item2
    );
    public static void Refresh() {
        SHChangeNotify(0x08000000, 0x0000, IntPtr.Zero, IntPtr.Zero);
    }
}
'@ -ErrorAction SilentlyContinue
            [ShulianShellIconRefresh]::Refresh()
        }
        catch {
            # 快捷方式本身已经更新；Shell 通知失败时留待下次资源管理器刷新。
        }
        return $true
    }
    catch {
        Write-Warning "桌面快捷方式刷新失败，已继续更新：$($_.Exception.Message)"
        return $false
    }
    finally {
        if ($null -ne $shortcut) {
            try {
                [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject(
                    $shortcut
                )
            }
            catch {
                # COM 资源释放失败不应中断已经完成的程序更新。
            }
        }
        if ($null -ne $shell) {
            try {
                [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell)
            }
            catch {
                # COM 资源释放失败不应中断已经完成的程序更新。
            }
        }
    }
}

$AppDir = Resolve-FullPath $AppDir
if (-not (Test-Path -LiteralPath $AppDir -PathType Container)) {
    throw "客户端目录不存在：$AppDir"
}
$localAppData = [string]$env:LOCALAPPDATA
if ([string]::IsNullOrWhiteSpace($localAppData)) {
    throw 'LOCALAPPDATA 不可用，无法建立安全回滚目录。'
}
$updatesRoot = Resolve-FullPath (Join-Path $localAppData 'Shulian\updates')
$backupsRoot = Join-Path $updatesRoot 'backups'
New-Item -ItemType Directory -Path $backupsRoot -Force | Out-Null

if ($Rollback) {
    $candidates = @(
        Get-ChildItem -LiteralPath $backupsRoot -Directory -ErrorAction SilentlyContinue |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'backup.json') } |
            Sort-Object LastWriteTimeUtc -Descending
    )
    if ($BackupId) {
        $candidates = @($candidates | Where-Object { $_.Name -eq $BackupId })
    }
    if (-not $candidates) {
        throw '没有可用的数恋程序回滚点。'
    }
    $selected = $candidates[0].FullName
    $selectedMetadata = Get-Content `
        -LiteralPath (Join-Path $selected 'backup.json') `
        -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $SkipProcessControl) { Stop-Shulian $AppDir }
    [void](New-Backup $AppDir $backupsRoot 'before-manual-rollback')
    $stage = New-Stage (Join-Path $selected 'payload') $AppDir
    Switch-ManagedPayload $stage $AppDir
    if (-not $SkipProcessControl) {
        [void](Refresh-ShulianDesktopShortcut $AppDir)
    }
    if (-not $NoLaunch) {
        Start-Shulian $AppDir
    }
    [pscustomobject]@{
        ok = $true
        action = 'rollback'
        backupId = [string]$selectedMetadata.backupId
        version = [string]$selectedMetadata.version
        buildId = [string]$selectedMetadata.buildId
    } | ConvertTo-Json
    return
}

$PackagePath = Resolve-FullPath $PackagePath
if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) {
    throw "更新包不存在：$PackagePath"
}
if ($ExpectedPackageSha256) {
    $actualPackageHash = Get-Sha256Hex $PackagePath
    if ($actualPackageHash -ne $ExpectedPackageSha256.Trim().ToLowerInvariant()) {
        throw '更新包总 SHA256 与可信校验值不一致。'
    }
}

$packageRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
    'shulian-update-' + [Guid]::NewGuid().ToString('N')
)
try {
    Expand-Archive -LiteralPath $PackagePath -DestinationPath $packageRoot
    $manifestPath = Join-Path $packageRoot 'release-manifest.json'
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        throw '更新包缺少 release-manifest.json。'
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 |
        ConvertFrom-Json
    $payloadRoot = Test-PackagePayload $packageRoot $manifest
    $current = Read-ReleaseIdentity $AppDir
    if (-not $AllowDowngrade -and
        (Compare-SemVer ([string]$manifest.version) ([string]$current.version)) -le 0) {
        throw "目标版本 $($manifest.version) 不高于当前版本 $($current.version)。"
    }

    if (-not $SkipProcessControl) { Stop-Shulian $AppDir }
    $backupRoot = New-Backup $AppDir $backupsRoot 'before-update'
    $stage = New-Stage $payloadRoot $AppDir
    Switch-ManagedPayload $stage $AppDir
    if (-not $SkipProcessControl) {
        [void](Refresh-ShulianDesktopShortcut $AppDir)
    }

    if (-not $NoLaunch) {
        Start-Shulian $AppDir
        if (-not (Wait-ForHealthyBuild ([string]$manifest.buildId))) {
            Stop-Shulian $AppDir
            $rollbackStage = New-Stage (Join-Path $backupRoot 'payload') $AppDir
            Switch-ManagedPayload $rollbackStage $AppDir
            Start-Shulian $AppDir
            throw (
                '新版启动健康检查失败，已自动恢复上一版本。' +
                " 自检详情：$script:LastHealthFailure"
            )
        }
    }

    Write-Utf8Json (Join-Path $updatesRoot 'installed.json') ([ordered]@{
        schemaVersion = 1
        updaterVersion = $UpdaterVersion
        installedAt = [DateTime]::UtcNow.ToString('o')
        version = [string]$manifest.version
        buildId = [string]$manifest.buildId
        backupId = Split-Path -Leaf $backupRoot
    })

    $oldBackups = @(
        Get-ChildItem -LiteralPath $backupsRoot -Directory |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -Skip 3
    )
    foreach ($oldBackup in $oldBackups) {
        $resolved = Resolve-FullPath $oldBackup.FullName
        $backupPrefix = (Resolve-FullPath $backupsRoot).TrimEnd(
            [char[]]@(92, 47)
        ) +
            [System.IO.Path]::DirectorySeparatorChar
        if ($resolved.StartsWith($backupPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolved -Recurse -Force
        }
    }

    [pscustomobject]@{
        ok = $true
        action = 'install'
        version = [string]$manifest.version
        buildId = [string]$manifest.buildId
        backupId = Split-Path -Leaf $backupRoot
    } | ConvertTo-Json
}
finally {
    if (Test-Path -LiteralPath $packageRoot) {
        Remove-Item -LiteralPath $packageRoot -Recurse -Force
    }
}
