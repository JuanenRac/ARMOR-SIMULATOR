"""The buses of the field nodes and the bench that plays them to a driver: the cases are repeatable, every fault changes what must be answered, and a driver that answers
something else is caught. (The drivers built from the real firmware run in the CI job 'Firmware in the loop'.)"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from armor_simulator import buses, node_bench


def echo_driver(tmp: Path, cases: list[buses.Case], wrong: set[str] = frozenset()) -> list[str]:
    """A driver written in Python that answers every case with the expected text (or a different one for the ids in `wrong`)."""
    table = {c.id: ("different" if c.id in wrong else c.expect) for c in cases}
    script = tmp / "driver.py"
    script.write_text("import sys, json\ntable = json.loads(%r)\nfor line in sys.stdin:\n    f = line.rstrip('\\n').split('\\t')\n    print(f[1] + '\\t' + table[f[1]])\n" % json.dumps(table), encoding="utf-8")
    return [sys.executable, str(script)]


class CaseTests(unittest.TestCase):
    def test_every_bus_has_every_fault_and_runs_are_identical(self):
        for bus in buses.BUSES:
            first, second = buses.cases_for(bus, 3), buses.cases_for(bus, 3)
            self.assertEqual(first, second, bus)
            self.assertEqual([c.fault for c in first], list(buses.FAULTS[bus]))
            self.assertEqual(len({c.id for c in first}), len(first))
            for case in first:
                self.assertEqual(case.line().count("\t"), 3, "the line the drivers read has four fields")
                self.assertTrue(case.expect, case.id)

    def test_another_seed_gives_other_data(self):
        self.assertNotEqual(buses.cases_for("ld2450", 1, ("none",))[0].payload, buses.cases_for("ld2450", 2, ("none",))[0].payload)

    def test_a_fault_changes_what_must_be_answered(self):
        for bus in buses.BUSES:
            by_fault = {c.fault: c.expect for c in buses.cases_for(bus, 1)}
            clean = by_fault.pop("none")
            if bus == "alarm-loop":
                by_fault.pop("noise")        # noise inside the normal band is, by design, not seen
                by_fault.pop("bounce")       # a flicker shorter than the hold time is, by design, not seen
                by_fault.pop("power-up-glitch")
            if bus == "hmi-feed":
                by_fault.pop("heartbeat-limits", None)
            for fault, expect in by_fault.items():
                if bus == "pylontech" and fault in ("no-header", "prompt"):
                    continue     # the table is read the same without them
                if bus == "ld2450" and fault in ("noise", "chunks"):
                    continue     # the frames come out the same: what changes is how the framer gets there
                self.assertNotEqual(expect, clean, f"{bus} {fault}")

    def test_the_rules_the_cases_state(self):
        by = {c.fault: c.expect for c in buses.cases_for("ld2450", 1)}
        self.assertIn("refused=1:out-of-range", by["out-of-range"])
        self.assertIn("refused=1:no-resolution", by["no-resolution"])
        self.assertIn("refused=1:origin", by["origin"])
        self.assertTrue(by["none"].startswith("frames=40 "))
        self.assertEqual(by["silence"], "frames=0")
        self.assertLess(int(by["truncate"].split()[0][7:]), 40)
        loop = buses.cases_for("alarm-loop", 1)
        none, glitch, cut = (next(c for c in loop if c.fault == f).expect.split(",") for f in ("none", "power-up-glitch", "cut"))
        self.assertEqual(none[0], "normal")
        self.assertEqual(glitch[0], "normal", "the first reading holds like any other")
        self.assertIn("triggered", none)
        self.assertEqual(cut[-1], "tamper")
        pzem = {c.fault: c.expect.split("|") for c in buses.cases_for("pzem", 1)}
        self.assertIn("crc", pzem["corrupt"])
        self.assertIn("exception", pzem["exception"])
        self.assertIn("too_short", pzem["silent"])
        self.assertIn("range", pzem["implausible"])
        self.assertIn("address", pzem["other-address"])
        self.assertIn("length", pzem["long"])

    def test_unknown_fault_and_bus_are_refused(self):
        with self.assertRaises(buses.BusError):
            buses.cases_for("pzem", 1, ("melted",))
        with self.assertRaises(buses.BusError):
            buses.cases_for("can", 1)


class BenchTests(unittest.TestCase):
    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = node_bench.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_a_driver_that_answers_what_is_expected_passes_and_another_is_caught(self):
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            for bus in buses.BUSES:
                cases = buses.cases_for(bus, 1)
                code, out, _ = self.run_main(["--bus", bus, "--driver", " ".join(echo_driver(tmp, cases))])
                self.assertEqual(code, 0, out)
                self.assertIn(f"NODE_BENCH=PASS bus={bus}", out)
            cases = buses.cases_for("pzem", 1)
            code, out, _ = self.run_main(["--bus", "pzem", "--driver", " ".join(echo_driver(tmp, cases, {"pzem-corrupt"}))])
            self.assertEqual(code, 1)
            self.assertIn("FAIL pzem-corrupt", out)
            self.assertIn("failed=1", out)

    def test_a_missing_answer_is_a_failure(self):
        cases = buses.cases_for("hmi-feed", 1, ("none",))
        self.assertFalse(node_bench.compare(cases, {})[0]["passed"])

    def test_a_recording_is_played_again_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            path = tmp / "cases.jsonl"
            self.assertEqual(self.run_main(["--bus", "ld2450", "--fault", "noise", "--record", str(path)])[0], 0)
            self.assertEqual(self.run_main(["--bus", "ld2450", "--record", str(path)])[0], 2, "an existing file is not overwritten")
            loaded = buses.load(path)
            self.assertEqual(loaded, buses.cases_for("ld2450", 1, ("noise",)))
            code, out, _ = self.run_main(["--bus", "ld2450", "--replay", str(path), "--driver", " ".join(echo_driver(tmp, loaded))])
            self.assertEqual(code, 0, out)

    def test_bad_recordings_and_missing_driver_are_not_run(self):
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            bad = tmp / "bad.jsonl"
            bad.write_text('{"bus":"can","id":"x","arg":"","payload":"","expect":""}\n', encoding="utf-8")
            self.assertEqual(self.run_main(["--bus", "pzem", "--replay", str(bad), "--driver", "x"])[0], 2)
            bad.write_text("not json\n", encoding="utf-8")
            self.assertEqual(self.run_main(["--bus", "pzem", "--replay", str(bad), "--driver", "x"])[0], 2)
            self.assertEqual(self.run_main(["--bus", "pzem"])[0], 2)
            self.assertEqual(self.run_main(["--bus", "pzem", "--driver", str(tmp / "nothing-here")])[0], 2)


if __name__ == "__main__":
    unittest.main()
