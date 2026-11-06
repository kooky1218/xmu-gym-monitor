using System;
using System.Diagnostics;
using System.IO;
using System.Text;

internal static class MonitorRunOnce
{
    private static int Main()
    {
        string toolsDirectory =
            AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        string projectRoot = Directory.GetParent(toolsDirectory).FullName;
        string workDirectory = Path.Combine(projectRoot, "work");
        string python = Path.Combine(
            projectRoot,
            ".venv",
            "Scripts",
            "python.exe"
        );
        string outputPath = Path.Combine(
            workDirectory,
            "monitor_run_once.json"
        );
        string errorPath = Path.Combine(
            workDirectory,
            "monitor_run_once.err"
        );
        Directory.CreateDirectory(workDirectory);

        ProcessStartInfo startInfo = new ProcessStartInfo
        {
            FileName = python,
            Arguments = "app.py --run-once",
            WorkingDirectory = projectRoot,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        try
        {
            using (Process process = Process.Start(startInfo))
            {
                string output = process.StandardOutput.ReadToEnd();
                string error = process.StandardError.ReadToEnd();
                process.WaitForExit();
                File.WriteAllText(outputPath, output, Encoding.UTF8);
                File.WriteAllText(errorPath, error, Encoding.UTF8);
                return process.ExitCode;
            }
        }
        catch (Exception error)
        {
            File.WriteAllText(
                errorPath,
                error.GetType().Name + ": " + error.Message,
                Encoding.UTF8
            );
            return 5;
        }
    }
}
