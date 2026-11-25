namespace KeyMacro;

internal sealed class ShortcutEditor : Form
{
    public ShortcutEditor(MacroEngine engine, Action<ShortcutKeys> save)
    {
        Text = "ショートカット設定";
        Font = Ui.Body;
        AutoScaleMode = AutoScaleMode.Dpi;
        StartPosition = FormStartPosition.CenterParent;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        ShowInTaskbar = false;
        MinimizeBox = false;
        MaximizeBox = false;
        ClientSize = new Size(540, 155);

        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, Padding = new Padding(14), ColumnCount = 2, RowCount = 3
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        Controls.Add(layout);

        var toggle = new ButtonPicker { Value = engine.Shortcuts.Toggle };
        var stop = new ButtonPicker { Value = engine.Shortcuts.Stop };
        layout.Controls.Add(Ui.Label("有効・停止の切り替え"), 0, 0);
        layout.Controls.Add(Ui.WithCapture(this, engine, toggle), 1, 0);
        layout.Controls.Add(Ui.Label("シーケンス停止"), 0, 1);
        layout.Controls.Add(Ui.WithCapture(this, engine, stop), 1, 1);

        var confirm = Ui.Button("保存", (_, _) =>
        {
            try
            {
                var shortcuts = new ShortcutKeys(toggle.Value, stop.Value);
                shortcuts.Validate();
                save(shortcuts);
                DialogResult = DialogResult.OK;
            }
            catch (Exception error) when (error is InvalidDataException or IOException or UnauthorizedAccessException)
            {
                MessageBox.Show(this, error.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        }, primary: true);
        var cancel = Ui.Button("キャンセル", (_, _) => DialogResult = DialogResult.Cancel);
        var reset = Ui.Button("初期値に戻す", (_, _) =>
        {
            toggle.Value = ShortcutKeys.Defaults.Toggle;
            stop.Value = ShortcutKeys.Defaults.Stop;
        });
        var footer = Ui.Row(confirm, cancel, reset);
        footer.FlowDirection = FlowDirection.RightToLeft;
        layout.Controls.Add(footer, 0, 2);
        layout.SetColumnSpan(footer, 2);
        AcceptButton = confirm;
        CancelButton = cancel;
    }
}
