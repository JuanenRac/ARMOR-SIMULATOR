"""The signature of the critical commands: the shared vectors of ARMOR-COMMON (as written there), the refusals, the nonce memory and a simulated panel that drops what does not verify."""

from __future__ import annotations

import json
import unittest

from armor_simulator.command_signature import NonceMemory, node_key, sign_command, verify
from armor_simulator.panel_sim import SimulatedPanel

MASTER = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"   # the made-up key of the vectors
KEY = "156a3ba893545ebfde6009ac5393395fcb033e467f7ee6fb1839548da19a66b3"       # the key of "alarm-1"
ARM = ('{"kind":"alarm_command","node_id":"alarm-1","timestamp_ms":1000000,"command_id":"c000000000000001","action":"arm","mode":"away","force":true,"nonce":"0123456789abcdef",'
       '"sig":"74f16f5431411bbecb71cc858aca6a59035ac0ce0f906b7a69882f692d2e493a"}')
DISARM = ('{"kind":"alarm_command","node_id":"alarm-1","timestamp_ms":1000001,"command_id":"c000000000000002","action":"disarm","nonce":"fedcba9876543210",'
          '"sig":"63e7ee9a583f23f6c491fa4e8c216bf4fa8a589391076f8c15e6a0e89e9e0e30"}')


class Vectors(unittest.TestCase):
    def test_the_key_of_a_node_and_the_signature_match_the_shared_vectors(self) -> None:
        self.assertEqual(node_key(MASTER, "alarm-1"), KEY)
        self.assertEqual(node_key(MASTER, "electrical-1"), "9d2bf6e333a39afd9ff219bdda4df1833697f37f9c0d7577be589d592f702652")
        command = {"kind": "alarm_command", "node_id": "alarm-1", "timestamp_ms": 1000000, "command_id": "c000000000000001", "action": "arm", "mode": "away", "force": True}
        self.assertEqual(sign_command(MASTER, command, "0123456789abcdef"), ARM)

    def test_a_signed_command_verifies_once_and_every_change_is_refused(self) -> None:
        memory = NonceMemory()
        self.assertEqual(verify(ARM, KEY, memory), "ok")
        self.assertEqual(verify(ARM, KEY, memory), "replay")
        for changed in (ARM.replace('"arm"', '"disarm"'), ARM.replace("alarm-1", "alarm-2"), ARM.replace("0123456789abcdef", "0123456789abcdee"), ARM + " ", ARM.replace("74f16f54", "74F16F54")):
            self.assertNotEqual(verify(changed, KEY, NonceMemory()), "ok", changed)
        self.assertEqual(verify(ARM, "", NonceMemory()), "no_key")
        self.assertEqual(verify(json.dumps({"kind": "alarm_command"}), KEY, NonceMemory()), "no_signature")
        self.assertEqual(verify(ARM, node_key(MASTER, "electrical-1"), NonceMemory()), "bad_signature")

    def test_the_freshness_is_checked_only_with_a_clock_and_a_stale_command_keeps_its_nonce(self) -> None:
        memory = NonceMemory()
        self.assertEqual(verify(DISARM, KEY, memory, 1000001 + 120001), "stale")
        self.assertEqual(verify(DISARM, KEY, memory, 1000001 + 100000), "ok")
        self.assertEqual(verify(DISARM, KEY, NonceMemory(), 0), "ok")

    def test_the_memory_keeps_the_last_thirty_two(self) -> None:
        memory = NonceMemory()
        memory.remember("0123456789abcdef")
        for index in range(32):
            memory.remember(f"{index:016x}")
        self.assertFalse(memory.seen("0123456789abcdef"))
        self.assertTrue(memory.seen(f"{31:016x}"))

    def test_signing_needs_a_node_and_a_nonce(self) -> None:
        with self.assertRaises(ValueError):
            sign_command(MASTER, {"kind": "alarm_command"}, "0123456789abcdef")
        with self.assertRaises(ValueError):
            sign_command(MASTER, {"kind": "alarm_command", "node_id": "alarm-1"}, "short")


class SimulatedPanelWithAKey(unittest.TestCase):
    def test_without_a_key_any_command_is_taken_as_before(self) -> None:
        panel = SimulatedPanel(node_id="alarm-1")
        self.assertIsNotNone(panel.handle_raw(DISARM, 5))
        self.assertEqual(panel.refused, [])

    def test_with_a_key_only_a_signed_command_is_answered_and_the_rest_is_dropped_with_a_reason(self) -> None:
        panel = SimulatedPanel(node_id="alarm-1", command_key=KEY)
        plain = json.dumps({"kind": "alarm_command", "node_id": "alarm-1", "timestamp_ms": 1, "command_id": "c000000000000009", "action": "disarm"})
        self.assertIsNone(panel.handle_raw(plain, 5))
        self.assertIsNone(panel.handle_raw(DISARM.replace("1000001", "1000002"), 5))
        answer = panel.handle_raw(DISARM, 5)
        self.assertEqual(answer["command_id"], "c000000000000002") if answer else self.fail("the signed command was not answered")
        self.assertIsNone(panel.handle_raw(DISARM, 5))
        self.assertEqual(panel.refused, ["no_signature", "bad_signature", "replay"])

    def test_a_message_that_is_not_json_or_not_an_object_is_ignored(self) -> None:
        panel = SimulatedPanel(node_id="alarm-1", command_key=KEY)
        for text in ("not json", "[]", "5", ""):
            self.assertIsNone(panel.handle_raw(text, 5))


if __name__ == "__main__":
    unittest.main()
