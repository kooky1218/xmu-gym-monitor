using System;
using System.Diagnostics;
using System.IO;

internal static class UiDumpLauncher
{
    [STAThread]
    private static void Main()
    {
        string toolsDirectory = AppDomain.CurrentDomain.BaseDirectory;
        string projectRoot = Directory.GetParent(toolsDirectory).FullName;
        string pythonw = Path.Combine(
            projectRoot, ".venv", "Scripts", "pythonw.exe"
        );
        string script = Path.Combine(
            projectRoot, "tools", "dump_miniprogram_ui.py"
        );
        if (!File.Exists(pythonw) || !File.Exists(script))
        {
            return;
        }
        Process.Start(new ProcessStartInfo
        {
            FileName = pythonw,
            Arguments = "\"" + script + "\"",
            WorkingDirectory = projectRoot,
            UseShellExecute = false
        });
    }
}
