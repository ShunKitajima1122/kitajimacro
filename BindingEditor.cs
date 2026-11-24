namespace KeyMacro;

internal sealed class BindingEditor : Form
{
    private readonly Layer _layer;
    private readonly ButtonPicker _trigger = new(trigger: true);
    private readonly ButtonPicker _output = new(trigger: false);
    private readonly ComboBox _behavior = Ui.Combo();
    private readonly Label _outputLabel = Ui.Label("変換先");
    private readonly Label _shiftHelp = Ui.Label("この入力を押している間だけSKレイヤーに切り替わります。", color: Ui.Muted);
    private readonly TableLayoutPanel _sequence = new() { Dock = DockStyle.Fill, ColumnCount = 1, Margin = Padding.Empty };
    private readonly CheckBox _repeat = new() { Text = "Escを押すまで繰り返す", AutoSize = true, Margin = new Padding(0, 8, 0, 6) };
    private readonly DataGridView _stepsGrid = Ui.Grid();
    private readonly List<Step> _steps = [];
    private readonly Button _editStep;
    private readonly Button _deleteStep;
    private readonly Button _moveUp;
    private readonly Button _moveDown;
    private readonly (string Label, Behavior Value)[] _behaviors;

    [System.ComponentModel.DesignerSerializationVisibility(System.ComponentModel.DesignerSerializationVisibility.Hidden)]
    internal Action<Binding>? SaveBinding { get; set; }

