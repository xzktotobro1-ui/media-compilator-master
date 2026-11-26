# -*- coding: utf-8 -*-
"""
RTX Media Master v3.5 — GUI + production-grade конвейер RIFE/FFmpeg.
Windows GUI для пакетной обработки видео через FFmpeg и RIFE NCNN Vulkan.

Улучшения v3:
- Исправлены расчёты desired_frames / actual_fps; прогресс RIFE теперь считается по
  реально созданным кадрам (вывод rife-ncnn-vulkan не содержит процентов).
- Исправлена подача аудио из исходника при сборке результата RIFE.
- Удалён мёртвый код build_encoder_command; построение команд унифицировано.
- Чистый фолбэк энкодеров: NVENC/AMF -> libx264/libx265 без искажения опций.
- Сохранение/загрузка настроек (settings.json) и геометрии окна.
- Встроенное окно логов, индикация стадий (Extract -> Interpolate -> Encode).
- Проверка зависимостей, энкодеров и свободного места перед запуском.
- Полная типизация, docstrings, константы, контекстный менеджер temp-папок.
- Thread-safe логирование и обновление UI через очередь событий.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
import tkinter as tk
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from pathlib import Path
from tkinter import (
    Tk, StringVar, IntVar, BooleanVar, DoubleVar, filedialog, messagebox,
    ttk, Listbox, Canvas, Scale, HORIZONTAL, Text, Scrollbar, END, DISABLED, NORMAL,
    font as tkfont,
)
from typing import Callable, Iterator

try:
    import media_engine_v35 as engine  # встроенный конвейер v3.5
except Exception:  # pragma: no cover - диагностика ниже
    engine = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Константы и пути
# ---------------------------------------------------------------------------

APP_NAME = "RTX Media Master"
APP_VERSION = "v3.5"

# Сквозной прогресс по стадиям RIFE-конвейера (проценты общего прогресса)
STAGE_EXTRACT_SPAN = (0.0, 12.0)
STAGE_RIFE_SPAN = (12.0, 88.0)
STAGE_ENCODE_SPAN = (88.0, 100.0)

# Оформление: Microsoft Fluent + «Pro Creative / AI Dark» для GPU-рендера
THEME_CREATIVE = "AI Dark (Pro Creative)"
THEME_SYSTEM = "Как в Windows"
THEME_LIGHT = "Светлая"
THEME_DARK = "Тёмная"
THEME_NORD = "Nord (Arctic)"
THEME_OCEAN = "Ocean Light"
THEME_SOLAR = "Solarized Dark"
THEME_CHOICES = [
    THEME_CREATIVE, THEME_SYSTEM, THEME_LIGHT, THEME_DARK,
    THEME_NORD, THEME_OCEAN, THEME_SOLAR,
]

FONT_REGISTRY = {
    "body": 9, "caption": 9, "subtitle": 12, "header": 18,
    "value": 12, "nav": 13, "mono": 10, "tooltip": 9,
}
SPACING = {"xs": 2, "sm": 4, "md": 8, "lg": 12, "xl": 16}

# Пиктограммы в духе Segoe MDL2. Используем обычные Юникод-глифы: они
# отрисовываются монохромно системным шрифтом и не зависят от PUA-шрифта.
ICON_MENU = "☰"
ICON_SEARCH = "⌕"
ICON_ADD = "＋"
ICON_CLEAR = "✕"
ICON_REMOVE = "✖"
ICON_REFRESH = "⟳"
ICON_SETTINGS = "⚙"
ICON_QUEUE = "▤"
ICON_DIAG = "◈"
ICON_LOG = "▦"
ICON_START = "▶"
ICON_STOP = "■"
ICON_RETRY = "↻"
ICON_THEME = "◐"

SEARCH_PLACEHOLDER = "Поиск по очереди..."

# Страницы NavigationView
PAGE_QUEUE = "queue"
PAGE_DIAG = "diag"
PAGE_SETTINGS = "settings"
PAGE_LOG = "log"
PAGE_TITLES = {
    PAGE_QUEUE: "Очередь видео",
    PAGE_DIAG: "Диагностика оборудования",
    PAGE_SETTINGS: "Параметры обработки",
    PAGE_LOG: "Журнал обработки",
}


def application_dir() -> Path:
    """Каталог приложения. В PyInstaller (frozen) — папка с .exe, а не _MEIPASS."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def user_data_dir() -> Path:
    """Доступный для записи каталог пользовательских данных.

    Program Files доступен только для чтения: создание session_runtime.log там
    приводит к PermissionError [Errno 13] при запуске MSI-версии без прав admin.
    """
    candidates: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "RTX Media Master")
    candidates.append(Path.home() / ".rtx_media_master")
    candidates.append(Path(tempfile.gettempdir()) / "RTX Media Master")
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".write_probe"
            probe.write_text("", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return path
        except OSError:
            continue
    return candidates[-1]


BASE_DIR = application_dir()
DATA_DIR = user_data_dir()
LOG_PATH = DATA_DIR / "session_runtime.log"
SETTINGS_PATH = DATA_DIR / "settings.json"
CRASH_LOG_PATH = DATA_DIR / "crash_log.txt"

# Миграция настроек из прежнего расположения (в каталоге программы).
_LEGACY_SETTINGS = BASE_DIR / "settings.json"
if not SETTINGS_PATH.exists() and _LEGACY_SETTINGS.is_file():
    try:
        shutil.copy2(_LEGACY_SETTINGS, SETTINGS_PATH)
    except OSError:
        pass

FFMPEG_NAME = "ffmpeg.exe"
FFPROBE_NAME = "ffprobe.exe"
RIFE_NAME = "rife-ncnn-vulkan.exe"
MODELS_DIR_NAME = "models"

FFMPEG_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip"
)
RIFE_URL = (
    "https://github.com/nihui/rife-ncnn-vulkan/releases/download/20221029/"
    "rife-ncnn-vulkan-20221029-windows.zip"
)

FPS_CHOICES = [60, 120, 144, 200, 240, 360, 480]
RESOLUTION_CHOICES = [
    ("Original", "Original"),
    ("1280x720 (HD)", "1280x720"),
    ("1920x1080 (FullHD)", "1920x1080"),
    ("2560x1440 (2K QHD)", "2560x1440"),
    ("3840x2160 (4K UHD)", "3840x2160"),
]
SCALE_CHOICES = ["lanczos", "bicubic", "bilinear", "neighbor", "area"]
CODEC_CHOICES = ["h264", "hevc", "av1"]
NVENC_PRESET_CHOICES = [
    "p1 (Быстро)", "p2", "p3", "p4 (Баланс)", "p5", "p6", "p7 (Качество)",
]
AUDIO_MODE_CHOICES = ["copy", "aac"]
AUDIO_BITRATE_CHOICES = ["128k", "160k", "192k", "256k", "320k"]
ENGINE_CODEC_CHOICES = ["auto", "av1", "hevc", "vvc", "h264"]
ENGINE_PRESET_CHOICES = ["compact", "balanced", "quality"]
QUALITY_CHOICES = [12, 14, 16, 18, 20, 21, 22, 24, 26, 28]

# Профили «размер ↔ качество». Значения: (кодек, NVENC preset, CQ/CRF, лимит битрейта).
PROFILE_BALANCED = "Оптимально (малый размер, высокое качество)"
PROFILE_MAX_QUALITY = "Максимальное качество (крупнее)"
PROFILE_MIN_SIZE = "Минимальный размер"
PROFILE_AV1 = "AV1 (макс. эффективность, медленно)"
PROFILE_MANUAL = "Вручную"
PROFILE_CHOICES = [
    PROFILE_BALANCED, PROFILE_MAX_QUALITY, PROFILE_MIN_SIZE, PROFILE_AV1, PROFILE_MANUAL,
]
PROFILE_PRESETS: dict[str, tuple[str, str, int, bool] | None] = {
    PROFILE_BALANCED: ("hevc", "p7 (Качество)", 21, True),
    PROFILE_MAX_QUALITY: ("hevc", "p7 (Качество)", 16, False),
    PROFILE_MIN_SIZE: ("hevc", "p7 (Качество)", 26, True),
    PROFILE_AV1: ("av1", "p4 (Баланс)", 22, False),
    PROFILE_MANUAL: None,
}

MODE_LABELS = {
    "rife_tensorrt": "RIFE AI Interpolation (Vulkan/NCNN)",
    "turbo_gpu": "Turbo GPU (дублирование/удаление кадров)",
    "ai_cpu": "AI CPU (FFmpeg minterpolate)",
}

TENSORRT_PATH = Path(r"C:\TensorRT-11.4.0.106")
if TENSORRT_PATH.exists():
    trt_bin = TENSORRT_PATH / "bin"
    if trt_bin.exists():
        os.environ["PATH"] = str(trt_bin) + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(trt_bin))
            except OSError:
                pass
    trt_python = TENSORRT_PATH / "python"
    if trt_python.exists():
        sys.path.insert(0, str(trt_python))

HAS_TENSORRT = False
trt = None
try:
    import tensorrt as trt  # type: ignore
    HAS_TENSORRT = True
except Exception as exc:  # pragma: no cover
    logging.info("TensorRT не загружен: %s", exc)

HAS_NVML = False
pynvml = None
try:
    import pynvml  # type: ignore
    pynvml.nvmlInit()
    HAS_NVML = True
except Exception as exc:  # pragma: no cover
    logging.info("NVML недоступен: %s", exc)

# ---------------------------------------------------------------------------
# Логирование (в файл + консоль). UI-лог подключается отдельно через очередь.
# ---------------------------------------------------------------------------

_log_handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
try:
    _log_handlers.append(logging.FileHandler(LOG_PATH, encoding="utf-8"))
except OSError as exc:  # программа должна запускаться даже без доступа к логу
    print(f"Файловый лог недоступен ({LOG_PATH}): {exc}", file=sys.stderr)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s [%(threadName)s] %(message)s",
    handlers=_log_handlers,
)


# ---------------------------------------------------------------------------
# Структуры данных
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class JobConfig:
    mode: str
    target_fps: int
    target_res: str
    scale_algo: str
    codec: str
    nvenc_preset: str
    audio_mode: str
    audio_bitrate: str
    hdr_tonemap: bool
    limit_bitrate: bool
    denoise: bool
    sharpen: bool
    sharpen_amount: float
    quality: int = 21
    gpu_index: int = 0
    engine_codec: str = "auto"
    engine_preset: str = "balanced"
    engine_enhance: bool = False
    engine_gpu: int = 0


@dataclass
class AppSettings:
    processing_mode: str = "rife_tensorrt"
    target_fps: int = 120
    target_res: str = "Original"
    scale_algo: str = "lanczos"
    output_codec: str = "hevc"
    nvenc_preset: str = "p7 (Качество)"
    audio_mode: str = "copy"
    audio_bitrate: str = "192k"
    enable_hdr_tonemap: bool = False
    limit_bitrate: bool = True
    enable_denoise: bool = False
    enable_sharpen: bool = True
    sharpen_amount: float = 0.6
    quality: int = 21
    profile: str = PROFILE_BALANCED
    theme: str = THEME_CREATIVE
    gpu_index: int = 0
    engine_codec: str = "auto"
    engine_preset: str = "balanced"
    engine_enhance: bool = False
    engine_gpu: int = 0
    geometry: str = "1020x760"

    @classmethod
    def load(cls) -> "AppSettings":
        result = cls()
        if not SETTINGS_PATH.exists():
            return result
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("settings.json должен содержать объект")

            def as_choice(key: str, default: str, choices: list[str] | tuple[str, ...]) -> str:
                value = data.get(key, default)
                return value if isinstance(value, str) and value in choices else default

            result.processing_mode = as_choice(
                "processing_mode", result.processing_mode, tuple(MODE_LABELS)
            )
            result.target_fps = safe_int(data.get("target_fps"), 120, 1, 1000)
            result.target_res = as_choice(
                "target_res", result.target_res, [value for _, value in RESOLUTION_CHOICES]
            )
            result.scale_algo = as_choice("scale_algo", result.scale_algo, SCALE_CHOICES)
            result.output_codec = as_choice("output_codec", result.output_codec, CODEC_CHOICES)
            result.nvenc_preset = as_choice(
                "nvenc_preset", result.nvenc_preset, NVENC_PRESET_CHOICES
            )
            result.audio_mode = as_choice("audio_mode", result.audio_mode, AUDIO_MODE_CHOICES)
            result.audio_bitrate = as_choice(
                "audio_bitrate", result.audio_bitrate, AUDIO_BITRATE_CHOICES
            )
            for key in (
                "enable_hdr_tonemap", "limit_bitrate", "enable_denoise", "enable_sharpen"
            ):
                if key in data:
                    setattr(result, key, bool(data[key]))
            result.sharpen_amount = safe_float(
                data.get("sharpen_amount"), 0.6, 0.0, 1.0
            )
            result.quality = safe_int(data.get("quality"), 21, 1, 51)
            result.gpu_index = safe_int(data.get("gpu_index"), 0, 0, 15)
            result.engine_codec = as_choice(
                "engine_codec", result.engine_codec, ENGINE_CODEC_CHOICES
            )
            result.engine_preset = as_choice(
                "engine_preset", result.engine_preset, ENGINE_PRESET_CHOICES
            )
            result.engine_enhance = bool(data.get("engine_enhance", False))
            result.engine_gpu = safe_int(data.get("engine_gpu"), 0, 0, 15)
            geometry = data.get("geometry", result.geometry)
            result.geometry = (
                geometry
                if isinstance(geometry, str)
                and re.fullmatch(r"\d{3,5}x\d{3,5}(?:[+-]\d+[+-]\d+)?", geometry)
                else result.geometry
            )
            # Старые settings.json не знают про профили — обновляем до оптимума.
            if "profile" not in data or data.get("profile") not in PROFILE_CHOICES:
                result.profile = PROFILE_BALANCED
                codec, preset_name, quality, limit = PROFILE_PRESETS[PROFILE_BALANCED]
                for key, value in (
                    ("output_codec", codec), ("nvenc_preset", preset_name),
                    ("quality", quality), ("limit_bitrate", limit),
                ):
                    if key not in data:
                        setattr(result, key, value)
            if "theme" not in data or data.get("theme") not in THEME_CHOICES:
                result.theme = THEME_SYSTEM
        except Exception as exc:
            logging.warning("Не удалось загрузить настройки: %s", exc)
        return result

    def save(self) -> None:
        try:
            SETTINGS_PATH.write_text(
                json.dumps(asdict(self), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logging.warning("Не удалось сохранить настройки: %s", exc)


@dataclass
class MediaMeta:
    w: int
    h: int
    fps: float
    frames: int
    pix: str
    color_transfer: str = ""
    color_primaries: str = ""
    color_space: str = ""
    duration: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def hidden_startupinfo():
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        return si
    return None


def hidden_creationflags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def run_capture(command: list[str], timeout: int | None = 120) -> str:
    completed = subprocess.run(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        startupinfo=hidden_startupinfo(), creationflags=hidden_creationflags(),
        timeout=timeout, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            completed.stderr.strip() or f"Команда завершилась с кодом {completed.returncode}"
        )
    return completed.stdout


def parse_fraction(value: str | None) -> float:
    if not value or value in {"0/0", "N/A"}:
        return 0.0
    try:
        if "/" in value:
            a, b = value.split("/", 1)
            denominator = float(b)
            return float(a) / denominator if denominator else 0.0
        result = float(value)
        return result if math.isfinite(result) else 0.0
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def format_eta(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def collect_system_info() -> dict[str, str]:
    """Опрос комплектующих через PowerShell/CIM. Возвращает «Компонент → Значение»."""
    if os.name != "nt":
        return {"Операционная система": "Подробный опрос доступен только в Windows"}

    script = r'''
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$cpu     = Get-CimInstance Win32_Processor | Select-Object -First 1
$bb      = Get-CimInstance Win32_BaseBoard | Select-Object -First 1
$bios    = Get-CimInstance Win32_BIOS | Select-Object -First 1
$cs      = Get-CimInstance Win32_ComputerSystem | Select-Object -First 1
$os      = Get-CimInstance Win32_OperatingSystem | Select-Object -First 1
$ram     = Get-CimInstance Win32_PhysicalMemory
$gpus    = Get-CimInstance Win32_VideoController
$disks   = Get-CimInstance Win32_DiskDrive
$volumes = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3"
$net     = Get-CimInstance Win32_NetworkAdapter | Where-Object {
    $_.NetEnabled -eq $true -and $_.Name -notmatch 'Virtual|VPN|WAN|Bluetooth|Tunnel'
} | Select-Object -First 1
$audio   = Get-CimInstance Win32_SoundDevice | Select-Object -First 1
$kbd     = Get-CimInstance Win32_Keyboard | Select-Object -First 1
$mouse   = Get-CimInstance Win32_PointingDevice | Select-Object -First 1
$cdrom   = Get-CimInstance Win32_CDROMDrive | Select-Object -First 1
$monitor = Get-CimInstance Win32_DesktopMonitor | Select-Object -First 1
$fans    = Get-CimInstance Win32_Fan

$cpuStr = if ($cpu) { "$($cpu.Name) — $($cpu.NumberOfCores) ядер / $($cpu.NumberOfLogicalProcessors) потоков, $($cpu.MaxClockSpeed) МГц" } else { '' }
$mbStr = if ($bb) { "$($bb.Manufacturer) $($bb.Product)" } else { '' }
$biosStr = if ($bios) { "$($bios.Manufacturer) $($bios.SMBIOSBIOSVersion) ($($bios.ReleaseDate))" } else { '' }

$ramTotal = if ($cs) { [math]::Round($cs.TotalPhysicalMemory / 1GB, 1) } else { 0 }
$ramMods = @()
foreach ($m in $ram) {
    $part = if ($m.PartNumber) { ([string]$m.PartNumber).Trim() } else { '' }
    $ramMods += "$([math]::Round($m.Capacity / 1GB)) ГБ $([string]$m.Speed) МГц $([string]$m.Manufacturer) $part"
}
$ramExtra = if ($ramMods.Count) { ' — ' + ($ramMods -join '; ') } else { '' }
$ramStr = "$ramTotal ГБ$ramExtra"

$gpuStr = (($gpus | ForEach-Object {
    "$($_.Name) (драйвер $($_.DriverVersion))"
}) -join '; ')
$diskStr = (($disks | ForEach-Object {
    "$($_.Model) — $([math]::Round($_.Size / 1GB)) ГБ, $($_.MediaType)"
}) -join '; ')
$volStr = (($volumes | ForEach-Object {
    "$($_.DeviceID) $([math]::Round($_.Size / 1GB)) ГБ (свободно $([math]::Round($_.FreeSpace / 1GB)) ГБ)"
}) -join '; ')
$netStr = if ($net) { "$($net.Name) — $([math]::Round($net.Speed / 1000000)) Мбит/с, MAC $($net.MACAddress)" } else { '' }
$audioStr = if ($audio) { "$($audio.Name) — $($audio.Manufacturer)" } else { '' }
$kbdStr = if ($kbd) { [string]$kbd.Description } else { '' }
$mouseStr = if ($mouse) { [string]$mouse.Description } else { '' }
$cdStr = if ($cdrom) { [string]$cdrom.Name } else { '' }
$monStr = if ($monitor) { [string]$monitor.Name } else { '' }
$fansStr = (($fans | ForEach-Object {
    "$($_.Name) $([math]::Round($_.CurrentSpeed)) об/мин"
}) -join '; ')
$osStr = if ($os) { "$($os.Caption) $($os.Version) (сборка $($os.BuildNumber))" } else { '' }

$info = [ordered]@{
    'Процессор'           = $cpuStr
    'Материнская плата'   = $mbStr
    'BIOS'                = $biosStr
    'Оперативная память'  = $ramStr
    'Видеокарта'          = $gpuStr
    'Звуковая карта'      = $audioStr
    'Накопители'          = $diskStr
    'Логические диски'    = $volStr
    'Сетевой адаптер'     = $netStr
    'Оптический привод'   = $cdStr
    'Монитор'             = $monStr
    'Клавиатура'          = $kbdStr
    'Мышь'                = $mouseStr
    'Охлаждение'          = $fansStr
    'Операционная система' = $osStr
}
$info | ConvertTo-Json -Compress -Depth 4
'''
    output = run_capture(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        timeout=30,
    ).strip()
    if not output:
        raise RuntimeError("PowerShell вернул пустой ответ")
    data = json.loads(output)
    if isinstance(data, list):
        data = data[0] if data else {}
    return {str(key): str(value) for key, value in data.items() if value not in (None, "")}


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, int(c))) for c in rgb))


