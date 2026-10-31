import contextlib
import copy
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
COMMON = ROOT.parent / "ARMOR-COMMON" / "src"
HAS_ARMOR_COMMON = COMMON.is_dir()
if HAS_ARMOR_COMMON:
    sys.path.insert(0, str(COMMON))

from armor_simulator.alarm_scenarios import (  # noqa: E402
    ALARM_CODES, ScenarioError, build_stream, guarded, load_observed, load_scenario, mode_at, parse_scenario, read_json, verify_alarms,
)
from armor_simulator.cli import main  # noqa: E402

EXAMPLES = sorted((ROOT / "examples" / "alarm").glob("*.json"))
GOLDEN = {
    ("--count", "5", "--seed", "1"): "8cbdec2f8a4400bb934511fbbb6edb3e3b9149e76f69df36149eb802a333d55d",
    ("--count", "240", "--solar", "--electrical", "--seed", "2", "--health-every", "7"): "5d4c1edc8279f566747aa8336f0ba376ce1e0c27739d3640abadb9ae5f1404b6",
    ("--count", "30", "--scenario", "two-intruders", "--fault", "duplicates", "--fault-every", "4", "--seed", "3"): "0c0a47aea4c33467bea39c455e88066526f06366f561117cf2897312e8cee9ed",
    ("--count", "20", "--scenario", "crossing", "--light", "night", "--start-ms", "1000"): "acace13a3b9d36d672d51df354d5a5f92f82250d56d7453996c7e4918857e308",
}


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(args))
        except SystemExit as exit_:
            code = exit_.code
    return code, out.getvalue(), err.getvalue()


def base():
    return {
        "schema": "armor-alarm-scenario/1", "name": "t", "duration_s": 100, "nodes": ["n1", "n2"], "seed": 1,
        "zones": [{"id": "a", "node": "n1", "sensor_id": 2}, {"id": "b", "node": "n2", "sensor_id": 1, "armed_in": ["away"]}],
        "events": [{"type": "mode", "at_s": 0, "mode": "away"}, {"type": "intrusion", "at_s": 10, "path": [{"zone": "a", "dwell_s": 5}, {"zone": "b", "dwell_s": 5}]}],
        "expect": {"alarms": [{"code": "intrusion", "at_s": [10, 15]}]},
    }


def at(stream, topic_end, second):
    return [p for t, p in stream if t.endswith(topic_end) and p["timestamp_ms"] == second * 1000]


class CharacterisationTests(unittest.TestCase):
    """What the simulator did before the scenario files and the energy model existed must stay byte for byte."""

    def test_the_default_output_is_unchanged(self):
        for args, digest in GOLDEN.items():
            code, out, _ = run(*args)
            self.assertEqual(code, 0)
            self.assertEqual(hashlib.sha256(out.encode()).hexdigest(), digest, args)


class ExamplesTests(unittest.TestCase):
    def test_there_are_examples_and_all_of_them_are_valid(self):
        self.assertGreaterEqual(len(EXAMPLES), 8)
        for path in EXAMPLES:
            with self.subTest(path.name):
                scenario = load_scenario(path)
                self.assertTrue(scenario.expect_alarms or scenario.expect_forbidden)

    @unittest.skipUnless(HAS_ARMOR_COMMON, "ARMOR-COMMON is not next to this repository")
    def test_every_message_of_every_example_is_valid_for_the_contracts(self):
        for path in EXAMPLES:
            with self.subTest(path.name):
                code, _, err = run("--alarm-scenario", str(path), "--validate")
                self.assertEqual(code, 0, err)

    @unittest.skipUnless(HAS_ARMOR_COMMON, "ARMOR-COMMON is not next to this repository")
    def test_the_codes_that_may_be_expected_exist_in_the_alarm_table_of_the_server(self):
        table = json.loads((COMMON / "armor_common" / "alarm_codes.json").read_text(encoding="utf-8"))["codes"]
        self.assertEqual([code for code in ALARM_CODES if code not in table], [])

    def test_the_same_scenario_always_gives_the_same_stream(self):
        for path in EXAMPLES:
            scenario = load_scenario(path)
            self.assertEqual(list(build_stream(scenario)), list(build_stream(scenario)), path.name)

    def test_a_seed_changes_the_random_part_only(self):
        data = read_json(ROOT / "examples" / "alarm" / "sensor-noise-and-drift.json")
        other = copy.deepcopy(data)
        other["seed"] += 1
        self.assertNotEqual(list(build_stream(parse_scenario(data))), list(build_stream(parse_scenario(other))))


