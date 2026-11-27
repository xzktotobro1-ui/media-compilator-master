using System;
using System.Collections.ObjectModel;
using System.IO;
using System.Text.RegularExpressions;
using System.Windows;

namespace RTXMediaMaster.Gui.Views;

public partial class AboutDialog
{
    public ObservableCollection<string> NoticeComponents { get; } = new();

    public AboutDialog()
    {
        InitializeComponent();
        LoadNotice();
    }

    private void Close_Click(object sender, RoutedEventArgs e) => Close();

    private async void CheckUpdates_Click(object sender, RoutedEventArgs e)
    {
        UpdateStatus.Text = "Проверка...";
        try
        {
            using var svc = new Services.UpdateService();
            var info = await svc.CheckAsync();
            UpdateStatus.Text = !string.IsNullOrEmpty(info.Error)
                ? $"Ошибка: {info.Error}"
                : info.Available
                    ? $"Доступна версия {info.LatestVersion}"
                    : "Установлена последняя версия (v3.5)";
        }
        catch (Exception ex)
        {
            UpdateStatus.Text = $"Ошибка: {ex.Message}";
        }
    }

    private void LoadNotice()
    {
        try
        {
            var repo = AppContext.BaseDirectory;
            for (int i = 0; i < 4; i++)
            {
                var candidate = Path.GetFullPath(Path.Combine(repo, @"..\..\..\..\", "NOTICE.md"));
                if (File.Exists(candidate))
                {
                    var text = File.ReadAllText(candidate);
                    foreach (var line in text.Split('\n'))
                    {
                        var m = Regex.Match(line, @"^\|\s*([^|\n]+?)\s*\|");
                        if (m.Success)
                        {
                            var name = m.Groups[1].Value.Trim();
                            if (name.Length > 0 && name != "Компонент" && name != "---")
                                NoticeComponents.Add(name);
                        }
                    }
                    break;
                }
            }
        }
        catch { /* best effort */ }
    }
}