def mix_colors(first: str, second: str, ratio: float) -> str:
    """Смешивает два hex-цвета: ratio=0 → first, ratio=1 → second."""
    a, b = _hex_to_rgb(first), _hex_to_rgb(second)
    return _rgb_to_hex(tuple(a[i] * (1 - ratio) + b[i] * ratio for i in range(3)))  # type: ignore[arg-type]


def ui_font_family() -> str:
    """Segoe UI Variable в Windows 11, иначе обычный Segoe UI."""
    try:
        families = set(tkfont.families())
        for name in ("Segoe UI Variable Text", "Segoe UI Variable Display", "Segoe UI"):
            if name in families:
                return name
    except Exception:
        pass
    return "Segoe UI"


def windows_uses_light_theme() -> bool:
    if os.name != "nt":
        return True
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return bool(value)
    except Exception:
        return True


def windows_accent_color() -> str:
    """Акцентный цвет Windows (HKCU\\DWM\\AccentColor, хранится как ABGR)."""
    if os.name != "nt":
        return "#0078D4"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as key:
            value, _ = winreg.QueryValueEx(key, "AccentColor")
            red = value & 0xFF
            green = (value >> 8) & 0xFF
            blue = (value >> 16) & 0xFF
            if red or green or blue:
                luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255.0
                highest, lowest = max(red, green, blue), min(red, green, blue)
                saturation = (highest - lowest) / highest if highest else 0.0
                # Слишком тёмный/серый акцент не читается в интерфейсе — берём синий Windows.
                if luminance < 0.22 or saturation < 0.08:
                    return "#0078D4"
                return _rgb_to_hex((red, green, blue))
    except Exception:
        pass
    return "#0078D4"


def fluent_palette(theme_key: str) -> dict[str, object]:
    """Палитра Fluent для светлой/тёмной темы."""
    system_light = theme_key == THEME_SYSTEM and windows_uses_light_theme()
    light = theme_key == THEME_LIGHT or system_light
    accent = windows_accent_color()
    if light:
        return {
            "dark": False, "bg": "#F3F3F3", "card": "#FFFFFF", "card_alt": "#EDEDED",
            "elevated": "#FFFFFF", "field": "#FFFFFF", "fg": "#1B1B1B", "muted": "#616161",
            "border": "#E1E1E1", "accent": accent, "accent_hover": mix_colors(accent, "#000000", 0.15),
            "accent_fg": "#FFFFFF", "success": "#0E7A0D", "warn": "#C4314B",
            "info": accent, "trough": "#E8E8E8", "track": "#C8C8C8",
            "disabled": "#EFEFEF", "list_fg": "#1B1B1B",
        }
    if theme_key == THEME_CREATIVE:
        # Графитовая палитра «Pro Creative / AI Dark»: DaVinci / Topaz / NVIDIA Broadcast.
        creative_accent = "#00A8E8"
        return {
            "dark": True, "bg": "#111317", "card": "#181B20", "card_alt": "#22262E",
            "elevated": "#22262E", "field": "#15181D", "fg": "#F3F4F6", "muted": "#88949E",
            "border": "#2E3440", "accent": creative_accent,
            "accent_hover": mix_colors(creative_accent, "#FFFFFF", 0.15),
            "accent_fg": "#0B1014", "success": "#76B900", "warn": "#FFB454",
            "info": creative_accent, "trough": "#0D0F12", "track": "#323842",
            "disabled": "#1B1F26", "list_fg": "#F3F4F6",
        }
    if theme_key == THEME_NORD:
        return {
            "dark": True, "bg": "#2E3440", "card": "#3B4252",
            "card_alt": "#434C5E", "elevated": "#434C5E", "field": "#2E3440",
            "fg": "#ECEFF4", "muted": "#A4B0BE", "border": "#4C566A",
            "accent": "#88C0D0", "accent_hover": "#A3D0DD", "accent_fg": "#2E3440",
            "success": "#A3BE8C", "warn": "#D08770", "info": "#81A1C1",
            "trough": "#2E3440", "track": "#4C566A", "disabled": "#3B4252",
            "list_fg": "#ECEFF4",
        }
    if theme_key == THEME_OCEAN:
        return {
            "dark": False, "bg": "#EAF2F8", "card": "#FFFFFF",
            "card_alt": "#D6E8F5", "elevated": "#F4F9FD", "field": "#FFFFFF",
            "fg": "#10334A", "muted": "#4E6E82", "border": "#BFD7E6",
            "accent": "#0078D4", "accent_hover": "#005A9E", "accent_fg": "#FFFFFF",
            "success": "#0E7A0D", "warn": "#C4314B", "info": "#0078D4",
            "trough": "#D6E8F5", "track": "#AFC9DB", "disabled": "#E4EDF4",
            "list_fg": "#10334A",
        }
    if theme_key == THEME_SOLAR:
        return {
            "dark": True, "bg": "#002B36", "card": "#073642",
            "card_alt": "#0B4350", "elevated": "#0B4350", "field": "#002B36",
            "fg": "#EEE8D5", "muted": "#93A1A1", "border": "#14505E",
            "accent": "#2AA198", "accent_hover": "#3BC4B9", "accent_fg": "#002B36",
            "success": "#859900", "warn": "#CB4B16", "info": "#268BD2",
            "trough": "#002B36", "track": "#14505E", "disabled": "#073642",
            "list_fg": "#EEE8D5",
        }
    dark_accent = mix_colors(accent, "#FFFFFF", 0.35)
    return {
        "dark": True, "bg": "#202020", "card": "#2B2B2B", "card_alt": "#383838",
        "elevated": "#333333", "field": "#1F1F1F", "fg": "#F5F5F5", "muted": "#B5B5B5",
        "border": "#3F3F46",
        "accent": dark_accent, "accent_hover": mix_colors(dark_accent, "#FFFFFF", 0.15),
        "accent_fg": "#FFFFFF", "success": "#6CCB6C", "warn": "#FF99A4",
        "info": dark_accent, "trough": "#1A1A1A", "track": "#4A4A4A",
        "disabled": "#333333", "list_fg": "#F5F5F5",
    }


def resolution_for_choice(choice: str, source_w: int, source_h: int) -> tuple[int, int]:
    mapping = {
        "1280x720": (1280, 720),
        "1920x1080": (1920, 1080),
        "2560x1440": (2560, 1440),
        "3840x2160": (3840, 2160),
    }
    for key, value in mapping.items():
        if key in choice:
            return value
    return source_w, source_h


def safe_float(value: object, default: float, low: float, high: float) -> float:
    try:
        result = float(value)  # type: ignore[arg-type]
        if math.isfinite(result):
            return min(high, max(low, result))
    except (TypeError, ValueError):
        pass
    return default


