# NOTICE — сторонние компоненты

RTX Media Master распространяется с рядом внешних бинарных зависимостей. Они **не включаются в исходный репозиторий**, но попадают в MSI/PyInstaller-сборку.

| Компонент | Лицензия | Примечание |
|---|---|---|
| FFmpeg / ffprobe | LGPL 2.1+ или GPL 2+ в зависимости от конфигурации | Сборка с libx264/libx265/libsvtav1 подпадает под GPL. Предоставьте исходники или ссылку на них при публичном распространении. |
| libx264 | GPL v2+ | H.264-кодирование |
| libx265 | GPL v2+ | HEVC-кодирование |
| libsvtav1 | BSD-2-Clause | AV1-кодирование |
| rife-ncnn-vulkan | MIT | Интерполяция RIFE |
| ncnn | BSD-3-Clause | Backend нейросети |
| Python 3.11 | PSF License | Встроен в CLI-движок `rtx_engine.exe` |
| .NET 8 / WPF | MIT License | Графический интерфейс `RTX_Media_Master_v3.exe` |
| CommunityToolkit.Mvvm | MIT License | MVVM-паттерн и команды в GUI |
| Ookii.Dialogs.Wpf | MIT License | Диалог выбора папки |
| PyInstaller | GPL v2 + bootloader exception | Упаковщик CLI-движка |
| NVIDIA TensorRT | Proprietary | Только для диагностики |

WiX Toolset используется только для создания MSI; согласно условиям WiX, созданные MSI не являются производными от WiX и не наследуют его лицензию. WiX 7 требует принятия OSMF EULA для организаций с выручкой выше порога; исходный код остаётся свободным.

Если вы публикуете MSI, приложите этот файл и соответствующие исходники GPL-компонентов (или ссылку на официальные исходники с патчами).
