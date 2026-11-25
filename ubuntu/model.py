"""Bindings and their on-disk format for the Ubuntu application."""

import json
import os
import stat
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

NORMAL = "Normal"
SHIFT = "Shift"
ESC = 1
F12 = 88
WHEEL_UP = 0x10000
WHEEL_DOWN = 0x10001
WHEEL_CODES = {WHEEL_UP, WHEEL_DOWN}
WHEEL_DELTA = 120
TAP = "Tap"
DOWN = "Down"
UP = "Up"
HOLD = "Hold"
WAIT = "Wait"
TEXT = "Text"
COMMAND = "Command"
BUTTON_ACTIONS = {TAP, DOWN, UP, HOLD}
TIME_ACTIONS = {WAIT, HOLD}
VALUE_ACTIONS = {TEXT, COMMAND}
MAX_EXCHANGE_BYTES = 4 * 1024 * 1024
CLIPBOARD_HEADER = "Kitajimacro:steps:ubuntu:v1"


@dataclass(frozen=True)
class Step:
    operation: str
    button: int = 0
    milliseconds: int = 0
    value: str = ""


@dataclass(frozen=True)
class Binding:
    layer: str
    trigger: int
    behavior: str = "Remap"
    output: int = 0
    repeat: bool = False
    steps: tuple[Step, ...] = ()


@dataclass(frozen=True)
class ShortcutKeys:
    toggle: int = F12
    stop: int = ESC

    def contains(self, code):
        return code == self.toggle or code == self.stop

    def validate(self, allowed):
        if any(type(code) is not int or code not in allowed for code in (self.toggle, self.stop)):
            raise ValueError("両方のショートカット入力を選んでください。")
        if self.toggle == self.stop:
            raise ValueError("有効・停止の切り替えとシーケンス停止には、別々の入力を選んでください。")

    def validate_bindings(self, bindings, button_label):
        for binding in bindings:
            if self.contains(binding.trigger):
                raise ValueError(f"「{button_label(binding.trigger)}」はショートカットと割り当て元の両方に指定できません。")


def example(layer, trigger, codes):
    return Binding(layer, trigger, "Sequence", repeat=True, steps=(
        Step(HOLD, codes["KEY_W"], 1000),
        Step(TAP, codes["KEY_SPACE"]),
        Step(WAIT, milliseconds=500),
        Step(HOLD, codes["KEY_S"], 1000),
    ))


def validate(bindings, allowed):
    sources = set()
    for binding in bindings:
        trigger = (binding.layer, binding.trigger)
        if (binding.layer not in {NORMAL, SHIFT} or type(binding.trigger) is not int
                or binding.trigger not in allowed
                or type(binding.repeat) is not bool):
            raise ValueError("割り当て元が不正です。")
        if trigger in sources:
            raise ValueError("同じレイヤーに同じ入力が割り当てられています。")
        sources.add(trigger)
        if binding.behavior == "Shift" and binding.trigger in WHEEL_CODES:
            raise ValueError("ホイールはSKキーに指定できません。")
        if binding.behavior == "Shift" and binding.layer == NORMAL:
            continue
        if binding.behavior == "Remap" and type(binding.output) is int and binding.output in allowed:
            continue
        if binding.behavior != "Sequence":
            raise ValueError("動作または変換先の入力が不正です。")
        if not binding.steps:
            raise ValueError("シーケンスにステップを追加してください。")
        held = set()
        for step in binding.steps:
            validate_step(step, allowed)
            operation = step.operation
            if operation in BUTTON_ACTIONS:
                if operation == UP:
                    if step.button not in held:
                        raise ValueError("解放の前に対応する押下が必要です。")
                    held.remove(step.button)
                elif step.button in held:
                    raise ValueError("押下中の入力を再び指定しています。")
                elif operation == DOWN:
                    held.add(step.button)
        if held:
            raise ValueError("押下した入力には対応する解放を追加してください。")


