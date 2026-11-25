"""GTK settings and sequence editors."""

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from evdev.ecodes import ecodes
from gi.repository import Gdk, Gtk, Pango

from linux_input import BUTTON_CODES, MOUSE_CODES, button_label
from model import (BUTTON_ACTIONS, ESC, F12, NORMAL, SHIFT, TIME_ACTIONS, VALUE_ACTIONS,
                   WHEEL_CODES, WHEEL_DOWN, WHEEL_UP, Binding, Step, decode_steps, encode_steps, example, has_commands)

OPERATIONS = {"Tap": "押して離す", "Down": "押下", "Up": "解放", "Hold": "長押し",
              "Wait": "待機", "Text": "文字入力", "Command": "コマンド実行"}
BEHAVIORS = {"Remap": "入力の置き換え", "Sequence": "シーケンス", "Shift": "SKキー"}
BUTTONS = sorted(BUTTON_CODES, key=lambda code: (code in MOUSE_CODES or code in WHEEL_CODES, button_label(code).casefold()))


def button(text, action):
    control = Gtk.Button(label=text)
    control.connect("clicked", lambda *_: action())
    return control


def label(text):
    return Gtk.Label(label=text, xalign=0)


def combo(options, selected=None):
    control = Gtk.ComboBoxText()
    for key, text in options:
        control.append(str(key), text)
    if selected is not None and not control.set_active_id(str(selected)):
        control.set_active(0)
    return control


def picker(parent, selected=0, trigger=False):
    allowed = BUTTON_CODES - {ESC, F12} if trigger else BUTTON_CODES
    choices = combo(((code, button_label(code)) for code in BUTTONS if code in allowed), selected or None)
    field = Gtk.Box(spacing=8)
    field.pack_start(choices, True, True, 0)
    field.add(button("入力を取得", lambda: capture_input(parent, choices, allowed)))
    return field, choices


def capture_input(parent, choices, allowed):
    prompt = Gtk.Dialog(title="入力を取得", transient_for=parent, modal=True, destroy_with_parent=True)
    app = parent.get_application()
    prompt.set_application(app)
    prompt.connect("notify::is-active", app.on_editor_focus)
    content = Gtk.EventBox()
    content.set_border_width(20)
    content.add(label("キーを押すか、この領域でマウスボタン・ホイールを操作してください。\nEscでキャンセル"))
    prompt.get_content_area().add(content)

    def complete(code):
        if code is not None:
            choices.set_active_id(str(code))
        prompt.response(Gtk.ResponseType.OK if code is not None else Gtk.ResponseType.CANCEL)

    def fallback_key(_, event):
        # GDK uses XKB keycodes (evdev code plus eight) on Ubuntu's Wayland and X11 backends.
        if event.keyval == Gdk.KEY_Escape:
            return app.engine.capture_input(ESC)
        valid, keycode = event.get_keycode()
        return app.engine.capture_input(keycode - 8) if valid else False

    mouse_codes = {1: "BTN_LEFT", 2: "BTN_MIDDLE", 3: "BTN_RIGHT", 8: "BTN_SIDE", 9: "BTN_EXTRA",
                   10: "BTN_FORWARD", 11: "BTN_BACK", 12: "BTN_TASK"}

    def fallback_button(_, event):
        valid, code = event.get_button()
        return app.engine.capture_input(ecodes.get(mouse_codes.get(code), -1)) if valid else False

    def fallback_scroll(_, event):
        valid, direction = event.get_scroll_direction()
        if valid and direction in {Gdk.ScrollDirection.UP, Gdk.ScrollDirection.DOWN}:
            return app.engine.capture_input(WHEEL_UP if direction == Gdk.ScrollDirection.UP else WHEEL_DOWN)
        valid, _, vertical = event.get_scroll_deltas()
        return app.engine.capture_input(WHEEL_UP if vertical < 0 else WHEEL_DOWN) if valid and vertical else False

    prompt.connect("key-press-event", fallback_key)
    content.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
    content.connect("scroll-event", fallback_scroll)
    content.connect("button-press-event", fallback_button)
    prompt.show_all()
    app.engine.begin_capture(allowed, complete)
    try:
        prompt.run()
    finally:
        app.engine.end_capture(complete)
        prompt.destroy()

def number(control):
    return int(control.get_active_id() or 0)