    public BindingEditor(Layer layer, Binding? existing, bool example)
    {
        _layer = layer;
        _behaviors = Ui.Behaviors.Where(item => layer == Layer.Normal || item.Value != Behavior.Shift).ToArray();
        Text = (existing is null ? "割り当ての追加" : "割り当ての編集") + (layer == Layer.Normal ? "  |  通常" : "  |  SK");
        Font = Ui.Body;
        AutoScaleMode = AutoScaleMode.Dpi;
        BackColor = Ui.Background;
        ForeColor = Ui.Ink;
        StartPosition = FormStartPosition.CenterParent;
        ClientSize = new Size(630, 495);
        MinimumSize = new Size(555, 435);
        ShowInTaskbar = false;
        MaximizeBox = false;
        MinimizeBox = false;

        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, Padding = new Padding(18, 12, 18, 12) };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 112));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        for (int i = 0; i < 3; i++)
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        Controls.Add(layout);

        layout.Controls.Add(Ui.Label("割り当て元"), 0, 0);
        layout.Controls.Add(_trigger, 1, 0);
        layout.Controls.Add(Ui.Label("動作"), 0, 1);
        layout.Controls.Add(_behavior, 1, 1);
        layout.Controls.Add(_outputLabel, 0, 2);
        layout.Controls.Add(_output, 1, 2);
        var detail = new Panel { Dock = DockStyle.Fill, Margin = Padding.Empty };
        _shiftHelp.Location = new Point(0, 10);
        detail.Controls.Add(_shiftHelp);
        layout.Controls.Add(detail, 0, 3);
        layout.SetColumnSpan(detail, 2);

        _sequence.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        _sequence.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        _sequence.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        _sequence.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        _sequence.Controls.Add(_repeat, 0, 0);
        var stepTools = Ui.Row(
            Ui.Button("ステップ追加", (_, _) => EditStep(false)),
            _editStep = Ui.Button("編集", (_, _) => EditStep(true)),
            _deleteStep = Ui.Button("削除", (_, _) => DeleteStep()),
            _moveUp = Ui.Button("上へ", (_, _) => MoveStep(-1)),
            _moveDown = Ui.Button("下へ", (_, _) => MoveStep(1)));
        stepTools.Margin = new Padding(0, 0, 0, 7);
        _sequence.Controls.Add(stepTools, 0, 1);
        _stepsGrid.AddColumn("動作", 35);
        _stepsGrid.AddColumn("設定値", 65);
        _stepsGrid.SelectionChanged += (_, _) => UpdateStepButtons();
        _stepsGrid.CellDoubleClick += (_, e) => { if (e.RowIndex >= 0) EditStep(true); };
        _sequence.Controls.Add(_stepsGrid, 0, 2);
        detail.Controls.Add(_sequence);

        var save = Ui.Button("保存", (_, _) => Save(), primary: true);
        var cancel = Ui.Button("キャンセル", (_, _) => Close());
        cancel.DialogResult = DialogResult.Cancel;
        var footer = Ui.Row(save, cancel);
        footer.FlowDirection = FlowDirection.RightToLeft;
        footer.Margin = new Padding(0, 10, 0, 0);
        layout.Controls.Add(footer, 0, 4);
        layout.SetColumnSpan(footer, 2);
        AcceptButton = save;
        CancelButton = cancel;

        _behavior.Items.AddRange(_behaviors.Select(item => item.Label).ToArray());
        var initial = example ? Binding.Example(layer, default) : existing;
        _trigger.Value = initial?.Trigger ?? default;
        _output.Value = initial?.Output ?? ButtonId.Space;
        _repeat.Checked = initial?.Repeat ?? false;
        _steps.AddRange(initial?.Steps ?? []);
        _behavior.SelectedIndexChanged += (_, _) => ChangeBehavior();
        _behavior.SelectedIndex = Array.FindIndex(_behaviors, item => item.Value == (initial?.Behavior ?? Behavior.Remap));
        RefreshSteps();
    }

    private Behavior BehaviorValue => _behaviors[_behavior.SelectedIndex].Value;

    private void ChangeBehavior()
    {
        bool remap = BehaviorValue == Behavior.Remap;
        _outputLabel.Visible = _output.Visible = remap;
        _sequence.Visible = BehaviorValue == Behavior.Sequence;
        _shiftHelp.Visible = BehaviorValue == Behavior.Shift;
    }

    private int StepIndex => _stepsGrid.CurrentRow?.Index ?? -1;

    private void UpdateStepButtons()
    {
        int index = StepIndex;
        _editStep.Enabled = _deleteStep.Enabled = index >= 0;
        _moveUp.Enabled = index > 0;
        _moveDown.Enabled = index >= 0 && index < _steps.Count - 1;
    }

    private void RefreshSteps(int selected = -1)
    {
        _stepsGrid.Rows.Clear();
        foreach (var step in _steps)
            _stepsGrid.Rows.Add(Ui.Operations.First(item => item.Value == step.Operation).Label, Ui.Describe(step));
        if (selected >= 0 && selected < _steps.Count)
            _stepsGrid.CurrentCell = _stepsGrid.Rows[selected].Cells[0];
        UpdateStepButtons();
    }

    private void EditStep(bool existing)
    {
        int index = StepIndex;
        if (existing && index < 0)
            return;
        using var editor = new StepEditor(existing ? _steps[index] : null);
        if (editor.ShowDialog(this) != DialogResult.OK)
            return;
        if (existing)
            _steps[index] = editor.Value;
        else
        {
            index = _steps.Count;
            _steps.Add(editor.Value);
        }
        RefreshSteps(index);
    }

    private void DeleteStep()
    {
        int index = StepIndex;
        if (index >= 0)
        {
            _steps.RemoveAt(index);
            RefreshSteps(Math.Min(index, _steps.Count - 1));
        }
    }

    private void MoveStep(int delta)
    {
        int index = StepIndex;
        int destination = index + delta;
        if (index < 0 || destination < 0 || destination >= _steps.Count)
            return;
        (_steps[index], _steps[destination]) = (_steps[destination], _steps[index]);
        RefreshSteps(destination);
    }

    private void Save()
    {
        try
        {
            var behavior = BehaviorValue;
            SaveBinding?.Invoke(new Binding(_layer, _trigger.Value, behavior, _output.Value,
                behavior == Behavior.Sequence && _repeat.Checked, _steps.ToArray()));
            DialogResult = DialogResult.OK;
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "保存できませんでした", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }
}

