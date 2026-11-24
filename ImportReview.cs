using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace KeyMacro;

internal sealed class ImportReview : Form
{
    private readonly CheckBox _includeCommands = new()
    {
        Text = "内容を確認し、コマンドを含む割り当ても取り込む", AutoSize = true
    };

    public bool IncludeCommands => _includeCommands.Checked;

    public ImportReview(Binding[] bindings)
    {
        var commands = bindings.Where(BindingStore.HasCommands).ToArray();
        Text = "設定のインポート";
        Font = Ui.Body;
        StartPosition = FormStartPosition.CenterParent;
        ShowInTaskbar = false;
        MinimizeBox = false;
        MaximizeBox = false;
        ClientSize = new Size(610, commands.Length == 0 ? 160 : 425);
        MinimumSize = new Size(500, commands.Length == 0 ? 190 : 350);

        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, Padding = new Padding(14) };
        Controls.Add(layout);
        int row = 0;
        var summary = Ui.Label("現在の通常・SKレイヤーの割り当てを入れ替えます。");
        layout.Controls.Add(summary, 0, row++);
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        var count = Ui.Label("");
        layout.Controls.Add(count, 0, row++);
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        if (commands.Length != 0)
        {
            var json = new JsonSerializerOptions { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };
            var preview = new TextBox
            {
                ReadOnly = true, Multiline = true, ScrollBars = ScrollBars.Vertical, Dock = DockStyle.Fill,
                Text = string.Join(Environment.NewLine + Environment.NewLine, commands.Select(binding =>
                {
                    string layer = binding.Layer == Layer.Normal ? "通常" : "SK";
                    var steps = binding.Steps.Select((step, index) => (step, index))
                        .Where(item => item.step.Operation == Operation.Command)
                        .Select(item => $"{item.index + 1}. {JsonSerializer.Serialize(VisibleCommand(item.step.Value), json)}");
                    return $"{layer}  {ButtonPicker.DisplayName(binding.Trigger)}" + Environment.NewLine
                        + string.Join(Environment.NewLine, steps);
                }))
            };
            layout.Controls.Add(preview, 0, row++);
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            layout.Controls.Add(_includeCommands, 0, row++);
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.Controls.Add(Ui.Label("コマンドは、取り込み後に対応するマクロを実行すると動きます。"), 0, row++);
        }

        var accept = Ui.Button("インポート", (_, _) => DialogResult = DialogResult.OK, primary: true);
        var cancel = Ui.Button("キャンセル", (_, _) => DialogResult = DialogResult.Cancel);
        var footer = Ui.Row(accept, cancel);
        footer.FlowDirection = FlowDirection.RightToLeft;
        layout.Controls.Add(footer, 0, row);
        CancelButton = cancel;

        void UpdateCount()
        {
            int omitted = IncludeCommands ? 0 : commands.Length;
            int accepted = bindings.Length - omitted;
            count.Text = $"{accepted}件を取り込みます"
                + (omitted > 0 ? $"（コマンドを含む{omitted}件は除外）" : "。");
            accept.Enabled = accepted > 0 || bindings.Length == 0;
        }

        _includeCommands.CheckedChanged += (_, _) => UpdateCount();
        UpdateCount();
    }

    private static string VisibleCommand(string value) =>
        Regex.Replace(value, @"[\p{Cf}\p{Zl}\p{Zp}]", match => $"\\u{(int)match.Value[0]:X4}");
}
