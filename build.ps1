$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Spec = Join-Path $Root 'VideoCongThuc.spec'
$Dist = Join-Path $Root 'dist'
$Package = Join-Path $Dist 'VideoCongThuc'
$Archive = Join-Path $Dist 'VideoCongThuc.zip'
$Templates = @(
    'settings.json', 'channels.txt', 'taxonomy.json', 'selectors.json',
    'graphql_paths.json', 'keyterms.txt', 'ban_words.txt'
)
$Documents = @('THIRD_PARTY_NOTICES.txt', 'HUONG-DAN.md')

foreach ($Required in (@($Python, $Spec, (Join-Path $Root 'launcher.py')) +
        @($Templates | ForEach-Object { Join-Path $Root "config\$_" }) +
        @($Documents | ForEach-Object { Join-Path $Root $_ }))) {
    if (-not (Test-Path -LiteralPath $Required -PathType Leaf)) {
        throw "Thieu tep bat buoc: $Required"
    }
}
$Ffmpeg = Get-Command ffmpeg -CommandType Application -ErrorAction Stop | Select-Object -First 1
if (-not (Test-Path -LiteralPath $Ffmpeg.Path -PathType Leaf)) {
    throw 'Khong tim thay ffmpeg.exe trong PATH.'
}
# PyInstaller replaces the previous build. Refuse to erase a used portable app.
foreach ($Name in @('data', 'output', 'profile')) {
    $RuntimeDir = Join-Path $Package $Name
    if ((Test-Path -LiteralPath $RuntimeDir) -and
        @(Get-ChildItem -LiteralPath $RuntimeDir -Force).Count -gt 0) {
        throw "Thu muc $RuntimeDir co du lieu nguoi dung. Hay chuyen ban ung dung nay ra ngoai dist truoc khi build."
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
    foreach ($Document in $Documents) {
        Copy-Item -LiteralPath (Join-Path $Root $Document) -Destination $Package -Force
    }
    $Pdf = Join-Path $Root 'HUONG-DAN.pdf'
    if (Test-Path -LiteralPath $Pdf -PathType Leaf) {
        Copy-Item -LiteralPath $Pdf -Destination $Package -Force
    }
    Copy-Item -LiteralPath $Ffmpeg.Path -Destination (Join-Path $Package 'ffmpeg.exe') -Force
    foreach ($Name in @('data', 'output', 'profile')) {
        New-Item -ItemType Directory -Path (Join-Path $Package $Name) -Force | Out-Null
    }

    # ZipFile preserves empty directories and the top-level VideoCongThuc folder.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $Archive) {
        Remove-Item -LiteralPath $Archive -Force
    }
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $Package, $Archive, [System.IO.Compression.CompressionLevel]::Optimal, $true
    )
    Write-Host "Da dong goi: $Archive"
}
finally {
    Pop-Location
}
