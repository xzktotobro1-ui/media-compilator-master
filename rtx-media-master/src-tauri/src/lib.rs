use serde::Serialize;
use serde_json::Value;
use std::process::Command;

#[derive(Serialize, Clone)]
pub struct GpuInfo {
    pub name: String,
    pub temperature_c: Option<u32>,
    pub utilization_gpu: Option<u32>,
    pub memory_used_mb: Option<u32>,
    pub memory_total_mb: Option<u32>,
    pub encoder: String,
}

#[tauri::command]
fn get_gpu_info() -> GpuInfo {
    // Real query via nvidia-smi; no fabricated values.
    let output = Command::new("nvidia-smi")
        .args([
            "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ])
        .output();

    match output {
        Ok(o) if o.status.success() => {
            let text = String::from_utf8_lossy(&o.stdout);
            let line = text.lines().next().unwrap_or("");
            let parts: Vec<&str> = line.split(',').map(|s| s.trim()).collect();
            let name = parts.get(0).unwrap_or(&"N/A").to_string();
            let temp = parts.get(1).and_then(|s| s.parse::<u32>().ok());
            let util = parts.get(2).and_then(|s| s.parse::<u32>().ok());
            let mem_used = parts.get(3).and_then(|s| s.parse::<u32>().ok());
            let mem_total = parts.get(4).and_then(|s| s.parse::<u32>().ok());
            // Encoder availability is determined by ffmpeg; placeholder honest status here.
            GpuInfo {
                name,
                temperature_c: temp,
                utilization_gpu: util,
                memory_used_mb: mem_used,
                memory_total_mb: mem_total,
                encoder: "check via ffmpeg -encoders".to_string(),
            }
        }
        _ => GpuInfo {
            name: "N/A".to_string(),
            temperature_c: None,
            utilization_gpu: None,
            memory_used_mb: None,
            memory_total_mb: None,
            encoder: "N/A".to_string(),
        },
    }
}

#[tauri::command]
fn probe_media(path: String) -> Result<Value, String> {
    let output = Command::new("ffprobe")
        .args([
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            &path,
        ])
        .output()
        .map_err(|e| format!("ffprobe launch failed: {}", e))?;

    if !output.status.success() {
        return Err(format!(
            "ffprobe failed: {}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }

    serde_json::from_str(&String::from_utf8_lossy(&output.stdout))
        .map_err(|e| format!("ffprobe JSON parse failed: {}", e))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![get_gpu_info, probe_media])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}