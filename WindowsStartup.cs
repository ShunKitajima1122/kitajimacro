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
        string? current = key?.GetValue(EntryName) as string;
        return Matches(current, LaunchCommand) || Matches(current, LegacyCommand);
    }

    public static void UpgradeLegacyRegistration()
    {
        if (!Matches(Path.GetFileName(Application.ExecutablePath), $"{Program.AppName}.exe"))
            return;
        using var key = Registry.CurrentUser.OpenSubKey(RunKey);
        if (Matches(key?.GetValue(EntryName) as string, LegacyCommand))
            SetEnabled(true);
    }

    private static string LegacyCommand => ExecutableCommand(Path.Combine(AppContext.BaseDirectory, "KeyMacro.exe"));

    private static bool Matches(string? value, string expected) =>
        string.Equals(value, expected, StringComparison.OrdinalIgnoreCase);

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
            return ExecutableCommand(executable);
        }
    }

    private static string ExecutableCommand(string executable) => $"\"{executable}\" {BackgroundArgument}";
}
