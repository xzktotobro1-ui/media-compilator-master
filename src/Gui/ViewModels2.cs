using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Threading.Tasks;
using System.Windows.Input;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using RTXMediaMaster.Gui.Models;
using RTXMediaMaster.Gui.Services;

namespace RTXMediaMaster.Gui.ViewModels;

public partial class SettingsViewModel : ObservableObject
{
    private readonly SettingsService _settingsService;
    private Models.Settings _settings = new();

    public SettingsViewModel(SettingsService settingsService)
    {
        _settingsService = settingsService;
        _settings = settingsService.Load();

        Theme = _settings.Theme;
        TargetFps = _settings.TargetFps;
        Preset = _settings.Preset;
        Codec = _settings.Codec;
        Enhance = _settings.Enhance;
        Scale = _settings.Scale ?? string.Empty;
        CropStart = _settings.CropStart ?? string.Empty;
        CropEnd = _settings.CropEnd ?? string.Empty;
        AudioCodec = _settings.AudioCodec;
        AudioBitrate = _settings.AudioBitrate;
        NoSceneDetect = _settings.NoSceneDetect;
        NoDeinterlace = _settings.NoDeinterlace;
        NoColorMetadata = _settings.NoColorMetadata;
        Verbose = _settings.Verbose;
        Crf = _settings.Crf?.ToString() ?? string.Empty;
        Cq = _settings.Cq?.ToString() ?? string.Empty;
        GpuIndex = _settings.GpuIndex.ToString();
        ChunkFrames = _settings.ChunkFrames.ToString();
        FfmpegPath = _settings.FfmpegPath ?? string.Empty;
        FfprobePath = _settings.FfprobePath ?? string.Empty;
        RifePath = _settings.RifePath ?? string.Empty;
        ModelsDir = _settings.ModelsDir ?? string.Empty;
        AfterCompletion = _settings.AfterCompletion;

        SaveCommand = new RelayCommand(Save);
        ResetCommand = new RelayCommand(Reset);
        OpenSettingsFolderCommand = new RelayCommand(OpenSettingsFolder);
        OpenModelsFolderCommand = new RelayCommand(OpenModelsFolder);
    }

    public string Theme
    {
        get => _settings.Theme;
        set { _settings.Theme = value; OnPropertyChanged(); OnThemeChanged(); }
    }
    public bool IsThemeDark { get => Theme == "dark"; set { if (value) Theme = "dark"; } }
    public bool IsThemeLight { get => Theme == "light"; set { if (value) Theme = "light"; } }
    public bool IsThemeSystem { get => Theme == "system"; set { if (value) Theme = "system"; } }

