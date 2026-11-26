using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace KeyMacro;

internal sealed class SequenceDelay : IDisposable
{
    private const uint HighResolution = 0x2;
    private const uint SynchronizeAndModify = 0x00100002;
    private WaitHandle? _timer;
    private bool _initialized;

    private sealed class TimerWaitHandle : WaitHandle
    {
        public TimerWaitHandle(SafeWaitHandle handle) => SafeWaitHandle = handle;
    }

    public async Task WaitAsync(int milliseconds, CancellationToken cancellation)
    {
        cancellation.ThrowIfCancellationRequested();
        if (!_initialized)
        {
            _initialized = true;
            var handle = CreateWaitableTimerExW(IntPtr.Zero, null, HighResolution, SynchronizeAndModify);
            if (handle.IsInvalid)
                handle.Dispose();
            else
                _timer = new TimerWaitHandle(handle);
        }

        long dueTime = -milliseconds * (long)TimeSpan.TicksPerMillisecond;
        if (_timer is null || !SetWaitableTimer(_timer.SafeWaitHandle, in dueTime, 0, IntPtr.Zero, IntPtr.Zero, false))
        {
            await Task.Delay(milliseconds, cancellation).ConfigureAwait(false);
            return;
        }

        var completion = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var wait = ThreadPool.RegisterWaitForSingleObject(_timer, static (state, _) =>
            ((TaskCompletionSource)state!).TrySetResult(), completion, Timeout.Infinite, executeOnlyOnce: true);
        try
        {
            using var registration = cancellation.Register(() => completion.TrySetCanceled(cancellation));
            await completion.Task.ConfigureAwait(false);
        }
        finally
        {
            wait.Unregister(null);
        }
    }

    public void Dispose() => _timer?.Dispose();

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
    private static extern SafeWaitHandle CreateWaitableTimerExW(IntPtr attributes, string? name, uint flags, uint access);

    [DllImport("kernel32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetWaitableTimer(SafeWaitHandle timer, in long dueTime, int period,
        IntPtr callback, IntPtr argument, [MarshalAs(UnmanagedType.Bool)] bool resume);
}
