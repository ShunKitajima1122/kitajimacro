using System.Text.Json;
using System.Text.Json.Serialization;

namespace KeyMacro;

internal enum Device { Keyboard, Mouse }
internal enum Layer { Normal, Shift }
internal enum Behavior { Remap, Sequence, Shift }
internal enum Operation { Tap, Down, Up, Hold, Wait, Text, Command }

internal readonly record struct ButtonId(Device Device, int Code)
{
    public static readonly ButtonId Escape = new(Device.Keyboard, 0x1B);
    public static readonly ButtonId Pause = new(Device.Keyboard, 0x7B);
    public static readonly ButtonId Space = new(Device.Keyboard, 0x20);
    public static readonly ButtonId WheelUp = new(Device.Mouse, 6);
    public static readonly ButtonId WheelDown = new(Device.Mouse, 7);

    [JsonIgnore]
    public bool IsWheel => this == WheelUp || this == WheelDown;

    public bool IsValid => Device switch
    {
        Device.Keyboard => (Code is >= 8 and <= 254) || Code == 0x10D,
        Device.Mouse => Code is >= 1 and <= 7,
        _ => false
    };
}

internal sealed record Step(Operation Operation, ButtonId Button, int Milliseconds, string Value)
{
    public bool UsesButton => Operation is Operation.Tap or Operation.Down or Operation.Up or Operation.Hold;
    public bool UsesTime => Operation is Operation.Wait or Operation.Hold;
    public bool UsesValue => Operation is Operation.Text or Operation.Command;
}

internal sealed record Binding(
    Layer Layer, ButtonId Trigger, Behavior Behavior, ButtonId Output, bool Repeat, Step[] Steps)
{
    public static Binding Example(Layer layer, ButtonId trigger) =>
        new(layer, trigger, Behavior.Sequence, ButtonId.Space, true,
        [
            new(Operation.Hold, new(Device.Keyboard, 'W'), 1000, ""),
            new(Operation.Tap, ButtonId.Space, 0, ""),
            new(Operation.Wait, default, 500, ""),
            new(Operation.Hold, new(Device.Keyboard, 'S'), 1000, "")
        ]);
}

internal static class BindingStore
{
    private const int MaxExchangeBytes = 4 * 1024 * 1024;
    private static readonly JsonSerializerOptions Json = new()
    {
        WriteIndented = true,
        Converters = { new JsonStringEnumConverter(allowIntegerValues: false) }
    };

