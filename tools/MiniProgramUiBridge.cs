using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Automation;
using System.Windows.Forms;

internal static class MiniProgramUiBridge
{
    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern bool SetCursorPos(int x, int y);

    [DllImport("user32.dll")]
    private static extern void mouse_event(
        uint flags, uint dx, uint dy, uint data, UIntPtr extraInfo
    );

    private const uint MouseLeftDown = 0x0002;
    private const uint MouseLeftUp = 0x0004;
    private static readonly StringBuilder Output = new StringBuilder();

    [STAThread]
    private static void Main()
    {
        string toolsDirectory =
            AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        string projectRoot = Directory.GetParent(toolsDirectory).FullName;
        string workDirectory = Path.Combine(projectRoot, "work");
        string commandPath = Path.Combine(workDirectory, "uia_command.txt");
        string outputPath = Path.Combine(workDirectory, "uia_bridge_output.txt");
        Directory.CreateDirectory(workDirectory);

        try
        {
            string[] command = File.Exists(commandPath)
                ? File.ReadAllLines(commandPath, Encoding.UTF8)
                : new[] { "read" };
            string action = command.Length > 0
                ? command[0].Trim().ToLowerInvariant()
                : "read";
            string targetName = command.Length > 1
                ? command[1].Trim()
                : "";
            int targetIndex = 0;
            if (command.Length > 2)
            {
                Int32.TryParse(
                    command[2].Trim(),
                    out targetIndex
                );
            }
            if (targetIndex < 0)
            {
                targetIndex = 0;
            }

            AutomationElement window = FindMiniProgramWindow();
            if (window == null)
            {
                Output.AppendLine("ERROR WINDOW_NOT_FOUND");
            }
            else
            {
                Output.AppendLine(
                    "PID " + window.Current.ProcessId.ToString()
                );
                if (action != "read")
                {
                    try
                    {
                        SetForegroundWindow(
                            new IntPtr(window.Current.NativeWindowHandle)
                        );
                    }
                    catch { }
                }

                if (action == "click" && targetName.Length > 0)
                {
                    AutomationElement target = FindByName(
                        window,
                        targetName,
                        targetIndex
                    );
                    if (target == null)
                    {
                        Output.AppendLine("ERROR CONTROL_NOT_FOUND " + targetName);
                    }
                    else
                    {
                        Click(target);
                        Output.AppendLine("CLICKED " + targetName);
                        System.Threading.Thread.Sleep(1800);
                        window = FindMiniProgramWindow() ?? window;
                    }
                }
                else if (action == "back")
                {
                    try
                    {
                        SendKeys.SendWait("%{LEFT}");
                        Output.AppendLine("BACK");
                        System.Threading.Thread.Sleep(1800);
                        window = FindMiniProgramWindow() ?? window;
                    }
                    catch (Exception error)
                    {
                        Output.AppendLine(
                            "ERROR BACK_FAILED: " + error.Message
                        );
                    }
                }

                Output.AppendLine("OK");
                Walk(window, 0);
            }
        }
        catch (Exception error)
        {
            Output.AppendLine(
                "ERROR " + error.GetType().Name + ": " + error.Message
            );
        }

        File.WriteAllText(outputPath, Output.ToString(), Encoding.UTF8);
        File.Delete(commandPath);
    }

    private static AutomationElement FindMiniProgramWindow()
    {
        AutomationElementCollection windows =
            AutomationElement.RootElement.FindAll(
                TreeScope.Children,
                Condition.TrueCondition
            );
        foreach (AutomationElement window in windows)
        {
            string name = SafeName(window);
            if (name == "厦大体育")
            {
                return window;
            }
        }
        return null;
    }

    private static AutomationElement FindByName(
        AutomationElement root,
        string name,
        int index
    )
    {
        Condition condition = new PropertyCondition(
            AutomationElement.NameProperty,
            name
        );
        AutomationElementCollection matches = root.FindAll(
            TreeScope.Descendants,
            condition
        );
        if (index < 0 || index >= matches.Count)
        {
            return null;
        }
        return matches[index];
    }

    private static void Click(AutomationElement element)
    {
        try { element.SetFocus(); } catch { }
        try
        {
            ScrollItemPattern scrollItem = element.GetCurrentPattern(
                ScrollItemPattern.Pattern
            ) as ScrollItemPattern;
            if (scrollItem != null)
            {
                scrollItem.ScrollIntoView();
                System.Threading.Thread.Sleep(400);
            }
        }
        catch { }

        try
        {
            InvokePattern invoke = element.GetCurrentPattern(
                InvokePattern.Pattern
            ) as InvokePattern;
            if (invoke != null)
            {
                invoke.Invoke();
                return;
            }
        }
        catch { }

        AutomationElement clickable = element;
        for (int level = 0; level < 4 && clickable != null; level++)
        {
            try
            {
                System.Windows.Rect rect = clickable.Current.BoundingRectangle;
                if (!clickable.Current.IsOffscreen &&
                    rect.Width > 1 && rect.Height > 1)
                {
                    int x = (int)(rect.Left + rect.Width / 2);
                    int y = (int)(rect.Top + rect.Height / 2);
                    SetCursorPos(x, y);
                    mouse_event(MouseLeftDown, 0, 0, 0, UIntPtr.Zero);
                    mouse_event(MouseLeftUp, 0, 0, 0, UIntPtr.Zero);
                    return;
                }
            }
            catch { }
            clickable = TreeWalker.ControlViewWalker.GetParent(clickable);
        }

        System.Windows.Rect rectangle = element.Current.BoundingRectangle;
        int fallbackX = (int)(rectangle.Left + rectangle.Width / 2);
        int fallbackY = (int)(rectangle.Top + rectangle.Height / 2);
        SetCursorPos(fallbackX, fallbackY);
        mouse_event(MouseLeftDown, 0, 0, 0, UIntPtr.Zero);
        mouse_event(MouseLeftUp, 0, 0, 0, UIntPtr.Zero);
    }

    private static void Walk(AutomationElement element, int depth)
    {
        string name = SafeName(element);
        if (!String.IsNullOrWhiteSpace(name))
        {
            Output.AppendLine(
                new string(' ', depth * 2) +
                element.Current.ControlType.ProgrammaticName +
                ": " + name.Replace("\r", "\\r").Replace("\n", "\\n")
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
        try { return element.Current.Name ?? ""; }
        catch { return ""; }
    }
}
