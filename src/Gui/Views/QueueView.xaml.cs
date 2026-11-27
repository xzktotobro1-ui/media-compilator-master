using System;
using System.Linq;
using System.Windows;
using RTXMediaMaster.Gui.ViewModels;

namespace RTXMediaMaster.Gui.Views;

public partial class QueueView
{
    public QueueView()
    {
        InitializeComponent();
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.Effects = e.Data.GetDataPresent(DataFormats.FileDrop)
            ? DragDropEffects.Copy : DragDropEffects.None;
        e.Handled = true;
    }

    private void DropZone_DragEnter(object sender, DragEventArgs e)
    {
        if (e.Data.GetDataPresent(DataFormats.FileDrop))
            HeroDropZone.BorderBrush = new System.Windows.Media.SolidColorBrush(
                (System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString("#00D2FF")!);
        HeroDropZone.BorderThickness = new Thickness(2);
    }

    private void DropZone_DragLeave(object sender, DragEventArgs e)
    {
        HeroDropZone.BorderBrush = null;
        HeroDropZone.BorderThickness = new Thickness(0);
    }

    private void DropZone_Drop(object sender, DragEventArgs e)
    {
        HeroDropZone.BorderBrush = null;
        HeroDropZone.BorderThickness = new Thickness(0);
        if (DataContext is not QueueViewModel vm) return;
        if (!e.Data.GetDataPresent(DataFormats.FileDrop)) return;

        var files = (string[])e.Data.GetData(DataFormats.FileDrop);
        var exts = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
            { ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts" };

        foreach (var path in files)
        {
            if (System.IO.Directory.Exists(path))
            {
                foreach (var f in System.IO.Directory.GetFiles(path, "*.*", System.IO.SearchOption.AllDirectories)
                             .Where(p => exts.Contains(System.IO.Path.GetExtension(p))))
                    vm.AddItem(f);
            }
            else if (System.IO.File.Exists(path) && exts.Contains(System.IO.Path.GetExtension(path)))
            {
                vm.AddItem(path);
            }
        }
        e.Handled = true;
    }
}
