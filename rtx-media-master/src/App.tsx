import { useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { open, save } from "@tauri-apps/plugin-dialog";
import { readTextFile, writeTextFile } from "@tauri-apps/plugin-fs";
import { openPath } from "@tauri-apps/plugin-opener";
import { sendNotification } from "@tauri-apps/plugin-notification";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  Check,
  ChevronDown,
  CircleCheck,
  CircleX,
  Clapperboard,
  Copy,
  Cpu,
  Download,
  Film,
  FolderClock,
  FolderOpen,
  Gauge,
  Layers,
  Maximize2,
  Minus,
  Pause,
  Play,
  Plus,
  RotateCcw,
  ScanLine,
  ScrollText,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Square,
  Timer,
  Trash2,
  Upload,
  Wand2,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { Badge, Button, Card, Field, Input, Progress, SectionTitle, Select, Sparkline, Toggle, cn } from "./components/ui";
import "./App.css";

type GpuInfo = {
  name: string;
  temperature_c: number | null;
  utilization_gpu: number | null;
  memory_used_mb: number | null;
  memory_total_mb: number | null;
  encoder: string;
};

type ComponentStatus = { name: string; available: boolean; detail: string };
type SystemInfo = { os: string; cpu: string; ram_gb: string; gpu: string; driver: string; vulkan: string };
type QualityMetrics = { ssim: string; psnr: string };

type QueueItem = {
  id: string;
  path: string;
  name: string;
  duration: number;
  width: number;
  height: number;
  fps: number;
  vfr: boolean;
  codec: string;
  bitrateKbps: number;
  sizeMb: number;
  trimIn: number;
  trimOut: number | null;
  probe: unknown;
};

type LogEntry = { time: string; level: "INFO" | "WARN" | "ERROR"; text: string };

type Preset = {
  id: string;
  title: string;
  subtitle: string;
  icon: LucideIcon;
  apply: Partial<Settings>;
};

type Settings = {
  mode: "compress" | "rife";
  codec: string;
  fps: string;
  profile: string;
  enhance: boolean;
  crf: number;
  targetSize: number;
  bitDepth: "8" | "10";
  audio: string;
  subtitles: string;
  scale: string;
  encoder: string;
  afterComplete: string;
};

const DEFAULT_SETTINGS: Settings = {
  mode: "compress",
  codec: "auto",
  fps: "original",
  profile: "balanced",
  enhance: false,
  crf: 25,
  targetSize: 25,
  bitDepth: "10",
  audio: "copy",
  subtitles: "keep",
  scale: "original",
  encoder: "auto",
  afterComplete: "none",
};

const PRESETS: Preset[] = [
  {
    id: "telegram",
    title: "Telegram / Discord",
    subtitle: "Целевой размер 10–100 МБ",
    icon: Zap,
    apply: { mode: "compress", codec: "h264", profile: "compact", targetSize: 25, audio: "aac" },
  },
  {
    id: "archive",
    title: "Мастер-архив",
    subtitle: "AV1 / HEVC 10-bit, без видимой потери",
    icon: Layers,
    apply: { mode: "compress", codec: "av1", profile: "quality", bitDepth: "10", crf: 24 },
  },
  {
    id: "rife",
    title: "Кино и Аниме 60/120",
    subtitle: "RIFE AI + NVENC/AMF",
    icon: Sparkles,
    apply: { mode: "rife", fps: "60", codec: "hevc", profile: "quality" },
  },
  {
    id: "enhance",
    title: "Реставрация + Резкость",
    subtitle: "bwdif · hqdn3d · zscale · CAS",
    icon: Wand2,
    apply: { mode: "compress", enhance: true, profile: "quality", codec: "hevc" },
  },
];

const TABS: { label: string; icon: LucideIcon }[] = [
  { label: "Очередь и Сжатие", icon: Film },
  { label: "Студия До/После", icon: Clapperboard },
  { label: "Диагностика", icon: Activity },
  { label: "Пресеты и Watch", icon: FolderClock },
  { label: "Журнал и CLI", icon: ScrollText },
];

function rate(value?: string): number {
  if (!value) return 0;
  if (value.includes("/")) {
    const [a, b] = value.split("/").map(Number);
    return b ? a / b : 0;
  }
  return Number(value) || 0;
}

function parseProbe(data: any, path: string): QueueItem {
  const video = data?.streams?.find((s: any) => s.codec_type === "video") ?? {};
  const r = rate(video.r_frame_rate);
  const avg = rate(video.avg_frame_rate);
  const duration = Number(data?.format?.duration ?? video.duration ?? 0) || 0;
  const bitrate = Number(data?.format?.bit_rate ?? video.bit_rate ?? 0) / 1000 || 0;
  return {
    id: `${Date.now()}-${Math.floor(performance.now())}`,
    path,
    name: path.split(/[\\/]/).pop() || path,
    duration,
    width: Number(video.width) || 0,
    height: Number(video.height) || 0,
    fps: avg || r,
    vfr: !!r && !!avg && Math.abs(r - avg) > 0.01,
    codec: String(video.codec_name ?? "N/A"),
    bitrateKbps: Math.round(bitrate),
    sizeMb: Number(data?.format?.size ?? 0) / 1024 / 1024 || 0,
    trimIn: 0,
    trimOut: null,
    probe: data,
  };
}

function fmtTime(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) return "--:--:--";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  return [h, m, s].map((v) => String(v).padStart(2, "0")).join(":");
}