def safe_int(value: object, default: int, low: int, high: int) -> int:
    try:
        return min(high, max(low, int(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def probe_meta(ffprobe: Path, filepath: str) -> MediaMeta:
    """Возвращает метаданные видеопотока через ffprobe."""
    output = run_capture([
        str(ffprobe), "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate,r_frame_rate,nb_frames,pix_fmt,"
        "color_transfer,color_primaries,color_space,duration:format=duration",
        "-of", "json", filepath,
    ])
    document = json.loads(output)
    streams = document.get("streams", [])
    if not streams:
        raise RuntimeError("В файле не найден видеопоток")
    stream = streams[0]
    fps = parse_fraction(stream.get("avg_frame_rate")) or parse_fraction(stream.get("r_frame_rate"))
    if fps <= 0:
        raise RuntimeError("Не удалось определить FPS исходного видео")
    frames_raw = stream.get("nb_frames")
    frames = int(frames_raw) if str(frames_raw).isdigit() else 0
    meta = MediaMeta(
        w=int(stream.get("width", 0)),
        h=int(stream.get("height", 0)),
        fps=fps,
        frames=frames,
        pix=stream.get("pix_fmt", "unknown"),
        color_transfer=stream.get("color_transfer", ""),
        color_primaries=stream.get("color_primaries", ""),
        color_space=stream.get("color_space", ""),
        duration=(float(stream.get("duration") or 0)
                  or float((document.get("format") or {}).get("duration") or 0)),
    )
    if meta.w <= 0 or meta.h <= 0:
        raise RuntimeError("Некорректные размеры видео")
    return meta


@contextmanager
def temp_workdir(prefix: str = "rtx_media_master_") -> Iterator[Path]:
    """Гарантированно очищает временную директорию при любом исходе."""
    path = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class VramEstimator:
    """Эвристическая оценка требуемой видеопамяти (не фактическое показание)."""

    @staticmethod
    def calculate(
        width: int, height: int, mode: str, res_choice: str,
        has_denoise: bool, has_sharpen: bool,
    ) -> float:
        tw, th = resolution_for_choice(res_choice, int(width), int(height))
        frame_mb = (tw * th * 3.0) / (1024.0 * 1024.0)
        if mode == "rife_tensorrt":
            estimate = 500.0 + frame_mb * 30.0
        elif mode == "ai_cpu":
            estimate = 250.0 + frame_mb * 8.0
        else:
            estimate = 350.0 + frame_mb * 14.0
        if has_denoise:
            estimate += frame_mb * 2.0
        if has_sharpen:
            estimate += frame_mb
        return round(estimate, 1)


# ---------------------------------------------------------------------------
# Простой tooltip
# ---------------------------------------------------------------------------

class ToolTip:
    def __init__(self, widget, text: str, delay_ms: int = 500):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.tip = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._hide)

    def _schedule(self, _event=None):
        self._hide()
        self.tip_after = self.widget.after(self.delay_ms, self._show)

    def _show(self):
        try:
            x = self.widget.winfo_rootx() + 20
            y = self.widget.winfo_rooty() + 20
            self.tip = tk.Toplevel(self.widget)
            self.tip.wm_overrideredirect(True)
            self.tip.wm_geometry(f"+{x}+{y}")
            label = tk.Label(
                self.tip, text=self.text, justify="left",
                background="#2a2a35", foreground="#f0f0f5",
                relief="solid", borderwidth=1, font=("Segoe UI", 9),
                wraplength=300,
            )
            label.pack(ipadx=6, ipady=4)
        except Exception:
            pass

    def _hide(self, _event=None):
        try:
            if hasattr(self, "tip_after"):
                self.widget.after_cancel(self.tip_after)
        except Exception:
            pass
        if self.tip:
            self.tip.destroy()
            self.tip = None


# ---------------------------------------------------------------------------
# Основное приложение
# ---------------------------------------------------------------------------

class VideoProcessorApp:
    def __init__(self, window: Tk):
        self.window = window
        self.window.app = self
        self.accent_rail = tk.Canvas(
            window, height=3, bd=0, highlightthickness=0, takefocus=False
        )
        self.accent_rail.place(relx=0, rely=0, relwidth=1, height=3)
        self.settings = AppSettings.load()
        self.window.title(f"{APP_NAME} {APP_VERSION} — Video Interpolator")
        self.window.geometry(self.settings.geometry)
        self.window.minsize(980, 680)

        self.file_paths: list[str] = []
        self.metadata_cache: dict[str, MediaMeta] = {}
        self.failed_files: list[str] = []
        self.ui_events: queue.Queue = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.active_processes: set[subprocess.Popen] = set()
        self.process_lock = threading.Lock()
        self.cancel_event = threading.Event()
        self.is_running = False
        self.is_downloading_dependencies = False
        self.closing = False
        self.available_encoders: set[str] = set()
        self.visible_paths: list[str] = []          # то, что показано в списке с учётом поиска
        self.active_file: str | None = None
        self.inspected_path: str = ""
        self._gpu_probe_pending: bool = False
        self._last_gpu_probe: float = 0.0
        self._vram_loop_pending: bool = False
        self.current_page: str = PAGE_QUEUE
        self.nav_expanded: bool = False

        self.gpu_vendor = "UNKNOWN"
        self.gpu_name = "Не определён"
        self.gpu_arch = "Не определено"
        self.tensor_cores_available = False
        self.total_system_vram = 4096.0
        self.vram_used_mb = 0.0
        self.vram_probe_ok = False  # удалось ли прочитать реальный объём VRAM
        self.gpu_load = 0.0         # загрузка GPU в процентах (nvidia-smi)

        # UI-переменные (инициализируются из настроек)
        self.status_msg = StringVar(value="Инициализация...")
        self.progress_percent = StringVar(value="0.0%")
        self.speed_fps = StringVar(value="Скорость: —")
        self.eta_time = StringVar(value="Осталось: --:--:--")
        self.stage_text = StringVar(value="Стадия: ожидание")
        self.tensor_test_status = StringVar(value="TensorRT: не проверен")
        self.vram_meter_text = StringVar(value="Оценка видеопамяти: —")
        self.gpu_telemetry = StringVar(value="GPU: — · VRAM: —")
        self.size_stats = StringVar(value="Размер: —")

        self.processing_mode = StringVar(value=self.settings.processing_mode)
        self.target_fps = IntVar(value=self.settings.target_fps)
        self.target_res = StringVar(value=self.settings.target_res)
        self.scale_algo = StringVar(value=self.settings.scale_algo)
        self.output_codec = StringVar(value=self.settings.output_codec)
        self.profile = StringVar(value=self.settings.profile)
        self.theme = StringVar(value=self.settings.theme)
        self.nvenc_preset = StringVar(value=self.settings.nvenc_preset)
        self.audio_mode = StringVar(value=self.settings.audio_mode)
        self.audio_bitrate = StringVar(value=self.settings.audio_bitrate)
        self.quality = IntVar(value=self.settings.quality)
        self.enable_hdr_tonemap = BooleanVar(value=self.settings.enable_hdr_tonemap)
        self.limit_bitrate = BooleanVar(value=self.settings.limit_bitrate)
        self.enable_denoise = BooleanVar(value=self.settings.enable_denoise)
        self.enable_sharpen = BooleanVar(value=self.settings.enable_sharpen)
        self.sharpen_amount = DoubleVar(value=self.settings.sharpen_amount)
        self.engine_codec = StringVar(value=self.settings.engine_codec)
        self.engine_preset = StringVar(value=self.settings.engine_preset)
        self.engine_enhance = BooleanVar(value=self.settings.engine_enhance)
        self.engine_gpu = IntVar(value=self.settings.engine_gpu)

        self.detect_hardware_capabilities()
        self.apply_fluent_theme()
        self.create_widgets()
        self.show_page(PAGE_QUEUE)
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)

        # Логирование из потоков -> в UI-окно логов
        self.log_handler = UILogHandler(self.ui_events)
        logging.getLogger().addHandler(self.log_handler)

        self.window.after(400, self.verify_and_download_dependencies_bootstrap)
        self.window.after(150, self.poll_ui_events)
        self.window.after(1000, self.update_vram_meter_display)
        self.window.bind("<Control-1>", lambda _e: self.show_page(PAGE_QUEUE))
        self.window.bind("<Control-2>", lambda _e: self.show_page(PAGE_DIAG))
        self.window.bind("<Control-3>", lambda _e: self.show_page(PAGE_SETTINGS))
        self.window.bind("<Control-4>", lambda _e: self.show_page(PAGE_LOG))
        self.window.bind("<Control-t>", lambda _e: self.cycle_theme())
        self.window.bind(
            "<Control-f>",
            lambda _e: (
                self.show_page(PAGE_QUEUE),
                self.search_entry.focus_set(),
            ),
        )

    # --------------------------- hardware ---------------------------------

    def detect_hardware_capabilities(self) -> None:
        if HAS_NVML and pynvml:
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                name = pynvml.nvmlDeviceGetName(handle)
                self.gpu_name = (
                    name.decode(errors="replace") if isinstance(name, bytes) else str(name)
                )
                self.gpu_vendor = "NVIDIA"
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                self.total_system_vram = max(1.0, mem.total / (1024 * 1024))
                self.vram_used_mb = mem.used / (1024 * 1024)
                self.vram_probe_ok = True
                major, minor = pynvml.nvmlDeviceGetCudaComputeCapability(handle)
                self.gpu_arch = f"Compute Capability {major}.{minor}"
                self.tensor_cores_available = major >= 7 and "GTX" not in self.gpu_name.upper()
                return
            except Exception as exc:
                logging.warning("NVML: %s", exc)

        # pynvml часто недоступен в замороженной сборке — читаем VRAM через nvidia-smi.
        if self.detect_via_nvidia_smi():
            return

        if os.name == "nt":
            try:
                import winreg
                reg_path = (
                    r"SYSTEM\CurrentControlSet\Control\Class"
                    r"\{4d36e968-e325-11ce-bfc1-08002be10318}"
                )
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path) as key:
                    for i in range(32):
                        try:
                            sub_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, sub_name) as sub:
                                desc, _ = winreg.QueryValueEx(sub, "DriverDesc")
                            upper = str(desc).upper()
                            if "NVIDIA" in upper:
                                self.gpu_vendor, self.gpu_name = "NVIDIA", str(desc)
                                self.tensor_cores_available = "RTX" in upper
                                self.gpu_arch = "RTX" if self.tensor_cores_available else "NVIDIA"
                                break
                            if "AMD" in upper or "RADEON" in upper:
                                self.gpu_vendor, self.gpu_name = "AMD", str(desc)
                                self.gpu_arch = "Radeon"
                                break
                        except OSError:
                            continue
            except Exception as exc:
                logging.info("GPU registry detection: %s", exc)

    def detect_via_nvidia_smi(self) -> bool:
        """Возвращает имя GPU и объём VRAM через nvidia-smi (без pynvml)."""
        smi = shutil.which("nvidia-smi")
        if not smi:
            candidate = (
                Path(os.environ.get("SystemRoot", r"C:\Windows"))
                / "System32" / "nvidia-smi.exe"
            )
            if candidate.exists():
                smi = str(candidate)
        if not smi:
            return False
        try:
            output = run_capture([
                smi,
                "--query-gpu=index,name,memory.total,memory.used,compute_cap",
                "--format=csv,noheader,nounits",
            ], timeout=12)
        except Exception as exc:
            logging.info("nvidia-smi недоступен: %s", exc)
            return False
        for line in output.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 4:
                continue
            try:
                total_mb = float(parts[2])
                used_mb = float(parts[3])
            except ValueError:
                continue
            if total_mb <= 0:
                continue
            self.gpu_vendor = "NVIDIA"
            self.gpu_name = parts[1] or self.gpu_name
            self.total_system_vram = total_mb
            self.vram_used_mb = max(0.0, used_mb)
            self.vram_probe_ok = True
            if len(parts) >= 5 and parts[4]:
                self.gpu_arch = f"Compute Capability {parts[4]}"
                try:
                    major = int(float(parts[4].split(".")[0]))
                    self.tensor_cores_available = (
                        major >= 7 and "GTX" not in self.gpu_name.upper()
                    )
                except ValueError:
                    pass
            elif "RTX" in self.gpu_name.upper():
                self.tensor_cores_available = True
                self.gpu_arch = "RTX"
            logging.info("GPU через nvidia-smi: %s, %.0f МБ", self.gpu_name, total_mb)
            self.refresh_gpu_load()
            return True
        return False

    def refresh_gpu_load(self) -> None:
        """Разовый опрос загрузки GPU и занятой VRAM через nvidia-smi."""
        if not self.vram_probe_ok or self.gpu_vendor != "NVIDIA":
            return
        smi = shutil.which("nvidia-smi")
        if not smi:
            candidate = (
                Path(os.environ.get("SystemRoot", r"C:\Windows"))
                / "System32" / "nvidia-smi.exe"
            )
            if candidate.exists():
                smi = str(candidate)
        if not smi:
            return
        try:
            output = run_capture([
                smi, "--query-gpu=utilization.gpu,memory.used",
                "--format=csv,noheader,nounits",
            ], timeout=6)
            line = output.splitlines()[0] if output.splitlines() else ""
            parts = [part.strip() for part in line.split(",")]
            if len(parts) >= 1:
                self.gpu_load = max(0.0, min(100.0, float(parts[0])))
            if len(parts) >= 2:
                self.vram_used_mb = max(0.0, float(parts[1]))
        except Exception:
            pass

    def update_vram_meter_display(self) -> None:
        now = time.monotonic()
        if (
            not getattr(self, "_gpu_probe_pending", False)
            and now - getattr(self, "_last_gpu_probe", 0.0) >= 1.5
        ):
            self._last_gpu_probe = now
            self._gpu_probe_pending = True
            threading.Thread(
                target=self._gpu_probe_worker, name="GPUProbe", daemon=True
            ).start()
        width, height = 1920, 1080
        if self.file_paths:
            meta = self.metadata_cache.get(self.file_paths[0])
            if meta:
                width, height = meta.w, meta.h
        estimated = VramEstimator.calculate(
            width, height, self.processing_mode.get(), self.target_res.get(),
            bool(self.enable_denoise.get()), bool(self.enable_sharpen.get()),
        )
        percent = min(100.0, estimated / max(1.0, self.total_system_vram) * 100.0)
        actual = (
            f"Факт. занято: {self.vram_used_mb:.0f} МБ; "
            if self.gpu_vendor == "NVIDIA" and self.vram_probe_ok else ""
        )
        self.vram_meter_text.set(
            f"{actual}Оценка задачи: {estimated:.0f} МБ / "
            f"{self.total_system_vram:.0f} МБ ({percent:.1f}%)"
        )
        if hasattr(self, "vram_bar"):
            self.vram_bar.configure(value=percent)
        if hasattr(self, "gpu_telemetry"):
            if self.gpu_vendor == "NVIDIA" and self.vram_probe_ok:
                self.gpu_telemetry.set(
                    f"GPU {self.gpu_load:.0f}% · VRAM {self.vram_used_mb:.0f}/"
                    f"{self.total_system_vram:.0f} МБ"
                )
            else:
                self.gpu_telemetry.set("GPU: — · VRAM: —")
        if not self.closing and not getattr(self, "_vram_loop_pending", False):
            self._vram_loop_pending = True
            self.window.after(2000, self._vram_tick)

    def _gpu_probe_worker(self) -> None:
        """nvidia-smi в фоне: не блокирует главный поток кадров UI."""
        try:
            self.refresh_gpu_load()
            self.ui_events.put(("gpu_telemetry", self.gpu_load, self.vram_used_mb))
        except Exception:
            logging.debug("Не удалось опросить GPU", exc_info=True)
            self.ui_events.put(("gpu_telemetry", None, None))
        finally:
            self._gpu_probe_pending = False

    def _vram_tick(self) -> None:
        self._vram_loop_pending = False
        self.update_vram_meter_display()

    # --------------------------- UI style ---------------------------------

    def apply_fluent_theme(self, _event: object = None) -> None:
        """Применяет палитру и стили в духе Microsoft Fluent / Windows 11."""
        theme_key = self.theme.get() if hasattr(self, "theme") else THEME_SYSTEM
        p = fluent_palette(theme_key)
        self.colors = p
        self.font_family = ui_font_family()
        font = self.font_family
        accent = str(p["accent"])

        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.window.configure(bg=str(p["bg"]))

        self.style.configure(
            ".", background=str(p["bg"]), foreground=str(p["fg"]),
            fieldbackground=str(p["field"]), font=(font, FONT_REGISTRY["body"]),
        )
        self.style.configure("TFrame", background=str(p["bg"]))
        self.style.configure("Inner.TFrame", background=str(p["card"]))
        self.style.configure("TLabel", background=str(p["card"]), foreground=str(p["fg"]))
        self.style.configure(
            "TLabelframe", background=str(p["card"]), bordercolor=str(p["border"]),
            lightcolor=str(p["border"]), darkcolor=str(p["border"]),
        )
        self.style.configure(
            "TLabelframe.Label", background=str(p["card"]), foreground=accent,
            font=(font, 10, "bold"),
        )
        self.style.configure(
            "TButton", background=str(p["card"]), foreground=str(p["fg"]),
            bordercolor=str(p["border"]), focuscolor=accent, padding=(10, 5), relief="flat",
        )
        self.style.map(
            "TButton",
            background=[("active", str(p["card_alt"])), ("disabled", str(p["disabled"]))],
            bordercolor=[("active", accent)],
            foreground=[("disabled", str(p["muted"]))],
        )
        self.style.configure(
            "Accent.TButton", background=accent, foreground=str(p["accent_fg"]),
            bordercolor=accent, padding=(12, 6), font=(font, 9, "bold"), relief="flat",
        )
        self.style.map(
            "Accent.TButton",
            background=[("active", str(p["accent_hover"])), ("disabled", str(p["disabled"]))],
            foreground=[("disabled", str(p["muted"]))],
        )
        self.style.configure(
            "Danger.TButton", background=str(p["card"]), foreground=str(p["warn"]),
            bordercolor=str(p["border"]), padding=(10, 5), relief="flat",
        )
        self.style.map(
            "Danger.TButton",
            background=[("active", mix_colors(str(p["warn"]), str(p["card"]), 0.85))],
            foreground=[("disabled", str(p["muted"]))],
        )
        self.style.configure(
            "TCheckbutton", background=str(p["bg"]), foreground=str(p["fg"]),
            indicatorcolor=accent, selectcolor=str(p["field"]), focuscolor=str(p["bg"]),
        )
        self.style.map(
            "TCheckbutton",
            background=[("active", str(p["bg"]))],
            foreground=[("disabled", str(p["muted"]))],
        )
        self.style.configure(
            "TRadiobutton", background=str(p["bg"]), foreground=str(p["fg"]),
            indicatorcolor=accent, focuscolor=str(p["bg"]),
        )
        self.style.map(
            "TRadiobutton",
            background=[("active", str(p["bg"]))],
            foreground=[("disabled", str(p["muted"]))],
        )
        self.style.configure(
            "TCombobox", fieldbackground=str(p["field"]), background=str(p["card"]),
            foreground=str(p["fg"]), arrowcolor=str(p["muted"]),
            bordercolor=str(p["border"]), padding=4,
        )
        self.style.map(
            "TCombobox",
            fieldbackground=[("disabled", str(p["disabled"]))],
            foreground=[("disabled", str(p["muted"]))],
        )
        self.style.configure(
            "TEntry", fieldbackground=str(p["field"]), foreground=str(p["fg"]),
            bordercolor=str(p["border"]),
        )
        scroll_thumb = mix_colors(str(p["track"]), str(p["accent"]), 0.45)
        self.style.configure(
            "TScrollbar", background=scroll_thumb, troughcolor=str(p["card"]),
            bordercolor=str(p["border"]), arrowcolor=str(p["muted"]),
            width=12, arrowsize=0, gripcount=1, relief="flat",
        )
        self.style.configure("TSeparator", background=str(p["border"]))
        for style_name, color in (
            ("Horizontal.TProgressbar", accent),
            ("Vram.Horizontal.TProgressbar", accent),
        ):
            self.style.configure(
                style_name, background=color, troughcolor=str(p["trough"]),
                bordercolor=str(p["trough"]), thickness=8,
            )
        for style_name, color in (
            ("Good.TLabel", str(p["success"])),
            ("Accent.TLabel", accent),
            ("Info.TLabel", str(p["info"])),
            ("Muted.TLabel", str(p["muted"])),
        ):
            self.style.configure(style_name, background=str(p["card"]), foreground=color)

        # Стили UWP/WinUI-подобной оболочки: карточки, панель навигации, CommandBar.
        self.style.configure(
            "Card.TFrame", background=str(p["card"]), bordercolor=str(p["border"]),
            relief="flat", borderwidth=1,
        )
        self.style.configure(
            "Card.TLabelframe", background=str(p["card"]), bordercolor=str(p["border"]),
            lightcolor=str(p["border"]), darkcolor=str(p["border"]),
        )
        self.style.configure(
            "Card.TLabelframe.Label", background=str(p["card"]), foreground=accent,
            font=(font, 10, "bold"),
        )
        self.style.configure(
            "Header.TLabel", background=str(p["card"]), foreground=str(p["fg"]),
            font=(font, FONT_REGISTRY["header"], "bold"),
        )
        self.style.configure(
            "Subtitle.TLabel", background=str(p["card"]), foreground=str(p["fg"]),
            font=(font, FONT_REGISTRY["subtitle"], "bold"),
        )
        self.style.configure(
            "Caption.TLabel", background=str(p["elevated"]), foreground=str(p["muted"]),
            font=(font, FONT_REGISTRY["caption"]),
        )
        self.style.configure(
            "Value.TLabel", background=str(p["elevated"]), foreground=str(p["fg"]),
            font=(font, FONT_REGISTRY["subtitle"], "bold"),
        )
        self.style.configure(
            "Info.Treeview", background=str(p["card"]), fieldbackground=str(p["card"]),
            foreground=str(p["fg"]), bordercolor=str(p["border"]), rowheight=24,
        )
        self.style.configure(
            "Info.Treeview.Heading", background=str(p["card_alt"]),
            foreground=str(p["fg"]), font=(font, 9, "bold"), relief="flat",
        )
        self.style.map(
            "Info.Treeview",
            background=[("selected", accent)],
            foreground=[("selected", str(p["accent_fg"]))],
        )
        self.style.configure(
            "Tool.TButton", background=str(p["card"]), foreground=str(p["fg"]),
            bordercolor=str(p["border"]), padding=(6, 8), font=(font, 11),
            relief="flat", width=3,
        )
        self.style.map(
            "Tool.TButton",
            background=[("active", str(p["card_alt"])), ("disabled", str(p["disabled"]))],
            foreground=[("disabled", str(p["muted"]))],
        )
        self.style.configure(
            "Nav.TButton", background=str(p["card"]), foreground=str(p["muted"]),
            bordercolor=str(p["card"]), padding=(6, 8), font=(font, FONT_REGISTRY["nav"]),
            relief="flat", width=3,
        )
        self.style.map(
            "Nav.TButton",
            background=[("active", str(p["card_alt"]))],
            foreground=[("active", accent)],
        )
        # Активная вкладка — тёмная плашка; акцент вынесен отдельной полоской-индикатором.
        self.style.configure(
            "NavActive.TButton", background=str(p["card_alt"]), foreground=accent,
            bordercolor=str(p["border"]), padding=(6, 8), font=(font, FONT_REGISTRY["nav"]),
            relief="flat", width=3,
        )
        self.style.configure(
            "Command.TButton", background=str(p["card"]), foreground=str(p["fg"]),
            bordercolor=str(p["border"]), padding=(6, 8), font=(font, FONT_REGISTRY["body"]),
            relief="flat", width=9,
        )
        self.style.map(
            "Command.TButton",
            background=[("active", str(p["card_alt"])), ("disabled", str(p["disabled"]))],
            foreground=[("disabled", str(p["muted"]))],
        )
        self.style.configure(
            "CommandAccent.TButton", background=accent, foreground=str(p["accent_fg"]),
            bordercolor=accent, padding=(6, 8), font=(font, 9, "bold"),
            relief="flat", width=9,
        )
        self.style.map(
            "CommandAccent.TButton",
            background=[("active", str(p["accent_hover"])), ("disabled", str(p["disabled"]))],
            foreground=[("disabled", str(p["muted"]))],
        )
        self.style.configure(
            "Search.TEntry", fieldbackground=str(p["field"]), foreground=str(p["fg"]),
            bordercolor=str(p["border"]), focuscolor=str(p["border"]),
            insertcolor=str(p["fg"]), relief="flat", padding=(8, 6),
        )

        # Обновляем не-ttk виджеты, у которых цвета задаются напрямую.
        if hasattr(self, "file_listbox"):
            self.file_listbox.configure(
                bg=str(p["field"]), fg=str(p["list_fg"]),
                selectbackground=accent, selectforeground=str(p["accent_fg"]),
                highlightbackground=str(p["border"]),
            )
        if hasattr(self, "log_text"):
            self.log_text.configure(
                bg=str(p["field"]), fg=str(p["fg"]), insertbackground=str(p["fg"]),
                highlightbackground=str(p["border"]),
            )
        if hasattr(self, "log_scroll"):
            self.log_scroll.configure(
                bg=str(p["track"]), troughcolor=str(p["card"]),
                activebackground=str(p["card_alt"]), width=8,
                relief="flat", borderwidth=0,
            )
        if hasattr(self, "settings_scroll"):
            self.settings_scroll.configure(
                bg=str(p["track"]), troughcolor=str(p["card"]),
                activebackground=str(p["card_alt"]), width=14,
                relief="flat", borderwidth=0,
            )
        if hasattr(self, "param_canvas"):
            self.param_canvas.configure(bg=str(p["card"]))
        if hasattr(self, "scale_sharpen"):
            self.scale_sharpen.configure(
                bg=str(p["bg"]), fg=str(p["fg"]), troughcolor=str(p["track"]),
                activebackground=accent, highlightbackground=str(p["bg"]),
            )
        if hasattr(self, "nav_indicator"):
            self.nav_indicator.configure(bg=str(p["accent"]))
        if hasattr(self, "_refresh_dynamic_colors"):
            self._refresh_dynamic_colors()
        if hasattr(self, "_paint_accent_rail"):
            self._paint_accent_rail()
        if hasattr(self, "_sync_scrollregion"):
            self._sync_scrollregion()
        self.apply_window_effects(bool(p["dark"]))
        # Тема применяется до отображения окна — повторяем после его создания.
        self.window.after(250, lambda: self.apply_window_effects(bool(p["dark"])))

    def apply_window_effects(self, dark: bool) -> None:
        """Скруглённые углы, тёмный заголовок и Mica-подложка (Windows 11)."""
        if os.name != "nt" or not hasattr(ctypes, "windll"):
            return
        try:
            hwnd = int(self.window.frame(), 16)
            dwm = ctypes.windll.dwmapi
            attributes = (
                (20, dark),      # DWMWA_USE_IMMERSIVE_DARK_MODE
                (19, dark),      # то же для старых сборок Windows 10
                (33, 2),         # DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND
                (38, 2),         # DWMWA_SYSTEMBACKDROP_TYPE = DWMSBT_MAINWINDOW (Mica)
            )
            for attribute, value in attributes:
                value_ref = ctypes.c_int(int(value))
                dwm.DwmSetWindowAttribute(
                    ctypes.c_void_p(hwnd), ctypes.c_int(attribute),
                    ctypes.byref(value_ref), ctypes.sizeof(value_ref),
                )
        except Exception as exc:
            logging.info("DWM window effects недоступны: %s", exc)

    def on_theme_changed(self, _event: object = None) -> None:
        self.apply_fluent_theme()
        self.save_current_settings()

    def _hex_to_rgb(self, value: str) -> tuple[int, int, int]:
        value = str(value).lstrip("#")
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))

    def _rgb_to_hex(self, rgb: tuple[int, int, int]) -> str:
        return "#{:02X}{:02X}{:02X}".format(*rgb)

    def _paint_accent_rail(self) -> None:
        rail = getattr(self, "accent_rail", None)
        if rail is None:
            return
        rail.delete("all")
        palette = getattr(self, "colors", {})
        accent = self._hex_to_rgb(str(palette.get("accent", "#00A8E8")))
        base = self._hex_to_rgb(str(palette.get("card", "#181B20")))
        width = max(1, rail.winfo_width())
        steps = max(1, min(96, width // 4))
        for i in range(steps):
            color = self._rgb_to_hex(tuple(
                round(accent[j] + (base[j] - accent[j]) * i / steps)
                for j in range(3)
            ))
            rail.create_rectangle(
                width * i / steps, 0, width * (i + 1) / steps + 1, 3,
                fill=color, outline="",
            )

    def _sync_scrollregion(self) -> None:
        canvas = getattr(self, "param_canvas", None)
        if canvas is None:
            return
        try:
            bbox = canvas.bbox("all")
        except tk.TclError:
            return
        if bbox is not None:
            canvas.configure(scrollregion=bbox)

    def _on_settings_wheel(self, event) -> str:
        canvas = getattr(self, "param_canvas", None)
        if canvas is not None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def _bind_settings_wheel(self) -> None:
        canvas = getattr(self, "param_canvas", None)
        if canvas is None:
            return

        def bind_tree(widget) -> None:
            widget.bind("<MouseWheel>", self._on_settings_wheel)
            for child in widget.winfo_children():
                bind_tree(child)

        bind_tree(canvas)

    def _refresh_dynamic_colors(self) -> None:
        palette = getattr(self, "colors", {})
        hint = getattr(self, "drop_hint", None)
        if hint is not None:
            for item in hint.find_all():
                kind = hint.type(item)
                if kind == "rectangle":
                    hint.itemconfigure(item, outline=str(palette.get("accent")))
                elif kind == "text":
                    hint.itemconfigure(item, fill=str(palette.get("muted")))
        for frame in getattr(self, "inspect_cards", []):
            try:
                frame.configure(bg=str(palette.get("card")))
            except tk.TclError:
                pass

    def command_button(self, parent, icon: str, label: str, command=None,
                       style: str = "Command.TButton", tooltip: str | None = None,
                       two_line: bool = True, width: int = 9):
        """Кнопка CommandBar: пиктограмма над подписью либо только пиктограмма."""
        button = ttk.Button(
            parent, text=(f"{icon}\n{label}" if two_line else icon),
            style=style, command=command, width=width,
        )
        if tooltip:
            ToolTip(button, tooltip)
        return button

    def toggle_nav(self) -> None:
        """Сворачивание/разворачивание левой панели навигации."""
        self.nav_expanded = not self.nav_expanded
        self.nav_frame.configure(width=(190 if self.nav_expanded else 64))
        for _page, (button, icon, label) in self.nav_buttons.items():
            button.configure(
                text=(f"{icon}  {label}" if self.nav_expanded else icon),
                width=(16 if self.nav_expanded else 3),
            )
        self.show_page(self.current_page)

    def show_page(self, page: str) -> None:
        """Переключение страницы NavigationView."""
        if page not in self.pages:
            return
        self.current_page = page
        self.pages[page].tkraise()
        self.page_title.configure(text=PAGE_TITLES.get(page, page))
        for name, (button, _icon, _label) in self.nav_buttons.items():
            button.configure(
                style=("NavActive.TButton" if name == page else "Nav.TButton")
            )
        if hasattr(self, "nav_indicator"):
            self.window.update_idletasks()
            self.window.update_idletasks()
            button = self.nav_buttons[page][0]
            self.nav_indicator.place(
                x=0,
                y=max(0, button.winfo_y() + 2),
                height=max(8, button.winfo_height() - 4),
            )
        if page == PAGE_SETTINGS and hasattr(self, "param_canvas"):
            self.window.update_idletasks()
            region = self.param_canvas.bbox("all")
            if region:
                self.param_canvas.configure(scrollregion=region)

    def cycle_theme(self) -> None:
        """Быстрое переключение Светлая/Тёмная/Как в Windows."""
        current = self.theme.get()
        index = THEME_CHOICES.index(current) if current in THEME_CHOICES else 0
        self.theme.set(THEME_CHOICES[(index + 1) % len(THEME_CHOICES)])
        self.on_theme_changed()
        self.status_msg.set(f"Тема оформления: {self.theme.get()}")

    def create_widgets(self) -> None:
        p = self.colors
        font = self.font_family
        root = self.window
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        # --- Верхняя панель: заголовок страницы, поиск и CommandBar ---
        header = ttk.Frame(root, style="Card.TFrame", padding=(10, 6))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(2, weight=1)

        self.nav_toggle = ttk.Button(
            header, text=ICON_MENU, style="Tool.TButton",
            command=self.toggle_nav, width=3,
        )
        self.nav_toggle.grid(row=0, column=0, padx=(0, 12))
        ToolTip(self.nav_toggle, "Показать или скрыть панель навигации")

        self.page_title = ttk.Label(
            header, text=PAGE_TITLES[PAGE_QUEUE], style="Header.TLabel"
        )
        self.page_title.grid(row=0, column=1, sticky="w")

        search_box = ttk.Frame(header)
        search_box.grid(row=0, column=2, sticky="ew", padx=24)
        search_box.columnconfigure(0, weight=1)
        self.search_var = StringVar(value=SEARCH_PLACEHOLDER)
        self.search_entry = ttk.Entry(
            search_box, textvariable=self.search_var, style="Search.TEntry",
            foreground=p["muted"],
        )
        self.search_entry.grid(row=0, column=0, sticky="ew")
        self.search_var.trace_add("write", lambda *_: self.refresh_listbox())
        self.search_entry.bind("<FocusIn>", self.on_search_focus_in)
        self.search_entry.bind("<FocusOut>", self.on_search_focus_out)
        ToolTip(self.search_entry, "Поиск по имени файла в очереди")

        commands = ttk.Frame(header)
        commands.grid(row=0, column=3, sticky="e")
        self.command_button(
            commands, ICON_ADD, "Добавить", self.browse_files,
            tooltip="Добавить видеофайлы в очередь",
        ).pack(side="left", padx=2)
        self.command_button(
            commands, ICON_REMOVE, "Удалить", self.remove_selected,
            tooltip="Удалить выбранные файлы",
        ).pack(side="left", padx=2)
        self.btn_start = self.command_button(
            commands, ICON_START, "Старт", self.start_processing_thread,
            style="CommandAccent.TButton", tooltip="Запустить обработку очереди",
        )
        self.btn_start.pack(side="left", padx=2)
        self.btn_stop = self.command_button(
            commands, ICON_STOP, "Отмена", self.stop_processing,
            tooltip="Остановить обработку",
        )
        self.btn_stop.pack(side="left", padx=2)
        self.command_button(
            commands, ICON_CLEAR, "", self.clear_queue, style="Tool.TButton",
            two_line=False, width=3, tooltip="Очистить очередь",
        ).pack(side="left", padx=2)
        self.command_button(
            commands, ICON_REFRESH, "", self.refresh_listbox, style="Tool.TButton",
            two_line=False, width=3, tooltip="Обновить список",
        ).pack(side="left", padx=2)
        self.btn_retry = self.command_button(
            commands, ICON_RETRY, "", self.retry_failed, style="Tool.TButton",
            two_line=False, width=3, tooltip="Повторить неудачные файлы",
        )
        self.btn_retry.pack(side="left", padx=2)
        self.command_button(
            commands, ICON_THEME, "", self.cycle_theme, style="Tool.TButton",
            two_line=False, width=3, tooltip="Переключить тему оформления",
        ).pack(side="left", padx=2)
        self.btn_stop.configure(state="disabled")
        self.btn_retry.configure(state="disabled")

        # --- Тело: навигация + страницы ---
        body = ttk.Frame(root)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self.nav_frame = ttk.Frame(body, style="Card.TFrame", width=64)
        self.nav_frame.grid(row=0, column=0, sticky="ns")
        self.nav_frame.grid_propagate(False)
        self.nav_indicator = tk.Frame(
            self.nav_frame, bg=str(self.colors["accent"]), width=3
        )
        self.nav_buttons = {}
        nav_specs = (
            (PAGE_QUEUE, ICON_QUEUE, "Очередь"),
            (PAGE_DIAG, ICON_DIAG, "Диагностика"),
            (PAGE_SETTINGS, ICON_SETTINGS, "Настройки"),
            (PAGE_LOG, ICON_LOG, "Журнал"),
        )
        for index, (page, icon, label) in enumerate(nav_specs):
            button = ttk.Button(
                self.nav_frame, text=icon, style="Nav.TButton", width=3,
                command=lambda pg=page: self.show_page(pg),
            )
            button.pack(fill="x", padx=6, pady=(8 if index == 0 else 2, 2))
            self.nav_buttons[page] = (button, icon, label)
            ToolTip(button, label)
        ttk.Frame(self.nav_frame).pack(fill="both", expand=True)
        ttk.Label(self.nav_frame, text=APP_VERSION, font=(font, FONT_REGISTRY["caption"])).pack(pady=8)

        self.content = ttk.Frame(body, padding=(14, 12))
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)
        self.pages = {}
        for page in (PAGE_QUEUE, PAGE_DIAG, PAGE_SETTINGS, PAGE_LOG):
            frame = ttk.Frame(self.content, style="Card.TFrame")
            frame.grid(row=0, column=0, sticky="nsew")
            self.pages[page] = frame

        # --- Страница «Очередь видео» ---
        qpage = self.pages[PAGE_QUEUE]
        qpage.columnconfigure(0, weight=1)
        qpage.rowconfigure(1, weight=1)
        qhead = ttk.Frame(qpage)
        qhead.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(qhead, text="Файлы в очереди", style="Subtitle.TLabel").pack(anchor="w")
        self.queue_count = ttk.Label(qhead, text="0 файлов", style="Muted.TLabel")
        self.queue_count.pack(anchor="w")

        list_card = ttk.Frame(qpage, style="Card.TFrame", padding=6)
        list_card.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        list_card.columnconfigure(0, weight=1)
        list_card.rowconfigure(0, weight=1)
        self.file_listbox = Listbox(
            list_card, font=("Consolas", 10), bg=str(p["field"]),
            fg=str(p["list_fg"]), borderwidth=0, highlightthickness=0,
            selectbackground=str(p["accent"]), selectforeground=str(p["accent_fg"]),
            activestyle="none",
        )
        self.file_listbox.grid(row=0, column=0, sticky="nsew")
        self.file_listbox.bind("<<ListboxSelect>>", self.on_file_select_inspect)
        list_scroll = ttk.Scrollbar(
            list_card, orient="vertical", command=self.file_listbox.yview
        )
        list_scroll.grid(row=0, column=1, sticky="ns")
        self.list_scroll = list_scroll
        self.file_listbox.configure(yscrollcommand=list_scroll.set)

        # Пунктирная заглушка пустой очереди (Drag & Drop).
        self.drop_hint = Canvas(
            list_card, bg=str(p["card"]), highlightthickness=0, bd=0
        )
        hint_rect = self.drop_hint.create_rectangle(
            8, 8, 252, 92, outline=str(p["border"]), dash=(6, 4), width=1
        )
        hint_title = self.drop_hint.create_text(
            130, 36, text=f"{ICON_ADD}  Перетащите видеофайлы сюда",
            fill=str(p["fg"]), font=(font, 10, "bold"),
        )
        hint_sub = self.drop_hint.create_text(
            130, 64, text="MP4, MKV, MOV — или нажмите, чтобы выбрать",
            fill=str(p["muted"]), font=(font, FONT_REGISTRY["caption"]),
        )

        def layout_drop_hint(_event=None) -> None:
            width = self.drop_hint.winfo_width()
            height = self.drop_hint.winfo_height()
            if width < 60 or height < 60:
                return
            cx, cy = width / 2, height / 2
            self.drop_hint.coords(hint_rect, 8, 8, width - 8, height - 8)
            self.drop_hint.coords(hint_title, cx, cy - 14)
            self.drop_hint.coords(hint_sub, cx, cy + 14)

        self.drop_hint.bind("<Configure>", layout_drop_hint)
        self.drop_hint.bind("<Button-1>", lambda _e: self.browse_files())

        # Индивидуальный прогресс обрабатываемого файла.
        self.file_progress = ttk.Progressbar(
            list_card, maximum=100, style="Horizontal.TProgressbar"
        )

        insp = ttk.LabelFrame(
            qpage, text=" Инспектор медиафайла ", padding=12, style="Card.TLabelframe"
        )
        insp.grid(row=2, column=0, sticky="ew")
        insp.columnconfigure(0, weight=1)
        insp.columnconfigure(1, weight=1)

        def add_inspect_card(row: int, col: int, caption: str, attr: str) -> None:
            card = tk.Frame(
                insp, bg=str(p["elevated"]), highlightbackground=str(p["border"]),
                highlightthickness=1,
            )
            padx = (0, 6) if col == 0 else (6, 0)
            card.grid(row=row, column=col, sticky="nsew", padx=padx, pady=(0, 6))
            ttk.Label(card, text=caption, style="Caption.TLabel").pack(anchor="w")
            value = ttk.Label(card, text="—", style="Value.TLabel")
            value.pack(anchor="w", pady=(2, 0))
            setattr(self, attr, value)

        add_inspect_card(0, 0, "РАЗРЕШЕНИЕ", "lbl_inspect_res")
        add_inspect_card(0, 1, "ИСХОДНЫЙ FPS", "lbl_inspect_fps")
        add_inspect_card(1, 0, "КАДРОВ", "lbl_inspect_frames")
        add_inspect_card(1, 1, "ФОРМАТ ПИКСЕЛЕЙ", "lbl_inspect_pix")

        # --- Страница «Диагностика» ---
        dpage = self.pages[PAGE_DIAG]
        dpage.columnconfigure(0, weight=1)
        dpage.rowconfigure(0, weight=1)
        diag_card = ttk.LabelFrame(
            dpage, text=" Комплектующие ПК ", padding=14,
            style="Card.TLabelframe",
        )
        diag_card.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        diag_card.columnconfigure(0, weight=1)
        diag_card.rowconfigure(2, weight=1)
        ttk.Label(
            diag_card, text=f"GPU: {self.gpu_name}", font=(font, 11, "bold")
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            diag_card,
            text=(
                f"Архитектура: {self.gpu_arch} | Tensor Cores: "
                f"{'есть' if self.tensor_cores_available else 'не подтверждены'}"
            ),
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        tree_frame = ttk.Frame(diag_card)
        tree_frame.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self.system_info_tree = ttk.Treeview(
            tree_frame, columns=("component", "value"), show="headings",
            style="Info.Treeview", height=12,
        )
        self.system_info_tree.heading("component", text="Компонент")
        self.system_info_tree.heading("value", text="Значение")
        self.system_info_tree.column("component", width=170, anchor="w", stretch=False)
        self.system_info_tree.column("value", width=520, anchor="w", stretch=True)
        self.system_info_tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll = ttk.Scrollbar(
            tree_frame, orient="vertical", command=self.system_info_tree.yview
        )
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.system_info_tree.configure(yscrollcommand=tree_scroll.set)

        diag_row = ttk.Frame(diag_card)
        diag_row.grid(row=3, column=0, sticky="w", pady=(12, 0))
        ttk.Button(
            diag_row, text="Проверить TensorRT",
            command=self.run_tensor_cores_stress_test,
        ).pack(side="left")
        ttk.Button(
            diag_row, text="Обновить состав", command=self.refresh_system_info
        ).pack(side="left", padx=8)
        ttk.Label(diag_row, textvariable=self.tensor_test_status).pack(side="left", padx=12)

        vram_card = ttk.LabelFrame(
            dpage, text=" Видеопамять ", padding=14, style="Card.TLabelframe"
        )
        vram_card.grid(row=1, column=0, sticky="ew")
        ttk.Label(
            vram_card, textvariable=self.vram_meter_text, wraplength=640
        ).pack(anchor="w")
        self.vram_bar = ttk.Progressbar(
            vram_card, maximum=100, style="Vram.Horizontal.TProgressbar"
        )
        self.vram_bar.pack(fill="x", pady=(10, 0))

        # --- Страница «Параметры обработки» ---
        spage = self.pages[PAGE_SETTINGS]
        self.param_canvas = Canvas(
            spage, bg=str(p["bg"]), borderwidth=0, highlightthickness=0
        )
        spage.columnconfigure(0, weight=1)
        spage.rowconfigure(0, weight=1)
        self.param_canvas.grid(row=0, column=0, sticky="nsew")
        settings_scroll = Scrollbar(
            spage, orient="vertical", command=self.param_canvas.yview,
            width=14, bg=str(p["track"]), troughcolor=str(p["card"]),
            activebackground=str(p["card_alt"]), relief="flat", borderwidth=0,
        )
        settings_scroll.grid(row=0, column=1, sticky="ns")
        self.settings_scroll = settings_scroll
        self.param_canvas.configure(yscrollcommand=settings_scroll.set)
        controls = ttk.Frame(self.param_canvas, padding=10)
        canvas_window = self.param_canvas.create_window(
            (0, 0), window=controls, anchor="nw"
        )
        controls.bind(
            "<Configure>",
            lambda _e: self.param_canvas.configure(
                scrollregion=self.param_canvas.bbox("all")
            ),
        )
        self.param_canvas.bind(
            "<Configure>",
            lambda e: (
                self.param_canvas.itemconfigure(canvas_window, width=e.width),
                self._sync_scrollregion()
            ),
        )

        theme_card = ttk.LabelFrame(
            controls, text=" Оформление ", padding=12, style="Card.TLabelframe"
        )
        theme_card.pack(fill="x", pady=(0, 10))
        ttk.Label(theme_card, text="Тема оформления:").pack(anchor="w")
        theme_box = ttk.Combobox(
            theme_card, textvariable=self.theme, values=THEME_CHOICES,
            width=30, state="readonly",
        )
        theme_box.pack(fill="x", pady=(4, 0))
        theme_box.bind("<<ComboboxSelected>>", self.on_theme_changed)
        ToolTip(theme_box, "«Как в Windows» синхронизирует тему с системной настройкой.")

        profile_card = ttk.LabelFrame(
            controls, text=" Профиль размера и качества ", padding=12,
            style="Card.TLabelframe",
        )
        profile_card.pack(fill="x", pady=(0, 10))
        ttk.Label(profile_card, text="Профиль:").pack(anchor="w")
        profile_box = ttk.Combobox(
            profile_card, textvariable=self.profile, values=PROFILE_CHOICES,
            width=38, state="readonly",
        )
        profile_box.pack(fill="x", pady=(4, 0))
        profile_box.bind("<<ComboboxSelected>>", lambda _e: self.apply_profile())
        ToolTip(profile_box, (
            "Оптимально: HEVC, CQ 21, p7, лимит битрейта — "
            "малый файл при визуально высоком качестве.\n"
            "AV1 даёт ещё меньший размер, но рендер на CPU очень медленный."
        ))

        video_card = ttk.LabelFrame(
            controls, text=" Видео ", padding=12, style="Card.TLabelframe"
        )
        video_card.pack(fill="x", pady=(0, 10))
        ttk.Label(
            video_card, text="Режим обработки:", font=(font, 9, "bold")
        ).pack(anchor="w")
        for value, label in MODE_LABELS.items():
            ttk.Radiobutton(
                video_card, text=label, variable=self.processing_mode, value=value,
                command=self.on_settings_changed,
            ).pack(anchor="w", pady=2)
        ttk.Separator(video_card).pack(fill="x", pady=8)

        grid = ttk.Frame(video_card)
        grid.pack(fill="x")
        rows = (
            ("Целевой FPS:", self.target_fps, FPS_CHOICES, 12,
             lambda _e: self.on_settings_changed()),
            ("Разрешение:", self.target_res,
             [value for _, value in RESOLUTION_CHOICES], 18,
             lambda _e: self.on_settings_changed()),
            ("Алгоритм масштабирования:", self.scale_algo, SCALE_CHOICES, 12, None),
            ("Видеокодек:", self.output_codec, CODEC_CHOICES, 12,
             lambda _e: self.on_manual_quality_change()),
            ("NVENC preset:", self.nvenc_preset, NVENC_PRESET_CHOICES, 15,
             lambda _e: self.on_manual_quality_change()),
            ("Качество (CQ/CRF):", self.quality, QUALITY_CHOICES, 12,
             lambda _e: self.on_manual_quality_change()),
        )
        for row, (label, variable, values, width, callback) in enumerate(rows):
            ttk.Label(grid, text=label).grid(row=row, column=0, sticky="w", pady=4)
            box = ttk.Combobox(
                grid, textvariable=variable, values=values,
                width=width, state="readonly",
            )
            box.grid(row=row, column=1, sticky="w", padx=8)
            if callback:
                box.bind("<<ComboboxSelected>>", callback)
        ToolTip(
            grid, "Меньше CQ/CRF = лучше качество и больше размер файла."
        )

        engine_card = ttk.LabelFrame(
            controls, text=" Движок v3.5 (RIFE + современные кодеки) ", padding=12,
            style="Card.TLabelframe",
        )
        engine_card.pack(fill="x", pady=(0, 10))
        engine_grid = ttk.Frame(engine_card)
        engine_grid.pack(fill="x")
        engine_rows = (
            ("Кодек v3.5:", self.engine_codec, ENGINE_CODEC_CHOICES, 12),
            ("Пресет v3.5:", self.engine_preset, ENGINE_PRESET_CHOICES, 12),
            ("GPU Vulkan (индекс):", self.engine_gpu, list(range(0, 8)), 12),
        )
        for row, (label, variable, values, width) in enumerate(engine_rows):
            ttk.Label(engine_grid, text=label).grid(row=row, column=0, sticky="w", pady=4)
            box = ttk.Combobox(
                engine_grid, textvariable=variable, values=values,
                width=width, state="readonly",
            )
            box.grid(row=row, column=1, sticky="w", padx=8)
        ttk.Checkbutton(
            engine_card, text="Enhance (denoise + CAS, 10-bit)",
            variable=self.engine_enhance, command=self.on_settings_changed,
        ).pack(anchor="w", pady=(6, 0))
        ToolTip(engine_card, (
            "Основной конвейер программы. Использует RIFE v4.6 с перекрытием чанков\n"
            "и scene-cut, точный A/V sync и 10-bit AV1/HEVC/VVC/H.264.\n"
            "CLI-режим доступен только как внутренний бэкенд: --headless."
        ))

        audio_card = ttk.LabelFrame(
            controls, text=" Аудио ", padding=12, style="Card.TLabelframe"
        )
        audio_card.pack(fill="x", pady=(0, 10))
        audio_grid = ttk.Frame(audio_card)
        audio_grid.pack(fill="x")
        ttk.Label(audio_grid, text="Аудио:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Combobox(
            audio_grid, textvariable=self.audio_mode, values=AUDIO_MODE_CHOICES,
            width=12, state="readonly",
        ).grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(audio_grid, text="Битрейт AAC:").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Combobox(
            audio_grid, textvariable=self.audio_bitrate, values=AUDIO_BITRATE_CHOICES,
            width=12, state="readonly",
        ).grid(row=1, column=1, sticky="w", padx=8)

        extra_card = ttk.LabelFrame(
            controls, text=" Дополнительная обработка ", padding=12,
            style="Card.TLabelframe",
        )
        extra_card.pack(fill="x")
        ttk.Checkbutton(
            extra_card, text="HDR → SDR tone mapping (только HDR)",
            variable=self.enable_hdr_tonemap, command=self.on_settings_changed,
        ).pack(anchor="w", pady=2)
        ttk.Checkbutton(
            extra_card, text="Ограничить битрейт", variable=self.limit_bitrate,
            command=self.on_manual_quality_change,
        ).pack(anchor="w", pady=2)
        ttk.Checkbutton(
            extra_card, text="Денойзер HQDN3D", variable=self.enable_denoise,
            command=self.on_settings_changed,
        ).pack(anchor="w", pady=2)
        ttk.Checkbutton(
            extra_card, text="Резкость CAS", variable=self.enable_sharpen,
            command=self.toggle_sharpen_slider,
        ).pack(anchor="w", pady=2)
        self.slider_frame = ttk.Frame(extra_card)
        ttk.Label(self.slider_frame, text="Сила резкости:").pack(side="left")
        self.scale_sharpen = Scale(
            self.slider_frame, from_=0.0, to=1.0, resolution=0.1,
            variable=self.sharpen_amount, orient=HORIZONTAL, length=140,
            bg=str(p["bg"]), fg=str(p["fg"]), highlightthickness=0, bd=0,
            command=lambda _v: self.on_settings_changed(),
        )
        self.scale_sharpen.pack(side="left", padx=8)
        if self.enable_sharpen.get():
            self.slider_frame.pack(fill="x", pady=3)

        # Явно пересчитываем область прокрутки и включаем колесо мыши.
        self._sync_scrollregion()
        self.param_canvas.bind(
            "<MouseWheel>",
            lambda e: self.param_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"),
        )

        # --- Страница «Журнал обработки» ---
        lpage = self.pages[PAGE_LOG]
        log_card = ttk.LabelFrame(
            lpage, text=" Журнал обработки ", padding=8, style="Card.TLabelframe"
        )
        log_card.pack(fill="both", expand=True)
        self.log_text = Text(
            log_card, height=12, bg=str(p["field"]), fg=str(p["fg"]),
            insertbackground=str(p["fg"]), font=("Consolas", 9), wrap="word",
            borderwidth=0, highlightthickness=0,
        )
        self.log_scroll = Scrollbar(
            log_card, orient="vertical", command=self.log_text.yview,
            bg=str(p["card"]), troughcolor=str(p["card"]),
            activebackground=str(p["card_alt"]),
        )
        self.log_text.configure(yscrollcommand=self.log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_scroll.pack(side="right", fill="y")
        self.log_text.configure(state=DISABLED)
        ttk.Button(
            log_card, text="Очистить лог", command=self.clear_log
        ).pack(side="bottom", anchor="e", pady=(6, 0))

        # --- Нижняя строка состояния и общий прогресс ---
        status = ttk.Frame(root, padding=(12, 6))
        status.grid(row=2, column=0, sticky="ew")
        status.columnconfigure(0, weight=1)
        self.progress_bar = ttk.Progressbar(
            status, maximum=100, style="Horizontal.TProgressbar"
        )
        self.progress_bar.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        info = ttk.Frame(status)
        info.grid(row=1, column=0, sticky="ew")
        info.columnconfigure(0, weight=1)
        ttk.Label(
            info, textvariable=self.status_msg, style="Info.TLabel"
        ).grid(row=0, column=0, sticky="ew")

        def vsep(column: int) -> None:
            ttk.Separator(info, orient="vertical").grid(
                row=0, column=column, sticky="ns", padx=8, pady=2
            )

        vsep(1)
        ttk.Label(
            info, textvariable=self.stage_text, style="Accent.TLabel"
        ).grid(row=0, column=2, sticky="w")
        vsep(3)
        ttk.Label(
            info, textvariable=self.speed_fps, style="Info.TLabel"
        ).grid(row=0, column=4, sticky="w")
        ttk.Label(
            info, textvariable=self.gpu_telemetry, style="Info.TLabel",
            foreground=str(p["accent"]),
        ).grid(row=0, column=5, sticky="w", padx=(10, 0))
        vsep(6)
        ttk.Label(
            info, textvariable=self.eta_time, style="Muted.TLabel"
        ).grid(row=0, column=7, sticky="w")
        vsep(8)
        ttk.Label(
            info, textvariable=self.progress_percent, style="Good.TLabel"
        ).grid(row=0, column=9, sticky="e")
        vsep(10)
        ttk.Label(
            info, textvariable=self.size_stats, style="Info.TLabel"
        ).grid(row=0, column=11, sticky="w")

        self.refresh_listbox()
        self.refresh_system_info()

    # --------------------------- settings callbacks -----------------------

    def on_settings_changed(self) -> None:
        self.refresh_listbox()
        self.update_vram_meter_display()
        self.save_current_settings()

    def on_search_focus_in(self, _event=None) -> None:
        """Убираем плейсхолдер при фокусе на поле поиска."""
        if self.search_var.get() == SEARCH_PLACEHOLDER:
            self.search_var.set("")
        self.search_entry.configure(foreground=str(self.colors.get("fg", "#F3F4F6")))
        self.refresh_listbox()

    def on_search_focus_out(self, _event=None) -> None:
        """Возвращаем плейсхолдер, если поиск пуст."""
        if not self.search_var.get().strip():
            self.search_var.set(SEARCH_PLACEHOLDER)
            self.search_entry.configure(foreground=str(self.colors.get("muted", "#88949E")))
        self.refresh_listbox()

    def apply_profile(self) -> None:
        preset = PROFILE_PRESETS.get(self.profile.get())
        if preset:
            codec, nvenc_preset, quality, limit_bitrate = preset
            self.output_codec.set(codec)
            self.nvenc_preset.set(nvenc_preset)
            self.quality.set(quality)
            self.limit_bitrate.set(limit_bitrate)
        self.on_settings_changed()

    def on_manual_quality_change(self) -> None:
        if self.profile.get() != PROFILE_MANUAL:
            self.profile.set(PROFILE_MANUAL)
        self.on_settings_changed()

    def save_current_settings(self) -> None:
        s = self.settings
        s.processing_mode = self.processing_mode.get()
        s.target_fps = int(self.target_fps.get())
        s.target_res = self.target_res.get()
        s.scale_algo = self.scale_algo.get()
        s.output_codec = self.output_codec.get()
        s.profile = self.profile.get()
        s.theme = self.theme.get()
        s.nvenc_preset = self.nvenc_preset.get()
        s.audio_mode = self.audio_mode.get()
        s.audio_bitrate = self.audio_bitrate.get()
        s.quality = int(self.quality.get())
        s.enable_hdr_tonemap = bool(self.enable_hdr_tonemap.get())
        s.limit_bitrate = bool(self.limit_bitrate.get())
        s.enable_denoise = bool(self.enable_denoise.get())
        s.enable_sharpen = bool(self.enable_sharpen.get())
        s.sharpen_amount = safe_float(self.sharpen_amount.get(), 0.6, 0.0, 1.0)
        s.engine_codec = self.engine_codec.get()
        s.engine_preset = self.engine_preset.get()
        s.engine_enhance = bool(self.engine_enhance.get())
        s.engine_gpu = safe_int(self.engine_gpu.get(), 0, 0, 15)
        # Не сохраняем «1x1+0+0», которое Tk отдаёт до первого отображения окна.
        geometry = self.window.geometry()
        match = re.match(r"(\d+)x(\d+)", geometry)
        if match and int(match.group(1)) >= 400 and int(match.group(2)) >= 300:
            s.geometry = geometry
        s.save()

    def toggle_sharpen_slider(self) -> None:
        if self.enable_sharpen.get():
            self.slider_frame.pack(fill="x", pady=3)
        else:
            self.slider_frame.pack_forget()
        self.on_settings_changed()

    def clear_log(self) -> None:
        self.log_text.configure(state=NORMAL)
        self.log_text.delete("1.0", END)
        self.log_text.configure(state=DISABLED)

    # --------------------------- dependency setup -------------------------

    def _tool_path(self, name: str) -> Path:
        """Использует установленный бинарник, иначе доступную для записи копию."""
        installed = BASE_DIR / name
        if installed.exists():
            return installed
        return DATA_DIR / name

    def ffmpeg_path(self) -> Path:
        return self._tool_path(FFMPEG_NAME)

    def ffprobe_path(self) -> Path:
        return self._tool_path(FFPROBE_NAME)

    def rife_path(self) -> Path:
        return self._tool_path(RIFE_NAME)

    def models_path(self) -> Path:
        installed = BASE_DIR / MODELS_DIR_NAME
        if installed.is_dir() and any(installed.rglob("*.param")):
            return installed
        return DATA_DIR / MODELS_DIR_NAME

    def set_status(self, message: str) -> None:
        self.ui_events.put(("status", message))

    def set_stage(self, text: str) -> None:
        self.ui_events.put(("stage", text))

    def make_ffmpeg_progress_callback(
        self, meta: MediaMeta, span: tuple[float, float],
    ) -> Callable[[str, float], None]:
        """Прогресс FFmpeg по строкам `time=HH:MM:SS.ms` в stderr."""
        total = float(getattr(meta, "duration", 0) or 0)
        if total <= 0 and meta.fps > 0 and meta.frames > 0:
            total = meta.frames / meta.fps
        last = [0.0]

        def callback(line: str, elapsed: float) -> None:
            if total <= 0:
                return
            match = re.search(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", line)
            if not match:
                return
            seconds = (
                int(match.group(1)) * 3600
                + int(match.group(2)) * 60
                + float(match.group(3))
            )
            pct = min(99.0, seconds / total * 100.0)
            if pct < last[0]:
                return
            last[0] = pct
            speed = seconds / max(0.1, elapsed)
            remaining = max(0.0, (total - seconds) / max(0.01, speed))
            self.emit_progress(span, pct, speed, format_eta(remaining))

        return callback

    def emit_progress(
        self, span: tuple[float, float], local_pct: float,
        speed: float = 0.0, eta: str = "--:--:--",
    ) -> None:
        """Переводит локальный процент стадии в процент общего прогресса."""
        lo, hi = span
        pct = lo + (hi - lo) * min(100.0, max(0.0, local_pct)) / 100.0
        self.ui_events.put(("progress", pct, speed, eta))

    def start_frame_monitor(
        self, frames_dir: Path, expected: int, span: tuple[float, float],
        stop: threading.Event, max_pct: float = 99.0,
    ) -> threading.Thread:
        """Следит за числом созданных PNG и обновляет общий прогресс/ETA.

        rife-ncnn-vulkan в не-verbose режиме не печатает проценты, а старый
        парсер принимал служебную строку «fp16-p/s/a=1/1/1» за 100%. Единственный
        надёжный источник прогресса — фактически появившиеся кадры на диске.
        """
        def monitor() -> None:
            last_count = 0
            last_ts = time.monotonic()
            smooth_speed = 0.0
            while not stop.wait(0.4):
                try:
                    count = len(list(frames_dir.glob("*.png")))
                except OSError:
                    count = last_count
                now = time.monotonic()
                dt = max(0.05, now - last_ts)
                inst = max(0.0, (count - last_count) / dt)
                smooth_speed = inst if smooth_speed <= 0.0 else smooth_speed * 0.7 + inst * 0.3
                last_count, last_ts = count, now
                local_pct = min(max_pct, count / max(1, expected) * 100.0)
                remaining = max(0, expected - count)
                if smooth_speed > 0.05:
                    eta = format_eta(remaining / smooth_speed)
                else:
                    eta = "--:--:--"
                self.emit_progress(span, local_pct, smooth_speed, eta)

        thread = threading.Thread(target=monitor, name="FrameProgress", daemon=True)
        thread.start()
        return thread

    def verify_and_download_dependencies_bootstrap(self) -> None:
        if engine is None:
            self.status_msg.set("Движок v3.5 не найден (media_engine_v35.py).")
            self.btn_start.configure(state="disabled")
            return
        if (
            self.ffmpeg_path().exists() and self.ffprobe_path().exists()
            and self.rife_path().exists() and self.models_path().exists()
            and self.has_rife_model()
        ):
            self.status_msg.set("FFmpeg и RIFE найдены. Система готова.")
            self.btn_start.configure(state="normal")
            threading.Thread(target=self.detect_available_encoders,
                             name="EncoderProbe", daemon=True).start()
            return

        self.is_downloading_dependencies = True
        self.btn_start.configure(state="disabled")

        def download(url: str, target: Path, label: str) -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            temp_target = target.with_suffix(target.suffix + ".part")
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=60) as response, open(temp_target, "wb") as out:
                total = int(response.headers.get("Content-Length", "0") or 0)
                done = 0
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    pct = (done / total * 100) if total else 0
                    self.ui_events.put(("download", label, done, total, pct))
            temp_target.replace(target)

        def safe_extract_selected(zip_path: Path, wanted: dict[str, Path]) -> None:
            with zipfile.ZipFile(zip_path) as archive:
                for info in archive.infolist():
                    normalized = info.filename.replace("\\", "/")
                    parts = [p for p in normalized.split("/") if p not in ("", ".")]
                    if ".." in parts:
                        raise RuntimeError(f"Небезопасный путь в архиве: {info.filename}")
                    for suffix, destination in wanted.items():
                        if normalized.endswith(suffix):
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            with archive.open(info) as src, open(destination, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                            break

        def worker() -> None:
            try:
                if not self.ffmpeg_path().exists() or not self.ffprobe_path().exists():
                    self.set_status("Скачивание FFmpeg...")
                    archive = DATA_DIR / "ffmpeg_download.zip"
                    download(FFMPEG_URL, archive, "FFmpeg")
                    safe_extract_selected(archive, {
                        "bin/ffmpeg.exe": self.ffmpeg_path(),
                        "bin/ffprobe.exe": self.ffprobe_path(),
                    })
                    archive.unlink(missing_ok=True)
                    if not self.ffmpeg_path().exists() or not self.ffprobe_path().exists():
                        raise RuntimeError("В архиве FFmpeg не найдены ffmpeg.exe / ffprobe.exe")

                if (
                    not self.rife_path().exists() or not self.models_path().exists()
                    or not self.has_rife_model()
                ):
                    self.set_status("Скачивание RIFE NCNN Vulkan...")
                    archive = DATA_DIR / "rife_download.zip"
                    download(RIFE_URL, archive, "RIFE")
                    self.models_path().mkdir(parents=True, exist_ok=True)
                    with zipfile.ZipFile(archive) as zf:
                        for info in zf.infolist():
                            name = info.filename.replace("\\", "/")
                            parts = [x for x in name.split("/") if x]
                            if ".." in parts or info.is_dir():
                                continue
                            base = Path(name).name.lower()
                            if base in {RIFE_NAME, "vcomp140.dll"}:
                                dest = DATA_DIR / Path(name).name
                            elif len(parts) >= 2 and (
                                parts[0].lower() == "models"
                                or parts[0].lower().startswith("rife")
                            ):
                                # В архиве 20221029 модели лежат в папках
                                # rife-v4 / rife-v4.6 в корне, а не в models/.
                                root = parts[0].lower()
                                strip_root = (
                                    root == "models"
                                    or (root.startswith("rife-ncnn") and len(parts) > 2)
                                )
                                rel_parts = parts[1:] if strip_root else parts
                                dest = self.models_path().joinpath(*rel_parts)
                            else:
                                continue
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            with zf.open(info) as src, open(dest, "wb") as out:
                                shutil.copyfileobj(src, out)
                    archive.unlink(missing_ok=True)
                    if not self.rife_path().exists():
                        raise RuntimeError("В архиве не найден rife-ncnn-vulkan.exe")
                    if not self.has_rife_model():
                        raise RuntimeError(
                            "Архив RIFE не содержит полной модели (пары .param/.bin)"
                        )

                self.detect_available_encoders()
                self.ui_events.put(("dependencies_done", True,
                                    "Компоненты установлены. Можно добавлять видео."))
            except Exception as exc:
                logging.exception("Dependency bootstrap failed")
                self.ui_events.put(("dependencies_done", False,
                                    f"Не удалось установить компоненты: {exc}"))

        threading.Thread(target=worker, name="DependencySetup", daemon=True).start()

    def detect_available_encoders(self) -> None:
        if not self.ffprobe_path().exists():
            return
        try:
            output = run_capture([str(self.ffprobe_path()), "-hide_banner", "-encoders"], timeout=30)
            encoders = set(re.findall(
                r"^\s*[VAS][.A-Z]{5}\s+([A-Za-z0-9_\-]+)", output, flags=re.MULTILINE
            ))
            self.available_encoders = encoders
            logging.info("Доступно энкодеров: %d", len(encoders))
        except Exception as exc:
            logging.warning("Не удалось получить список энкодеров: %s", exc)

    # --------------------------- file queue / metadata --------------------

    def browse_files(self) -> None:
        if self.is_running or self.is_downloading_dependencies:
            return
        selected = filedialog.askopenfilenames(
            title="Выберите видеофайлы",
            filetypes=[
                ("Видеофайлы", "*.mp4 *.mkv *.avi *.mov *.3gp *.webm *.m4v *.ts *.flv"),
                ("Все файлы", "*.*"),
            ],
        )
        added = False
        for filename in selected:
            path = str(Path(filename).resolve())
            if path not in self.file_paths:
                self.file_paths.append(path)
                added = True
                threading.Thread(
                    target=self.inspect_file_metadata, args=(path,), daemon=True
                ).start()
        if added:
            if not getattr(self, "inspected_path", ""):
                self.inspected_path = str(Path(selected[0]).resolve())
            self.refresh_listbox()
            self.update_vram_meter_display()

    def remove_selected(self) -> None:
        if self.is_running or self.is_downloading_dependencies:
            return
        selection = list(self.file_listbox.curselection())
        for index in reversed(selection):
            if index < len(self.visible_paths):
                path = self.visible_paths[index]
                if path in self.file_paths:
                    self.file_paths.remove(path)
        self.refresh_listbox()

    def clear_queue(self) -> None:
        if self.is_running or self.is_downloading_dependencies:
            return
        self.file_paths.clear()
        self.metadata_cache.clear()
        self.failed_files.clear()
        self.active_file = None
        self.inspected_path = ""
        self.refresh_listbox()
        self.btn_retry.configure(state="disabled")
        self.update_vram_meter_display()

    def refresh_listbox(self) -> None:
        """Перерисовка списка: поиск, бейджи длительности/FPS, заглушка и прогресс."""
        query = self.search_var.get().strip().lower() if hasattr(self, "search_var") else ""
        if query == SEARCH_PLACEHOLDER.lower():
            query = ""
        self.visible_paths = []
        self.file_listbox.delete(0, "end")
        for path in self.file_paths:
            name = Path(path).name
            if query and query not in name.lower():
                continue
            if path == self.active_file:
                prefix = "ACTIVE"
            elif path in self.failed_files:
                prefix = "FAILED"
            else:
                prefix = "WAITING"
            meta = self.metadata_cache.get(path)
            badges = ""
            if meta is not None:
                if meta.duration > 0:
                    badges += f"  ·  {meta.duration:.1f}s"
                if meta.fps > 0:
                    badges += f"  ·  {meta.fps:.0f}→{self.target_fps.get()} FPS"
            self.visible_paths.append(path)
            self.file_listbox.insert("end", f"{prefix} | {name}{badges}")
        if hasattr(self, "queue_count"):
            total = len(self.file_paths)
            shown = len(self.visible_paths)
            self.queue_count.configure(
                text=(f"{shown} из {total} файлов" if query else f"{total} файлов")
            )
        # list_card использует grid: переключаем только виджеты внутри неё.
        if self.file_paths:
            if not self.file_listbox.winfo_manager():
                self.file_listbox.grid(row=0, column=0, sticky="nsew")
            # Скролл показываем ВСЕГДА при непустой очереди, независимо от
            # состояния Listbox — иначе он остаётся спрятанным после очистки.
            if not self.list_scroll.winfo_manager():
                self.list_scroll.grid(row=0, column=1, sticky="ns")
            if self.drop_hint.winfo_manager():
                self.drop_hint.grid_forget()
        else:
            self.file_listbox.grid_forget()
            self.list_scroll.grid_forget()
            if not self.drop_hint.winfo_manager():
                self.drop_hint.grid(
                    row=0, column=0, columnspan=2, sticky="nsew"
                )
        progress = getattr(self, "file_progress", None)
        if progress is not None:
            if self.active_file:
                if not progress.winfo_manager():
                    progress.grid(
                        row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0)
                    )
            elif progress.winfo_manager():
                progress.grid_forget()

    def on_file_select_inspect(self, _event=None) -> None:
        selection = self.file_listbox.curselection()
        if selection and selection[0] < len(self.visible_paths):
            path = self.visible_paths[selection[0]]
            self.inspected_path = path
            threading.Thread(
                target=self.inspect_file_metadata, args=(path,), daemon=True
            ).start()

    def inspect_file_metadata(self, filepath: str) -> None:
        if filepath in self.metadata_cache:
            self.ui_events.put(("metadata", filepath, self.metadata_cache[filepath].as_dict()))
            return
        if not self.ffprobe_path().exists():
            self.ui_events.put(("metadata_error", filepath, "ffprobe.exe не найден"))
            return
        try:
            meta = probe_meta(self.ffprobe_path(), filepath)
            self.metadata_cache[filepath] = meta
            self.ui_events.put(("metadata", filepath, meta.as_dict()))
        except Exception as exc:
            logging.exception("Metadata inspection failed: %s", filepath)
            self.ui_events.put(("metadata_error", filepath, str(exc)))

    def update_inspector_labels_ui(self, meta: dict) -> None:
        is_10bit = "10" in str(meta.get("pix", ""))
        color = str(self.colors["warn"]) if is_10bit else str(self.colors["muted"])
        self.lbl_inspect_res.configure(text=f"{meta['w']}×{meta['h']}")
        self.lbl_inspect_fps.configure(text=f"{meta['fps']:.3f} FPS")
        self.lbl_inspect_frames.configure(text=str(meta.get('frames') or '—'))
        self.lbl_inspect_pix.configure(text=meta.get('pix', 'unknown'), foreground=color)

    # --------------------------- process lifecycle ------------------------

    def preflight_check(self, cfg: JobConfig, jobs: list[str]) -> bool:
        """Проверяет компоненты, энкодеры и место на диске перед запуском."""
        if not self.ffmpeg_path().exists() or not self.ffprobe_path().exists():
            messagebox.showerror("Нет FFmpeg", "Не найдены ffmpeg.exe и ffprobe.exe рядом с программой.")
            return False
        if cfg.mode == "rife_tensorrt" and engine is None:
            messagebox.showerror("Нет движка", "Движок v3.5 не найден в сборке.")
            return False
        # Проверка свободного места (консервативно 6 ГБ на файл)
        try:
            directories = [Path(tempfile.gettempdir())]
            directories.extend(Path(job).parent for job in jobs)
            for directory in dict.fromkeys(directories):
                usage = shutil.disk_usage(directory)
                if usage.free < 6 * 1024**3:
                    messagebox.showwarning(
                        "Мало места",
                        f"На диске {directory} менее 6 ГБ свободно. "
                        "Обработка может прерваться.",
                    )
                    break
        except Exception as exc:
            logging.warning("Не удалось проверить место на диске: %s", exc)
        return True

    def start_processing_thread(self) -> None:
        if self.is_running or self.is_downloading_dependencies:
            return
        if not self.file_paths:
            messagebox.showinfo("Очередь пуста", "Сначала добавьте видеофайлы.")
            return
        try:
            target = int(self.target_fps.get())
            if target < 1 or target > 1000:
                raise ValueError
        except Exception:
            messagebox.showerror("Некорректный FPS", "Укажите целевой FPS от 1 до 1000.")
            return

        cfg = self.snapshot_config()
        if not self.preflight_check(cfg, list(self.file_paths)):
            return

        jobs = list(self.file_paths)
        self.cancel_event.clear()
        self.is_running = True
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.btn_retry.configure(state="disabled")
        self.prevent_windows_sleep(True)
        self.worker_thread = threading.Thread(
            target=self.process_queue_logic, args=(jobs, cfg),
            name="VideoQueueWorker", daemon=True,
        )
        self.worker_thread.start()

    def retry_failed(self) -> None:
        if self.is_running or not self.failed_files:
            return
        retry = [p for p in self.failed_files if p in self.file_paths]
        if not retry:
            return
        cfg = self.snapshot_config()
        if not self.preflight_check(cfg, retry):
            return
        self.failed_files.clear()
        self.refresh_listbox()
        self.btn_retry.configure(state="disabled")
        self.cancel_event.clear()
        self.is_running = True
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.prevent_windows_sleep(True)
        self.worker_thread = threading.Thread(
            target=self.process_queue_logic, args=(retry, cfg),
            name="VideoQueueWorker", daemon=True,
        )
        self.worker_thread.start()

    def snapshot_config(self) -> JobConfig:
        return JobConfig(
            mode=self.processing_mode.get(),
            target_fps=int(self.target_fps.get()),
            target_res=self.target_res.get(),
            scale_algo=self.scale_algo.get(),
            codec=self.output_codec.get(),
            nvenc_preset=self.nvenc_preset.get().split()[0],
            audio_mode=self.audio_mode.get(),
            audio_bitrate=self.audio_bitrate.get(),
            hdr_tonemap=bool(self.enable_hdr_tonemap.get()),
            limit_bitrate=bool(self.limit_bitrate.get()),
            denoise=bool(self.enable_denoise.get()),
            sharpen=bool(self.enable_sharpen.get()),
            sharpen_amount=safe_float(self.sharpen_amount.get(), 0.6, 0.0, 1.0),
            quality=int(self.quality.get()),
            gpu_index=safe_int(self.settings.gpu_index, 0, 0, 15),
            engine_codec=self.engine_codec.get(),
            engine_preset=self.engine_preset.get(),
            engine_enhance=bool(self.engine_enhance.get()),
            engine_gpu=safe_int(self.engine_gpu.get(), 0, 0, 15),
        )

    def prevent_windows_sleep(self, enable: bool = True) -> None:
        if os.name != "nt":
            return
        try:
            continuous = 0x80000000
            system_required = 0x00000001
            display_required = 0x00000002
            flags = continuous | system_required | display_required if enable else continuous
            ctypes.windll.kernel32.SetThreadExecutionState(flags)
        except Exception as exc:
            logging.warning("SetThreadExecutionState: %s", exc)

    def register_process(self, process: subprocess.Popen) -> None:
        with self.process_lock:
            self.active_processes.add(process)

    def unregister_process(self, process: subprocess.Popen) -> None:
        with self.process_lock:
            self.active_processes.discard(process)

    def popen(self, command: list[str], **kwargs) -> subprocess.Popen:
        kwargs.setdefault("startupinfo", hidden_startupinfo())
        kwargs.setdefault("creationflags", hidden_creationflags())
        kwargs.setdefault("stdin", subprocess.DEVNULL)
        process = subprocess.Popen(command, **kwargs)
        self.register_process(process)
        return process

    def terminate_processes(self) -> None:
        if engine is not None:
            try:
                engine.cancel_active_processes()
            except Exception:
                logging.exception('Не удалось остановить процессы движка')
        with self.process_lock:
            processes = list(self.active_processes)
        for proc in processes:
            if proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass
        for proc in processes:
            if proc.poll() is None:
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try:
                        proc.kill()
                    except OSError:
                        pass

    def stop_processing(self) -> None:
        if not self.is_running:
            return
        self.cancel_event.set()
        self.status_msg.set("Остановка обработки...")
        self.terminate_processes()

    def run_logged_process(
        self, command: list[str], label: str,
        progress_callback: Callable[[str, float], None] | None = None,
        timeout: int | None = None, progress_stdout: bool = False,
    ) -> int:
        """Процесс с потоковым stderr, прогрессом из stdout и поддержкой отмены."""
        logging.info("%s: %s", label, subprocess.list2cmdline(command))
        process = self.popen(
            command,
            stdout=subprocess.PIPE if progress_stdout else subprocess.DEVNULL,
            stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
        )
        progress_thread: threading.Thread | None = None
        if progress_stdout and progress_callback and process.stdout is not None:
            def read_progress() -> None:
                start_progress = time.monotonic()
                assert process.stdout is not None
                try:
                    for raw in process.stdout:
                        text = raw.decode("utf-8", errors="replace").strip()
                        if text.startswith("out_time="):
                            value = text.split("=", 1)[1]
                            if value and value != "N/A":
                                progress_callback(
                                    "time=" + value, time.monotonic() - start_progress
                                )
                except Exception:
                    pass

            progress_thread = threading.Thread(
                target=read_progress, name="FFmpegProgress", daemon=True
            )
            progress_thread.start()
        try:
            start = time.monotonic()
            assert process.stderr is not None
            while True:
                if self.cancel_event.is_set():
                    raise InterruptedError("Операция отменена пользователем")
                line = process.stderr.readline()
                if not line:
                    break
                text_line = line.decode("utf-8", errors="replace").strip()
                if text_line:
                    logging.info("[%s] %s", label, text_line)
                    if progress_callback and not progress_stdout:
                        progress_callback(text_line, time.monotonic() - start)
            if self.cancel_event.is_set():
                raise InterruptedError("Операция отменена пользователем")
            return_code = process.wait(timeout=timeout)
            if self.cancel_event.is_set():
                raise InterruptedError("Операция отменена пользователем")
            if return_code != 0:
                raise RuntimeError(f"{label}: процесс завершился с кодом {return_code}")
            return return_code
        finally:
            self.unregister_process(process)
            if process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
            if progress_thread is not None:
                progress_thread.join(timeout=1.5)
            if process.stderr:
                process.stderr.close()
            if process.stdout:
                process.stdout.close()

    # --------------------------- UI events --------------------------------

    def poll_ui_events(self) -> None:
        if self.closing:
            return
        try:
            while True:
                event = self.ui_events.get_nowait()
                kind = event[0]
                if kind == "status":
                    self.status_msg.set(event[1])
                elif kind == "stage":
                    self.stage_text.set(event[1])
                elif kind == "log":
                    _, message = event
                    self.log_text.configure(state=NORMAL)
                    self.log_text.insert(END, message + "\n")
                    self.log_text.see(END)
                    self.log_text.configure(state=DISABLED)
                elif kind == "download":
                    _, label, done, total, pct = event
                    self.progress_percent.set(
                        f"{pct:.1f}%" if total else f"{done / 1048576:.1f} МБ"
                    )
                    self.progress_bar.configure(value=pct)
                    suffix = f" / {total / 1048576:.1f} МБ" if total else ""
                    self.status_msg.set(
                        f"Загрузка {label}: {done / 1048576:.1f} МБ{suffix}"
                    )
                elif kind == "dependencies_done":
                    _, success, message = event
                    self.is_downloading_dependencies = False
                    self.status_msg.set(message)
                    self.btn_start.configure(state="normal" if success else "disabled")
                    self.progress_bar.configure(value=0)
                    self.progress_percent.set("0.0%")
                elif kind == "gpu_telemetry":
                    if event[1] is not None:
                        self.gpu_load = float(event[1])
                        self.vram_used_mb = float(event[2])
                    self.update_vram_meter_display()
                elif kind == "metadata":
                    _, filepath, meta = event
                    if filepath == getattr(self, "inspected_path", None):
                        self.update_inspector_labels_ui(meta)
                    self.update_vram_meter_display()
                elif kind == "metadata_error":
                    _, filepath, message = event
                    self.status_msg.set(f"Инспектор: {Path(filepath).name}: {message}")
                elif kind == "active":
                    _, filepath = event
                    self.active_file = filepath
                    self.status_msg.set(f"Обработка: {Path(filepath).name}")
                    self.progress_bar.configure(value=0)
                    self.progress_percent.set("0.0%")
                    if hasattr(self, "file_progress"):
                        self.file_progress.configure(value=0)
                    self.refresh_listbox()
                elif kind == "job_done":
                    _, filepath, success, message = event
                    if filepath == self.active_file:
                        self.active_file = None
                    if not success and filepath not in self.failed_files:
                        self.failed_files.append(filepath)
                    self.status_msg.set(message)
                    if not success:
                        logging.error(message)
                        self.btn_retry.configure(state="normal")
                    if hasattr(self, "file_progress"):
                        self.file_progress.configure(value=100 if success else 0)
                    self.refresh_listbox()
                    self.update_vram_meter_display()
                elif kind == "progress":
                    _, pct, fps, eta = event
                    self.progress_bar.configure(value=max(0, min(100, pct)))
                    if hasattr(self, "file_progress"):
                        self.file_progress.configure(value=max(0, min(100, pct)))
                    self.progress_percent.set(f"{pct:.1f}%")
                    self.speed_fps.set(f"Скорость: {fps:.1f}x")
                    self.eta_time.set(f"Осталось: {eta}")
                elif kind == "v35_progress":
                    _, pct, description, speed, eta = event
                    self.progress_bar.configure(value=max(0, min(100, pct)))
                    if hasattr(self, "file_progress"):
                        self.file_progress.configure(value=max(0, min(100, pct)))
                    self.progress_percent.set(f"{pct:.1f}%")
                    self.speed_fps.set(
                        f"Скорость: {speed}" if speed else "Скорость: —"
                    )
                    self.eta_time.set(f"Осталось: {eta}")
                    if description:
                        self.stage_text.set(f"Стадия: {description}")
                elif kind == "v35_stats":
                    _, stats = event
                    self.size_stats.set(
                        f"Размер: {stats.get('size', '—')} · {stats.get('size_ratio', '—')}"
                    )
                elif kind == "tensor_test":
                    _, success, message = event
                    self.tensor_test_status.set(message)
                elif kind == "system_info":
                    self.populate_system_info(event[1])
                elif kind == "system_info_error":
                    self.populate_system_info({"Ошибка опроса": event[1]})
                elif kind == "save_settings":
                    self.save_current_settings()
                elif kind == "finished":
                    self.is_running = False
                    self.active_file = None
                    self.refresh_listbox()
                    self.prevent_windows_sleep(False)
                    self.btn_start.configure(
                        state="normal" if not self.is_downloading_dependencies else "disabled"
                    )
                    self.btn_stop.configure(state="disabled")
                    self.progress_bar.configure(value=0)
                    self.stage_text.set("Стадия: завершено")
                    self.speed_fps.set("Скорость: —")
                    self.eta_time.set("Осталось: --:--:--")
                    self.progress_percent.set("0.0%")
                    self.btn_retry.configure(
                        state="normal" if self.failed_files else "disabled"
                    )
                    if self.cancel_event.is_set():
                        self.status_msg.set("Обработка отменена.")
        except queue.Empty:
            pass
        except Exception:
            logging.exception("Ошибка обработки события UI")
        finally:
            if not self.closing:
                self.window.after(150, self.poll_ui_events)

    # --------------------------- filter / encoder builders ----------------

    def build_video_filters(
        self, cfg: JobConfig, meta: MediaMeta, width: int, height: int,
        interpolation_filter: str | None = None, include_sharpen: bool = True,
    ) -> list[str]:
        filters: list[str] = []
        if cfg.denoise:
            filters.append("hqdn3d=4:3:6:4.5")
        if cfg.hdr_tonemap and self.is_hdr(meta):
            filters.extend([
                "zscale=t=linear:npl=100",
                "format=gbrpf32le",
                "tonemap=tonemap=hable:desat=0",
                "zscale=t=bt709:m=bt709:p=bt709:r=tv",
                "format=yuv420p",
            ])
        if interpolation_filter:
            filters.append(interpolation_filter)
        out_w, out_h = resolution_for_choice(cfg.target_res, width, height)
        if (out_w, out_h) != (width, height):
            filters.append(
                f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:flags={cfg.scale_algo},"
                f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black"
            )
        if include_sharpen and cfg.sharpen and cfg.sharpen_amount > 0:
            filters.append(f"cas={cfg.sharpen_amount:.1f}")
        return filters

    @staticmethod
    def is_hdr(meta: MediaMeta) -> bool:
        transfer = str(meta.color_transfer).lower()
        primaries = str(meta.color_primaries).lower()
        return transfer in {"smpte2084", "arib-std-b67"} or primaries in {"bt2020"}

    def pick_encoder(self, cfg: JobConfig) -> tuple[str, str]:
        """
        Возвращает (encoder_name, family) с учётом доступных энкодеров.
        family: 'nvidia' | 'amd' | 'software'.
        """
        codec = cfg.codec
        if codec == "hevc":
            sw = "libx265"
            candidates = [("hevc_nvenc", "nvidia"), ("hevc_amf", "amd")]
        elif codec == "av1":
            # RTX 3050 (Ampere) умеет AV1 только в декодере — av1_nvenc не пробуем.
            sw = "libaom-av1"
            candidates = [("libsvtav1", "software")]
        else:
            sw = "libx264"
            candidates = [("h264_nvenc", "nvidia"), ("h264_amf", "amd")]

        # Если hw-энкодер доступен в системе — используем его для соответствующего вендора
        for name, family in candidates:
            if name in self.available_encoders:
                if family == "nvidia" and self.gpu_vendor != "NVIDIA":
                    continue
                if family == "amd" and self.gpu_vendor != "AMD":
                    continue
                return name, family
        return sw, "software"

    def encoder_options(self, cfg: JobConfig, family: str, encoder: str = "") -> list[str]:
        """Опции кодирования, проверенные по `ffmpeg -h encoder=...`."""
        quality = max(0, min(51, int(getattr(cfg, "quality", 18))))
        max_rate = (
            "45M" if "2160" in cfg.target_res
            else "35M" if "1440" in cfg.target_res
            else "30M"
        )
        bitrate_caps = ["-maxrate", max_rate, "-bufsize", f"{int(max_rate[:-1]) * 2}M"]
        if family == "nvidia":
            preset = cfg.nvenc_preset or "p4"
            options = ["-preset", preset, "-rc", "vbr", "-cq", str(quality)]
            if cfg.limit_bitrate:
                options.extend(bitrate_caps)
            return options
        if family == "amd":
            # У AMF нет -cq: quality-ползунок маппируем на CQP.
            return [
                "-rc", "cqp", "-qp_i", str(quality), "-qp_p", str(quality),
                "-qp_b", str(quality), "-quality", "2",
            ]
        if encoder == "libsvtav1":
            # -preset у libsvtav1 — целое (-2..13), «medium» не парсится.
            return ["-preset", "8", "-crf", str(quality), "-b:v", "0"]
        if encoder == "libaom-av1":
            # У libaom-av1 нет -preset, но есть -cpu-used.
            return ["-cpu-used", "4", "-crf", str(quality), "-b:v", "0"]
        options = ["-preset", "medium", "-crf", str(quality)]
        if cfg.limit_bitrate:
            options.extend(bitrate_caps)
        return options

    def build_encode_command(
        self, inputs: list[str], maps: list[str], output: Path,
        cfg: JobConfig, encoder: str, family: str, extra: list[str] | None = None,
    ) -> list[str]:
        """Унифицированное построение команды кодирования."""
        cmd = [
            str(self.ffmpeg_path()), "-hide_banner", "-loglevel", "warning",
            "-nostats", "-progress", "pipe:1", "-y", *inputs,
        ]
        cmd.extend(maps)
        if extra:
            cmd.extend(extra)
        cmd.extend(["-c:v", encoder, *self.encoder_options(cfg, family, encoder)])
        cmd.extend(["-pix_fmt", "yuv420p"])
        if cfg.audio_mode == "copy":
            cmd.extend(["-c:a", "copy"])
        else:
            cmd.extend(["-c:a", "aac", "-b:a", cfg.audio_bitrate])
        if output.suffix.lower() in {".mp4", ".mov", ".m4v"}:
            cmd.extend(["-movflags", "+faststart"])
        cmd.append(str(output))
        return cmd

    # --------------------------- RIFE pipeline ----------------------------

    def find_rife_model(self) -> Path:
        """Находит полную модель RIFE даже внутри корневой папки архива."""
        models = self.models_path()
        if not models.exists():
            raise RuntimeError("Каталог models не найден")
        found: list[Path] = []
        for param in models.rglob("flownet.param"):
            if param.with_suffix(".bin").is_file():
                found.append(param.parent)
        # На всякий случай поддерживаем модели без flownet.param, но с парой файлов.
        for param in models.rglob("*.param"):
            parent = param.parent
            if parent in found:
                continue
            if param.with_suffix(".bin").is_file():
                found.append(parent)
        if not found:
            raise RuntimeError(
                "Не найдена совместимая модель RIFE-v4 / RIFE-v4.6 (нужны пары .param/.bin). "
                "Установите полный пакет RIFE с моделью rife-v4.6."
            )
        found.sort(key=lambda path: (
            0 if path.name == "rife-v4.6" else 1 if path.name == "rife-v4" else 2,
            str(path).lower(),
        ))
        return found[0]

    def has_rife_model(self) -> bool:
        """Быстрая проверка: есть ли хотя бы одна полная модель RIFE."""
        try:
            self.find_rife_model()
            return True
        except RuntimeError:
            return False

    def run_rife(self, input_file: str, output_file: Path, meta: MediaMeta, cfg: JobConfig) -> None:
        ffmpeg = str(self.ffmpeg_path())
        rife = str(self.rife_path())
        source_fps = float(meta.fps)
        target_fps = float(cfg.target_fps)
        if source_fps <= 0 or not math.isfinite(source_fps):
            raise RuntimeError("Исходный FPS равен нулю или некорректен")
        if target_fps <= source_fps * 1.001:
            raise RuntimeError(
                f"RIFE выбран, но целевой FPS ({target_fps:g}) не выше исходного "
                f"({source_fps:g}). Выберите более высокий FPS или Turbo GPU."
            )

        with temp_workdir("rtx_media_master_") as work_root:
            input_frames = work_root / "input"
            output_frames = work_root / "output"
            input_frames.mkdir()
            output_frames.mkdir()

            # 1) Извлечение кадров сFilters (без резкости — она применяется при сборке)
            out_pattern = str(input_frames / "%08d.png")
            filters = self.build_video_filters(
                cfg, meta, meta.w, meta.h, include_sharpen=False
            )
            extract_cmd = [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", input_file,
                "-map", "0:v:0",
            ]
            if filters:
                extract_cmd.extend(["-vf", ",".join(filters)])
            extract_cmd.extend(["-fps_mode", "passthrough", out_pattern])

            self.set_stage("Стадия: 1/3 Извлечение кадров")
            self.set_status(f"Извлечение кадров: {Path(input_file).name}")
            expected_extract = int(meta.frames or 0) or max(
                2, int(round(float(meta.duration) * source_fps))
            )
            extract_stop = threading.Event()
            extract_monitor = self.start_frame_monitor(
                input_frames, expected_extract, STAGE_EXTRACT_SPAN, extract_stop
            )
            try:
                self.run_logged_process(extract_cmd, "FFmpeg decode")
            finally:
                extract_stop.set()
                extract_monitor.join(timeout=1.5)
            self.emit_progress(STAGE_EXTRACT_SPAN, 100.0)

            if self.cancel_event.is_set():
                raise InterruptedError("Операция отменена пользователем")

            extracted = sorted(input_frames.glob("*.png"))
            if len(extracted) < 2:
                raise RuntimeError("FFmpeg извлёк меньше двух кадров")

            # 2) Интерполяция RIFE
            desired_frames = max(2, int(round((len(extracted) - 1) * target_fps / source_fps)) + 1)
            model_dir = self.find_rife_model()
            rife_threads = "2:2:2" if meta.w * meta.h >= 3840 * 2160 else "4:4:4"
            rife_cmd = [
                rife, "-i", str(input_frames), "-o", str(output_frames),
                "-n", str(desired_frames), "-m", str(model_dir),
                "-g", str(cfg.gpu_index), "-j", rife_threads, "-f", "%08d.png",
            ]
            self.set_stage("Стадия: 2/3 Интерполяция RIFE (GPU Vulkan)")
            self.set_status("RIFE: интерполяция кадров на GPU Vulkan...")
            # rife-ncnn-vulkan не печатает проценты: прогресс берём из числа
            # реально записанных кадров. Служебные строки вроде «1/1/1»
            # больше не могут превратиться в ложные 100%.
            rife_stop = threading.Event()
            rife_monitor = self.start_frame_monitor(
                output_frames, desired_frames, STAGE_RIFE_SPAN, rife_stop
            )
            try:
                self.run_logged_process(rife_cmd, "RIFE")
            finally:
                rife_stop.set()
                rife_monitor.join(timeout=1.5)
            self.emit_progress(STAGE_RIFE_SPAN, 100.0)

            if self.cancel_event.is_set():
                raise InterruptedError("Операция отменена пользователем")

            generated = sorted(output_frames.glob("*.png"))
            if len(generated) < 2:
                raise RuntimeError("RIFE не создал достаточное количество выходных PNG-кадров")
            frame_count = len(generated)

            # Нормализация нумерации кадров (надёжный вариант без временных коллизий)
            normalized = work_root / "normalized"
            normalized.mkdir()
            for index, path in enumerate(generated):
                path.rename(normalized / f"{index:08d}.png")

            # FPS итогового видео из расчёта сохранения длительности
            output_fps = (frame_count - 1) * source_fps / max(1, len(extracted) - 1)

            # 3) Сборка видео + аудио из исходника
            self.set_stage("Стадия: 3/3 Кодирование результата")
            self.set_status("Кодирование итогового видео...")
            self.emit_progress(STAGE_ENCODE_SPAN, 0.0)
            sequence_input = [
                "-framerate", f"{output_fps:.12g}", "-start_number", "0",
                "-i", str(normalized / "%08d.png"),
                "-i", input_file,
            ]
            maps = ["-map", "0:v:0", "-map", "1:a:0?", "-r", f"{output_fps:.12g}"]
            extra: list[str] = []
            if cfg.sharpen and cfg.sharpen_amount > 0:
                extra.extend(["-vf", f"cas={cfg.sharpen_amount:.1f}"])

            encoder, family = self.pick_encoder(cfg)
            temp_output = output_file.with_name(
                output_file.stem + ".partial" + output_file.suffix
            )
            output_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                try:
                    cmd = self.build_encode_command(
                        sequence_input, maps, temp_output, cfg, encoder, family, extra
                    )
                    attempt_cb = self.make_ffmpeg_progress_callback(
                        meta, STAGE_ENCODE_SPAN
                    )
                    self.run_logged_process(
                        cmd, "FFmpeg encode", attempt_cb, progress_stdout=True
                    )
                except Exception:
                    if self.cancel_event.is_set() or (
                        family == "software" and encoder != "libsvtav1"
                    ):
                        raise
                    logging.exception("Hardware encoder failed; retrying with software encoder")
                    temp_output.unlink(missing_ok=True)
                    sw_encoder = "libx265" if cfg.codec == "hevc" else (
                        "libaom-av1" if cfg.codec == "av1" else "libx264"
                    )
                    cmd = self.build_encode_command(
                        sequence_input, maps, temp_output, cfg, sw_encoder, "software", extra
                    )
                    attempt_cb = self.make_ffmpeg_progress_callback(
                        meta, STAGE_ENCODE_SPAN
                    )
                    self.run_logged_process(
                        cmd, "FFmpeg x264/x265 fallback", attempt_cb,
                        progress_stdout=True,
                    )
                if not temp_output.exists() or temp_output.stat().st_size == 0:
                    raise RuntimeError("Файл результата не создан или пуст")
                temp_output.replace(output_file)
                self.emit_progress(STAGE_ENCODE_SPAN, 100.0)
            finally:
                temp_output.unlink(missing_ok=True)

    # --------------------------- standard FFmpeg modes --------------------

    def run_ffmpeg_mode(self, input_file: str, output_file: Path, meta: MediaMeta, cfg: JobConfig) -> None:
        self.set_stage("Стадия: FFmpeg-обработка")
        self.emit_progress((0.0, 100.0), 0.0)
        filters = self.build_video_filters(cfg, meta, meta.w, meta.h)
        if cfg.mode == "turbo_gpu":
            filters.append(f"fps=fps={cfg.target_fps}")
        else:
            filters.append(
                f"minterpolate=fps={cfg.target_fps}:mi_mode=mci:mc_mode=aobmc:scd=none"
            )

        inputs = ["-i", input_file]
        maps = ["-map", "0:v:0", "-map", "0:a:0?"]
        extra = ["-vf", ",".join(filters)] if filters else []

        encoder, family = self.pick_encoder(cfg)
        temp_output = output_file.with_name(
            output_file.stem + ".partial" + output_file.suffix
        )
        output_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            try:
                cmd = self.build_encode_command(
                    inputs, maps, temp_output, cfg, encoder, family, extra
                )
                attempt_cb = self.make_ffmpeg_progress_callback(meta, (0.0, 100.0))
                self.run_logged_process(
                    cmd, "FFmpeg processing", attempt_cb, progress_stdout=True
                )
            except Exception:
                if self.cancel_event.is_set() or (
                    family == "software" and encoder != "libsvtav1"
                ):
                    raise
                logging.exception("Hardware encoder failed; retrying with software encoder")
                temp_output.unlink(missing_ok=True)
                sw_encoder = "libx265" if cfg.codec == "hevc" else (
                    "libaom-av1" if cfg.codec == "av1" else "libx264"
                )
                cmd = self.build_encode_command(
                    inputs, maps, temp_output, cfg, sw_encoder, "software", extra
                )
                attempt_cb = self.make_ffmpeg_progress_callback(meta, (0.0, 100.0))
                self.run_logged_process(
                    cmd, "FFmpeg software fallback", attempt_cb, progress_stdout=True
                )
            if not temp_output.exists() or temp_output.stat().st_size == 0:
                raise RuntimeError("Файл результата не создан или пуст")
            temp_output.replace(output_file)
            self.emit_progress((0.0, 100.0), 100.0)
        finally:
            temp_output.unlink(missing_ok=True)

    # --------------------------- queue worker -----------------------------

    def make_output_path(self, input_file: str, target_fps: int) -> Path:
        source = Path(input_file)
        candidate = source.with_name(f"{source.stem}_{target_fps}fps_master.mp4")
        counter = 1
        while candidate.exists():
            candidate = source.with_name(
                f"{source.stem}_{target_fps}fps_master_{counter}{source.suffix}"
            )
            counter += 1
        return candidate

    def process_queue_logic(self, jobs: list[str], cfg: JobConfig) -> None:
        try:
            for input_file in jobs:
                if self.cancel_event.is_set():
                    break
                self.ui_events.put(("active", input_file))
                try:
                    if not Path(input_file).is_file():
                        raise RuntimeError("Исходный файл больше не существует")
                    meta = self.metadata_cache.get(input_file)
                    if not meta:
                        meta = probe_meta(self.ffprobe_path(), input_file)
                        self.metadata_cache[input_file] = meta
                    output_file = self.make_output_path(input_file, cfg.target_fps)
                    if cfg.mode == "rife_tensorrt" and engine is not None:
                        self.run_v35_pipeline(input_file, output_file, cfg)
                    elif cfg.mode == "rife_tensorrt":
                        raise RuntimeError(
                            "Движок v3.5 (media_engine_v35.py) не найден в сборке"
                        )
                    else:
                        self.run_ffmpeg_mode(input_file, output_file, meta, cfg)
                    if input_file in self.failed_files:
                        self.failed_files.remove(input_file)
                    self.ui_events.put(("job_done", input_file, True,
                                        f"Готово: {output_file.name}"))
                except InterruptedError:
                    self.ui_events.put(("job_done", input_file, False,
                                        f"Отменено: {Path(input_file).name}"))
                    break
                except Exception as exc:
                    if self.cancel_event.is_set():
                        self.ui_events.put(
                            ("job_done", input_file, False,
                             f"Отменено: {Path(input_file).name}")
                        )
                        break
                    logging.exception("Processing failed: %s", input_file)
                    try:
                        with open(CRASH_LOG_PATH, "a", encoding="utf-8") as log:
                            log.write(f"{input_file}: {exc}\n")
                    except OSError:
                        pass
                    self.ui_events.put(("job_done", input_file, False,
                                        f"Ошибка {Path(input_file).name}: {exc}"))
                    if self.cancel_event.is_set():
                        break
        finally:
            with self.process_lock:
                procs = list(self.active_processes)
            for proc in procs:
                self.unregister_process(proc)
            # save_current_settings() читает Tk-переменные и geometry(): только
            # в главном потоке. Worker публикует событие, сохраняет UI-поток.
            self.ui_events.put(("save_settings",))
            self.ui_events.put(("finished",))

    # --------------------------- v3.5 engine ------------------------------

    def run_v35_pipeline(self, input_file: str, output_file: Path,
                         cfg: JobConfig) -> None:
        """Основной путь обработки: встроенный конвейер v3.5."""
        if engine is None:
            raise RuntimeError("Движок v3.5 недоступен")
        self.set_stage("Стадия: инициализация конвейера v3.5")
        self.set_status("Диагностика FFmpeg / RIFE / Vulkan...")
        res_match = re.search(r"(\d+)\s*[xX:]\s*(\d+)", str(cfg.target_res))
        scale = f"{res_match.group(1)}x{res_match.group(2)}" if res_match else None
        cfg35 = engine.PipelineConfig(
            input=Path(input_file),
            output=Path(output_file),
            scale=scale,
            fps=str(cfg.target_fps),
            codec=cfg.engine_codec,
            preset=cfg.engine_preset,
            enhance=bool(cfg.engine_enhance),
            gpu=cfg.engine_gpu,
            audio_codec=cfg.audio_mode,
            audio_bitrate=cfg.audio_bitrate,
            ffmpeg=str(self.ffmpeg_path()),
            ffprobe=str(self.ffprobe_path()),
            rife=str(self.rife_path()),
            models_dir=str(self.models_path()),
        )
        stats = engine.run_pipeline(
            cfg35, progress=GuiProgress(self), cancel_event=self.cancel_event
        )
        self.ui_events.put(("v35_stats", stats))
        self.ui_events.put(("stage", "Стадия: завершено"))
        self.ui_events.put((
            "status",
            f"Готово: {Path(output_file).name} · "
            f"{stats.get('size', '—')} · {stats.get('size_ratio', '—')}",
        ))
        logging.info("v3.5 stats: %s", stats)

    # --------------------------- diagnostics ------------------------------

    def run_tensor_cores_stress_test(self) -> None:
        if not HAS_TENSORRT or trt is None:
            self.tensor_test_status.set("TensorRT: библиотека Python не найдена")
            return
        self.tensor_test_status.set("TensorRT: проверка версии и CUDA...")

        def test() -> None:
            try:
                version = getattr(trt, "__version__", "unknown")
                logger = trt.Logger(trt.Logger.ERROR)
                builder = trt.Builder(logger)
                if builder is None:
                    raise RuntimeError("Не удалось создать TensorRT Builder")
                self.ui_events.put((
                    "tensor_test", True,
                    f"TensorRT {version}: Builder создан; инференс-модель не запускалась.",
                ))
            except Exception as exc:
                self.ui_events.put(("tensor_test", False, f"TensorRT: ошибка — {exc}"))

        threading.Thread(target=test, name="TensorRTCheck", daemon=True).start()

    def refresh_system_info(self) -> None:
        """Асинхронно опросить комплектующие и заполнить таблицу диагностики."""
        tree = getattr(self, "system_info_tree", None)
        if tree is None:
            return
        for item in tree.get_children():
            tree.delete(item)
        tree.insert("", "end", values=("Опрос системы…", "Пожалуйста, подождите"))
        threading.Thread(
            target=self._collect_system_info_worker,
            name="SystemInfoCollector",
            daemon=True,
        ).start()

    def _collect_system_info_worker(self) -> None:
        try:
            info = collect_system_info()
            self.ui_events.put(("system_info", info))
        except Exception as exc:
            logging.exception("Не удалось собрать информацию о системе")
            self.ui_events.put(("system_info_error", str(exc)))

    def populate_system_info(self, info: dict[str, str]) -> None:
        tree = getattr(self, "system_info_tree", None)
        if tree is None:
            return
        for item in tree.get_children():
            tree.delete(item)
        for component, value in info.items():
            tree.insert("", "end", values=(component, value))

    def on_close(self) -> None:
        if self.is_running and not messagebox.askyesno(
            "Выход", "Остановить обработку и закрыть программу?"
        ):
            return
        self.closing = True
        self.cancel_event.set()
        self.terminate_processes()
        self.prevent_windows_sleep(False)
        self.save_current_settings()
        logging.getLogger().removeHandler(self.log_handler)
        self.window.destroy()


# ---------------------------------------------------------------------------
# GuiProgress — пересылает прогресс движка v3.5 в UI
# ---------------------------------------------------------------------------

class GuiProgress:
    """Минимальный интерфейс Progress, совместимый с media_engine_v35."""

    def __init__(self, app: "VideoProcessorApp") -> None:
        self.app = app
        self.started = 0.0

    def start(self, description: str, total: float) -> None:
        self.started = time.monotonic()
        self.app.ui_events.put(("stage", f"Стадия: {description}"))
        self.app.ui_events.put(
            ("v35_progress", 0.0, description, "", "--:--:--")
        )

    def update(self, value: float, total: float,
               description: str | None = None) -> None:
        pct = min(100.0, max(0.0, 100.0 * value / max(1.0, total)))
        elapsed = max(0.001, time.monotonic() - self.started)
        rate = pct / elapsed
        eta = format_eta((100.0 - pct) / rate) if rate > 0.0001 else "--:--:--"
        speed = f"{rate * 60.0:.1f}%/мин" if rate > 0.0001 else ""
        self.app.ui_events.put(
            ("v35_progress", pct, description or "", speed, eta)
        )

    def finish(self) -> None:
        self.app.ui_events.put(
            ("v35_progress", 100.0, "", "", "00:00:00")
        )


# ---------------------------------------------------------------------------
# UILogHandler — пересылает логи в UI через очередь событий
# ---------------------------------------------------------------------------

class UILogHandler(logging.Handler):
    def __init__(self, event_queue: queue.Queue):
        super().__init__()
        self.event_queue = event_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            self.event_queue.put(("log", message))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CLI-бэкенд (внутренний режим, GUI остаётся основным продуктом)
# ---------------------------------------------------------------------------

def run_headless(argv: list[str] | None = None) -> int:
    # В windowed-сборке PyInstaller sys.stdout/stderr равны None.
    if sys.stdout is None or sys.stderr is None:
        devnull = open(os.devnull, "w")
        if sys.stdout is None:
            sys.stdout = devnull
        if sys.stderr is None:
            sys.stderr = devnull
    parser = argparse.ArgumentParser(
        prog="RTX_Media_Master_v3.exe --headless",
        description="Внутренний CLI-бэкенд движка v3.5.",
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output")
    parser.add_argument("--fps", default="60")
    parser.add_argument("--codec", default="auto", choices=ENGINE_CODEC_CHOICES)
    parser.add_argument("--preset", default="balanced", choices=ENGINE_PRESET_CHOICES)
    parser.add_argument("--enhance", action="store_true")
    parser.add_argument("--gpu", type=int, default=0)
    opts = parser.parse_args(argv)
    if engine is None:
        print("Движок v3.5 недоступен", file=sys.stderr)
        return 3
    source = Path(opts.input).expanduser().resolve()
    output = Path(opts.output or source.with_name(
        f"{source.stem}_{str(opts.fps).replace('x', 'mul')}fps_master.mp4"
    )).expanduser().resolve()
    cfg = engine.PipelineConfig(
        input=source, output=output, fps=opts.fps, codec=opts.codec,
        preset=opts.preset, enhance=opts.enhance, gpu=opts.gpu,
        audio_codec="copy", audio_bitrate="192k",
    )
    try:
        stats = engine.run_pipeline(cfg)
        for key, value in stats.items():
            print(f"{key:18s}: {value}")
        return 0
    except Exception as exc:
        try:
            import traceback
            crash = Path(os.environ.get("TEMP", ".")) / "rtx_headless_crash.txt"
            crash.write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--headless" in sys.argv[1:]:
        try:
            index = sys.argv.index("--headless")
            sys.exit(run_headless(sys.argv[index + 1:]))
        except SystemExit:
            raise
        except BaseException:
            try:
                import traceback
                crash = Path(os.environ.get("TEMP", ".")) / "rtx_headless_crash.txt"
                crash.write_text(traceback.format_exc(), encoding="utf-8")
            except Exception:
                pass
            raise
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = Tk()
    app = VideoProcessorApp(root)
    root.mainloop()
