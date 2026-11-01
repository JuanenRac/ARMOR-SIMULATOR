"""The simulated alarm panel and the check of the panel sync of a server.

The server here is a small model on the loopback of the process (no network): it keeps the mode, asks the panel through the same messages of the contract and reports `panel_sync`.
A few variants break it on purpose, to show that the check notices a server that confirms what a panel did not accept, asks for the wrong profile, or asks for nothing.
The real server is what `--verify-panel-sync` is pointed at in a machine that has a broker.
"""

from __future__ import annotations

import contextlib
import io
import unittest
from typing import Any

from armor_simulator.cli import main
from armor_simulator.panel_sim import BEHAVIORS, MODE_BASE, MODE_PROFILE, PanelLink, PanelLinkError, SimulatedPanel, verify_panel_map, verify_panel_sync


class ModelServer:
    """Stands in for the server: `session.call(method, path, body)`."""

    def __init__(self, panel: SimulatedPanel, *, sync_enabled: bool = True, wrong_profile: bool = False, silent_server: bool = False, confirm_everything: bool = False, hold_back: bool = False, no_alarm: bool = False, alarm_when_confirmed: bool = False) -> None:
        self.panel, self.sync_enabled = panel, sync_enabled
        self.wrong_profile, self.silent_server, self.confirm_everything, self.hold_back = wrong_profile, silent_server, confirm_everything, hold_back
        self.no_alarm, self.alarm_when_confirmed = no_alarm, alarm_when_confirmed
        self.alarm_open = False
        self.mode = "disarmed"
        self.sync: dict[str, Any] | None = None
        self.counter = 0

    panel_map: dict[str, Any] = {}
    revision = 1
    ignore_only = False
    ignore_profiles = False
    restores_nothing = False

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        if path == "/api/v1/alarm/modes":
            if method == "PUT":
                assert body is not None
                self.panel_map = {} if self.restores_nothing and not body["panel_map"] else dict(body["panel_map"])
                self.revision += 1
                return {"revision": self.revision}
            return {"enabled": True, "panel_sync_enabled": self.sync_enabled, "revision": self.revision, "modes": {"away": {}, "home": {}, "night": {}}, "panel_map": self.panel_map}
        if path == "/api/v1/status":
            state: dict[str, Any] = {"mode": "armed" if self.mode != "disarmed" else "disarmed", "arming_mode": self.mode}
            if self.hold_back and self.sync and self.sync["status"] != "confirmed":
                state["arming_mode"], state["mode"] = "disarmed", "disarmed"
            if self.sync:
                state["panel_sync"] = self.sync
            return state
        if path == "/api/v1/alarms":
            alarm = {"id": "alm-00001", "key": "mode_panel_sync", "code": "mode_panel_sync_failed", "severity": "high", "source": {"type": "alarm", "id": "mode_panel"}, "raised_at": "x"}
            return {"active": [alarm] if self.alarm_open else [{**alarm, "cleared_at": "y"}], "recent": []}
        assert path == "/api/v1/mode" and body is not None
        mode = str(body["mode"])
        self.mode = mode
        self.alarm_open = False
        if mode == "disarmed":
            self.sync = None
            return {}
        if not self.sync_enabled or self.silent_server:
            return {}
        profile_id = MODE_PROFILE[mode] if not self.wrong_profile else "stay"
        profile_id = profile_id if self.ignore_profiles else self.panel_map.get("profiles", {}).get(mode, profile_id)
        only = None if self.ignore_only else self.panel_map.get("only")
        if only is not None and self.panel.node_id not in only:
            unknown = [name for name in only if name != self.panel.node_id]
            self.sync = {"mode": mode, "profile": profile_id, "status": "failed" if unknown else "none", "nodes": []}
            self.alarm_open = bool(unknown)
            return {}
        self.counter += 1
        base = {"away": "away", "stay": "stay", "night": "stay"}.get(profile_id, MODE_BASE[mode])
        command = {"kind": "alarm_command", "node_id": self.panel.node_id, "timestamp_ms": 1, "command_id": f"{self.counter:016x}", "action": "arm", "mode": base,
                   "profile": {"id": profile_id, "name": profile_id, "base": base}}
        answer = self.panel.handle_command(command, 2)
        status = "confirmed" if answer is not None and answer["accepted"] else "failed"
        if self.confirm_everything:
            status = "confirmed"
        self.sync = {"mode": mode, "profile": profile_id, "status": status, "nodes": [{"node_id": self.panel.node_id, "status": "confirmed" if status == "confirmed" else "refused"}]}
        self.alarm_open = (status == "failed" and not self.no_alarm) or self.alarm_when_confirmed
        return {}