    private void OnThemeChanged()
    {
        OnPropertyChanged(nameof(IsThemeDark));
        OnPropertyChanged(nameof(IsThemeLight));
        OnPropertyChanged(nameof(IsThemeSystem));
    }
    public string TargetFps { get => _settings.TargetFps; set { _settings.TargetFps = value; OnPropertyChanged(); } }
    public string Preset { get => _settings.Preset; set { _settings.Preset = value; OnPropertyChanged(); } }
    public string Codec { get => _settings.Codec; set { _settings.Codec = value; OnPropertyChanged(); } }
    public bool Enhance { get => _settings.Enhance; set { _settings.Enhance = value; OnPropertyChanged(); } }
    public string Scale { get => _settings.Scale ?? string.Empty; set { _settings.Scale = value; OnPropertyChanged(); OnScaleChanged(); } }
    public bool IsScaleOriginal { get => string.IsNullOrEmpty(Scale); set { if (value) Scale = string.Empty; } }
    public bool IsScale1080 { get => Scale == "1920x1080"; set { if (value) Scale = "1920x1080"; } }
    public bool IsScale1440 { get => Scale == "2560x1440"; set { if (value) Scale = "2560x1440"; } }
    public bool IsScale2160 { get => Scale == "3840x2160"; set { if (value) Scale = "3840x2160"; } }
    public bool IsScaleCustom { get => !string.IsNullOrEmpty(Scale) && Scale != "1920x1080" && Scale != "2560x1440" && Scale != "3840x2160"; set { } }
    private void OnScaleChanged()
    {
        OnPropertyChanged(nameof(IsScaleOriginal));
        OnPropertyChanged(nameof(IsScale1080));
        OnPropertyChanged(nameof(IsScale1440));
        OnPropertyChanged(nameof(IsScale2160));
        OnPropertyChanged(nameof(IsScaleCustom));
    }
    public string CropStart { get => _settings.CropStart ?? string.Empty; set { _settings.CropStart = value; OnPropertyChanged(); } }
    public string CropEnd { get => _settings.CropEnd ?? string.Empty; set { _settings.CropEnd = value; OnPropertyChanged(); } }
    public string AudioCodec { get => _settings.AudioCodec; set { _settings.AudioCodec = value; OnPropertyChanged(); OnAudioChanged(); } }
    public bool IsAudioCopy { get => AudioCodec == "copy"; set { if (value) AudioCodec = "copy"; } }
    public bool IsAudioAac { get => AudioCodec == "aac"; set { if (value) AudioCodec = "aac"; } }
    public bool IsAudioOpus { get => AudioCodec == "opus"; set { if (value) AudioCodec = "opus"; } }
    private void OnAudioChanged()
    {
        OnPropertyChanged(nameof(IsAudioCopy));
        OnPropertyChanged(nameof(IsAudioAac));
        OnPropertyChanged(nameof(IsAudioOpus));
    }
    public string AudioBitrate { get => _settings.AudioBitrate; set { _settings.AudioBitrate = value; OnPropertyChanged(); } }
    public bool NoSceneDetect { get => _settings.NoSceneDetect; set { _settings.NoSceneDetect = value; OnPropertyChanged(); } }
    public bool NoDeinterlace { get => _settings.NoDeinterlace; set { _settings.NoDeinterlace = value; OnPropertyChanged(); } }
    public bool NoColorMetadata { get => _settings.NoColorMetadata; set { _settings.NoColorMetadata = value; OnPropertyChanged(); } }
    public bool Verbose { get => _settings.Verbose; set { _settings.Verbose = value; OnPropertyChanged(); } }
    public string Crf { get => _settings.Crf?.ToString() ?? string.Empty; set { _settings.Crf = string.IsNullOrWhiteSpace(value) ? null : int.Parse(value); OnPropertyChanged(); } }
    public string Cq { get => _settings.Cq?.ToString() ?? string.Empty; set { _settings.Cq = string.IsNullOrWhiteSpace(value) ? null : double.Parse(value); OnPropertyChanged(); } }
    public string GpuIndex { get => _settings.GpuIndex.ToString(); set { _settings.GpuIndex = int.TryParse(value, out var v) ? v : 0; OnPropertyChanged(); } }
    public string ChunkFrames { get => _settings.ChunkFrames.ToString(); set { _settings.ChunkFrames = int.TryParse(value, out var v) ? v : 96; OnPropertyChanged(); } }
    public string FfmpegPath { get => _settings.FfmpegPath ?? string.Empty; set { _settings.FfmpegPath = value; OnPropertyChanged(); } }
    public string FfprobePath { get => _settings.FfprobePath ?? string.Empty; set { _settings.FfprobePath = value; OnPropertyChanged(); } }
    public string RifePath { get => _settings.RifePath ?? string.Empty; set { _settings.RifePath = value; OnPropertyChanged(); } }
    public string ModelsDir { get => _settings.ModelsDir ?? string.Empty; set { _settings.ModelsDir = value; OnPropertyChanged(); } }
    public string AfterCompletion { get => _settings.AfterCompletion; set { _settings.AfterCompletion = value; OnPropertyChanged(); } }

    public ICommand SaveCommand { get; }
    public ICommand ResetCommand { get; }
    public ICommand OpenSettingsFolderCommand { get; }
    public ICommand OpenModelsFolderCommand { get; }

    public void Save()
    {
        _settingsService.Save(_settings);
    }

    private void Reset()
    {
        _settings = new Models.Settings();
        Theme = _settings.Theme;
        TargetFps = _settings.TargetFps;
        Preset = _settings.Preset;
        Codec = _settings.Codec;
        Enhance = _settings.Enhance;
        Scale = string.Empty;
        CropStart = string.Empty;
        CropEnd = string.Empty;
        AudioCodec = _settings.AudioCodec;
        AudioBitrate = _settings.AudioBitrate;
        NoSceneDetect = false;
        NoDeinterlace = false;
        NoColorMetadata = false;
        Verbose = false;
        Crf = string.Empty;
        Cq = string.Empty;
        GpuIndex = "0";
        ChunkFrames = "96";
        FfmpegPath = string.Empty;
        FfprobePath = string.Empty;
        RifePath = string.Empty;
        ModelsDir = string.Empty;
        AfterCompletion = "none";
        Save();
    }

