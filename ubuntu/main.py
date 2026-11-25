#!/usr/bin/python3
"""Ubuntu entry point for Kitajimacro."""

import os
import signal
import subprocess
import sys
from time import monotonic, sleep
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import AyatanaAppIndicator3 as Indicator, Gio, GLib, Gtk

from engine import Engine
from gui import MainWindow
from linux_input import BUTTON_CODES, InputBackend, LinuxOutput
from model import BindingStore, config_home

APP_ID = "io.github.ShunKitajima1122.Kitajimacro"


def schedule(milliseconds, callback):
    def once():
        callback()
        return GLib.SOURCE_REMOVE
    return GLib.timeout_add(milliseconds, once)


def exec_argument(path):
    text = str(path).replace("%", "%%")
    text = "".join("\\" + char if char in {'"', '\\', '$', chr(96)} else char for char in text)
    return '"' + text + '"'


def restart_resident():
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def running():
        result = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                               "NameHasOwner", GLib.Variant("(s)", (APP_ID,)), GLib.VariantType("(b)"),
                               Gio.DBusCallFlags.NONE, 1000, None)
        return result.unpack()[0]

    if not running():
        return
    subprocess.run([sys.executable, "-B", __file__, "--exit"], check=True, timeout=5)
    deadline = monotonic() + 5
    while running():
        if monotonic() >= deadline:
            raise RuntimeError("常駐中のKitajimacroを終了できませんでした。")
        sleep(0.025)


