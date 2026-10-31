# Energy model

`--energy` replaces the fast day of `--solar` and `--electrical` (240 samples to exercise a consumer) with data that looks like an installation: **real time** (a sample is `--energy-step-s` seconds, 900 by default; a day is 86 400 s), a sun with clouds, a house that eats by the hour, a tariff, a Pylontech-style battery with cycles, and a meter that is noisy and now and then silent.

```powershell
$env:PYTHONPATH="src"
python -m armor_simulator --energy --energy-days 3 --seed 5 --validate
python -m armor_simulator --energy --energy-config examples/energy/cloudy-winter.json --energy-days 2
```

| Option | Default | Meaning |
|---|---|---|
| `--energy` | off | Emit an inverter (`armor/solar/<node>/axpert-1/state`), a battery stack (`.../us3000-1/state`) and an electrical node (`armor/electrical/<node>/state`) from the model; without it nothing changes |
| `--energy-config FILE` | built-in settings | A JSON file; it overrides only what it names |
| `--energy-days` | `1` | Days of data, up to 366 |
| `--energy-step-s` | `900` | Seconds per sample, 1 to 3600; days divided by step must give 1 to 10 000 samples |
| `--seed` | `0` | Same seed and same settings, same data; a shorter run is the start of a longer one |

It cannot be combined with `--solar`, `--electrical`, `--count` or `--alarm-scenario`. `--start-ms`, `--fault`, `--fault-topic` (`solar` and `electrical` apply), `--validate` and delivery to a server work as usual. Samples are dated from second 0 (the first sample is at 0 ms plus `--start-ms`).

## What it guarantees

The tests check these for many seeds and for extreme settings (a tiny battery, a huge array, a house that eats more than the array gives, total cloud, a day-long outage, no export):

* **No production at night:** `pv_w` is exactly 0 outside `sun.sunrise_h`..`sun.sunset_h`, and never negative.
* **State of charge** always between `battery.min_soc` and 100 %.
* **Energy balances** at every step: panels + battery output + grid import = the house (minus load left without supply) + battery input + export + curtailed. No flow is negative, the battery never charges and discharges in the same step, the house never buys and sells in the same step, and the battery respects `max_charge_w` and `max_discharge_w`. Stored energy follows what went in and out with the round-trip `efficiency`.
* **Counters only go up** (import, export, load, production, charge, discharge) and so do the cycles.
* **The price** is always one of the tariff.
* **Every message is valid** for the solar and electrical contracts of ARMOR-COMMON.

## The settings

All tuning lives in the file; the built-in values are in `DEFAULTS` (`src/armor_simulator/energy.py`). A key that does not exist, a value of the wrong type or outside its range, or a tariff that does not cover every minute of the day exactly once refuses the file.

| Section | Settings |
|---|---|
| `sun` | `sunrise_h`, `sunset_h` (hours of day, sunrise before sunset), `shape` (how peaked the curve is) |
| `pv` | `peak_w` (clear sky at noon), `mean_cloud` (0 clear to 1 overcast), `cloud_persistence` (how slowly clouds change), `cloud_variability`, `cloud_loss` (share of the sun a full cloud takes), `noise_w` |
| `load` | `base_w`, `morning_peak_w`, `evening_peak_w`, `noise_w`, `weekend_factor`, `appliance_w`, `appliances_per_day`, `appliance_minutes` |
| `tariff` | `periods`: `{from, to, name, eur_kwh}` covering the day once (a period may cross midnight), `weekend_eur_kwh` (one price all day on Saturday and Sunday), `export_eur_kwh` |
| `battery` | `modules`, `module_ah`, `nominal_v`, `min_soc`, `initial_soc`, `max_charge_w`, `max_discharge_w`, `efficiency`, `initial_cycles` |
| `grid` | `export` (false curtails the surplus), `voltage_v`, `voltage_noise_v`, `outages`: `{at_s, duration_s}` (no grid: nothing imported or exported, the battery covers the house until it reaches `min_soc`, and what it cannot cover is left without supply) |
| `meter` | `noise_percent`, `dropout_probability`, `dropout_burst_max` (a hole lasts 1 to that many samples; the step has no electrical message while it lasts) |
| `start_weekday` | 0 (Monday) to 6 |

A file may carry `"schema": "armor-energy-model/1"`. The examples are in `examples/energy/`.

## What this is and is not

It is a plausible model, not a measurement: nothing here says how a real panel, inverter, battery or meter behaves, and no data of a real installation was used to tune it. The state of charge is that of the battery model, not what an inverter would estimate.