def dialog(parent, title, submit="保存"):
    window = Gtk.Dialog(title=title, transient_for=parent, modal=True, destroy_with_parent=True)
    app = parent.get_application()
    window.set_application(app)
    window.connect("notify::is-active", app.on_editor_focus)
    window.set_default_size(570, -1)
    window.add_button("キャンセル", Gtk.ResponseType.CANCEL)
    window.add_button(submit, Gtk.ResponseType.OK)
    window.set_default_response(Gtk.ResponseType.OK)
    content = window.get_content_area()
    content.set_border_width(15)
    content.set_spacing(9)
    return window


def show_message(parent, text, kind=Gtk.MessageType.WARNING, actions=Gtk.ButtonsType.CLOSE):
    window = Gtk.MessageDialog(transient_for=parent, modal=True, destroy_with_parent=True,
                               message_type=kind, buttons=actions, text=text)
    window.set_application(parent.get_application())
    app = parent.get_application()
    window.connect("notify::is-active", app.on_editor_focus)
    try:
        return window.run()
    finally:
        window.destroy()


def form():
    return Gtk.Grid(column_spacing=12, row_spacing=8)


def form_field(grid, row, name, control):
    title = label(name)
    grid.attach(title, 0, row, 1, 1)
    grid.attach(control, 1, row, 1, 1)
    control.set_hexpand(True)
    return title


def table(columns):
    data = Gtk.ListStore(*([str] * len(columns)))
    view = Gtk.TreeView(model=data, hexpand=True, vexpand=True)
    for index, title in enumerate(columns):
        cell = Gtk.CellRendererText()
        cell.set_property("ellipsize", Pango.EllipsizeMode.END)
        field = Gtk.TreeViewColumn(title, cell, text=index)
        field.set_resizable(True)
        field.set_expand(index == len(columns) - 1)
        view.append_column(field)
    scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True, shadow_type=Gtk.ShadowType.IN)
    scroll.add(view)
    return data, view, scroll


def selected_rows(view):
    _, paths = view.get_selection().get_selected_rows()
    return sorted(path.get_indices()[0] for path in paths)


def selected_row(view):
    rows = selected_rows(view)
    return rows[0] if len(rows) == 1 else -1


def edit_step(parent, original=None):
    initial = original or Step("Tap", ecodes["KEY_SPACE"], 500)
    window = dialog(parent, "ステップの編集" if original else "ステップの追加", submit="確定")
    operation = combo(OPERATIONS.items(), initial.operation)
    key_field, key = picker(window, initial.button if initial.operation in BUTTON_ACTIONS else ecodes["KEY_SPACE"])
    duration = Gtk.SpinButton.new_with_range(1, 3_600_000, 1)
    duration.set_value(initial.milliseconds if initial.operation in TIME_ACTIONS else 500)
    text = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
    text.get_buffer().set_text(initial.value if initial.operation in VALUE_ACTIONS else "")
    text_scroll = Gtk.ScrolledWindow(min_content_height=75)
    text_scroll.add(text)
    layout = form()
    form_field(layout, 0, "動作", operation)
    key_name = form_field(layout, 1, "入力", key_field)
    duration_name = form_field(layout, 2, "時間（ms）", duration)
    value_name = form_field(layout, 3, "テキスト", text_scroll)
    window.get_content_area().add(layout)

    def update(*_):
        value = operation.get_active_id()
        key_name.set_visible(value in BUTTON_ACTIONS)
        key_field.set_visible(value in BUTTON_ACTIONS)
        duration_name.set_visible(value in TIME_ACTIONS)
        duration.set_visible(value in TIME_ACTIONS)
        value_name.set_visible(value in VALUE_ACTIONS)
        text_scroll.set_visible(value in VALUE_ACTIONS)
        value_name.set_text("コマンド" if value == "Command" else "テキスト")

    operation.connect("changed", update)
    try:
        window.show_all()
        update()
        while window.run() == Gtk.ResponseType.OK:
            value = operation.get_active_id()
            buffer = text.get_buffer()
            contents = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
            if value in BUTTON_ACTIONS and number(key) in WHEEL_CODES and value != "Tap":
                show_message(window, "ホイールは「押して離す」で指定してください。")
                continue
            if value in VALUE_ACTIONS and not (contents if value == "Text" else contents.strip()):
                show_message(window, "文字またはコマンドを入力してください。")
                continue
            return Step(value, number(key) if value in BUTTON_ACTIONS else 0,
                        duration.get_value_as_int() if value in TIME_ACTIONS else 0,
                        contents if value in VALUE_ACTIONS else "")
    finally:
        window.destroy()
    return None


