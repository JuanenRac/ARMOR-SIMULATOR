"""Vision scenarios: the file is read strictly, the rules play on the host as the vision service plays them, and the command line prints and checks the events."""
import contextlib
import copy
import io
import json
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

from armor_simulator import cli, vision_scenarios as vs
from armor_simulator.alarm_scenarios import ScenarioError

EXAMPLES = sorted((ROOT / "examples" / "vision").glob("*.json"))
SQUARE = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.9], [0.2, 0.9]]


def base():
    return {
        "schema": vs.SCHEMA, "name": "t", "duration_s": 30, "step_s": 0.5,
        "cameras": [{"id": "cam", "detection": {
            "zones": [{"id": "a", "name": "A", "points": copy.deepcopy(SQUARE), "labels": ["person"]}, {"id": "b", "name": "B", "points": [[0.0, 0.0], [0.1, 0.0], [0.1, 0.1]], "kind": "detection"}],
            "profiles": {"away": {"watch": ["a"]}, "night": {"watch": []}}}}],
        "events": [{"type": "mode", "at_s": 0, "mode": "home"}, {"type": "walk", "at_s": 1, "camera": "cam", "label": "person", "speed": 0.1, "path": [[0.1, 0.5], [0.5, 0.5]]}],
    }


def load(raw):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "s.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        return vs.load_scenario(path)


def events(raw):
    return vs.build_events(load(raw))


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(args))
        except SystemExit as exit_:
            code = exit_.code
    return code, out.getvalue(), err.getvalue()


class ReadingTests(unittest.TestCase):
    def test_the_examples_load_and_the_rules_answer_as_they_expect(self):
        self.assertGreaterEqual(len(EXAMPLES), 2)
        for path in EXAMPLES:
            scenario = vs.load_scenario(path)
            self.assertEqual(vs.verify_events(scenario, vs.build_events(scenario)), [], path.name)

    def test_whatever_is_not_understood_refuses_the_whole_file(self):
        def mutate(change):
            raw = base()
            change(raw)
            return raw
        bad = {
            "schema": lambda r: r.update(schema="x"),
            "unknown key": lambda r: r.update(extra=1),
            "no cameras": lambda r: r.update(cameras=[]),
            "camera twice": lambda r: r["cameras"].append(copy.deepcopy(r["cameras"][0])),
            "zone twice": lambda r: r["cameras"][0]["detection"]["zones"].append(copy.deepcopy(r["cameras"][0]["detection"]["zones"][0])),
            "corner out of the picture": lambda r: r["cameras"][0]["detection"]["zones"][0]["points"].__setitem__(0, [1.5, 0.2]),
            "no area": lambda r: r["cameras"][0]["detection"]["zones"][0].update(points=[[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]]),
            "bad kind": lambda r: r["cameras"][0]["detection"]["zones"][0].update(kind="siren"),
            "profile of an unknown mode": lambda r: r["cameras"][0]["detection"]["profiles"].update(sleep={"watch": []}),
            "profile watches a ghost": lambda r: r["cameras"][0]["detection"]["profiles"].update(away={"watch": ["ghost"]}),
            "bad sensitivity": lambda r: r["cameras"][0]["detection"]["profiles"].update(away={"watch": [], "sensitivity": "x"}),
            "no mode at zero": lambda r: r["events"][0].update(at_s=2),
            "walk on a ghost camera": lambda r: r["events"][1].update(camera="ghost"),
            "walk outside the time": lambda r: r["events"][1].update(at_s=99),
            "walk too fast": lambda r: r["events"][1].update(speed=50),
            "walk of one point": lambda r: r["events"][1].update(path=[[0.1, 0.1]]),
            "unknown event": lambda r: r["events"].append({"type": "fire", "at_s": 1}),
            "too many steps": lambda r: r.update(duration_s=3600, step_s=0.05),
            "expectation on a ghost zone": lambda r: r.update(expect={"events": [{"camera": "cam", "zone": "ghost"}]}),
            "window outside": lambda r: r.update(expect={"events": [{"camera": "cam", "zone": "a", "between_s": [0, 99]}]}),
        }
        for name, change in bad.items():
            with self.assertRaises(ScenarioError, msg=name):
                load(mutate(change))

    def test_a_file_with_a_repeated_key_or_nan_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            for text in ('{"schema": "a", "schema": "b"}', '{"duration_s": NaN}', "not json"):
                path = Path(folder) / "s.json"
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ScenarioError, msg=text):
                    vs.load_scenario(path)


