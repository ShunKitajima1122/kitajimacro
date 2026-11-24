namespace KeyMacro;

internal sealed class MainWindow : Form
{
    private readonly Button _toggle;
    private readonly Label _state = Ui.Label("停止中", Ui.Bold);
    private readonly Label _layerState = Ui.Label("", color: Ui.Muted);
    private readonly Label _notice = Ui.Label("", color: Ui.Muted);
    private readonly DataGridView _grid = Ui.Grid();
    private readonly Button _edit;
    private readonly Button _delete;
    private MacroEngine? _engine;
    private Binding[] _bindings = [];
    private Layer _layer;
    private int _refreshPosted;

    public MainWindow()
    {
        Text = Program.AppName;
        Font = Ui.Body;
        AutoScaleMode = AutoScaleMode.Dpi;
        BackColor = Ui.Background;
        ForeColor = Ui.Ink;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(820, 540);
        MinimumSize = new Size(650, 410);

        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(24, 18, 24, 12), ColumnCount = 1 };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        foreach (var size in new[] { SizeType.AutoSize, SizeType.AutoSize, SizeType.AutoSize, SizeType.Percent, SizeType.AutoSize, SizeType.AutoSize })
            layout.RowStyles.Add(size == SizeType.Percent ? new RowStyle(size, 100) : new RowStyle(size));
        Controls.Add(layout);

