# RTX Media Master

GUI-приложение для Windows, которое ускоряет видео до 60/120 FPS через RIFE (ncnn-vulkan), Turbo GPU или FFmpeg `minterpolate`. Работает **без установки Python**: PyInstaller-сборка включает interpreter, Tkinter и все зависимости.

## Возможности

- Интерполяция RIFE-v4.6 на Vulkan (`rife-ncnn-vulkan`), потоки `-j` под разрешение.
- Turbo GPU (дублирование/удаление кадров) и AI CPU (`minterpolate`).
- Кодирование HEVC/H.264 through NVENC/AMF с фолбэком на libx265/libx264; AV1 через libsvtav1/libaom-av1.
- Профили «качество ↔ размер», лимит битрейта, HDR-тонмаппинг, Cas-резкость.
- Диагностика GPU/VRAM, инспектор видео, очередь с поиском и прогрессом.

## Установка

1. Скачайте `RTX_Media_Master_v3.msi` из релиза.
2. Запустите установщик. Приложение установится в `C:\Program Files (x86)\RTX Media Master` (MSI x86) и появится в меню «Пуск».
3. Для RIFE нужен GPU с поддержкой Vulkan. NVENC/AMF необязательны — есть программный фолбэк.

Портативный вариант: распакуйте архив `dist_new/RTX_Media_Master_v3` и запустите `RTX_Media_Master_v3.exe`.

## Сборка из исходников

См. [docs/BUILD.md](docs/BUILD.md). Коротко:

```powershell
python -m py_compile src/rife_120fps_v3.py
pyinstaller src/rife_120fps_v3.spec --noconfirm --clean --distpath dist_new
# скопировать ffmpeg/ffprobe/rife-ncnn-vulkan/models в dist_new/RTX_Media_Master_v3
python installer/generate_wxs.py
wix build installer/Package.wxs -o RTX_Media_Master_v3.msi
```

## Лицензии

Код приложения — MIT (см. LICENSE). Состав третьих лиц и GPL-компоненты описаны в [NOTICE.md](NOTICE.md). Biнарные зависимости не хранятся в репозитории.
