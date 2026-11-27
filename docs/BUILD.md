# Сборка RTX Media Master v4

## Требования

- Windows 10/11 x64
- .NET SDK 8.0 (для WPF-интерфейса)
- Python 3.11 (только для сборки CLI-движка; пользователю не нужен)
- PyInstaller 6.x
- WiX Toolset 7 (`dotnet tool install --global wix`, расширение `WixToolset.UI.wixext`)
- Бинарные зависимости в `_assets_backup`: `ffmpeg.exe`, `ffprobe.exe`, `rife-ncnn-vulkan.exe`, `vcomp140.dll`, `models/`

## Шаги

1. Соберите WPF-интерфейс:
   `dotnet build src/Gui/RTX_Media_Master_v3.csproj -c Release -o dist_new/RTX_Media_Master_v3`
2. Скопируйте `src/rtx_media_master_v35.py` и `src/rtx_engine.spec` в корень проекта сборки.
3. Проверьте синтаксис: `python -m py_compile rtx_media_master_v35.py`.
4. Соберите headless-движок:
   `pyinstaller rtx_engine.spec --noconfirm --clean --distpath dist_new`
5. Скопируйте содержимое `_assets_backup` в `dist_new/RTX_Media_Master_v3` (кроме ненужных логов).
6. Скопируйте `installer/generate_wxs.py` и `installer/app_icon.ico` в корень проекта сборки.
7. Сгенерируйте WiX-источник: `python installer/generate_wxs.py` (версия MSI — `4.0.0`).
8. Соберите MSI: `wix build -ext WixToolset.UI.wixext installer/Package.wxs -o RTX_Media_Master_v3.msi`.
   Если WiX 7 требует EULA: `wix eula accept wix7`.
9. Проверьте: `wix msi validate RTX_Media_Master_v3.msi`, тихая установка
   `msiexec /i RTX_Media_Master_v3.msi /quiet /norestart`, запуск exe из
   `C:\Program Files (x86)\RTX Media Master`, затем удаление
   `msiexec /x RTX_Media_Master_v3.msi /quiet /norestart`.

Локальный скрипт `build.ps1` автоматизирует все шаги:

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
# переиспользовать готовые сборки:
powershell -ExecutionPolicy Bypass -File build.ps1 -SkipDotNet -SkipPyInstaller
```

## Структура дистрибутива

- `RTX_Media_Master_v3.exe` — WPF-интерфейс (главное приложение).
- `rtx_engine.exe` — CLI-движок, который GUI запускает с `--no-progress`.
- `ffmpeg.exe`, `ffprobe.exe`, `rife-ncnn-vulkan.exe`, `models/` — зависимости пайплайна.

Если `rtx_engine.exe` отсутствует, GUI автоматически запускает
`python -u rtx_media_master_v35.py` (требует установленный Python).

## Особенности установщика

MSI использует `WixToolset.UI.wixext`, диалог выбора папки (`WixUI_InstallDir`),
высокое сжатие CAB (`CompressionLevel=high`) и настоящий текст MIT License в
`WixUILicenseRtf` вместо Lorem ipsum.