class RulesTests(unittest.TestCase):
    def test_a_person_in_a_watched_zone_raises_one_event_per_visit(self):
        found = events(base())
        self.assertEqual([(e["zone_id"], e["type"], e["label"]) for e in found], [("a", "alert", "person")])
        self.assertFalse(found[0]["authorizes_action"])
        self.assertEqual(found[0]["schema"], "armor.vision.event/v1")

    def test_leaving_and_coming_back_is_a_new_visit(self):
        raw = base()
        raw["events"][1]["path"] = [[0.1, 0.5], [0.5, 0.5], [0.1, 0.5], [0.5, 0.5]]
        raw["events"][1]["speed"] = 0.2
        self.assertEqual(len(events(raw)), 2)

    def test_a_label_the_zone_does_not_count_is_ignored(self):
        raw = base()
        raw["events"][1]["label"] = "cat"
        self.assertEqual(events(raw), [])

    def test_the_profile_of_the_mode_picks_the_zones(self):
        raw = base()
        raw["events"][0]["mode"] = "night"
        self.assertEqual(events(raw), [])   # night watches nothing
        raw["events"][0]["mode"] = "away"
        self.assertEqual(len(events(raw)), 1)

    def test_a_mode_without_profile_watches_every_zone(self):
        raw = base()
        raw["cameras"][0]["detection"]["profiles"] = {}
        for mode in ("home", "away", "night", "disarmed"):
            raw["events"][0]["mode"] = mode
            self.assertEqual(len(events(raw)), 1, mode)

    def test_the_mode_can_change_during_the_walk(self):
        raw = base()
        raw["cameras"][0]["detection"]["profiles"] = {"home": {"watch": []}}
        raw["events"][1].update(path=[[0.1, 0.5], [0.9, 0.5]], speed=0.05)
        raw["events"].append({"type": "mode", "at_s": 6, "mode": "away"})
        found = events(raw)
        self.assertEqual(len(found), 1)
        self.assertGreaterEqual(found[0]["timestamp"], 6)

    def test_min_frames_and_min_seconds_hold_the_event_back(self):
        raw = base()
        zone = raw["cameras"][0]["detection"]["zones"][0]
        zone.update(min_frames=1, min_seconds=0)
        quick = events(raw)[0]["timestamp"]
        zone.update(min_seconds=3)
        slow = events(raw)[0]["timestamp"]
        self.assertAlmostEqual(slow - quick, 3, delta=0.5)
        zone.update(min_seconds=0, min_frames=4)
        self.assertAlmostEqual(events(raw)[0]["timestamp"] - quick, 1.5, delta=0.01)

    def test_a_walk_too_short_to_stay_makes_no_event(self):
        raw = base()
        raw["cameras"][0]["detection"]["zones"][0].update(min_seconds=60)
        self.assertEqual(events(raw), [])

    def test_the_result_is_the_same_every_time_and_in_order_of_time(self):
        raw = base()
        raw["cameras"][0]["detection"]["profiles"] = {}
        raw["events"].append({"type": "walk", "at_s": 3, "camera": "cam", "label": "person", "speed": 0.1, "path": [[0.1, 0.3], [0.5, 0.3]]})
        first, second = events(raw), events(raw)
        self.assertEqual(first, second)
        self.assertEqual([e["timestamp"] for e in first], sorted(e["timestamp"] for e in first))
        self.assertEqual({e["track_id"] for e in first}, {1, 2})

    def test_the_boxes_stay_inside_the_picture(self):
        raw = base()
        raw["events"][1].update(path=[[0.0, 0.3], [0.9, 0.3]])
        raw["cameras"][0]["detection"]["zones"][0]["points"] = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
        for event in events(raw):
            self.assertTrue(all(0 <= v <= 1 for v in event["box"]))

    @unittest.skipUnless(HAS_ARMOR_COMMON, "ARMOR-COMMON is not next to this repository")
    def test_the_events_follow_the_contract_of_the_vision_event(self):
        from armor_common.contracts import validate_payload
        for path in EXAMPLES:
            scenario = vs.load_scenario(path)
            built = vs.build_events(scenario)
            self.assertTrue(built, path.name)
            for event in built:
                validate_payload("vision_event", event)


