using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;

namespace KeyMacro;

internal sealed class WindowsInput : IOutput
{
    private static readonly UIntPtr Signature = new(0x4B4D4143u);
    private const uint KeyUp = 2;
    private const uint Unicode = 4;
    private const uint Extended = 1;
    internal const int WheelDelta = 120;

    public void Send(ButtonId button, bool down)
    {
        if (button.Device == Device.Keyboard)
        {
            var flags = down ? 0u : KeyUp;
            if (button.Code is 0x10D or 0xA3 or 0xA5 or 0x21 or 0x22 or 0x23 or 0x24 or 0x25 or 0x26
                or 0x27 or 0x28 or 0x2C or 0x2D or 0x2E or 0x5B or 0x5C or 0x5D or 0x6F or 0x90
                or (>= 0xA6 and <= 0xB7))
                flags |= Extended;
            SendBatch([Key((ushort)(button.Code & 0xFF), 0, flags)]);
            return;
        }

        if (button.IsWheel)
        {
            if (down)
            {
                uint delta = unchecked((uint)(button == ButtonId.WheelUp ? WheelDelta : -WheelDelta));
                SendBatch([Mouse(0x0800, delta)]);
            }
            return;
        }

        uint mouseFlags = button.Code switch
        {
            1 => down ? 0x0002u : 0x0004u,
            2 => down ? 0x0008u : 0x0010u,
            3 => down ? 0x0020u : 0x0040u,
            _ => down ? 0x0080u : 0x0100u
        };
        SendBatch([new Input
        {
            Type = 0,
            Data = new InputData
            {
                Mouse = new MouseInput { Flags = mouseFlags, Data = button.Code > 3 ? (uint)(button.Code - 3) : 0, Extra = Signature }
            }
        }]);
    }

    public void SendText(string value, CancellationToken cancellation)
    {
        for (int i = 0; i < value.Length;)
        {
            cancellation.ThrowIfCancellationRequested();
            int count = Math.Min(32, value.Length - i);
            if (i + count < value.Length && char.IsHighSurrogate(value[i + count - 1]))
                count--;
            var batch = new Input[count * 2];
            for (int j = 0; j < count; j++)
            {
                char character = value[i + j];
                batch[j * 2] = Key(0, character, Unicode);
                batch[j * 2 + 1] = Key(0, character, Unicode | KeyUp);
            }
            SendBatch(batch);
            i += count;
        }
    }

    public async Task RunCommand(string command, CancellationToken cancellation)
    {
        cancellation.ThrowIfCancellationRequested();
        using var process = Process.Start(new ProcessStartInfo
        {
            FileName = Path.Combine(Environment.SystemDirectory, "cmd.exe"),
            Arguments = "/d /s /c \"" + command + "\"",
            WorkingDirectory = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            UseShellExecute = false,
            CreateNoWindow = true
        }) ?? throw new InvalidOperationException("コマンドを起動できませんでした。");
        try
        {
            await process.WaitForExitAsync(cancellation);
        }
        catch (OperationCanceledException)
        {
            try { process.Kill(entireProcessTree: true); }
            catch (InvalidOperationException) { }
            throw;
        }
        if (process.ExitCode != 0)
            throw new InvalidOperationException($"コマンドが終了コード {process.ExitCode} を返しました。");
    }

    private static Input Mouse(uint flags, uint data) => new()
    {
        Type = 0,
        Data = new InputData { Mouse = new MouseInput { Flags = flags, Data = data, Extra = Signature } }
    };

    private static Input Key(ushort virtualKey, ushort scan, uint flags) => new()
    {
        Type = 1,
        Data = new InputData { Keyboard = new KeyboardInput { Key = virtualKey, Scan = scan, Flags = flags, Extra = Signature } }
    };

    private static void SendBatch(Input[] batch)
    {
        if (SendInput((uint)batch.Length, batch, Marshal.SizeOf<Input>()) != batch.Length)
            throw new InvalidOperationException("入力を送信できませんでした。操作先のウィンドウの権限を確認してください。");
    }

    internal sealed class Hook : IDisposable
    {
        private readonly MacroEngine _engine;
        private readonly int _processId = Environment.ProcessId;
        private readonly Thread _thread;
        private readonly HookProc _keyboard;
        private readonly HookProc _mouse;
        private readonly TaskCompletionSource _ready = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private uint _threadId;

        public Hook(MacroEngine engine)
        {
            _engine = engine;
            _keyboard = OnKeyboard;
            _mouse = OnMouse;
            _thread = new Thread(Listen) { IsBackground = true, Name = "Keyboard and mouse hooks" };
            _thread.Start();
            _ready.Task.GetAwaiter().GetResult();
        }

        private void Listen()
        {
            _threadId = GetCurrentThreadId();
            IntPtr module = GetModuleHandle(null);
            IntPtr keyboard = IntPtr.Zero;
            IntPtr mouse = IntPtr.Zero;
            try
            {
                PeekMessage(out _, IntPtr.Zero, 0, 0, 0);
                keyboard = SetWindowsHookEx(13, _keyboard, module, 0);
                if (keyboard == IntPtr.Zero)
                    throw new Win32Exception();
                mouse = SetWindowsHookEx(14, _mouse, module, 0);
                if (mouse == IntPtr.Zero)
                    throw new Win32Exception();
                _ready.SetResult();
                while (GetMessage(out var message, IntPtr.Zero, 0, 0) > 0)
                    DispatchMessage(ref message);
            }
            catch (Exception ex) { _ready.TrySetException(ex); }
            finally
            {
                if (mouse != IntPtr.Zero)
                    UnhookWindowsHookEx(mouse);
                if (keyboard != IntPtr.Zero)
                    UnhookWindowsHookEx(keyboard);
            }
        }

