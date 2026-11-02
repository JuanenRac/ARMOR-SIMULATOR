"""The other nodes of the simulator: several radars, the information of a node, an alarm panel and a network watcher, the walks of the alarm scenarios and the broker.

The shape of every message is also compared with the vectors of ARMOR-COMMON (the same ones the firmware serialisers are held to), and with the contract when that checkout is next to this one.
"""
import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from armor_simulator import alarm_scenarios, nodes
from armor_simulator.cli import main, messages
from armor_simulator.mqtt_out import MqttOutError, MqttSink, check_broker_url
from armor_simulator.publisher import kind_of
from armor_simulator.scenarios import RELAY_PERIOD, health, scenario_for_node, telemetry
from armor_simulator.solar import battery, inverter, solar_messages

COMMON = ROOT.parent / "ARMOR-COMMON"


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("ARMOR_INGEST_TOKEN", None)
        try:
            code = main(list(args))
        except SystemExit as exit_:
            code = exit_.code
    return code, out.getvalue(), err.getvalue()


def shape(value):
    """Keys and JSON types, recursively (lists by their first element): what a consumer depends on besides the values."""
    if isinstance(value, dict):
        return {key: shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    return "int" if isinstance(value, int) and not isinstance(value, bool) else "number" if isinstance(value, float) else type(value).__name__


class Parity(unittest.TestCase):
    """The simulator says the same fields, with the same types, as the vectors the contract and the firmware are held to."""

    def vectors(self, name):
        path = COMMON / "conformance" / f"{name}.json"
        if not path.is_file():
            self.skipTest("ARMOR-COMMON is not next to this repository")
        return [item["payload"] for item in json.loads(path.read_text(encoding="utf-8"))["vectors"] if item["valid"]]

    def assertSameFields(self, produced, vectors, optional=()):
        """Every field the vectors all have is there, no field is invented, and the types agree (a whole number counts as a number)."""
        needed = set.intersection(*(set(v) for v in vectors)) - set(optional)
        self.assertTrue(needed <= set(produced), f"missing {needed - set(produced)}")
        self.assertAgrees(produced, vectors, "message")

    def assertAgrees(self, value, examples, where):
        if isinstance(value, dict):
            for key, item in value.items():
                found = [e[key] for e in examples if isinstance(e, dict) and key in e]
                self.assertTrue(found, f"{where}.{key} is in no vector")
                self.assertAgrees(item, found, f"{where}.{key}")
        elif isinstance(value, list):
            inner = [x for e in examples if isinstance(e, list) for x in e]
            for item in value:
                if inner:
                    self.assertAgrees(item, inner, f"{where}[]")
        else:
            numbers = (int, float)
            ok = any(isinstance(e, numbers) and not isinstance(e, bool) for e in examples) if isinstance(value, numbers) and not isinstance(value, bool) else any(type(e) is type(value) for e in examples)
            self.assertTrue(ok, f"{where} has another type than the vectors")

    def test_telemetry_health_and_info(self):
        telemetry_vectors = self.vectors("telemetry")
        sample = telemetry("north-1", 3, "two-intruders")
        self.assertTrue(sample["targets"])
        self.assertSameFields(sample, telemetry_vectors)
        track_vectors = [t for v in telemetry_vectors for t in v["targets"]]
        self.assertTrue(track_vectors)
        for track in sample["targets"]:
            self.assertEqual(set(track), set(track_vectors[0]))
            self.assertTrue(all(type(value) is int for value in track.values()), "a track is whole numbers, as the firmware sends them")
        self.assertSameFields(health("north-1", 3), self.vectors("health"))
        self.assertSameFields(nodes.info("north-1", 3), self.vectors("info"))

    def test_alarm_and_network(self):
        self.assertSameFields(nodes.alarm_state("alarm-1", 80), self.vectors("alarm"), optional=("profile", "seq", "sig"))
        self.assertSameFields(nodes.network_state("network-1", 40), self.vectors("network"), optional=("results", "scan"))

    def test_the_contract_accepts_them(self):
        if not (COMMON / "src").is_dir():
            self.skipTest("ARMOR-COMMON is not next to this repository")
        sys.path.insert(0, str(COMMON / "src"))
        from armor_common.contracts import validate_alarm_message, validate_network_message, validate_payload
        for sample in range(0, 240, 3):
            validate_alarm_message("armor/alarm/alarm-1/state", nodes.alarm_state("alarm-1", sample))
            validate_network_message("armor/network/network-1/state", nodes.network_state("network-1", sample))
            validate_payload("info", nodes.info("north-1", sample, "0.8.0.1"))


class Panel(unittest.TestCase):
    def test_walks_its_timeline_and_repeats(self):
        phases = [nodes.alarm_state("alarm-1", s)["phase"] for s in range(nodes.ALARM_PERIOD)]
        self.assertEqual([phases[s] for s in (0, 22, 40, 72, 76, 90)], ["disarmed", "exit_delay", "armed", "entry_delay", "alarm", "disarmed"])
        self.assertTrue(nodes.alarm_state("alarm-1", 78)["siren"])
        self.assertFalse(nodes.alarm_state("alarm-1", 84)["siren"])
        again = nodes.alarm_state("alarm-1", 78 + nodes.ALARM_PERIOD)
        self.assertEqual(nodes.alarm_state("alarm-1", 78) | {"timestamp_ms": 0}, again | {"timestamp_ms": 0})
        self.assertEqual(nodes.alarm_state("alarm-1", 78)["open_zones"], ["window"])

    def test_the_network_gets_a_printer(self):
        self.assertEqual(len(nodes.network_state("n", 10)["devices"]), 2)
        late = nodes.network_state("n", 45)
        self.assertEqual(len(late["devices"]), 3)
        self.assertEqual(late["events"][0]["kind"], "new_device")
        self.assertFalse(late["devices"][1]["online"])


class SeveralNodes(unittest.TestCase):
    def test_relay_hands_the_walker_over(self):
        names = ("a", "b", "c")
        active = [[scenario_for_node("relay", i, 3, s) for i in range(3)] for s in (0, RELAY_PERIOD, 2 * RELAY_PERIOD, 3 * RELAY_PERIOD)]
        self.assertEqual(active[0], ["crossing", "empty", "empty"])
        self.assertEqual(active[1], ["empty", "crossing", "empty"])
        self.assertEqual(active[3], ["crossing", "empty", "empty"])
        self.assertEqual(scenario_for_node("relay", 0, 1, 5), "relay")
        stream = list(messages("x", 2 * RELAY_PERIOD, "relay", "night", 1, 0, nodes=names))
        seen = {n: [bool(p["targets"]) for t, p in stream if t == f"armor/node/{n}/telemetry"] for n in names}
        self.assertTrue(any(seen["a"][:RELAY_PERIOD]) and not any(seen["b"][:RELAY_PERIOD]))
        self.assertTrue(any(seen["b"][RELAY_PERIOD:]) and not any(seen["a"][RELAY_PERIOD:]))

    def test_the_command_line(self):
        code, out, _err = run("--nodes", "north-1,south-1", "--count", "2", "--health-every", "1", "--info", "--alarm-node", "alarm-1", "--network-node", "net-1")
        self.assertEqual(code, 0)
        topics = [json.loads(line)["topic"] for line in out.splitlines()]
        self.assertIn("armor/node/south-1/telemetry", topics)
        self.assertIn("armor/node/south-1/info", topics)
        self.assertEqual(topics.count("armor/alarm/alarm-1/state"), 2)
        self.assertEqual(topics.count("armor/network/net-1/state"), 1)
        self.assertEqual(run("--nodes", "a,a")[0], 2)
        self.assertEqual(run("--nodes", "a", "--node-id", "b")[0], 2)
        self.assertEqual(run("--alarm-node", "Bad Id")[0], 2)
        self.assertEqual(run("--energy", "--info")[0], 2)

    def test_a_plain_run_is_unchanged(self):
        self.assertEqual(list(messages("n", 3, "patrol", "cycle", 0, 2)), list(messages("n", 3, "patrol", "cycle", 0, 2, nodes=("n",))))
        self.assertEqual([t for t, _ in messages("n", 1, "empty", "cycle", 0, 1, True)].count("armor/solar/n/us3000-1/state"), 1)

    def test_routes(self):
        self.assertEqual(kind_of("armor/alarm/a/state"), "alarm")
        self.assertEqual(kind_of("armor/network/n/state"), "network")
        self.assertIsNone(kind_of("armor/node/n/info"))
        self.assertEqual(kind_of("armor/node/n/health"), "health")


class Battery(unittest.TestCase):
    def test_current_is_shared_with_the_inverter(self):
        for sample in (0, 50, 200):
            reading = inverter("n", sample)
            self.assertEqual(battery("n", sample), battery("n", sample, battery_a=reading["battery_a"]))
            self.assertEqual(dict(solar_messages("n", sample))["armor/solar/n/us3000-1/state"], battery("n", sample))


class Walks(unittest.TestCase):
    def scenario(self, **walk):
        base = {"schema": "armor-alarm-scenario/1", "name": "w", "duration_s": 30, "nodes": ["r-1"], "zones": [{"id": "z", "node": "r-1", "sensor_id": 2}],
                "events": [{"type": "walk", "at_s": 2, "node": "r-1", "speed_mm_s": 1000, "points": [{"x_mm": -3000, "y_mm": 3000}, {"x_mm": 3000, "y_mm": 3000}], **walk}]}
        return alarm_scenarios.parse_scenario(base)

    def test_position_along_the_polyline(self):
        points = [(0.0, 0.0), (3000.0, 0.0), (3000.0, 4000.0)]
        self.assertEqual(alarm_scenarios.walk_position(points, 1000.0, 0), (0.0, 0.0))
        self.assertEqual(alarm_scenarios.walk_position(points, 1000.0, 1.5), (1500.0, 0.0))
        self.assertEqual(alarm_scenarios.walk_position(points, 1000.0, 5), (3000.0, 2000.0))
        self.assertEqual(alarm_scenarios.walk_position(points, 1000.0, 99), (3000.0, 4000.0))

    def test_tracks_follow_the_speed(self):
        stream = list(alarm_scenarios.build_stream(self.scenario(), 0))
        x = {p["timestamp_ms"] // 1000: p["targets"][0]["x_mm"] for t, p in stream if t.endswith("/telemetry") and p["targets"]}
        self.assertEqual(x[2], -3000)
        self.assertEqual(x[3], -2000)
        self.assertEqual(x[8], 3000)
        self.assertNotIn(1, x)
        self.assertNotIn(10, x)
        first = next(p for t, p in stream if t.endswith("/telemetry") and p["timestamp_ms"] == 3000)["targets"][0]
        self.assertLess(first["speed_mm_s"], 0)      # coming closer to the sensor at first

    def test_refused_files(self):
        cases = (({"speed_mm_s": 10}, "speed_mm_s"), ({"speed_mm_s": 4000}, "speed_mm_s"), ({"points": [{"x_mm": 0, "y_mm": 1}]}, "two points"),
                 ({"node": "other"}, "not in nodes"), ({"at_s": 29}, "ends after"), ({"points": [{"x_mm": 1, "y_mm": 1}, {"x_mm": 1, "y_mm": 1}]}, "does not move"),
                 ({"points": [{"x_mm": 99999, "y_mm": 1}, {"x_mm": 1, "y_mm": 1}]}, "x_mm"), ({"colour": 1}, "colour"))
        for walk, text in cases:
            with self.assertRaises(alarm_scenarios.ScenarioError, msg=str(walk)) as caught:
                self.scenario(**walk)
            self.assertIn(text, str(caught.exception))

    def test_the_example_is_valid(self):
        scenario = alarm_scenarios.load_scenario(ROOT / "examples" / "alarm" / "walk-across-two-nodes.json")
        self.assertEqual(sum(e["type"] == "walk" for e in scenario.events), 2)


class FakeInfo:
    rc = 0

    def wait_for_publish(self, _timeout):
        return None


class FakeClient:
    instances = []

    def __init__(self, _client_id):
        self.sent, self.login, self.stopped, self.address = [], None, False, None
        FakeClient.instances.append(self)

    def username_pw_set(self, user, password):
        self.login = (user, password)

    def connect(self, host, port, keepalive=30):
        self.address = (host, port)

    def loop_start(self):
        self.on_connect(self, None, None, mock.Mock(is_failure=False))

    def loop_stop(self):
        self.stopped = True

    def disconnect(self):
        pass

    def publish(self, topic, payload, qos=0):
        self.sent.append((topic, json.loads(payload), qos))
        return FakeInfo()


class Broker(unittest.TestCase):
    def test_which_hosts_are_local(self):
        for url in ("mqtt://127.0.0.1", "mqtt://localhost:1884", "mqtt://192.168.0.5", "mqtt://mosquitto", "mqtt://broker.local", "tcp://10.0.0.2:1883"):
            check_broker_url(url)
        for url in ("mqtt://8.8.8.8", "mqtt://broker.example.com"):
            with self.assertRaises(MqttOutError):
                check_broker_url(url)
            self.assertEqual(check_broker_url(url, allow_network=True)[1], 1883)
        for url in ("http://localhost", "mqtt://user:pw@localhost", "mqtt://localhost/topic", "mqtt://localhost:99999", "mqtt://"):
            with self.assertRaises(MqttOutError):
                check_broker_url(url)

    def test_publishes_every_message_with_its_topic(self):
        FakeClient.instances.clear()
        sink = MqttSink("mqtt://127.0.0.1:1884", username="sim", password="pw", client_factory=FakeClient)
        sink.open()
        sink.publish("armor/node/n/health", {"node_id": "n", "timestamp_ms": 0, "online": True})
        sink.close()
        client = FakeClient.instances[0]
        self.assertEqual(client.address, ("127.0.0.1", 1884))
        self.assertEqual(client.login, ("sim", "pw"))
        self.assertEqual(client.sent, [("armor/node/n/health", {"node_id": "n", "timestamp_ms": 0, "online": True}, 1)])
        self.assertEqual(sink.published, 1)
        with self.assertRaises(MqttOutError):
            sink.publish("armor/node/n/health", {})

    def test_the_command_line_publishes(self):
        FakeClient.instances.clear()
        real = MqttSink

        def sink(url, **kw):
            return real(url, client_factory=FakeClient, **kw)

        with mock.patch("armor_simulator.cli.MqttSink", sink):
            code, out, err = run("--count", "2", "--health-every", "1", "--info", "--mqtt-url", "mqtt://127.0.0.1")
        self.assertEqual(code, 0)
        sent = FakeClient.instances[0].sent
        self.assertEqual([t for t, _p, _q in sent], [json.loads(line)["topic"] for line in out.splitlines()])
        self.assertTrue(FakeClient.instances[0].stopped)
        self.assertIn(f"{len(sent)} message(s) published", err)

    def test_a_far_broker_is_refused_without_publishing(self):
        code, out, err = run("--count", "1", "--mqtt-url", "mqtt://8.8.8.8")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("--mqtt-allow-network", err)
        self.assertEqual(run("--count", "1", "--mqtt-allow-network")[0], 2)

    def test_without_paho_it_says_so(self):
        with mock.patch.dict(sys.modules, {"paho": None, "paho.mqtt": None, "paho.mqtt.client": None}):
            code, _out, err = run("--count", "1", "--mqtt-url", "mqtt://127.0.0.1")
        self.assertEqual(code, 2)
        self.assertIn("paho-mqtt", err)


if __name__ == "__main__":
    unittest.main()
