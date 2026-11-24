namespace KeyMacro;

internal static class Ui
{
    internal static readonly Color Background = Color.FromArgb(246, 248, 252);
    internal static readonly Color Ink = Color.FromArgb(24, 34, 56);
    internal static readonly Color Muted = Color.FromArgb(78, 91, 113);
    internal static readonly Color Accent = Color.FromArgb(42, 74, 171);
    internal static readonly Font Body = new("Yu Gothic UI", 10F);
    internal static readonly Font Bold = new("Yu Gothic UI", 10F, FontStyle.Bold);
    internal static readonly Font Title = new("Yu Gothic UI", 23F, FontStyle.Bold);

    internal static Button Button(string text, EventHandler click, bool primary = false)
    {
        var button = new Button
        {
            Text = text, AutoSize = true, MinimumSize = new Size(68, 34),
            Padding = new Padding(10, 0, 10, 0), Margin = new Padding(0, 0, 8, 0),
            FlatStyle = FlatStyle.Flat, UseVisualStyleBackColor = false,
            BackColor = primary ? Accent : Color.White, ForeColor = primary ? Color.White : Ink
        };
        button.FlatAppearance.BorderColor = primary ? Accent : Color.FromArgb(205, 214, 229);
        button.Click += click;
        return button;
    }

    internal static Label Label(string text, Font? font = null, Color? color = null) => new()
    {
        Text = text, Font = font ?? Body, ForeColor = color ?? Ink,
        AutoSize = true, Margin = new Padding(0, 4, 8, 4), Anchor = AnchorStyles.Left
    };

    internal static FlowLayoutPanel Row(params Control[] children)
    {
        var row = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill, AutoSize = true, WrapContents = false, Margin = Padding.Empty
        };
        row.Controls.AddRange(children);
        return row;
    }

    internal static TableLayoutPanel WithCapture(Form owner, MacroEngine engine, ButtonPicker picker, bool trigger = false)
    {
        var row = new TableLayoutPanel
        {
            ColumnCount = 2, AutoSize = true, Anchor = AnchorStyles.Left | AnchorStyles.Right, Margin = Padding.Empty
        };
        row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        row.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        row.Controls.Add(picker, 0, 0);
        var capture = Button("入力を取得", (_, _) =>
        {
            if (CaptureInput(owner, engine, trigger) is { } result)
                picker.Value = result;
        });
        capture.Margin = new Padding(8, 0, 0, 0);
        row.Controls.Add(capture, 1, 0);
        return row;
    }

    private static ButtonId? CaptureInput(Form owner, MacroEngine engine, bool trigger)
    {
        using var prompt = new Form
        {
            Text = "入力を取得", Font = Body, ForeColor = Ink, BackColor = Background,
            StartPosition = FormStartPosition.CenterParent, FormBorderStyle = FormBorderStyle.FixedDialog,
            ControlBox = false, ShowInTaskbar = false, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink,
            Padding = new Padding(18)
        };
        prompt.Controls.Add(new Label
        {
            AutoSize = true, Dock = DockStyle.Fill, Text = "キーまたはマウスボタンを押してください。\nEscでキャンセル"
        });
        ButtonId? result = null;
        Action<ButtonId?> complete = value =>
        {
            try
            {
                prompt.BeginInvoke(() =>
                {
                    result = value;
                    prompt.DialogResult = value is null ? DialogResult.Cancel : DialogResult.OK;
                });
            }
            catch (InvalidOperationException) { }
        };
        prompt.Shown += (_, _) => engine.BeginCapture(trigger, complete);
        try
        {
            return prompt.ShowDialog(owner) == DialogResult.OK ? result : null;
        }
        finally
        {
            engine.EndCapture(complete);
        }
    }

    internal static ComboBox Combo() => new()
    {
        DropDownStyle = ComboBoxStyle.DropDownList, IntegralHeight = false, DropDownHeight = 320,
        Anchor = AnchorStyles.Left | AnchorStyles.Right, Margin = new Padding(0, 3, 0, 3)
    };

    internal static DataGridView Grid() => new()
    {
        Dock = DockStyle.Fill, BackgroundColor = Color.White, BorderStyle = BorderStyle.FixedSingle,
        AutoGenerateColumns = false, AllowUserToAddRows = false, AllowUserToDeleteRows = false,
        AllowUserToResizeRows = false, ReadOnly = true, MultiSelect = false, RowHeadersVisible = false,
        SelectionMode = DataGridViewSelectionMode.FullRowSelect,
        AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill, ColumnHeadersHeight = 36,
        RowTemplate = { Height = 33 }, GridColor = Color.FromArgb(227, 231, 241),
        EnableHeadersVisualStyles = false, ColumnHeadersBorderStyle = DataGridViewHeaderBorderStyle.Single,
        ColumnHeadersDefaultCellStyle = new DataGridViewCellStyle { BackColor = Color.FromArgb(235, 240, 249), ForeColor = Ink, Font = Bold },
        DefaultCellStyle = new DataGridViewCellStyle
        {
            BackColor = Color.White, ForeColor = Ink, SelectionBackColor = Color.FromArgb(218, 230, 255),
            SelectionForeColor = Ink, Padding = new Padding(7, 0, 5, 0)
        }
    };

    internal static void AddColumn(this DataGridView grid, string title, float weight)
    {
        grid.Columns.Add(new DataGridViewTextBoxColumn
        {
            HeaderText = title, FillWeight = weight, SortMode = DataGridViewColumnSortMode.NotSortable
        });
    }

    internal static (string Label, Behavior Value)[] Behaviors { get; } =
        [("入力の置き換え", Behavior.Remap), ("シーケンス", Behavior.Sequence), ("SKキー", Behavior.Shift)];

    internal static (string Label, Operation Value)[] Operations { get; } =
    [
        ("押して離す", Operation.Tap), ("押下", Operation.Down), ("解放", Operation.Up),
        ("長押し", Operation.Hold), ("待機", Operation.Wait), ("文字入力", Operation.Text), ("コマンド実行", Operation.Command)
    ];

    internal static string Describe(Step step)
    {
        var values = new List<string>(2);
        if (step.UsesButton)
            values.Add(ButtonPicker.DisplayName(step.Button));
        if (step.UsesTime)
            values.Add($"{step.Milliseconds:N0} ms");
        if (step.UsesValue)
            values.Add(step.Value.ReplaceLineEndings(" "));
        return string.Join("   ", values);
    }
}