def edit_binding(parent, layer, original, sample, save):
    initial = original or (example(layer, 0, ecodes) if sample else Binding(layer, 0, output=ecodes["KEY_SPACE"]))
    window = dialog(parent, "割り当ての編集" if original else "割り当ての追加")
    layout = form()
    source_field, source = picker(window, initial.trigger, trigger=True)
    behavior = combo(((key, text) for key, text in BEHAVIORS.items() if key != "Shift" or layer == NORMAL),
                     initial.behavior)
    output_field, output = picker(window, initial.output or ecodes["KEY_SPACE"])
    form_field(layout, 0, "割り当て元", source_field)
    form_field(layout, 1, "動作", behavior)
    output_name = form_field(layout, 2, "変換先", output_field)
    content = window.get_content_area()
    content.add(layout)
    help_text = label("この入力を押している間だけSKレイヤーに切り替わります。")
    content.add(help_text)
    sequence = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
    content.add(sequence)
    repeat = Gtk.CheckButton(label="Escを押すまで繰り返す")
    repeat.set_active(initial.repeat)
    sequence.add(repeat)
    data, view, scroll = table(("動作", "設定値"))
    selection = view.get_selection()
    selection.set_mode(Gtk.SelectionMode.MULTIPLE)
    scroll.set_min_content_height(185)
    steps = list(initial.steps)
    undo = []
    redo = []
    tools = Gtk.Box(spacing=6)
    sequence.add(tools)
    sequence.add(scroll)

    def render(rows=()):
        data.clear()
        for step in steps:
            details = []
            if step.operation in BUTTON_ACTIONS:
                details.append(button_label(step.button))
            if step.operation in TIME_ACTIONS:
                details.append(f"{step.milliseconds:,} ms")
            if step.operation in VALUE_ACTIONS:
                details.append(" ".join(step.value.splitlines()))
            data.append([OPERATIONS[step.operation], "   ".join(details)])
        for row in rows:
            selection.select_path(Gtk.TreePath.new_from_indices([row]))

    def remember():
        undo.append((steps.copy(), selected_rows(view)))
        redo.clear()

    def restore(previous, following):
        if previous:
            following.append((steps.copy(), selected_rows(view)))
            restored, rows = previous.pop()
            steps[:] = restored
            render(rows)

    def change_step(edit):
        index = selected_row(view) if edit else len(steps)
        if index < 0:
            return
        updated = edit_step(window, steps[index] if edit else None)
        if updated is not None and (not edit or updated != steps[index]):
            remember()
            steps[index:index + 1] = [updated]
            render([index])

    def remove():
        rows = selected_rows(view)
        if not rows:
            return
        remember()
        for index in reversed(rows):
            del steps[index]
        render([min(rows[0], len(steps) - 1)] if steps else [])

    def move(delta):
        index = selected_row(view)
        destination = index + delta
        if index >= 0 and 0 <= destination < len(steps):
            remember()
            steps[index], steps[destination] = steps[destination], steps[index]
            render([destination])

    clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

    def copy_steps():
        items = [steps[index] for index in selected_rows(view)]
        if items:
            clipboard.set_text(encode_steps(items), -1)

    def paste_steps():
        clipboard.request_text(receive_steps, None)

    def receive_steps(_, text, _data):
        if not window.get_visible():
            return
        try:
            items = decode_steps(text, BUTTON_CODES)
        except (TypeError, ValueError) as error:
            show_message(window, str(error))
            return
        rows = selected_rows(view)
        index = rows[-1] + 1 if rows else len(steps)
        remember()
        steps[index:index] = items
        render(range(index, index + len(items)))

    def history_shortcuts(_, event):
        state = event.state & Gtk.accelerator_get_default_mod_mask()
        if not sequence.get_visible() or state != Gdk.ModifierType.CONTROL_MASK:
            return False
        keyval = Gdk.keyval_to_lower(event.keyval)
        if keyval == Gdk.KEY_z:
            restore(undo, redo)
            return True
        if keyval == Gdk.KEY_y:
            restore(redo, undo)
            return True
        return False

    def list_shortcuts(_, event):
        state = event.state & Gtk.accelerator_get_default_mod_mask()
        keyval = Gdk.keyval_to_lower(event.keyval)
        if not state and keyval in {Gdk.KEY_Delete, Gdk.KEY_KP_Delete}:
            remove()
            return True
        if state == Gdk.ModifierType.CONTROL_MASK and keyval in {Gdk.KEY_c, Gdk.KEY_v}:
            (copy_steps if keyval == Gdk.KEY_c else paste_steps)()
            return True
        return False

    for text, action in (("ステップ追加", lambda: change_step(False)), ("編集", lambda: change_step(True)),
                         ("削除", remove), ("上へ", lambda: move(-1)), ("下へ", lambda: move(1))):
        tools.add(button(text, action))
    tools.add(button("コピー", copy_steps))
    tools.add(button("貼り付け", paste_steps))
    window.connect("key-press-event", history_shortcuts)
    view.connect("key-press-event", list_shortcuts)
    view.connect("row-activated", lambda *_: change_step(True))

    def update(*_):
        current = behavior.get_active_id()
        output_field.set_visible(current == "Remap")
        output_name.set_visible(current == "Remap")
        sequence.set_visible(current == "Sequence")
        help_text.set_visible(current == "Shift")

    behavior.connect("changed", update)
    try:
        window.show_all()
        update()
        render()
        while window.run() == Gtk.ResponseType.OK:
            current = behavior.get_active_id()
            try:
                save(Binding(layer, number(source), current, number(output) if current == "Remap" else 0,
                             repeat.get_active() if current == "Sequence" else False,
                             tuple(steps) if current == "Sequence" else ()))
            except (OSError, ValueError) as error:
                show_message(window, str(error))
            else:
                break
    finally:
        window.destroy()


