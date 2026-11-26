#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RTX Media Master 3.5 — production-grade RIFE / FFmpeg video pipeline.

Возможности:
  * RIFE NCNN (Vulkan) интерполяция и downscaling FPS;
  * диагностика FFmpeg / FFprobe / RIFE / модели / Vulkan GPU;
  * VFR -> CFR нормализация, scene-cut сегментация, точная A/V синхронизация;
  * AV1 / HEVC / VVC / H.264 с современными quality-rate-control режимами;
  * 10-bit кодирование, опциональный enhance (denoise + CAS);
  * CLI с прогрессом и проверкой результата через ffprobe.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import shutil
import subprocess
import threading

_ACTIVE_PROCS: set[subprocess.Popen] = set()
_PROC_LOCK = threading.Lock()

def register_process(proc: subprocess.Popen) -> None:
    with _PROC_LOCK:
        _ACTIVE_PROCS.add(proc)

def unregister_process(proc: subprocess.Popen) -> None:
    with _PROC_LOCK:
        _ACTIVE_PROCS.discard(proc)

def cancel_active_processes() -> None:
    with _PROC_LOCK:
        procs = list(_ACTIVE_PROCS)
    for proc in procs:
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()
                    proc.wait(timeout=3)
        except Exception:
            LOG.debug('Не удалось завершить процесс движка', exc_info=True)
import sys
import tempfile
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Sequence

APP_NAME = "RTX Media Master"
APP_VERSION = "v3.5"

LOG = logging.getLogger("rtx_media_master")

try:  # прогресс: rich если установлен, иначе стандартный вывод
    from rich.console import Console
    from rich.progress import (
        BarColumn, Progress as RichProgress, TaskProgressColumn,
        TextColumn, TimeRemainingColumn,
    )
    HAVE_RICH = True
except Exception:  # pragma: no cover
    Console = None  # type: ignore[assignment]
    RichProgress = None  # type: ignore[assignment]
    HAVE_RICH = False


class PipelineError(RuntimeError):
    """Критическая ошибка конвейера с понятным сообщением."""


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def parse_fraction(value: Any) -> Fraction:
    """Безопасное преобразование '30000/1001', 29.97 или 60 в Fraction."""
    if value is None:
        return Fraction(0, 1)
    text = str(value).strip()
    if not text or text in {"0/0", "N/A"}:
        return Fraction(0, 1)
    try:
        if "/" in text:
            num, den = text.split("/", 1)
            result = Fraction(int(float(num)), int(float(den)))
        else:
            result = Fraction(str(round(float(text), 6))).limit_denominator(1000000)
        return result if result > 0 else Fraction(0, 1)
    except (ValueError, ZeroDivisionError, OverflowError):
        return Fraction(0, 1)


def parse_target_fps(text: str, source_fps: float) -> float:
    """Разрешает абсолютный FPS или множитель вида 2x от исходного FPS."""
    raw = str(text).strip().lower().replace("х", "x")
    if raw.endswith("x") or raw.startswith("x"):
        mult = parse_fraction(raw.strip("x"))
        if mult <= 0:
            raise PipelineError(f"Некорректный множитель FPS: {text!r}")
        return float(mult) * source_fps
    fps = parse_fraction(raw)
    if fps <= 0:
        raise PipelineError(f"Некорректный целевой FPS: {text!r}")
    return float(fps)