internal sealed class ButtonPicker : ComboBox
{
    private sealed record Choice(ButtonId Id, string Label)
    {
        public override string ToString() => Label;
    }

    private static readonly Dictionary<int, string> CommonKeys = new()
    {
        [0x08] = "Backspace", [0x09] = "Tab", [0x0D] = "Enter", [0x10D] = "テンキー Enter",
        [0x14] = "Caps Lock", [0x1B] = "Esc", [0x20] = "Space",
        [0x21] = "Page Up", [0x22] = "Page Down", [0x25] = "←", [0x26] = "↑", [0x27] = "→", [0x28] = "↓",
        [0x2C] = "Print Screen", [0x5B] = "左 Windows", [0x5C] = "右 Windows",
        [0xA0] = "左 Shift", [0xA1] = "右 Shift", [0xA2] = "左 Ctrl", [0xA3] = "右 Ctrl",
        [0xA4] = "左 Alt", [0xA5] = "右 Alt", [0x1C] = "変換", [0x1D] = "無変換",
        [0xBA] = "OEM 1（JIS コロン / US セミコロン）", [0xBB] = "OEM Plus",
        [0xBC] = ",", [0xBD] = "-", [0xBE] = ".", [0xBF] = "/",
        [0xC0] = "OEM 3（JIS @）", [0xDB] = "OEM 4（[）",
        [0xDC] = "OEM 5（JIS ¥）", [0xDD] = "OEM 6（]）",
        [0xDE] = "OEM 7（JIS ^）", [0xE2] = "OEM 102（JIS ろ）"
    };

    public ButtonPicker(bool trigger)
    {
        DropDownStyle = ComboBoxStyle.DropDownList;
        IntegralHeight = false;
        DropDownHeight = 360;
        Anchor = AnchorStyles.Left | AnchorStyles.Right;
        Margin = new Padding(0, 3, 0, 3);
        var keys = Enumerable.Range(8, 247)
            .Where(code => code is not (0x10 or 0x11 or 0x12 or 0xE7) &&
                (CommonKeys.ContainsKey(code) || Enum.IsDefined((Keys)code)))
            .Append(0x10D)
            .Select(code => new ButtonId(Device.Keyboard, code));
        var buttons = keys.Concat(Enumerable.Range(1, 5).Select(code => new ButtonId(Device.Mouse, code)));
        Items.AddRange(buttons.Where(id => !trigger || (id != ButtonId.Escape && id != ButtonId.Pause))
            .Select(id => new Choice(id, DisplayName(id))).ToArray());
    }

    [System.ComponentModel.DesignerSerializationVisibility(System.ComponentModel.DesignerSerializationVisibility.Hidden)]
    internal ButtonId Value
    {
        get => SelectedItem is Choice choice ? choice.Id : default;
        set
        {
            for (int i = 0; i < Items.Count; i++)
            {
                if (Items[i] is Choice choice && choice.Id == value)
                {
                    SelectedIndex = i;
                    return;
                }
            }
            if (!value.IsValid)
            {
                SelectedIndex = -1;
                return;
            }
            SelectedIndex = Items.Add(new Choice(value, DisplayName(value)));
        }
    }

    internal static string DisplayName(ButtonId button)
    {
        if (button.Device == Device.Mouse)
        {
            return button.Code switch
            {
                1 => "マウス 左", 2 => "マウス 右", 3 => "マウス 中央",
                4 => "マウス X1", 5 => "マウス X2", _ => $"マウス {button.Code}"
            };
        }
        if (CommonKeys.TryGetValue(button.Code, out var label))
            return label;
        if (button.Code is >= '0' and <= '9')
            return ((char)button.Code).ToString();
        if (button.Code is >= 0x60 and <= 0x69)
            return $"テンキー {button.Code - 0x60}";
        return Enum.IsDefined((Keys)button.Code) ? ((Keys)button.Code).ToString() : $"VK 0x{button.Code:X2}";
    }
}