        private IntPtr OnKeyboard(int code, UIntPtr parameter, IntPtr data)
        {
            if (code == 0)
            {
                var input = Marshal.PtrToStructure<KeyboardEvent>(data);
                if (input.Extra != Signature)
                {
                    int key = (int)input.Key;
                    if (key == 0x0D && (input.Flags & 1) != 0)
                        key = 0x10D;
                    if (_engine.Route(new(Device.Keyboard, key), (input.Flags & 0x80) == 0, EditorIsActive))
                        return new IntPtr(1);
                }
            }
            return CallNextHookEx(IntPtr.Zero, code, parameter, data);
        }

        private IntPtr OnMouse(int code, UIntPtr parameter, IntPtr data)
        {
            var message = parameter.ToUInt32();
            if (code == 0 && message is 0x201 or 0x202 or 0x204 or 0x205 or 0x207 or 0x208 or 0x20A or 0x20B or 0x20C)
            {
                var input = Marshal.PtrToStructure<MouseEvent>(data);
                if (input.Extra != Signature)
                {
                    if (message == 0x20A)
                    {
                        int delta = unchecked((short)(input.Data >> 16));
                        return _engine.RouteWheel(delta, EditorIsActive)
                            ? new IntPtr(1) : CallNextHookEx(IntPtr.Zero, code, parameter, data);
                    }
                    int button = message switch
                    {
                        0x201 or 0x202 => 1,
                        0x204 or 0x205 => 2,
                        0x207 or 0x208 => 3,
                        _ => (input.Data >> 16) == 1 ? 4 : 5
                    };
                    if (_engine.Route(new(Device.Mouse, button), message is 0x201 or 0x204 or 0x207 or 0x20B, EditorIsActive))
                        return new IntPtr(1);
                }
            }
            return CallNextHookEx(IntPtr.Zero, code, parameter, data);
        }

        private bool EditorIsActive()
        {
            GetWindowThreadProcessId(GetForegroundWindow(), out uint processId);
            return processId == _processId;
        }

        public void Dispose()
        {
            PostThreadMessage(_threadId, 0x12, UIntPtr.Zero, IntPtr.Zero);
            _thread.Join();
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct Input { public uint Type; public InputData Data; }
    [StructLayout(LayoutKind.Explicit)]
    private struct InputData
    {
        [FieldOffset(0)] public MouseInput Mouse;
        [FieldOffset(0)] public KeyboardInput Keyboard;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct MouseInput { public int X, Y; public uint Data, Flags, Time; public UIntPtr Extra; }
    [StructLayout(LayoutKind.Sequential)]
    private struct KeyboardInput { public ushort Key, Scan; public uint Flags, Time; public UIntPtr Extra; }
    [StructLayout(LayoutKind.Sequential)]
    private struct KeyboardEvent { public uint Key, Scan, Flags, Time; public UIntPtr Extra; }
    [StructLayout(LayoutKind.Sequential)]
    private struct MouseEvent { public Point Location; public uint Data, Flags, Time; public UIntPtr Extra; }
    [StructLayout(LayoutKind.Sequential)]
    private struct Message
    {
        public IntPtr Window;
        public uint Id;
        public UIntPtr WParam;
        public IntPtr LParam;
        public uint Time;
        public Point Location;
        public uint Private;
    }

    private delegate IntPtr HookProc(int code, UIntPtr parameter, IntPtr data);
    [DllImport("user32.dll", SetLastError = true)] private static extern uint SendInput(uint count, Input[] inputs, int size);
    [DllImport("user32.dll", EntryPoint = "SetWindowsHookExW", SetLastError = true)] private static extern IntPtr SetWindowsHookEx(int type, HookProc proc, IntPtr module, uint thread);
    [DllImport("user32.dll")] private static extern bool UnhookWindowsHookEx(IntPtr hook);
    [DllImport("user32.dll")] private static extern IntPtr CallNextHookEx(IntPtr hook, int code, UIntPtr parameter, IntPtr data);
    [DllImport("user32.dll", EntryPoint = "PeekMessageW")] private static extern bool PeekMessage(out Message message, IntPtr window, uint min, uint max, uint remove);
    [DllImport("user32.dll", EntryPoint = "GetMessageW")] private static extern int GetMessage(out Message message, IntPtr window, uint min, uint max);
    [DllImport("user32.dll", EntryPoint = "DispatchMessageW")] private static extern IntPtr DispatchMessage(ref Message message);
    [DllImport("user32.dll", EntryPoint = "PostThreadMessageW")] private static extern bool PostThreadMessage(uint thread, uint message, UIntPtr wParam, IntPtr lParam);
    [DllImport("kernel32.dll", EntryPoint = "GetModuleHandleW", CharSet = CharSet.Unicode)] private static extern IntPtr GetModuleHandle(string? name);
    [DllImport("kernel32.dll")] private static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] private static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
}
