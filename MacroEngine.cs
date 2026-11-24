using System.Threading.Channels;

namespace KeyMacro;

internal sealed class MacroEngine : IDisposable
{
    private readonly object _routing = new();
    private readonly object _sending = new();
    private readonly IOutput _output;
    private readonly Action<string> _error;
    private readonly Channel<Action> _queue = Channel.CreateUnbounded<Action>(new UnboundedChannelOptions { SingleReader = true });
    private readonly Task _worker;
    private readonly Dictionary<ButtonId, Press> _pressed = [];
    private readonly HashSet<ButtonId> _shift = [];
    private Dictionary<(Layer, ButtonId), Binding> _bindings = [];
    private readonly Dictionary<(Layer, ButtonId), Playback> _playing = [];
    private readonly Dictionary<ButtonId, int> _held = [];
    private bool _enabled;
    private bool _closing;
    private Binding? _wheelBinding;
    private int _wheelRemainder;
    private (bool Trigger, Action<ButtonId?> Complete)? _capture;

    private readonly record struct Press(bool Block, Binding? Remap = null);
    private sealed class Playback
    {
        public readonly CancellationTokenSource Cancellation = new();
        public Task Work = Task.CompletedTask;
    }

    public MacroEngine(IOutput output, Action<string> error)
    {
        _output = output;
        _error = error;
        _worker = Task.Run(async () =>
        {
            await foreach (var action in _queue.Reader.ReadAllAsync())
            {
                try { action(); }
                catch (Exception ex) { _error(ex.Message); }
            }
        });
    }

    public event Action? StateChanged;

    public (bool Enabled, bool Shift) State
    {
        get { lock (_routing) return (_enabled, _shift.Count > 0); }
    }

    public void ReplaceBindings(Binding[] bindings)
    {
        var lookup = bindings.ToDictionary(binding => (binding.Layer, binding.Trigger));
        lock (_routing)
        {
            _bindings = lookup;
            StopLocked(includeRemaps: true);
        }
        StateChanged?.Invoke();
    }

    public void Toggle()
    {
        lock (_routing)
        {
            if (_closing)
                return;
            ToggleLocked();
        }
        StateChanged?.Invoke();
    }

    public void Pause()
    {
        lock (_routing)
        {
            if (_closing || !_enabled)
                return;
            ToggleLocked();
        }
        StateChanged?.Invoke();
    }

    private void ToggleLocked()
    {
        _enabled = !_enabled;
        if (!_enabled)
            StopLocked(includeRemaps: true);
    }

    public void BeginCapture(bool trigger, Action<ButtonId?> complete)
    {
        lock (_routing)
            _capture = (trigger, complete);
    }

    public void EndCapture(Action<ButtonId?> complete)
    {
        lock (_routing)
        {
            if (_capture?.Complete == complete)
                _capture = null;
        }
    }

    public bool Route(ButtonId button, bool down, Func<bool> editorIsActive)
    {
        lock (_routing)
        {
            if (_closing)
                return false;
            if (!down)
            {
                if (!_pressed.Remove(button, out var prior))
                    return false;
                if (_shift.Remove(button))
                    StateChanged?.Invoke();
                if (prior.Remap is { } remap)
                    Enqueue(() => ChangeOutput(remap.Output, false));
                return prior.Block;
            }

            if (_pressed.TryGetValue(button, out var press))
            {
                if (button.Device == Device.Keyboard && press.Remap?.Output is { Device: Device.Keyboard } output)
                    Enqueue(() => RepeatOutput(output));
                return press.Block;
            }

            if (TryCapture(button, editorIsActive))
            {
                _pressed[button] = new(true);
                return true;
            }

            if (button == ButtonId.Pause)
            {
                _pressed[button] = new(true);
                ToggleLocked();
                StateChanged?.Invoke();
                return true;
            }
            if (button == ButtonId.Escape)
                StopLocked(includeRemaps: false);
            if (!_enabled || !TryGetBinding(button, out var binding) || editorIsActive())
            {
                _pressed[button] = new(false);
                return false;
            }

            _pressed[button] = new(true);
            switch (binding.Behavior)
            {
                case Behavior.Shift:
                    _shift.Add(button);
                    StateChanged?.Invoke();
                    break;
                case Behavior.Remap:
                    _pressed[button] = new(true, binding);
                    Enqueue(() => ChangeOutput(binding.Output, true));
                    break;
                case Behavior.Sequence:
                    Enqueue(() => StartSequence(binding));
                    break;
            }
            return true;
        }
    }

    private bool TryCapture(ButtonId button, Func<bool> editorIsActive)
    {
        if (_capture is not { } capture || !editorIsActive())
            return false;
        if (button == ButtonId.Escape || (button.IsValid && (button.Device != Device.Keyboard || button.Code != 0xE7)
                && (!capture.Trigger || button != ButtonId.Pause)))
        {
            _capture = null;
            capture.Complete(button == ButtonId.Escape ? null : button);
        }
        return true;
    }

