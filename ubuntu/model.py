"""Bindings and their on-disk format for the Ubuntu application."""

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

NORMAL = "Normal"
SHIFT = "Shift"
ESC = 1
F12 = 88
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
                or binding.trigger not in allowed or binding.trigger in {ESC, F12}
                or type(binding.repeat) is not bool):
            raise ValueError("割り当て元が不正です。EscとF12は予約されています。")
        if trigger in sources:
            raise ValueError("同じレイヤーに同じ入力が割り当てられています。")
        sources.add(trigger)
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
        self.allowed = allowed

    def load(self):
        try:
            with self.path.open(encoding="utf-8") as source:
                data = json.load(source)
        except FileNotFoundError:
            return []
        if not isinstance(data, list):
            raise ValueError("設定ファイルは割り当ての配列である必要があります。")
        bindings = [Binding(**dict(item, steps=tuple(Step(**step) for step in item.get("steps", []))))
                    for item in data]
        validate(bindings, self.allowed)
        return bindings

    def save(self, bindings):
        validate(bindings, self.allowed)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as target:
            temporary = Path(target.name)
            try:
                json.dump([asdict(binding) for binding in bindings], target, ensure_ascii=False, indent=2)
                target.write("\n")
                target.flush()
                target.close()
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)


def windows_buttons(codes):
    names = {
        0x08: "BACKSPACE", 0x09: "TAB", 0x0C: "CLEAR", 0x0D: "ENTER", 0x10D: "KPENTER",
        0x13: "PAUSE", 0x14: "CAPSLOCK", 0x1B: "ESC", 0x1C: "HENKAN", 0x1D: "MUHENKAN",
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


def import_windows(path, codes):
    """Translate portable Windows VKs; report layout-dependent or OS-dependent steps."""
    with path.open(encoding="utf-8-sig") as source:
        data = json.load(source)
    keyboard = windows_buttons(codes)
    mouse = tuple(codes[f"BTN_{name}"] for name in ("LEFT", "RIGHT", "MIDDLE", "SIDE", "EXTRA"))

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