def run(**flags: bool) -> tuple[list[str], list[str]]:
    panel = SimulatedPanel()
    return verify_panel_sync(ModelServer(panel, **flags), panel, wait_s=0, sleep=lambda _s: None)


class PanelMapCheckTests(unittest.TestCase):
    def play(self, **flags: bool) -> tuple[list[str], list[str], ModelServer]:
        panel = SimulatedPanel()
        server = ModelServer(panel)
        for name, value in flags.items():
            setattr(server, name, value)
        problems, log = verify_panel_map(server, panel, wait_s=0, sleep=lambda _s: None)
        return problems, log, server

    def test_a_server_that_follows_the_mapping_and_the_list_passes_and_gets_its_document_back(self) -> None:
        problems, log, server = self.play()
        self.assertEqual(problems, [])
        self.assertEqual(len(log), 4)
        self.assertEqual(server.panel_map, {}, "the document is put back as it was")

    def test_a_server_that_ignores_the_list_is_caught(self) -> None:
        problems, _, _ = self.play(ignore_only=True)
        self.assertTrue(any("no panel at all" in problem and "arm command" in problem for problem in problems), problems)

    def test_a_server_that_ignores_the_mapping_is_caught(self) -> None:
        problems, _, _ = self.play(ignore_profiles=True)
        self.assertTrue(any("home arms another profile" in problem and "profile" in problem for problem in problems), problems)

    def test_it_refuses_to_run_when_the_modes_or_the_sync_are_off(self) -> None:
        panel = SimulatedPanel()
        problems, _ = verify_panel_map(ModelServer(panel, sync_enabled=False), panel, wait_s=0, sleep=lambda _s: None)
        self.assertIn("alarm.mode_panel_sync", problems[0])


class PanelModelTests(unittest.TestCase):
    def command(self, **extra: Any) -> dict[str, Any]:
        return {"kind": "alarm_command", "node_id": "sim-panel", "timestamp_ms": 1, "command_id": "00000000000000aa", "action": "arm", "mode": "stay", "profile": {"id": "stay", "name": "Home", "base": "stay"}, **extra}

    def test_a_panel_that_accepts_arms_with_the_profile_and_says_so(self) -> None:
        panel = SimulatedPanel()
        answer = panel.handle_command(self.command(), 5)
        assert answer is not None
        self.assertEqual((answer["accepted"], answer["refusal"], answer["phase"], answer["command_id"], answer["action"]), (True, "none", "armed", "00000000000000aa", "arm"))
        state = panel.state(6)
        self.assertEqual((state["mode"], state["phase"], state["profile"], state["arm_profiles"]), ("stay", "armed", "stay", True))

    def test_a_panel_that_refuses_says_why_and_stays_as_it_was(self) -> None:
        panel = SimulatedPanel(behavior="refuse", refusal="zones_open")
        answer = panel.handle_command(self.command(), 5)
        assert answer is not None
        self.assertEqual((answer["accepted"], answer["refusal"], answer["phase"]), (False, "zones_open", "disarmed"))
        self.assertEqual(panel.state(6)["phase"], "disarmed")

    def test_a_silent_panel_receives_but_never_answers(self) -> None:
        panel = SimulatedPanel(behavior="silent")
        self.assertIsNone(panel.handle_command(self.command(), 5))
        self.assertEqual(len(panel.arms_received()), 1)

    def test_what_is_not_for_the_panel_is_ignored_and_a_wrong_setup_is_refused(self) -> None:
        panel = SimulatedPanel()
        self.assertIsNone(panel.handle_command(self.command(node_id="other"), 5))
        self.assertIsNone(panel.handle_command({"kind": "alarm"}, 5))
        self.assertEqual(panel.received, [])
        with self.assertRaises(ValueError):
            SimulatedPanel(behavior="angry")
        with self.assertRaises(ValueError):
            SimulatedPanel(refusal="because")

    def test_a_disarm_command_disarms_and_the_list_of_others_is_kept(self) -> None:
        panel = SimulatedPanel()
        panel.handle_command(self.command(), 5)
        answer = panel.handle_command({**self.command(), "action": "disarm", "command_id": "00000000000000bb"}, 6)
        assert answer is not None
        self.assertTrue(answer["accepted"])
        self.assertEqual(panel.state(7)["phase"], "disarmed")
        self.assertEqual(len(panel.others_received()), 1)
        panel.reset()
        self.assertEqual(panel.received, [])

    def test_the_link_needs_paho_or_a_valid_address(self) -> None:
        with self.assertRaises(PanelLinkError):
            PanelLink(SimulatedPanel(), "http://broker").start()