class StreamTests(unittest.TestCase):
    def test_an_intruder_walks_the_zones_in_order_and_only_then(self):
        stream = list(build_stream(parse_scenario(base())))
        present = {s: [t for t in at(stream, "/telemetry", s)[0:1] for _ in [0] if t["targets"]] for s in range(100)}
        seen = [s for s, found in present.items() if found]
        self.assertEqual(seen, list(range(10, 15)), "only the five seconds in zone a (node n1)")
        self.assertTrue(all(t["targets"][0]["sensor_id"] == 2 for t in at(stream, "/telemetry", 12) if t["node_id"] == "n1"))
        second_node = [t for t in at(stream, "/telemetry", 17) if t["node_id"] == "n2"][0]
        self.assertEqual(second_node["targets"][0]["sensor_id"], 1, "then zone b, on the other node, sensor 1")

    def test_a_node_without_link_says_nothing_and_comes_back(self):
        data = base()
        data["events"] = [{"type": "node_comm_loss", "at_s": 20, "duration_s": 30, "node": "n2"}]
        data["expect"] = {}
        stream = list(build_stream(parse_scenario(data)))
        n2 = [p["timestamp_ms"] // 1000 for t, p in stream if p["node_id"] == "n2"]
        self.assertFalse([s for s in n2 if 20 <= s < 50])
        self.assertIn(19, n2)
        self.assertIn(50, n2)
        self.assertEqual(sum(1 for t, p in stream if p["node_id"] == "n1" and t.endswith("/telemetry")), 100)

    def test_a_dead_sensor_hides_the_intruder_and_a_stuck_one_invents_him(self):
        data = base()
        data["events"] = [{"type": "intrusion", "at_s": 10, "path": [{"zone": "a", "dwell_s": 10}]}, {"type": "sensor_fault", "at_s": 10, "zone": "a", "fault": "dead", "duration_s": 10},
                          {"type": "sensor_fault", "at_s": 40, "zone": "a", "fault": "stuck", "duration_s": 10}]
        data["expect"] = {}
        stream = list(build_stream(parse_scenario(data)))
        n1 = {p["timestamp_ms"] // 1000: p["targets"] for t, p in stream if p["node_id"] == "n1" and t.endswith("/telemetry")}
        self.assertTrue(all(not n1[s] for s in range(10, 20)))
        phantom = [n1[s][0] for s in range(40, 50)]
        self.assertEqual(len({(p["x_mm"], p["y_mm"]) for p in phantom}), 1, "a stuck sensor repeats one position")
        self.assertTrue(all(p["speed_mm_s"] == 0 for p in phantom))
        self.assertFalse(n1[60])

    def test_drift_moves_the_reported_position_away_from_the_truth(self):
        data = base()
        data["events"] = [{"type": "intrusion", "at_s": 0, "path": [{"zone": "a", "dwell_s": 50}]}, {"type": "sensor_fault", "at_s": 0, "zone": "a", "fault": "drift", "duration_s": 50, "magnitude": 20.0}]
        data["expect"] = {}
        stream = list(build_stream(parse_scenario(data)))
        xs = [p["targets"][0]["x_mm"] for t, p in stream if p["node_id"] == "n1" and t.endswith("/telemetry") and p["targets"]]
        self.assertGreater(xs[40] - xs[0], 600)

    def test_the_tracks_respect_the_limits_of_the_node(self):
        data = base()
        data["events"] = [{"type": "intrusion", "at_s": 0, "people": 5, "path": [{"zone": "a", "dwell_s": 50}]}] * 4
        data["expect"] = {}
        for topic, payload in build_stream(parse_scenario(data)):
            if topic.endswith("/telemetry"):
                self.assertLessEqual(len(payload["targets"]), 15)
                self.assertEqual([t["track_id"] for t in payload["targets"]], list(range(1, len(payload["targets"]) + 1)))

    def test_a_mains_outage_brings_power_messages_with_no_voltage_on_the_grid(self):
        stream = list(build_stream(load_scenario(ROOT / "examples" / "alarm" / "mains-outage.json")))
        volts = {p["timestamp_ms"] // 1000: p["channels"][0]["voltage_v"] for t, p in stream if t.startswith("armor/electrical/")}
        self.assertTrue(all(volts[s] == 0.0 for s in range(60, 120)))
        self.assertTrue(all(volts[s] > 200 for s in list(range(0, 60)) + list(range(120, 180))))
        modes = {p["timestamp_ms"] // 1000: p["mode"] for t, p in stream if t.endswith("axpert-1/state")}
        self.assertEqual({modes[s] for s in range(60, 120)}, {"battery"})
        self.assertEqual({modes[s] for s in range(0, 60)}, {"line"})


class ModesTests(unittest.TestCase):
    def test_the_calendar_puts_the_night_across_midnight_and_an_event_wins_from_its_second(self):
        data = base()
        data.update({"start_clock": "21:00", "schedule": [{"from": "22:00", "to": "06:00", "mode": "night"}], "duration_s": 8000})
        data["events"] = [{"type": "mode", "at_s": 5000, "mode": "home"}]
        data["expect"] = {}
        scenario = parse_scenario(data)
        self.assertEqual(mode_at(scenario, 0), "disarmed")
        self.assertEqual(mode_at(scenario, 3599), "disarmed")
        self.assertEqual(mode_at(scenario, 3600), "night")
        self.assertEqual(mode_at(scenario, 4999), "night")
        self.assertEqual(mode_at(scenario, 5000), "home")

    def test_a_zone_is_defended_only_in_the_modes_it_lists(self):
        scenario = parse_scenario(base())
        self.assertTrue(guarded(scenario, "b", 5))
        data = base()
        data["events"][0]["mode"] = "home"
        data["zones"][0]["armed_in"] = ["home"]
        self.assertFalse(guarded(parse_scenario(data | {"expect": {}}), "b", 5))
        self.assertTrue(guarded(parse_scenario(data | {"expect": {}}), "a", 5))


class FailClosedTests(unittest.TestCase):
    def refused(self, mutate, text=None):
        data = base()
        mutate(data)
        with self.assertRaises(ScenarioError) as caught:
            parse_scenario(data)
        if text:
            self.assertIn(text, str(caught.exception))

    def test_the_valid_base_is_valid(self):
        parse_scenario(base())

    def test_a_key_that_is_not_part_of_the_schema_is_refused_at_every_level(self):
        self.refused(lambda d: d.update(extra=1), "extra")
        self.refused(lambda d: d["zones"][0].update(extra=1), "extra")
        self.refused(lambda d: d["events"][0].update(extra=1), "extra")
        self.refused(lambda d: d["events"][1]["path"][0].update(extra=1), "extra")
        self.refused(lambda d: d["expect"].update(extra=1), "extra")
        self.refused(lambda d: d["expect"]["alarms"][0].update(extra=1), "extra")

    def test_types_ranges_and_references(self):
        self.refused(lambda d: d.update(schema="armor-alarm-scenario/2"), "schema")
        self.refused(lambda d: d.update(duration_s=True), "duration_s")
        self.refused(lambda d: d.update(duration_s=0), "duration_s")
        self.refused(lambda d: d.update(duration_s=10_001), "duration_s")
        self.refused(lambda d: d.update(duration_s=100.0), "duration_s")
        self.refused(lambda d: d.update(nodes=["n1", "n1"]), "twice")
        self.refused(lambda d: d.update(nodes=["N 1"]), "node")
        self.refused(lambda d: d.update(light="dusk"), "light")
        self.refused(lambda d: d.update(power="yes"), "power")
        self.refused(lambda d: d.update(start_clock="25:00"), "HH:MM")
        self.refused(lambda d: d.update(seed=-1), "seed")
        self.refused(lambda d: d["zones"].append({"id": "a", "sensor_id": 1}), "twice")
        self.refused(lambda d: d["zones"][0].update(node="n9"), "not in nodes")
        self.refused(lambda d: d["zones"][0].update(sensor_id=4), "sensor_id")
        self.refused(lambda d: d["zones"][0].update(x_mm=0.0, y_mm=-3000.0), "field of view")
        self.refused(lambda d: d["zones"][0].update(x_mm=0.0, y_mm=1000.0, sensor_id=1), "sensor that sees")
        self.refused(lambda d: d["zones"][0].update(x_mm=0.0), "both")
        self.refused(lambda d: d["zones"][0].update(armed_in=["disarmed"]), "armed_in")
        self.refused(lambda d: d["zones"][0].update(armed_in=[]), "armed_in")
        self.refused(lambda d: d["events"].append({"type": "volcano", "at_s": 1}), "type")
        self.refused(lambda d: d["events"].append({"type": "mode", "at_s": 101, "mode": "away"}), "at_s")
        self.refused(lambda d: d["events"].append({"type": "mode", "at_s": 1, "mode": "party"}), "mode")
        self.refused(lambda d: d["events"].append({"type": "pet", "at_s": 95, "zone": "a", "duration_s": 10}), "ends after")
        self.refused(lambda d: d["events"].append({"type": "pet", "at_s": 1, "zone": "ghost", "duration_s": 10}), "ghost")
        self.refused(lambda d: d["events"].append({"type": "wind", "at_s": 1, "zone": "a", "duration_s": 10, "intensity": 2.0}), "intensity")
        self.refused(lambda d: d["events"].append({"type": "sensor_fault", "at_s": 1, "zone": "a", "duration_s": 10, "fault": "melted"}), "fault")
        self.refused(lambda d: d["events"].append({"type": "sensor_fault", "at_s": 1, "zone": "a", "duration_s": 10}), "lacks")
        self.refused(lambda d: d["events"].append({"type": "node_comm_loss", "at_s": 1, "duration_s": 10, "node": "n9"}), "not in nodes")
        self.refused(lambda d: d["events"][1].update(people=6), "people")
        self.refused(lambda d: d["events"][1].update(path=[]), "at least one")
        self.refused(lambda d: d["events"][1]["path"][0].update(dwell_s=95), "ends after")
        self.refused(lambda d: d["events"].extend([{"type": "mode", "at_s": 1, "mode": "away"}] * 2000), "events")

    def test_the_expectation_is_checked_against_the_scenario(self):
        self.refused(lambda d: d["expect"]["alarms"][0].update(code="made_up"), "code")
        self.refused(lambda d: d["expect"]["alarms"][0].update(at_s=[15, 10]), "after the end")
        self.refused(lambda d: d["expect"]["alarms"][0].update(at_s=[0, 101]), "at_s")
        self.refused(lambda d: d["expect"]["alarms"][0].update(zone="ghost"), "ghost")
        self.refused(lambda d: d["expect"]["alarms"][0].update(severity="loud"), "severity")
        self.refused(lambda d: d["expect"].update(order="sideways"), "order")
        self.refused(lambda d: d["expect"].update(allow_extra=1), "allow_extra")
        self.refused(lambda d: d["expect"]["alarms"][0].update(zone="b", at_s=[10, 15]) or d["events"][0].update(mode="home"), "not defending")
        self.refused(lambda d: d["events"].__setitem__(0, {"type": "mode", "at_s": 0, "mode": "disarmed"}), "not defending")

    def test_a_file_with_repeated_keys_nan_or_garbage_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            for text in ('{"a": 1, "a": 2}', '{"a": NaN}', '{"a": Infinity}', "not json", "\ufeff{", ""):
                path = Path(folder) / "x.json"
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ScenarioError, msg=text):
                    load_scenario(path)
            path.write_bytes(b"\xff\xfe\x00")
            with self.assertRaises(ScenarioError):
                load_scenario(path)
            path.write_text(" " * 1_000_001, encoding="utf-8")
            with self.assertRaises(ScenarioError):
                load_scenario(path)
            with self.assertRaises(ScenarioError):
                load_scenario(Path(folder) / "missing.json")


class VerificationTests(unittest.TestCase):
    def scenario(self, **expect):
        data = base()
        data["expect"] = expect
        return parse_scenario(data)

    def test_what_was_expected_in_time_passes(self):
        scenario = self.scenario(alarms=[{"code": "intrusion", "at_s": [10, 15]}])
        self.assertEqual(verify_alarms(scenario, [{"t_s": 11.0, "code": "intrusion"}]), [])

    def test_a_missing_or_late_alarm_is_said_with_its_time(self):
        scenario = self.scenario(alarms=[{"code": "intrusion", "at_s": [10, 15]}])
        self.assertIn("did not happen", verify_alarms(scenario, [])[0])
        late = verify_alarms(scenario, [{"t_s": 40.0, "code": "intrusion"}])
        self.assertIn("did not happen in time", late[0])
        self.assertIn("40", late[0])

    def test_the_order_matters_only_when_it_is_strict(self):
        alarms = [{"code": "intrusion", "at_s": [0, 100]}, {"code": "node_down", "at_s": [0, 100]}]
        observed = [{"t_s": 50.0, "code": "node_down"}, {"t_s": 60.0, "code": "intrusion"}]
        self.assertEqual(verify_alarms(self.scenario(alarms=alarms), observed), [])
        self.assertIn("order is wrong", verify_alarms(self.scenario(alarms=alarms, order="strict"), observed)[0])

    def test_a_forbidden_alarm_and_an_unexpected_one_are_found(self):
        scenario = self.scenario(forbidden=[{"code": "intrusion", "from_s": 20, "to_s": 30}])
        self.assertEqual(verify_alarms(scenario, [{"t_s": 10.0, "code": "intrusion"}]), [])
        self.assertIn("must not happen", verify_alarms(scenario, [{"t_s": 25.0, "code": "intrusion"}])[0])
        strict = self.scenario(alarms=[{"code": "intrusion", "at_s": [10, 15]}], allow_extra=False)
        problems = verify_alarms(strict, [{"t_s": 11.0, "code": "intrusion"}, {"t_s": 12.0, "code": "node_down"}])
        self.assertEqual(len(problems), 1)
        self.assertIn("node_down", problems[0])

    def test_zone_node_and_severity_must_match_when_the_expectation_names_them(self):
        scenario = self.scenario(alarms=[{"code": "intrusion", "zone": "a", "severity": "high", "at_s": [10, 15]}])
        self.assertEqual(verify_alarms(scenario, [{"t_s": 11.0, "code": "intrusion", "zone": "a", "severity": "high"}]), [])
        self.assertTrue(verify_alarms(scenario, [{"t_s": 11.0, "code": "intrusion", "zone": "b", "severity": "high"}]))
        self.assertTrue(verify_alarms(scenario, [{"t_s": 11.0, "code": "intrusion", "zone": "a", "severity": "warning"}]))

    def test_one_observed_alarm_cannot_satisfy_two_expectations(self):
        scenario = self.scenario(alarms=[{"code": "intrusion", "at_s": [0, 50]}, {"code": "intrusion", "at_s": [0, 50]}])
        self.assertEqual(len(verify_alarms(scenario, [{"t_s": 5.0, "code": "intrusion"}])), 1)

    def test_observed_files_are_read_strictly(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "o.json"
            path.write_text('[{"t_s": 2, "code": "intrusion"}, {"t_s": 1, "code": "node_down", "node": "n"}]', encoding="utf-8")
            self.assertEqual([a["code"] for a in load_observed(path)], ["node_down", "intrusion"])
            path.write_text('{"t_s": 3, "code": "intrusion"}\n{"t_s": 1, "code": "x"}\n', encoding="utf-8")
            self.assertEqual(len(load_observed(path)), 2)
            for bad in ('[{"code": "x"}]', '[{"t_s": -1, "code": "x"}]', '[{"t_s": true, "code": "x"}]', '[{"t_s": 1, "code": "x", "other": 1}]', '[1]'):
                path.write_text(bad, encoding="utf-8")
                with self.assertRaises(ScenarioError, msg=bad):
                    load_observed(path)


class CommandLineTests(unittest.TestCase):
    def test_check_prints_a_summary_and_a_bad_file_is_refused_with_code_2(self):
        example = str(ROOT / "examples" / "alarm" / "sequential-intrusion.json")
        code, out, _ = run("--alarm-scenario", example, "--check-alarm-scenario")
        self.assertEqual(code, 0)
        self.assertIn("Sequential intrusion", out)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.json"
            path.write_text('{"schema": "x"}', encoding="utf-8")
            code, out, err = run("--alarm-scenario", str(path))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("bad.json", err)

    def test_the_stream_is_json_lines_in_the_usual_envelope(self):
        code, out, _ = run("--alarm-scenario", str(ROOT / "examples" / "alarm" / "sequential-intrusion.json"))
        self.assertEqual(code, 0)
        lines = [json.loads(line) for line in out.splitlines()]
        self.assertTrue(all(set(line) == {"topic", "payload"} for line in lines))
        self.assertEqual(sum(1 for line in lines if line["topic"].endswith("/telemetry")), 120)

    def test_verifying_exits_0_when_the_system_answered_as_expected_and_1_when_not(self):
        example = str(ROOT / "examples" / "alarm" / "sequential-intrusion.json")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "o.jsonl"
            path.write_text('{"t_s": 31, "code": "intrusion", "node": "radar-1", "severity": "high"}\n', encoding="utf-8")
            code, out, err = run("--alarm-scenario", example, "--verify-alarms", str(path))
            self.assertEqual((code, err), (0, ""))
            self.assertIn("as expected", out)
            path.write_text('{"t_s": 90, "code": "intrusion", "node": "radar-1", "severity": "high"}\n', encoding="utf-8")
            code, _, err = run("--alarm-scenario", example, "--verify-alarms", str(path))
            self.assertEqual(code, 1)
            self.assertIn("did not happen in time", err)

    def test_combinations_that_make_no_sense_are_refused(self):
        example = str(ROOT / "examples" / "alarm" / "sequential-intrusion.json")
        for extra in (["--count", "5"], ["--solar"], ["--electrical"], ["--energy"], ["--scenario", "crossing"], ["--node-id", "other"]):
            code, _, err = run("--alarm-scenario", example, *extra)
            self.assertEqual(code, 2, extra)
        self.assertEqual(run("--check-alarm-scenario")[0], 2)
        self.assertEqual(run("--verify-alarms", "x.json")[0], 2)

    def test_faults_apply_to_a_scenario_like_to_any_stream(self):
        example = str(ROOT / "examples" / "alarm" / "node-comm-loss.json")
        code, out, _ = run("--alarm-scenario", example, "--fault", "duplicates", "--fault-every", "10", "--fault-topic", "telemetry")
        self.assertEqual(code, 0)
        clean = run("--alarm-scenario", example)[1].splitlines()
        self.assertGreater(len(out.splitlines()), len(clean))

    def test_it_runs_as_a_module(self):
        result = subprocess.run([sys.executable, "-m", "armor_simulator", "--alarm-scenario", str(ROOT / "examples" / "alarm" / "pet-and-wind.json"), "--check-alarm-scenario"],
                                capture_output=True, text=True, env={"PYTHONPATH": str(ROOT / "src"), "SYSTEMROOT": "C:\\Windows"}, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
