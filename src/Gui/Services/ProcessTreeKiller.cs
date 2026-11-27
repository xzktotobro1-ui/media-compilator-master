using System;
using System.Diagnostics;

namespace RTXMediaMaster.Gui.Services;

/// <summary>
/// Убивает дерево процессов (родитель + все потомки) через taskkill /T —
/// используется при отмене обработки (Kill entire process tree).
/// </summary>
public sealed class ProcessTreeKiller : IDisposable
{
    private int _mainId;
    private bool _disposed;

    public void Attach(int processId) => _mainId = processId;

    public void KillTree()
    {
        if (_mainId <= 0) return;
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "taskkill.exe",
                ArgumentList = { "/T", "/F", "/PID", _mainId.ToString() },
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };
            using var p = Process.Start(psi);
            p?.WaitForExit(5000);
        }
        catch
        {
            // best-effort
        }
    }

    public void Dispose()
    {
        if (!_disposed)
        {
            _disposed = true;
        }
    }
}
