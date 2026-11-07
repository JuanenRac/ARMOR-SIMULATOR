"""The MQTT shim: the chunks it plays, the checks on what the driver prints and the publishing, with a stand-in driver and a stand-in broker client (the real driver is built in the CI)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from armor_simulator import node_shim


class FakeClient:
    def __init__(self, client_id):
        self.sent = []
        self.on_connect = None

    def connect(self, host, port, keepalive=30):
        self.host = host

    def loop_start(self):
        self.on_connect(self, None, None, type("Reason", (), {"is_failure": False})(), None)

    def loop_stop(self):
        pass

    def disconnect(self):
        pass

    def publish(self, topic, payload, qos=0):
        self.sent.append((topic, json.loads(payload), qos))
        return type("Info", (), {"rc": 0, "wait_for_publish": lambda self, timeout=None: None})()


def stand_in(body: str) -> list[str]:
    folder = Path(tempfile.mkdtemp())
    script = folder / "driver.py"
    script.write_text(body, encoding="utf-8")
    return [sys.executable, "-I", str(script)]


ECHO = (
    "import sys\n"
    "node = sys.argv[1]\n"
    "for line in sys.stdin:\n"
    "    stamp, lux, hexa = line.split()\n"
    "    print(f'armor/node/{node}/telemetry\t' + '{\"kind\":\"telemetry\",\"node_id\":\"' + node + '\",\"timestamp_ms\":' + stamp + '}')\n"
)


class ShimTests(unittest.TestCase):
    def test_a_clean_stream_is_one_chunk_per_frame(self):
        lines, frames = node_shim.stream_lines(1, 12)
        self.assertEqual((len(lines), frames), (12, 12))
        self.assertTrue(all(len(line.split("\t")) == 3 for line in lines))

    def test_the_driver_messages_are_collected(self):
        lines, _ = node_shim.stream_lines(1, 5)
        messages = node_shim.run_driver(stand_in(ECHO), "n1", lines)
        self.assertEqual(len(messages), 5)
        self.assertEqual(messages[0][0], "armor/node/n1/telemetry")

    def test_a_topic_of_another_node_is_refused(self):
        driver = stand_in("import sys\nfor line in sys.stdin:\n    print('armor/node/other/telemetry\t{}')\n")
        with self.assertRaises(node_shim.ShimError):
            node_shim.run_driver(driver, "n1", ["1\t1.0\taa"])

    def test_text_that_is_not_a_message_is_refused(self):
        driver = stand_in("import sys\nfor line in sys.stdin:\n    print('hello')\n")
        with self.assertRaises(node_shim.ShimError):
            node_shim.run_driver(driver, "n1", ["1\t1.0\taa"])

    def test_a_driver_that_stops_is_reported(self):
        with self.assertRaises(node_shim.ShimError):
            node_shim.run_driver(stand_in("import sys\nsys.exit(3)\n"), "n1", ["1\t1.0\taa"])

    def test_the_messages_go_to_the_broker_with_qos_one(self):
        made = []

        def factory(client_id):
            made.append(FakeClient(client_id))
            return made[0]

        count = node_shim.publish([("armor/node/n1/telemetry", {"a": 1})], "mqtt://127.0.0.1:1883", client_factory=factory)
        self.assertEqual(count, 1)
        self.assertEqual(made[0].sent, [("armor/node/n1/telemetry", {"a": 1}, 1)])

    def test_a_broker_off_the_private_network_is_refused(self):
        with self.assertRaises(node_shim.MqttOutError):
            node_shim.publish([], "mqtt://8.8.8.8:1883")


if __name__ == "__main__":
    unittest.main()
