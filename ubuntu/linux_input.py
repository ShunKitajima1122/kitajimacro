"""evdev device forwarding and Linux macro output."""

import errno
import os
import shutil
import signal
import subprocess
import tempfile
from contextlib import contextmanager

import evdev
import pyudev
from evdev import ecodes as E
from gi.repository import GLib

from model import WHEEL_CODES, WHEEL_DELTA, WHEEL_UP

VIRTUAL_PHYS = "kitajimacro/"
MOUSE_CODES = set(range(E.BTN_LEFT, E.BTN_TASK + 1))
KEYBOARD_CODES = {code for name, code in E.ecodes.items() if name.startswith("KEY_")
                  and isinstance(code, int) and 0 < code <= E.KEY_MAX
                  and name not in {"KEY_UNKNOWN", "KEY_MAX", "KEY_CNT", "KEY_MIN_INTERESTING"}}
BUTTON_CODES = KEYBOARD_CODES | MOUSE_CODES | WHEEL_CODES
VERTICAL_WHEEL = {E.REL_WHEEL, E.REL_WHEEL_HI_RES}
DEVICE_EVENTS = GLib.IO_IN | GLib.IO_ERR | GLib.IO_HUP | GLib.IO_NVAL


def button_label(code):
    if code in WHEEL_CODES:
        return "ホイール 上" if code == WHEEL_UP else "ホイール 下"
    special = {
        E.KEY_ESC: "Esc", E.KEY_SPACE: "Space", E.KEY_ENTER: "Enter", E.KEY_KPENTER: "テンキー Enter",
        E.KEY_LEFTCTRL: "左 Ctrl", E.KEY_RIGHTCTRL: "右 Ctrl", E.KEY_LEFTSHIFT: "左 Shift",
        E.KEY_RIGHTSHIFT: "右 Shift", E.KEY_LEFTALT: "左 Alt", E.KEY_RIGHTALT: "右 Alt",
        E.KEY_LEFTMETA: "左 Super", E.KEY_RIGHTMETA: "右 Super",
        E.KEY_LEFT: "←", E.KEY_RIGHT: "→", E.KEY_UP: "↑", E.KEY_DOWN: "↓",
        E.BTN_LEFT: "マウス 左", E.BTN_RIGHT: "マウス 右", E.BTN_MIDDLE: "マウス 中央",
        E.BTN_SIDE: "マウス X1", E.BTN_EXTRA: "マウス X2",
        E.BTN_FORWARD: "マウス Forward", E.BTN_BACK: "マウス Back", E.BTN_TASK: "マウス Task",
    }
    if code in special:
        return special[code]
    name = E.KEY.get(code, str(code))
    return (name[0] if isinstance(name, (list, tuple)) else name).removeprefix("KEY_")


def clipboard_command():
    x11 = os.environ.get("DISPLAY") and shutil.which("xclip")
    wayland = os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy")
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower().split(":")
    # GNOME can bridge XWayland clipboard selections without focusing a helper window.
    if x11 and (not wayland or "gnome" in desktop):
        return [x11, "-selection", "clipboard", "-in"]
    if wayland:
        return [wayland, "--type", "text/plain;charset=utf-8"]
    raise RuntimeError("文字入力にはwl-copy（Wayland）またはxclip（X11）が必要です。")


class LinuxOutput:
    paste_keys = (E.KEY_LEFTCTRL, E.KEY_V)

    def __init__(self):
        self.keyboard = None
        self.mouse = None

    def open(self):
        self.close()
        self.keyboard = evdev.UInput({E.EV_KEY: sorted(KEYBOARD_CODES)}, name="Kitajimacro Keyboard", phys=VIRTUAL_PHYS + "output-keys")
        try:
            self.mouse = evdev.UInput({E.EV_KEY: sorted(MOUSE_CODES), E.EV_REL: [E.REL_X, E.REL_Y, *sorted(VERTICAL_WHEEL)]},
                                      name="Kitajimacro Mouse", phys=VIRTUAL_PHYS + "output-mouse")
        except Exception:
            self.close()
            raise

    def close(self):
        for device in (self.keyboard, self.mouse):
            if device is not None:
                device.close()
        self.keyboard = self.mouse = None

    def send(self, code, down):
        device = self.mouse if code in MOUSE_CODES or code in WHEEL_CODES else self.keyboard
        if device is None:
            raise OSError("出力デバイスが接続されていません。")
        if code in WHEEL_CODES:
            if not down:
                return
            direction = 1 if code == WHEEL_UP else -1
            device.write(E.EV_REL, E.REL_WHEEL_HI_RES, direction * WHEEL_DELTA)
            device.write(E.EV_REL, E.REL_WHEEL, direction)
        else:
            device.write(E.EV_KEY, code, int(down))
        device.syn()

    def repeat(self, code):
        if self.keyboard is not None and code in KEYBOARD_CODES:
            self.keyboard.write(E.EV_KEY, code, 2)
            self.keyboard.syn()

    @contextmanager
    def start_job(self, operation, value):
        stream = None
        try:
            if operation == "Text":
                arguments = clipboard_command()
                stream = tempfile.TemporaryFile()
                stream.write(value.encode("utf-8"))
                stream.seek(0)
            else:
                arguments = ["/bin/sh", "-c", value]
            process = subprocess.Popen(arguments, stdin=stream if stream is not None else subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       cwd=os.path.expanduser("~"), start_new_session=True)
            try:
                yield process
            finally:
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    GLib.timeout_add(50, lambda: process.poll() is None)
        finally:
            if stream is not None:
                stream.close()


