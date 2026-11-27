using System;
using System.Diagnostics;
using System.Runtime.InteropServices;

namespace RTXMediaMaster.Gui.Services;

public sealed class NotificationService
{
    public void Show(string title, string body)
    {
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "powershell.exe",
                ArgumentList =
                {
                    "-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass",
                    "-Command",
                    $"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;" +
                    $"$template = @'<toast><visual><binding template=\"ToastGeneric\"><text>{System.Security.SecurityElement.Escape(title)}</text><text>{System.Security.SecurityElement.Escape(body)}</text></binding></visual></toast>';" +
                    "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument; $xml.LoadXml($template);" +
                    "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml);" +
                    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastListener('RTX Media Master').Show($toast);"
                },
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };
            using var p = Process.Start(psi);
            _ = p?.WaitForExit(3000);
        }
        catch
        {
            // notifications are best-effort
        }
    }

    public void Sleep()
    {
        Run("rundll32.exe powrprof.dll,SetSuspendState 0,1,0");
    }

    public void Shutdown()
    {
        Run("shutdown.exe /s /t 60 /c \"RTX Media Master: обработка завершена. ПК выключится через 60 сек.\"");
    }

    public void CancelShutdown()
    {
        Run("shutdown.exe /a");
    }

    private static void Run(string command)
    {
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "cmd.exe",
                ArgumentList = { "/c", command },
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
            };
            using var _ = Process.Start(psi);
        }
        catch { /* best-effort */ }
    }
}