    public static string PathName { get; } = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "KeyMacro", "bindings.json");

    public static Binding[] Load(string path)
    {
        if (!File.Exists(path))
            return [];
        var bindings = JsonSerializer.Deserialize<Binding[]>(File.ReadAllText(path), Json)
            ?? throw new InvalidDataException("設定の形式が不正です。");
        Validate(bindings);
        return bindings;
    }

    public static bool HasCommands(Binding binding) =>
        binding.Behavior == Behavior.Sequence && binding.Steps.Any(step => step.Operation == Operation.Command);

    public static Binding[] LoadExchange(string path, out int excluded)
    {
        using var file = File.OpenRead(path);
        if (file.Length > MaxExchangeBytes)
            throw new InvalidDataException("設定ファイルは4 MiBまで読み込めます。");
        // Read one extra byte to enforce the limit if the file is changed during the read.
        var bytes = new byte[Math.Min(file.Length + 1, MaxExchangeBytes + 1)];
        int length = file.ReadAtLeast(bytes, bytes.Length, false);
        if (length == bytes.Length || length > MaxExchangeBytes)
            throw new InvalidDataException("設定ファイルが読み込み中に変化したか、上限を超えています。");

        var json = bytes.AsMemory(0, length);
        if (json.Span.StartsWith(new byte[] { 0xEF, 0xBB, 0xBF }))
            json = json[3..];
        excluded = 0;
        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;
        var bindings = root.ValueKind == JsonValueKind.Object
            ? PortableSettings.Decode(root, out excluded)
            : root.Deserialize<Binding[]>(Json) ?? throw new InvalidDataException("設定ファイルの形式が不正です。");
        Validate(bindings);
        return bindings;
    }

    public static void SaveExchange(string path, Binding[] bindings, bool includeCommands)
    {
        if (Path.GetFullPath(path).Equals(PathName, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("設定の保存先とは別のファイルを選んでください。");
        var shared = includeCommands ? bindings : bindings.Where(item => !HasCommands(item)).ToArray();
        Validate(shared);
        var bytes = PortableSettings.Encode(shared);
        if (bytes.Length > MaxExchangeBytes)
            throw new InvalidDataException("エクスポートできる設定ファイルは4 MiBまでです。");
        SaveFile(path, bytes);
    }

    public static void Save(string path, Binding[] bindings)
    {
        Validate(bindings);
        SaveFile(path, JsonSerializer.SerializeToUtf8Bytes(bindings, Json));
    }

    private static void SaveFile(string path, byte[] contents)
    {
        var directory = Path.GetDirectoryName(path)!;
        Directory.CreateDirectory(directory);
        var temporary = Path.Combine(directory, Guid.NewGuid().ToString("N") + ".tmp");
        try
        {
            File.WriteAllBytes(temporary, contents);
            File.Move(temporary, path, overwrite: true);
        }
        finally
        {
            File.Delete(temporary);
        }
    }

    private const string ClipboardHeader = "Kitajimacro:steps:windows:v1\n";

    public static string EncodeSteps(IEnumerable<Step> steps) => ClipboardHeader + JsonSerializer.Serialize(steps, Json);

    public static Step[] DecodeSteps(string text)
    {
        string normalized = text.ReplaceLineEndings("\n");
        if (!normalized.StartsWith(ClipboardHeader, StringComparison.Ordinal))
            throw new InvalidDataException("コピーしたシーケンスのステップが見つかりません。");
        var steps = JsonSerializer.Deserialize<Step[]>(normalized.AsSpan(ClipboardHeader.Length), Json);
        if (steps is not { Length: > 0 })
            throw new InvalidDataException("貼り付けるステップがありません。");
        foreach (var step in steps)
            ValidateStep(step);
        return steps;
    }

    private static void ValidateStep(Step? step)
    {
        if (step is { UsesButton: true } && step.Button.IsWheel && step.Operation != Operation.Tap)
            throw new InvalidDataException("ホイールは「押して離す」で指定してください。");
        if (step is null || !Enum.IsDefined(step.Operation) || (step.UsesButton && !step.Button.IsValid) ||
            (step.UsesTime && step.Milliseconds is < 1 or > 3_600_000) ||
            (step.UsesValue && string.IsNullOrWhiteSpace(step.Value) &&
                (step.Operation == Operation.Command || string.IsNullOrEmpty(step.Value))))
            throw new InvalidDataException("入力・時間・文字列を確認してください。時間は1～3,600,000 msです。");
    }

    public static void Validate(Binding[] bindings)
    {
        var sources = new HashSet<(Layer, ButtonId)>();
        foreach (var binding in bindings)
        {
            if (binding is null || !Enum.IsDefined(binding.Layer) || !Enum.IsDefined(binding.Behavior) ||
                !binding.Trigger.IsValid || binding.Trigger == ButtonId.Escape || binding.Trigger == ButtonId.Pause)
                throw new InvalidDataException("割り当て元の入力が不正です。EscとF12は予約されています。");
            if (!sources.Add((binding.Layer, binding.Trigger)))
                throw new InvalidDataException("同じレイヤーに同じ入力が割り当てられています。");
            if (binding.Behavior == Behavior.Shift && binding.Trigger.IsWheel)
                throw new InvalidDataException("ホイールはSKキーに指定できません。");
            if (binding.Behavior == Behavior.Shift && binding.Layer != Layer.Normal)
                throw new InvalidDataException("SKキーは通常レイヤーで設定してください。");
            if (binding.Behavior == Behavior.Remap && !binding.Output.IsValid)
                throw new InvalidDataException("変換先の入力を選んでください。");
            if (binding.Behavior != Behavior.Sequence)
                continue;
            if (binding.Steps is not { Length: > 0 })
                throw new InvalidDataException("シーケンスにステップを追加してください。");
            var held = new HashSet<ButtonId>();
            foreach (var step in binding.Steps)
            {
                ValidateStep(step);
                if (step.Operation == Operation.Down && !held.Add(step.Button))
                    throw new InvalidDataException("同じ入力を押したまま再び押下しています。");
                if (step.Operation == Operation.Up && !held.Remove(step.Button))
                    throw new InvalidDataException("解放の前に対応する押下が必要です。");
                if (step.Operation is Operation.Tap or Operation.Hold && held.Contains(step.Button))
                    throw new InvalidDataException("押下中の入力を押して離すには、先に解放してください。");
            }
            if (held.Count > 0)
                throw new InvalidDataException("押下した入力には対応する解放を追加してください。");
        }
    }
}

internal interface IOutput
{
    void Send(ButtonId button, bool down);
    void Tap(ButtonId button, int count);
    void SendText(string value, CancellationToken cancellation);
    Task RunCommand(string command, CancellationToken cancellation);
}