class InputProxy:
    def __init__(self, device):
        self.device = device
        self.keys = set()
        self.watch = None
        self.dropped = False
        self.scan = None
        self.wheel_events = []
        self.grabbed = False
        capabilities = device.capabilities(absinfo=True)
        for kind in (E.EV_SYN, E.EV_FF, E.EV_LED, E.EV_SND, E.EV_REP):
            capabilities.pop(kind, None)
        name = f"{device.name} (Kitajimacro)".encode("utf-8")[:79].decode("utf-8", "ignore")
        self.output = evdev.UInput(capabilities, name=name,
                                   vendor=device.info.vendor, product=device.info.product, version=device.info.version,
                                   bustype=device.info.bustype, phys=VIRTUAL_PHYS + device.path,
                                   input_props=device.input_props())

    def write(self, event):
        if self.scan is not None:
            self.output.write_event(self.scan)
            self.scan = None
        self.output.write_event(event)
        if event.type == E.EV_KEY and event.value < 2:
            self.keys.add(event.code) if event.value else self.keys.discard(event.code)

    def resync(self, active):
        for code in self.keys - active:
            self.output.write(E.EV_KEY, code, 0)
        for code in active - self.keys:
            self.output.write(E.EV_KEY, code, 1)
        self.keys = active
        self.output.syn()

    def close(self):
        if self.grabbed:
            try:
                self.device.ungrab()
            except OSError:
                pass
        self.device.close()
        self.output.close()


