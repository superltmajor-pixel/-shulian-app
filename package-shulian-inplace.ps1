param(
    [string]$ProgressPath = '',
    [switch]$LaunchedByApp,
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $scriptDir 'packager.local.json'
if (-not (Test-Path -LiteralPath $configPath) -and
    (Test-Path -LiteralPath (Join-Path $scriptDir 'desktop.py'))) {
    $configPath = Join-Path (Split-Path -Parent $scriptDir) 'packager.local.json'
}
$repo = [string]$env:SHULIAN_REPO
$appDir = [string]$env:SHULIAN_APP_DIR

if (Test-Path -LiteralPath $configPath) {
    $localConfig = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 |
        ConvertFrom-Json
    if ([string]::IsNullOrWhiteSpace($repo)) {
        $repo = [string]$localConfig.repo
    }
    if ([string]::IsNullOrWhiteSpace($appDir)) {
        $appDir = [string]$localConfig.appDir
    }
}

if ([string]::IsNullOrWhiteSpace($repo) -and
    (Test-Path -LiteralPath (Join-Path $scriptDir 'desktop.py'))) {
    $repo = $scriptDir
}
if ([string]::IsNullOrWhiteSpace($appDir) -and
    (Test-Path -LiteralPath (Join-Path $scriptDir 'dist\Shulian.exe'))) {
    $appDir = Join-Path $scriptDir 'dist'
}
if ([string]::IsNullOrWhiteSpace($repo) -or
    [string]::IsNullOrWhiteSpace($appDir)) {
    throw '缺少打包路径。请复制 packager.local.example.json 为 packager.local.json，或设置 SHULIAN_REPO 与 SHULIAN_APP_DIR。'
}

$repo = [System.IO.Path]::GetFullPath($repo)
$appDir = [System.IO.Path]::GetFullPath($appDir)
$python = Join-Path $repo 'venv\Scripts\python.exe'
$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
$npm = if ($npmCommand) { [string]$npmCommand.Source } else { '' }
$frontendPackage = Join-Path $repo 'package.json'
$frontendLock = Join-Path $repo 'package-lock.json'
$frontendVite = Join-Path $repo 'node_modules\vite\package.json'
$spec = Join-Path $repo 'shulian-onedir.spec'
$releaseBuilder = Join-Path $repo 'scripts\build-release-package.ps1'
$releaseMetadata = Join-Path $repo 'release.json'
$releaseUpdater = Join-Path $repo 'packaging\updater\ShulianUpdater.ps1'
$rollbackLauncher = Join-Path $repo 'packaging\updater\回滚数恋到上一版本.bat'
$uninstaller = Join-Path $repo 'packaging\uninstaller\ShulianUninstaller.ps1'
$targetExe = Join-Path $appDir 'Shulian.exe'
$releaseToolsDir = Split-Path -Parent $appDir
$publishedUpdater = Join-Path $releaseToolsDir 'ShulianUpdater.ps1'
$publishedRollbackLauncher = Join-Path $releaseToolsDir '回滚数恋到上一版本.bat'
$releaseOutputDir = Join-Path $releaseToolsDir 'release'
$cacheRoot = Join-Path $env:LOCALAPPDATA 'ShulianPackager'
$workPath = Join-Path $cacheRoot 'build'
$distPath = Join-Path $cacheRoot 'dist'
$builtDir = Join-Path $distPath 'Shulian'
$builtWebRoot = Join-Path $builtDir '_internal\web'
$backupFilePattern = '(\.before-|\.bak\d*|\.bak-|\.tmp|\.orig|~$)'
$expectedBuildId = '2026-10-03-public-portable-v26-0'
$startedAt = Get-Date

function Write-UpdateProgress(
    [int]$Percent,
    [string]$Stage,
    [string]$Message,
    [string]$Status = 'running'
) {
    if ([string]::IsNullOrWhiteSpace($ProgressPath)) { return }
    $directory = Split-Path -Parent $ProgressPath
    if (-not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    $sourceIdentity = if (Test-Path -LiteralPath $releaseMetadata) {
        Get-Content -LiteralPath $releaseMetadata -Raw -Encoding UTF8 | ConvertFrom-Json
    } else { $null }
    $clientMetadata = Join-Path $appDir '_internal\release.json'
    $clientIdentity = if (Test-Path -LiteralPath $clientMetadata) {
        Get-Content -LiteralPath $clientMetadata -Raw -Encoding UTF8 | ConvertFrom-Json
    } else { $null }
    $payload = [ordered]@{
        schemaVersion = 1
        productId = 'shulian'
        status = $Status
        percent = [math]::Max(0, [math]::Min(100, $Percent))
        stage = $Stage
        message = $Message
        processId = $PID
        sourceVersion = [string]$sourceIdentity.version
        sourceBuildId = [string]$sourceIdentity.buildId
        clientVersion = [string]$clientIdentity.version
        clientBuildId = [string]$clientIdentity.buildId
        updatedAt = [DateTimeOffset]::Now.ToUnixTimeSeconds()
    }
    $temporary = Join-Path $directory ('.update-progress-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($temporary, ($payload | ConvertTo-Json -Depth 5), $utf8WithoutBom)
    Move-Item -LiteralPath $temporary -Destination $ProgressPath -Force
}

function Measure-Files([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return [pscustomobject]@{ Count = 0; Bytes = 0 }
    }
    $result = Get-ChildItem -LiteralPath $Path -Recurse -File -Force -ErrorAction SilentlyContinue |
        Measure-Object Length -Sum
    return [pscustomobject]@{ Count = $result.Count; Bytes = [int64]$result.Sum }
}

function Get-BackupFileHits([string]$Root) {
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        return @()
    }
    return @(
        Get-ChildItem -LiteralPath $Root -Recurse -File -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match $backupFilePattern }
    )
}

function Test-BackupFileAbsent([string]$WebRoot) {
    $hits = @(Get-BackupFileHits $WebRoot)
    return ($hits.Count -eq 0)
}

function Assert-BackupFileAbsent([string]$WebRoot, [string]$Label) {
    $hits = @(Get-BackupFileHits $WebRoot)
    if ($hits.Count -eq 0) {
        return
    }
    $sample = (@($hits | Select-Object -First 10 | ForEach-Object { $_.FullName }) -join '; ')
    throw "$Label 仍包含备份/临时文件，拒绝发布：$sample"
}

function Get-TargetClientProcesses {
    $expectedPath = [System.IO.Path]::GetFullPath($targetExe)
    $matches = @()
    foreach ($process in @(Get-Process -Name 'Shulian' -ErrorAction SilentlyContinue)) {
        try {
            $processPath = [System.IO.Path]::GetFullPath([string]$process.Path)
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

function Wait-TargetClientExit([int]$TimeoutSeconds) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        if (@(Get-TargetClientProcesses).Count -eq 0) {
            return $true
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    return $false
}

function Stop-TargetClient {
    $running = @(Get-TargetClientProcesses)
    foreach ($process in $running) {
        try { [void]$process.CloseMainWindow() } catch { }
    }
    if ($running.Count -gt 0 -and (Wait-TargetClientExit 8)) {
        return
    }

    $remaining = @(Get-TargetClientProcesses)
    foreach ($process in $remaining) {
        try { Stop-Process -Id $process.Id -Force -ErrorAction Stop } catch { }
    }
    if (-not (Wait-TargetClientExit 8)) {
        $remainingIds = @(
            Get-TargetClientProcesses | ForEach-Object { [string]$_.Id }
        ) -join ', '
        throw "旧数恋进程没有完全退出，已停止更新。进程号：$remainingIds"
    }
}

function Write-EnvironmentFileAtomic([string]$Path, [string[]]$Lines) {
    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }

    $temporary = Join-Path $directory ('.env.shulian-migrate-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    $backup = Join-Path $directory ('.env.shulian-migrate-' + [Guid]::NewGuid().ToString('N') + '.bak')
    try {
        $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllLines($temporary, $Lines, $utf8WithoutBom)
        if (Test-Path -LiteralPath $Path) {
            [System.IO.File]::Replace($temporary, $Path, $backup, $true)
        }
        else {
            [System.IO.File]::Move($temporary, $Path)
        }
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
        if (Test-Path -LiteralPath $backup) {
            Remove-Item -LiteralPath $backup -Force
        }
    }
}

function Remove-LegacyDeepSeekKey([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return $false
    }

    [string[]]$originalLines = [System.IO.File]::ReadAllLines($Path)
    [string[]]$safeLines = @($originalLines | Where-Object {
        $_ -notmatch '^\s*(?:export\s+)?DEEPSEEK_API_KEY\s*='
    })
    if ($safeLines.Count -eq $originalLines.Count) {
        return $false
    }

    Write-EnvironmentFileAtomic $Path $safeLines
    return $true
}

function Move-LegacyEnvironmentSettings([string]$BundledPath, [string]$RootPath) {
    if (-not (Test-Path -LiteralPath $BundledPath)) {
        return 0
    }

    [string[]]$bundledLines = [System.IO.File]::ReadAllLines($BundledPath)
    [string[]]$safeBundledLines = @($bundledLines | Where-Object {
        $_ -notmatch '^\s*(?:export\s+)?DEEPSEEK_API_KEY\s*='
    })
    [string[]]$rootLines = if (Test-Path -LiteralPath $RootPath) {
        @([System.IO.File]::ReadAllLines($RootPath) | Where-Object {
            $_ -notmatch '^\s*(?:export\s+)?DEEPSEEK_API_KEY\s*='
        })
    }
    else {
        @()
    }

    $knownNames = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($line in $rootLines) {
        if ($line -match '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=') {
            [void]$knownNames.Add($Matches[1])
        }
    }

    $merged = [System.Collections.Generic.List[string]]::new()
    foreach ($line in $rootLines) {
        $merged.Add($line)
    }
    $migrated = 0
    foreach ($line in $safeBundledLines) {
        if ($line -notmatch '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=') {
            continue
        }
        $name = $Matches[1]
        if ($knownNames.Add($name)) {
            $merged.Add($line)
            $migrated += 1
        }
    }

    if ($merged.Count -gt 0 -and ($migrated -gt 0 -or -not (Test-Path -LiteralPath $RootPath))) {
        Write-EnvironmentFileAtomic $RootPath $merged.ToArray()
    }
    Remove-Item -LiteralPath $BundledPath -Force
    return $migrated
}

try {
    Write-UpdateProgress 3 'checking' '正在核对源码、客户端与构建环境。'
    Write-Host '============================================' -ForegroundColor Cyan
    Write-Host '  数恋 APP：一键重新打包并更新现用客户端' -ForegroundColor Cyan
    Write-Host '============================================' -ForegroundColor Cyan

    if ([string]::IsNullOrWhiteSpace($npm)) {
        throw '缺少 npm.cmd。请先安装 Node.js 24，再重新运行打包。'
    }
    foreach ($required in @(
        $repo,
        $appDir,
        $python,
        $npm,
        $frontendPackage,
        $frontendLock,
        $frontendVite,
        $spec,
        $releaseBuilder,
        $releaseMetadata,
            $releaseUpdater,
            $rollbackLauncher,
            $uninstaller,
            $targetExe
    )) {
        if (-not (Test-Path -LiteralPath $required)) {
            throw "缺少必要路径：$required"
        }
    }

    if ($ValidateOnly -or $env:SHULIAN_PACKAGER_VALIDATE_ONLY -eq '1') {
        $backupGate = [ordered]@{
            path = $builtWebRoot
            checked = $false
            passed = $true
            hitCount = 0
        }
        if (Test-Path -LiteralPath $builtWebRoot -PathType Container) {
            $backupHits = @(Get-BackupFileHits $builtWebRoot)
            $backupGate.checked = $true
            $backupGate.passed = Test-BackupFileAbsent $builtWebRoot
            $backupGate.hitCount = $backupHits.Count
            Assert-BackupFileAbsent $builtWebRoot '现有构建缓存'
        }
        [pscustomobject]@{
            repo = $repo
            appDir = $appDir
            python = $python
            npm = $npm
            frontendPackage = $frontendPackage
            frontendLock = $frontendLock
            spec = $spec
            releaseBuilder = $releaseBuilder
            releaseMetadata = $releaseMetadata
            releaseUpdater = $releaseUpdater
            rollbackLauncher = $rollbackLauncher
            uninstaller = $uninstaller
            releaseOutputDir = $releaseOutputDir
            targetExe = $targetExe
            backupFilePattern = $backupFilePattern
            backupGate = [pscustomobject]$backupGate
        } | ConvertTo-Json
        return
    }

    Write-UpdateProgress 8 'validated' '构建环境检查完成。'
    & $python -c "import numpy, sherpa_onnx; assert callable(getattr(sherpa_onnx.OnlineRecognizer, 'from_transducer', None))"
    if ($LASTEXITCODE -ne 0) {
        throw '打包环境缺少本地语音识别依赖。请先用正式版源码 venv 安装 requirements.txt，再重试更新。'
    }

    New-Item -ItemType Directory -Path $workPath -Force | Out-Null
    New-Item -ItemType Directory -Path $distPath -Force | Out-Null

    Write-Host ''
    Write-Host '[1/5] 正在构建离线前端并重新打包，请耐心等待……' -ForegroundColor Yellow
    Write-UpdateProgress 12 'frontend' '正在构建离线前端。'
    Push-Location $repo
    try {
        Write-UpdateProgress 10 'quality' '正在运行离线回归检查。'
        & $python (Join-Path $repo 'scripts\check-quality.py')
        if ($LASTEXITCODE -ne 0) {
            throw "离线回归检查失败，停止打包。退出码：$LASTEXITCODE"
        }
        & $npm run build:web
        if ($LASTEXITCODE -ne 0) {
            throw "Vite 前端构建失败，退出码：$LASTEXITCODE"
        }
        & $npm run check:web
        if ($LASTEXITCODE -ne 0) {
            throw "Vite 前端产物校验失败，退出码：$LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
    Write-UpdateProgress 22 'packaging' '前端构建完成，正在生成桌面程序。'
    & $python (Join-Path $repo 'scripts\write-maintenance-manifest.py')
    if ($LASTEXITCODE -ne 0) {
        throw "源码维护清单生成失败，退出码：$LASTEXITCODE"
    }
    & $python -m PyInstaller `
        --noconfirm `
        --distpath $distPath `
        --workpath $workPath `
        $spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller 打包失败，退出码：$LASTEXITCODE"
    }
    Write-UpdateProgress 64 'verifying' '桌面程序已生成，正在校验资源和发布身份。'

    $builtExe = Join-Path $builtDir 'Shulian.exe'
    $builtIndex = Join-Path $builtDir '_internal\web\index.html'
    $builtApp = Join-Path $builtDir '_internal\web\app.jsx'
    $builtScreens = Join-Path $builtDir '_internal\web\screens.jsx'
    $builtGlass = Join-Path $builtDir '_internal\web\glass.jsx'
    $builtWebBundle = Join-Path $builtDir '_internal\web\bundle\app.bundle.js'
    $builtWebManifest = Join-Path $builtDir '_internal\web\bundle\manifest.json'
    $builtRelease = Join-Path $builtDir '_internal\release.json'
    $builtUninstaller = Join-Path $builtDir '_internal\packaging\uninstaller\ShulianUninstaller.ps1'
    $builtBundledEnv = Join-Path $builtDir '_internal\.env'
    $builtRootEnv = Join-Path $builtDir '.env'
    foreach ($required in @(
        $builtExe,
        $builtIndex,
        $builtApp,
        $builtScreens,
        $builtGlass,
        $builtWebBundle,
        $builtWebManifest,
        $builtRelease,
        $builtUninstaller
    )) {
        if (-not (Test-Path -LiteralPath $required)) {
            throw "打包产物不完整：$required"
        }
    }
    if (-not (Select-String -LiteralPath $builtApp -SimpleMatch $expectedBuildId -Quiet)) {
        throw "打包产物不是本次新版前端：缺少构建标识 $expectedBuildId"
    }
    Assert-BackupFileAbsent $builtWebRoot '打包产物'
    $builtWebIdentity = Get-Content -LiteralPath $builtWebManifest -Raw -Encoding UTF8 |
        ConvertFrom-Json
    if ($builtWebIdentity.tool -ne 'vite' -or
        $builtWebIdentity.buildId -ne $expectedBuildId -or
        [string]::IsNullOrWhiteSpace([string]$builtWebIdentity.bundleSha256)) {
        throw '打包产物的 Vite 前端清单无效或已经过期。'
    }
    if ((Test-Path -LiteralPath $builtBundledEnv) -or (Test-Path -LiteralPath $builtRootEnv)) {
        throw '打包产物仍包含 .env，已停止更新以避免泄露 API Key。'
    }
    if (-not (Select-String -LiteralPath $builtApp -SimpleMatch 'function ApiKeyGate' -Quiet) -or
        -not (Select-String -LiteralPath $builtApp -SimpleMatch 'function MainApp' -Quiet) -or
        -not (Select-String -LiteralPath $builtApp -SimpleMatch '/api/ai-config' -Quiet) -or
        -not (Select-String -LiteralPath $builtScreens -SimpleMatch 'function AiServiceScreen' -Quiet)) {
        throw '打包产物缺少 API Key 首次连接门禁或 AI 服务设置页。'
    }
    if (-not (Select-String -LiteralPath $builtScreens -SimpleMatch 'function LoverArchiveScreen' -Quiet) -or
        -not (Select-String -LiteralPath $builtScreens -SimpleMatch 'function ProfileScreen' -Quiet) -or
        -not (Select-String -LiteralPath $builtScreens -SimpleMatch 'function SettingsScreen' -Quiet) -or
        (Select-String -LiteralPath $builtScreens -SimpleMatch '默认头像颜色' -Quiet) -or
        (Select-String -LiteralPath $builtIndex -SimpleMatch '.profile-color-' -Quiet)) {
        throw '打包产物缺少新版“我的资料”或“设置”页面。'
    }
    if (-not (Select-String -LiteralPath $builtIndex -SimpleMatch "bundle/app.bundle.js?v=$expectedBuildId" -Quiet) -or
        (Select-String -LiteralPath $builtIndex -SimpleMatch 'text/babel' -Quiet) -or
        (Select-String -LiteralPath $builtIndex -SimpleMatch 'unpkg.com' -Quiet)) {
        throw '打包产物 index.html 没有切换到本地 Vite bundle。'
    }

    Write-Host '[2/5] 正在生成可校验 Release 更新包……' -ForegroundColor Yellow
    Write-UpdateProgress 72 'release' '正在生成带校验清单的更新包。'
    $releaseResultText = & $releaseBuilder `
        -BuiltAppDir $builtDir `
        -OutputDir $releaseOutputDir |
        Out-String
    $releaseResult = $releaseResultText | ConvertFrom-Json
    if (-not $releaseResult.ok -or
        [string]$releaseResult.buildId -ne $expectedBuildId) {
        throw 'Release 更新包生成后身份校验失败。'
    }
    Copy-Item -LiteralPath $releaseUpdater -Destination $publishedUpdater -Force
    Copy-Item -LiteralPath $rollbackLauncher `
        -Destination $publishedRollbackLauncher `
        -Force
    Write-UpdateProgress 82 'ready' '更新包已就绪，正在准备安全切换。'

    # 默认使用独立更新器完成备份、切换、健康检查和自动回滚。
    # 只有显式设置此环境变量时才进入下方保留的旧原位更新流程。
    if ($env:SHULIAN_LEGACY_INPLACE_UPDATE -ne '1') {
        Write-Host '[3/5] 正在准备安全更新并迁移旧配置……' -ForegroundColor Yellow
        Write-UpdateProgress 86 'restarting' '即将关闭当前窗口并切换到新版本。' 'restarting'
        Stop-TargetClient

        $storage = Join-Path $appDir 'webview-data\EBWebView\Default\Local Storage'
        $before = Measure-Files $storage
        $targetBundledEnv = Join-Path $appDir '_internal\.env'
        $targetRootEnv = Join-Path $appDir '.env'
        $legacyKeyRemoved = Remove-LegacyDeepSeekKey $targetRootEnv
        $legacySettingsMigrated = Move-LegacyEnvironmentSettings `
            $targetBundledEnv `
            $targetRootEnv
        if (Test-Path -LiteralPath $targetBundledEnv) {
            throw '旧客户端 _internal\.env 无法删除，已停止更新。'
        }
        if ((Test-Path -LiteralPath $targetRootEnv) -and
            (Select-String -LiteralPath $targetRootEnv `
                -Pattern '^\s*(?:export\s+)?DEEPSEEK_API_KEY\s*=' -Quiet)) {
            throw '旧客户端根目录 .env 中的明文 API Key 未能安全移除。'
        }

        Write-Host '[4/5] 独立更新器正在建立回滚点并切换程序……' -ForegroundColor Yellow
        $updaterOutput = & powershell.exe `
            -NoProfile `
            -ExecutionPolicy Bypass `
            -File $releaseUpdater `
            -PackagePath ([string]$releaseResult.archive) `
            -ExpectedPackageSha256 ([string]$releaseResult.sha256) `
            -AppDir $appDir `
            -AllowDowngrade 2>&1 |
            Out-String
        if ($LASTEXITCODE -ne 0) {
            throw "独立更新器失败：$updaterOutput"
        }
        Write-UpdateProgress 98 'health-check' '新版已启动，正在完成健康检查。' 'restarting'

        $after = Measure-Files $storage
        # 独立更新器会启动新版执行健康检查。WebView 启动后会正常滚动、
        # 压缩 LevelDB 文件，因此文件数和总字节数不保证逐字节不变。
        # 更新器只切换 Shulian.exe/_internal，并明确保护 webview-data；
        # 此处仅拦截原本存在的 Local Storage 整体消失或变空。
        if ($before.Count -gt 0 -and
            ($after.Count -eq 0 -or $after.Bytes -eq 0)) {
            throw "用户数据校验失败：更新前 $($before.Count) 个文件/$($before.Bytes) 字节，更新后 Local Storage 为空"
        }
        if ($before.Count -ne $after.Count -or $before.Bytes -ne $after.Bytes) {
            Write-Host (
                "用户数据存储已由新版正常维护：更新前 " +
                "$($before.Count) 个文件/$($before.Bytes) 字节，更新后 " +
                "$($after.Count) 个文件/$($after.Bytes) 字节"
            ) -ForegroundColor DarkGray
        }

        # 旧版本的重复 web 目录不参与更新；新版健康检查成功后再安全清理。
        $legacyWeb = Join-Path $appDir 'web'
        if (Test-Path -LiteralPath $legacyWeb) {
            $resolvedLegacyWeb = [System.IO.Path]::GetFullPath($legacyWeb)
            $resolvedAppDir = [System.IO.Path]::GetFullPath($appDir).TrimEnd('\')
            if ([System.IO.Path]::GetDirectoryName($resolvedLegacyWeb).TrimEnd('\') -ne $resolvedAppDir -or
                [System.IO.Path]::GetFileName($resolvedLegacyWeb) -ne 'web') {
                throw "拒绝清理未验证的旧资源目录：$resolvedLegacyWeb"
            }
            Remove-Item -LiteralPath $resolvedLegacyWeb -Recurse -Force
        }

        Write-Host '[5/5] 更新与新版健康检查完成。' -ForegroundColor Yellow
        $elapsed = [math]::Round(((Get-Date) - $startedAt).TotalMinutes, 1)
        Write-Host ''
        Write-Host '更新成功，已建立自动回滚点。' -ForegroundColor Green
        Write-Host "EXE：$targetExe"
        Write-Host "Release：$($releaseResult.archive)"
        Write-Host "SHA256：$($releaseResult.sha256)"
        Write-Host "历史会话/好感度/默契值：已保留（$($after.Count) 个 Local Storage 文件）"
        Write-Host "耗时：$elapsed 分钟"
        Write-UpdateProgress 100 'completed' '更新完成，当前已是新版本。' 'completed'
        exit 0
    }

    Write-Host '警告：已显式启用旧原位更新流程，不提供自动回滚。' -ForegroundColor Yellow
    Write-Host '[3/5] 打包成功，正在关闭旧客户端……' -ForegroundColor Yellow
    Stop-TargetClient

    $storage = Join-Path $appDir 'webview-data\EBWebView\Default\Local Storage'
    $before = Measure-Files $storage

    Write-Host '[4/5] 正在覆盖程序文件（用户数据不会被替换）……' -ForegroundColor Yellow
    $targetBundledEnv = Join-Path $appDir '_internal\.env'
    $targetRootEnv = Join-Path $appDir '.env'
    Copy-Item -LiteralPath $builtExe -Destination $targetExe -Force
    Copy-Item -Path (Join-Path $builtDir '_internal\*') -Destination (Join-Path $appDir '_internal') -Recurse -Force

    $after = Measure-Files $storage
    if ($before.Count -ne $after.Count -or $before.Bytes -ne $after.Bytes) {
        throw "用户数据校验失败：更新前 $($before.Count) 个文件/$($before.Bytes) 字节，更新后 $($after.Count) 个文件/$($after.Bytes) 字节"
    }

    $sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $builtExe).Hash
    $targetHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $targetExe).Hash
    if ($sourceHash -ne $targetHash) {
        throw 'EXE 覆盖后的哈希与构建产物不一致。'
    }
    $targetApp = Join-Path $appDir '_internal\web\app.jsx'
    $targetScreens = Join-Path $appDir '_internal\web\screens.jsx'
    $targetGlass = Join-Path $appDir '_internal\web\glass.jsx'
    $targetIndex = Join-Path $appDir '_internal\web\index.html'
    $targetWebBundle = Join-Path $appDir '_internal\web\bundle\app.bundle.js'
    $targetWebManifest = Join-Path $appDir '_internal\web\bundle\manifest.json'
    if (-not (Select-String -LiteralPath $targetApp -SimpleMatch $expectedBuildId -Quiet)) {
        throw "现用客户端 web 目录没有收到新版前端：$expectedBuildId"
    }
    if (-not (Test-Path -LiteralPath $targetWebBundle) -or
        -not (Test-Path -LiteralPath $targetWebManifest)) {
        throw '现用客户端缺少 Vite 前端 bundle 或构建清单。'
    }
    $targetWebIdentity = Get-Content -LiteralPath $targetWebManifest -Raw -Encoding UTF8 |
        ConvertFrom-Json
    if (-not (Select-String -LiteralPath $targetApp -SimpleMatch 'function ApiKeyGate' -Quiet) -or
        -not (Select-String -LiteralPath $targetApp -SimpleMatch 'function MainApp' -Quiet) -or
        -not (Select-String -LiteralPath $targetApp -SimpleMatch '/api/ai-config' -Quiet) -or
        -not (Select-String -LiteralPath $targetScreens -SimpleMatch 'function AiServiceScreen' -Quiet) -or
        -not (Select-String -LiteralPath $targetScreens -SimpleMatch 'function LoverArchiveScreen' -Quiet) -or
        -not (Select-String -LiteralPath $targetScreens -SimpleMatch 'function ProfileScreen' -Quiet) -or
        -not (Select-String -LiteralPath $targetScreens -SimpleMatch 'function SettingsScreen' -Quiet) -or
        (Select-String -LiteralPath $targetScreens -SimpleMatch '默认头像颜色' -Quiet) -or
        (Select-String -LiteralPath $targetIndex -SimpleMatch '.profile-color-' -Quiet) -or
        -not (Select-String -LiteralPath $targetGlass -SimpleMatch 'aria-current={on ? ''page'' : undefined}' -Quiet) -or
        -not (Select-String -LiteralPath $targetIndex -SimpleMatch "bundle/app.bundle.js?v=$expectedBuildId" -Quiet) -or
        $targetWebIdentity.tool -ne 'vite' -or
        $targetWebIdentity.buildId -ne $expectedBuildId) {
        throw '现用客户端 web 目录没有收到 API Key 门禁、账户页面、侧栏或缓存入口。'
    }

    # 旧版曾额外复制一份 appDir\web，但当前 EXE 只从 _internal\web 提供资源。
    # 校验新版内部资源后再删除重复副本，且严格验证目标就是应用目录的直接子目录。
    $legacyWeb = Join-Path $appDir 'web'
    if (Test-Path -LiteralPath $legacyWeb) {
        $resolvedLegacyWeb = [System.IO.Path]::GetFullPath($legacyWeb)
        $resolvedAppDir = [System.IO.Path]::GetFullPath($appDir).TrimEnd('\')
        if ([System.IO.Path]::GetDirectoryName($resolvedLegacyWeb).TrimEnd('\') -ne $resolvedAppDir -or
            [System.IO.Path]::GetFileName($resolvedLegacyWeb) -ne 'web') {
            throw "拒绝清理未验证的旧资源目录：$resolvedLegacyWeb"
        }
        Remove-Item -LiteralPath $resolvedLegacyWeb -Recurse -Force
    }

    # 新程序与前端校验通过后再迁移旧配置：先保留非敏感 TTS 设置，再移除旧明文凭据。
    $legacyKeyRemoved = Remove-LegacyDeepSeekKey $targetRootEnv
    $legacySettingsMigrated = Move-LegacyEnvironmentSettings $targetBundledEnv $targetRootEnv
    if (Test-Path -LiteralPath $targetBundledEnv) {
        throw '旧客户端 _internal\.env 无法删除，已停止更新以避免继续携带明文 API Key。'
    }
    if ((Test-Path -LiteralPath $targetRootEnv) -and
        (Select-String -LiteralPath $targetRootEnv -Pattern '^\s*(?:export\s+)?DEEPSEEK_API_KEY\s*=' -Quiet)) {
        throw '旧客户端根目录 .env 中的 DEEPSEEK_API_KEY 未能安全移除。'
    }
    if ($legacySettingsMigrated -gt 0) {
        Write-Host "已从旧 _internal\.env 迁移 $legacySettingsMigrated 项非敏感配置。" -ForegroundColor DarkGray
    }
    if ($legacyKeyRemoved) {
        Write-Host '已从旧 .env 原子移除 DEEPSEEK_API_KEY；TTS 等其他配置已保留。' -ForegroundColor DarkGray
    }

    Write-Host '[5/5] 更新完成，正在重新打开数恋 APP……' -ForegroundColor Yellow
    Start-Process -FilePath $targetExe -WorkingDirectory $appDir | Out-Null

    $servedNewBuild = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $request = [System.Net.HttpWebRequest]::Create("http://127.0.0.1:8770/app.jsx?build=$expectedBuildId")
            $request.Proxy = $null
            $request.Timeout = 1500
            $response = $request.GetResponse()
            $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
            $servedText = $reader.ReadToEnd()
            $reader.Dispose()
            $response.Dispose()
            $screensRequest = [System.Net.HttpWebRequest]::Create("http://127.0.0.1:8770/screens.jsx?build=$expectedBuildId")
            $screensRequest.Proxy = $null
            $screensRequest.Timeout = 1500
            $screensResponse = $screensRequest.GetResponse()
            $screensReader = New-Object System.IO.StreamReader($screensResponse.GetResponseStream())
            $servedScreens = $screensReader.ReadToEnd()
            $screensReader.Dispose()
            $screensResponse.Dispose()
            $glassRequest = [System.Net.HttpWebRequest]::Create("http://127.0.0.1:8770/glass.jsx?build=$expectedBuildId")
            $glassRequest.Proxy = $null
            $glassRequest.Timeout = 1500
            $glassResponse = $glassRequest.GetResponse()
            $glassReader = New-Object System.IO.StreamReader($glassResponse.GetResponseStream())
            $servedGlass = $glassReader.ReadToEnd()
            $glassReader.Dispose()
            $glassResponse.Dispose()
            $indexRequest = [System.Net.HttpWebRequest]::Create("http://127.0.0.1:8770/?build=$expectedBuildId")
            $indexRequest.Proxy = $null
            $indexRequest.Timeout = 1500
            $indexResponse = $indexRequest.GetResponse()
            $indexReader = New-Object System.IO.StreamReader($indexResponse.GetResponseStream())
            $servedIndex = $indexReader.ReadToEnd()
            $indexReader.Dispose()
            $indexResponse.Dispose()
            $schemaRequest = [System.Net.HttpWebRequest]::Create('http://127.0.0.1:8770/openapi.json')
            $schemaRequest.Proxy = $null
            $schemaRequest.Timeout = 1500
            $schemaResponse = $schemaRequest.GetResponse()
            $schemaReader = New-Object System.IO.StreamReader($schemaResponse.GetResponseStream())
            $servedSchemaText = $schemaReader.ReadToEnd()
            $schemaReader.Dispose()
            $schemaResponse.Dispose()
            $servedSchema = $servedSchemaText | ConvertFrom-Json
            $aiConfigPath = $servedSchema.paths.'/api/ai-config'
            $aiConfigMethods = @($aiConfigPath.PSObject.Properties.Name)
            if ($servedText.Contains($expectedBuildId) -and
                $servedText.Contains('function ApiKeyGate') -and
                $servedText.Contains('function MainApp') -and
                $servedText.Contains('/api/ai-config') -and
                $servedScreens.Contains('function AiServiceScreen') -and
                $servedScreens.Contains('function LoverArchiveScreen') -and
                $servedScreens.Contains('function ProfileScreen') -and
                $servedScreens.Contains('function SettingsScreen') -and
                -not $servedScreens.Contains('默认头像颜色') -and
                -not $servedIndex.Contains('.profile-color-') -and
                $servedGlass.Contains("aria-current={on ? 'page' : undefined}") -and
                $servedIndex.Contains("bundle/app.bundle.js?v=$expectedBuildId") -and
                -not $servedIndex.Contains('text/babel') -and
                -not $servedIndex.Contains('unpkg.com') -and
                $aiConfigMethods -contains 'get' -and
                $aiConfigMethods -contains 'put' -and
                $aiConfigMethods -contains 'delete') {
                $servedNewBuild = $true
                break
            }
        } catch { }
    }
    if (-not $servedNewBuild) {
        throw "客户端已启动，但 8770 实际返回的不是新版页面：$expectedBuildId"
    }

    $elapsed = [math]::Round(((Get-Date) - $startedAt).TotalMinutes, 1)
    Write-Host ''
    Write-Host '更新成功。' -ForegroundColor Green
    Write-Host "EXE：$targetExe"
    Write-Host "Release：$($releaseResult.archive)"
    Write-Host "SHA256：$($releaseResult.sha256)"
    Write-Host "历史会话/好感度/默契值：已保留（$($after.Count) 个 Local Storage 文件）"
    Write-Host "耗时：$elapsed 分钟"
    Write-UpdateProgress 100 'completed' '更新完成，当前已是新版本。' 'completed'
    exit 0
}
catch {
    $failureMessage = $_.Exception.Message
    try { Write-UpdateProgress 0 'failed' ("更新失败：" + $failureMessage) 'failed' } catch { }
    Write-Host ''
    Write-Host '更新失败：' -ForegroundColor Red
    Write-Host $failureMessage -ForegroundColor Red
    Write-Host '用户数据未被删除；若已进入安全迁移阶段，旧明文 API Key 可能已移除。' -ForegroundColor Yellow
    exit 1
}
