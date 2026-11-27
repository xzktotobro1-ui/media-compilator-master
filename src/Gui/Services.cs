using System;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;
using RTXMediaMaster.Gui.Models;

namespace RTXMediaMaster.Gui.Services;

public sealed class SettingsService
{
    private static readonly JsonSerializerOptions Options = new()
    {
        WriteIndented = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    private readonly string _filePath;

    public SettingsService(string? appDataDir = null)
    {
        var baseDir = appDataDir ??
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "RTX Media Master");
        Directory.CreateDirectory(baseDir);
        _filePath = Path.Combine(baseDir, "settings.json");
    }

    public Settings Load()
    {
        if (!File.Exists(_filePath))
            return new Settings();
        try
        {
            var json = File.ReadAllText(_filePath);
            var s = JsonSerializer.Deserialize<Settings>(json, Options) ?? new Settings();
            return s;
        }
        catch
        {
            return new Settings();
        }
    }

    public void Save(Settings settings)
    {
        var json = JsonSerializer.Serialize(settings, Options);
        File.WriteAllText(_filePath, json);
    }

    public string FilePath => _filePath;
    public string AppDataDir => Path.GetDirectoryName(_filePath) ?? string.Empty;
}