class InputBackend:
    def __init__(self, output, engine, editing, status):
        self.output = output
        self.engine = engine
        self.editing = editing
        self.status = status
        self.context = pyudev.Context()
        self.monitor = None
        self.monitor_watch = None
        self.proxies = {}
        self.pending = {}
        self.seat = os.environ.get("XDG_SEAT", "seat0")

    def start(self):
        self.stop()
        try:
            self.output.open()
            self.monitor = pyudev.Monitor.from_netlink(self.context)
            self.monitor.filter_by(subsystem="input")
            self.monitor.start()
            self.monitor_watch = GLib.io_add_watch(self.monitor.fileno(), GLib.PRIORITY_DEFAULT,
                                                  DEVICE_EVENTS, self.on_udev)
            self.scan()
        except (OSError, evdev.UInputError) as error:
            self.stop()
            self.status(f"入力を開始できません。デバイスのアクセス権を確認してください。 {error}")

    def stop(self):
        self.engine.stop(remaps=True)
        if self.monitor_watch is not None:
            GLib.source_remove(self.monitor_watch)
            self.monitor_watch = None
        self.monitor = None
        for path in tuple(self.proxies):
            self.drop(path)
        for proxy, timer in self.pending.values():
            GLib.source_remove(timer)
            proxy.close()
        self.pending.clear()
        self.output.close()

    def on_udev(self, _fd, condition):
        if not condition & GLib.IO_IN:
            self.monitor_watch = None
            return False
        while self.monitor.poll(timeout=0) is not None:
            pass
        self.scan()
        return True

    def eligible(self, info):
        properties = info.properties
        if not info.device_node or not info.sys_name.startswith("event") or properties.get("ID_SEAT", "seat0") != self.seat:
            return False
        if info.device_path.startswith("/devices/virtual/"):
            return False
        if properties.get("ID_INPUT_TOUCHPAD") == "1":
            return False
        return properties.get("ID_INPUT_KEYBOARD") == "1" or properties.get("ID_INPUT_MOUSE") == "1"

    def scan(self):
        candidates = {info.device_node for info in self.context.list_devices(subsystem="input") if self.eligible(info)}
        for path in set(self.proxies) - candidates:
            self.drop(path)
        for path in set(self.pending) - candidates:
            proxy, timer = self.pending.pop(path)
            GLib.source_remove(timer)
            proxy.close()
        denied = 0
        for path in sorted(candidates - self.proxies.keys() - self.pending.keys()):
            device = None
            try:
                device = evdev.InputDevice(path)
                keys = set(device.capabilities(absinfo=False).get(E.EV_KEY, []))
                if not (device.phys or "").startswith(VIRTUAL_PHYS) and keys & BUTTON_CODES:
                    proxy = InputProxy(device)
                    timer = GLib.timeout_add(250, self.grab, path)
                    self.pending[path] = proxy, timer
                    device = None
            except (OSError, evdev.UInputError):
                denied += 1
            finally:
                if device is not None:
                    device.close()
        self.device_status(denied)

    def device_status(self, denied=0):
        count = len(self.proxies)
        if count:
            message = f"入力デバイス {count} 台に接続中"
        elif self.pending:
            message = "入力デバイスに接続中…"
        else:
            message = "対応する入力デバイスがありません。アクセス権と接続を確認してください。"
        self.status(message + (f"（アクセスできないデバイス {denied} 台）" if denied else ""))

    def grab(self, path):
        proxy, _timer = self.pending[path]
        try:
            if proxy.device.active_keys():
                return True
            proxy.device.grab()
            proxy.grabbed = True
            try:
                for _event in proxy.device.read():
                    pass
            except BlockingIOError:
                pass
            active = set(proxy.device.active_keys())
            proxy.resync(active)
            self.engine.track_passthrough(path, active)
            proxy.watch = GLib.io_add_watch(proxy.device.fd, GLib.PRIORITY_HIGH, DEVICE_EVENTS,
                                           lambda fd, condition: self.read(path, condition))
            self.proxies[path] = proxy
        except OSError as error:
            proxy.close()
            self.status(f"{path} を監視できませんでした。 {error}")
        else:
            self.device_status()
        self.pending.pop(path, None)
        return False

    def drop(self, path):
        proxy = self.proxies.pop(path)
        if proxy.watch is not None:
            GLib.source_remove(proxy.watch)
        self.engine.detach(path)
        proxy.close()

    def read(self, path, condition):
        proxy = self.proxies[path]
        try:
            if not condition & GLib.IO_IN:
                raise OSError(errno.ENODEV, "入力デバイスの接続が切れました。")
            for event in proxy.device.read():
                self.forward(path, proxy, event)
        except BlockingIOError:
            return True
        except OSError as error:
            proxy.watch = None
            self.drop(path)
            self.status(str(error))
            return False
        return True

    def forward(self, path, proxy, event):
        if event.type == E.EV_SYN and event.code == E.SYN_DROPPED:
            proxy.scan = None
            proxy.wheel_events.clear()
            proxy.dropped = True
            return
        if proxy.dropped:
            if event.type == E.EV_SYN and event.code == E.SYN_REPORT:
                self.engine.detach(path)
                active = set(proxy.device.active_keys())
                self.engine.track_passthrough(path, active)
                proxy.resync(active)
                proxy.dropped = False
            return
        if event.type == E.EV_REL and event.code in VERTICAL_WHEEL:
            proxy.wheel_events.append(event)
            return
        if event.type == E.EV_SYN and event.code == E.SYN_REPORT and proxy.wheel_events:
            self.forward_wheel(path, proxy)
        if event.type == E.EV_MSC and event.code == E.MSC_SCAN:
            proxy.scan = event
            return
        if event.type == E.EV_KEY and self.engine.route(path, event.code, event.value, self.editing()):
            proxy.scan = None
            return
        proxy.write(event)


    def forward_wheel(self, path, proxy):
        events = proxy.wheel_events
        high_resolution = [event.value for event in events if event.code == E.REL_WHEEL_HI_RES]
        # High-resolution devices often send both values in the same packet.
        delta = sum(high_resolution) if high_resolution else sum(event.value for event in events) * WHEEL_DELTA
        if not self.engine.route_wheel(path, delta, self.editing()):
            for event in events:
                proxy.write(event)
        events.clear()