        var header = new TableLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, ColumnCount = 2, Margin = new Padding(0, 0, 0, 13) };
        header.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        header.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        var title = new TableLayoutPanel { AutoSize = true, ColumnCount = 1, Margin = Padding.Empty };
        title.Controls.Add(Ui.Label(Program.AppName, Ui.Title));
        title.Controls.Add(Ui.Label("キーとマウスの割り当て", color: Ui.Muted));
        header.Controls.Add(title, 0, 0);
        _toggle = Ui.Button("有効にする", (_, _) => _engine?.Toggle(), primary: true);
        _toggle.Anchor = AnchorStyles.Right;
        header.Controls.Add(_toggle, 1, 0);
        layout.Controls.Add(header, 0, 0);

        var statusRow = Ui.Row(_state, _layerState);
        statusRow.Margin = new Padding(0, 0, 0, 13);
        layout.Controls.Add(statusRow, 0, 1);

        var toolbar = Ui.Row(
            LayerSelector("通常レイヤー", Layer.Normal), LayerSelector("SKレイヤー", Layer.Shift),
            Ui.Button("＋ 追加", (_, _) => EditBinding(null, false)),
            _edit = Ui.Button("編集", (_, _) => EditBinding(Selected, false)),
            _delete = Ui.Button("削除", (_, _) => DeleteBinding()),
            Ui.Button("例を追加", (_, _) => EditBinding(null, true)));
        toolbar.Margin = new Padding(0, 0, 0, 8);
        layout.Controls.Add(toolbar, 0, 2);

        _grid.AddColumn("割り当て元", 27);
        _grid.AddColumn("動作", 26);
        _grid.AddColumn("内容", 47);
        _grid.SelectionChanged += (_, _) => UpdateSelection();
        _grid.CellDoubleClick += (_, e) => { if (e.RowIndex >= 0) EditBinding(Selected, false); };
        _grid.Margin = Padding.Empty;
        _grid.Paint += PaintEmpty;
        layout.Controls.Add(_grid, 0, 3);
        layout.Controls.Add(Ui.Label("F12  有効・停止の切替      Esc  シーケンス停止", color: Ui.Muted), 0, 4);
        layout.Controls.Add(_notice, 0, 5);
        RefreshGrid();
    }

    public void Attach(MacroEngine engine)
    {
        _engine = engine;
        engine.StateChanged += RefreshStateFromHook;
        try
        {
            _bindings = BindingStore.Load(BindingStore.PathName);
            engine.ReplaceBindings(_bindings);
        }
        catch (Exception ex)
        {
            ReportError("設定の読み込みに失敗しました。 " + ex.Message);
        }
        RefreshGrid();
        RefreshState();
    }

    protected override void OnActivated(EventArgs e)
    {
        base.OnActivated(e);
        _engine?.StopForEditor();
    }

    private RadioButton LayerSelector(string text, Layer layer)
    {
        var button = new RadioButton
        {
            Text = text, Appearance = Appearance.Button, AutoSize = true, MinimumSize = new Size(110, 34),
            TextAlign = ContentAlignment.MiddleCenter, Margin = new Padding(0, 0, 8, 0),
            FlatStyle = FlatStyle.Flat, Checked = layer == Layer.Normal
        };
        button.FlatAppearance.BorderColor = Color.FromArgb(205, 214, 229);
        button.FlatAppearance.CheckedBackColor = Color.FromArgb(218, 230, 255);
        button.CheckedChanged += (_, _) =>
        {
            if (!button.Checked)
                return;
            _layer = layer;
            RefreshGrid();
        };
        return button;
    }

    private Binding? Selected => _grid.CurrentRow?.Tag as Binding;

    private void RefreshGrid(Binding? select = null)
    {
        _grid.Rows.Clear();
        DataGridViewRow? selectedRow = null;
        foreach (var binding in _bindings.Where(item => item.Layer == _layer)
                     .OrderBy(item => item.Trigger.Device).ThenBy(item => item.Trigger.Code))
        {
            var detail = binding.Behavior switch
            {
                Behavior.Remap => ButtonPicker.DisplayName(binding.Output),
                Behavior.Shift => "押している間はSKレイヤー",
                _ => $"{binding.Steps.Length} ステップ" + (binding.Repeat ? "  ·  Escまで繰り返す" : "  ·  1回")
            };
            var row = _grid.Rows[_grid.Rows.Add(ButtonPicker.DisplayName(binding.Trigger),
                Ui.Behaviors.First(item => item.Value == binding.Behavior).Label, detail)];
            row.Tag = binding;
            if (binding == select)
                selectedRow = row;
        }
        if (selectedRow is not null)
            _grid.CurrentCell = selectedRow.Cells[0];
        UpdateSelection();
        _grid.Invalidate();
    }

    private void PaintEmpty(object? sender, PaintEventArgs e)
    {
        if (_grid.RowCount != 0)
            return;
        var area = _grid.ClientRectangle;
        area.Y += _grid.ColumnHeadersHeight;
        area.Height -= _grid.ColumnHeadersHeight;
        TextRenderer.DrawText(e.Graphics, "このレイヤーには割り当てがありません", Ui.Body, area, Ui.Muted,
            TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
    }

    private void UpdateSelection() => _edit.Enabled = _delete.Enabled = Selected is not null;

    private void EditBinding(Binding? current, bool example)
    {
        using var editor = new BindingEditor(_layer, current, example);
        editor.SaveBinding = binding => Save(_bindings.Where(item => item != current).Append(binding).ToArray(), binding);
        editor.ShowDialog(this);
    }

    private void DeleteBinding()
    {
        if (Selected is not { } binding)
            return;
        try { Save(_bindings.Where(item => item != binding).ToArray(), null); }
        catch (Exception ex) { ReportError(ex.Message); }
    }

    private void Save(Binding[] bindings, Binding? select)
    {
        BindingStore.Save(BindingStore.PathName, bindings);
        _bindings = bindings;
        _engine?.ReplaceBindings(bindings);
        _notice.Text = "設定を保存しました";
        _notice.ForeColor = Ui.Muted;
        RefreshGrid(select);
    }

    private void RefreshStateFromHook()
    {
        if (!IsHandleCreated || Interlocked.Exchange(ref _refreshPosted, 1) != 0)
            return;
        try
        {
            BeginInvoke(() =>
            {
                Interlocked.Exchange(ref _refreshPosted, 0);
                RefreshState();
            });
        }
        catch (InvalidOperationException) { Interlocked.Exchange(ref _refreshPosted, 0); }
    }

    private void RefreshState()
    {
        if (_engine is null)
            return;
        var (enabled, shift) = _engine.State;
        _toggle.Text = enabled ? "停止する" : "有効にする";
        _state.Text = enabled ? "● 有効" : "○ 停止中";
        _state.ForeColor = enabled ? Color.FromArgb(0, 108, 75) : Ui.Muted;
        _layerState.Text = enabled ? (shift ? "SKレイヤーで動作中" : "設定画面の外で通常レイヤーが動作します") : "";
    }

    public void ReportError(string error)
    {
        if (InvokeRequired)
        {
            try { BeginInvoke(() => ReportError(error)); }
            catch (InvalidOperationException) { }
            return;
        }
        if (IsDisposed)
            return;
        _notice.Text = error;
        _notice.ForeColor = Color.Firebrick;
    }
}