    private void OpenSettingsFolder()
    {
        try { System.Diagnostics.Process.Start("explorer.exe", _settingsService.AppDataDir); } catch { }
    }
    private void OpenModelsFolder()
    {
        var dir = System.IO.Path.Combine(AppContext.BaseDirectory, "models");
        if (!Directory.Exists(dir)) dir = _settingsService.AppDataDir;
        try { System.Diagnostics.Process.Start("explorer.exe", dir); } catch { }
    }
}

public partial class DiagnosticsViewModel : ObservableObject
{
    public ObservableCollection<DiagnosticItem> Components { get; } = new();

    [ObservableProperty]
    private double _gpuUtilization;

    [ObservableProperty]
    private double _vramUsed;

    [ObservableProperty]
    private double _vramTotal;

    [ObservableProperty]
    private double _gpuTemperature;

    [ObservableProperty]
    private double _gpuPower;

    public ObservableCollection<double> SparkUtil { get; } = new();
    public ObservableCollection<double> SparkTemp { get; } = new();

    public string SparkUtilPoints => string.Join(",", SparkUtil.Select((v, i) =>
        $"{i * (280.0 / Math.Max(1, SparkUtil.Count - 1)):0},{80 - (v / 100.0 * 70):0}"));
    public string SparkTempPoints => string.Join(",", SparkTemp.Select((v, i) =>
        $"{i * (280.0 / Math.Max(1, SparkTemp.Count - 1)):0},{80 - (Math.Clamp(v, 0, 100) / 100.0 * 70):0}"));

    public double VramPercent => VramTotal > 0 ? VramUsed / VramTotal * 100 : 0;

    [ObservableProperty]
    private string _gpuName = "RTX 3050";

    [ObservableProperty]
    private string _gpuStatus = "Проверка...";

    public DiagnosticsViewModel()
    {
        Components.Add(new DiagnosticItem { Component = "FFmpeg", Status = "Проверка...", Detail = "" });
        Components.Add(new DiagnosticItem { Component = "FFprobe", Status = "Проверка...", Detail = "" });
        Components.Add(new DiagnosticItem { Component = "RIFE NCNN", Status = "Проверка...", Detail = "" });
        Components.Add(new DiagnosticItem { Component = "Модель rife-v4.6", Status = "Проверка...", Detail = "" });
        Components.Add(new DiagnosticItem { Component = "Vulkan GPU", Status = "Проверка...", Detail = "" });
        RefreshCommand = new RelayCommand(Refresh);
    }

    public ICommand RefreshCommand { get; }

    public void Refresh()
    {
        GpuStatus = "Проверка...";
        foreach (var c in Components) c.Status = "Проверка...";

        // Асинхронная диагностика через ffmpeg -encoders, nvidia-smi, vulkaninfo
        _ = System.Threading.Tasks.Task.Run(() =>
        {
            try
            {
                var appDir = AppContext.BaseDirectory;
                var ffmpeg = System.IO.Path.Combine(appDir, "ffmpeg.exe");
                var ffprobe = System.IO.Path.Combine(appDir, "ffprobe.exe");
                var rife = System.IO.Path.Combine(appDir, "rife-ncnn-vulkan.exe");
                var vulkaninfo = System.IO.Path.Combine(appDir, "vulkaninfo.exe");
                var modelsDir = System.IO.Path.Combine(appDir, "models");

                if (System.IO.File.Exists(ffmpeg))
                {
                    SetComponent("FFmpeg", "OK", ffmpeg);
                    var encoders = CheckEncoders(ffmpeg);
                    UpdateEncoderItems(encoders);
                }
                else SetComponent("FFmpeg", "MISSING", "не найден");

                if (System.IO.File.Exists(ffprobe)) SetComponent("FFprobe", "OK", ffprobe);
                else SetComponent("FFprobe", "MISSING", "не найден");

                if (System.IO.File.Exists(rife)) SetComponent("RIFE NCNN", "OK", rife);
                else SetComponent("RIFE NCNN", "MISSING", "не найден");

                var (modelFound, modelName) = FindModel(modelsDir);
                SetComponent("Модель rife-v4.6", modelFound ? "OK" : "MISSING",
                    modelFound ? modelName : "папка models/ не содержит модель");

                if (System.IO.File.Exists(vulkaninfo)) SetComponent("Vulkan GPU", "OK", vulkaninfo);
                else SetComponent("Vulkan GPU", "WARN", "vulkaninfo отсутствует");

                // Живые цифры GPU через nvidia-smi (CSV): gpu name, utilization, memory.used/total
                QueryGpu();
                GpuStatus = "Готов (nvidia-smi)";
            }
            catch (Exception ex)
            {
                GpuStatus = $"Ошибка: {ex.Message}";
            }
        });
    }

