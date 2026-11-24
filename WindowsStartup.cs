using Microsoft.Win32;

namespace KeyMacro;

internal static class WindowsStartup
{
    public const string BackgroundArgument = "--background";
    private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string EntryName = "KeyMacro";

    public static bool IsEnabled()
    {
        using var key = Registry.CurrentUser.OpenSubKey(RunKey);
        return string.Equals(key?.GetValue(EntryName) as string, LaunchCommand, StringComparison.OrdinalIgnoreCase);
    }

    public static void SetEnabled(bool enabled)
    {
        if (!enabled)
        {
            using var existing = Registry.CurrentUser.OpenSubKey(RunKey, writable: true);
            existing?.DeleteValue(EntryName, throwOnMissingValue: false);
            return;
        }

        string command = LaunchCommand;
        if (command.Length > 260)
            throw new InvalidOperationException("自動起動のパスが長すぎます。短いパスにアプリを移動してください。");

        using var key = Registry.CurrentUser.CreateSubKey(RunKey);
        key.SetValue(EntryName, command, RegistryValueKind.String);
    }

    private static string LaunchCommand
    {
        get
        {
            string executable = Application.ExecutablePath;
            if (string.Equals(Path.GetFileNameWithoutExtension(executable), "dotnet", StringComparison.OrdinalIgnoreCase))
                return $"\"{executable}\" \"{typeof(Program).Assembly.Location}\" {BackgroundArgument}";
            return $"\"{executable}\" {BackgroundArgument}";
        }
    }
}
