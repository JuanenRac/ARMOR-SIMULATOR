"""The meter bus: the CRC, the frames of a PZEM-004T and a PZEM-017, what is refused, the faults, the file of settings, the TCP line and the command line.

The decoder below is a second, independent reading of the makers' register map (the one ARMOR-NODE-ELECTRICAL decodes), so the bus and the node cannot agree by accident.
"""
import contextlib
import io
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from armor_simulator import cli
from armor_simulator.electrical import electrical
from armor_simulator.meter_bus import (BusConfig, Fault, Meter, MeterBus, MeterBusError, crc16, default_config, load_config, parse_config, request_length, serve, stop,
                                        with_crc)

AC_REQUEST_1 = bytes.fromhex("01 04 00 00 00 0A 70 0D")      # the request the PZEM-004T's own description shows


def request(address: int, function: int, first: int, count: int) -> bytes:
    return with_crc(bytes((address, function)) + first.to_bytes(2, "big") + count.to_bytes(2, "big"))


def registers(reply: bytes) -> list[int]:
    assert crc16(reply) == 0, "a reply with its own CRC checks to zero"
    assert reply[2] == len(reply) - 5
    return [int.from_bytes(reply[3 + i:5 + i], "big") for i in range(0, reply[2], 2)]


def decode_ac(reply: bytes) -> dict:
    r = registers(reply)
    return {"v": r[0] / 10, "a": (r[1] | r[2] << 16) / 1000, "w": (r[3] | r[4] << 16) / 10, "kwh": (r[5] | r[6] << 16) / 1000, "hz": r[7] / 10, "pf": r[8] / 100, "alarm": r[9] == 0xFFFF}


def decode_dc(reply: bytes) -> dict:
    r = registers(reply)
    return {"v": r[0] / 100, "a": r[1] / 100, "w": (r[2] | r[3] << 16) / 10, "kwh": (r[4] | r[5] << 16) / 1000, "high": r[6] == 0xFFFF, "low": r[7] == 0xFFFF}


def bus(sample: int = 10, **kwargs) -> MeterBus:
    return MeterBus(kwargs.pop("config", default_config()), lambda: sample, **kwargs)


class Crc(unittest.TestCase):
    def test_known_values(self):
        self.assertEqual(crc16(bytes.fromhex("01 03 00 00 00 0A")), 0xCDC5)      # the well-known Modbus example
        self.assertEqual(crc16(b""), 0xFFFF)
        self.assertEqual(crc16(bytes.fromhex("01 04 00 00 00 0A")), 0x0D70)
        self.assertEqual(with_crc(bytes.fromhex("01 04 00 00 00 0A")), AC_REQUEST_1)


