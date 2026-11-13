"""The publisher of the simulator on a broker, tried with a stand-in for the client of the broker: every way to open, publish and close that does not need a real broker, and the checks of
the address of the broker."""
import json
import sys
import unittest
from unittest import mock

from armor_simulator.mqtt_out import MqttOutError, MqttSink, check_broker_url


class FakeInfo:
    def __init__(self, rc=0, wait_error=None):
        self.rc, self.wait_error = rc, wait_error

    def wait_for_publish(self, timeout):
        if self.wait_error is not None:
            raise self.wait_error


class FakeClient:
    """What paho gives: it answers the connection as the test chose and keeps what it was asked."""

    def __init__(self, client_id, answer="ok", connect_error=None, info=None):
        self.client_id, self.answer, self.connect_error, self.info = client_id, answer, connect_error, info or FakeInfo()
        self.on_connect = None
        self.credentials = None
        self.published = []
        self.loop_started = self.loop_stopped = self.disconnected = False

    def username_pw_set(self, user, password):
        self.credentials = (user, password)

    def connect(self, host, port, keepalive=60):
        if self.connect_error is not None:
            raise self.connect_error
        self.address = (host, port, keepalive)

    def loop_start(self):
        self.loop_started = True
        if self.answer == "ok":
            self.on_connect(self, None, {}, mock.Mock(is_failure=False))
        elif self.answer == "refused":
            self.on_connect(self, None, {}, mock.Mock(is_failure=True, __str__=lambda _s: "Not authorized"))

    def loop_stop(self):
        self.loop_stopped = True

    def disconnect(self):
        self.disconnected = True

    def publish(self, topic, payload, qos=0):
        self.published.append((topic, payload, qos))
        return self.info


def sink(**fake):
    made = []

    def factory(client_id):
        client = FakeClient(client_id, **fake)
        made.append(client)
        return client

    return MqttSink("mqtt://127.0.0.1:1884", client_factory=factory, wait_s=0.05, username="armor", password="a-password"), made


class MqttSinkTests(unittest.TestCase):
    def test_a_broker_that_accepts_gets_the_credentials_and_the_messages_sorted_and_compact(self):
        out, made = sink()
        out.open()
        out.publish("armor/x", {"b": 2, "a": 1})
        client = made[0]
        self.assertEqual(client.credentials, ("armor", "a-password"))
        self.assertEqual(client.address, ("127.0.0.1", 1884, 30))
        self.assertEqual(client.published, [("armor/x", '{"a":1,"b":2}', 1)])
        self.assertEqual(json.loads(client.published[0][1]), {"a": 1, "b": 2})
        self.assertEqual(out.published, 1)
        out.close()
        self.assertTrue(client.loop_stopped and client.disconnected)
        out.close()   # closing twice is harmless

    def test_a_broker_that_refuses_the_simulator_is_an_error_that_says_why(self):
        out, made = sink(answer="refused")
        with self.assertRaises(MqttOutError) as caught:
            out.open()
        self.assertIn("did not accept the simulator", str(caught.exception))
        self.assertTrue(made[0].loop_stopped)

    def test_a_broker_that_does_not_answer_is_an_error_that_says_no_answer(self):
        out, _made = sink(answer="silent")
        with self.assertRaises(MqttOutError) as caught:
            out.open()
        self.assertIn("no answer", str(caught.exception))

    def test_a_broker_that_cannot_be_reached_is_an_error(self):
        out, _made = sink(connect_error=OSError("connection refused"))
        with self.assertRaises(MqttOutError) as caught:
            out.open()
        self.assertIn("could not be reached", str(caught.exception))

    def test_publishing_before_opening_is_an_error(self):
        out, _made = sink()
        with self.assertRaises(MqttOutError):
            out.publish("armor/x", {})

    def test_a_publish_that_the_broker_does_not_take_is_an_error(self):
        out, _made = sink(info=FakeInfo(wait_error=RuntimeError("queue full")))
        out.open()
        with self.assertRaises(MqttOutError) as caught:
            out.publish("armor/x", {})
        self.assertIn("did not take armor/x", str(caught.exception))
        self.assertEqual(out.published, 0)

    def test_a_publish_with_a_code_of_refusal_is_an_error(self):
        out, _made = sink(info=FakeInfo(rc=4))
        out.open()
        with self.assertRaises(MqttOutError) as caught:
            out.publish("armor/x", {})
        self.assertIn("code 4", str(caught.exception))

    def test_without_the_client_library_it_says_what_to_install(self):
        out = MqttSink("mqtt://127.0.0.1:1883", wait_s=0.05)
        with mock.patch.dict(sys.modules, {"paho": None, "paho.mqtt": None, "paho.mqtt.client": None}):
            with self.assertRaises(MqttOutError) as caught:
                out.open()
        self.assertIn("paho-mqtt", str(caught.exception))


class BrokerAddressTests(unittest.TestCase):
    def test_local_and_private_addresses_are_allowed_and_the_default_port_is_1883(self):
        for url in ("mqtt://localhost", "mqtt://127.0.0.1", "mqtt://192.168.0.10:1884", "mqtt://broker.local", "mqtt://broker", "mqtt://[::1]"):
            host, port = check_broker_url(url, False)
            self.assertTrue(host)
            self.assertIn(port, (1883, 1884))

    def test_a_public_address_needs_the_option_that_says_so(self):
        with self.assertRaises(MqttOutError) as caught:
            check_broker_url("mqtt://8.8.8.8:1883", False)
        self.assertIn("--mqtt-allow-network", str(caught.exception))
        self.assertEqual(check_broker_url("mqtt://8.8.8.8:1883", True), ("8.8.8.8", 1883))
        with self.assertRaises(MqttOutError):
            check_broker_url("mqtt://example.com", False)

    def test_a_port_that_is_not_a_number_is_refused(self):
        with self.assertRaises(MqttOutError) as caught:
            check_broker_url("mqtt://127.0.0.1:99999", True)
        self.assertIn("port", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