@dataclass
class BindingEdit:
    before: list[Binding]
    after: list[Binding]
    layer: str
    before_selection: list[Binding]
    after_selection: list[Binding]


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Kitajimacro", default_width=820, default_height=500)
        self.app = app
        self.current = []
        self.undo = []
        self.redo = []
        self.connect("key-press-event", self.history_shortcuts)
        self.set_icon_from_file(str(app.icon))
        self.connect("delete-event", lambda *_: self.hide_on_delete())
        self.connect("window-state-event", self.on_window_state)
        self.connect("notify::is-active", app.on_editor_focus)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=18)
        self.add(outer)
        header = Gtk.Box(spacing=10)
        name = label("")
        name.set_markup("<span size='xx-large' weight='bold'>Kitajimacro</span>")
        header.pack_start(name, True, True, 0)
        self.toggle = button("有効にする", app.engine.toggle)
        self.toggle.get_style_context().add_class("suggested-action")
        header.pack_end(self.toggle, False, False, 0)
        outer.add(header)
        self.state = label("")
        outer.add(self.state)
        tool_row = Gtk.Box(spacing=7)
        outer.add(tool_row)
        self.layer = combo(((NORMAL, "通常レイヤー"), (SHIFT, "SKレイヤー")), NORMAL)
        self.layer.connect("changed", lambda *_: self.render())
        tool_row.add(self.layer)
        self.edit_control = button("編集", lambda: self.edit(existing=True))
        self.delete_control = button("削除", self.remove)
        for control in (button("＋ 追加", self.edit), self.edit_control, self.delete_control,
                        button("例を追加", lambda: self.edit(sample=True))):
            tool_row.add(control)
        self.data, self.view, scroll = table(("割り当て元", "動作", "内容"))
        selection = self.view.get_selection()
        selection.set_mode(Gtk.SelectionMode.MULTIPLE)
        selection.connect("changed", lambda *_: self.update_selection())
        self.view.connect("key-press-event", self.list_shortcuts)
        self.view.connect("row-activated", lambda _, path, _column: self.edit(existing=True, row=path.get_indices()[0]))
        outer.pack_start(scroll, True, True, 0)

        footer = Gtk.Box(spacing=8)
        footer.add(button("エクスポート", self.export_file))
        footer.add(button("インポート", self.import_file))
        footer.add(button("入力デバイスを再接続", app.connect_devices))
        outer.add(footer)
        outer.add(label("F12  有効・停止の切替      Esc  シーケンス停止"))
        self.notice = label(app.last_status)
        self.notice.set_line_wrap(True)
        outer.add(self.notice)
        self.render()
        self.update_state()

    def on_window_state(self, _window, event):
        flags = event.changed_mask & event.new_window_state
        if flags & Gdk.WindowState.ICONIFIED:
            self.hide()
        return False

    def update_state(self):
        enabled = self.app.engine.enabled
        self.toggle.set_label("停止する" if enabled else "有効にする")
        layer = "SKレイヤー" if self.app.engine.shift else "通常レイヤー"
        self.state.set_text(f"● 有効  ·  {layer}" if enabled else "○ 停止中")

    def update_selection(self):
        selected = selected_rows(self.view)
        self.edit_control.set_sensitive(len(selected) == 1)
        self.delete_control.set_sensitive(bool(selected))

    def render(self):
        layer = self.layer.get_active_id()
        self.current = sorted((item for item in self.app.bindings if item.layer == layer),
                              key=lambda item: button_label(item.trigger))
        self.data.clear()
        for binding in self.current:
            if binding.behavior == "Remap":
                detail = button_label(binding.output)
            elif binding.behavior == "Shift":
                detail = "押している間はSKレイヤー"
            else:
                detail = f"{len(binding.steps)} ステップ" + ("  ·  Escまで繰り返す" if binding.repeat else "  ·  1回")
            self.data.append([button_label(binding.trigger), BEHAVIORS[binding.behavior], detail])
        self.update_selection()

    def edit(self, existing=False, sample=False, row=None):
        selected = selected_row(self.view) if row is None else row
        if existing and selected < 0:
            return
        original = self.current[selected] if existing else None
        edit_binding(self, self.layer.get_active_id(), original, sample,
                     lambda binding: self.save([item for item in self.app.bindings if item != original] + [binding],
                                               [binding]))

    def remove(self):
        selected = self.selected_bindings()
        if selected:
            try:
                self.save([item for item in self.app.bindings if item not in selected], [])
            except (OSError, ValueError) as error:
                show_message(self, str(error))

    def selected_bindings(self):
        return [self.current[index] for index in selected_rows(self.view)]

    def save(self, bindings, selection, pause=False):
        if self.app.bindings == bindings:
            if pause and self.app.engine.enabled:
                self.app.engine.toggle()
            return
        edit = BindingEdit(self.app.bindings, bindings, self.layer.get_active_id(), self.selected_bindings(), selection)
        self.apply(edit.after, edit.layer, edit.after_selection, pause)
        self.undo.append(edit)
        self.redo.clear()

    def restore(self, previous, following, undo):
        if not previous:
            return
        edit = previous[-1]
        try:
            self.apply(edit.before if undo else edit.after, edit.layer,
                       edit.before_selection if undo else edit.after_selection)
        except (OSError, ValueError) as error:
            show_message(self, str(error))
        else:
            following.append(previous.pop())

    def apply(self, bindings, layer, selection, pause=False):
        self.app.save(bindings)
        if pause and self.app.engine.enabled:
            self.app.engine.toggle()
        self.layer.set_active_id(layer)
        selector = self.view.get_selection()
        selector.unselect_all()
        for index, item in enumerate(self.current):
            if item in selection:
                selector.select_path(Gtk.TreePath.new_from_indices([index]))

    def history_shortcuts(self, _window, event):
        state = event.state & Gtk.accelerator_get_default_mod_mask()
        if state != Gdk.ModifierType.CONTROL_MASK:
            return False
        key = Gdk.keyval_to_lower(event.keyval)
        if key == Gdk.KEY_z:
            self.restore(self.undo, self.redo, undo=True)
            return True
        if key == Gdk.KEY_y:
            self.restore(self.redo, self.undo, undo=False)
            return True
        return False

    def list_shortcuts(self, _view, event):
        state = event.state & Gtk.accelerator_get_default_mod_mask()
        if not state and event.keyval in {Gdk.KEY_Delete, Gdk.KEY_KP_Delete}:
            self.remove()
            return True
        return False

    def pick_settings_file(self, title, save=False):
        action = Gtk.FileChooserAction.SAVE if save else Gtk.FileChooserAction.OPEN
        chooser = Gtk.FileChooserDialog(title=title, transient_for=self, action=action, modal=True)
        chooser.set_application(self.app)
        chooser.connect("notify::is-active", self.app.on_editor_focus)
        chooser.add_button("キャンセル", Gtk.ResponseType.CANCEL)
        chooser.add_button("保存" if save else "開く", Gtk.ResponseType.OK)
        settings_filter = Gtk.FileFilter()
        settings_filter.set_name("Kitajimacro 設定 (*.json)")
        settings_filter.add_pattern("*.json")
        chooser.add_filter(settings_filter)
        if save:
            chooser.set_current_name("kitajimacro.json")
            chooser.set_do_overwrite_confirmation(True)
        try:
            return Path(chooser.get_filename()) if chooser.run() == Gtk.ResponseType.OK else None
        finally:
            chooser.destroy()

    def export_file(self):
        include_commands = False
        if any(map(has_commands, self.app.bindings)):
            prompt = dialog(self, "設定のエクスポート")
            option = Gtk.CheckButton(label="コマンドを含む割り当ても保存する")
            content = prompt.get_content_area()
            content.add(label("他の人と共有する場合は、コマンドを除外できます。"))
            content.add(option)
            try:
                prompt.show_all()
                if prompt.run() != Gtk.ResponseType.OK:
                    return
                include_commands = option.get_active()
            finally:
                prompt.destroy()
        path = self.pick_settings_file("設定のエクスポート", save=True)
        if path is None:
            return
        try:
            self.app.store.save_exchange(path, self.app.bindings, ecodes, include_commands)
            self.app.report("設定をエクスポートしました")
        except (OSError, ValueError) as error:
            show_message(self, str(error))

    def import_file(self):
        path = self.pick_settings_file("設定のインポート")
        if path is None:
            return
        try:
            bindings, foreign_excluded = self.app.store.load_exchange(path, ecodes)
            chosen = review_import(self, bindings, foreign_excluded)
            if chosen is not None:
                self.save(chosen, [], pause=True)
                self.app.report(f"{len(chosen)}件をインポートしました。マクロは停止中です。")
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as error:
            show_message(self, str(error))


