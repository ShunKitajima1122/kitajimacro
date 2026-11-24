import heapq
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from engine import Engine
from model import (COMMAND, DOWN, ESC, F12, HOLD, NORMAL, SHIFT, TEXT, UP, Binding,
                   BindingStore, Step, example, import_windows)


class Clock:
    def __init__(self):
        self.now = 0
        self.count = 0
        self.queue = []
        self.cancelled = set()

    def schedule(self, delay, callback):
        self.count += 1
        heapq.heappush(self.queue, (self.now + delay, self.count, callback))
        return self.count

    def tick(self, delay):
        deadline = self.now + delay
        while self.queue and self.queue[0][0] <= deadline:
            self.now, token, callback = heapq.heappop(self.queue)
            if token not in self.cancelled:
                callback()
        self.now = deadline


class Output:
    paste_keys = (29, 47)

    def __init__(self):
        self.events = []
        self.jobs = []
        self.finished = []
        self.result = None

    def send(self, code, down):
        self.events.append((code, down))

    def repeat(self, code):
        self.events.append((code, "repeat"))

    @contextmanager
    def start_job(self, operation, value):
        self.jobs.append((operation, value))
        try:
            yield self
        finally:
            self.finished.append(operation)

    def poll(self):
        return self.result


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.output = Output()
        self.errors = []
        self.engine = Engine(self.output, self.clock.schedule, self.clock.cancelled.add,
                             lambda: None, self.errors.append)
        self.engine.toggle()

    def test_remap_layer_and_repeat(self):
        engine = self.engine
        engine.replace([Binding(NORMAL, 30, output=48), Binding(SHIFT, 30, output=276),
                        Binding(NORMAL, 275, "Shift")])
        self.assertTrue(engine.route("keys", 30, 1))
        engine.route("keys", 30, 2)
        self.assertTrue(engine.route("mouse", 275, 1))
        self.assertTrue(engine.route("keys", 30, 0))
        self.assertFalse(engine.route("keys", 31, 1))
        self.assertTrue(engine.route("keys", 30, 1))
        engine.detach("mouse")
        self.assertFalse(engine.shift)
        self.assertTrue(engine.route("keys", 30, 0))
        self.assertEqual(self.output.events, [(48, True), (48, "repeat"), (48, False), (276, True), (276, False)])

    def test_press_ownership_while_editing_or_stopping(self):
        e = self.engine
        e.replace([Binding(NORMAL, 30, output=48), Binding(NORMAL, 31, output=48)])
        self.assertFalse(e.route("keys", 30, 1, editing=True))
        self.assertFalse(e.route("keys", 30, 2))
        self.assertFalse(e.route("keys", 30, 0))
        self.assertTrue(e.route("keys", 30, 1))
        self.assertTrue(e.route("keys", 31, 1))
        self.assertTrue(e.route("keys", 30, 0))
        self.assertEqual(self.output.events, [(48, True)])
        self.assertTrue(e.route("keys", F12, 1))
        self.assertFalse(e.enabled)
        self.assertEqual(self.output.events, [(48, True), (48, False)])
        self.assertTrue(e.route("keys", 31, 0))

    def test_example_sequence_and_escape(self):
        e = self.engine
        e.replace([example(NORMAL, 30, {"KEY_W": 17, "KEY_SPACE": 57, "KEY_S": 31})])
        self.assertTrue(e.route("keys", 30, 1))
        self.clock.tick(2550)
        self.assertEqual(self.output.events, [(17, True), (17, False), (57, True), (57, False),
                                              (31, True), (31, False), (17, True)])
        self.assertFalse(e.route("keys", ESC, 1))
        self.clock.tick(5000)
        self.assertEqual(self.output.events[-2:], [(17, True), (17, False)])
        self.assertEqual(len(self.output.events), 8)

    def test_cancel_command_releases_chord(self):
        e = self.engine
        e.replace([Binding(NORMAL, 30, "Sequence", steps=(
            Step(DOWN, 29), Step(COMMAND, value="sleep 5"), Step(UP, 29)))])
        e.route("keys", 30, 1)
        self.clock.tick(1)
        self.assertEqual(self.output.jobs, [(COMMAND, "sleep 5")])
        e.route("keys", ESC, 1)
        self.assertEqual(self.output.finished, [COMMAND])
        self.assertEqual(self.output.events, [(29, True), (29, False)])

    def test_text_uses_paste_shortcut(self):
        e = self.engine
        self.output.result = 0
        e.replace([Binding(NORMAL, 30, "Sequence", steps=(Step(TEXT, value="日本語"),))])
        e.route("keys", 30, 1)
        self.clock.tick(200)
        self.assertEqual(self.output.jobs, [(TEXT, "日本語")])
        self.assertEqual(self.output.events, [(29, True), (47, True), (47, False), (29, False)])

    def test_binding_store_and_windows_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bindings.json"
            store = BindingStore(path, {30, 48, 57})
            item = Binding(NORMAL, 30, "Sequence", steps=(Step(HOLD, 48, 1000),))
            store.save([item])
            self.assertEqual(store.load(), [item])
            with self.assertRaises(ValueError):
                store.save([item, item])
            self.assertEqual(store.load(), [item])
            windows = [{"Layer": "Normal", "Trigger": {"Device": "Keyboard", "Code": 0x41},
                        "Behavior": "Remap", "Output": {"Device": "Keyboard", "Code": 0x42}, "Repeat": False}]
            path.write_text(json.dumps(windows), encoding="utf-8")
            codes = {"KEY_A": 30, "KEY_B": 48}
            codes.update({f"BTN_{name}": i for i, name in enumerate(("LEFT", "RIGHT", "MIDDLE", "SIDE", "EXTRA"), 272)})
            self.assertEqual(import_windows(path, codes), [Binding(NORMAL, 30, output=48)])


if __name__ == "__main__":
    unittest.main()
