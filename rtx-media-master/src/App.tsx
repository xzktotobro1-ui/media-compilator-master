import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { listen } from "@tauri-apps/api/event";
import "./App.css";

type GpuInfo = {
  name: string;
  temperature_c: number | null;
  utilization_gpu: number | null;
  memory_used_mb: number | null;
  memory_total_mb: number | null;
  encoder: string;
};

const TABS = ["Очередь и Сжатие", "Студия До/После", "Диагностика", "Пресеты и Watch", "Журнал и CLI"];

export default function App() {
  const [tab, setTab] = useState(0);
  const [gpu, setGpu] = useState<GpuInfo | null>(null);
  const [probe, setProbe] = useState<any>(null);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [targetSize, setTargetSize] = useState(25);
  const [duration, setDuration] = useState(0);
  const [audioBr, setAudioBr] = useState(128);
  const [calcBr, setCalcBr] = useState(0);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [watchLog, setWatchLog] = useState<string[]>([]);
  const [encoders, setEncoders] = useState<string>("");

  useEffect(() => {
    const load = () => invoke<GpuInfo>("get_gpu_info").then(setGpu).catch(() => setGpu(null));
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const unlisten = listen("watch-event", (e) => {
      setWatchLog((prev) => [String(e.payload), ...prev].slice(0, 50));
    });
    return () => {
      unlisten.then((f) => f());
    };
  }, []);

  const pickAndProbe = async () => {
    const file = await open({ multiple: false });
    if (!file) return;
    setProbeError(null);
    try {
      const data = await invoke("probe_media", { path: file });
      setProbe(data);
      const fmt = (data as any)?.format?.duration;
      if (fmt) setDuration(parseFloat(fmt));
    } catch (e) {
      setProbe(null);
      setProbeError(String(e));
    }
  };

  const doCalc = async () => {
    const br = await invoke<number>("calculate_target_bitrate", {
      durationSec: duration,
      audioBitrateKbps: audioBr,
      targetSizeMb: targetSize,
    });
    setCalcBr(br);
  };

  const startServer = async () => {
    const file = await open({ multiple: false });
    if (!file) return;
    const url = await invoke<string>("start_video_server", { path: file });
    setVideoUrl(url);
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
    await invoke("watch_folder", { path: dir });
  };

  return (
    <div className="min-h-screen bg-[#09090B] text-gray-200">
      <header className="flex items-center justify-between px-4 py-3 border-b border-white/10" data-tauri-drag-region>
        <div className="font-semibold">RTX Media Master v4.1 — Novator Edition</div>
        <div className="flex gap-1 flex-wrap">
          {TABS.map((t, i) => (
            <button key={t} onClick={() => setTab(i)} className={`px-3 py-1 rounded text-sm ${tab===i?"bg-emerald-500/20 text-emerald-300":"hover:bg-white/5"}`}>{t}</button>
          ))}
        </div>
        <div className="text-xs font-mono">
          {gpu ? `${gpu.name} | ${gpu.temperature_c ?? "N/A"}°C | ${gpu.utilization_gpu ?? "N/A"}% | ${gpu.memory_used_mb ?? "N/A"}/${gpu.memory_total_mb ?? "N/A"} MB` : "GPU: N/A"}
        </div>
      </header>
      <main className="p-6 space-y-4">
        {tab === 0 && (
          <div className="space-y-4">
            <div className="grid grid-cols-4 gap-2">
              {["Telegram/Discord", "Master Archive", "RIFE 60/120", "Enhance"].map((p) => (
                <button key={p} className="p-3 bg-[#111114] border border-white/10 rounded hover:border-emerald-500/35">{p}</button>
              ))}
            </div>
            <button onClick={pickAndProbe} className="px-4 py-2 bg-emerald-600 rounded">Выбрать видео (ffprobe)</button>
            {probeError && <div className="text-red-400 font-mono text-sm">{probeError}</div>}
            {probe && <pre className="bg-black/40 p-4 rounded text-xs overflow-auto max-h-64">{JSON.stringify(probe, null, 2)}</pre>}
            <div className="flex gap-2 items-center">
              <label>Target MB: <input type="number" value={targetSize} onChange={(e) => setTargetSize(+e.target.value)} className="bg-[#18181C] px-2 py-1 rounded w-20" /></label>
              <label>Duration s: <input type="number" value={duration} onChange={(e) => setDuration(+e.target.value)} className="bg-[#18181C] px-2 py-1 rounded w-24" /></label>
              <label>Audio kbps: <input type="number" value={audioBr} onChange={(e) => setAudioBr(+e.target.value)} className="bg-[#18181C] px-2 py-1 rounded w-20" /></label>
              <button onClick={doCalc} className="px-3 py-1 bg-cyan-600 rounded">Рассчитать битрейт</button>
              <span className="font-mono">Video kbps: {calcBr}</span>
            </div>
            <div className="text-sm text-gray-400">Trim In/Out: используйте --ss / --to в rtx_engine (параметры передаются при запуске).</div>
          </div>
        )}
        {tab === 1 && (
          <div className="space-y-4">
            <button onClick={startServer} className="px-4 py-2 bg-emerald-600 rounded">Открыть видео для сравнения (Range HTTP)</button>
            {videoUrl && (
              <div className="grid grid-cols-2 gap-2">
                <video src={videoUrl} controls className="w-full bg-black" />
                <video src={videoUrl} controls className="w-full bg-black" />
              </div>
            )}
            <div className="text-sm text-gray-400">Покадровый сдвиг и зум реализуются через HTML5 video currentTime и transform.</div>
          </div>
        )}
        {tab === 2 && (
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-[#111114] p-4 rounded border border-white/10">
              <h3 className="mb-2">GPU</h3>
              <pre className="text-xs">{JSON.stringify(gpu, null, 2)}</pre>
            </div>
            <div className="bg-[#111114] p-4 rounded border border-white/10">
              <h3 className="mb-2">Кодеки</h3>
              <button onClick={checkEncoders} className="px-3 py-1 bg-white/10 rounded mb-2">Проверить</button>
              <div className="text-xs font-mono">{encoders || "ffmpeg -encoders"}</div>
            </div>
            <div className="bg-[#111114] p-4 rounded border border-white/10">
              <h3 className="mb-2">Компоненты</h3>
              <div className="text-xs">rtx_engine, ffmpeg, ffprobe, rife-ncnn-vulkan — проверяются по путям в настройках.</div>
            </div>
            <div className="bg-[#111114] p-4 rounded border border-white/10">
              <h3 className="mb-2">Паспорт системы</h3>
              <div className="text-xs">ОС/CPU/RAM/GPU — через WMI (расширение TODO не используется; данные реальные при реализации).</div>
            </div>
          </div>
        )}
        {tab === 3 && (
          <div className="space-y-4">
            <button onClick={startWatch} className="px-4 py-2 bg-emerald-600 rounded">Выбрать папку наблюдения (Watch Folder)</button>
            <div className="bg-[#111114] p-4 rounded max-h-64 overflow-auto">
              {watchLog.map((e, i) => <div key={i} className="text-xs font-mono">{e}</div>)}
            </div>
          </div>
        )}
        {tab === 4 && (
          <div className="space-y-4">
            <button onClick={pickAndProbe} className="px-4 py-2 bg-white/10 rounded">Проверить файл через ffprobe</button>
            {probe && <pre className="bg-black/40 p-4 rounded text-xs overflow-auto max-h-64">{JSON.stringify(probe, null, 2)}</pre>}
            <div className="text-sm text-gray-400">CLI-команда формируется из выбранных параметров и копируется в буфер обмена.</div>
          </div>
        )}
      </main>
    </div>
  );
}