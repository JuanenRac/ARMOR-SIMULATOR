"""Corners of the faults, the node shim and the link of the panel to the broker that the other tests do not reach: the faults that make invalid messages (each on the same fixed input),
the exits of the shim command (a driver that fails, the wrong number of readings, a problem found by the check of the node, a good run) and every way the link of the panel to
the broker can be refused, with stand-ins for the broker library. Nothing here opens a socket or runs a program.
Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later."""
import contextlib
import io
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from armor_simulator import faults, node_shim  # noqa: E402
from armor_simulator.panel_sim import PanelLink, PanelLinkError, SimulatedPanel  # noqa: E402

STREAM = [("armor/radar/radar-1/telemetry", {"n": index, "timestamp_ms": 100_000 + index * 1000, "lux": 10.0}) for index in range(6)] + [("armor/radar/radar-1/health", {"ok": True, "timestamp_ms": 106_000})]


class InvalidFaultTests(unittest.TestCase):
    def test_oversized_targets_makes_sixteen_tracks_in_every_nth_telemetry_only(self):
        out = list(faults.oversized_targets(STREAM, 3))
        self.assertEqual([len(payload.get("targets", [])) for _topic, payload in out], [16, 0, 0, 16, 0, 0, 0])
        self.assertEqual([payload["track_id"] for payload in out[0][1]["targets"]], list(range(1, 17)))
        self.assertEqual(out[-1], STREAM[-1], "the health message is not touched")

    def test_no_invalid_fault_changes_anything_when_the_count_is_zero(self):
        for fault in (faults.oversized_targets, faults.corrupt_lux, faults.unknown_field):
            self.assertEqual(list(fault(STREAM, 0)), STREAM, fault.__name__)

    def test_corrupt_lux_and_unknown_field_hit_the_same_messages(self):
        lux = [index for index, (_t, payload) in enumerate(faults.corrupt_lux(STREAM, 2)) if payload.get("lux") == 1e9]
        self.assertEqual(lux, [0, 2, 4])
        marked = [index for index, (_t, payload) in enumerate(faults.unknown_field(STREAM, 2)) if "firmware_debug" in payload]
        self.assertEqual(marked, [0, 2, 4, 6], "every second message of all the topics, health included")

    def test_a_fault_that_looks_at_one_topic_leaves_the_others_and_counts_only_its_own(self):
        only_health = lambda topic: topic.endswith("/health")  # noqa: E731
        out = list(faults.oversized_targets(STREAM, 1, only_health))
        self.assertEqual(out, STREAM, "oversized targets only touches telemetry, whatever the match")

    def test_every_fault_in_the_table_is_deterministic(self):
        for name, fault in faults.FAULTS.items():
            self.assertEqual(list(fault(STREAM, 2, faults.every_topic)), list(fault(STREAM, 2, faults.every_topic)), name)


class ShimCommandTests(unittest.TestCase):
    ARGS = ["--driver", "/bin/driver --x", "--node-id", "radar-1", "--mqtt-url", "mqtt://127.0.0.1:1883"]

    def run_main(self, *extra, messages=None, error=None, publish=3):
        out, err = io.StringIO(), io.StringIO()
        run = mock.Mock(side_effect=error) if error else mock.Mock(return_value=messages if messages is not None else [("armor/radar/radar-1/telemetry", {})] * 12)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.object(node_shim, "run_driver", run), mock.patch.object(node_shim, "publish", return_value=publish):
            code = node_shim.main([*self.ARGS, *extra])
        return code, out.getvalue(), err.getvalue(), run

    def test_a_good_run_says_pass_with_the_number_of_frames_and_messages(self):
        code, out, _err, run = self.run_main("--frames", "12")
        self.assertEqual(code, 0)
        self.assertIn("NODE_SHIM=PASS node=radar-1 frames=12 published=3", out)
        self.assertEqual(run.call_args.args[0], ["/bin/driver", "--x"], "the driver command is split as a shell would, without a shell")

    def test_a_driver_that_fails_exits_with_two_and_says_why_on_the_error_output(self):
        code, out, err, _run = self.run_main(error=node_shim.ShimError("the driver stopped with status 3"))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("node shim: the driver stopped with status 3", err)

    def test_the_wrong_number_of_readings_is_a_failure(self):
        code, _out, err, _run = self.run_main("--frames", "12", messages=[("armor/radar/radar-1/telemetry", {})] * 5)
        self.assertEqual(code, 2)
        self.assertIn("12 rounds went in and 5 messages with the readings came out", err)

    def test_a_problem_found_by_the_check_of_the_node_is_a_failure_and_nothing_is_published(self):
        replaced = dict(node_shim.NODES)
        replaced["radar"] = node_shim.NodeShim(*[getattr(node_shim.NODES["radar"], field) for field in node_shim.NodeShim.__dataclass_fields__ if field != "verify"], verify=lambda _messages: "a track left its box") if hasattr(node_shim.NodeShim, "__dataclass_fields__") else node_shim.NODES["radar"]
        if not hasattr(node_shim.NodeShim, "__dataclass_fields__"):
            self.skipTest("the node description is not a dataclass")
        with mock.patch.dict(node_shim.NODES, replaced, clear=True):
            code, _out, err, _run = self.run_main("--frames", "12")
        self.assertEqual(code, 2)
        self.assertIn("a track left its box", err)

    def test_each_kind_of_node_builds_its_own_lines(self):
        for node in ("solar", "hmi", "alarm", "meter"):
            if node not in node_shim.NODES:
                continue
            with self.subTest(node=node):
                code, _out, _err, run = self.run_main("--node", node, "--frames", "3", messages=[])
                self.assertEqual(code, 2, "an empty answer cannot match the rounds that went in")
                self.assertEqual(run.call_args.kwargs.get("node"), node)