    /// <summary>Опрашивает nvidia-smi без блокировки UI и обновляет SPAРКЛАЙН.</summary>
    private void QueryGpu()
    {
        try
        {
            var psi = new System.Diagnostics.ProcessStartInfo
            {
                FileName = "nvidia-smi",
                Arguments = "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw --format=csv,noheader,nounits",
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
                StandardOutputEncoding = System.Text.Encoding.UTF8,
            };
            using var p = System.Diagnostics.Process.Start(psi);
            if (p == null) return;
            var line = p.StandardOutput.ReadLine() ?? string.Empty;
            p.WaitForExit(3000);
            var parts = line.Split(',').Select(s => s.Trim()).ToArray();
            if (parts.Length >= 4)
            {
                if (double.TryParse(parts[1], System.Globalization.NumberStyles.Any,
                    System.Globalization.CultureInfo.InvariantCulture, out var util)) GpuUtilization = util;
                if (double.TryParse(parts[2], System.Globalization.NumberStyles.Any,
                    System.Globalization.CultureInfo.InvariantCulture, out var usedMb)) VramUsed = usedMb / 1024.0;
                if (double.TryParse(parts[3], System.Globalization.NumberStyles.Any,
                    System.Globalization.CultureInfo.InvariantCulture, out var totalMb)) VramTotal = totalMb / 1024.0;
                GpuName = parts[0];
                if (parts.Length >= 5 && double.TryParse(parts[4], System.Globalization.NumberStyles.Any,
                    System.Globalization.CultureInfo.InvariantCulture, out var temp)) GpuTemperature = temp;
                if (parts.Length >= 6 && double.TryParse(parts[5], System.Globalization.NumberStyles.Any,
                    System.Globalization.CultureInfo.InvariantCulture, out var power)) GpuPower = power;
            }

            System.Windows.Application.Current.Dispatcher.Invoke(() =>
            {
                SparkUtil.Add(GpuUtilization);
                while (SparkUtil.Count > 40) SparkUtil.RemoveAt(0);
                SparkTemp.Add(GpuTemperature);
                while (SparkTemp.Count > 40) SparkTemp.RemoveAt(0);
                OnPropertyChanged(nameof(SparkUtilPoints));
                OnPropertyChanged(nameof(SparkTempPoints));
                OnPropertyChanged(nameof(VramPercent));
            });
        }
        catch
        {
            GpuName = "NVIDIA GPU (nvidia-smi недоступен)";
            GpuStatus = "Внимание: nvidia-smi недоступен";
        }
    }

    private void SetComponent(string name, string status, string detail)
    {
        System.Windows.Application.Current.Dispatcher.Invoke(() =>
        {
            var c = Components.FirstOrDefault(x => x.Component == name);
            if (c != null) { c.Status = status; c.Detail = detail; }
            else Components.Add(new DiagnosticItem { Component = name, Status = status, Detail = detail });
        });
    }

    private HashSet<string> CheckEncoders(string ffmpeg)
    {
        var psi = new System.Diagnostics.ProcessStartInfo
        {
            FileName = ffmpeg, Arguments = "-hide_banner -encoders",
            UseShellExecute = false, RedirectStandardOutput = true, CreateNoWindow = true
        };
        var names = new HashSet<string>();
        try
        {
            using var p = System.Diagnostics.Process.Start(psi);
            if (p != null)
            {
                while (!p.StandardOutput.EndOfStream)
                {
                    var line = p.StandardOutput.ReadLine();
                    if (line == null) continue;
                    var parts = line.Split(' ');
                    if (parts.Length >= 2 && parts[0].Length >= 6 && "VAS.".Contains(parts[0][0].ToString()))
                        names.Add(parts[1]);
                }
                p.WaitForExit();
            }
        }
        catch { }
        return names;
    }

