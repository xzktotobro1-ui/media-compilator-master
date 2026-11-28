# RTX Media Master v4.1 — Novator Edition

![Release](https://img.shields.io/github/v/release/xzktotobro1-ui/media-compilator-master?style=for-the-badge&color=00A8E8)
![Downloads](https://img.shields.io/github/downloads/xzktotobro1-ui/media-compilator-master/total?style=for-the-badge&color=2ea043)
![License](https://img.shields.io/badge/license-MIT-green?style=for-the-badge)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue?style=for-the-badge)
![Stack](https://img.shields.io/badge/stack-Tauri%202%20%C2%B7%20React%20%C2%B7%20Rust-10B981?style=for-the-badge)

Автономная Windows-утилита для интерполяции видео до 60/120 FPS, сжатия и реставрации на базе **RIFE (ncnn-vulkan)** и **FFmpeg**. Начиная с v4.1 графический интерфейс полностью переписан на **Tauri v2 + React + TypeScript + Tailwind CSS + Shadcn UI + Framer Motion + Lucide React**. Headless-движок `rtx_engine` работает как Tauri Sidecar.

## Принцип: только реальные данные

- Метаданные видео — реальный `ffprobe -v quiet -print_format json -show_format -show_streams`; при ошибке выводится причина.
- Телеметрия GPU — реальный опрос `nvidia-smi`; если датчик недоступен, показывается честное `N/A`.
- Поддержка кодеков определяется реальным выводом `ffmpeg -encoders` и доступностью видеокарты.
- Прогресс, скорость и ETA парсятся только из stdout/stderr запущенного sidecar-процесса.
- В коде нет `Math.random()`, захардкоженных «RTX 4090 / 45°C / 60 FPS» или симуляции прогресса.

## Возможности

- **Пять вкладок**: «Очередь и Сжатие», «Студия сравнения До / После», «Диагностика и Железо», «Пресеты и Автоматизация», «Журнал и CLI».
- **Очередь**: Drag & Drop файлов и папок, реальные миниатюры `ffmpeg`, длительность/разрешение/FPS/кодек/битрейт, бейдж VFR, поиск, фильтр и сортировка, обрезка `--ss`/`--to`, тест 5 секунд.
- **Пресеты в один клик**: Telegram/Discord с расчётом битрейта под лимит 10/25/50/100 МБ, мастер-архив AV1/HEVC 10-bit, RIFE 60/120 FPS, реставрация `bwdif + hqdn3d + zscale + CAS`.
- **Плавающий док-бар**: режим, кодек, целевой FPS, профиль, Enhance; выдвижная панель Pro Studio с CQ/CRF, глубиной цвета, аудио, субтитрами, масштабом и выбором реально доступного энкодера.
- **Студия сравнения**: синхронное воспроизведение original/result, шторка-разделитель, зум 100–400%, покадровая перемотка, скорость 0.25x/0.5x/1x, метрики SSIM/PSNR через `ffmpeg`.
- **Диагностика**: Bento Grid 2×2 — живые спарклайны GPU, матрица кодеков, статус компонентов, паспорт системы.
- **Watch Folder**: реальный файловый вотчер `notify` автоматически добавляет новые видеофайлы в очередь.
- **Журнал**: поток `engine-log`, фильтры ALL/INFO/WARN/ERROR, поиск, экспорт `.txt`, копирование CLI-команды, верификация `ffprobe` после рендера.
- **Системное**: кастомный заголовок без рамки, Mica/acrylic с фолбэком `#09090B`, прогресс на иконке в панели задач, уведомления и звук завершения, опциональная интеграция в контекстное меню Windows.

## Установка

1. Скачайте `setup.exe` из [последнего релиза](https://github.com/xzktotobro1-ui/media-compilator-master/releases/latest).
2. Запустите установщик: он предложит папку установки, создаст ярлыки и опционально добавит пункт «Сжать / Улучшить через RTX Media Master» в контекстное меню Windows (передаёт `%1` в аргументы).
3. Рядом с `rtx-media-master.exe` устанавливаются `rtx_engine.exe`, `ffmpeg.exe`, `ffprobe.exe`, `rife-ncnn-vulkan.exe`, `vcomp140.dll`, папки `_internal/` и `models/` (включая `models/rife-v4.6`) из релиза v3.5.
4. Для RIFE нужен GPU с поддержкой Vulkan и модель `rife-v4.6`. NVENC/AMF необязательны — есть программный фолбэк.

## Headless-бэкенд

GUI запускает sidecar-бинарники из `src-tauri/binaries/` с суффиксом `-x86_64-pc-windows-msvc.exe`:

- `rtx_engine` — основной CLI-движок;
- `ffmpeg`, `ffprobe` — медиаинструменты;
- `rife-ncnn-vulkan` — нейросетевая интерполяция (при наличии).

Пример прямого вызова:

```powershell
rtx_engine.exe --input input.mp4 --output output.mp4 --fps 120 --codec auto --preset balanced --enhance --no-progress
```

Отмена рендера завершает всё дерево процессов через `taskkill /PID /T /F`.

## Сборка из исходников

Нужны **Node.js 20+**, **Rust/Cargo**, **PyInstaller**, **NSIS** (устанавливается самим Tauri при первом `tauri build`).

```powershell
# 1. Движок (PyInstaller)
pyinstaller src/rtx_engine.spec --noconfirm --clean --distpath dist_engine

# 2. Sidecar-бинарники: положите в src-tauri/binaries/ с суффиксом целевой платформы
#    rtx_engine-x86_64-pc-windows-msvc.exe и его папку _internal/
#    ffmpeg-x86_64-pc-windows-msvc.exe, ffprobe-x86_64-pc-windows-msvc.exe

# 3. ESLint-free frontend + Tauri
cd rtx-media-master
npm install
npm run build
npm run tauri build
```

Готовый установщик:

```text
rtx-media-master/src-tauri/target/release/bundle/nsis/RTX Media Master v4.1 — Novator Edition_4.1.0_x64-setup.exe
```

Полная автоматизация — `powershell -ExecutionPolicy Bypass -File build.ps1`.

> Тяжёлые бинарники, модели, `node_modules/` и `src-tauri/target/` намеренно исключены из Git через `.gitignore`. Их нужно подготовить локально перед сборкой.

## Ограничения

- RIFE требует Vulkan-совместимого GPU и полного набора моделей `flownet.param` + `.bin`.
- Программные AV1/FFV1-энкодеры заметно медленнее NVENC/AMF.
- 4K/120fps-рендер на слабом GPU может занять длительное время.

## Сообщество

[Сообщить об ошибке](.github/ISSUE_TEMPLATE/bug_report.md) · [Предложить функцию](.github/ISSUE_TEMPLATE/feature_request.md) · [Правила участия](CONTRIBUTING.md) · [История изменений](CHANGELOG.md) · [Кодекс поведения](CODE_OF_CONDUCT.md) · [NOTICE](NOTICE.md)

Автор: **x_kitaikuyo_x**. Лицензия — [MIT](LICENSE).
