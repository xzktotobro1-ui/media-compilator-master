using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Threading.Tasks;
using RTXMediaMaster.Gui.Models;

namespace RTXMediaMaster.Gui.Services;

public sealed class MediaProbe
{
    public int Width { get; set; }
    public int Height { get; set; }
    public double Fps { get; set; }
    public string Codec { get; set; } = string.Empty;
    public string PixFmt { get; set; } = string.Empty;
    public double DurationSeconds { get; set; }
    public long SizeBytes { get; set; }
    public bool IsVfr { get; set; }
    public bool HasAudio { get; set; }
}

public sealed class ProbeService
{
    private readonly string _ffprobe;

    public ProbeService(string ffprobePath) => _ffprobe = ffprobePath;

    public Task<MediaProbe> ProbeAsync(string filePath, CancellationToken ct = default)
    {
        return Task.Run(() =>
        {
            var psi = new System.Diagnostics.ProcessStartInfo
            {
                FileName = _ffprobe,
                ArgumentList =
                {
                    "-v", "quiet", "-print_format", "json",
                    "-show_format", "-show_streams", filePath
                },
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
                StandardOutputEncoding = System.Text.Encoding.UTF8,
            };
            using var proc = System.Diagnostics.Process.Start(psi)
                ?? throw new InvalidOperationException("Не удалось запустить ffprobe");
            var stdout = proc.StandardOutput.ReadToEnd();
            proc.WaitForExit();
            return Parse(stdout, filePath);
        }, ct);
    }

    private static MediaProbe Parse(string json, string filePath)
    {
        using var doc = JsonDocument.Parse(json);
        var streams = doc.RootElement.GetProperty("streams");
        var fmt = doc.RootElement.TryGetProperty("format", out var f) ? f : default;

        JsonElement video = default;
        bool hasVideo = false;
        foreach (var s in streams.EnumerateArray())
        {
            if (s.TryGetProperty("codec_type", out var ct) && ct.GetString() == "video")
            {
                video = s;
                hasVideo = true;
                break;
            }
        }
        if (!hasVideo) throw new InvalidOperationException("Нет видеопотока");

        double ParseFps(JsonElement el)
        {
            if (!el.TryGetProperty("r_frame_rate", out var r)) return 0;
            var txt = r.GetString() ?? "0/1";
            if (txt.Contains('/'))
            {
                var parts = txt.Split('/');
                var n = double.Parse(parts[0], System.Globalization.CultureInfo.InvariantCulture);
                var d = double.Parse(parts[1], System.Globalization.CultureInfo.InvariantCulture);
                return d > 0 ? n / d : 0;
            }
            return double.TryParse(txt, System.Globalization.NumberStyles.Any,
                System.Globalization.CultureInfo.InvariantCulture, out var v) ? v : 0;
        }

        var width = video.TryGetProperty("width", out var w) ? w.GetInt32() : 0;
        var height = video.TryGetProperty("height", out var h) ? h.GetInt32() : 0;
        var fps = ParseFps(video);
        var codec = video.TryGetProperty("codec_name", out var c) ? c.GetString() ?? string.Empty : string.Empty;
        var pix = video.TryGetProperty("pix_fmt", out var p) ? p.GetString() ?? string.Empty : string.Empty;

        double duration = 0;
        if (video.TryGetProperty("duration", out var vd) && vd.ValueKind == JsonValueKind.String)
            double.TryParse(vd.GetString(), System.Globalization.NumberStyles.Any,
                System.Globalization.CultureInfo.InvariantCulture, out duration);
        if (duration <= 0 && fmt.ValueKind == JsonValueKind.Object &&
            fmt.TryGetProperty("duration", out var fd) && fd.ValueKind == JsonValueKind.String)
            double.TryParse(fd.GetString(), System.Globalization.NumberStyles.Any,
                System.Globalization.CultureInfo.InvariantCulture, out duration);

        bool isVfr = false;
        if (video.TryGetProperty("avg_frame_rate", out var ar))
        {
            var avg = ParseFps(video);
            var r = ParseFps(video);
            if (r > 0 && avg > 0) isVfr = Math.Abs(r - avg) / r > 0.005;
        }

        bool hasAudio = false;
        foreach (var s in streams.EnumerateArray())
        {
            if (s.TryGetProperty("codec_type", out var ct) && ct.GetString() == "audio")
            { hasAudio = true; break; }
        }

        long size = 0;
        try { size = new FileInfo(filePath).Length; } catch { }

        return new MediaProbe
        {
            Width = width, Height = height, Fps = fps, Codec = codec, PixFmt = pix,
            DurationSeconds = duration, SizeBytes = size, IsVfr = isVfr, HasAudio = hasAudio
        };
    }
}

public sealed class ThumbnailService
{
    private readonly string _ffmpeg;

    public ThumbnailService(string ffmpegPath) => _ffmpeg = ffmpegPath;

    /// <summary>
    /// Извлекает один кадр на 1-й секунде в PNG. Возвращает путь к файлу превью.
    /// </summary>
    public async Task<string?> ExtractAsync(string sourceFile, string outputPng, CancellationToken ct = default)
    {
        try
        {
            var psi = new System.Diagnostics.ProcessStartInfo
            {
                FileName = _ffmpeg,
                ArgumentList =
                {
                    "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", "1", "-i", sourceFile,
                    "-vframes", "1", outputPng
                },
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
            };
            using var proc = System.Diagnostics.Process.Start(psi)
                ?? throw new InvalidOperationException("Не удалось запустить ffmpeg");
            await proc.WaitForExitAsync(ct);
            if (File.Exists(outputPng)) return outputPng;
            return null;
        }
        catch
        {
            return null;
        }
    }
}
