using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Windows.Automation;

internal static class MiniProgramUiDump
{
    private static readonly StringBuilder Output = new StringBuilder();

    [STAThread]
    private static void Main()
    {
        string toolsDirectory = AppDomain.CurrentDomain.BaseDirectory;
        string projectRoot = Directory.GetParent(toolsDirectory).FullName;
        string outputPath = Path.Combine(
            projectRoot, "work", "csharp_uia_dump.txt"
        );
        Directory.CreateDirectory(Path.GetDirectoryName(outputPath));

        try
        {
            AutomationElementCollection windows =
                AutomationElement.RootElement.FindAll(
                    TreeScope.Children,
                    Condition.TrueCondition
                );
            Output.AppendLine("top_level_count=" + windows.Count);
            AutomationElement target = null;
            foreach (AutomationElement window in windows)
            {
                string name = SafeName(window);
                Output.AppendLine(
                    "TOP name=" + Escape(name) +
                    " pid=" + window.Current.ProcessId
                );
                if (name == "厦大体育")
                {
                    target = window;
                }
            }

            if (target != null)
            {
                Walk(target, 0);
            }
        }
        catch (Exception error)
        {
            Output.AppendLine(
                "ERROR " + error.GetType().Name + ": " + error.Message
            );
        }

        File.WriteAllText(outputPath, Output.ToString(), Encoding.UTF8);
    }

    private static void Walk(AutomationElement element, int depth)
    {
        string name = SafeName(element);
        if (!String.IsNullOrWhiteSpace(name))
        {
            Output.AppendLine(
                new string(' ', depth * 2) +
                element.Current.ControlType.ProgrammaticName +
                ": " + Escape(name)
            );
        }
        AutomationElement child =
            TreeWalker.ControlViewWalker.GetFirstChild(element);
        while (child != null)
        {
            Walk(child, depth + 1);
            child = TreeWalker.ControlViewWalker.GetNextSibling(child);
        }
    }

    private static string SafeName(AutomationElement element)
    {
        try
        {
            return element.Current.Name ?? "";
        }
        catch
        {
            return "";
        }
    }

    private static string Escape(string value)
    {
        return value.Replace("\r", "\\r").Replace("\n", "\\n");
    }
}
