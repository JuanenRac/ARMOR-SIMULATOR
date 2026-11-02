# The meter bus

`--meter-bus-port PORT` plays the serial line of the energy meters over TCP, so the code that reads them (the CRC, the frames, the addresses, the timeouts, a meter that stays silent) can be tried without a meter. The other options of this simulator emit what a *node* publishes; this one plays the *meters* a node reads.

```powershell
python -m armor_simulator --meter-bus-port 5020
python -m armor_simulator --meter-bus-port 0 --meter-bus-config my-bus.json --meter-bus-seconds 60
```

It listens on the loopback only (`--meter-bus-host` and `--meter-bus-allow-network` if it must be reached from another computer: the bus has no authentication), prints the port it took, and counts at the end the requests, the replies, the requests left without an answer and the writes it refused. `--meter-bus-port` cannot be combined with the options that emit messages.

## What it answers

Modbus-RTU frames (address, function, data, CRC-16/MODBUS with the low byte first), the way a PZEM-004T v3 (AC) and a PZEM-017 (DC) answer them, from the makers' public description as written in ARMOR-NODE-ELECTRICAL. Nothing here has been compared with a real meter.

| Request | Answer |
|---|---|
| function `0x04`, input registers | the measurements: PZEM-004T v3, ten registers from 0 (voltage 0.1 V, current 0.001 A and power 0.1 W and energy 1 Wh in two registers each with the low word first, frequency 0.1 Hz, power factor 0.01, alarm 0xFFFF); PZEM-017, eight registers (voltage 0.01 V, current 0.01 A, power and energy as above, high and low voltage alarm) |
| function `0x03`, holding registers | the settings the meter keeps: PZEM-004T v3 two registers from 1 (power alarm threshold, address); PZEM-017 four registers from 0 (high and low voltage threshold, address, shunt code) |
| a part of the registers | answered when it lies inside the block; a read outside it gets the exception `0x02` (illegal data address) |
| `0x06`, `0x10`, `0x42` and any other function | the exception `0x01` (illegal function); the writes are counted and **nothing changes**: the bus is read only, like the node |
| a frame whose CRC does not fit, or an address no meter has | no answer at all, as a real meter does |
| address `0xF8` | the first meter answers, whatever its own address |

The readings are the ones of `--electrical` (`electrical.py`): the grid input, the water heater and the DC bus over a fast day, with the mains outage, the spell of high voltage and the meter alarm. The sample of the day advances with real time, `speed` samples per second. The PZEM-017 has a shunt and gives no sign: a battery that gives and one that takes read the same.

## The settings file

Every setting lives in a JSON file, `--meter-bus-config FILE` (schema `armor-meter-bus/1`, up to 64 KiB, read strictly: whatever is not understood refuses the whole file and the exit code is 2). Without a file the three meters of `--electrical` answer.

```json
{
  "schema": "armor-meter-bus/1",
  "node_id": "simulator-1",
  "seed": 0,
  "speed": 1.0,
  "meters": [
    {"address": 1, "model": "pzem-004t", "channel": "grid", "power_alarm_w": 2300},
    {"address": 2, "model": "pzem-004t", "channel": "heater"},
    {"address": 7, "model": "pzem-017", "channel": "dc-bus", "high_voltage_v": 58.0, "low_voltage_v": 44.0, "shunt_a": 100}
  ],
  "faults": [
    {"kind": "silent", "address": 2},
    {"kind": "corrupt", "address": 1, "every": 5}
  ]
}
```

| Field | Meaning |
|---|---|
| `meters[].address` | 1 to 247, one per meter |
| `meters[].model` | `pzem-004t` (reads `grid` or `heater`) or `pzem-017` (reads `dc-bus`) |
| `meters[].power_alarm_w` | PZEM-004T: the power alarm threshold the meter keeps, 0 to 22000 W |
| `meters[].high_voltage_v`, `low_voltage_v` | PZEM-017: the alarm thresholds, which also set its alarm registers from the voltage read |
| `meters[].shunt_a` | PZEM-017: 50, 100, 200 or 300 |
| `speed` | samples of the day per real second, 0 to 1000 (0 freezes the day) |
| `faults[].kind` | `silent` (never answers), `corrupt` (a bit of the reply is flipped after its CRC, so the node must refuse it) or `exception` (answers "illegal data address") |
| `faults[].every` | the fault strikes every Nth request to that meter (default 1) |

## What is tried with it, and what is not

It exercises, without hardware, the framing and the CRC of the node, its handling of a silent, garbled or refusing meter, and the sequence of questions on a shared line. It does not tell how a real meter behaves on a real line (timing between frames, noise, the RS-485 direction pin): that stays to be tried with a meter.
