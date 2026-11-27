param(
    [switch]$SkipPyInstaller,
    [switch]$SkipDotNet
)

$ErrorActionPreference = 'Stop'

$repo    = Split-Path -Parent $MyInvocation.MyCommand.Definition
$project = Split-Path -Parent $repo
$gui     = Join-Path $repo 'src\Gui'
$dst     = Join-Path $project 'dist_new\RTX_Media_Master_v3'
$assets  = Join-Path $project '_assets_backup'
$msi     = Join-Path $project 'RTX_Media_Master_v3.msi'

Write-Host "Repo:    $repo"
Write-Host "Project: $project"
Write-Host "Output:  $msi"

# 1) Исходники в корень проекта сборки
Copy-Item -LiteralPath (Join-Path $repo 'src\rtx_media_master_v35.py') -Destination (Join-Path $project 'rtx_media_master_v35.py') -Force
Copy-Item -LiteralPath (Join-Path $repo 'src\rtx_engine.spec')         -Destination (Join-Path $project 'rtx_engine.spec') -Force
Copy-Item -LiteralPath (Join-Path $repo 'installer\generate_wxs.py')  -Destination (Join-Path $project 'installer\generate_wxs.py') -Force
Copy-Item -LiteralPath (Join-Path $repo 'installer\app_icon.ico')     -Destination (Join-Path $project 'installer\app_icon.ico') -Force

New-Item -ItemType Directory -Force -Path $dst | Out-Null

Push-Location $project
try {
    python -m py_compile rtx_media_master_v35.py
    if ($LASTEXITCODE -ne 0) { throw 'Syntax check failed' }

    # 2) Сборка C# GUI (.NET 8 + WPF) — главное приложение
    if (-not $SkipDotNet) {
        Write-Host "Building C# GUI..."
        dotnet build (Join-Path $gui 'RTX_Media_Master_v3.csproj') -c Release -o $dst
        if ($LASTEXITCODE -ne 0) { throw 'dotnet build failed' }

        # Иконка приложения рядом с exe
        Copy-Item -LiteralPath (Join-Path $repo 'installer\app_icon.ico') -Destination (Join-Path $dst 'app_icon.ico') -Force
    }

    # 3) Сборка干净 CLI-движка rtx_engine.exe
    if (-not $SkipPyInstaller) {
        Write-Host "Building rtx_engine.exe (PyInstaller)..."
        pyinstaller rtx_engine.spec --noconfirm --clean --distpath (Join-Path $project 'dist_new')
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }

        # Бинарные зависимости и модели не хранятся в git
        Copy-Item -LiteralPath `
            (Join-Path $assets 'ffmpeg.exe'),
            (Join-Path $assets 'ffprobe.exe'),
            (Join-Path $assets 'rife-ncnn-vulkan.exe'),
            (Join-Path $assets 'vcomp140.dll') -Destination $dst -Force
        Copy-Item -LiteralPath (Join-Path $assets 'models') -Destination $dst -Recurse -Force
    }

    # 4) Генерация WiX и сборка MSI
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
