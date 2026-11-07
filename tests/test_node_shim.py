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


ELECTRICAL_OK = "import sys\nfor line in sys.stdin:\n    print('armor/electrical/n1/state\\t{}')\nprint('armor/health/n1\\t{}')\n"
ELECTRICAL_WRONG = "import sys\nfor line in sys.stdin:\n    print('armor/node/n1/telemetry\\t{}')\n"


SOLAR_OK = "import sys\nfor line in sys.stdin:\n    print('armor/solar/n1/axpert-1/state\\t{}')\n"
SOLAR_WRONG = "import sys\nfor line in sys.stdin:\n    print('armor/solar/n2/axpert-1/state\\t{}')\n"


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

    def test_the_meter_rounds_carry_one_reply_per_meter_with_a_good_crc(self):
        lines, rounds = node_shim.meter_lines(3)
        self.assertEqual((len(lines), rounds), (3, 3))
        stamp, _, entries = lines[0].partition("\t")
        items = entries.split("|")
        self.assertEqual((stamp, [item.split(":")[0] for item in items]), ("1000", ["grid", "heater", "dc-bus"]))
        for item in items:
            reply = bytes.fromhex(item.split(":")[3])
            self.assertEqual(node_shim.meter_bus.crc16(reply[:-2]), int.from_bytes(reply[-2:], "little"))

    def test_the_electrical_shim_may_print_its_state_and_health_topics_only(self):
        good = stand_in(ELECTRICAL_OK)
        self.assertEqual(len(node_shim.run_driver(good, "n1", ["1\t-"], node="electrical")), 2)
        with self.assertRaises(node_shim.ShimError):
            node_shim.run_driver(stand_in(ELECTRICAL_WRONG), "n1", ["1\t-"], node="electrical")

    def test_the_solar_rounds_carry_an_inverter_and_a_battery_with_a_mains_loss(self):
        lines, expected = node_shim.solar_lines(5)
        self.assertEqual((len(lines), expected), (10, 10))
        inverter = [line.split("	") for line in lines if "	inverter	" in line]
        batteries = [line.split("	") for line in lines if "	battery	" in line]
        self.assertEqual((len(inverter), len(batteries)), (5, 5))
        self.assertTrue(all(len(item) == 6 for item in inverter) and all(len(item) == 5 for item in batteries))
        self.assertEqual([item[4] for item in inverter], ["L", "L", "L", "B", "L"])
        self.assertEqual(inverter[3][5][5], "1")       # the mains-loss flag of QPIWS
        self.assertEqual(len(inverter[0][3].split()), 20)
        self.assertEqual(len(bytes.fromhex(batteries[0][3])) > 0, True)

    def test_the_solar_shim_may_print_its_own_topics_only(self):
        good = stand_in(SOLAR_OK)
        self.assertEqual(len(node_shim.run_driver(good, "n1", ["1	x"], node="solar")), 1)
        with self.assertRaises(node_shim.ShimError):
            node_shim.run_driver(stand_in(SOLAR_WRONG), "n1", ["1	x"], node="solar")

    def test_the_alarm_steps_open_the_door_and_cut_the_power(self):
        lines, expected = node_shim.alarm_lines(8)
        self.assertEqual((len(lines), expected), (8, 8))
        actions = [line.split("	")[1] for line in lines]
        self.assertEqual(actions, list(node_shim.ALARM_STEPS))
        self.assertTrue(all(len(line.split("	")) == 3 for line in lines))
        self.assertIn("door:instant:1800", lines[3])
        self.assertIn("door:instant:1800", lines[4])
        self.assertNotIn("door:instant:1800", lines[5])

    def test_the_alarm_must_pass_every_phase(self):
        every = [("armor/alarm/n1/state", {"phase": phase}) for phase in node_shim.ALARM_PHASES]
        self.assertIsNone(node_shim.alarm_verify(every))
        self.assertIn("alarm", node_shim.alarm_verify(every[:2] + every[3:]))

    def test_the_hmi_reports_a_brownout_restart_with_the_uptime_starting_again(self):
        lines, expected = node_shim.hmi_lines(6)
        self.assertEqual((len(lines), expected), (6, 6))
        rows = [line.split("	") for line in lines]
        self.assertTrue(all(len(row) == 9 for row in rows))
        self.assertEqual([row[2] for row in rows], ["1", "1", "1", "9", "9", "9"])
        self.assertLess(int(rows[3][1]), int(rows[2][1]))
        good = [("armor/health/n1", {"kind": "node_health", "reset_reason": reason, "uptime_s": up}) for reason, up in (("power_on", 100), ("brownout", 5))]
        self.assertIsNone(node_shim.hmi_verify(good))
        self.assertIsNotNone(node_shim.hmi_verify(good[:1]))
        self.assertIsNotNone(node_shim.hmi_verify([good[0], ("armor/health/n1", {"kind": "node_health", "reset_reason": "brownout", "uptime_s": 200})]))

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