def validate_step(step, allowed):
    operation = step.operation
    if operation in BUTTON_ACTIONS and (type(step.button) is not int or step.button not in allowed):
        raise ValueError("ステップの入力が不正です。")
    if operation in BUTTON_ACTIONS and step.button in WHEEL_CODES and operation != TAP:
        raise ValueError("ホイールは「押して離す」で指定してください。")
    if operation in TIME_ACTIONS and (type(step.milliseconds) is not int or not 1 <= step.milliseconds <= 3_600_000):
        raise ValueError("時間は1～3,600,000 msです。")
    if operation in VALUE_ACTIONS:
        if not isinstance(step.value, str) or not (step.value if operation == TEXT else step.value.strip()):
            raise ValueError("文字またはコマンドを入力してください。")
    if operation not in BUTTON_ACTIONS | TIME_ACTIONS | VALUE_ACTIONS:
        raise ValueError("未対応のステップです。")


def encode_steps(steps):
    return CLIPBOARD_HEADER + "\n" + json.dumps([asdict(step) for step in steps], ensure_ascii=False)


def decode_steps(text, allowed):
    prefix, _, payload = (text or "").partition("\n")
    if prefix.rstrip("\r") != CLIPBOARD_HEADER:
        raise ValueError("コピーしたシーケンスのステップが見つかりません。")
    items = json.loads(payload)
    if not isinstance(items, list) or not items:
        raise ValueError("貼り付けるステップがありません。")
    steps = [Step(**item) for item in items]
    for step in steps:
        validate_step(step, allowed)
    return steps


def config_home():
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


class BindingStore:
    def __init__(self, path, allowed):
        self.path = path
        self.shortcuts_path = path.with_name("shortcuts.json")
        self.allowed = allowed

    def load_shortcuts(self):
        try:
            with self.shortcuts_path.open(encoding="utf-8") as source:
                shortcuts = ShortcutKeys(**json.load(source))
        except FileNotFoundError:
            return ShortcutKeys()
        shortcuts.validate(self.allowed)
        return shortcuts

    def save_shortcuts(self, shortcuts):
        shortcuts.validate(self.allowed)
        save_file(self.shortcuts_path, (json.dumps(asdict(shortcuts), indent=2) + "\n").encode("utf-8"))

    def load(self):
        try:
            with self.path.open(encoding="utf-8") as source:
                data = json.load(source)
        except FileNotFoundError:
            return []
        bindings = decode_bindings(data)
        validate(bindings, self.allowed)
        return bindings

    def load_exchange(self, path, codes):
        data = read_exchange(path)
        excluded = 0
        if isinstance(data, dict):
            bindings, excluded = decode_portable(data, codes, self.allowed)
        elif data and all(isinstance(item, dict) and "Trigger" in item for item in data):
            compatible = [item for item in data if not windows_has_commands(item)]
            excluded = len(data) - len(compatible)
            bindings = convert_windows(compatible, codes)
        else:
            bindings = decode_bindings(data)
        validate(bindings, self.allowed)
        return bindings, excluded

    def save_exchange(self, path, bindings, codes, include_commands=False):
        if path.resolve() in {self.path.resolve(), self.shortcuts_path.resolve()}:
            raise ValueError("設定の保存先とは別のファイルを選んでください。")
        shared = bindings if include_commands else [binding for binding in bindings if not has_commands(binding)]
        validate(shared, self.allowed)
        data = encode_portable(shared, codes, self.allowed)
        contents = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if len(contents) > MAX_EXCHANGE_BYTES:
            raise ValueError("エクスポートできる設定ファイルは4 MiBまでです。")
        save_file(path, contents)

    def save(self, bindings):
        validate(bindings, self.allowed)
        save_file(self.path, encode_bindings(bindings))


def decode_bindings(data):
    if not isinstance(data, list):
        raise ValueError("設定ファイルは割り当ての配列である必要があります。")
    return [Binding(**dict(item, steps=tuple(Step(**step) for step in item.get("steps", []))))
            for item in data]


