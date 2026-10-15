$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Spec = Join-Path $Root 'VideoCongThuc.spec'
$Dist = Join-Path $Root 'dist'
$Package = Join-Path $Dist 'VideoCongThuc'
$Archive = Join-Path $Dist 'VideoCongThuc.zip'
$InstallerScript = Join-Path $Root 'installer\VideoCongThuc.iss'
$Setup = Join-Path $Dist 'VideoCongThuc-Setup.exe'
# Published SHA256: https://api.github.com/repos/GyanD/codexffmpeg/releases/tags/9.0.2
$FfmpegVersion = '9.0.2'
$FfmpegSha256 = '60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba'
$FfmpegUrl = "https://github.com/GyanD/codexffmpeg/releases/download/$FfmpegVersion/ffmpeg-$FfmpegVersion-essentials_build.zip"
$FfmpegCache = Join-Path $Root 'build\ffmpeg-cache'
$FfmpegZip = Join-Path $FfmpegCache "ffmpeg-$FfmpegVersion-essentials_build.zip"
$FfmpegExe = Join-Path $FfmpegCache "ffmpeg-$FfmpegVersion.exe"
$Templates = @(
    'settings.json', 'channels.txt', 'taxonomy.json', 'taxonomy.default.json', 'selectors.json',
    'graphql_paths.json', 'keyterms.txt', 'ban_words.txt'
)
$Documents = @('THIRD_PARTY_NOTICES.txt', 'docs\HUONG-DAN.md')
$Pdf = Join-Path $Root 'docs\HUONG-DAN.pdf'

foreach ($Required in (@($Python, $Spec, $InstallerScript, $Pdf, (Join-Path $Root 'backend\main.py'), (Join-Path $Root 'frontend\index.html')) +
        @($Templates | ForEach-Object { Join-Path $Root "config\$_" }) +
        @($Documents | ForEach-Object { Join-Path $Root $_ }))) {
    if (-not (Test-Path -LiteralPath $Required -PathType Leaf)) {
        throw "Thieu tep bat buoc: $Required"
    }
}
$IsccCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
)
$Iscc = $IsccCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $Iscc) {
    throw 'Khong tim thay Inno Setup 6. Hay cai JRSoftware.InnoSetup truoc khi build.'
}
# PyInstaller replaces the previous build. Refuse to erase a used portable app.
foreach ($Name in @('data', 'output', 'profile')) {
    $RuntimeDir = Join-Path $Package $Name
    if ((Test-Path -LiteralPath $RuntimeDir) -and
        @(Get-ChildItem -LiteralPath $RuntimeDir -Force).Count -gt 0) {
        throw "Thu muc $RuntimeDir co du lieu nguoi dung. Hay chuyen ban ung dung nay ra ngoai dist truoc khi build."
    }
}

# Never trust an unverified cached archive or fall back to the full PATH binary.
New-Item -ItemType Directory -Path $FfmpegCache -Force | Out-Null
if (-not (Test-Path -LiteralPath $FfmpegZip -PathType Leaf)) {
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $FfmpegUrl -OutFile "$FfmpegZip.download"
        Move-Item -LiteralPath "$FfmpegZip.download" -Destination $FfmpegZip -Force
    }
    catch {
        throw "Khong tai duoc FFmpeg essentials tu $FfmpegUrl. $($_.Exception.Message)"
    }
}
$ActualHash = (Get-FileHash -LiteralPath $FfmpegZip -Algorithm SHA256).Hash
if ($ActualHash -ne $FfmpegSha256) {
    throw "FFmpeg essentials sai SHA256: $FfmpegZip. Mong doi $FfmpegSha256, nhan $ActualHash. Hay xoa tep cache nay roi build lai."
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$FfmpegArchive = [System.IO.Compression.ZipFile]::OpenRead($FfmpegZip)
try {
    $Entries = @($FfmpegArchive.Entries | Where-Object { $_.FullName -match '(^|/)bin/ffmpeg\.exe$' })
    if ($Entries.Count -ne 1) {
        throw 'Goi FFmpeg essentials khong chua dung mot bin/ffmpeg.exe.'
    }
    [System.IO.Compression.ZipFileExtensions]::ExtractToFile($Entries[0], $FfmpegExe, $true)
}
finally {
    $FfmpegArchive.Dispose()
}
$AppVersion = Get-Date -Format 'yyyy.MM.dd'
if (Get-Command git -CommandType Application -ErrorAction SilentlyContinue) {
    try {
        $GitVersion = & git -C $Root describe --tags --always 2>$null
        if ($LASTEXITCODE -eq 0 -and $GitVersion) {
            $AppVersion = $GitVersion.Trim()
        }
    }
    catch {
        # Source ZIPs may not include Git metadata; retain the date-based version.
    }
}

Push-Location $Root
try {
    & $Python -m PyInstaller --noconfirm --clean --distpath $Dist --workpath (Join-Path $Root 'build') $Spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller that bai (ma thoat $LASTEXITCODE)."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $Package 'VideoCongThuc.exe') -PathType Leaf)) {
        throw 'PyInstaller khong tao VideoCongThuc.exe.'
    }

    $ConfigDestination = Join-Path $Package 'config'
    New-Item -ItemType Directory -Path $ConfigDestination -Force | Out-Null
    # Copy only the allowlisted templates, never local profiles, databases or the venv.
    foreach ($Template in $Templates) {
        Copy-Item -LiteralPath (Join-Path $Root "config\$Template") -Destination $ConfigDestination -Force
    }
    # Folder root keeps only the exe, the PDF guide and user folders; everything else lives in app/.
    $AppDir = Join-Path $Package 'app'
    foreach ($Document in $Documents) {
        Copy-Item -LiteralPath (Join-Path $Root $Document) -Destination $AppDir -Force
    }
    Copy-Item -LiteralPath $Pdf -Destination $Package -Force
    Copy-Item -LiteralPath $FfmpegExe -Destination (Join-Path $AppDir 'ffmpeg.exe') -Force
    foreach ($Name in @('data', 'output', 'profile')) {
        New-Item -ItemType Directory -Path (Join-Path $Package $Name) -Force | Out-Null
    }

    # ZipFile preserves empty directories and the top-level VideoCongThuc folder.
    if (Test-Path -LiteralPath $Archive) {
        Remove-Item -LiteralPath $Archive -Force
    }
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $Package, $Archive, [System.IO.Compression.CompressionLevel]::Optimal, $true
    )
    & $Iscc "/DAppVersion=$AppVersion" $InstallerScript
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup that bai (ma thoat $LASTEXITCODE)."
    }
    foreach ($Artifact in @($Archive, $Setup)) {
        $File = Get-Item -LiteralPath $Artifact
        Write-Host ("Da dong goi: {0} ({1:N2} MiB; {2} bytes)" -f $File.FullName, ($File.Length / 1MB), $File.Length)
    }
}
finally {
    Pop-Location
}
