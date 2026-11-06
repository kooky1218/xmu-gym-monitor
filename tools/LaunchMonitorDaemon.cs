using System;
using System.Diagnostics;
using System.IO;

internal static class LaunchMonitorDaemon
{
    private static int Main()
    {
        string toolsDirectory =
            AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        string projectRoot = Directory.GetParent(toolsDirectory).FullName;
        string pythonw = Path.Combine(
            projectRoot,
            ".venv",
            "Scripts",
            "pythonw.exe"
        );
        ProcessStartInfo startInfo = new ProcessStartInfo
        {
            FileName = pythonw,
            Arguments = "app.py --daemon",
            WorkingDirectory = projectRoot,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        try
        {
            Process.Start(startInfo);
            return 0;
        }
        catch
        {
            return 5;
        }
    }
}
