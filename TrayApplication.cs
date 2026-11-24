using System.Runtime.InteropServices;

namespace KeyMacro;

internal sealed class TrayApplication : ApplicationContext
{
    private readonly MainWindow _window;
    private readonly MacroEngine _engine;
    private readonly ContextMenuStrip _menu = new();
    private readonly NotifyIcon _icon;
    private readonly ToolStripMenuItem _toggle;
    private readonly ToolStripMenuItem _startup;
    private readonly RegisteredWaitHandle _openSettings;
    private readonly RegisteredWaitHandle _exitSignal;
    private bool _exiting;
    private bool _disposed;
    private int _refreshPosted;

    public TrayApplication(MainWindow window, MacroEngine engine, WaitHandle openSettings, WaitHandle exitSignal, bool background)
    {
        _window = window;
        _engine = engine;

        _menu.Items.Add("設定を開く", null, (_, _) => ShowSettings());
        _toggle = new ToolStripMenuItem("", null, (_, _) => _engine.Toggle());
        _menu.Items.Add(_toggle);
        _startup = new ToolStripMenuItem("サインイン時に自動起動", null, (_, _) => ToggleStartup());
        _menu.Items.Add(_startup);
        _menu.Items.Add(new ToolStripSeparator());
        _menu.Items.Add("終了", null, (_, _) => Quit());
        _menu.Opening += (_, _) => RefreshStartup();

        _icon = new NotifyIcon { Icon = SystemIcons.Application, ContextMenuStrip = _menu };
        _icon.MouseDoubleClick += (_, e) =>
        {
            if (e.Button == MouseButtons.Left)
                ShowSettings();
        };

        _window.FormClosing += OnWindowClosing;
        _window.FormClosed += (_, _) => ExitThread();
        _window.Resize += (_, _) =>
        {
            if (_window.WindowState == FormWindowState.Minimized)
                _window.Hide();
        };
        _ = _window.Handle;
        _window.Attach(_engine);
        _engine.StateChanged += PostState;
        if (background)
            _engine.Toggle();
        else
            ShowSettings();

        RefreshState();
        _icon.Visible = true;
        _openSettings = ThreadPool.RegisterWaitForSingleObject(openSettings, (_, _) => Post(ShowSettings),
            null, Timeout.Infinite, executeOnlyOnce: false);
        _exitSignal = ThreadPool.RegisterWaitForSingleObject(exitSignal, (_, _) => Post(Quit),
            null, Timeout.Infinite, executeOnlyOnce: true);
    }

    private void OnWindowClosing(object? sender, FormClosingEventArgs e)
    {
        if (_exiting || e.CloseReason != CloseReason.UserClosing)
            return;
        e.Cancel = true;
        _window.Hide();
    }

    private void ShowSettings()
    {
        if (_exiting)
            return;
        _window.Show();
        if (_window.WindowState == FormWindowState.Minimized)
            _window.WindowState = FormWindowState.Normal;
        // A launcher can override the first ShowWindow call with SW_HIDE.
        if (!IsWindowVisible(_window.Handle))
            ShowWindow(_window.Handle, 5);
        _window.Activate();
    }

    private void Post(Action action)
    {
        try { _window.BeginInvoke(action); }
        catch (InvalidOperationException) { }
    }

    private void PostState()
    {
        if (Interlocked.Exchange(ref _refreshPosted, 1) != 0)
            return;
        Post(() =>
        {
            Interlocked.Exchange(ref _refreshPosted, 0);
            RefreshState();
        });
    }

    private void RefreshState()
    {
        bool enabled = _engine.State.Enabled;
        _toggle.Text = enabled ? "マクロを停止" : "マクロを有効にする";
        _icon.Text = enabled ? "KeyMacro | 有効" : "KeyMacro | 停止中";
    }

    private void RefreshStartup()
    {
        try
        {
            _startup.Checked = WindowsStartup.IsEnabled();
            _startup.Enabled = true;
        }
        catch (Exception ex)
        {
            _startup.Enabled = false;
            _window.ReportError("自動起動の設定を読み込めませんでした。 " + ex.Message);
        }
    }

    private void ToggleStartup()
    {
        try
        {
            WindowsStartup.SetEnabled(!WindowsStartup.IsEnabled());
            RefreshStartup();
        }
        catch (Exception ex)
        {
            ShowSettings();
            _window.ReportError("自動起動を設定できませんでした。 " + ex.Message);
        }
    }

    private void Quit()
    {
        _exiting = true;
        _window.Close();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing && !_disposed)
        {
            _disposed = true;
            _exiting = true;
            _openSettings.Unregister(null);
            _exitSignal.Unregister(null);
            _engine.StateChanged -= PostState;
            _icon.Dispose();
            _menu.Dispose();
        }
        base.Dispose(disposing);
    }

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr window);

    [DllImport("user32.dll")]
    private static extern bool ShowWindow(IntPtr window, int command);
}