class Reads(unittest.TestCase):
    def test_the_ac_meter_gives_the_channel_it_reads(self):
        for sample in (0, 10, 77, 190, 237):
            reply = bus(sample).answer(AC_REQUEST_1)
            self.assertEqual(len(reply), 25)
            channel = electrical("simulator-1", sample, 0)["channels"][0]
            got = decode_ac(reply)
            self.assertAlmostEqual(got["v"], channel["voltage_v"], delta=0.05)
            self.assertAlmostEqual(got["a"], channel["current_a"], delta=0.0006)
            self.assertAlmostEqual(got["w"], channel["power_w"], delta=0.06)
            self.assertAlmostEqual(got["kwh"], channel["energy_kwh"], delta=0.0006)
            self.assertAlmostEqual(got["hz"], channel["frequency_hz"], delta=0.06)
            self.assertAlmostEqual(got["pf"], channel["power_factor"], delta=0.006)

    def test_the_dc_meter_gives_the_bus_without_the_sign(self):
        reply = bus(50).answer(request(7, 4, 0, 8))
        self.assertEqual(len(reply), 21)
        channel = electrical("simulator-1", 50, 0)["channels"][2]
        got = decode_dc(reply)
        self.assertAlmostEqual(got["v"], channel["voltage_v"], delta=0.006)
        self.assertAlmostEqual(got["a"], abs(channel["current_a"]), delta=0.006)
        self.assertAlmostEqual(got["w"], abs(channel["power_w"]), delta=0.06)
        self.assertFalse(got["high"] or got["low"])

    def test_the_outage_reads_zero(self):
        outage = next(s for s in range(240) if electrical("x", s, 0)["channels"][0]["voltage_v"] == 0)
        got = decode_ac(bus(outage).answer(AC_REQUEST_1))
        self.assertEqual((got["v"], got["a"], got["w"], got["hz"]), (0, 0, 0, 0))

    def test_the_meter_alarm_and_the_thresholds(self):
        alarm = next(s for s in range(240) if electrical("x", s, 0)["channels"][1]["alarm"])
        self.assertTrue(decode_ac(bus(alarm).answer(request(2, 4, 0, 10)))["alarm"])
        self.assertFalse(decode_ac(bus(0).answer(request(2, 4, 0, 10)))["alarm"])
        config = BusConfig((Meter(7, "pzem-017", "dc-bus", high_voltage_v=1.0), ))
        self.assertTrue(decode_dc(bus(5, config=config).answer(request(7, 4, 0, 8)))["high"])
        config = BusConfig((Meter(7, "pzem-017", "dc-bus", low_voltage_v=99.0), ))
        self.assertTrue(decode_dc(bus(5, config=config).answer(request(7, 4, 0, 8)))["low"])

    def test_a_part_of_the_registers_and_the_limits(self):
        self.assertEqual(len(registers(bus().answer(request(1, 4, 3, 2)))), 2)
        self.assertEqual(registers(bus().answer(request(1, 4, 0, 10)))[3:5], registers(bus().answer(request(1, 4, 3, 2))))
        for first, count in ((0, 11), (9, 2), (0, 0), (10, 1)):
            reply = bus().answer(request(1, 4, first, count))
            self.assertEqual(reply[1:3], bytes((0x84, 0x02)), (first, count))
            self.assertEqual(crc16(reply), 0)

    def test_any_address_answers_as_the_first_meter(self):
        self.assertEqual(bus().answer(request(0xF8, 4, 0, 10))[0], 0xF8)
        self.assertEqual(registers(bus().answer(request(0xF8, 4, 0, 10))), registers(bus().answer(request(1, 4, 0, 10))))

    def test_other_addresses_are_not_answered(self):
        b = bus()
        for address in (3, 4, 100, 247):
            self.assertIsNone(b.answer(request(address, 4, 0, 10)))
        self.assertEqual(b.silent, 4)

    def test_the_settings_the_meters_keep(self):
        self.assertEqual(registers(bus().answer(request(1, 3, 1, 2))), [2300, 1])
        self.assertEqual(registers(bus().answer(request(7, 3, 0, 4))), [5800, 4400, 7, 0])
        self.assertEqual(bus().answer(request(7, 3, 0, 5))[1], 0x83)
        config = parse_config({"schema": "armor-meter-bus/1", "meters": [{"address": 9, "model": "pzem-017", "channel": "dc-bus", "shunt_a": 300}]})
        self.assertEqual(registers(bus(config=config).answer(request(9, 3, 0, 4)))[3], 3)

    def test_the_values_are_deterministic(self):
        self.assertEqual(bus(33).answer(AC_REQUEST_1), bus(33).answer(AC_REQUEST_1))


class Refusals(unittest.TestCase):
    def test_a_bad_crc_gets_no_answer(self):
        b = bus()
        broken = bytearray(AC_REQUEST_1)
        broken[7] ^= 0xFF
        self.assertIsNone(b.answer(bytes(broken)))
        self.assertIsNone(b.answer(b"\x01\x04"))
        self.assertIsNone(b.answer(b""))
        self.assertEqual(b.bad_crc, 3)

    def test_nothing_can_be_written(self):
        b = bus()
        before = b.answer(AC_REQUEST_1)
        writes = [request(1, 6, 2, 1000),                                   # the alarm threshold
                  with_crc(bytes.fromhex("01 10 00 02 00 01 02 03 E8")),    # several registers
                  with_crc(bytes.fromhex("01 42")),                         # the reset of the energy counter
                  request(1, 5, 0, 0xFF00), request(1, 0x2B, 0, 0)]
        for frame in writes:
            reply = b.answer(frame)
            self.assertEqual(reply[:3], bytes((1, frame[1] | 0x80, 0x01)), frame.hex())
            self.assertEqual(crc16(reply), 0)
        self.assertEqual(b.refused_writes, 3)
        self.assertEqual(b.answer(AC_REQUEST_1), before)
        self.assertEqual(registers(b.answer(request(1, 3, 1, 2))), [2300, 1])


