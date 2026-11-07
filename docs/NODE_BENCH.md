# The simulation bench

The simulator can play the equipment around the field nodes and the installation around the server, so that the software of the system can be tried against both without a board,
a broker in the house or Docker. Two benches exist, and the pages below say what a green run of each one does and does not prove.

## 1. The buses of the nodes, into the real firmware code

`python -m armor_simulator.node_bench --bus <bus> --driver <program>` generates the traffic of one bus (`armor_simulator/buses.py`), spoils it in the ways listed below, hands it to a
driver and compares what the driver answers with what it must answer. The driver is `tests/sim_bench.cpp` in each node repository: a short program built with any C++17 compiler
from the same core files the firmware is built from (no ESP-IDF, no board), so the code that frames, checks and decodes the bytes is the code that runs on the node.

| Bus | Node | What the firmware code does with it | Faults injected |
| --- | --- | --- | --- |
| `ld2450` | ARMOR-NODE-RADAR | frames the serial stream of the HLK-LD2450 modules and turns the targets into tracks | noise between frames, frames cut short, a bad tail, a target beyond what the module can measure, a target without resolution, a target at the origin, the stream handed over in pieces, silence |
| `pzem` | ARMOR-NODE-ELECTRICAL | checks and decodes the Modbus-RTU replies of the PZEM-004T and PZEM-017 meters (the replies are the ones of `meter_bus.py`) | a flipped bit, an exception, a silent meter, a short reply, a long reply, the reply of another meter, a reading no meter could give |
| `pylontech` | ARMOR-NODE-SOLAR | reads the `pwr` table and the `bat` table printed by the console of a Pylontech stack | an absent module, a garbled row, no header, the prompt after the table, a cell voltage out of range, cells out of order |
| `alarm-loop` | ARMOR-NODE-ALARM | classifies the voltage of a wired loop and holds it for 200 ms before it counts | a bouncing contact, noise, a converter still settling at power-up, a cut wire, a shorted wire, a slow opening |
| `hmi-feed` | ARMOR-NODE-HMI | reads the frames of the live channel of the server and keeps the summary | a frame of another type, text that is not JSON, a frame cut in half, an unknown mode, a missing block, a frame over the size limit, a silent alarm code, more alarms than fit, heartbeats beyond the limits |

Every case carries the answer it must get, worked out in `buses.py` from the rules each firmware file documents, not by running the firmware, so a run is a comparison between two
separate statements of the same rules. `--fault` plays only some of the faults, `--seed` changes the data, `--record FILE` writes the cases as JSON lines and `--replay FILE`
plays them again later (an existing file is never overwritten). The exit status is 0 when every case passes, 1 when one differs and 2 when the run could not be made.

To try one by hand from the repository of a node (the simulator next to it):

    g++ -std=c++17 -Wall -Wextra -Wpedantic -Werror -O1 -o sim_bench tests/sim_bench.cpp
    PYTHONPATH=../ARMOR-SIMULATOR/src python -m armor_simulator.node_bench --bus ld2450 --driver ./sim_bench

The format between the two sides is one case per line on the standard input of the driver (`bus`, `id`, `arg`, `payload`, tab separated) and one `id`, tab, answer per case on its
standard output. A new node only needs a driver that speaks it.

**What it proves.** The code that reads each bus copes with well-formed input and with the faults above, and answers as the documented rules say. **What it does not.** The data is made
up from the descriptions the firmware files cite; nothing has been compared with the real equipment, with its timing or with its electrical behaviour. Those checks need the board.

## 2. The server, without Docker

`python -m armor_simulator.bench_ci --server-dir <ARMOR-SERVER, built>` is `docker/bench.sh` without Docker. It starts the built server on a free loopback port with secrets made up for
the run, feeds it with the simulator and checks the status of the server after each step: patrol, solar and electrical messages over HTTP; impossible readings refused; a message sent
twice and a slow link; a recording of the traffic of a server played again (`examples/recordings/incident.jsonl` and `examples/recordings/http_routes.jsonl`, the second with the HTTP reports of an alarm panel, a meter, solar equipment and a network node: the accepted messages arrive and the refused one is refused again
for the same reason); two fake IP cameras (a walker, and one that answers an error on purpose) configured in the server by its own route, whose picture reaches the preview of the server through a ticket as a real PNG while the broken one is a clean refusal; and, when `mosquitto` is installed (`--mosquitto auto`) and `paho-mqtt` too, a node that exists only on the broker. It removes its temporary folder and stops only
the processes it started.

The workflow `Simulation bench` runs it on every push and once a week. What it does not replace: the Docker image, its healthcheck and the real Mosquitto settings of the CM5 profile.

## 3. The MQTT shim: the message code of a node, publishing

`python -m armor_simulator.node_shim --driver <program> --node-id <id> --mqtt-url mqtt://127.0.0.1:1883` plays the serial stream of the radar modules, one chunk per line, into
`tests/mqtt_shim.cpp` of ARMOR-NODE-RADAR. That program is built from the same core files as the firmware (framer, LD2450 decoder, track builder, `build_info`, `build_health`,
`build_telemetry`, `build_topic`) and prints one `topic`, tab, `payload` line per message; the simulator publishes each line on the broker with QoS 1. The broker must be on this machine or
a private network. In the server bench (`bench_ci --mosquitto auto --shim-driver <program>`) the node then has to show in the status of the real server. ARMOR-NODE-ELECTRICAL has one too (`--node electrical`): the Modbus replies of the meter bus go through the real PZEM decoder and the writer of the electrical message, and the server bench (`--shim-electrical-driver`) checks that the meters show in its readings. Nodes are added one at a time,
each with a shim program of its own in its repository.

**What it proves.** The messages the code of the node writes are accepted by the real server over the real broker. **What it does not.** The Wi-Fi or Ethernet link, the TLS session, the
broker client of the board and the clock of the board; those need the board.
