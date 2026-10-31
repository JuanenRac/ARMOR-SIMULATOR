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

from armor_simulator.alarm_scenarios import ScenarioError  # noqa: E402
from armor_simulator.cli import main  # noqa: E402
from armor_simulator.energy import DEFAULTS, cell_voltage, check_config, energy_messages, load_config, price_at, simulate  # noqa: E402

CONFIGS = sorted((ROOT / "examples" / "energy").glob("*.json"))
EPS = 1e-6


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(args))
        except SystemExit as exit_:
            code = exit_.code
    return code, out.getvalue(), err.getvalue()


def rows(config=None, seed=1, days=3, step=900):
    return list(simulate(config or load_config(), seed, days * 86_400 // step, step))


def variants():
    """Configurations that push the model to its limits, to see that the physics holds there too."""
    small = load_config()
    small["battery"].update(modules=1, module_ah=5.0, max_charge_w=100.0, max_discharge_w=100.0, initial_soc=100.0)
    huge = load_config()
    huge["pv"].update(peak_w=20_000.0, mean_cloud=0.0)
    huge["battery"].update(initial_soc=10.0, min_soc=10.0)
    hungry = load_config()
    hungry["load"].update(base_w=5_000.0, evening_peak_w=9_000.0)
    cloudy = load_config()
    cloudy["pv"].update(mean_cloud=1.0, cloud_loss=1.0)
    outage = load_config()
    outage["grid"]["outages"] = [{"at_s": 3_600, "duration_s": 80_000}]
    noexport = load_config()
    noexport["grid"]["export"] = False
    return {"default": load_config(), "small": small, "huge": huge, "hungry": hungry, "cloudy": cloudy, "outage": outage, "noexport": noexport}


class PropertyTests(unittest.TestCase):
    """Whatever the seed and the configuration, the numbers have to be physically possible."""

    def each(self):
        for name, config in variants().items():
            for seed in (0, 1, 7, 12345):
                yield f"{name}/{seed}", rows(config, seed), config

    def test_there_is_no_production_outside_the_hours_of_sun(self):
        for label, data, config in self.each():
            sun = config["sun"]
            for row in data:
                if not sun["sunrise_h"] <= row["hour"] < sun["sunset_h"]:
                    self.assertEqual(row["pv_w"], 0.0, label)
                self.assertGreaterEqual(row["pv_w"], 0.0, label)
        night = [r for r in rows() if r["hour"] < 6 or r["hour"] >= 21]
        self.assertTrue(night and all(r["pv_w"] == 0.0 for r in night))

    def test_the_sun_is_there_at_noon_when_it_is_not_cloudy(self):
        clear = load_config()
        clear["pv"]["mean_cloud"] = 0.0
        noon = [r for r in rows(clear) if 12 <= r["hour"] < 14]
        self.assertGreater(max(r["pv_w"] for r in noon), 0.8 * clear["pv"]["peak_w"])

    def test_the_state_of_charge_never_leaves_its_limits(self):
        for label, data, config in self.each():
            floor = config["battery"]["min_soc"]
            for row in data:
                self.assertGreaterEqual(row["soc_percent"], floor - EPS, label)
                self.assertLessEqual(row["soc_percent"], 100.0 + EPS, label)

    def test_no_flow_of_power_is_negative_and_the_limits_of_the_battery_hold(self):
        for label, data, config in self.each():
            bat = config["battery"]
            for row in data:
                for key in ("pv_w", "house_w", "charge_w", "discharge_w", "import_w", "export_w", "curtailed_w", "unserved_w"):
                    self.assertGreaterEqual(row[key], 0.0, f"{label} {key}")
                self.assertLessEqual(row["charge_w"], bat["max_charge_w"] + EPS, label)
                self.assertLessEqual(row["discharge_w"], bat["max_discharge_w"] + EPS, label)
                self.assertFalse(row["charge_w"] > 0 and row["discharge_w"] > 0, "the battery does not charge and discharge in the same step")
                self.assertFalse(row["import_w"] > 0 and row["export_w"] > 0, "the house does not buy and sell in the same step")

    def test_the_power_that_comes_in_equals_the_power_that_goes_out_at_every_step(self):
        for label, data, _ in self.each():
            for row in data:
                sources = row["pv_w"] + row["discharge_w"] + row["import_w"]
                sinks = row["house_w"] - row["unserved_w"] + row["charge_w"] + row["export_w"] + row["curtailed_w"]
                self.assertAlmostEqual(sources, sinks, delta=1e-6, msg=label)

    def test_the_energy_counters_and_the_cycles_never_go_down(self):
        for label, data, _ in self.each():
            for before, after in zip(data, data[1:], strict=False):
                for key in before["counters_kwh"]:
                    self.assertGreaterEqual(after["counters_kwh"][key], before["counters_kwh"][key], f"{label} {key}")
                self.assertGreaterEqual(after["cycles"], before["cycles"] - EPS, label)

    def test_the_stored_energy_follows_what_went_in_and_out(self):
        config = load_config()
        data = rows(config)
        eff, hours = config["battery"]["efficiency"], 900 / 3600
        for before, after in zip(data, data[1:], strict=False):
            expected = before["stored_wh"] + (after["charge_w"] * eff - after["discharge_w"] / eff) * hours
            self.assertAlmostEqual(after["stored_wh"], expected, delta=1e-6)

    def test_there_is_no_export_when_it_is_not_allowed_and_no_grid_in_an_outage(self):
        configs = variants()
        self.assertTrue(all(r["export_w"] == 0.0 for r in rows(configs["noexport"])))
        during = [r for r in rows(configs["outage"]) if 3_600 <= r["t_s"] < 83_600]
        self.assertTrue(during and all(r["import_w"] == 0.0 and r["export_w"] == 0.0 and not r["mains"] for r in during))
        self.assertTrue(any(r["unserved_w"] > 0 for r in during), "a long outage must end by leaving some load without supply")

    def test_the_battery_does_cycle_in_a_normal_house(self):
        data = rows(days=3)
        self.assertGreater(max(r["soc_percent"] for r in data) - min(r["soc_percent"] for r in data), 20)
        self.assertGreater(data[-1]["cycles"], data[0]["cycles"])

    def test_the_voltage_of_a_cell_rises_with_the_charge(self):
        values = [cell_voltage(soc) for soc in range(0, 101)]
        self.assertTrue(all(b >= a for a, b in zip(values, values[1:], strict=False)))
        self.assertAlmostEqual(cell_voltage(-5), cell_voltage(0))
        self.assertAlmostEqual(cell_voltage(500), cell_voltage(100))


class DeterminismTests(unittest.TestCase):
    def test_the_same_seed_gives_the_same_data_and_another_seed_does_not(self):
        self.assertEqual(rows(seed=5), rows(seed=5))
        self.assertNotEqual([r["pv_w"] for r in rows(seed=5)], [r["pv_w"] for r in rows(seed=6)])

    def test_a_shorter_run_is_the_start_of_a_longer_one(self):
        self.assertEqual(rows(days=1), rows(days=2)[:96])

    def test_the_messages_are_the_same_too(self):
        config = load_config()
        self.assertEqual(list(energy_messages("n", config, 3, 96, 900)), list(energy_messages("n", config, 3, 96, 900)))

    def test_the_weekend_and_the_house_by_the_hour(self):
        data = rows(days=7)
        weekday_evening = [r["house_w"] for r in data if r["weekday"] < 5 and 20.5 <= r["hour"] < 21.5]
        small_hours = [r["house_w"] for r in data if 3 <= r["hour"] < 4]
        self.assertGreater(sum(weekday_evening) / len(weekday_evening), 2 * sum(small_hours) / len(small_hours))
        self.assertTrue(all(r["house_w"] >= 30.0 for r in data))


class TariffTests(unittest.TestCase):
    def test_the_price_follows_the_periods_and_the_weekend(self):
        config = load_config()
        self.assertEqual(price_at(config, 3 * 3600), 0.08)            # Monday 03:00, valley
        self.assertEqual(price_at(config, 11 * 3600), 0.24)           # Monday 11:00, peak
        self.assertEqual(price_at(config, 23 * 3600), 0.15)           # Monday 23:00, flat
        self.assertEqual(price_at(config, 5 * 86_400 + 11 * 3600), 0.08)   # Saturday 11:00: one price all day
        config["start_weekday"] = 5
        self.assertEqual(price_at(config, 11 * 3600), 0.08)
        self.assertEqual(price_at(config, 2 * 86_400 + 11 * 3600), 0.24)   # Monday again

    def test_every_row_carries_a_price_of_the_tariff(self):
        config = load_config()
        valid = {p["eur_kwh"] for p in config["tariff"]["periods"]} | {config["tariff"]["weekend_eur_kwh"]}
        self.assertTrue(all(r["price_eur_kwh"] in valid for r in rows(config, days=7)))

    def test_a_period_across_midnight_works_and_a_tariff_with_holes_or_overlaps_is_refused(self):
        config = load_config()
        config["tariff"]["periods"] = [{"from": "22:00", "to": "08:00", "name": "night", "eur_kwh": 0.05}, {"from": "08:00", "to": "22:00", "name": "day", "eur_kwh": 0.2}]
        check_config(config)
        self.assertEqual(price_at(config, 1 * 3600), 0.05)
        self.assertEqual(price_at(config, 23 * 3600), 0.05)
        self.assertEqual(price_at(config, 12 * 3600), 0.2)
        for periods in ([{"from": "00:00", "to": "12:00", "name": "a", "eur_kwh": 1.0}],
                        [{"from": "00:00", "to": "13:00", "name": "a", "eur_kwh": 1.0}, {"from": "12:00", "to": "24:00", "name": "b", "eur_kwh": 1.0}],
                        [{"from": "00:00", "to": "00:00", "name": "a", "eur_kwh": 1.0}]):
            broken = load_config()
            broken["tariff"]["periods"] = periods
            with self.assertRaises(ScenarioError):
                check_config(broken)


class MeterTests(unittest.TestCase):
    def test_the_meter_has_holes_only_when_asked_and_in_bursts(self):
        quiet = load_config()
        quiet["meter"]["dropout_probability"] = 0.0
        self.assertFalse(any(r["meter_gap"] for r in rows(quiet)))
        noisy = load_config()
        noisy["meter"].update(dropout_probability=0.1, dropout_burst_max=4)
        data = rows(noisy, days=5)
        gaps = [r["meter_gap"] for r in data]
        self.assertTrue(0.03 < sum(gaps) / len(gaps) < 0.5, sum(gaps) / len(gaps))
        longest = run_length = 0
        for gap in gaps:
            run_length = run_length + 1 if gap else 0
            longest = max(longest, run_length)
        self.assertGreaterEqual(longest, 2, "a hole usually lasts more than one reading")

    def test_the_meter_reads_the_truth_with_a_little_noise(self):
        data = [r for r in rows(days=5) if r["house_w"] > 500]
        errors = [abs(r["meter_house_w"] - r["house_w"]) / r["house_w"] for r in data]
        self.assertLess(sum(errors) / len(errors), 0.03)
        self.assertTrue(any(error > 0 for error in errors))


class ConfigTests(unittest.TestCase):
    def test_the_defaults_are_valid_and_a_file_changes_only_what_it_says(self):
        config = load_config()
        self.assertEqual(config, DEFAULTS)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "c.json"
            path.write_text(json.dumps({"schema": "armor-energy-model/1", "pv": {"peak_w": 1000}}), encoding="utf-8")
            changed = load_config(path)
        self.assertEqual(changed["pv"]["peak_w"], 1000)
        self.assertEqual(changed["pv"]["mean_cloud"], DEFAULTS["pv"]["mean_cloud"])

    def test_the_examples_are_valid(self):
        self.assertGreaterEqual(len(CONFIGS), 2)
        for path in CONFIGS:
            load_config(path)

    def test_anything_that_is_not_understood_is_refused(self):
        bad = [
            {"pv": {"peak_watts": 1}}, {"solar": {}}, {"pv": 3}, {"pv": {"peak_w": "big"}}, {"pv": {"peak_w": True}}, {"pv": {"mean_cloud": 1.5}}, {"pv": {"peak_w": -1}},
            {"sun": {"sunrise_h": 20, "sunset_h": 6}}, {"battery": {"modules": 0}}, {"battery": {"modules": 2.5}}, {"battery": {"efficiency": 1.2}},
            {"battery": {"initial_soc": 5, "min_soc": 10}}, {"grid": {"export": "yes"}}, {"grid": {"outages": [{"at_s": 1}]}}, {"grid": {"outages": [{"at_s": 1, "duration_s": 0}]}},
            {"meter": {"dropout_burst_max": 0}}, {"start_weekday": 7}, {"tariff": {"periods": "all"}}, {"tariff": {"weekend_eur_kwh": -1}}, [],
        ]
        for data in bad:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "c.json"
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(ScenarioError, msg=data):
                    load_config(path)

    def test_the_defaults_are_not_changed_by_a_run(self):
        before = copy.deepcopy(DEFAULTS)
        rows(load_config())
        list(energy_messages("n", load_config(), 1, 10, 900))
        self.assertEqual(DEFAULTS, before)


@unittest.skipUnless(HAS_ARMOR_COMMON, "ARMOR-COMMON is not next to this repository")
class ContractTests(unittest.TestCase):
    def test_every_message_is_valid_for_the_contracts_with_any_configuration(self):
        for path in [None, *CONFIGS]:
            args = ["--energy", "--validate", "--energy-days", "2", "--seed", "4"] + (["--energy-config", str(path)] if path else [])
            code, out, err = run(*args)
            self.assertEqual(code, 0, f"{path}: {err}")
            self.assertGreater(len(out.splitlines()), 100)

    def test_the_extreme_configurations_are_valid_too(self):
        from armor_common.contracts import validate_electrical_message, validate_solar_message
        for config in variants().values():
            for topic, payload in energy_messages("node-1", config, 2, 192, 900):
                (validate_electrical_message if "/electrical/" in topic else validate_solar_message)(topic, payload)


class MessageTests(unittest.TestCase):
    def test_a_step_gives_an_inverter_and_a_battery_and_the_meter_when_it_is_not_in_a_hole(self):
        config = load_config()
        data = rows(config, seed=2, days=1)
        messages = list(energy_messages("n", config, 2, 96, 900))
        for step, row in enumerate(data):
            here = [t for t, p in messages if p["timestamp_ms"] == row["t_s"] * 1000]
            self.assertIn("armor/solar/n/axpert-1/state", here)
            self.assertIn("armor/solar/n/us3000-1/state", here)
            self.assertEqual("armor/electrical/n/state" in here, not row["meter_gap"], step)

    def test_the_inverter_and_the_battery_tell_the_same_story(self):
        messages = list(energy_messages("n", load_config(), 2, 96, 900))
        inverters = {p["timestamp_ms"]: p for t, p in messages if t.endswith("axpert-1/state")}
        batteries = {p["timestamp_ms"]: p for t, p in messages if t.endswith("us3000-1/state")}
        for stamp, inverter in inverters.items():
            battery = batteries[stamp]
            self.assertEqual(inverter["battery_percent"], battery["soc_percent"])
            self.assertAlmostEqual(inverter["battery_v"], battery["voltage_v"], delta=0.01)
            self.assertAlmostEqual(inverter["battery_a"], battery["current_a"], delta=0.06)
            self.assertTrue(0 <= battery["soc_percent"] <= 100)
            if inverter["pv_w"] == 0:
                self.assertEqual(inverter["pv_v"], 0.0)

    def test_the_day_has_a_night_without_pv_in_the_messages_too(self):
        night = [p for t, p in energy_messages("n", load_config(), 1, 96, 900) if t.endswith("axpert-1/state") and (p["timestamp_ms"] // 3_600_000) % 24 < 5]
        self.assertTrue(night and all(p["pv_w"] == 0 for p in night))


class CommandLineTests(unittest.TestCase):
    def test_the_data_are_stamped_in_real_time_and_the_start_date_shifts_them(self):
        code, out, _ = run("--energy", "--energy-days", "1", "--energy-step-s", "3600")
        self.assertEqual(code, 0)
        stamps = sorted({json.loads(line)["payload"]["timestamp_ms"] for line in out.splitlines()})
        self.assertEqual(stamps, [h * 3_600_000 for h in range(24)])
        code, shifted, _ = run("--energy", "--energy-days", "1", "--energy-step-s", "3600", "--start-ms", "1000000")
        self.assertEqual(json.loads(shifted.splitlines()[0])["payload"]["timestamp_ms"], 1_000_000)

    def test_faults_apply_to_the_energy_messages(self):
        code, out, _ = run("--energy", "--energy-days", "1", "--fault", "node-silent", "--fault-every", "5", "--fault-topic", "solar")
        self.assertEqual(code, 0)
        self.assertEqual(sum(1 for line in out.splitlines() if "/solar/" in line), 5)
        self.assertEqual(run("--fault", "node-silent", "--fault-topic", "solar")[0], 2, "without --energy or --solar there is nothing to spoil")

    def test_combinations_and_limits_that_make_no_sense_are_refused(self):
        for args in (["--energy", "--solar"], ["--energy", "--electrical"], ["--energy", "--count", "5"], ["--energy", "--energy-days", "0"], ["--energy", "--energy-days", "400"],
                     ["--energy", "--energy-step-s", "0"], ["--energy", "--energy-step-s", "7200"], ["--energy", "--energy-days", "366", "--energy-step-s", "60"], ["--energy-config", "x.json"]):
            self.assertEqual(run(*args)[0], 2, args)
        code, out, err = run("--energy", "--energy-config", str(ROOT / "examples" / "missing.json"))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("energy configuration", err)

    def test_without_the_option_nothing_changes(self):
        _, out, _ = run("--count", "10", "--solar", "--electrical", "--seed", "9")
        self.assertIn("armor/solar/simulator-1/axpert-1/state", out)
        self.assertNotIn("us3000-1", run("--count", "3")[1])


if __name__ == "__main__":
    unittest.main()
