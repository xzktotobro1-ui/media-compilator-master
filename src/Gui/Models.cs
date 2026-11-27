namespace RTXMediaMaster.Gui.Models;

public enum ItemStatus
{
    Pending,
    Analyzing,
    Ready,
    Processing,
    Completed,
    Error,
    Cancelled,
    Removed
}

public class QueueItem : CommunityToolkit.Mvvm.ComponentModel.ObservableObject
{
    public string Id { get; } = Guid.NewGuid().ToString("N")[..8];
    public string SourcePath { get; set; } = string.Empty;
    public string FileName => System.IO.Path.GetFileName(SourcePath);
    public string? OutputPath { get; set; }
    public System.Windows.Media.ImageSource? Thumbnail { get; set; }

    public int Width { get; set; }
    public int Height { get; set; }
    public double SourceFps { get; set; }
    public double TargetFps { get; set; }
    public string SourceCodec { get; set; } = string.Empty;
    public string TargetCodec { get; set; } = string.Empty;
    public bool IsVfr { get; set; }
    public double DurationSeconds { get; set; }
    public long SizeBytes { get; set; }

    public string ResolutionLabel
    {
        get
        {
            var p = Height >= 2160 ? "4K" : Height >= 1440 ? "1440p" : Height >= 1080 ? "1080p" :
                    Height >= 720 ? "720p" : $"{Height}p";
            return $"{p} {(int)SourceFps} FPS {SourceCodec} → {(int)TargetFps} FPS {TargetCodec}";
        }
    }

    public string SizeText
    {
        get
        {
            var mb = SizeBytes / 1024.0 / 1024.0;
            return mb < 1024 ? $"{mb:0.##} MiB" : $"{mb / 1024.0:0.##} GiB";
        }
    }

    public string DurationText
    {
        get
        {
            var ts = System.TimeSpan.FromSeconds(DurationSeconds);
            return ts.TotalHours >= 1
                ? $"{ts.Hours:D2}:{ts.Minutes:D2}:{ts.Seconds:D2}"
                : $"{ts.Minutes:D2}:{ts.Seconds:D2}";
        }
    }

    private ItemStatus _status = ItemStatus.Pending;
    public ItemStatus Status
    {
        get => _status;
        set => SetProperty(ref _status, value);
    }

    private double _progress;
    public double Progress
    {
        get => _progress;
        set => SetProperty(ref _progress, value);
    }

    private string _progressText = string.Empty;
    public string ProgressText
    {
        get => _progressText;
        set => SetProperty(ref _progressText, value);
    }

    private string _stage = "Ожидание";
    public string Stage
    {
        get => _stage;
        set => SetProperty(ref _stage, value);
    }

    private string? _error;
    public string? Error
    {
        get => _error;
        set => SetProperty(ref _error, value);
    }
}

public class LogEntry : CommunityToolkit.Mvvm.ComponentModel.ObservableObject
{
    public DateTime Time { get; set; } = DateTime.Now;
    public LogLevel Level { get; set; }
    public string Message { get; set; } = string.Empty;
    public string? Source { get; set; }
}

public enum LogLevel
{
    Info,
    Warning,
    Error,
    Success
}

public class DiagnosticItem
{
    public string Component { get; set; } = string.Empty;
    public string Status { get; set; } = string.Empty; // OK / WARN / MISSING
    public string Detail { get; set; } = string.Empty;
    public bool IsOk => Status == "OK";
}

public class AppTheme
{
    public string Name { get; set; } = string.Empty;
    public string Key { get; set; } = string.Empty;
}