    public bool RouteWheel(int delta, Func<bool> editorIsActive)
    {
        if (delta == 0)
            return false;
        var direction = delta > 0 ? ButtonId.WheelUp : ButtonId.WheelDown;
        lock (_routing)
        {
            if (_closing)
                return false;
            if (TryCapture(direction, editorIsActive))
            {
                _wheelBinding = null;
                _wheelRemainder = 0;
                return true;
            }

            if (!_enabled || !TryGetBinding(direction, out var binding) || binding.Behavior == Behavior.Shift || editorIsActive())
            {
                _wheelBinding = null;
                _wheelRemainder = 0;
                return false;
            }

            if (!ReferenceEquals(_wheelBinding, binding))
            {
                _wheelBinding = binding;
                _wheelRemainder = 0;
            }
            int distance = _wheelRemainder + Math.Abs(delta);
            int count = distance / WindowsInput.WheelDelta;
            _wheelRemainder = distance % WindowsInput.WheelDelta;
            if (count > 0)
            {
                if (binding.Behavior == Behavior.Remap)
                    Enqueue(() => TapWheelTarget(binding.Output, count));
                else
                    Enqueue(() => StartSequence(binding));
            }
            return true;
        }
    }

    public void StopForEditor()
    {
        lock (_routing)
        {
            if (_closing)
                return;
            StopLocked(includeRemaps: true);
        }
        StateChanged?.Invoke();
    }

    private bool TryGetBinding(ButtonId button, out Binding binding)
    {
        if (_bindings.TryGetValue((Layer.Normal, button), out var normal) && normal.Behavior == Behavior.Shift)
        {
            binding = normal;
            return true;
        }
        return _bindings.TryGetValue((_shift.Count == 0 ? Layer.Normal : Layer.Shift, button), out binding!);
    }

    private void Enqueue(Action action) => _queue.Writer.TryWrite(action);

    private void StopLocked(bool includeRemaps)
    {
        if (includeRemaps)
        {
            foreach (var (key, press) in _pressed)
            {
                if (press.Remap is not { } remap)
                    continue;
                _pressed[key] = new(true);
                Enqueue(() => ChangeOutput(remap.Output, false));
            }
            _shift.Clear();
            _wheelBinding = null;
            _wheelRemainder = 0;
        }
        Enqueue(() =>
        {
            foreach (var playback in _playing.Values)
                playback.Cancellation.Cancel();
        });
    }

    private void TapWheelTarget(ButtonId output, int count)
    {
        lock (_sending)
        {
            if (!_held.ContainsKey(output))
                _output.Tap(output, count);
        }
    }

    private void StartSequence(Binding binding)
    {
        var key = (binding.Layer, binding.Trigger);
        if (_playing.ContainsKey(key))
            return;
        var playback = new Playback();
        _playing.Add(key, playback);
        playback.Work = Task.Run(async () =>
        {
            await RunSequence(binding, playback.Cancellation.Token);
            Enqueue(() =>
            {
                _playing.Remove(key);
                playback.Cancellation.Dispose();
            });
        });
    }

    private async Task RunSequence(Binding binding, CancellationToken cancellation)
    {
        var own = new List<ButtonId>();
        try
        {
            do
            {
                foreach (var step in binding.Steps)
                {
                    cancellation.ThrowIfCancellationRequested();
                    switch (step.Operation)
                    {
                        case Operation.Down:
                            PressOutput(step.Button, own);
                            break;
                        case Operation.Up:
                            ReleaseOutput(step.Button, own);
                            break;
                        case Operation.Tap when step.Button.IsWheel:
                            ChangeOutput(step.Button, true);
                            break;
                        case Operation.Tap:
                        case Operation.Hold:
                            PressOutput(step.Button, own);
                            await Task.Delay(step.Operation == Operation.Hold ? step.Milliseconds : 30, cancellation);
                            ReleaseOutput(step.Button, own);
                            break;
                        case Operation.Wait:
                            await Task.Delay(step.Milliseconds, cancellation);
                            break;
                        case Operation.Text:
                            lock (_sending)
                                _output.SendText(step.Value, cancellation);
                            break;
                        case Operation.Command:
                            await _output.RunCommand(step.Value, cancellation);
                            break;
                    }
                }
                if (binding.Repeat)
                    await Task.Delay(10, cancellation);
            } while (binding.Repeat);
        }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { }
        catch (Exception ex) { _error(ex.Message); }
        finally
        {
            for (var index = own.Count - 1; index >= 0; index--)
            {
                try { ChangeOutput(own[index], false); }
                catch (Exception ex) { _error(ex.Message); }
            }
        }
    }

    private void PressOutput(ButtonId button, List<ButtonId> own)
    {
        ChangeOutput(button, true);
        own.Add(button);
    }

    private void ReleaseOutput(ButtonId button, List<ButtonId> own)
    {
        own.Remove(button);
        ChangeOutput(button, false);
    }

    private void RepeatOutput(ButtonId button)
    {
        lock (_sending)
        {
            if (_held.ContainsKey(button))
                _output.Send(button, true);
        }
    }

    private void ChangeOutput(ButtonId button, bool down)
    {
        lock (_sending)
        {
            if (button.IsWheel)
            {
                if (down)
                    _output.Send(button, true);
                return;
            }
            var count = _held.GetValueOrDefault(button);
            if (down)
            {
                if (count == 0)
                    _output.Send(button, true);
                _held[button] = count + 1;
            }
            else if (count == 1)
            {
                _held.Remove(button);
                _output.Send(button, false);
            }
            else if (count > 1)
                _held[button] = count - 1;
        }
    }

    public void Dispose()
    {
        lock (_routing)
        {
            if (_closing)
                return;
            _closing = true;
            StopLocked(includeRemaps: true);
            Enqueue(() =>
            {
                Task.WhenAll(_playing.Values.Select(playback => playback.Work)).GetAwaiter().GetResult();
            });
            _queue.Writer.Complete();
        }
        _worker.GetAwaiter().GetResult();
        foreach (var playback in _playing.Values)
            playback.Cancellation.Dispose();
    }
}
