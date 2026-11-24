param(
    [switch]$SkipPyInstaller
)

$ErrorActionPreference = 'Stop'

$repo    = Split-Path -Parent $MyInvocation.MyCommand.Definition
$project = Split-Path -Parent $repo
$dst     = Join-Path $project 'dist_new\RTX_Media_Master_v3'
$assets  = Join-Path $project '_assets_backup'
$msi     = Join-Path $project 'RTX_Media_Master_v3.msi'

Write-Host "Repo:    $repo"
Write-Host "Project: $project"
Write-Host "Output:  $msi"

# 1) Исходники в корень проекта сборки
Copy-Item -LiteralPath (Join-Path $repo 'src\rife_120fps_v3.py')   -Destination (Join-Path $project 'rife_120fps_v3.py') -Force
Copy-Item -LiteralPath (Join-Path $repo 'src\rife_120fps_v3.spec') -Destination (Join-Path $project 'rife_120fps_v3.spec') -Force
Copy-Item -LiteralPath (Join-Path $repo 'installer\generate_wxs.py') -Destination (Join-Path $project 'installer\generate_wxs.py') -Force
Copy-Item -LiteralPath (Join-Path $repo 'installer\app_icon.ico')   -Destination (Join-Path $project 'installer\app_icon.ico') -Force

Push-Location $project
try {
    python -m py_compile rife_120fps_v3.py
    if ($LASTEXITCODE -ne 0) { throw 'Syntax check failed' }

    if (-not $SkipPyInstaller) {
        pyinstaller rife_120fps_v3.spec --noconfirm --clean --distpath (Join-Path $project 'dist_new')
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }

        # Бинарные зависимости и модели не хранятся в git
        Copy-Item -LiteralPath `
            (Join-Path $assets 'ffmpeg.exe'),
            (Join-Path $assets 'ffprobe.exe'),
            (Join-Path $assets 'rife-ncnn-vulkan.exe'),
            (Join-Path $assets 'vcomp140.dll'),
            (Join-Path $assets 'settings.json') -Destination $dst -Force
        Copy-Item -LiteralPath (Join-Path $assets 'models') -Destination $dst -Recurse -Force
    }

    python installer/generate_wxs.py
    if ($LASTEXITCODE -ne 0) { throw 'WXS generation failed' }

    wix build installer/Package.wxs -o $msi
    if ($LASTEXITCODE -ne 0) { throw 'WiX build failed' }

    wix msi validate $msi
    if ($LASTEXITCODE -ne 0) { throw 'MSI validation failed' }
}
finally {
    Pop-Location
}

Get-Item -LiteralPath $msi | Select-Object FullName, Length, LastWriteTime | Format-List