class FakeClient:
    """A stand-in for the MQTT client of the broker library that records what the panel does with it."""

    def __init__(self, behaviour):
        self.behaviour, self.published, self.subscribed, self.stopped, self.disconnected, self.credentials = behaviour, [], [], False, False, None
        self.on_connect = self.on_message = None

    def username_pw_set(self, user, password):
        self.credentials = (user, password)

    def connect(self, host, port, keepalive=30):
        self.address = (host, port)
        if self.behaviour == "unreachable":
            raise OSError("no route to host")

    def loop_start(self):
        if self.behaviour == "accept":
            self.on_connect(self, None, None, types.SimpleNamespace(is_failure=False))
        elif self.behaviour == "refuse":
            self.on_connect(self, None, None, types.SimpleNamespace(is_failure=True, __str__=lambda _s: "Not authorized"))

    def subscribe(self, topic, qos=0):
        self.subscribed.append(topic)

    def publish(self, topic, payload, qos=0):
        self.published.append((topic, payload))

    def loop_stop(self):
        self.stopped = True

    def disconnect(self):
        self.disconnected = True


def fake_paho(behaviour):
    client = FakeClient(behaviour)
    module = types.ModuleType("paho.mqtt.client")
    module.Client = lambda *args, **kwargs: client
    module.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)
    package = types.ModuleType("paho.mqtt")
    package.client = module
    root = types.ModuleType("paho")
    root.mqtt = package
    return client, {"paho": root, "paho.mqtt": package, "paho.mqtt.client": module}


class PanelLinkRefusalTests(unittest.TestCase):
    def link(self, url="mqtt://broker.lan:1884", **options):
        return PanelLink(SimulatedPanel("alarm-1"), url, every_s=0.01, **options)

    def test_a_missing_library_is_told_with_what_to_install(self):
        with mock.patch.dict(sys.modules, {"paho": None, "paho.mqtt": None, "paho.mqtt.client": None}):
            with self.assertRaisesRegex(PanelLinkError, "pip install paho-mqtt"):
                self.link().start()

    def test_an_address_that_is_not_a_broker_address_is_refused_before_connecting(self):
        client, modules = fake_paho("accept")
        with mock.patch.dict(sys.modules, modules):
            for bad in ("http://broker.lan", "mqtt://", "broker.lan:1883"):
                with self.subTest(url=bad), self.assertRaisesRegex(PanelLinkError, "mqtt://host"):
                    self.link(bad).start()
        self.assertFalse(hasattr(client, "address"))

    def test_a_broker_that_cannot_be_reached_is_told_with_the_reason(self):
        _client, modules = fake_paho("unreachable")
        with mock.patch.dict(sys.modules, modules), self.assertRaisesRegex(PanelLinkError, "could not be reached: no route to host"):
            self.link().start()

    def test_a_broker_that_never_answers_stops_the_loop_and_says_so(self):
        client, modules = fake_paho("silent")
        with mock.patch.dict(sys.modules, modules), self.assertRaisesRegex(PanelLinkError, r"did not accept the panel \(no answer\)"):
            self.link().start(timeout_s=0.05)
        self.assertTrue(client.stopped)

    def test_a_good_connection_subscribes_publishes_the_state_and_stops_cleanly(self):
        client, modules = fake_paho("accept")
        with mock.patch.dict(sys.modules, modules):
            link = self.link(username="panel", password="pw")
            link.start()
            self.assertEqual(client.credentials, ("panel", "pw"))
            self.assertEqual(client.address, ("broker.lan", 1884))
            self.assertEqual(client.subscribed, ["armor/alarm/alarm-1/command"])
            for _ in range(100):
                if client.published:
                    break
                import time
                time.sleep(0.01)
            link.stop()
        self.assertTrue(client.published and client.published[0][0] == "armor/alarm/alarm-1/state")
        self.assertTrue(client.stopped and client.disconnected)

    def test_a_command_is_answered_on_the_result_topic_and_a_damaged_one_is_ignored(self):
        client, modules = fake_paho("accept")
        with mock.patch.dict(sys.modules, modules):
            link = self.link()
            link.start()
            link._stop.set()
            client.published.clear()
            client.on_message(client, None, types.SimpleNamespace(payload=b"{not json"))
            client.on_message(client, None, types.SimpleNamespace(payload=b"[1, 2]"))
            self.assertEqual(client.published, [])
            client.on_message(client, None, types.SimpleNamespace(payload=b'{"kind": "alarm_command", "node_id": "alarm-1", "action": "arm", "mode": "away", "command_id": "c1"}'))
            link.stop()
        self.assertTrue(any(topic == "armor/alarm/alarm-1/result" for topic, _payload in client.published))


if __name__ == "__main__":
    unittest.main()
