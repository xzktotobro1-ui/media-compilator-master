using System;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text.Json;
using System.Threading.Tasks;

namespace RTXMediaMaster.Gui.Services;

public sealed class UpdateInfo
{
    public bool Available { get; set; }
    public string? LatestVersion { get; set; }
    public string? HtmlUrl { get; set; }
    public string? ReleaseNotes { get; set; }
    public string? Error { get; set; }
}

public sealed class UpdateService : IDisposable
{
    private readonly HttpClient _http;
    public UpdateService()
    {
        _http = new HttpClient { Timeout = TimeSpan.FromSeconds(10) };
        _http.DefaultRequestHeaders.UserAgent.Add(new ProductInfoHeaderValue("RTX-Media-Master-Updater", "4.0"));
    }

    public async Task<UpdateInfo> CheckAsync(CancellationToken ct = default)
    {
        var result = new UpdateInfo();
        try
        {
            var url = "https://api.github.com/repos/xzktotobro1-ui/media-compilator-master/releases/latest";
            var json = await _http.GetStringAsync(url.WithCancellation(ct));
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            var latest = root.TryGetProperty("tag_name", out var t) ? t.GetString() ?? string.Empty : string.Empty;
            var html = root.TryGetProperty("html_url", out var h) ? h.GetString() ?? string.Empty : string.Empty;
            var notes = root.TryGetProperty("body", out var b) ? b.GetString() ?? string.Empty : string.Empty;
            result.LatestVersion = latest.TrimStart('v');
            result.HtmlUrl = html;
            result.ReleaseNotes = notes;
            result.Available = Version.TryParse(latest.TrimStart('v'), out var latestV) &&
                               Version.TryParse("4.0.0", out var curV) && latestV > curV;
        }
        catch (Exception ex)
        {
            result.Error = ex.Message;
        }
        return result;
    }

    public void Dispose() => _http.Dispose();
}

internal static class UriExtensions
{
    public static Uri WithCancellation(this string url, CancellationToken ct)
    {
        // Cancellation is handled by HttpClient.Timeout; kept for API symmetry.
        _ = ct;
        return new Uri(url);
    }
}