class Faults(unittest.TestCase):
    def config(self, *faults: Fault) -> BusConfig:
        return BusConfig(default_config().meters, faults)

    def test_silent(self):
        b = bus(config=self.config(Fault("silent", 2)))
        self.assertIsNone(b.answer(request(2, 4, 0, 10)))
        self.assertIsNotNone(b.answer(request(1, 4, 0, 10)))

    def test_corrupt_every_second_reply(self):
        b = bus(config=self.config(Fault("corrupt", 1, every=2)))
        first, second, third = (b.answer(AC_REQUEST_1) for _ in range(3))
        self.assertEqual(crc16(first), 0)
        self.assertNotEqual(crc16(second), 0)
        self.assertEqual(crc16(third), 0)

    def test_exception_replies(self):
        reply = bus(config=self.config(Fault("exception", 7))).answer(request(7, 4, 0, 8))
        self.assertEqual(reply[1:3], bytes((0x84, 0x02)))


class Settings(unittest.TestCase):
    GOOD = {"schema": "armor-meter-bus/1", "speed": 2, "meters": [{"address": 5, "model": "pzem-004t", "channel": "grid"}], "faults": [{"kind": "silent", "address": 5, "every": 3}]}

    def test_a_good_file(self):
        config = parse_config(self.GOOD)
        self.assertEqual((config.meters[0].address, config.speed, config.faults[0].every), (5, 2.0, 3))

    def test_every_mistake_is_refused(self):
        def changed(**kw):
            d = json.loads(json.dumps(self.GOOD))
            d.update(kw)
            return d
        bad = [[], {}, changed(schema="x"), changed(extra=1), changed(meters=[]), changed(meters="a"), changed(speed=5000), changed(speed=True), changed(seed=-1),
               changed(node_id=""), changed(faults={}), changed(faults=[{"kind": "boom", "address": 5}]), changed(faults=[{"kind": "silent", "address": 6}]),
               changed(faults=[{"kind": "silent", "address": 5, "every": 0}]), changed(faults=[{"kind": "silent", "address": 5, "x": 1}]),
               changed(meters=[{"address": 0, "model": "pzem-004t", "channel": "grid"}]), changed(meters=[{"address": 248, "model": "pzem-004t", "channel": "grid"}]),
               changed(meters=[{"address": 1, "model": "pzem-004t", "channel": "dc-bus"}]), changed(meters=[{"address": 1, "model": "pzem-017", "channel": "grid"}]),
               changed(meters=[{"address": 1, "model": "other", "channel": "grid"}]), changed(meters=[{"address": 1, "model": "pzem-004t", "channel": "grid", "x": 1}]),
               changed(meters=[{"address": 1, "model": "pzem-017", "channel": "dc-bus", "shunt_a": 70}]),
               changed(meters=[{"address": 1, "model": "pzem-004t", "channel": "grid"}, {"address": 1, "model": "pzem-004t", "channel": "heater"}])]
        for document in bad:
            with self.assertRaises(MeterBusError, msg=str(document)[:80]):
                parse_config(document)

    def test_the_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bus.json"
            path.write_text(json.dumps(self.GOOD), encoding="utf-8")
            self.assertEqual(load_config(path).meters[0].address, 5)
            path.write_text('{"schema": "armor-meter-bus/1", "speed": NaN}', encoding="utf-8")
            with self.assertRaises(MeterBusError):
                load_config(path)
            path.write_text("{", encoding="utf-8")
            with self.assertRaises(MeterBusError):
                load_config(path)
            path.write_bytes(b"x" * 70000)
            with self.assertRaises(MeterBusError):
                load_config(path)
            with self.assertRaises(MeterBusError):
                load_config(Path(folder) / "none.json")
        self.assertEqual(len(load_config(None).meters), 3)


