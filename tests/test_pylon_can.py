"""The frames and the caution of the emulated battery. Nothing is sent: only bytes are compared."""

import contextlib
import dataclasses
import io
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from armor_simulator.pylon_can import Bank, Order, Policy, bank_from, decide, frames, main  # noqa: E402

GOOD = Bank(voltage_v=52.28, current_a=0.4, temperature_c=22.0, soc_percent=60, soh_percent=100, modules=2, charge_voltage_v=55.2, discharge_voltage_v=48.0,
            max_charge_a=50.0, max_discharge_a=80.0)


def by_id(bank, order=None):
    return dict(frames(bank, order or decide(bank)))


def change(**values):
    return dataclasses.replace(GOOD, **values)


class Frames(unittest.TestCase):
    def test_the_bytes_of_the_published_example(self):
        said = by_id(GOOD)
        self.assertEqual(said[0x351], bytes([0x28, 0x02, 0xF4, 0x01, 0x20, 0x03, 0xE0, 0x01]))
        self.assertEqual(said[0x355], bytes([0x3C, 0x00, 0x64, 0x00]))
        self.assertEqual(said[0x356], bytes([0x6C, 0x14, 0x04, 0x00, 0xDC, 0x00]))
        self.assertEqual(said[0x359], bytes([0, 0, 0, 0, 2, 0x50, 0x4E]))
        self.assertEqual(said[0x35C], bytes([0xC0, 0x00]))
        self.assertEqual(said[0x35E], b"PYLON   ")

    def test_protections_and_warnings_have_their_bits(self):
        said = by_id(change(protections=("cell_high_v", "charge_over_current"), warnings=("temperature_low", "system")))
        self.assertEqual(said[0x359][:4], bytes([0x02, 0x01, 0x10, 0x80]))

    def test_a_current_while_discharging_is_negative(self):
        self.assertEqual(struct.unpack("<hhh", by_id(change(current_a=-12.5, temperature_c=-3.0))[0x356])[1:], (-125, -30))

    def test_old_or_impossible_data_closes_everything_and_says_no_figure(self):
        for bank in (change(age_s=11), change(age_s=-1), change(voltage_v=float("nan")), change(modules=0), change(soc_percent=101), change(charge_voltage_v=40.0),
                     change(max_charge_a=-1.0)):
            order = decide(bank)
            self.assertEqual(order, Order(0.0, 0.0, False, False, False))
            said = by_id(bank, order)
            self.assertEqual(said[0x351], bytes(8))
            self.assertEqual(said[0x35C], bytes(2))
            self.assertEqual(said[0x359][1], 0x80)
            self.assertNotIn(0x355, said)
            self.assertNotIn(0x356, said)


class Caution(unittest.TestCase):
    def test_a_fault_of_the_electronics_closes_both_directions(self):
        self.assertEqual(decide(change(protections=("system",))), Order(0.0, 0.0, False, False, False))

    def test_the_charge_tapers_near_full(self):
        self.assertEqual(decide(change(soc_percent=80)).charge_a, 50.0)
        self.assertAlmostEqual(decide(change(soc_percent=90)).charge_a, 30.0)
        self.assertAlmostEqual(decide(change(soc_percent=100)).charge_a, 10.0)
        self.assertEqual(decide(change(soc_percent=100), Policy(taper_from_soc=100)).charge_a, 50.0)

    def test_temperature_voltage_and_protections_stop_a_direction(self):
        for bank in (change(temperature_c=-1), change(temperature_c=51), change(voltage_v=55.2), change(protections=("cell_high_v",))):
            order = decide(bank)
            self.assertFalse(order.charge_enable)
            self.assertEqual(order.charge_a, 0.0)
        for bank in (change(temperature_c=56), change(voltage_v=48.0), change(soc_percent=10), change(protections=("cell_low_v",))):
            order = decide(bank)
            self.assertFalse(order.discharge_enable)
            self.assertEqual(order.discharge_a, 0.0)

    def test_a_stopped_discharge_waits_for_more_charge(self):
        self.assertTrue(decide(change(soc_percent=12)).discharge_enable)
        self.assertFalse(decide(change(soc_percent=12), discharge_was_stopped=True).discharge_enable)
        self.assertTrue(decide(change(soc_percent=16), discharge_was_stopped=True).discharge_enable)

    def test_an_empty_battery_asks_to_be_charged(self):
        order = decide(change(soc_percent=4))
        self.assertTrue(order.force_charge)
        self.assertEqual(by_id(change(soc_percent=4))[0x35C][0], 0xA0)


class Reading(unittest.TestCase):
    def test_a_state_is_read_and_a_wrong_one_refused(self):
        document = {field.name: getattr(GOOD, field.name) for field in dataclasses.fields(GOOD)}
        document["protections"], document["warnings"] = ["system"], []
        self.assertEqual(bank_from(document).protections, ("system",))
        for wrong in ([], {**document, "extra": 1}, {**document, "voltage_v": "52"}, {**document, "modules": True}, {**document, "warnings": ["fire"]},
                      {**document, "warnings": "system"}, {"voltage_v": 52}):
            with self.assertRaises(ValueError):
                bank_from(wrong)

    def test_the_command_prints_the_frames_and_says_they_are_simulated(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / "bank.json"
            state.write_text(json.dumps({f.name: getattr(GOOD, f.name) for f in dataclasses.fields(GOOD) if f.name not in ("protections", "warnings")}), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main([str(state)]), 0)
            lines = out.getvalue().splitlines()
            self.assertEqual(len(lines), 6)
            self.assertTrue(all(line.startswith("(simulated) ") for line in lines))
            state.write_text("{", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(state)]), 2)
                self.assertEqual(main([str(Path(folder) / "missing.json")]), 2)


if __name__ == "__main__":
    unittest.main()