internal sealed class StepEditor : Form
{
    private readonly ComboBox _operation = Ui.Combo();
    private readonly ButtonPicker _button = new(trigger: false);
    private readonly NumericUpDown _duration = new()
    {
        Minimum = 1, Maximum = 3_600_000, Value = 500, ThousandsSeparator = true,
        Anchor = AnchorStyles.Left | AnchorStyles.Right, Margin = new Padding(0, 3, 0, 3)
    };
    private readonly TextBox _text = new()
    {
        Multiline = true, ScrollBars = ScrollBars.Vertical, Dock = DockStyle.Fill, Margin = new Padding(0, 3, 0, 3)
    };
    private readonly Label _buttonLabel = Ui.Label("入力");
    private readonly Label _durationLabel = Ui.Label("時間（ms）");
    private readonly Label _textLabel = Ui.Label("テキスト");

    internal Step Value => new(Ui.Operations[_operation.SelectedIndex].Value, _button.Value, (int)_duration.Value, _text.Text);

    public StepEditor(Step? existing)
    {
        Text = existing is null ? "ステップの追加" : "ステップの編集";
        Font = Ui.Body;
        AutoScaleMode = AutoScaleMode.Dpi;
        StartPosition = FormStartPosition.CenterParent;
        BackColor = Ui.Background;
        ForeColor = Ui.Ink;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        ShowInTaskbar = false;
        MaximizeBox = false;
        MinimizeBox = false;
        ClientSize = new Size(435, 220);

        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, Padding = new Padding(15) };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 112));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        for (int i = 0; i < 3; i++)
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        Controls.Add(layout);
        layout.Controls.Add(Ui.Label("動作"), 0, 0);
        layout.Controls.Add(_operation, 1, 0);
        layout.Controls.Add(_buttonLabel, 0, 1);
        layout.Controls.Add(_button, 1, 1);
        layout.Controls.Add(_durationLabel, 0, 2);
        layout.Controls.Add(_duration, 1, 2);
        layout.Controls.Add(_textLabel, 0, 3);
        _textLabel.Anchor = AnchorStyles.Top | AnchorStyles.Left;
        layout.Controls.Add(_text, 1, 3);

        var ok = Ui.Button("確定", (_, _) =>
        {
            if (Value.UsesValue && (Value.Operation == Operation.Command
                    ? string.IsNullOrWhiteSpace(Value.Value)
                    : string.IsNullOrEmpty(Value.Value)))
            {
                MessageBox.Show(this, "入力欄を記入してください。", Text);
                return;
            }
            DialogResult = DialogResult.OK;
        }, primary: true);
        var cancel = Ui.Button("キャンセル", (_, _) => Close());
        cancel.DialogResult = DialogResult.Cancel;
        var footer = Ui.Row(ok, cancel);
        footer.FlowDirection = FlowDirection.RightToLeft;
        footer.Margin = new Padding(0, 10, 0, 0);
        layout.Controls.Add(footer, 0, 4);
        layout.SetColumnSpan(footer, 2);
        AcceptButton = ok;
        CancelButton = cancel;

        _operation.Items.AddRange(Ui.Operations.Select(item => item.Label).ToArray());
        _button.Value = existing is { UsesButton: true } ? existing.Button : ButtonId.Space;
        _duration.Value = existing is { UsesTime: true } ? existing.Milliseconds : 500;
        _text.Text = existing?.Value ?? "";
        _operation.SelectedIndexChanged += (_, _) =>
        {
            var step = Value;
            _buttonLabel.Visible = _button.Visible = step.UsesButton;
            _durationLabel.Visible = _duration.Visible = step.UsesTime;
            _textLabel.Visible = _text.Visible = step.UsesValue;
            _textLabel.Text = step.Operation == Operation.Command ? "コマンド" : "テキスト";
        };
        _operation.SelectedIndex = Array.FindIndex(Ui.Operations, item => item.Value == (existing?.Operation ?? Operation.Tap));
    }
}
