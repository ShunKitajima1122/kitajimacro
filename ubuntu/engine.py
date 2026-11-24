"""Platform-independent routing and asynchronous sequence playback."""

from collections import Counter
from dataclasses import dataclass
from time import monotonic

from model import COMMAND, DOWN, ESC, F12, HOLD, NORMAL, SHIFT, TAP, TEXT, UP, WAIT


@dataclass
class Press:
    blocked: bool
    output: int = 0


class Playback:
    def __init__(self, engine, key, binding, source):
        self.engine = engine
        self.key = key
        self.source = source
        self.script = engine.actions(binding)
        self.timer = engine.schedule(0, self.advance)

    def advance(self):
        self.timer = None
        try:
            self.timer = self.engine.schedule(next(self.script), self.advance)
        except StopIteration:
            self.stop()
        except Exception as error:
            self.stop()
            self.engine.report(str(error))

    def stop(self):
        if self.timer is not None:
            self.engine.cancel(self.timer)
            self.timer = None
        self.engine.playing.pop(self.key, None)
        self.script.close()


class Engine:
    def __init__(self, output, schedule, cancel, changed, report):
        self.output = output
        self.schedule = schedule
        self.cancel = cancel
        self.changed = changed
        self.report = report
        self.enabled = False
        self.bindings = {}
        self.pressed = {}
        self.shift = set()
        self.playing = {}
        self.held = Counter()
        self.capture = None

    def replace(self, bindings):
        self.stop(remaps=True)
        self.bindings = {(item.layer, item.trigger): item for item in bindings}

    def toggle(self):
        self.enabled = not self.enabled
        if not self.enabled:
            self.stop(remaps=True)
        self.changed()

    def begin_capture(self, allowed, complete):
        self.capture = (allowed, complete)

    def end_capture(self, complete):
        if self.capture is not None and self.capture[1] is complete:
            self.capture = None

    def capture_input(self, code):
        if self.capture is None:
            return False
        allowed, complete = self.capture
        if code == ESC or code in allowed:
            self.capture = None
            complete(None if code == ESC else code)
        return True

    def route(self, source, code, value, editing=False):
        """Return true when the original key event must not be forwarded."""
        physical = (source, code)
        if value == 0:
            return self.release(physical)
        if physical in self.pressed:
            press = self.pressed[physical]
            if value == 2 and press.output:
                self.output.repeat(press.output)
            return press.blocked
        if value != 1:
            return False
        if editing and self.capture is not None:
            self.pressed[physical] = Press(True)
            return self.capture_input(code)
        if code == F12:
            self.pressed[physical] = Press(True)
            self.toggle()
            return True
        if code == ESC:
            self.stop()
        normal = self.bindings.get((NORMAL, code))
        if not self.enabled or editing:
            binding = None
        elif normal is not None and normal.behavior == "Shift":
            binding = normal
        else:
            binding = self.bindings.get((SHIFT, code)) if self.shift else normal
        press = self.pressed[physical] = Press(binding is not None)
        if binding is None:
            return False

        if binding.behavior == "Shift":
            self.shift.add(physical)
            self.changed()
        elif binding.behavior == "Remap":
            try:
                self.change_output(binding.output, True)
                press.output = binding.output
            except OSError as error:
                press.blocked = False
                self.report(str(error))
                return False
        else:
            key = (binding.layer, binding.trigger)
            if key not in self.playing:
                self.playing[key] = Playback(self, key, binding, source)
        return True

    def release(self, physical):
        press = self.pressed.pop(physical, None)
        if physical in self.shift:
            self.shift.remove(physical)
            self.changed()
        if press is not None and press.output:
            self.release_output(press.output)
        return press is not None and press.blocked

    def track_passthrough(self, source, active):
        for code in active:
            self.pressed[(source, code)] = Press(False)

    def detach(self, source):
        for playback in tuple(self.playing.values()):
            if playback.source == source:
                playback.stop()
        for physical in tuple(self.pressed):
            if physical[0] == source:
                self.release(physical)

    def stop(self, remaps=False):
        for playback in tuple(self.playing.values()):
            playback.stop()
        if remaps:
            self.shift.clear()
            for press in self.pressed.values():
                if press.output:
                    self.release_output(press.output)
                    press.output = 0
            self.changed()

    def change_output(self, code, down):
        count = self.held[code]
        if down:
            if count == 0:
                self.output.send(code, True)
            self.held[code] = count + 1
        elif count == 1:
            del self.held[code]
            self.output.send(code, False)
        elif count > 1:
            self.held[code] = count - 1

    def release_output(self, code):
        try:
            self.change_output(code, False)
        except OSError as error:
            self.report(str(error))

    def actions(self, binding):
        own = []

        def down(code):
            self.change_output(code, True)
            own.append(code)

        def up(code):
            own.remove(code)
            self.release_output(code)

        try:
            while True:
                for step in binding.steps:
                    operation, code = step.operation, step.button
                    if operation == DOWN:
                        down(code)
                    elif operation == UP:
                        up(code)
                    elif operation in {TAP, HOLD}:
                        down(code)
                        yield 30 if operation == TAP else step.milliseconds
                        up(code)
                    elif operation == WAIT:
                        yield step.milliseconds
                    elif operation in {COMMAND, TEXT}:
                        with self.output.start_job(operation, step.value) as process:
                            deadline = monotonic() + 4 if operation == TEXT else None
                            while (result := process.poll()) is None:
                                if deadline is not None and monotonic() >= deadline:
                                    raise RuntimeError("クリップボードにアクセスできませんでした。")
                                yield 30
                            if result:
                                raise RuntimeError(f"処理 {operation} が終了コード {result} を返しました。")
                        if operation == TEXT:
                            yield 80
                            ctrl, letter = self.output.paste_keys
                            if ctrl not in own:
                                down(ctrl)
                            else:
                                ctrl = None
                            if letter in own:
                                raise RuntimeError("Vキーの解放後に文字入力を指定してください。")
                            down(letter)
                            yield 30
                            up(letter)
                            if ctrl is not None:
                                up(ctrl)
                if not binding.repeat:
                    break
                yield 10
        finally:
            for code in reversed(own):
                self.release_output(code)
