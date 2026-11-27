using System;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Input;
using RTXMediaMaster.Gui.ViewModels;

namespace RTXMediaMaster.Gui;

public partial class MainWindow
{
    private readonly MainViewModel _vm;

    public MainWindow(MainViewModel viewModel)
    {
        _vm = viewModel;
        DataContext = _vm;
        InitializeComponent();

        // Запуск диагностики при открытии
        _vm.Diagnostics.RefreshCommand.Execute(null);

        // Mica / Acrylic фон окна (Windows 11 22H2+). Лучшее усилие — если не применится,
        // визуальную глубину обеспечивают стеклянные карточки (#CC141820).
        _ = ApplyMica();
    }

    private bool ApplyMica()
    {
        try
        {
            var hwnd = new System.Windows.Interop.WindowInteropHelper(this).Handle;
            const int DWMWA_SYSTEMBACKDROP_TYPE = 13;
            // 2 = Mica, 3 = Acrylic, 4 = Tabbed
            int backdrop = 2;
            return DwmSetWindowAttribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE,
                ref backdrop, Marshal.SizeOf<int>()) == 0;
        }
        catch
        {
            return false;
        }
    }

    private void TitleBar_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (e.LeftButton == MouseButtonState.Pressed)
            DragMove();
    }

    private void Minimize_Click(object sender, RoutedEventArgs e) => WindowState = WindowState.Minimized;

    private void Maximize_Click(object sender, RoutedEventArgs e)
    {
        WindowState = WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized;
    }

    private void Close_Click(object sender, RoutedEventArgs e)
    {
        _vm.CancelCommand.Execute(null);
        Application.Current.Shutdown();
    }

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int dwAttribute,
        ref int pvAttribute, int cbAttribute);
}
