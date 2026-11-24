using System.ComponentModel;

namespace KeyMacro;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        using var instance = new Mutex(true, @"Local\KeyMacro.App", out bool first);
        if (!first)
        {
            MessageBox.Show("KeyMacro はすでに起動しています。", "KeyMacro");
            return;
        }

        using var window = new MainWindow();
        using var engine = new MacroEngine(new WindowsInput(), window.ReportError);
        try
        {
            using var hook = new WindowsInput.Hook(engine);
            window.Attach(engine);
            Application.Run(window);
        }
        catch (Win32Exception ex)
        {
            MessageBox.Show("キー・マウスの監視を開始できませんでした。\n" + ex.Message, "KeyMacro",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
