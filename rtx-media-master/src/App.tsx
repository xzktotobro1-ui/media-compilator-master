import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import "./App.css";

type GpuInfo = {
  name: string;
  temperature_c: number | null;
  utilization_gpu: number | null;
  memory_used_mb: number | null;
  memory_total_mb: number | null;
  encoder: string;
};

const TABS = ["Очередь", "Сравнение", "Диагностика", "Пресеты", "Журнал"];

export default function App() {
  const [tab, setTab] = useState(0);
  const [gpu, setGpu] = useState<GpuInfo | null>(null);
  const [probe, setProbe] = useState<any>(null);
  const [probeError, setProbeError] = useState<string | null>(null);

  const pickAndProbe = async () => {
    const file = await open({ multiple: false, filters: [{ name: "Video", extensions: ["mp4","mkv","mov","avi","webm"] }] });
    if (!file) return;
    setProbeError(null);
    try {
      const data = await invoke("probe_media", { path: file });
      setProbe(data);
    } catch (e) {
      setProbe(null);
      setProbeError(String(e));
    }
  };

  useEffect(() => {
    const load = () => invoke<GpuInfo>("get_gpu_info").then(setGpu).catch(() => setGpu(null));
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="min-h-screen bg-bg text-gray-200">
      <header className="flex items-center justify-between px-4 py-3 border-b border-white/10" data-tauri-drag-region>
        <div className="font-semibold">RTX Media Master v4.1 — Novator Edition</div>
        <div className="flex gap-2">
          {TABS.map((t, i) => (
            <button key={t} onClick={() => setTab(i)} className={`px-3 py-1 rounded ${tab===i?"bg-emerald-500/20 text-emerald-300":"hover:bg-white/5"}`}>{t}</button>
          ))}
        </div>
        <div className="text-sm font-mono">
          {gpu ? `${gpu.name} | ${gpu.temperature_c ?? "N/A"}°C | ${gpu.utilization_gpu ?? "N/A"}% | ${gpu.memory_used_mb ?? "N/A"}/${gpu.memory_total_mb ?? "N/A"} MB` : "GPU: N/A"}
        </div>
      </header>
      <main className="p-6">
        {tab === 0 && (
          <div className="space-y-4">
            <button onClick={pickAndProbe} className="px-4 py-2 bg-emerald-600 rounded">Выбрать видео и получить метаданные (ffprobe)</button>
            {probeError && <div className="text-red-400 font-mono text-sm">{probeError}</div>}
            {probe && <pre className="bg-black/40 p-4 rounded text-xs overflow-auto max-h-96">{JSON.stringify(probe, null, 2)}</pre>}
          </div>
        )}
        {tab !== 0 && <p className="text-gray-400">Вкладка: {TABS[tab]}</p>}
      </main>
    </div>
  );
}