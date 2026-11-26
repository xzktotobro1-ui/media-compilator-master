# Сборка RTX Media Master

## Требования

- Windows 10/11 x64
- Python 3.11 (для сборки из исходников; конечному пользователю не нужен)
- PyInstaller 6.x
- .NET SDK >= 6 и WiX Toolset 7 (`dotnet tool install --global wix`)
- Бинарные зависимости в `_assets_backup`: `ffmpeg.exe`, `ffprobe.exe`, `rife-ncnn-vulkan.exe`, `vcomp140.dll`, `models/`

## Шаги

1. Скопируйте `src/rife_120fps_v3.py` и `src/rife_120fps_v3.spec` в корень проекта сборки.
2. Проверьте синтаксис: `python -m py_compile rife_120fps_v3.py`.
3. Соберите Portable-версию:
   `pyinstaller rife_120fps_v3.spec --noconfirm --clean --distpath dist_new`
4. Скопируйте содержимое `_assets_backup` в `dist_new/RTX_Media_Master_v3` (кроме ненужных логов).
5. Скопируйте `installer/generate_wxs.py` и `installer/app_icon.ico` в корень проекта сборки.
6. Сгенерируйте WiX-источник: `python installer/generate_wxs.py`.
7. Соберите MSI: `wix build installer/Package.wxs -o RTX_Media_Master_v3.msi`.
   Если WiX 7 требует EULA: `wix eula accept wix7`.
8. Проверьте: `wix msi validate RTX_Media_Master_v3.msi`, тихая установка
   `msiexec /i RTX_Media_Master_v3.msi /quiet /norestart`, запуск exe из
   `C:\Program Files (x86)\RTX Media Master`, затем удаление
   `msiexec /x RTX_Media_Master_v3.msi /quiet /norestart`.

Локальный скрипт `build.ps1` автоматизирует шаги 1–7.

## Особенности установщика v3.5

Для сборки MSI используется расширение `WixToolset.UI.wixext` (`wix extension add -g WixToolset.UI.wixext`) и `wix build -ext WixToolset.UI.wixext`. В `generate_wxs.py` добавлены `WixUI_InstallDir`, `Property WixUIInstallDir` и `MediaTemplate CompressionLevel="high"`. Дистрибутив включает полный `ffmpeg.exe` и облегчённый `ffprobe.exe`.