def encode_bindings(bindings):
    return (json.dumps([asdict(binding) for binding in bindings], ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def save_file(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, delete=False) as target:
        temporary = Path(target.name)
        try:
            target.write(contents)
            target.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def read_exchange(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("通常のJSONファイルを選んでください。")
        contents = source.read(MAX_EXCHANGE_BYTES + 1)
    if len(contents) > MAX_EXCHANGE_BYTES:
        raise ValueError("設定ファイルは4 MiBまで読み込めます。")
    data = json.loads(contents.decode("utf-8-sig"))
    if not isinstance(data, (dict, list)):
        raise ValueError("設定ファイルの形式が不正です。")
    return data


def portable_buttons(codes, allowed):
    native = {"mouse." + name: codes[f"BTN_{name.upper()}"]
              for name in ("left", "right", "middle", "side", "extra", "forward", "back", "task")
              if f"BTN_{name.upper()}" in codes}
    native.update({"mouse.wheel-up": WHEEL_UP, "mouse.wheel-down": WHEEL_DOWN})
    # Prefer these shared names on export while accepting the existing evdev names on import.
    native.update({token: codes[name] for token, name in
                   (("key.ime-on", "KEY_HANGEUL"), ("key.ime-off", "KEY_HANJA")) if name in codes})
    native.update({"key." + name[4:].lower().replace("_", "-"): code
                   for name, code in sorted(codes.items()) if name.startswith("KEY_") and code in allowed
                   and name not in {"KEY_RESERVED", "KEY_UNKNOWN", "KEY_CNT", "KEY_MAX", "KEY_MIN_INTERESTING"}})
    return {token: code for token, code in native.items() if code in allowed}


def encode_portable(bindings, codes, allowed):
    portable = {code: token for token, code in reversed(tuple(portable_buttons(codes, allowed).items()))}

    def button(code):
        if code not in portable:
            raise ValueError(f"入力 {code} を共有形式に変換できません。")
        return portable[code]

    records = []
    for binding in bindings:
        record = dict(layer=binding.layer, trigger=button(binding.trigger), behavior=binding.behavior,
                      repeat=binding.repeat, steps=[])
        if binding.behavior == "Remap":
            record["output"] = button(binding.output)
        if binding.behavior == "Sequence":
            for step in binding.steps:
                item = dict(operation=step.operation, milliseconds=step.milliseconds)
                if step.operation in BUTTON_ACTIONS:
                    item["button"] = button(step.button)
                if step.operation in VALUE_ACTIONS:
                    item["value"] = step.value
                if step.operation == COMMAND:
                    item["shell"] = "sh"
                record["steps"].append(item)
        records.append(record)
    return {"format": "kitajimacro", "version": 1, "bindings": records}


def decode_portable(data, codes, allowed):
    if data.get("format") != "kitajimacro" or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("対応しているKitajimacro共有形式ではありません。")
    if not isinstance(data.get("bindings"), list):
        raise ValueError("割り当ての形式が不正です。")
    native = portable_buttons(codes, allowed)

    def button(token):
        if token not in native:
            raise ValueError(f"「{token}」はUbuntu版で取り込めません。")
        return native[token]

    records = []
    excluded = 0
    for item in data["bindings"]:
        commands = [step for step in item["steps"] if step["operation"] == COMMAND]
        if any(step.get("shell") not in {"cmd", "sh"} for step in commands):
            raise ValueError("コマンドの実行環境が不正です。")
        if any(step["shell"] != "sh" for step in commands):
            excluded += 1
            continue
        steps = tuple(Step(step["operation"],
                           button(step["button"]) if step["operation"] in BUTTON_ACTIONS else 0,
                           step.get("milliseconds", 0), step.get("value", "")) for step in item["steps"])
        records.append(Binding(item["layer"], button(item["trigger"]), item["behavior"],
                               button(item["output"]) if item["behavior"] == "Remap" else 0,
                               item["repeat"], steps))
    return records, excluded


def has_commands(binding):
    return binding.behavior == "Sequence" and any(step.operation == COMMAND for step in binding.steps)


def windows_has_commands(item):
    return item["Behavior"] == "Sequence" and any(step["Operation"] == COMMAND for step in item["Steps"])


def windows_buttons(codes):
    names = {
        0x08: "BACKSPACE", 0x09: "TAB", 0x0C: "CLEAR", 0x0D: "ENTER", 0x10D: "KPENTER",
        0x13: "PAUSE", 0x14: "CAPSLOCK", 0x16: "HANGEUL", 0x1A: "HANJA",
        0x1B: "ESC", 0x1C: "HENKAN", 0x1D: "MUHENKAN",
        0x20: "SPACE", 0x21: "PAGEUP", 0x22: "PAGEDOWN", 0x23: "END", 0x24: "HOME",
        0x25: "LEFT", 0x26: "UP", 0x27: "RIGHT", 0x28: "DOWN", 0x2C: "SYSRQ",
        0x2D: "INSERT", 0x2E: "DELETE", 0x5B: "LEFTMETA", 0x5C: "RIGHTMETA", 0x5D: "COMPOSE",
        0x6A: "KPASTERISK", 0x6B: "KPPLUS", 0x6C: "KPCOMMA", 0x6D: "KPMINUS",
        0x6E: "KPDOT", 0x6F: "KPSLASH", 0x90: "NUMLOCK", 0x91: "SCROLLLOCK",
        0xA0: "LEFTSHIFT", 0xA1: "RIGHTSHIFT", 0xA2: "LEFTCTRL", 0xA3: "RIGHTCTRL",
        0xA4: "LEFTALT", 0xA5: "RIGHTALT", 0xA6: "BACK", 0xA7: "FORWARD",
        0xAD: "MUTE", 0xAE: "VOLUMEDOWN", 0xAF: "VOLUMEUP", 0xB0: "NEXTSONG",
        0xB1: "PREVIOUSSONG", 0xB2: "STOPCD", 0xB3: "PLAYPAUSE",
    }
    names.update({i: chr(i) for i in (*range(0x30, 0x3A), *range(0x41, 0x5B))})
    names.update({0x60 + i: f"KP{i}" for i in range(10)})
    names.update({0x6F + i: f"F{i}" for i in range(1, 25)})
    return {vk: codes[f"KEY_{name}"] for vk, name in names.items() if f"KEY_{name}" in codes}


def convert_windows(data, codes):
    """Translate portable Windows VKs; report layout-dependent or OS-dependent steps."""
    keyboard = windows_buttons(codes)
    mouse = tuple(codes[f"BTN_{name}"] for name in ("LEFT", "RIGHT", "MIDDLE", "SIDE", "EXTRA"))
    mouse += (WHEEL_UP, WHEEL_DOWN)

    def button(item):
        device, code = item["Device"], item["Code"]
        if device == "Keyboard" and code in keyboard:
            return keyboard[code]
        if device == "Mouse" and 1 <= code <= len(mouse):
            return mouse[code - 1]
        raise ValueError(f"{device} {code:#x} は自動変換できません。Ubuntuの画面で割り当て直してください。")

    bindings = []
    for item in data:
        behavior = item["Behavior"]
        steps = []
        if behavior == "Sequence":
            for step in item["Steps"]:
                op = step["Operation"]
                if op == COMMAND:
                    raise ValueError("Windows用のコマンドは自動変換できません。Ubuntuの画面で作成してください。")
                steps.append(Step(op, button(step["Button"]) if op in BUTTON_ACTIONS else 0,
                                  step["Milliseconds"], step["Value"]))
        bindings.append(Binding(item["Layer"], button(item["Trigger"]), behavior,
                                button(item["Output"]) if behavior == "Remap" else 0, item["Repeat"], tuple(steps)))
    return bindings
