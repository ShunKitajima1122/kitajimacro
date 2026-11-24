using System.ComponentModel;

namespace KeyMacro;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        bool background = args.Contains(WindowsStartup.BackgroundArgument, StringComparer.OrdinalIgnoreCase);
        bool requestExit = args.Contains("--exit", StringComparer.OrdinalIgnoreCase);
        using var exitSignal = new EventWaitHandle(false, EventResetMode.AutoReset, @"Local\KeyMacro.Exit");
        using var openSettings = new EventWaitHandle(false, EventResetMode.AutoReset, @"Local\KeyMacro.OpenSettings");
        using var instance = new Mutex(false, @"Local\KeyMacro.App", out bool first);
        if (requestExit)
        {
            if (!first)
                exitSignal.Set();
            return;
        }

        if (!first)
        {
            if (!background)
                openSettings.Set();
            return;
        }

        ApplicationConfiguration.Initialize();
        using var window = new MainWindow();
        using var engine = new MacroEngine(new WindowsInput(), window.ReportError);
        try
        {
            using var hook = new WindowsInput.Hook(engine);
            using var tray = new TrayApplication(window, engine, openSettings, exitSignal, background);
            Application.Run(tray);
        }
        catch (Win32Exception ex)
        {
            MessageBox.Show("キー・マウスの監視を開始できませんでした。\n" + ex.Message, "KeyMacro",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