def review_import(parent, bindings, foreign_excluded):
    window = dialog(parent, "設定のインポート", submit="インポート")
    content = window.get_content_area()
    content.add(label("現在の通常・SKレイヤーの割り当てを入れ替えます。"))
    if foreign_excluded:
        content.add(label(f"対応しない実行環境のコマンドを含む{foreign_excluded}件は除外します。"))
    content.add(label("信頼できる設定ファイルのみ取り込むこと。"))
    content.add(label("Kitajimacro製作者は一切責任を負わないこと。"))
    consent = Gtk.CheckButton(label="上記の両方に同意します")
    content.add(consent)
    count = label("")
    content.add(count)
    commands = [binding for binding in bindings if has_commands(binding)]
    option = Gtk.CheckButton(label="内容を確認し、コマンドを含む割り当ても取り込む")

    def display_command(value):
        safe = "".join(char if unicodedata.category(char) not in {"Cf", "Zl", "Zp"} else f"\\u{{{ord(char):X}}}" for char in value)
        return json.dumps(safe, ensure_ascii=False)

    if commands:
        preview = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        lines = []
        for binding in commands:
            layer = "通常" if binding.layer == NORMAL else "SK"
            lines.append(f"{layer}  {button_label(binding.trigger)}")
            lines.extend(f"{index}. {display_command(step.value)}"
                         for index, step in enumerate(binding.steps, 1) if step.operation == "Command")
            lines.append("")
        preview.get_buffer().set_text("\n".join(lines))
        scroll = Gtk.ScrolledWindow(min_content_height=180)
        scroll.add(preview)
        content.add(scroll)
        content.add(option)
        content.add(label("コマンドは、取り込み後に対応するマクロを実行すると動きます。"))

    def update(*_):
        omitted = 0 if option.get_active() else len(commands)
        accepted = len(bindings) - omitted
        count.set_text(f"{accepted}件を取り込みます" + (f"（コマンドを含む{omitted}件は除外）" if omitted else "。"))
        permitted = consent.get_active() and (accepted > 0 or not (bindings or foreign_excluded))
        window.set_response_sensitive(Gtk.ResponseType.OK, permitted)
        return permitted

    option.connect("toggled", update)
    consent.connect("toggled", update)
    try:
        window.show_all()
        update()
        if window.run() == Gtk.ResponseType.OK and update():
            return bindings if option.get_active() else [binding for binding in bindings if not has_commands(binding)]
        return None
    finally:
        window.destroy()
