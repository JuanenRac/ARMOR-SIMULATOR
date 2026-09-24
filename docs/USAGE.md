# Simulator usage

```powershell
$env:PYTHONPATH="src"
python -m armor_simulator --count 20 --scenario crossing --seed 1 --validate
```

Each output line is an MQTT-ready envelope `{"topic": ..., "payload": ...}` with
stable key order, so the same command always prints the same lines. Nothing is
transmitted unless you ask for it: publishing to a broker is deliberately not
built in, so a test can never reach a production broker by accident.

## Options

| Option | Meaning |
|---|---|
| `--node-id` | Node identifier (lowercase letters, digits, `-`, `_`; up to 64) |
| `--count` | Samples to generate, 1 to 10 000; one sample is one second of simulated time |
| `--scenario` | `patrol`, `crossing`, `two-intruders` or `empty` |
| `--light` | `cycle` (day and night) or `night` (fixed 0.3 lux, for the low-light vision profile) |
| `--seed` | Same seed, same output |
| `--health-every` | One health message every N samples (0 disables) |
| `--fault`, `--fault-every` | Inject a repeatable fault (below) |
| `--allow-invalid` | Required for faults that break the contract on purpose |
| `--validate` | Check every message against ARMOR-COMMON before it is emitted |
| `--interval-ms` | Real pause between messages |
| `--server-url`, `--ingest-token` | Deliver to an ARMOR-SERVER (both are needed; the token is never written anywhere) |

## Scenarios

The geometry is illustrative, not a model of the real hardware: a node covers a
90 degree corner with three sensors facing -45, 0 and +45 degrees, each seeing
about ±60 degrees out to 6 m, and at most five targets per sensor. A person
outside every field of view is simply not reported.

* `patrol`: one target circling at 3 m; it leaves and re-enters the field of view.
* `crossing`: a person crossing left to right at about 1.2 m/s, handed from sensor 1 to sensor 3.
* `two-intruders`: two people approaching; two tracks raise a **high** alert while the system is armed.
* `empty`: a quiet perimeter.

## Faults

| Fault | Effect | Valid messages? |
|---|---|---|
| `node-silent` | The node stops after N messages: the server must show it stale, then offline | yes |
| `out-of-order` | Every Nth message carries an older timestamp: it must be ignored | yes |
| `duplicates` | Every Nth message is delivered twice (what MQTT QoS 1 does) | yes |
| `flapping` | Some health messages report the node offline | yes |
| `corrupt-lux` | Lux above the sensor limit | **no** |
| `unknown-field` | A field the contract does not define | **no** |
| `oversized-targets` | More than 15 tracks | **no** |

Faults that produce invalid messages need `--allow-invalid` and cannot be combined
with `--validate`. When delivering to a server, a refusal of such a message is
expected and is reported without stopping the run.

## Delivering to a server

```powershell
python -m armor_simulator --count 60 --scenario two-intruders --server-url http://127.0.0.1:8080 --ingest-token <ingest token>
```

Only a plain `http(s)://host[:port]` origin is accepted. A 4xx answer stops the
run at once (the message or the token is wrong); a network error or a 5xx is
retried three times.
