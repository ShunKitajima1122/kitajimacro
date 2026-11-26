import heapq
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from engine import Engine
from model import (COMMAND, DOWN, ESC, F12, HOLD, NORMAL, SHIFT, TAP, TEXT, UP, WAIT, Binding,
                   BindingStore, MAX_EXCHANGE_BYTES, ShortcutKeys, Step, WHEEL_DOWN, WHEEL_UP, decode_steps, encode_steps, example)


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
    clipboard_bridge_delay = 0

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

    def test_wheel_accumulates_and_repeated_notches_each_tap(self):
        engine = self.engine
        engine.replace([Binding(NORMAL, WHEEL_UP, output=30)])
        self.assertFalse(engine.route_wheel("mouse", -120))
        self.assertTrue(engine.route_wheel("mouse", 60))
        self.clock.tick(10)
        self.assertFalse(self.output.events)
        self.assertTrue(engine.route_wheel("mouse", 60))
        self.assertEqual(self.output.events, [(30, True), (30, False)])
        self.assertTrue(engine.route_wheel("mouse", 240))
        self.assertFalse(self.clock.queue)
        self.assertEqual(self.output.events, [(30, True), (30, False)] * 3)
        self.assertFalse(engine.held)

    def test_wheel_can_activate_sk_mapping_and_output_has_no_release(self):
        engine = self.engine
        engine.replace([Binding(NORMAL, 46, "Shift"), Binding(SHIFT, WHEEL_DOWN, output=WHEEL_UP),
                        Binding(NORMAL, 30, output=WHEEL_DOWN)])
        self.assertFalse(engine.route_wheel("mouse", -120))
        engine.route("keys", 46, 1)
        self.assertTrue(engine.route_wheel("mouse", -240))
        engine.route("keys", 46, 0)
        engine.route("keys", 30, 1)
        engine.route("keys", 30, 0)
        self.assertEqual(self.output.events, [(WHEEL_UP, True), (WHEEL_UP, True), (WHEEL_DOWN, True)])
        self.assertFalse(engine.held)

    def test_wheel_tap_does_not_release_an_already_held_key(self):
        engine = self.engine
        engine.replace([Binding(NORMAL, WHEEL_UP, output=48), Binding(NORMAL, 30, output=48)])
        self.assertTrue(engine.route("keys", 30, 1))
        self.assertTrue(engine.route_wheel("mouse", 120))
        self.assertEqual(self.output.events, [(48, True)])
        self.assertTrue(engine.route("keys", 30, 0))
        self.assertEqual(self.output.events, [(48, True), (48, False)])

    def test_wheel_sequence_and_capture(self):
        engine = self.engine
        engine.replace([Binding(NORMAL, WHEEL_UP, "Sequence", steps=(Step("Tap", WHEEL_DOWN),))])
        self.assertTrue(engine.route_wheel("mouse", 120))
        self.clock.tick(0)
        self.assertEqual(self.output.events, [(WHEEL_DOWN, True)])
        captured = []
        engine.begin_capture({WHEEL_DOWN}, captured.append)
        self.assertTrue(engine.route_wheel("mouse", -10, editing=True))
        self.assertEqual(captured, [WHEEL_DOWN])

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

    def test_sequence_taps_send_without_waiting_and_leave_held_outputs_alone(self):
        engine = self.engine
        engine.replace([
            Binding(NORMAL, 31, output=48),
            Binding(NORMAL, 30, "Sequence", steps=(Step(TAP, 48), Step(TAP, 57), Step(TAP, WHEEL_UP),
                                                   Step(WAIT, milliseconds=10), Step(HOLD, 57, 20))),
        ])
        engine.route("keys", 31, 1)
        engine.route("keys", 30, 1)
        self.clock.tick(0)
        self.assertEqual(self.output.events, [(48, True), (57, True), (57, False), (WHEEL_UP, True)])
        self.clock.tick(9)
        self.assertEqual(len(self.output.events), 4)
        self.clock.tick(1)
        self.assertEqual(self.output.events[-1], (57, True))
        self.clock.tick(19)
        self.assertEqual(len(self.output.events), 5)
        self.clock.tick(1)
        engine.route("keys", 31, 0)
        self.assertEqual(self.output.events[-2:], [(57, False), (48, False)])

    def test_counted_sequence_runs_exact_count_after_trigger_release(self):
        engine = self.engine
        engine.replace([Binding(NORMAL, 30, "Sequence", steps=(Step(HOLD, 57, 20),), repeat_count=3)])
        self.assertTrue(engine.route("keys", 30, 1))
        self.assertTrue(engine.route("keys", 30, 0))
        self.clock.tick(250)
        self.assertEqual(self.output.events, [(57, True), (57, False)] * 3)
        self.assertFalse(engine.playing)

    def test_held_sequence_uses_original_press_and_can_restart(self):
        engine = self.engine
        engine.replace([Binding(NORMAL, 275, "Shift"),
                        Binding(SHIFT, 30, "Sequence", steps=(Step(HOLD, 57, 20),), while_held=True)])
        engine.route("mouse", 275, 1)
        engine.route("keys", 30, 1)
        engine.route("mouse", 275, 0)
        engine.route("other-keyboard", 30, 1)
        engine.route("other-keyboard", 30, 0)
        self.clock.tick(35)
        self.assertEqual(self.output.events, [(57, True), (57, False), (57, True)])
        self.assertTrue(engine.route("keys", 30, 0))
        self.clock.tick(200)
        self.assertEqual(self.output.events, [(57, True), (57, False)] * 2)
        self.assertFalse(engine.playing)
        engine.route("mouse", 275, 1)
        engine.route("keys", 30, 1)
        self.clock.tick(1)
        engine.route("keys", ESC, 1)
        self.clock.tick(200)
        self.assertEqual(self.output.events, [(57, True), (57, False)] * 3)
        self.assertFalse(engine.playing)

    def test_custom_shortcuts_toggle_and_stop_without_reserving_defaults(self):
        engine = self.engine
        engine.set_shortcuts(ShortcutKeys(87, 276))
        engine.replace([Binding(NORMAL, F12, output=48),
                        Binding(NORMAL, ESC, "Sequence", repeat=True, steps=(Step(HOLD, 57, 200),))])
        self.assertTrue(engine.route("keys", 87, 1))
        self.assertTrue(engine.route("keys", 87, 2))
        self.assertFalse(engine.enabled)
        self.assertTrue(engine.route("keys", 87, 0))
        self.assertTrue(engine.route("keys", 87, 1))
        self.assertTrue(engine.enabled)
        self.assertTrue(engine.route("keys", F12, 1))
        self.assertTrue(engine.route("keys", F12, 0))
        self.assertTrue(engine.route("keys", ESC, 1))
        self.clock.tick(50)
        self.assertEqual(self.output.events, [(48, True), (48, False), (57, True)])
        self.assertFalse(engine.route("mouse", 276, 1, mouse=True))
        self.assertFalse(engine.route("mouse", 276, 0, mouse=True))
        self.clock.tick(500)
        self.assertEqual(self.output.events[-1], (57, False))
        self.assertFalse(engine.playing)
        self.assertTrue(engine.enabled)

    def test_custom_wheel_shortcut_accumulates_partial_scroll(self):
        engine = self.engine
        engine.set_shortcuts(ShortcutKeys(WHEEL_UP, WHEEL_DOWN))
        self.assertFalse(engine.route_wheel("mouse", 60))
        self.assertTrue(engine.enabled)
        self.assertFalse(engine.route_wheel("mouse", 60))
        self.assertFalse(engine.enabled)
        self.assertFalse(engine.route_wheel("mouse", 120))
        self.assertTrue(engine.enabled)

    def test_command_notification_resumes_and_cancellation_unregisters(self):
        notifications = []

        def watch(process, timeout, callback):
            notifications.append(callback)
            return lambda: notifications.remove(callback)

        engine = self.engine
        engine.watch_job = watch
        engine.replace([Binding(NORMAL, 30, "Sequence",
                                steps=(Step(COMMAND, value=":"), Step(TAP, 57)))])
        engine.route("keys", 30, 1)
        engine.route("keys", 30, 0)
        self.clock.tick(1)
        self.assertEqual(len(notifications), 1)
        self.assertFalse(self.output.events)
        self.output.result = 0
        notifications.pop()()
        self.assertEqual(self.output.events, [(57, True), (57, False)])

        self.output.result = None
        engine.route("keys", 30, 1)
        self.clock.tick(0)
        self.assertEqual(len(notifications), 1)
        engine.route("keys", ESC, 1)
        self.assertFalse(notifications)
        self.assertEqual(self.output.finished, [COMMAND, COMMAND])

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

    def test_capture_precedes_remap_and_reserves_escape(self):
        engine = self.engine
        results = []
        engine.replace([Binding(NORMAL, 30, output=48)])
        engine.begin_capture({30, 276}, results.append)
        self.assertTrue(engine.route("mouse", 276, 1, editing=True))
        self.assertTrue(engine.route("mouse", 276, 0))
        self.assertEqual(results, [276])
        self.assertFalse(self.output.events)
        engine.begin_capture({30}, results.append)
        self.assertTrue(engine.route("keys", F12, 1, editing=True))
        self.assertTrue(engine.enabled)
        self.assertTrue(engine.route("keys", F12, 0))
        self.assertTrue(engine.route("keys", ESC, 1, editing=True))
        self.assertEqual(results, [276, None])
        self.assertTrue(engine.route("keys", ESC, 0))

    def test_clipboard_preserves_order_and_allows_partial_chords(self):
        steps = [Step(UP, 29), Step(TEXT, value="行1\n行2"), Step(HOLD, 30, 1234)]
        encoded = encode_steps(steps)
        self.assertEqual(decode_steps(encoded, {29, 30}), steps)
        with self.assertRaises(ValueError):
            decode_steps(encoded, {30})
        with self.assertRaises(ValueError):
            decode_steps("external text", {29, 30})

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
            self.assertEqual(store.load_exchange(path, codes), ([Binding(NORMAL, 30, output=48)], 0))