    private void UpdateEncoderItems(HashSet<string> encoders)
    {
        var checks = new[] { ("av1_nvenc", "AV1 NVENC"), ("hevc_nvenc", "HEVC NVENC"),
            ("h264_nvenc", "H.264 NVENC"), ("libsvtav1", "SVT-AV1") };
        foreach (var (enc, label) in checks)
        {
            System.Windows.Application.Current.Dispatcher.Invoke(() =>
            {
                var c = Components.FirstOrDefault(x => x.Component == label);
                if (c == null)
                {
                    Components.Add(new DiagnosticItem
                    {
                        Component = label,
                        Status = encoders.Contains(enc) ? "OK" : "MISSING",
                        Detail = enc
                    });
                }
                else
                {
                    c.Status = encoders.Contains(enc) ? "OK" : "MISSING";
                    c.Detail = enc;
                }
            });
        }
    }

    private (bool Found, string Name) FindModel(string modelsDir)
    {
        if (!Directory.Exists(modelsDir)) return (false, string.Empty);
        foreach (var p in Directory.GetFiles(modelsDir, "*.param", System.IO.SearchOption.AllDirectories))
        {
            var bin = System.IO.Path.ChangeExtension(p, ".bin");
            if (File.Exists(bin)) return (true, System.IO.Path.GetFileName(p));
        }
        return (false, string.Empty);
    }
}

public partial class LogViewModel : ObservableObject
{
    public ObservableCollection<LogEntry> Entries { get; } = new();

    [ObservableProperty]
    private string _filter = string.Empty;

    public ICommand ExportCommand { get; }
    public ICommand CopyCommand { get; }
    public ICommand CopyCliCommand { get; }
    public ICommand ClearCommand { get; }

    [ObservableProperty]
    private string _cliCommand = string.Empty;

    public ObservableCollection<KeyValuePair<string, string>> Verification { get; } = new();

    public LogViewModel()
    {
        ExportCommand = new RelayCommand(Export);
        CopyCommand = new RelayCommand(Copy);
        CopyCliCommand = new RelayCommand(CopyCli);
        ClearCommand = new RelayCommand(Clear);
        Add("RTX Media Master v4.0 запущен", LogLevel.Info);
    }

    public void SetCliCommand(string command) => CliCommand = command;

    public void SetVerification(Dictionary<string, string> data)
    {
        System.Windows.Application.Current.Dispatcher.Invoke(() =>
        {
            Verification.Clear();
            foreach (var kv in data) Verification.Add(kv);
        });
    }

    private void CopyCli()
    {
        try { System.Windows.Clipboard.SetText(CliCommand); } catch { }
    }

    public void Add(string message, LogLevel level = LogLevel.Info, string? source = null)
    {
        System.Windows.Application.Current.Dispatcher.Invoke(() =>
        {
            Entries.Insert(0, new LogEntry { Time = DateTime.Now, Level = level, Message = message, Source = source });
            while (Entries.Count > 5000) Entries.RemoveAt(Entries.Count - 1);
        });
    }

    public IEnumerable<LogEntry> Filtered
    {
        get
        {
            if (string.IsNullOrWhiteSpace(Filter)) return Entries;
            var f = Filter.ToLowerInvariant();
            return EnumerableExtensions.Where(Entries, e => e.Message.ToLowerInvariant().Contains(f)
                || (e.Source ?? "").ToLowerInvariant().Contains(f));
        }
    }

    private void Export()
    {
        var dlg = new Microsoft.Win32.SaveFileDialog
        {
            Filter = "Текст (*.txt)|*.txt",
            FileName = $"RTXMediaMaster_log_{DateTime.Now:yyyyMMdd_HHmm}.txt"
        };
        if (dlg.ShowDialog() == true)
        {
            try
            {
                System.IO.File.WriteAllLines(dlg.FileName,
                    Entries.Select(e => $"[{e.Time:HH:mm:ss}] [{e.Level}] {e.Message}"));
            }
            catch { }
        }
    }

    private void Copy()
    {
        try
        {
            System.Windows.Clipboard.SetText(string.Join("\n",
                Entries.Select(e => $"[{e.Time:HH:mm:ss}] [{e.Level}] {e.Message}")));
        }
        catch { }
    }

    private void Clear() => Entries.Clear();
}

internal static class EnumerableExtensions
{
    public static IEnumerable<T> Where<T>(IEnumerable<T> src, Func<T, bool> pred)
    {
        foreach (var x in src) if (pred(x)) yield return x;
    }
}
