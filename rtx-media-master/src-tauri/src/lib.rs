use notify::{Config, RecommendedWatcher, RecursiveMode, Watcher};
use serde::Serialize;
use serde_json::Value;
use std::fs::File;
use std::io::{BufReader, Read, Seek, SeekFrom, Write};
use std::net::TcpListener;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::thread;
use tauri::{AppHandle, Emitter};

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
    let output = std::process::Command::new("nvidia-smi")
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
            GpuInfo {
                name: parts.get(0).unwrap_or(&"N/A").to_string(),
                temperature_c: parts.get(1).and_then(|s| s.parse::<u32>().ok()),
                utilization_gpu: parts.get(2).and_then(|s| s.parse::<u32>().ok()),
                memory_used_mb: parts.get(3).and_then(|s| s.parse::<u32>().ok()),
                memory_total_mb: parts.get(4).and_then(|s| s.parse::<u32>().ok()),
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
    let output = std::process::Command::new("ffprobe")
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

#[tauri::command]
fn calculate_target_bitrate(duration_sec: f64, audio_bitrate_kbps: u32, target_size_mb: u32) -> u32 {
    if duration_sec <= 0.0 {
        return 0;
    }
    let total_kbits = target_size_mb as f64 * 8.0 * 1024.0;
    let audio_kbits = audio_bitrate_kbps as f64 * duration_sec;
    let video_kbits = (total_kbits - audio_kbits).max(0.0);
    (video_kbits / duration_sec) as u32
}

#[tauri::command]
fn start_video_server(path: String) -> Result<String, String> {
    let file_path = PathBuf::from(&path);
    if !file_path.exists() {
        return Err("file not found".to_string());
    }
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|e| e.to_string())?;
    let port = listener.local_addr().map_err(|e| e.to_string())?.port();
    let token = format!("{:x}", rand_simple());
    let token_clone = token.clone();
    let path_clone = file_path.clone();
    thread::spawn(move || {
        for stream in listener.incoming() {
            if let Ok(mut stream) = stream {
                let mut buf = [0u8; 4096];
                let n = stream.read(&mut buf).unwrap_or(0);
                let req = String::from_utf8_lossy(&buf[..n]);
                let first_line = req.lines().next().unwrap_or("");
                // token check
                if !req.contains(&format!("token={}", token_clone)) {
                    let _ = stream.write_all(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n");
                    continue;
                }
                // parse range
                let mut range: Option<(u64, u64)> = None;
                for line in req.lines() {
                    if line.to_lowercase().starts_with("range:") {
                        let v = line.split(':').nth(1).unwrap_or("").trim();
                        if let Some(r) = v.strip_prefix("bytes=") {
                            let parts: Vec<&str> = r.split('-').collect();
                            if parts.len() == 2 {
                                let start = parts[0].parse::<u64>().unwrap_or(0);
                                let end = if parts[1].is_empty() {
                                    None
                                } else {
                                    parts[1].parse::<u64>().ok()
                                };
                                range = Some((start, end.unwrap_or(u64::MAX)));
                            }
                        }
                    }
                }

                let file_size = std::fs::metadata(&path_clone).map(|m| m.len()).unwrap_or(0);
                let mut f = File::open(&path_clone).unwrap();
                if let Some((start, end_req)) = range {
                    let end = if end_req == u64::MAX || end_req >= file_size {
                        file_size.saturating_sub(1)
                    } else {
                        end_req
                    };
                    let len = end - start + 1;
                    f.seek(SeekFrom::Start(start)).ok();
                    let mut reader = BufReader::new(f.take(len));
                    let mut body = Vec::with_capacity(len as usize);
                    reader.read_to_end(&mut body).ok();
                    let header = format!(
                        "HTTP/1.1 206 Partial Content\r\nContent-Type: video/mp4\r\nContent-Range: bytes {}-{}/{}\r\nContent-Length: {}\r\nAccept-Ranges: bytes\r\n\r\n",
                        start, end, file_size, len
                    );
                    let _ = stream.write_all(header.as_bytes());
                    let _ = stream.write_all(&body);
                } else {
                    f.seek(SeekFrom::Start(0)).ok();
                    let mut body = Vec::new();
                    f.read_to_end(&mut body).ok();
                    let header = format!(
                        "HTTP/1.1 200 OK\r\nContent-Type: video/mp4\r\nContent-Length: {}\r\nAccept-Ranges: bytes\r\n\r\n",
                        file_size
                    );
                    let _ = stream.write_all(header.as_bytes());
                    let _ = stream.write_all(&body);
                }
            }
        }
    });

    Ok(format!("http://127.0.0.1:{}/?token={}", port, token))
}

fn rand_simple() -> u64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos() as u64
}

#[tauri::command]
fn ffmpeg_encoders() -> Result<String, String> {
    let output = std::process::Command::new("ffmpeg")
        .args(["-encoders"])
        .output()
        .map_err(|e| format!("ffmpeg launch failed: {}", e))?;
    Ok(String::from_utf8_lossy(&output.stdout).to_string()
        + &String::from_utf8_lossy(&output.stderr))
}

#[tauri::command]
fn watch_folder(app: AppHandle, path: String) -> Result<(), String> {
    let (tx, rx) = std::sync::mpsc::channel();
    let mut watcher = RecommendedWatcher::new(tx, Config::default()).map_err(|e| e.to_string())?;
    watcher
        .watch(std::path::Path::new(&path), RecursiveMode::NonRecursive)
        .map_err(|e| e.to_string())?;

    let app_clone = app.clone();
    thread::spawn(move || {
        // keep watcher alive
        let _watcher = watcher;
        while let Ok(event) = rx.recv() {
            if let Ok(ev) = event {
                let _ = app_clone.emit("watch-event", format!("{:?}", ev));
            }
        }
    });
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![
            get_gpu_info,
            probe_media,
            calculate_target_bitrate,
            start_video_server,
            watch_folder,
            ffmpeg_encoders
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}