class VerifyPanelSyncTests(unittest.TestCase):
    def test_a_server_that_does_what_it_must_passes_every_mode_against_every_behaviour(self) -> None:
        problems, log = run()
        self.assertEqual(problems, [])
        self.assertEqual(len(log), len(BEHAVIORS) * 3)
        self.assertIn("accept/home: the report says confirmed", log[1])
        self.assertIn("refuse/night: the report says failed", " ".join(log))
        self.assertIn("silent/away: the report says failed", " ".join(log))

    def test_it_notices_a_server_that_confirms_what_the_panel_did_not_accept(self) -> None:
        problems, _ = run(confirm_everything=True)
        self.assertTrue(any("refuse/home" in item and "must be 'failed'" in item for item in problems), problems)
        self.assertTrue(any("silent/night" in item and "shown as confirmed" in item for item in problems), problems)

    def test_it_notices_the_wrong_profile(self) -> None:
        problems, _ = run(wrong_profile=True)
        self.assertTrue(any("accept/night" in item and "profile" in item for item in problems), problems)
        self.assertTrue(any("accept/away" in item for item in problems))

    def test_it_notices_a_server_that_asks_the_panel_nothing(self) -> None:
        problems, _ = run(silent_server=True)
        self.assertTrue(any("received 0 arm command" in item for item in problems), problems)

    def test_it_notices_a_server_that_holds_its_own_defence_back_for_a_panel(self) -> None:
        problems, _ = run(hold_back=True)
        self.assertTrue(any("never hold the server back" in item for item in problems), problems)

    def test_it_notices_a_server_that_does_not_raise_the_alarm_of_a_failed_panel(self) -> None:
        problems, _ = run(no_alarm=True)
        self.assertTrue(any("refuse/home" in item and "0 open alarm(s)" in item for item in problems), problems)
        self.assertTrue(any("silent/night" in item for item in problems), problems)
        self.assertFalse(any(item.startswith("accept/") for item in problems), problems)

    def test_it_notices_an_alarm_for_a_panel_that_did_confirm(self) -> None:
        problems, _ = run(alarm_when_confirmed=True)
        self.assertTrue(any("accept/away" in item and "1 open alarm(s)" in item for item in problems), problems)

    def test_it_stops_with_the_reason_when_the_server_is_not_ready(self) -> None:
        panel = SimulatedPanel()
        problems, _ = verify_panel_sync(ModelServer(panel, sync_enabled=False), panel, wait_s=0, sleep=lambda _s: None)
        self.assertEqual(len(problems), 1)
        self.assertIn("alarm.mode_panel_sync", problems[0])

    def test_the_behaviour_of_the_panel_is_given_back_when_the_check_ends(self) -> None:
        panel = SimulatedPanel(behavior="refuse")
        verify_panel_sync(ModelServer(panel), panel, wait_s=0, sleep=lambda _s: None)
        self.assertEqual(panel.behavior, "refuse")


class CommandLineTests(unittest.TestCase):
    def test_the_check_asks_for_what_it_needs(self) -> None:
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as raised:
            main(["--verify-panel-sync"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--mqtt-url", err.getvalue())

    def test_a_password_is_never_asked_on_the_command_line(self) -> None:
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            main(["--verify-panel-sync", "--password", "x"])
        self.assertIn("unrecognized arguments", err.getvalue())


if __name__ == "__main__":
    unittest.main()