function parseLogLine(line: string): LogEntry {
  const time = new Date().toLocaleTimeString("ru-RU", { hour12: false });
  if (/error|failed|exception|ошибка|не найден/i.test(line)) return { time, level: "ERROR", text: line };
  if (/warn|warning|предупре/i.test(line)) return { time, level: "WARN", text: line };
  return { time, level: "INFO", text: line };
}

export default function App() {
  const [tab, setTab] = useState(0);
  const [gpu, setGpu] = useState<GpuInfo | null>(null);
  const [gpuHistory, setGpuHistory] = useState<number[]>([]);
  const [vramHistory, setVramHistory] = useState<number[]>([]);
  const [tempHistory, setTempHistory] = useState<number[]>([]);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [activePreset, setActivePreset] = useState<string>("telegram");
  const [proOpen, setProOpen] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState("Ожидание");
  const [speed, setSpeed] = useState<string>("N/A");
  const [eta, setEta] = useState<string>("N/A");
  const [running, setRunning] = useState(false);
  const [encoders, setEncoders] = useState<string>("");
  const [components, setComponents] = useState<ComponentStatus[]>([]);
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [metrics, setMetrics] = useState<QualityMetrics | null>(null);
  const [search, setSearch] = useState("");
  const [logFilter, setLogFilter] = useState<"ALL" | "INFO" | "WARN" | "ERROR">("ALL");
  const [customPresets, setCustomPresets] = useState<Record<string, Settings>>(() => {
    try {
      return JSON.parse(localStorage.getItem("rtx-presets") || "{}");
    } catch {
      return {};
    }
  });
  const [watchDir, setWatchDir] = useState<string | null>(null);
  const [watchEvents, setWatchEvents] = useState<string[]>([]);
  const [videoA, setVideoA] = useState<string | null>(null);
  const [videoB, setVideoB] = useState<string | null>(null);
  const [divider, setDivider] = useState(50);
  const [zoom, setZoom] = useState(1);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [syncPlay, setSyncPlay] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const videoARef = useRef<HTMLVideoElement>(null);
  const videoBRef = useRef<HTMLVideoElement>(null);
  const win = useMemo(() => getCurrentWindow(), []);

  const set = <K extends keyof Settings>(key: K, value: Settings[K]) =>
    setSettings((prev) => ({ ...prev, [key]: value }));

  useEffect(() => {
    const loadGpu = async () => {
      try {
        const info = await invoke<GpuInfo>("get_gpu_info");
        setGpu(info);
        setGpuHistory((prev) => [...prev.slice(-39), info.utilization_gpu ?? 0]);
        setVramHistory((prev) => [...prev.slice(-39), info.memory_used_mb ?? 0]);
        setTempHistory((prev) => [...prev.slice(-39), info.temperature_c ?? 0]);
      } catch {
        setGpu(null);
      }
    };
    loadGpu();
    const id = window.setInterval(loadGpu, 3000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    let alive = true;
    invoke<ComponentStatus[]>("check_components").then((v) => alive && setComponents(v)).catch(() => {});
    invoke<SystemInfo>("system_info").then((v) => alive && setSystem(v)).catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const unlisteners: Array<Promise<() => void>> = [];
    unlisteners.push(
      listen<string>("engine-log", (e) => {
        const line = String(e.payload);
        const entry = parseLogLine(line);
        setLogs((prev) => [...prev.slice(-499), entry]);
        const frame = line.match(/frame=\s*(\d+)/);
        const time = line.match(/time=\s*([\d:.]+)/);
        const spd = line.match(/speed=\s*([\d.]+x)/);
        if (frame || time) {
          const t = time?.[1];
          if (t) {
            const parts = t.split(":").map(Number);
            const sec = parts.length === 3 ? parts[0] * 3600 + parts[1] * 60 + parts[2] : Number(t) || 0;
            const total = queue[0]?.duration || 0;
            if (total > 0) {
              const pct = Math.min(100, (sec / total) * 100);
              setProgress(pct);
              win.setProgressBar({ progress: pct / 100 }).catch(() => {});
              const remain = total - sec;
              const speedVal = spd ? parseFloat(spd[1]) : 0;
              setEta(speedVal > 0 ? fmtTime(remain / speedVal) : "N/A");
            }
          }
          if (spd) setSpeed(spd[1]);
          setStage("Кодирование");
        }
        if (/scene|scdet|сцен/i.test(line)) setStage("Сцены");
        if (/rife|interpol/i.test(line)) setStage("RIFE AI");
        if (/verif|ffprobe|проверк/i.test(line)) setStage("Проверка");
      }),
    );
    unlisteners.push(
      listen<number>("engine-done", (e) => {
        const code = Number(e.payload);
        setRunning(false);
        setProgress(code === 0 ? 100 : progress);
        setStage(code === 0 ? "Готово" : "Ошибка");
        win.setProgressBar({ progress: 0 }).catch(() => {});
        try {
          sendNotification({
            title: code === 0 ? "RTX Media Master — готово" : "RTX Media Master — ошибка",
            body: code === 0 ? "Очередь обработана" : `Код завершения: ${code}`,
          });
        } catch {
          /* уведомления могут быть отключены системой */
        }
        if (code === 0 && settings.afterComplete === "folder") {
          openPath(".").catch(() => {});
        }
        if (code === 0 && settings.afterComplete === "sound") {
          try {
            const ctx = new AudioContext();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain).connect(ctx.destination);
            osc.frequency.value = 880;
            gain.gain.value = 0.08;
            osc.start();
            osc.stop(ctx.currentTime + 0.2);
          } catch {
            /* звук недоступен */
          }
        }
      }),
    );
    unlisteners.push(
      listen<string>("watch-event", (e) => setWatchEvents((prev) => [String(e.payload), ...prev].slice(0, 50))),
    );
    return () => unlisteners.forEach((u) => u.then((f) => f()));
  }, [queue, progress, win, settings.afterComplete]);

  useEffect(() => {
    localStorage.setItem("rtx-presets", JSON.stringify(customPresets));
  }, [customPresets]);

  const addFiles = async () => {
    const files = await open({ multiple: true, filters: [{ name: "Video", extensions: ["mp4", "mkv", "mov", "webm", "avi", "m4v"] }] });
    if (!files) return;
    setError(null);
    const list = Array.isArray(files) ? files : [files];
    for (const path of list) {
      try {
        const data = await invoke("probe_media", { path });
        setQueue((prev) => [...prev, parseProbe(data, path)]);
      } catch (e) {
        setError(`${path}: ${String(e)}`);
      }
    }
  };

  const removeItem = (id: string) => setQueue((prev) => prev.filter((i) => i.id !== id));
  const moveItem = (from: number, to: number) => {
    setQueue((prev) => {
      const next = [...prev];
      if (to < 0 || to >= next.length) return prev;
      const [item] = next.splice(from, 1);
      next.splice(to, 0, item);
      return next;
    });
  };

  const calcBitrate = async (item: QueueItem) => {
    try {
      const br = await invoke<number>("calculate_target_bitrate", {
        durationSec: item.duration,
        audioBitrateKbps: 128,
        targetSizeMb: settings.targetSize,
      });
      setLogs((prev) => [...prev, { time: new Date().toLocaleTimeString("ru-RU", { hour12: false }), level: "INFO", text: `${item.name}: видео ${br} kbps при лимите ${settings.targetSize} МБ` }]);
    } catch (e) {
      setError(String(e));
    }
  };

  const buildArgs = (item: QueueItem, testSeconds?: number) => {
    const args = ["--input", item.path, "--fps", settings.fps === "original" ? String(Math.round(item.fps)) : settings.fps, "--codec", settings.codec, "--preset", settings.profile];
    if (settings.crf) args.push("--crf", String(settings.crf));
    if (settings.enhance) args.push("--enhance");
    if (settings.audio !== "copy") args.push("--audio-codec", settings.audio, "--audio-bitrate", settings.audio === "opus" ? "128k" : "192k");
    if (settings.scale !== "original") args.push("--scale", settings.scale);
    if (testSeconds) {
      args.push("--ss", String(item.trimIn), "--to", String(item.trimIn + testSeconds));
    } else {
      if (item.trimIn > 0) args.push("--ss", String(item.trimIn));
      if (item.trimOut !== null && item.trimOut > item.trimIn) args.push("--to", String(item.trimOut));
    }
    return args;
  };

  const startRender = async (testSeconds?: number) => {
    const item = queue[0];
    if (!item || running) return;
    setError(null);
    setLogs([]);
    setProgress(0);
    setStage("Анализ");
    try {
      await invoke("run_engine", { args: buildArgs(item, testSeconds) });
      setRunning(true);
    } catch (e) {
      setError(String(e));
    }
  };

  const cancelRender = async () => {
    try {
      await invoke("cancel_engine");
      setRunning(false);
      setStage("Отменено");
      win.setProgressBar({ progress: 0 }).catch(() => {});
    } catch (e) {
      setError(String(e));
    }
  };

  const checkEncoders = async () => {
    try {
      const out = await invoke<string>("ffmpeg_encoders");
      setEncoders(out);
    } catch (e) {
      setEncoders(String(e));
    }
  };

  const startWatch = async () => {
    const dir = await open({ directory: true });
    if (!dir) return;
    try {
      await invoke("watch_folder", { path: dir });
      setWatchDir(dir);
    } catch (e) {
      setError(String(e));
    }
  };

  const pickCompare = async (slot: "a" | "b") => {
    const file = await open({ multiple: false, filters: [{ name: "Video", extensions: ["mp4", "mkv", "mov", "webm", "avi", "m4v"] }] });
    if (!file) return;
    try {
      const url = await invoke<string>("start_video_server", { path: file });
      if (slot === "a") setVideoA(url);
      else setVideoB(url);
    } catch (e) {
      setError(String(e));
    }
  };

  const stepFrame = (delta: number) => {
    const fps = queue[0]?.fps || 24;
    [videoARef.current, videoBRef.current].forEach((v) => {
      if (v) v.currentTime = Math.max(0, Math.min(v.duration || 0, v.currentTime + delta / fps));
    });
  };

  const runMetrics = async () => {
    if (!videoA || !videoB) return;
    try {
      const result = await invoke<QualityMetrics>("quality_metrics", {
        original: videoA.split("?")[0].replace("http://127.0.0.1:", ""),
        rendered: videoB.split("?")[0].replace("http://127.0.0.1:", ""),
      });
      setMetrics(result);
    } catch (e) {
      setError(String(e));
    }
  };

  const openOutput = async () => {
    try {
      await openPath(watchDir || ".");
    } catch (e) {
      setError(String(e));
    }
  };

  const savePreset = async () => {
    const name = window.prompt("Имя пресета");
    if (!name) return;
    setCustomPresets((prev) => ({ ...prev, [name]: settings }));
  };

  const exportPresets = async () => {
    const path = await save({ defaultPath: "rtx-presets.json", filters: [{ name: "JSON", extensions: ["json"] }] });
    if (path) await writeTextFile(path, JSON.stringify(customPresets, null, 2));
  };

  const importPresets = async () => {
    const path = await open({ multiple: false, filters: [{ name: "JSON", extensions: ["json"] }] });
    if (!path) return;
    try {
      const text = await readTextFile(path);
      setCustomPresets(JSON.parse(text));
    } catch (e) {
      setError(String(e));
    }
  };

  const cliCommand = useMemo(() => {
    const item = queue[0];
    if (!item) return "—";
    return `rtx_engine ${buildArgs(item).join(" ")}`;
  }, [queue, settings]);

  const filteredLogs = logs.filter(
    (l) => (logFilter === "ALL" || l.level === logFilter) && l.text.toLowerCase().includes(search.toLowerCase()),
  );

  const encoderFlags = useMemo(() => {
    const out = encoders.toLowerCase();
    return {
      av1: out.includes("av1"),
      hevc: out.includes("hevc") || out.includes("h265"),
      h264: out.includes("h264"),
      nvenc: out.includes("nvenc"),
      vulkan: !!gpu && gpu.name !== "N/A",
    };
  }, [encoders, gpu]);

  return (
    <div className="relative h-screen overflow-hidden bg-[#09090B] text-zinc-200">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(900px_500px_at_15%_-10%,rgba(16,185,129,0.10),transparent),radial-gradient(700px_500px_at_90%_0%,rgba(6,182,212,0.08),transparent)]" />

      <header className="relative z-20 flex h-16 items-center gap-4 border-b border-white/[0.06] bg-[#09090B]/80 px-5 backdrop-blur-xl" data-tauri-drag-region>
        <div className="flex shrink-0 items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500 to-cyan-500 text-zinc-950 shadow-[0_8px_30px_rgba(16,185,129,0.3)]">
            <Clapperboard size={19} />
          </div>
          <div className="leading-tight">
            <div className="text-[13px] font-semibold tracking-tight text-white">RTX Media Master</div>
            <div className="text-[10px] uppercase tracking-[0.18em] text-emerald-400">Novator Edition · v4.1</div>
          </div>
        </div>

        <nav className="flex min-w-0 flex-1 items-center justify-center gap-0.5 rounded-2xl border border-white/[0.06] bg-white/[0.03] p-1" data-tauri-drag-region>
          {TABS.map(({ label, icon: Icon }, i) => (
            <button
              key={label}
              onClick={() => setTab(i)}
              className={cn(
                "relative flex items-center gap-1.5 rounded-xl px-2 py-2 text-[11px] font-medium transition-colors",
                tab === i ? "text-white" : "text-zinc-500 hover:text-zinc-200",
              )}
            >
              {tab === i && (
                <motion.span
                  layoutId="active-tab"
                  className="absolute inset-0 rounded-xl border border-emerald-400/20 bg-gradient-to-r from-emerald-500/15 to-cyan-500/15"
                  transition={{ type: "spring", stiffness: 400, damping: 30 }}
                />
              )}
              <Icon size={14} className="relative z-10" />
              <span className="relative z-10 whitespace-nowrap">{label}</span>
            </button>
          ))}
        </nav>

        <div className="flex shrink-0 items-center gap-3">
          <div className="hidden min-w-0 max-w-[220px] items-center gap-2 truncate rounded-xl border border-white/[0.06] bg-white/[0.03] px-3 py-1.5 xl:flex">
            <Gauge size={14} className="shrink-0 text-emerald-400" />
            <span className="max-w-[120px] shrink truncate text-[11px] text-zinc-300">{gpu?.name ?? "N/A"}</span>
            <span className="h-3 w-px shrink-0 bg-white/10" />
            <span className="tabular shrink-0 font-mono text-[11px] text-zinc-400">{gpu?.temperature_c ?? "N/A"}°C</span>
            <span className="tabular shrink-0 font-mono text-[11px] text-zinc-400">{gpu?.utilization_gpu ?? "N/A"}%</span>
            <span className="tabular shrink-0 font-mono text-[11px] text-zinc-400">
              {gpu?.memory_used_mb ?? "N/A"}/{gpu?.memory_total_mb ?? "N/A"} MB
            </span>
          </div>
          <Button variant="ghost" size="icon" title="Открыть выходную папку" onClick={openOutput}>
            <FolderOpen size={16} />
          </Button>
          <div className="flex items-center gap-0.5" data-tauri-drag-region>
            <button onClick={() => win.minimize()} className="flex h-8 w-8 items-center justify-center rounded-lg text-zinc-500 hover:bg-white/10 hover:text-white"><Minus size={14} /></button>
            <button onClick={() => win.toggleMaximize()} className="flex h-8 w-8 items-center justify-center rounded-lg text-zinc-500 hover:bg-white/10 hover:text-white"><Maximize2 size={13} /></button>
            <button onClick={() => win.close()} className="flex h-8 w-8 items-center justify-center rounded-lg text-zinc-500 hover:bg-red-500/20 hover:text-red-300"><X size={15} /></button>
          </div>
        </div>
      </header>

      {error && (
        <div className="relative z-10 mx-5 mt-3 flex items-center gap-2 rounded-xl border border-red-500/25 bg-red-500/10 px-4 py-2 text-xs text-red-300">
          <AlertTriangle size={14} /> {error}
          <button className="ml-auto" onClick={() => setError(null)}><X size={14} /></button>
        </div>
      )}

      <main className="relative z-10 h-[calc(100vh-4rem)] overflow-y-auto px-5 pb-28 pt-5">
        <AnimatePresence mode="wait">
          <motion.div
            key={tab}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.22 }}
          >
            {tab === 0 && (
              <div className="space-y-5">
                <div className="grid grid-cols-4 gap-3">
                  {PRESETS.map(({ id, title, subtitle, icon: Icon, apply }) => (
                    <Card
                      key={id}
                      onClick={() => { setSettings((prev) => ({ ...prev, ...apply })); setActivePreset(id); }}
                      className={cn(
                        "group relative cursor-pointer overflow-hidden p-4 transition-all hover:-translate-y-0.5 hover:border-emerald-400/40",
                        activePreset === id && "border-emerald-400/40 bg-gradient-to-br from-emerald-500/10 to-cyan-500/5",
                      )}
                    >
                      <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-xl bg-white/[0.06] text-emerald-300 group-hover:bg-emerald-500/15">
                        <Icon size={18} />
                      </div>
                      <div className="text-sm font-medium text-zinc-100">{title}</div>
                      <div className="mt-1 text-[11px] text-zinc-500">{subtitle}</div>
                      {activePreset === id && <Check size={14} className="absolute right-3 top-3 text-emerald-400" />}
                    </Card>
                  ))}
                </div>

                <Card className="p-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-sm font-medium text-zinc-100">Очередь</div>
                      <div className="text-[11px] text-zinc-500">{queue.length} файлов · данные из ffprobe</div>
                    </div>
                    <div className="flex gap-2">
                      <Button variant="outline" size="sm" onClick={() => { const d = window.prompt("Папка выходных файлов"); if (d) setWatchDir(d); }}><FolderOpen size={13} /> Выходная папка</Button>
                      <Button variant="primary" size="sm" onClick={addFiles}><Plus size={14} /> Добавить видео</Button>
                    </div>
                  </div>

                  {queue.length === 0 ? (
                    <button onClick={addFiles} className="mt-4 flex w-full flex-col items-center gap-2 rounded-xl border border-dashed border-white/10 py-12 text-zinc-500 transition-colors hover:border-emerald-400/40 hover:bg-emerald-500/5">
                      <Film size={28} />
                      <span className="text-sm text-zinc-300">Перетащите файлы или нажмите для выбора</span>
                      <span className="text-[11px]">реальные метаданные извлекаются через ffprobe</span>
                    </button>
                  ) : (
                    <div className="mt-4 space-y-2">
                      {queue.map((item, i) => (
                        <Card key={item.id} className="flex items-center gap-4 p-3">
                          <div className="flex flex-col gap-0.5">
                            <button disabled={i === 0} onClick={() => moveItem(i, i - 1)} className="text-zinc-600 hover:text-emerald-400 disabled:opacity-20">▲</button>
                            <button disabled={i === queue.length - 1} onClick={() => moveItem(i, i + 1)} className="text-zinc-600 hover:text-emerald-400 disabled:opacity-20">▼</button>
                          </div>
                          <div className="flex h-12 w-20 items-center justify-center rounded-lg bg-black/50 text-zinc-600"><Film size={18} /></div>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <span className="truncate text-sm text-zinc-100">{item.name}</span>
                              {item.vfr && <Badge tone="amber">VFR</Badge>}
                            </div>
                            <div className="mt-1 flex flex-wrap gap-3 font-mono text-[10px] text-zinc-500">
                              <span>{fmtTime(item.duration)}</span>
                              <span>{item.width}×{item.height}</span>
                              <span>{item.fps.toFixed(3)} FPS</span>
                              <span>{item.codec}</span>
                              <span>{item.bitrateKbps} kbps</span>
                              <span>{item.sizeMb.toFixed(1)} MB</span>
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            <Input type="number" value={item.trimIn} onChange={(e) => setQueue((p) => p.map((q) => q.id === item.id ? { ...q, trimIn: Number(e.target.value) } : q))} className="w-16" title="Trim In, сек" />
                            <Input type="number" value={item.trimOut ?? ""} onChange={(e) => setQueue((p) => p.map((q) => q.id === item.id ? { ...q, trimOut: e.target.value === "" ? null : Number(e.target.value) } : q))} className="w-16" title="Trim Out, сек" />
                            <Button variant="ghost" size="icon" title="Рассчитать битрейт" onClick={() => calcBitrate(item)}><Gauge size={14} /></Button>
                            <Button variant="ghost" size="icon" title="Тест 5 сек" onClick={() => startRender(5)}><Timer size={14} /></Button>
                            <Button variant="ghost" size="icon" title="Удалить" onClick={() => removeItem(item.id)}><Trash2 size={14} /></Button>
                          </div>
                        </Card>
                      ))}
                    </div>
                  )}
                </Card>

                <Card className="p-4">
                  <SectionTitle title="Прогресс" subtitle="Только реальные данные из вывода процесса" right={<Badge tone={running ? "emerald" : "default"}>{stage}</Badge>} />
                  <Progress value={progress} />
                  <div className="mt-3 grid grid-cols-4 gap-3 font-mono text-[11px] text-zinc-500">
                    <div>Скорость: <span className="text-zinc-200">{speed}</span></div>
                    <div>ETA: <span className="text-zinc-200">{eta}</span></div>
                    <div>Стадия: <span className="text-zinc-200">{stage}</span></div>
                    <div>Кодек: <span className="text-zinc-200">{settings.codec}</span></div>
                  </div>
                </Card>
              </div>
            )}

            {tab === 1 && (
              <div className="space-y-4">
                <SectionTitle title="Студия сравнения До / После" subtitle="Локальный HTTP-поток с поддержкой Range · синхронное воспроизведение" />
                <div className="flex flex-wrap gap-2">
                  <Button variant="outline" size="sm" onClick={() => pickCompare("a")}><Upload size={13} /> Оригинал</Button>
                  <Button variant="outline" size="sm" onClick={() => pickCompare("b")}><Upload size={13} /> Результат</Button>
                  <Button variant="ghost" size="sm" onClick={() => stepFrame(-1)}>-1 кадр</Button>
                  <Button variant="ghost" size="sm" onClick={() => stepFrame(1)}>+1 кадр</Button>
                  <Select value={playbackSpeed} onChange={(e) => { const v = Number(e.target.value); setPlaybackSpeed(v); [videoARef.current, videoBRef.current].forEach((x) => x && (x.playbackRate = v)); }}>
                    <option value={0.25}>0.25x</option><option value={0.5}>0.5x</option><option value={1}>1x</option>
                  </Select>
                  <Select value={zoom} onChange={(e) => setZoom(Number(e.target.value))}>
                    <option value={1}>100%</option><option value={2}>200%</option><option value={3}>300%</option><option value={4}>400%</option>
                  </Select>
                  <Button variant="secondary" size="sm" onClick={() => {
                    const players = [videoARef.current, videoBRef.current];
                    if (syncPlay) players.forEach((v) => v?.pause());
                    else players.forEach((v) => v?.play().catch(() => {}));
                    setSyncPlay(!syncPlay);
                  }}>{syncPlay ? <Pause size={13} /> : <Play size={13} />} {syncPlay ? "Пауза" : "Синхронно"}</Button>
                  <Button variant="primary" size="sm" onClick={runMetrics}><ScanLine size={13} /> SSIM / PSNR</Button>
                </div>
                <div className="relative grid grid-cols-2 gap-2 overflow-hidden rounded-2xl border border-white/[0.08] bg-black">
                  <div className="relative" style={{ transform: `scale(${zoom})`, transformOrigin: "left center" }}>
                    <video ref={videoARef} src={videoA ?? undefined} controls className="h-[420px] w-full bg-black object-contain" />
                    <Badge className="absolute left-3 top-3">Оригинал</Badge>
                  </div>
                  <div className="relative" style={{ transform: `scale(${zoom})`, transformOrigin: "right center" }}>
                    <video ref={videoBRef} src={videoB ?? undefined} controls className="h-[420px] w-full bg-black object-contain" />
                    <Badge tone="emerald" className="absolute right-3 top-3">После</Badge>
                  </div>
                  <div className="pointer-events-none absolute inset-y-0 left-1/2 w-px bg-gradient-to-b from-transparent via-emerald-400/60 to-transparent" style={{ transform: `translateX(${(divider - 50) * 4}px)` }} />
                  <input type="range" min={0} max={100} value={divider} onChange={(e) => setDivider(Number(e.target.value))} className="absolute inset-x-4 bottom-3 z-10 opacity-30 hover:opacity-100" />
                </div>
                <Card className="p-4">
                  <div className="text-sm font-medium">Объективные метрики</div>
                  <div className="mt-2 font-mono text-xs text-zinc-400">
                    {metrics ? <div className="flex gap-6"><span>SSIM: <span className="text-emerald-300">{metrics.ssim}</span></span><span>PSNR: <span className="text-cyan-300">{metrics.psnr}</span></span></div> : "Нажмите «SSIM / PSNR» для реального расчета через ffmpeg"}
                  </div>
                  {queue.length > 0 && <div className="mt-2 font-mono text-[11px] text-zinc-500">Вес original: {queue[0].sizeMb.toFixed(1)} MB · битрейт: {queue[0].bitrateKbps} kbps</div>}
                </Card>
              </div>
            )}

            {tab === 2 && (
              <div className="grid grid-cols-2 gap-4">
                <Card className="p-5">
                  <SectionTitle title="GPU Core / Энкодер / VRAM / Температура" subtitle="Реальный опрос nvidia-smi" right={<Badge tone={gpu ? "emerald" : "red"}>{gpu ? "онлайн" : "N/A"}</Badge>} />
                  <div className="space-y-3">
                    <div><div className="mb-1 flex justify-between text-[11px] text-zinc-500"><span>GPU загрузка</span><span className="tabular font-mono text-zinc-200">{gpu?.utilization_gpu ?? "N/A"}%</span></div><Sparkline values={gpuHistory} /></div>
                    <div><div className="mb-1 flex justify-between text-[11px] text-zinc-500"><span>VRAM</span><span className="tabular font-mono text-zinc-200">{gpu?.memory_used_mb ?? "N/A"} MB</span></div><Sparkline values={vramHistory} color="#06b6d4" /></div>
                    <div><div className="mb-1 flex justify-between text-[11px] text-zinc-500"><span>Температура</span><span className="tabular font-mono text-zinc-200">{gpu?.temperature_c ?? "N/A"}°C</span></div><Sparkline values={tempHistory} color="#f59e0b" /></div>
                  </div>
                </Card>

                <Card className="p-5">
                  <SectionTitle title="Матрица кодеков" subtitle="Реальный вывод ffmpeg -encoders" right={<Button size="sm" variant="ghost" onClick={checkEncoders}><RotateCcw size={13} /> Проверить</Button>} />
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      ["AV1", encoderFlags.av1], ["HEVC", encoderFlags.hevc], ["H.264", encoderFlags.h264], ["NVENC", encoderFlags.nvenc], ["Vulkan", encoderFlags.vulkan],
                    ].map(([name, ok]) => (
                      <div key={String(name)} className="flex items-center justify-between rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2">
                        <span className="text-xs text-zinc-300">{name}</span>
                        {ok ? <CircleCheck size={15} className="text-emerald-400" /> : <CircleX size={15} className="text-zinc-600" />}
                      </div>
                    ))}
                  </div>
                  {encoders && <pre className="mt-3 max-h-32 overflow-auto rounded-lg bg-black/40 p-2 font-mono text-[9px] text-zinc-600">{encoders.slice(0, 3000)}</pre>}
                </Card>

                <Card className="p-5">
                  <SectionTitle title="Компоненты конвейера" subtitle="Проверка реальных путей" />
                  <div className="space-y-2">
                    {components.map((c) => (
                      <div key={c.name} className="flex items-center gap-3 rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2">
                        {c.available ? <ShieldCheck size={15} className="text-emerald-400" /> : <AlertTriangle size={15} className="text-amber-400" />}
                        <span className="text-xs text-zinc-200">{c.name}</span>
                        <span className="ml-auto truncate font-mono text-[10px] text-zinc-600">{c.detail}</span>
                      </div>
                    ))}
                    {!components.length && <div className="text-xs text-zinc-600">Проверка…</div>}
                  </div>
                </Card>

                <Card className="p-5">
                  <SectionTitle title="Паспорт системы" subtitle="WMI / vulkaninfo" right={<Cpu size={16} className="text-emerald-400" />} />
                  <div className="space-y-2 text-xs">
                    {[
                      ["ОС", system?.os], ["CPU", system?.cpu], ["RAM", system?.ram_gb ? `${system.ram_gb} GB` : undefined],
                      ["Видеокарта", system?.gpu], ["Драйвер", system?.driver], ["Vulkan", system?.vulkan],
                    ].map(([k, v]) => (
                      <div key={String(k)} className="flex justify-between gap-4 border-b border-white/[0.04] pb-1.5">
                        <span className="text-zinc-500">{k}</span><span className="truncate text-right font-mono text-zinc-300">{v ?? "N/A"}</span>
                      </div>
                    ))}
                  </div>
                </Card>
              </div>
            )}

            {tab === 3 && (
              <div className="space-y-5">
                <SectionTitle title="Пресеты и Автоматизация" subtitle="Сохранение в AppData · экспорт/импорт JSON · наблюдение за папкой" />
                <Card className="p-5">
                  <div className="flex flex-wrap gap-2">
                    <Button variant="primary" size="sm" onClick={savePreset}><Plus size={13} /> Сохранить текущий</Button>
                    <Button variant="outline" size="sm" onClick={exportPresets}><Download size={13} /> Экспорт JSON</Button>
                    <Button variant="outline" size="sm" onClick={importPresets}><Upload size={13} /> Импорт JSON</Button>
                  </div>
                  <div className="mt-4 grid grid-cols-3 gap-3">
                    {Object.entries(customPresets).map(([name, cfg]) => (
                      <Card key={name} className="flex items-center gap-3 p-3">
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm text-zinc-100">{name}</div>
                          <div className="font-mono text-[10px] text-zinc-500">{cfg.codec} · {cfg.profile} · CRF {cfg.crf}</div>
                        </div>
                        <Button size="icon" variant="ghost" onClick={() => setSettings(cfg)}><Play size={13} /></Button>
                        <Button size="icon" variant="ghost" onClick={() => setCustomPresets((p) => { const n = { ...p }; delete n[name]; return n; })}><Trash2 size={13} /></Button>
                      </Card>
                    ))}
                    {!Object.keys(customPresets).length && <div className="col-span-3 text-xs text-zinc-600">Сохраненных пресетов нет</div>}
                  </div>
                </Card>

                <Card className="p-5">
                  <SectionTitle title="Папка наблюдения" subtitle="Новые видеофайлы автоматически добавляются в очередь" right={<Button size="sm" variant="primary" onClick={startWatch}><FolderClock size={13} /> Выбрать папку</Button>} />
                  <div className="font-mono text-xs text-zinc-500">{watchDir ?? "папка не выбрана"}</div>
                  <div className="mt-3 max-h-48 space-y-1 overflow-auto rounded-xl bg-black/30 p-3 font-mono text-[10px] text-zinc-500">
                    {watchEvents.length ? watchEvents.map((e, i) => <div key={i}>{e}</div>) : <div>событий нет</div>}
                  </div>
                </Card>
              </div>
            )}

            {tab === 4 && (
              <div className="space-y-4">
                <SectionTitle title="Журнал и CLI" subtitle="Поток вывода rtx_engine · реальная проверка ffprobe" />
                <Card className="p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="relative flex-1 min-w-[200px]">
                      <Search size={14} className="absolute left-3 top-2.5 text-zinc-600" />
                      <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Поиск по журналу" className="pl-9" />
                    </div>
                    {(["ALL", "INFO", "WARN", "ERROR"] as const).map((f) => (
                      <Button key={f} size="sm" variant={logFilter === f ? "primary" : "ghost"} onClick={() => setLogFilter(f)}>{f}</Button>
                    ))}
                    <Button size="sm" variant="outline" onClick={() => { const text = filteredLogs.map((l) => `[${l.time}] ${l.level} ${l.text}`).join("\n"); const blob = new Blob([text], { type: "text/plain" }); const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "rtx-media-master.log"; a.click(); }}><Download size={13} /> Экспорт</Button>
                    <Button size="sm" variant="outline" onClick={() => navigator.clipboard.writeText(cliCommand)}><Copy size={13} /> Скопировать CLI</Button>
                  </div>
                  <div className="mt-3 max-h-[420px] overflow-auto rounded-xl bg-black/40 p-3 font-mono text-[11px] leading-relaxed">
                    {filteredLogs.map((l, i) => (
                      <div key={i} className={cn("flex gap-3", l.level === "ERROR" && "text-red-400", l.level === "WARN" && "text-amber-400", l.level === "INFO" && "text-zinc-400")}>
                        <span className="text-zinc-700">{l.time}</span><span className="w-10 shrink-0">{l.level}</span><span className="break-all">{l.text}</span>
                      </div>
                    ))}
                    {!filteredLogs.length && <div className="text-zinc-700">журнал пуст</div>}
                  </div>
                </Card>
                <Card className="p-4">
                  <SectionTitle title="CLI-команда" subtitle="Формируется из реальных параметров очереди" />
                  <pre className="overflow-auto rounded-xl bg-black/40 p-3 font-mono text-[11px] text-emerald-300">{cliCommand}</pre>
                </Card>
                <Card className="p-4">
                  <SectionTitle title="Верификация ffprobe" subtitle="Проверка выбранного файла" right={<Button size="sm" variant="outline" onClick={addFiles}>Выбрать файл</Button>} />
                  {queue.length ? <pre className="max-h-64 overflow-auto rounded-xl bg-black/40 p-3 font-mono text-[10px] text-zinc-500">{JSON.stringify(queue[0].probe, null, 2)}</pre> : <div className="text-xs text-zinc-600">файл не выбран</div>}
                </Card>
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </main>

      {tab === 0 && (
        <div className="fixed bottom-5 left-1/2 z-30 w-[min(1180px,calc(100%-2.5rem))] -translate-x-1/2">
          <motion.div layout className="rounded-2xl border border-white/[0.08] bg-zinc-900/85 p-3 shadow-[0_24px_80px_rgba(0,0,0,0.6)] backdrop-blur-2xl">
            <div className="flex flex-wrap items-center gap-2">
              <Select value={settings.mode} onChange={(e) => set("mode", e.target.value as Settings["mode"])} className="w-36 pl-3 pr-7"><option value="compress">Только сжатие</option><option value="rife">RIFE + Сжатие</option></Select>
              <Select value={settings.codec} onChange={(e) => set("codec", e.target.value)} className="w-28 pl-3 pr-7"><option value="auto">AV1/HEVC Auto</option><option value="av1">AV1</option><option value="hevc">HEVC</option><option value="h264">H.264</option><option value="vvc">VVC</option></Select>
              <Select value={settings.fps} onChange={(e) => set("fps", e.target.value)} className="w-28 pl-3 pr-7"><option value="original">Исходный</option><option value="60">60</option><option value="120">120</option><option value="2x">2x</option><option value="3x">3x</option></Select>
              <Select value={settings.profile} onChange={(e) => set("profile", e.target.value)} className="w-32"><option value="compact">Compact</option><option value="balanced">Balanced</option><option value="quality">Quality</option></Select>
              <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] px-3 py-1.5"><Toggle checked={settings.enhance} onChange={(v) => set("enhance", v)} label="Enhance" /></div>
              <Button variant="ghost" size="sm" onClick={() => setProOpen(!proOpen)} className="ml-auto"><SlidersHorizontal size={14} /> Pro Studio <ChevronDown size={13} className={cn("transition-transform", proOpen && "rotate-180")} /></Button>
              <Button variant="primary" size="lg" disabled={!queue.length || running} onClick={() => startRender()}><Play size={16} /> Запустить</Button>
              <Button variant="secondary" size="icon" disabled={!running} onClick={cancelRender} title="Отмена"><Square size={14} /></Button>
            </div>
            <AnimatePresence>
              {proOpen && (
                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                  <div className="mt-3 grid grid-cols-6 gap-3 border-t border-white/[0.06] pt-3">
                    <Field label="CRF / CQ"><Input type="number" value={settings.crf} onChange={(e) => set("crf", Number(e.target.value))} /></Field>
                    <Field label="Цель, МБ"><Input type="number" value={settings.targetSize} onChange={(e) => set("targetSize", Number(e.target.value))} /></Field>
                    <Field label="Аудио"><Select value={settings.audio} onChange={(e) => set("audio", e.target.value)} className="w-full"><option value="copy">Копировать</option><option value="aac">AAC 192k</option><option value="opus">Opus 128k</option></Select></Field>
                    <Field label="Масштаб"><Select value={settings.scale} onChange={(e) => set("scale", e.target.value)} className="w-full"><option value="original">Оригинал</option><option value="3840x2160">4K</option><option value="2560x1440">2K</option><option value="1920x1080">1080p</option><option value="1280x720">720p</option></Select></Field>
                    <Field label="После завершения"><Select value={settings.afterComplete} onChange={(e) => set("afterComplete", e.target.value)} className="w-full"><option value="none">Ничего</option><option value="folder">Открыть папку</option><option value="sound">Звуковой сигнал</option></Select></Field>
                    <div className="col-span-3 flex items-end"><Button variant="outline" size="md" onClick={savePreset} className="w-full"><Plus size={14} /> Сохранить пресет</Button></div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        </div>
      )}
    </div>
  );
}