def hidden_run_kwargs() -> dict[str, Any]:
    """Скрывать чёрные окна консоли при запуске ffmpeg/ffprobe/RIFE из GUI."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0  # SW_HIDE
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return {"startupinfo": startupinfo, "creationflags": flags}


def run_command(argv: Sequence[Any], *, capture: bool = False,
                check: bool = True, timeout: float | None = None,
                ) -> subprocess.CompletedProcess[str]:
    """Безопасный запуск внешней команды только списком аргументов."""
    printable = " ".join(str(a) for a in argv)
    LOG.debug("CMD: %s", printable)
    try:
        proc = subprocess.run(
            [str(a) for a in argv], capture_output=capture, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
            **hidden_run_kwargs(),
        )
    except FileNotFoundError as exc:
        raise PipelineError(f"Не найден исполняемый файл: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PipelineError(f"Превышен таймаут команды: {printable}") from exc
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise PipelineError(
            f"Команда завершилась с кодом {proc.returncode}:\n{printable}\n{detail[-3000:]}"
        )
    return proc


def run_ffmpeg_progress(argv: Sequence[Any], duration: float, progress: "Progress",
                        timeout: float | None = None) -> None:
    """Запуск ffmpeg с -progress pipe:1 и передача процентов в GUI/CLI."""
    cmd = [str(a) for a in argv]
    printable = " ".join(cmd)
    LOG.debug("CMD: %s", printable)
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", **hidden_run_kwargs(),
        )
        register_process(proc)
    except FileNotFoundError as exc:
        raise PipelineError(f"Не найден исполняемый файл: {argv[0]}") from exc

    deadline = None if timeout is None else time.monotonic() + timeout
    last_pct = -1.0
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            seconds = None
            if line.startswith("out_time_us="):
                try:
                    seconds = float(line.split("=", 1)[1]) / 1_000_000.0
                except ValueError:
                    seconds = None
            elif line.startswith("out_time="):
                try:
                    parts = line.split("=", 1)[1].split(":")
                    seconds = (float(parts[0]) * 3600.0 + float(parts[1]) * 60.0
                               + float(parts[2]))
                except (ValueError, IndexError):
                    seconds = None
            if seconds is not None and duration > 0:
                pct = min(100.0, max(0.0, seconds / duration * 100.0))
                if pct - last_pct >= 0.5 or pct >= 100.0:
                    progress.update(int(pct), 100, f"Кодирование {pct:.0f}%")
                    last_pct = pct
            if deadline is not None and time.monotonic() > deadline:
                raise PipelineError(f"Превышен таймаут команды: {printable}")
        proc.wait()
        unregister_process(proc)
    except BaseException:
        proc.kill()
        unregister_process(proc)
        proc.communicate()
        raise
    if proc.returncode != 0:
        detail = (proc.stderr.read() if proc.stderr else "").strip()
        raise PipelineError(
            f"Команда завершилась с кодом {proc.returncode}:\n{printable}\n{detail[-3000:]}"
        )


def iter_install_dirs(script_dir: Path) -> list[Path]:
    """Кандидаты каталогов установки без жёстко зашитого绝对路径."""
    dirs: list[Path] = [script_dir, Path.cwd()]
    env_dir = os.environ.get("RTX_MEDIA_MASTER_DIR")
    if env_dir:
        dirs.append(Path(env_dir))
    for env_name in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(env_name)
        if base:
            dirs.append(Path(base) / "RTX Media Master")
            dirs.append(Path(base) / "Programs" / "RTX Media Master")
    try:
        import winreg  # Windows-only
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Uninstall") as root:
                index = 0
                while True:
                    try:
                        sub = winreg.EnumKey(root, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(root, sub) as key:
                            name = str(winreg.QueryValueEx(key, "DisplayName")[0])
                            if "RTX Media Master" in name:
                                location = str(winreg.QueryValueEx(key, "InstallLocation")[0])
                                if location:
                                    dirs.append(Path(location))
                    except OSError:
                        continue
    except Exception:  # pragma: no cover
        pass
    seen: set[str] = set()
    unique: list[Path] = []
    for path in dirs:
        try:
            key = str(path.resolve()).lower()
        except OSError:
            key = str(path).lower()
        if key not in seen and path.exists():
            seen.add(key)
            unique.append(path)
    return unique


def find_executable(name: str, install_dirs: Iterable[Path]) -> Path | None:
    found = shutil.which(name)
    if found:
        return Path(found)
    for directory in install_dirs:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def model_score(path: Path) -> tuple[int, int, str]:
    name = path.name.lower()
    match = re.search(r"v?(\d+)(?:\.(\d+))?", name)
    major = int(match.group(1)) if match and match.group(1) else 0
    minor = int(match.group(2)) if match and match.group(2) else 0
    tier = 4 if major >= 4 else 3 if major == 3 else 2 if major == 2 else 0
    return (tier, major * 10 + minor, str(path).lower())


def find_rife_model(install_dirs: Iterable[Path], explicit: str | None = None) -> Path:
    """Ищем модель только в models/ и непосредственно в каталогах установки.

    Рекурсивный обход всего диска/Program Files недопустим: он натыкается на
    повреждённые симлинки и занимает минуты. Явный --models-dir обходим рекурсивно.
    """
    roots: list[tuple[Path, bool]] = []
    if explicit:
        roots.append((Path(explicit), True))
    for directory in install_dirs:
        roots.append((directory / "models", True))
        roots.append((directory, False))
    seen: set[str] = set()
    candidates: list[Path] = []
    for root, recursive in roots:
        if not root.exists():
            continue
        try:
            key = str(root.resolve()).lower()
        except OSError:
            key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        search = root.rglob("*.param") if recursive else root.glob("*.param")
        try:
            for param in search:
                try:
                    if param.with_suffix(".bin").is_file():
                        candidates.append(param.parent)
                except OSError:
                    continue
        except OSError:
            continue
    unique = {str(p.resolve()).lower(): p for p in candidates if p.exists()}
    if not unique:
        raise PipelineError(
            "Не найдена модель RIFE (нужна пара .param + .bin). "
            "Положите rife-v4.6 в каталог models рядом с rife-ncnn-vulkan.exe "
            "или укажите --models-dir."
        )
    return sorted(unique.values(), key=model_score, reverse=True)[0]


def check_vulkan(vulkaninfo: Path | None, gpu_index: int) -> str:
    """Проверяет наличие Vulkan-устройства; возвращает описание GPU."""
    if vulkaninfo is None:
        LOG.warning("vulkaninfo не найден: GPU проверит сам rife-ncnn-vulkan")
        return "не проверено (vulkaninfo отсутствует)"
    proc = run_command([vulkaninfo, "--summary"], capture=True, check=False, timeout=60)
    text = f"{proc.stdout}\n{proc.stderr}"
    devices = [
        line.strip() for line in text.splitlines()
        if "deviceName" in line or "deviceType" in line
    ]
    if proc.returncode != 0 and not devices:
        raise PipelineError(
            "Vulkan-устройства не обнаружены. Установите драйвер GPU с поддержкой Vulkan."
        )
    names = [line.split("=", 1)[1].strip() for line in devices if "deviceName" in line]
    if not names:
        raise PipelineError("Vulkan работает, но физические GPU не найдены.")
    if gpu_index < 0 or gpu_index >= len(names):
        raise PipelineError(
            f"Запрошен --gpu {gpu_index}, но доступно устройств: {len(names)}: {', '.join(names)}"
        )
    return names[gpu_index]


@dataclass(slots=True)
class Tools:
    ffmpeg: Path
    ffprobe: Path
    rife: Path
    model: Path
    vulkan_gpu: str
    install_dirs: list[Path] = field(default_factory=list)

    @classmethod
    def discover(cls, *, ffmpeg: str | None, ffprobe: str | None,
                 rife: str | None, models_dir: str | None, gpu: int) -> "Tools":
        dirs = iter_install_dirs(Path(__file__).resolve().parent)
        if not dirs:
            raise PipelineError(
                "Не найден каталог установки RTX Media Master. Укажите пути вручную "
                "или переменную RTX_MEDIA_MASTER_DIR."
            )
        ffmpeg_path = Path(ffmpeg) if ffmpeg else (
            find_executable("ffmpeg.exe", dirs) or find_executable("ffmpeg", dirs)
        )
        ffprobe_path = Path(ffprobe) if ffprobe else (
            find_executable("ffprobe.exe", dirs) or find_executable("ffprobe", dirs)
        )
        rife_path = Path(rife) if rife else (
            find_executable("rife-ncnn-vulkan.exe", dirs) or find_executable("rife-ncnn-vulkan", dirs)
        )
        missing: list[str] = []
        if not ffmpeg_path or not ffmpeg_path.is_file():
            missing.append("ffmpeg")
        if not ffprobe_path or not ffprobe_path.is_file():
            missing.append("ffprobe")
        if not rife_path or not rife_path.is_file():
            missing.append("rife-ncnn-vulkan")
        if missing:
            raise PipelineError(
                "Отсутствуют обязательные компоненты: " + ", ".join(missing) +
                ". Укажите пути вручную или переустановите RTX Media Master."
            )
        model = find_rife_model(dirs, models_dir)
        vulkan = find_executable("vulkaninfo.exe", dirs) or find_executable("vulkaninfo", dirs)
        gpu_name = check_vulkan(vulkan, gpu)
        return cls(ffmpeg_path, ffprobe_path, rife_path, model, gpu_name, dirs)

    def log_summary(self) -> None:
        LOG.info("FFmpeg : %s", self.ffmpeg)
        LOG.info("FFprobe: %s", self.ffprobe)
        LOG.info("RIFE   : %s", self.rife)
        LOG.info("Модель : %s", self.model.name)
        LOG.info("Vulkan : %s", self.vulkan_gpu)


# ---------------------------------------------------------------------------
# Медиа-информация
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class MediaInfo:
    path: Path
    width: int
    height: int
    fps: Fraction
    duration: float
    pix_fmt: str
    bit_depth: int
    color_space: str
    color_transfer: str
    color_primaries: str
    color_range: str
    field_order: str
    nb_frames: int
    video_stream: dict[str, Any]
    audio_stream: dict[str, Any] | None
    subtitle_streams: list[dict[str, Any]]
    is_vfr: bool
    size_bytes: int

    @property
    def source_bitrate(self) -> float:
        return self.size_bytes * 8.0 / max(0.1, self.duration)

    @property
    def interlaced(self) -> bool:
        return str(self.field_order).lower() not in {"", "progressive", "unknown"}


def probe_media(ffprobe: Path, path: Path) -> MediaInfo:
    """Полный probe: -show_format -show_streams в JSON."""
    proc = run_command([
        ffprobe, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ], capture=True, timeout=120)
    try:
        doc = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise PipelineError("FFprobe вернул некорректный JSON") from exc
    streams = doc.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video"]
    if not videos:
        raise PipelineError(f"В файле нет видеопотока: {path}")
    video = videos[0]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    fmt = doc.get("format", {})
    r_fps = parse_fraction(video.get("r_frame_rate"))
    avg_fps = parse_fraction(video.get("avg_frame_rate"))
    fps = avg_fps or r_fps
    if fps <= 0:
        raise PipelineError("Не удалось определить FPS через ffprobe")
    duration = float(video.get("duration") or fmt.get("duration") or 0)
    if duration <= 0:
        nb = str(video.get("nb_frames", ""))
        duration = int(nb) / float(fps) if nb.isdigit() else 0.0
    if duration <= 0:
        raise PipelineError("Не удалось определить длительность видео")
    pix = str(video.get("pix_fmt", "unknown"))
    bit_depth = 10 if any(x in pix for x in ("10", "12", "p010")) else 8
    is_vfr = bool(
        r_fps and avg_fps and
        abs(float(r_fps) - float(avg_fps)) / float(r_fps) > 0.005
    )
    return MediaInfo(
        path=path, width=int(video.get("width", 0)), height=int(video.get("height", 0)),
        fps=fps, duration=duration, pix_fmt=pix, bit_depth=bit_depth,
        color_space=str(video.get("color_space", "")),
        color_transfer=str(video.get("color_transfer", "")),
        color_primaries=str(video.get("color_primaries", "")),
        color_range=str(video.get("color_range", "")),
        field_order=str(video.get("field_order", "")),
        nb_frames=int(video.get("nb_frames") or 0),
        video_stream=video, audio_stream=audios[0] if audios else None,
        subtitle_streams=[s for s in streams if s.get("codec_type") == "subtitle"],
        is_vfr=is_vfr, size_bytes=path.stat().st_size,
    )


def detect_scene_cuts(ffmpeg: Path, info: MediaInfo) -> list[float]:
    """Находит моменты склейки через ffmpeg scdet."""
    proc = run_command([
        ffmpeg, "-hide_banner", "-loglevel", "info", "-i", info.path,
        "-vf", "scdet=threshold=12", "-an", "-f", "null", "-",
    ], capture=True, check=False, timeout=max(300, int(info.duration * 3) + 60))
    text = f"{proc.stdout}\n{proc.stderr}"
    times = [float(m.group(1)) for m in re.finditer(r"lavfi\.scd\.time:\s*([0-9.]+)", text)]
    LOG.info("Scene cuts обнаружено: %d", len(times))
    return sorted(set(times))


# ---------------------------------------------------------------------------
# Кодеры
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class EncoderChoice:
    name: str
    family: str
    pix_fmt: str
    options: list[str]
    description: str


CODEC_CANDIDATES: dict[str, list[tuple[str, str]]] = {
    "auto": [
        # Сначала аппаратные энкодеры: GPU должна использоваться всегда, когда доступна.
        ("av1_nvenc", "nvidia"), ("av1_qsv", "intel"), ("av1_amf", "amd"),
        ("hevc_nvenc", "nvidia"), ("hevc_qsv", "intel"), ("hevc_amf", "amd"),
        ("h264_nvenc", "nvidia"), ("h264_qsv", "intel"), ("h264_amf", "amd"),
        ("libsvtav1", "software"), ("librav1e", "software"), ("libaom-av1", "software"),
        ("libx265", "software"), ("libx264", "software"),
    ],
    "av1": [
        ("av1_nvenc", "nvidia"), ("av1_qsv", "intel"), ("av1_amf", "amd"),
        ("libsvtav1", "software"), ("librav1e", "software"), ("libaom-av1", "software"),
    ],
    "hevc": [("hevc_nvenc", "nvidia"), ("hevc_qsv", "intel"), ("hevc_amf", "amd"), ("libx265", "software")],
    "vvc": [("libvvenc", "software")],
    "h264": [("h264_nvenc", "nvidia"), ("h264_qsv", "intel"), ("h264_amf", "amd"), ("libx264", "software")],
}

PRESET_DELTA = {"compact": 4, "balanced": 0, "quality": -3}
SVT_PRESET = {"compact": 8, "balanced": 6, "quality": 4}
NV_PRESET = {"compact": "p5", "balanced": "p6", "quality": "p7"}
AV1_CQ = {"compact": 38, "balanced": 34, "quality": 30}
SOFT_PRESET = {"compact": "faster", "balanced": "medium", "quality": "slow"}
VVC_PRESET = {"compact": 1, "balanced": 2, "quality": 3}


def available_encoders(ffmpeg: Path) -> set[str]:
    proc = run_command([ffmpeg, "-hide_banner", "-encoders"], capture=True, timeout=60)
    names: set[str] = set()
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) >= 6 and parts[0][0] in "VAS.":
            names.add(parts[1])
    return names


def encoder_works(ffmpeg: Path, name: str, pix_fmt: str) -> bool:
    """Мини-тест: отсекает заявленные, но нефункциональные энкодеры."""
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
        # NVENC rejects tiny frames; 256x144 is the smallest safe probe size.
        "-i", "color=c=black:s=256x144:r=1", "-frames:v", "2",
        "-c:v", name, "-pix_fmt", pix_fmt, "-f", "null", "-",
    ]
    return run_command(cmd, capture=True, check=False, timeout=45).returncode == 0


def encoder_options(name: str, family: str, preset: str, crf: int | None,
                    cq: float | None, maxrate_bps: int) -> list[str]:
    delta = PRESET_DELTA.get(preset, 0)
    caps = ["-maxrate", str(maxrate_bps), "-bufsize", str(maxrate_bps * 2)]
    if name == "av1_nvenc":
        # AV1 NVENC uses CQ 0-63 (not 0-51); a higher CQ means a smaller file.
        value = cq if cq is not None else AV1_CQ.get(preset, 34)
        value = min(63.0, max(1.0, float(value)))
        # Explicit average target: quality cannot inflate the file up to the cap.
        return [
            "-preset", NV_PRESET.get(preset, "p6"), "-tune", "hq", "-rc", "vbr",
            "-cq", f"{value:g}", "-b:v", str(maxrate_bps),
            "-multipass", "qres", "-rc-lookahead", "20",
            "-spatial-aq", "1", "-temporal-aq", "1", *caps,
        ]
    if name in {"hevc_nvenc", "h264_nvenc"}:
        value = cq if cq is not None else 23 + delta
        opts = [
            "-preset", NV_PRESET.get(preset, "p6"), "-tune", "hq", "-rc", "vbr",
            "-cq", f"{value:g}", "-b:v", "0", "-multipass", "qres",
            "-spatial-aq", "1", "-temporal-aq", "1",
        ]
        if name == "hevc_nvenc":
            opts.extend(["-tag:v", "hvc1"])
        return opts + caps
    if name in {"av1_qsv", "av1_amf", "hevc_qsv", "hevc_amf", "h264_qsv", "h264_amf"}:
        opts = ["-rc", "vbr", "-b:v", str(maxrate_bps)]
        if name.startswith("hevc"):
            opts.extend(["-tag:v", "hvc1"])
        return opts
    if name == "libsvtav1":
        value = crf if crf is not None else 28 + delta
        # libsvtav1 ignores FFmpeg -maxrate in CRF mode; capped CRF is mbr=<kbps>.
        mbr = max(1, maxrate_bps // 1000)
        params = (
            f"tune=0:enable-overlays=1:scd=1:keyint=10s:mbr={mbr}"
            ":mbr-overshoot-pct=10"
        )
        return [
            "-preset", str(SVT_PRESET.get(preset, 6)), "-crf", str(value),
            "-svtav1-params", params,
        ]
    if name in {"librav1e", "libaom-av1"}:
        value = crf if crf is not None else 30 + delta
        speed = "-cpu-used" if name == "libaom-av1" else "-speed"
        return [speed, "4" if name == "libaom-av1" else "6", "-crf", str(value), "-b:v", "0", *caps]
    if name == "libx265":
        value = crf if crf is not None else 21 + delta
        return [
            "-preset", SOFT_PRESET.get(preset, "medium"), "-crf", str(value),
            "-x265-params", "aq-mode=3", "-tag:v", "hvc1", *caps,
        ]
    if name == "libvvenc":
        value = crf if crf is not None else 32 + delta
        return [
            "-preset", str(VVC_PRESET.get(preset, 2)), "-qp", str(value),
            "-qpa", "1", "-period", "10", *caps,
        ]
    value = crf if crf is not None else 20 + delta
    return ["-preset", SOFT_PRESET.get(preset, "medium"), "-crf", str(value), *caps]


def choose_encoder(ffmpeg: Path, codec: str, preset: str, crf: int | None,
                   cq: float | None, maxrate_bps: int) -> EncoderChoice:
    requested = codec if codec in CODEC_CANDIDATES else "auto"
    available = available_encoders(ffmpeg)
    LOG.info("Доступно энкодеров: %d", len(available))
    tried: list[str] = []
    for name, family in CODEC_CANDIDATES[requested]:
        if name not in available:
            continue
        pix_candidates = (
            ["p010le", "yuv420p10le", "yuv420p"] if family != "software"
            else ["yuv420p10le", "yuv420p"]
        )
        pix = next((p for p in pix_candidates if encoder_works(ffmpeg, name, p)), None)
        if not pix:
            tried.append(f"{name}(не запустился)")
            continue
        choice = EncoderChoice(
            name, family, pix, encoder_options(name, family, preset, crf, cq, maxrate_bps),
            f"{name} / {pix}",
        )
        LOG.info("Выбран энкодер: %s", choice.description)
        return choice
    raise PipelineError(
        f"Не удалось выбрать рабочий энкодер для --codec {requested}. "
        f"Проверенные: {', '.join(tried) or 'нет'}."
    )


def bitrate_cap(info: MediaInfo, target_fps: float, out_w: int, out_h: int,
                preset: str) -> int:
    """Ограничивает итоговый размер, сохраняя качество как можно выше."""
    factor = {"compact": 0.45, "balanced": 0.62, "quality": 0.80}.get(preset, 0.62)
    fps_ratio = max(0.25, min(4.0, target_fps / float(info.fps)))
    pixel_ratio = max(0.15, min(4.0, (out_w * out_h) / max(1, info.width * info.height)))
    complexity = pixel_ratio ** 0.6 * fps_ratio ** 0.25
    target = info.source_bitrate * min(0.80, factor * complexity)
    pixels = out_w * out_h
    ceiling = (
        45_000_000 if pixels >= 3840 * 2160 else
        35_000_000 if pixels >= 2560 * 1440 else
        20_000_000 if pixels >= 1920 * 1080 else
        12_000_000 if pixels >= 1280 * 720 else 6_000_000
    )
    return int(max(400_000, min(ceiling, target)))


# ---------------------------------------------------------------------------
# Фильтры
# ---------------------------------------------------------------------------

def output_resolution(scale: str | None, info: MediaInfo) -> tuple[int, int]:
    if not scale:
        return info.width, info.height
    match = re.fullmatch(r"\s*(\d+)\s*[xX:]\s*(\d+)\s*", scale)
    if not match:
        raise PipelineError(f"Некорректное --scale: {scale!r} (ожидается 1920x1080)")
    return int(match.group(1)), int(match.group(2))


def build_filters(info: MediaInfo, out_w: int, out_h: int, *,
                  enhance: bool, deinterlace: bool, color_metadata: bool,
                  fps: float | None = None) -> list[str]:
    filters: list[str] = []
    # VFR нормализуется в CFR до интерполяции: иначе RIFE получит
    # неравномерные интервалы и frame pacing «поплывёт».
    if info.is_vfr and fps is None:
        filters.append(f"fps=fps={float(info.fps):.9g}:round=near")
    if info.interlaced and deinterlace:
        filters.append("bwdif=mode=1:parity=auto:deint=all")
    if fps is not None:
        filters.append(f"fps=fps={fps:.9g}:round=near")
    if (out_w, out_h) != (info.width, info.height):
        filters.append(
            f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    if enhance:
        filters.append("hqdn3d=1.2:1.0:3.0:2.4")
        filters.append("cas=strength=0.25")
    if color_metadata:
        filters.append("zscale=matrix=bt709:primaries=bt709:transfer=bt709:range=limited")
    return filters


def filter_arg(filters: Sequence[str]) -> list[str]:
    return ["-vf", ",".join(filters)] if filters else []


# ---------------------------------------------------------------------------
# Прогресс
# ---------------------------------------------------------------------------

class Progress:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._task: Any = None
        self._rich: Any = None
        if enabled and HAVE_RICH:
            self._rich = RichProgress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(), TaskProgressColumn(), TimeRemainingColumn(),
                console=Console(), transient=False,
            )
            self._rich.start()

    def start(self, description: str, total: float) -> None:
        self._description = description
        self._total = max(1, total)
        if self._rich is not None:
            self._task = self._rich.add_task(description, total=self._total)
        elif self.enabled:
            print(f"{description} ...", flush=True)

    def update(self, value: float, total: float, description: str | None = None) -> None:
        total = max(1, total)
        if self._rich is not None and self._task is not None:
            self._rich.update(
                self._task, completed=value, total=total,
                description=description or getattr(self, "_description", "Обработка"),
            )
        elif self.enabled and self._rich is None:
            pct = 100 * value / total
            print(f"\r{pct:5.1f}%", end="", flush=True)

    def finish(self) -> None:
        if self._rich is not None:
            self._rich.stop()
        elif self.enabled:
            print(flush=True)


# ---------------------------------------------------------------------------
# RIFE chunk pipeline
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ChunkRange:
    start: int
    end: int
    overlap_next: bool = False  # включительно


def build_chunks(total_frames: int, cuts: Sequence[float], fps: float,
                 max_chunk_frames: int) -> list[ChunkRange]:
    boundaries = {0, max(0, total_frames - 1)}
    for t in cuts:
        idx = int(round(t * float(fps)))
        if 0 < idx < total_frames - 1:
            boundaries.add(idx)
    ordered = sorted(boundaries)
    cut_set = set()
    for t in cuts:
        idx = int(round(t * float(fps)))
        if 0 < idx < total_frames - 1:
            cut_set.add(idx)
    chunks: list[ChunkRange] = []
    for left, right in zip(ordered, ordered[1:]):
        cursor = left
        while cursor <= right:
            stop = min(cursor + max_chunk_frames, right)
            # 不在硬切点跨块插值，避免把两个镜头糊成一团。
            overlap = stop < right and (stop + 1) not in cut_set
            chunks.append(ChunkRange(cursor, stop, overlap))
            cursor = stop + 1
    return chunks


def extract_chunk(ffmpeg: Path, info: MediaInfo, chunk: ChunkRange,
                  filters: Sequence[str], out_dir: Path,
                  extra_frames: int = 0) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    start_time = chunk.start / float(info.fps)
    frame_count = chunk.end - chunk.start + 1 + extra_frames
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", info.path,
        "-ss", f"{start_time:.9f}", "-frames:v", str(frame_count),
        "-map", "0:v:0", *filter_arg(filters),
        "-fps_mode", "passthrough", "-pix_fmt", "rgb24",
        str(out_dir / "%08d.png"),
    ]
    run_command(cmd, timeout=max(300, frame_count * 3))
    return len(list(out_dir.glob("*.png")))


def interpolate_chunk(tools: Tools, in_dir: Path, out_dir: Path,
                      source_frames: int, target_fps: float, source_fps: float,
                      gpu: int, width: int, height: int,
                      lock: threading.Lock) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    # RIFE -n задаёт точное число выходных кадров. Для каждого чанка оно равно
    # числу исходных кадров, умноженному на коэффициент FPS: суммарная
    # длительность сегментов тогда совпадает с источником, а стыки чанков
    # не теряют кадры (drop_first больше не нужен).
    desired = max(2, int(round(source_frames * target_fps / source_fps)))
    uhd = width * height > 1920 * 1080
    threads = "2:2:2" if uhd else "4:4:4"
    cmd = [
        tools.rife, "-i", in_dir, "-o", out_dir, "-n", str(desired),
        "-m", tools.model, "-g", str(gpu), "-j", threads, "-f", "%08d.png",
    ]
    if uhd:
        cmd.append("-u")
    with lock:  # GPU обслуживаем последовательно
        run_command(cmd, timeout=max(600, desired * 4))
    return len(list(out_dir.glob("*.png")))


def normalize_frames(src_dir: Path, dst_dir: Path,
                     keep: int | None = None) -> int:
    dst_dir.mkdir(parents=True, exist_ok=True)
    frames = sorted(src_dir.glob("*.png"))
    if keep is not None and keep > 0:
        frames = frames[:keep]
    for index, path in enumerate(frames):
        target = dst_dir / f"{index:08d}.png"
        if path != target:
            path.replace(target)
    return len(frames)


def encode_segment(ffmpeg: Path, frames_dir: Path, fps: float, choice: EncoderChoice,
                   output: Path) -> int:
    count = len(list(frames_dir.glob("*.png")))
    if count < 2:
        raise PipelineError(f"Сегмент содержит слишком мало кадров: {count}")
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-framerate", f"{fps:.9g}", "-start_number", "0",
        "-i", str(frames_dir / "%08d.png"),
        "-map", "0:v:0", "-an", "-c:v", choice.name, *choice.options,
        "-pix_fmt", choice.pix_fmt, "-f", "mp4", output,
    ]
    run_command(cmd, timeout=max(600, count * 3))
    return count


def concat_segments(ffmpeg: Path, segments: Sequence[Path], output: Path) -> None:
    if len(segments) == 1:
        segments[0].replace(output)
        return
    list_file = output.with_suffix(".concat.txt")
    list_file.write_text(
        "".join(f"file '{p.as_posix()}'\n" for p in segments), encoding="utf-8"
    )
    run_command([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", list_file,
        "-c", "copy", "-movflags", "+faststart", output,
    ], timeout=max(600, len(segments) * 60))
    list_file.unlink(missing_ok=True)


def mux_audio(ffmpeg: Path, video: Path, source: Path, info: MediaInfo,
              output: Path, *, audio_codec: str, audio_bitrate: str) -> None:
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-fflags", "+genpts", "-i", video, "-i", source,
        "-map", "0:v:0", "-map", "1:a:0?", "-map_metadata", "1",
        "-c:v", "copy", "-t", f"{info.duration:.9f}", "-shortest",
    ]
    if info.audio_stream is not None and audio_codec == "copy":
        cmd.extend(["-c:a", "copy", "-avoid_negative_ts", "make_zero"])
    else:
        codec = "opus" if audio_codec == "opus" else "aac"
        cmd.extend([
            "-c:a", codec, "-b:a", audio_bitrate,
            "-af", "aresample=async=1:first_pts=0",
        ])
    if output.suffix.lower() in {".mp4", ".mov", ".m4v"}:
        cmd.extend(["-movflags", "+faststart"])
    cmd.append(output)
    run_command(cmd, timeout=max(600, int(info.duration * 2) + 120))


def process_upscale(tools: Tools, info: MediaInfo, output: Path, opts: Any,
                    target_fps: float, out_w: int, out_h: int,
                    choice: EncoderChoice, progress: Progress,
                    cancel_event: Any | None = None) -> None:
    total_frames = info.nb_frames or max(2, int(round(info.duration * float(info.fps))))
    cuts = [] if opts.no_scene_detect else detect_scene_cuts(tools.ffmpeg, info)
    chunks = build_chunks(total_frames, cuts, float(info.fps), opts.chunk_frames)
    LOG.info("RIFE: %d кадров, %d сегментов, целевой FPS %.6g",
             total_frames, len(chunks), target_fps)
    progress.start("Интерполяция RIFE + кодирование", len(chunks))
    base_filters = build_filters(
        info, out_w, out_h, enhance=opts.enhance,
        deinterlace=not opts.no_deinterlace,
        color_metadata=not opts.no_color_metadata,
    )
    lock = threading.Lock()
    segments: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="rtx_master_chunks_") as tmp:
        root = Path(tmp)

        def process(index: int, chunk: ChunkRange) -> Path:
            if cancel_event is not None and cancel_event.is_set():
                raise PipelineError("Обработка отменена пользователем")
            with tempfile.TemporaryDirectory(dir=root, prefix=f"seg{index:04d}_") as seg_tmp:
                seg = Path(seg_tmp)
                frames_in, frames_rife, frames_out = seg / "in", seg / "rife", seg / "out"
                core_frames = chunk.end - chunk.start + 1
                extracted = extract_chunk(
                    tools.ffmpeg, info, chunk, base_filters, frames_in,
                    extra_frames=1 if chunk.overlap_next else 0,
                )
                if extracted < 2:
                    raise PipelineError(f"FFmpeg не извлёк кадры для сегмента {index}")
                interpolate_chunk(
                    tools, frames_in, frames_rife, extracted, target_fps,
                    float(info.fps), opts.gpu, out_w, out_h, lock,
                )
                # 多取的 1 帧只用于跨块插值，不进入最终输出。
                keep = min(
                    int(round(core_frames * target_fps / float(info.fps))),
                    len(list(frames_rife.glob("*.png"))),
                )
                count = normalize_frames(frames_rife, frames_out, keep=keep)
                segment = root / f"segment_{index:05d}.mp4"
                encode_segment(tools.ffmpeg, frames_out, target_fps, choice, segment)
                return segment

        with ThreadPoolExecutor(max_workers=min(2, os.cpu_count() or 2)) as pool:
            futures = {pool.submit(process, i, c): i for i, c in enumerate(chunks)}
            for future in as_completed(futures):
                segments.append(future.result())
                progress.update(len(segments), len(chunks),
                                f"Сегмент {len(segments)}/{len(chunks)}")
        progress.update(len(chunks), len(chunks), "Интерполяция завершена")
        video_only = root / "video_only.mp4"
        concat_segments(tools.ffmpeg, sorted(segments), video_only)
        mux_audio(tools.ffmpeg, video_only, info.path, info, output,
                  audio_codec=opts.audio_codec, audio_bitrate=opts.audio_bitrate)
    progress.finish()


def process_downscale(tools: Tools, info: MediaInfo, output: Path, opts: argparse.Namespace,
                      target_fps: float, out_w: int, out_h: int,
                      choice: EncoderChoice, progress: Progress) -> None:
    LOG.info("Downscale FPS: %.6g -> %.6g через ffmpeg fps", float(info.fps), target_fps)
    progress.start("Downscale + кодирование", 100)
    filters = build_filters(
        info, out_w, out_h, enhance=opts.enhance,
        deinterlace=not opts.no_deinterlace,
        color_metadata=not opts.no_color_metadata,
        fps=target_fps,
    )
    with tempfile.TemporaryDirectory(prefix="rtx_master_down_") as tmp:
        video_only = Path(tmp) / "video_only.mp4"
        cmd = [
            tools.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", info.path, "-map", "0:v:0", *filter_arg(filters),
            "-fps_mode", "cfr", "-c:v", choice.name, *choice.options,
            "-pix_fmt", choice.pix_fmt, "-an",
            "-progress", "pipe:1", "-nostats", "-f", "mp4", video_only,
        ]
        run_ffmpeg_progress(cmd, info.duration, progress,
                            timeout=max(900, int(info.duration * 4) + 180))
        progress.update(100, 100, "Кодирование завершено")
        mux_audio(tools.ffmpeg, video_only, info.path, info, output,
                  audio_codec=opts.audio_codec, audio_bitrate=opts.audio_bitrate)
    progress.finish()


# ---------------------------------------------------------------------------
# Верификация
# ---------------------------------------------------------------------------

def verify_output(ffprobe: Path, output: Path, info: MediaInfo,
                  target_fps: float) -> dict[str, Any]:
    actual = probe_media(ffprobe, output)
    fps_error = abs(float(actual.fps) - target_fps) / max(1e-9, target_fps)
    duration_error = abs(actual.duration - info.duration) / max(1e-9, info.duration)
    if fps_error > 0.02:
        LOG.warning("FPS результата %.6g отличается от целевого %.6g",
                    float(actual.fps), target_fps)
    if duration_error > 1.0 / max(1.0, target_fps) + 0.02:
        LOG.warning("Длительность результата %.3f с отличается от исходной %.3f с",
                    actual.duration, info.duration)
    expected_frames = max(1, int(round(info.duration * target_fps)))
    actual_frames = actual.nb_frames or int(round(actual.duration * float(actual.fps)))
    if abs(actual_frames - expected_frames) > 1:
        LOG.warning("Frames %d, expected %d", actual_frames, expected_frames)
    if actual.audio_stream is None and info.audio_stream is not None:
        LOG.warning("Аудиодорожка отсутствует в результате")
    return {
        "codec": actual.video_stream.get("codec_name"),
        "profile": actual.video_stream.get("profile"),
        "pix_fmt": actual.pix_fmt,
        "width": actual.width,
        "height": actual.height,
        "fps": f"{float(actual.fps):.6f} (цель {target_fps:.6f})",
        "duration": f"{actual.duration:.3f} с (исходник {info.duration:.3f} с)",
        "audio": (actual.audio_stream or {}).get("codec_name", "нет"),
        "size": f"{actual.size_bytes / 1024 / 1024:.1f} MiB "
                f"(исходник {info.size_bytes / 1024 / 1024:.1f} MiB)",
        "size_ratio": f"{actual.size_bytes / max(1, info.size_bytes):.3f}x",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rtx_media_master_v35.py",
        description="RIFE NCNN + современный видеокодер: интерполяция, enhance и сжатие.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input", required=True, type=Path, help="исходный видеофайл")
    parser.add_argument("--output", type=Path, help="выходной файл (по умолчанию рядом с исходником)")
    parser.add_argument("--fps", default="60", help="целевой FPS: 24, 30, 60, 120 или множитель 2x")
    parser.add_argument("--codec", default="auto", choices=sorted(CODEC_CANDIDATES), help="видеокодек")
    parser.add_argument("--preset", default="balanced", choices=sorted(PRESET_DELTA), help="профиль размера/качества")
    parser.add_argument("--crf", type=int, help="переопределить CRF/CQ/QP")
    parser.add_argument("--cq", type=float, help="переопределить CQ только для NVENC")
    parser.add_argument("--enhance", action="store_true", help="лёгкий denoise + CAS sharpening")
    parser.add_argument("--gpu", type=int, default=0, help="индекс Vulkan GPU для RIFE")
    parser.add_argument("--scale", help="целевое разрешение, например 1920x1080")
    parser.add_argument("--audio-codec", default="copy", choices=["copy", "aac", "opus"])
    parser.add_argument("--audio-bitrate", default="192k")
    parser.add_argument("--chunk-frames", type=int, default=96, help="кадров на RIFE-чанк")
    parser.add_argument("--no-scene-detect", action="store_true", help="не искать склейки через scdet")
    parser.add_argument("--no-deinterlace", action="store_true")
    parser.add_argument("--no-color-metadata", action="store_true")
    parser.add_argument("--ffmpeg", help="путь к ffmpeg.exe")
    parser.add_argument("--ffprobe", help="путь к ffprobe.exe")
    parser.add_argument("--rife", help="путь к rife-ncnn-vulkan.exe")
    parser.add_argument("--models-dir", help="каталог с моделью RIFE")
    parser.add_argument("--no-progress", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    opts = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if opts.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    progress = Progress(enabled=not opts.no_progress)
    try:
        source = opts.input.expanduser().resolve()
        if not source.is_file():
            raise PipelineError(f"Исходный файл не найден: {source}")
        suffix = str(opts.fps).replace("x", "mul")
        output = (opts.output or source.with_name(f"{source.stem}_{suffix}fps_master.mp4"))
        output = output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)

        LOG.info("%s %s", APP_NAME, APP_VERSION)
        tools = Tools.discover(
            ffmpeg=opts.ffmpeg, ffprobe=opts.ffprobe, rife=opts.rife,
            models_dir=opts.models_dir, gpu=opts.gpu,
        )
        tools.log_summary()

        info = probe_media(tools.ffprobe, source)
        LOG.info(
            "Источник: %dx%d, %.6g FPS%s, %.3f с, %s, %.1f MiB",
            info.width, info.height, float(info.fps),
            " (VFR)" if info.is_vfr else "", info.duration,
            info.pix_fmt, info.size_bytes / 1024 / 1024,
        )
        if info.audio_stream:
            LOG.info("Аудио: %s, %s Hz, %s ch",
                     info.audio_stream.get("codec_name"),
                     info.audio_stream.get("sample_rate"),
                     info.audio_stream.get("channels"))
        if info.subtitle_streams:
            LOG.info("Субтитры: %d дорожек (не переносятся)", len(info.subtitle_streams))

        target_fps = parse_target_fps(opts.fps, float(info.fps))
        out_w, out_h = output_resolution(opts.scale, info)
        cap = bitrate_cap(info, target_fps, out_w, out_h, opts.preset)
        LOG.info("Потолок битрейта: %.2f Мбит/с", cap / 1_000_000)
        choice = choose_encoder(tools.ffmpeg, opts.codec, opts.preset,
                                opts.crf, opts.cq, cap)

        if target_fps > float(info.fps) * 1.001:
            process_upscale(tools, info, output, opts, target_fps, out_w, out_h, choice, progress)
        else:
            process_downscale(tools, info, output, opts, target_fps, out_w, out_h, choice, progress)

        result = verify_output(tools.ffprobe, output, info, target_fps)
        print("\n--- Проверка результата (ffprobe) ---")
        for key, value in result.items():
            print(f"{key:18s}: {value}")
        print(f"Результат: {output}")
        return 0
    except KeyboardInterrupt:
        LOG.error("Обработка прервана пользователем")
        return 130
    except PipelineError as exc:
        LOG.error("%s", exc)
        return 2
    except Exception as exc:  # pragma: no cover
        LOG.exception("Неожиданная ошибка: %s", exc)
        return 3
    finally:
        progress.finish()


# ---------------------------------------------------------------------------
# Публичный API для GUI (CLI остаётся внутренним бэкендом)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class PipelineConfig:
    """Настройки конвейера, приходящие из GUI или CLI."""

    input: Path
    output: Path
    fps: str = "60"
    codec: str = "auto"
    preset: str = "balanced"
    crf: int | None = None
    cq: float | None = None
    enhance: bool = False
    gpu: int = 0
    scale: str | None = None
    audio_codec: str = "copy"
    audio_bitrate: str = "192k"
    chunk_frames: int = 96
    no_scene_detect: bool = False
    no_deinterlace: bool = False
    no_color_metadata: bool = False
    ffmpeg: str | None = None
    ffprobe: str | None = None
    rife: str | None = None
    models_dir: str | None = None


def run_pipeline(cfg: PipelineConfig, progress: Any | None = None,
                 cancel_event: Any | None = None) -> dict[str, Any]:
    """Запускает полный конвейер и возвращает статистику для GUI."""
    source = Path(cfg.input).expanduser().resolve()
    if not source.is_file():
        raise PipelineError(f"Исходный файл не найден: {source}")
    output = Path(cfg.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    tools = Tools.discover(
        ffmpeg=cfg.ffmpeg, ffprobe=cfg.ffprobe, rife=cfg.rife,
        models_dir=cfg.models_dir, gpu=cfg.gpu,
    )
    tools.log_summary()
    info = probe_media(tools.ffprobe, source)
    LOG.info(
        "Источник: %dx%d, %.6g FPS%s, %.3f с, %s, %.1f MiB",
        info.width, info.height, float(info.fps),
        " (VFR)" if info.is_vfr else "", info.duration,
        info.pix_fmt, info.size_bytes / 1024 / 1024,
    )

    target_fps = parse_target_fps(str(cfg.fps), float(info.fps))
    out_w, out_h = output_resolution(cfg.scale, info)
    cap = bitrate_cap(info, target_fps, out_w, out_h, cfg.preset)
    LOG.info("Потолок битрейта: %.2f Мбит/с", cap / 1_000_000)
    choice = choose_encoder(tools.ffmpeg, cfg.codec, cfg.preset, cfg.crf, cfg.cq, cap)
    LOG.info("Выбран энкодер: %s / %s", choice.name, choice.pix_fmt)
    if progress is None:
        progress = Progress(enabled=False)

    if target_fps > float(info.fps) * 1.001:
        process_upscale(tools, info, output, cfg, target_fps, out_w, out_h,
                        choice, progress, cancel_event)
    else:
        process_downscale(tools, info, output, cfg, target_fps, out_w, out_h,
                          choice, progress)

    stats = verify_output(tools.ffprobe, output, info, target_fps)
    stats["output"] = str(output)
    stats["source_size"] = info.size_bytes
    stats["output_size"] = output.stat().st_size if output.exists() else 0
    stats["target_fps"] = target_fps
    return stats



if __name__ == "__main__":
    sys.exit(main())