class Framing(unittest.TestCase):
    def test_lengths(self):
        self.assertIsNone(request_length(b"\x01"))
        self.assertEqual(request_length(AC_REQUEST_1), 8)
        self.assertEqual(request_length(bytes.fromhex("01 42")), 4)
        self.assertIsNone(request_length(bytes.fromhex("01 10 00 02 00 01")))
        self.assertEqual(request_length(bytes.fromhex("01 10 00 02 00 01 02")), 11)


def exchange(sock: socket.socket, frame: bytes, expect: int) -> bytes:
    sock.sendall(frame)
    data = b""
    while len(data) < expect:
        chunk = sock.recv(64)
        if not chunk:
            break
        data += chunk
    return data


class Line(unittest.TestCase):
    def setUp(self):
        self.bus = bus()
        self.server, _ = serve(self.bus)
        self.port = self.server.server_address[1]

    def tearDown(self):
        stop(self.server)

    def connect(self) -> socket.socket:
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        self.addCleanup(sock.close)
        return sock

    def test_a_request_gets_its_reply(self):
        sock = self.connect()
        reply = exchange(sock, AC_REQUEST_1, 25)
        self.assertEqual(reply, bus().answer(AC_REQUEST_1))
        self.assertEqual(len(exchange(sock, request(7, 4, 0, 8), 21)), 21)

    def test_two_requests_in_one_packet_and_one_in_pieces(self):
        sock = self.connect()
        reply = exchange(sock, AC_REQUEST_1 + request(7, 4, 0, 8), 46)
        self.assertEqual(len(reply), 46)
        sock.sendall(AC_REQUEST_1[:3])
        sock.settimeout(5)
        sock.sendall(AC_REQUEST_1[3:])
        self.assertEqual(len(exchange(sock, b"", 25)), 25)

    def test_a_bad_frame_is_not_answered_and_the_line_goes_on(self):
        sock = self.connect()
        broken = bytearray(AC_REQUEST_1)
        broken[3] ^= 1
        sock.settimeout(0.6)
        sock.sendall(bytes(broken))
        with self.assertRaises(socket.timeout):
            sock.recv(64)
        sock.settimeout(5)
        self.assertEqual(len(exchange(sock, AC_REQUEST_1, 25)), 25)

    def test_only_the_loopback_by_default(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        with self.assertRaises(MeterBusError):
            serve(bus(), port=70000)


class CommandLine(unittest.TestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(list(args))
            except SystemExit as exit_:
                code = exit_.code
        return code, out.getvalue(), err.getvalue()

    def test_it_listens_and_says_what_it_did(self):
        code, out, err = self.run_cli("--meter-bus-port", "0", "--meter-bus-seconds", "0.2")
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        self.assertIn("meter bus listening on 127.0.0.1:", err)
        self.assertIn("0 request(s)", err)

    def test_what_is_refused(self):
        for args in (["--meter-bus-port", "70000"], ["--meter-bus-port", "0", "--meter-bus-host", "0.0.0.0"], ["--meter-bus-port", "0", "--electrical"],
                     ["--meter-bus-port", "0", "--meter-bus-seconds", "-1"], ["--meter-bus-config", "x.json"], ["--meter-bus-seconds", "3"]):
            code, _, err = self.run_cli(*args)
            self.assertEqual(code, 2, args)
            self.assertIn("meter-bus", err)

    def test_a_bad_file_exits_2(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bus.json"
            path.write_text("[]", encoding="utf-8")
            code, _, err = self.run_cli("--meter-bus-port", "0", "--meter-bus-config", str(path))
        self.assertEqual(code, 2)
        self.assertIn("meter bus:", err)

    def test_a_port_in_use_exits_2(self):
        taken = socket.socket()
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        try:
            code, _, err = self.run_cli("--meter-bus-port", str(taken.getsockname()[1]), "--meter-bus-seconds", "0.1")
        finally:
            taken.close()
        self.assertEqual(code, 2)
        self.assertIn("cannot listen", err)

    def test_the_default_output_is_untouched(self):
        code, out, _ = self.run_cli("--count", "1")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith('{"payload"'))


if __name__ == "__main__":
    unittest.main()