class SharingTests(unittest.TestCase):
    def test_shortcuts_are_local_and_reject_conflicting_bindings(self):
        with tempfile.TemporaryDirectory() as folder:
            store = BindingStore(Path(folder) / "bindings.json", {ESC, F12, 30, 48, 57})
            self.assertEqual(store.load_shortcuts(), ShortcutKeys())
            shortcuts = ShortcutKeys(30, 48)
            store.save_shortcuts(shortcuts)
            with self.assertRaises(ValueError):
                store.save_shortcuts(ShortcutKeys(57, 57))
            self.assertEqual(store.load_shortcuts(), shortcuts)

            conflict = Binding(SHIFT, 30, output=57)
            with self.assertRaises(ValueError):
                shortcuts.validate_bindings([conflict], str)
            regular = Binding(NORMAL, ESC, output=57)
            shortcuts.validate_bindings([regular], str)
            exchange = Path(folder) / "portable.json"
            codes = {"KEY_ESC": ESC, "KEY_SPACE": 57}
            store.save_exchange(exchange, [regular], codes)
            self.assertEqual(set(json.loads(exchange.read_text())), {"format", "version", "bindings"})
            self.assertEqual(store.load_exchange(exchange, codes), ([regular], 0))

    def test_repeat_modes_save_and_round_trip_with_version_two(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "portable.json"
            codes = {"KEY_A": 30, "KEY_B": 48, "KEY_SPACE": 57}
            store = BindingStore(Path(folder) / "bindings.json", set(codes.values()) | {WHEEL_UP})
            steps = (Step(HOLD, 57, 20),)
            held = Binding(NORMAL, 30, "Sequence", steps=steps, while_held=True)
            count = Binding(NORMAL, 48, "Sequence", steps=steps, repeat_count=4)
            store.save([held, count])
            self.assertEqual(store.load(), [held, count])
            store.save_exchange(path, [held, count], codes)
            exported = json.loads(path.read_text())
            self.assertEqual(exported["version"], 2)
            self.assertEqual(store.load_exchange(path, codes), ([held, count], 0))
            exported["version"] = 1
            path.write_text(json.dumps(exported))
            with self.assertRaises(ValueError):
                store.load_exchange(path, codes)
            with self.assertRaises(ValueError):
                store.save([Binding(NORMAL, WHEEL_UP, "Sequence", steps=steps, while_held=True)])

    def test_ime_keys_export_shared_names_and_import_existing_names(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "portable.json"
            codes = {"KEY_HANGEUL": 122, "KEY_HANGUEL": 122, "KEY_HANJA": 123}
            store = BindingStore(Path(folder) / "bindings.json", set(codes.values()))
            bindings = [Binding(NORMAL, 122, output=123)]
            store.save_exchange(path, bindings, codes)
            exported = path.read_text(encoding="utf-8")
            record = json.loads(exported)["bindings"][0]
            self.assertEqual((record["trigger"], record["output"]), ("key.ime-on", "key.ime-off"))
            self.assertEqual(store.load_exchange(path, codes), (bindings, 0))
            path.write_text(exported.replace("key.ime-on", "key.hangeul").replace("key.ime-off", "key.hanja"),
                            encoding="utf-8")
            self.assertEqual(store.load_exchange(path, codes), (bindings, 0))

    def test_export_is_safe_by_default_and_full_backup_is_optional(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "portable.json"
            store = BindingStore(Path(folder) / "local.json", {30, 48, 57})
            regular = Binding(NORMAL, 30, output=57)
            command = Binding(NORMAL, 48, "Sequence", steps=(Step(COMMAND, value="printf audit"),))
            codes = {"KEY_A": 30, "KEY_B": 48, "KEY_SPACE": 57}
            store.save_exchange(destination, [regular, command], codes)
            self.assertEqual(json.loads(destination.read_text())["bindings"][0]["trigger"], "key.a")
            self.assertEqual(store.load_exchange(destination, codes), ([regular], 0))
            self.assertNotIn("printf audit", destination.read_text(encoding="utf-8"))
            store.save_exchange(destination, [regular, command], codes, include_commands=True)
            self.assertEqual(store.load_exchange(destination, codes), ([regular, command], 0))
            with self.assertRaises(ValueError):
                store.save_exchange(store.path, [regular], codes)

    def test_windows_commands_are_omitted_as_whole_bindings(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "windows.json"
            store = BindingStore(Path(folder) / "local.json", {30, 48})
            safe = {"Layer": "Normal", "Trigger": {"Device": "Keyboard", "Code": 0x41},
                    "Behavior": "Remap", "Output": {"Device": "Keyboard", "Code": 0x42}, "Repeat": False}
            command = {"Trigger": {"Device": "Keyboard", "Code": 0x43}, "Behavior": "Sequence",
                       "Steps": [{"Operation": "Command", "Value": "echo audit"}]}
            destination.write_text(json.dumps([safe, command]), encoding="utf-8")
            codes = {"KEY_A": 30, "KEY_B": 48}
            codes.update({f"BTN_{name}": i for i, name in enumerate(("LEFT", "RIGHT", "MIDDLE", "SIDE", "EXTRA"), 272)})
            self.assertEqual(store.load_exchange(destination, codes), ([Binding(NORMAL, 30, output=48)], 1))

    def test_import_checks_shape_and_size(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "exchange.json"
            store = BindingStore(Path(folder) / "local.json", {30, 48})
            with path.open("wb") as target:
                target.truncate(MAX_EXCHANGE_BYTES + 1)
            with self.assertRaises(ValueError):
                store.load_exchange(path, {})
            path.write_text(json.dumps({"bindings": []}))
            with self.assertRaises(ValueError):
                store.load_exchange(path, {})


if __name__ == "__main__":
    unittest.main()
