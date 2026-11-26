namespace KeyMacro;

internal sealed class MainWindow : Form
{
    private readonly Button _toggle;
    private readonly Label _state = Ui.Label("停止中", Ui.Bold);
    private readonly Label _layerState = Ui.Label("", color: Ui.Muted);
    private readonly Label _shortcutSummary = Ui.Label("", color: Ui.Muted);
    private readonly Label _notice = Ui.Label("", color: Ui.Muted);
    private readonly DataGridView _grid = Ui.Grid();
    private readonly Button _edit;
    private readonly Button _delete;
    private readonly RadioButton _normalLayer;
    private readonly RadioButton _skLayer;
    private readonly Stack<BindingEdit> _undo = new();
    private readonly Stack<BindingEdit> _redo = new();
    private MacroEngine? _engine;
    private Binding[] _bindings = [];
    private Layer _layer;
    private int _refreshPosted;

    private sealed record BindingEdit(Binding[] Before, Binding[] After, Layer Layer,
        Binding[] BeforeSelection, Binding[] AfterSelection);

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
        foreach (var size in new[] { SizeType.AutoSize, SizeType.AutoSize, SizeType.AutoSize, SizeType.Percent, SizeType.AutoSize, SizeType.AutoSize, SizeType.AutoSize })
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
            _normalLayer = LayerSelector("通常レイヤー", Layer.Normal),
            _skLayer = LayerSelector("SKレイヤー", Layer.Shift),
            Ui.Button("＋ 追加", (_, _) => EditBinding(null, false)),
            _edit = Ui.Button("編集", (_, _) => EditBinding(Selected, false)),
            _delete = Ui.Button("削除", (_, _) => DeleteBindings()),
            Ui.Button("例を追加", (_, _) => EditBinding(null, true)));
        toolbar.Margin = new Padding(0, 0, 0, 8);
        layout.Controls.Add(toolbar, 0, 2);

        _grid.MultiSelect = true;
        _grid.AddColumn("割り当て元", 27);
        _grid.AddColumn("動作", 26);
        _grid.AddColumn("内容", 47);
        _grid.SelectionChanged += (_, _) => UpdateSelection();
        _grid.CellDoubleClick += (_, e) =>
        {
            if (e.RowIndex >= 0 && _grid.Rows[e.RowIndex].Tag is Binding binding)
                EditBinding(binding, false);
        };
        _grid.Margin = Padding.Empty;
        _grid.Paint += PaintEmpty;
        layout.Controls.Add(_grid, 0, 3);
        var exchange = Ui.Row(
            Ui.Button("エクスポート", (_, _) => ExportBindings()), Ui.Button("インポート", (_, _) => ImportBindings()),
            Ui.Button("ショートカット設定", (_, _) => EditShortcuts()));
        exchange.Margin = new Padding(0, 8, 0, 0);
        layout.Controls.Add(exchange, 0, 4);
        layout.Controls.Add(_shortcutSummary, 0, 5);
        layout.ClientSizeChanged += (_, _) => _shortcutSummary.MaximumSize = new Size(
            Math.Max(1, layout.ClientSize.Width - layout.Padding.Horizontal - _shortcutSummary.Margin.Horizontal), 0);
        UpdateShortcutSummary(ShortcutKeys.Defaults);
        layout.Controls.Add(_notice, 0, 6);
        RefreshGrid();
    }

    public void Attach(MacroEngine engine)
    {
        _engine = engine;
        engine.StateChanged += RefreshStateFromHook;
        try
        {
            engine.SetShortcuts(BindingStore.LoadShortcuts());
        }
        catch (Exception ex)
        {
            ReportError("ショートカット設定の読み込みに失敗しました。 " + ex.Message);
        }
        UpdateShortcutSummary(engine.Shortcuts);
        try
        {
            _bindings = BindingStore.Load(BindingStore.PathName);
            engine.ReplaceBindings(_bindings);
            engine.Shortcuts.ValidateBindings(_bindings);
        }
        catch (Exception ex)
        {
            ReportError("設定の読み込みに失敗しました。 " + ex.Message);
        }
        RefreshGrid();
        RefreshState();
    }

    private void EditShortcuts()
    {
        if (_engine is not { } engine)
            return;
        using var dialog = new ShortcutEditor(engine, shortcuts =>
        {
            shortcuts.ValidateBindings(_bindings);
            BindingStore.SaveShortcuts(shortcuts);
            engine.SetShortcuts(shortcuts);
            UpdateShortcutSummary(shortcuts);
            _notice.Text = "ショートカット設定を保存しました";
            _notice.ForeColor = Ui.Muted;
        });
        dialog.ShowDialog(this);
    }

    private void UpdateShortcutSummary(ShortcutKeys shortcuts) =>
        _shortcutSummary.Text = $"有効・停止  {ButtonPicker.DisplayName(shortcuts.Toggle)}    シーケンス停止  {ButtonPicker.DisplayName(shortcuts.Stop)}";

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
            if (!button.Checked || _layer == layer)
                return;
            _layer = layer;
            RefreshGrid();
        };
        return button;
    }

    private Binding? Selected => _grid.SelectedRows.Count == 1 ? _grid.SelectedRows[0].Tag as Binding : null;

    private Binding[] SelectedBindings() => _grid.SelectedRows.Cast<DataGridViewRow>()
        .Select(row => row.Tag).OfType<Binding>().ToArray();

    private void RefreshGrid(Binding[]? selection = null)
    {
        _grid.Rows.Clear();
        var selectedRows = new List<DataGridViewRow>();
        foreach (var binding in _bindings.Where(item => item.Layer == _layer)
                     .OrderBy(item => item.Trigger.Device).ThenBy(item => item.Trigger.Code))
        {
            var detail = binding.Behavior switch
            {
                Behavior.Remap => ButtonPicker.DisplayName(binding.Output),
                Behavior.Shift => "押している間はSKレイヤー",
                _ => $"{binding.Steps.Length} ステップ  ·  " + (binding switch
                {
                    { Repeat: true } => "停止入力まで繰り返す",
                    { WhileHeld: true } => "押している間だけ繰り返す",
                    { RepeatCount: > 0 } => $"{binding.RepeatCount:N0}回",
                    _ => "1回"
                })
            };
            var row = _grid.Rows[_grid.Rows.Add(ButtonPicker.DisplayName(binding.Trigger),
                Ui.Behaviors.First(item => item.Value == binding.Behavior).Label, detail)];
            row.Tag = binding;
            if (selection?.Contains(binding) == true)
                selectedRows.Add(row);
        }
        if (selection is not null)
        {
            if (selectedRows.Count > 0)
                _grid.CurrentCell = selectedRows[0].Cells[0];
            _grid.ClearSelection();
            foreach (var row in selectedRows)
                row.Selected = true;
        }
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

    private void UpdateSelection()
    {
        _edit.Enabled = Selected is not null;
        _delete.Enabled = _grid.SelectedRows.Count > 0;
    }

    private void EditBinding(Binding? current, bool example)
    {
        if (_engine is null)
            return;
        using var editor = new BindingEditor(_engine, _layer, current, example);
        editor.SaveBinding = binding => Save(_bindings.Where(item => item != current).Append(binding).ToArray(), [binding]);
        editor.ShowDialog(this);
    }

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        if (keyData == Keys.Delete && _grid.ContainsFocus)
        {
            DeleteBindings();
            return true;
        }
        if (keyData == (Keys.Control | Keys.Z))
        {
            Restore(_undo, _redo, undo: true);
            return true;
        }
        if (keyData == (Keys.Control | Keys.Y))
        {
            Restore(_redo, _undo, undo: false);
            return true;
        }
        return base.ProcessCmdKey(ref msg, keyData);
    }

    private void DeleteBindings()
    {
        var selected = SelectedBindings().ToHashSet();
        if (selected.Count == 0)
            return;
        try { Save(_bindings.Where(item => !selected.Contains(item)).ToArray(), []); }
        catch (Exception ex) { ReportError(ex.Message); }
    }

    private void Save(Binding[] bindings, Binding[] selection, bool pause = false)
    {
        if (_bindings.SequenceEqual(bindings))
        {
            if (pause)
                _engine?.Pause();
            return;
        }
        var edit = new BindingEdit(_bindings, bindings, _layer, SelectedBindings(), selection);
        Apply(edit.After, edit.Layer, edit.AfterSelection, pause);
        _undo.Push(edit);
        _redo.Clear();
    }

    private void Restore(Stack<BindingEdit> from, Stack<BindingEdit> to, bool undo)
    {
        if (!from.TryPeek(out var edit))
            return;
        try
        {
            Apply(undo ? edit.Before : edit.After, edit.Layer, undo ? edit.BeforeSelection : edit.AfterSelection);
            from.Pop();
            to.Push(edit);
        }
        catch (Exception ex) { ReportError(ex.Message); }
    }

    private void Apply(Binding[] bindings, Layer layer, Binding[] selection, bool pause = false)
    {
        _engine?.Shortcuts.ValidateBindings(bindings);
        BindingStore.Save(BindingStore.PathName, bindings);
        if (pause)
            _engine?.Pause();
        _bindings = bindings;
        _engine?.ReplaceBindings(bindings);
        _layer = layer;
        (layer == Layer.Normal ? _normalLayer : _skLayer).Checked = true;
        _notice.Text = "設定を保存しました";
        _notice.ForeColor = Ui.Muted;
        RefreshGrid(selection);
    }

    private const string SettingsFilter = "Kitajimacro 設定 (*.json)|*.json";

    private void ExportBindings()
    {
        bool includeCommands = false;
        if (_bindings.Any(BindingStore.HasCommands))
        {
            var choice = MessageBox.Show(this,
                "コマンドを含む割り当ても保存しますか？ 共有用なら「いいえ」を選んでください。",
                "設定のエクスポート", MessageBoxButtons.YesNoCancel, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2);
            if (choice == DialogResult.Cancel)
                return;
            includeCommands = choice == DialogResult.Yes;
        }
        using var dialog = new SaveFileDialog
        {
            Title = "設定のエクスポート", Filter = SettingsFilter, FileName = "kitajimacro.json", OverwritePrompt = true
        };
        if (dialog.ShowDialog(this) != DialogResult.OK)
            return;
        try
        {
            BindingStore.SaveExchange(dialog.FileName, _bindings, includeCommands);
            _notice.ForeColor = Ui.Muted;
            _notice.Text = "設定をエクスポートしました";
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or InvalidDataException)
        {
            ReportError(ex.Message);
        }
    }

    private void ImportBindings()
    {
        using var dialog = new OpenFileDialog { Title = "設定のインポート", Filter = SettingsFilter };
        if (dialog.ShowDialog(this) != DialogResult.OK)
            return;
        try
        {
            var incoming = BindingStore.LoadExchange(dialog.FileName, out int excluded);
            using var review = new ImportReview(incoming, excluded);
            if (review.ShowDialog(this) != DialogResult.OK)
                return;
            var selected = review.IncludeCommands ? incoming : incoming.Where(item => !BindingStore.HasCommands(item)).ToArray();
            Save(selected, [], pause: true);
            _notice.ForeColor = Ui.Muted;
            _notice.Text = $"{selected.Length}件をインポートしました。マクロは停止中です。";
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or InvalidDataException or System.Text.Json.JsonException)
        {
            ReportError(ex.Message);
        }
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
