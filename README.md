# RTX Media Master

![Release](https://img.shields.io/github/v/release/xzktotobro1-ui/media-compilator-master?style=for-the-badge&color=00A8E8)
![Downloads](https://img.shields.io/github/downloads/xzktotobro1-ui/media-compilator-master/total?style=for-the-badge&color=2ea043)
![License](https://img.shields.io/badge/license-MIT-green?style=for-the-badge)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-not%20required-orange?style=for-the-badge)

**Автономная Windows-утилита для интерполяции видео до 60/120 FPS** на базе **RIFE (ncnn-vulkan)** и **FFmpeg**. Работает без установки Python: готовая сборка вместе со всеми зависимостями поставляется через MSI-установщик.

Программа предназначена для владельцев видеокарт NVIDIA/AMD с поддержкой Vulkan: она превращает 24/30/60 FPS-ролики в плавные 60/120 FPS, сохраняя исходную длительность и аудио. Есть пакетная очередь, инспектор файлов, диагностика GPU/VRAM и ускоренное кодирование NVENC/AMF с программным фолбэком.

## Скриншоты

### Очередь и инспектор файла

![Очередь](docs/screenshots/01-queue.png)

### Диагностика системы

![Диагностика](docs/screenshots/02-diagnostics.png)

### Параметры обработки

![Параметры](docs/screenshots/03-settings.png)

### Журнал выполнения

![Журнал](docs/screenshots/04-log.png)

## Возможности

- **RIFE AI-интерполяция** через `rife-ncnn-vulkan` (модель rife-v4.6), автоматический выбор потоков `-j` под 4K и обычное разрешение.
- **Turbo GPU** — дублирование/удаление кадров через FFmpeg `fps`.
- **AI CPU** — `minterpolate` (mci/aobmc) для систем без Vulkan.
- **Кодирование**: H.264/HEVC через NVENC или AMF, AV1 через `libsvtav1` / `libaom-av1`; при недоступности железного энкодера — фолбэк на `libx264`/`libx265`.
- **Профили «качество ↔ размер»**, лимит битрейта, HDR-тонмаппинг, CAS-резкость.
- **Очередь файлов** с поиском, прогрессом стадий, ETA, бейджами длительности/FPS и карточкой-инспектором.
- **Диагностика**: реальные комплектующие, загрузка GPU и VRAM через `nvidia-smi`, проверка TensorRT.
- **Интерфейс** в стиле Windows 11 / Fluent: тёмная палитра AI Dark, светлая тема и тема «Как в Windows».
- **Никакого Python** на целевом компьютере — PyInstaller-сборка включает interpreter, Tkinter и все модули.

## v3.5 — новый CLI-конвейер

В репозитории доступен production-grade CLI `src/rtx_media_master_v35.py`:
RIFE ncnn-vulkan с чанками и сцен-резами, VFR→CFR, двусторонний FPS,
автовыбор AV1/HEVC/VVC/H.264 с 10-битным кодированием и опциональный
`--enhance` (deinterlace, цвет, лёгкое шумоподавление, CAS).

```powershell
python src/rtx_media_master_v35.py --input input.mp4 --output output.mp4 --fps 120 --codec auto --preset balanced --enhance
python src/rtx_media_master_v35.py --input input.mp4 --output output.mp4 --fps 2x --codec hevc
python src/rtx_media_master_v35.py --input input.mp4 --output output.mp4 --fps 24 --codec vvc --preset compact
```

Скрипт сам находит `ffmpeg`, `ffprobe`, `rife-ncnn-vulkan.exe`, лучшую модель
`rife-v4.6` и Vulkan-GPU; при отсутствии компонентов завершается с понятной
диагностикой. GUI/MSI-сборка v3.1.1 остаётся в `src/rife_120fps_v3.py`;
релиз v3.5 поставляется как CLI-скрипт и ZIP с ним.

## Установка

1. Скачайте `RTX_Media_Master_v3.msi` из [последнего релиза](https://github.com/xzktotobro1-ui/media-compilator-master/releases/latest).
2. Запустите установщик. Приложение установится в `C:\Program Files (x86)\RTX Media Master` и появится в меню «Пуск».
3. Для RIFE необходим GPU с поддержкой Vulkan. NVENC/AMF необязательны — есть программный фолбэк.

Портативный вариант: распакуйте содержимое `dist_new/RTX_Media_Master_v3` и запустите `RTX_Media_Master_v3.exe`.

## Быстрый старт

1. Перетащите видеофайлы в окно очереди или нажмите «Добавить».
2. Выберите режим (`RIFE AI Interpolation`, `Turbo GPU`, `AI CPU`) и целевой FPS.
3. Выберите профиль качества/размера и кодек.
4. Нажмите «Обработать». Результат появится рядом с исходником как `<имя>_120fps_master.mp4`.

## Сборка из исходников

Python нужен **только для сборки**. Подробности — в [docs/BUILD.md](docs/BUILD.md).

```powershell
python -m py_compile src/rife_120fps_v3.py
pyinstaller src/rife_120fps_v3.spec --noconfirm --clean --distpath dist_new
# скопируйте ffmpeg/ffprobe/rife-ncnn-vulkan/models в dist_new/RTX_Media_Master_v3
python installer/generate_wxs.py
wix build installer/Package.wxs -o RTX_Media_Master_v3.msi
```

Автоматизация: `powershell -ExecutionPolicy Bypass -File build.ps1` (флаг `-SkipPyInstaller` переиспользует готовую сборку).

## Ограничения

- RIFE-режим требует Vulkan-совместимого GPU и полного пакета моделей (`flownet.param` + `.bin`).
- AV1-кодирование программными энкодерами заметно медленнее NVENC/AMF.
- Первое кодирование 4K может занять длительное время на слабых GPU.

## Сообщество

- [Сообщить об ошибке](.github/ISSUE_TEMPLATE/bug_report.md)
- [Предложить функцию](.github/ISSUE_TEMPLATE/feature_request.md)
- [Правила участия](CONTRIBUTING.md), [ChangeLog](CHANGELOG.md), [Кодекс поведения](CODE_OF_CONDUCT.md)

## Лицензии

Код приложения — [MIT](LICENSE). Сторонние компоненты и их лицензии (FFmpeg, libx264, libx265, libsvtav1, RIFE, ncnn, Python, Tcl/Tk, PyInstaller, TensorRT, WiX) перечислены в [NOTICE.md](NOTICE.md). Бинарные зависимости не хранятся в репозитории.
