using System;
using System.Windows;

namespace RTXMediaMaster.Gui.Views;

public partial class CompareDialog : Window
{
    private readonly string _before;
    private readonly string _after;

    public CompareDialog(string before, string after)
    {
        InitializeComponent();
        _before = before;
        _after = after;
        BeforePlayer.Source = new Uri(before);
        AfterPlayer.Source = new Uri(after);
        Loaded += (s, e) => Play_Click(this, new RoutedEventArgs());
    }

    private void Play_Click(object sender, RoutedEventArgs e)
    {
        BeforePlayer.Position = TimeSpan.Zero;
        AfterPlayer.Position = TimeSpan.Zero;
        BeforePlayer.Play();
        AfterPlayer.Play();
    }

    private void Close_Click(object sender, RoutedEventArgs e)
    {
        BeforePlayer.Stop();
        AfterPlayer.Stop();
        Close();
    }
}