class VerifyTests(unittest.TestCase):
    def test_a_missing_expected_event_and_a_forbidden_one_are_told(self):
        raw = base()
        raw["expect"] = {"events": [{"camera": "cam", "zone": "b"}, {"camera": "cam", "zone": "a", "between_s": [20, 30]}], "forbidden": [{"camera": "cam", "zone": "a", "label": "person"}]}
        scenario = load(raw)
        problems = vs.verify_events(scenario, vs.build_events(scenario))
        self.assertEqual(len(problems), 3)
        self.assertIn("must stay quiet", problems[-1])

    def test_the_summary_counts_what_the_file_has(self):
        text = vs.summary(load(base()))
        self.assertIn("2 zone(s)", text)
        self.assertIn("2 profile(s)", text)

    def test_a_point_on_the_edge_is_inside(self):
        square = tuple((x, y) for x, y in SQUARE)
        self.assertTrue(vs.point_in_polygon((0.2, 0.5), square))
        self.assertTrue(vs.point_in_polygon((0.5, 0.5), square))
        self.assertFalse(vs.point_in_polygon((0.1, 0.5), square))


class CommandLineTests(unittest.TestCase):
    example = str(ROOT / "examples" / "vision" / "porch-by-mode.json")

    def test_it_prints_one_json_object_per_event_and_nothing_else_on_the_output(self):
        code, out, err = run("--vision-scenario", self.example)
        self.assertEqual(code, 0)
        lines = out.strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(all(json.loads(line)["schema"] == "armor.vision.event/v1" for line in lines))
        self.assertIn("3 vision event(s)", err)

    def test_check_only_validates(self):
        code, out, _ = run("--vision-scenario", self.example, "--check-vision-scenario")
        self.assertEqual((code, "camera(s)" in out), (0, True))

    def test_verify_exits_one_when_the_rules_differ(self):
        raw = json.loads(Path(self.example).read_text(encoding="utf-8"))
        raw["expect"]["events"].append({"camera": "front", "zone": "garden", "label": "person", "between_s": [0, 30]})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "s.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            code, _, err = run("--vision-scenario", str(path), "--verify-vision")
        self.assertEqual(code, 1)
        self.assertIn("expected an event in zone garden", err)
        self.assertEqual(run("--vision-scenario", self.example, "--verify-vision")[0], 0)

    def test_a_bad_file_exits_two_and_the_options_need_the_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "s.json"
            path.write_text("{}", encoding="utf-8")
            self.assertEqual(run("--vision-scenario", str(path))[0], 2)
        self.assertEqual(run("--verify-vision")[0], 2)
        self.assertEqual(run("--check-vision-scenario")[0], 2)

    def test_it_cannot_be_combined_with_options_that_emit_messages(self):
        self.assertEqual(run("--vision-scenario", self.example, "--solar")[0], 2)
        self.assertEqual(run("--vision-scenario", self.example, "--alarm-scenario", self.example)[0], 2)


if __name__ == "__main__":
    unittest.main()
