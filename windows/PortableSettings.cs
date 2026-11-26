using System.Text.Json;
using System.Text.Json.Serialization;

namespace KeyMacro;

internal static class PortableSettings
{
    private const string Format = "kitajimacro";
    private const int LegacyVersion = 1;
    private const int RepeatModesVersion = 2;
    private const string NativeShell = "cmd";
    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        Converters = { new JsonStringEnumConverter(allowIntegerValues: false) }
    };
    private static readonly string[] Mouse = ["mouse.left", "mouse.right", "mouse.middle", "mouse.side",
        "mouse.extra", "mouse.wheel-up", "mouse.wheel-down"];
    private static readonly Dictionary<int, string> Keys = LoadKeys();
    private static readonly Dictionary<string, int> KeyCodes = Keys.ToDictionary(item => "key." + item.Value, item => item.Key);

    private sealed record Exchange(string Format, int Version, PortableBinding[] Bindings);
    private sealed record PortableBinding(Layer Layer, string Trigger, Behavior Behavior, string? Output, bool Repeat,
        PortableStep[] Steps,
        [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingDefault)] int RepeatCount = 0,
        [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingDefault)] bool WhileHeld = false);
    private sealed record PortableStep(Operation Operation, string? Button, int Milliseconds, string? Value, string? Shell);

    private static Dictionary<int, string> LoadKeys()
    {
        using var resource = typeof(PortableSettings).Assembly.GetManifestResourceStream("KeyMacro.PortableKeys.json")
            ?? throw new InvalidOperationException("共通キー定義が見つかりません。");
        return JsonSerializer.Deserialize<Dictionary<int, string>>(resource)
            ?? throw new InvalidOperationException("共通キー定義を読み込めません。");
    }

    public static byte[] Encode(Binding[] bindings) =>
        JsonSerializer.SerializeToUtf8Bytes(new Exchange(Format,
            bindings.Any(binding => binding.RepeatCount > 0 || binding.WhileHeld) ? RepeatModesVersion : LegacyVersion,
            bindings.Select(EncodeBinding).ToArray()), Json);

    private static PortableBinding EncodeBinding(Binding binding) => new(
        binding.Layer, EncodeButton(binding.Trigger), binding.Behavior,
        binding.Behavior == Behavior.Remap ? EncodeButton(binding.Output) : null, binding.Repeat,
        binding.Behavior == Behavior.Sequence ? binding.Steps.Select(step => new PortableStep(step.Operation,
            step.UsesButton ? EncodeButton(step.Button) : null, step.Milliseconds, step.UsesValue ? step.Value : null,
            step.Operation == Operation.Command ? NativeShell : null)).ToArray() : [],
        binding.RepeatCount, binding.WhileHeld);

    public static Binding[] Decode(JsonElement json, out int excluded)
    {
        var exchange = json.Deserialize<Exchange>(Json);
        if (exchange is null || exchange.Format != Format || exchange.Version is not (LegacyVersion or RepeatModesVersion) || exchange.Bindings is null)
            throw new InvalidDataException("対応しているKitajimacro共有形式ではありません。");

        excluded = 0;
        var bindings = new List<Binding>();
        foreach (var binding in exchange.Bindings)
        {
            if (binding is null || binding.Steps is null || binding.Steps.Any(step => step is null))
                throw new InvalidDataException("割り当ての形式が不正です。");
            if (exchange.Version == LegacyVersion && (binding.RepeatCount != 0 || binding.WhileHeld))
                throw new InvalidDataException("この実行モードには新しい共有形式が必要です。");
            var commands = binding.Steps.Where(step => step.Operation == Operation.Command).ToArray();
            if (commands.Any(step => step.Shell is not ("cmd" or "sh")))
                throw new InvalidDataException("コマンドの実行環境が不正です。");
            if (commands.Any(step => step.Shell != NativeShell))
            {
                excluded++;
                continue;
            }
            bindings.Add(new Binding(binding.Layer, DecodeButton(binding.Trigger), binding.Behavior,
                binding.Behavior == Behavior.Remap ? DecodeButton(binding.Output) : default, binding.Repeat,
                binding.Behavior == Behavior.Sequence ? binding.Steps.Select(step => new Step(step.Operation,
                    step.Operation is Operation.Tap or Operation.Down or Operation.Up or Operation.Hold
                        ? DecodeButton(step.Button) : default, step.Milliseconds, step.Value ?? "")).ToArray() : [], binding.RepeatCount, binding.WhileHeld));
        }
        return bindings.ToArray();
    }

    private static string EncodeButton(ButtonId button)
    {
        if (button.Device == Device.Mouse && button.Code >= 1 && button.Code <= Mouse.Length)
            return Mouse[button.Code - 1];
        if (button.Device == Device.Keyboard && Keys.TryGetValue(button.Code, out var name))
            return "key." + name;
        throw new InvalidDataException($"「{ButtonPicker.DisplayName(button)}」を共有形式へ変換できません。");
    }

    private static ButtonId DecodeButton(string? token)
    {
        int mouse = Array.IndexOf(Mouse, token);
        if (mouse >= 0)
            return new(Device.Mouse, mouse + 1);
        if (token is not null && KeyCodes.TryGetValue(token, out int key))
            return new(Device.Keyboard, key);
        throw new InvalidDataException($"「{token}」はWindows版で取り込めません。");
    }
}
