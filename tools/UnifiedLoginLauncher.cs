using System;
using System.Diagnostics;
using System.IO;

internal static class UnifiedLoginLauncher
{
    [STAThread]
    private static void Main()
    {
        string toolsDirectory = AppDomain.CurrentDomain.BaseDirectory;
        string projectRoot = Directory.GetParent(toolsDirectory).FullName;
        string pythonw = Path.Combine(
            projectRoot, ".venv", "Scripts", "pythonw.exe"
        );
        string app = Path.Combine(projectRoot, "app.py");

        if (!File.Exists(pythonw) || !File.Exists(app))
        {
            return;
        }

        ProcessStartInfo startInfo = new ProcessStartInfo
        {
            FileName = pythonw,
            Arguments = "\"" + app + "\" --unified-login",
            WorkingDirectory = projectRoot,
            UseShellExecute = false
        };
        Process.Start(startInfo);
    }
}
