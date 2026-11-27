using System;
using System.Collections.ObjectModel;
using System.IO;
using System.Text.Json;
using System.Windows;
using RTXMediaMaster.Gui.ViewModels;

namespace RTXMediaMaster.Gui.Views;

public partial class PresetManagerDialog : Window
{
    private readonly string _presetsDir;
    public ObservableCollection<string> Presets { get; } = new();

    public PresetManagerDialog()
    {
        InitializeComponent();
        var settingsDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "RTX Media Master");
        _presetsDir = Path.Combine(settingsDir, "presets");
        Directory.CreateDirectory(_presetsDir);
        PresetsList.ItemsSource = Presets;
        Reload();
    }

    private void Reload()
    {
        Presets.Clear();
        try
        {
            foreach (var f in Directory.GetFiles(_presetsDir, "*.json"))
                Presets.Add(Path.GetFileNameWithoutExtension(f));
        }
        catch { }
    }

    private QueueSettings? ReadCurrent()
    {
        var main = Application.Current.MainWindow;
        if (main?.DataContext is MainViewModel vm)
        {
            var q = vm.Queue;
            return new QueueSettings
            {
                TargetFps = q.TargetFps, Preset = q.Preset, Codec = q.Codec,
                Enhance = q.Enhance, Scale = string.Empty, AfterCompletion = q.AfterCompletion
            };
        }
        return null;
    }

    private void Apply(QueueSettings s)
    {
        var main = Application.Current.MainWindow;
        if (main?.DataContext is MainViewModel vm)
        {
            var q = vm.Queue;
            q.ApplyPreset(s.TargetFps, s.Preset, s.Codec, s.Enhance, s.AfterCompletion);
        }
    }

    private void Save_Click(object sender, RoutedEventArgs e)
    {
        var name = PresetName.Text.Trim();
        if (string.IsNullOrEmpty(name)) return;
        var s = ReadCurrent();
        if (s == null) return;
        try
        {
            var path = Path.Combine(_presetsDir, name + ".json");
            File.WriteAllText(path, JsonSerializer.Serialize(s, new JsonSerializerOptions { WriteIndented = true }));
            if (!Presets.Contains(name)) Presets.Add(name);
            PresetsList.SelectedItem = name;
        }
        catch { }
    }

    private void Load_Click(object sender, RoutedEventArgs e)
    {
        if (PresetsList.SelectedItem is not string name) return;
        try
        {
            var path = Path.Combine(_presetsDir, name + ".json");
            var json = File.ReadAllText(path);
            var s = JsonSerializer.Deserialize<QueueSettings>(json);
            if (s != null) Apply(s);
        }
        catch { }
    }

    private void Delete_Click(object sender, RoutedEventArgs e)
    {
        if (PresetsList.SelectedItem is not string name) return;
        try
        {
            File.Delete(Path.Combine(_presetsDir, name + ".json"));
            Presets.Remove(name);
        }
        catch { }
    }

    private void Close_Click(object sender, RoutedEventArgs e) => Close();
}

public class QueueSettings
{
    public string TargetFps { get; set; } = "120";
    public string Preset { get; set; } = "balanced";
    public string Codec { get; set; } = "auto";
    public bool Enhance { get; set; } = true;
    public string Scale { get; set; } = string.Empty;
    public string AfterCompletion { get; set; } = "none";
}