class Application(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.icon = Path(__file__).resolve().with_name("kitajimacro.png")
        self.autostart = config_home() / "autostart" / "kitajimacro.desktop"
        data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        self.desktop_entry = data_home / "applications" / f"{APP_ID}.desktop"
        self.store = BindingStore(config_home() / "kitajimacro" / "bindings.json", BUTTON_CODES)
        self.bindings = []
        self.window = None
        self.indicator = None
        self.session = None
        self.connected = False
        self.launched = False
        self.last_status = ""

    def do_startup(self):
        Gtk.Application.do_startup(self)
        Gtk.Window.set_default_icon_from_file(str(self.icon))
        self.hold()
        output = LinuxOutput()
        self.engine = Engine(output, schedule, GLib.source_remove, self.changed, self.report)
        self.backend = InputBackend(output, self.engine, self.editing, self.report)
        self.load()
        try:
            self.write_desktop_entry(self.desktop_entry)
        except (OSError, GLib.Error) as error:
            self.report(f"アプリメニューを登録できませんでした。 {error}")
        self.make_indicator()
        self.watch_session()
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self.request_exit)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.request_exit)

    def do_command_line(self, invocation):
        arguments = invocation.get_arguments()[1:]
        if arguments == ["--exit"]:
            GLib.idle_add(self.request_exit)
            return 0
        if arguments not in ([], ["--background"]):
            return 2
        if not self.launched:
            self.launched = True
            self.connect_devices()
            if arguments:
                self.engine.toggle()
        if not arguments:
            self.activate()
        return 0

    def do_activate(self):
        if self.window is None:
            self.window = MainWindow(self)
        self.window.show_all()
        self.window.deiconify()
        self.window.present()

    def do_shutdown(self):
        self.backend.stop()
        self.indicator.set_status(Indicator.IndicatorStatus.PASSIVE)
        Gtk.Application.do_shutdown(self)

    def request_exit(self):
        for window in self.get_windows():
            if isinstance(window, Gtk.Dialog):
                window.response(Gtk.ResponseType.CANCEL)
        self.quit()
        return GLib.SOURCE_REMOVE

    def load(self):
        try:
            self.bindings = self.store.load()
            self.engine.replace(self.bindings)
        except (OSError, ValueError, TypeError, AttributeError) as error:
            self.report(f"設定を読み込めませんでした。 {error}")

    def save(self, bindings):
        self.store.save(bindings)
        self.bindings = bindings
        self.engine.replace(bindings)
        self.window.render()
        self.report("設定を保存しました")

    def report(self, status):
        self.last_status = status
        if self.window is not None:
            self.window.notice.set_text(status)

    def changed(self):
        text = "有効" if self.engine.enabled else "停止中"
        if self.indicator is not None:
            self.indicator.set_title(f"Kitajimacro | {text}")
            self.toggle_item.set_label("マクロを停止" if self.engine.enabled else "マクロを有効にする")
        if self.window is not None:
            self.window.update_state()

    def editing(self):
        return any(window.is_active() for window in self.get_windows())

    def on_editor_focus(self, window, _property):
        if window.is_active():
            self.engine.stop(remaps=True)

    def make_indicator(self):
        self.indicator = Indicator.Indicator.new_with_path(APP_ID, self.icon.stem,
                                                           Indicator.IndicatorCategory.APPLICATION_STATUS,
                                                           str(self.icon.parent))
        menu = Gtk.Menu()
        settings_item = Gtk.MenuItem(label="設定を開く")
        settings_item.connect("activate", lambda *_: self.activate())
        menu.append(settings_item)
        self.toggle_item = Gtk.MenuItem(label="マクロを有効にする")
        self.toggle_item.connect("activate", lambda *_: self.engine.toggle())
        menu.append(self.toggle_item)
        self.startup_item = Gtk.CheckMenuItem(label="サインイン時に自動起動")
        self.startup_item.set_active(self.autostart.exists())
        self.startup_item.connect("toggled", self.set_autostart)
        menu.append(self.startup_item)
        menu.append(Gtk.SeparatorMenuItem())
        exit_item = Gtk.MenuItem(label="終了")
        exit_item.connect("activate", lambda *_: self.request_exit())
        menu.append(exit_item)
        menu.show_all()
        self.indicator.set_menu(menu)
        self.indicator.set_secondary_activate_target(settings_item)
        self.indicator.set_status(Indicator.IndicatorStatus.ACTIVE)
        self.changed()

    def set_autostart(self, toggle):
        try:
            if not toggle.get_active():
                self.autostart.unlink(missing_ok=True)
                return
            self.write_desktop_entry(self.autostart, "--background")
        except (OSError, GLib.Error) as error:
            self.report(f"自動起動を設定できませんでした。 {error}")
            with toggle.handler_block_by_func(self.set_autostart):
                toggle.set_active(self.autostart.exists())
            self.activate()

    def write_desktop_entry(self, destination, option=""):
        section = "Desktop Entry"
        command = f"/usr/bin/python3 -B {exec_argument(Path(__file__).resolve())}"
        entry = GLib.KeyFile()
        for key, value in {
            "Type": "Application", "Name": "Kitajimacro", "Icon": str(self.icon),
            "Exec": f"{command} {option}" if option else command,
        }.items():
            entry.set_string(section, key, value)
        destination.parent.mkdir(parents=True, exist_ok=True)
        entry.save_to_file(str(destination))

    def connect_devices(self):
        if self.session is not None:
            active = self.session.get_cached_property("Active")
            if active is None or not active.get_boolean():
                self.report("デスクトップセッションが有効になるまで待機しています。")
                return
        self.backend.start()
        self.connected = self.backend.monitor is not None

    def watch_session(self):
        session_id = os.environ.get("XDG_SESSION_ID")
        if not session_id:
            return
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            service = "org.freedesktop.login1"
            result = bus.call_sync(service, "/org/freedesktop/login1", f"{service}.Manager",
                                   "GetSession", GLib.Variant("(s)", (session_id,)), GLib.VariantType("(o)"),
                                   Gio.DBusCallFlags.NONE, 1000, None)
            self.session = Gio.DBusProxy.new_sync(bus, Gio.DBusProxyFlags.DO_NOT_AUTO_START, None, service,
                                                 result.unpack()[0], f"{service}.Session", None)
            self.session.connect("g-properties-changed", self.session_changed)
        except GLib.Error:
            return

    def session_changed(self, proxy, changes, invalidated):
        if changes.lookup_value("Active") is None and "Active" not in invalidated:
            return
        active = proxy.get_cached_property("Active")
        if active is None or not active.get_boolean():
            self.backend.stop()
            self.connected = False
            self.report("デスクトップセッションが非アクティブのため入力監視を停止しました。")
        elif self.launched and not self.connected:
            self.connect_devices()


if __name__ == "__main__":
    if os.geteuid() == 0:
        sys.exit("Kitajimacroは通常のデスクトップユーザーで実行してください。")
    arguments = sys.argv
    if arguments[1:] == ["--restart"]:
        try:
            restart_resident()
        except (GLib.Error, OSError, subprocess.SubprocessError, RuntimeError) as error:
            sys.exit(f"Kitajimacroを再起動できませんでした。 {error}")
        arguments = arguments[:1]
    sys.exit(Application().run(arguments))
