"""Publishing the simulated messages on an MQTT broker, the way the real nodes do.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

ARMOR-SERVER takes the messages of the nodes by two roads (HTTP and MQTT) with different code behind each, and only this one exercises the second: the topic is the one of
the real node and the payload the same JSON. It is opt-in and explicit: a broker is chosen with `--mqtt-url`, and one that is not on this machine or a private network is refused
unless `--mqtt-allow-network` says it is meant (a simulation must not reach a real installation by accident). `paho-mqtt` is an optional extra (`pip install paho-mqtt`),
imported only when a broker is used; the user and the password of the broker never travel on the command line (a file or ARMOR_MQTT_PASSWORD).
"""

from __future__ import annotations

import ipaddress
import json
import threading
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse


class MqttOutError(RuntimeError):
    """The broker could not be used."""


def check_broker_url(url: str, allow_network: bool = False) -> tuple[str, int]:
    """(host, port) of mqtt://host[:port]; the host must be this machine or a private network address unless `allow_network`."""
    parsed = urlparse(url)
    if parsed.scheme not in ("mqtt", "tcp") or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise MqttOutError("the broker address is mqtt://host[:port], with no user, password or path (they have their own options)")
    host = parsed.hostname
    try:
        port = parsed.port or 1883
    except ValueError:
        raise MqttOutError("the port of the broker is not valid") from None
    if not allow_network and not _is_local(host):
        raise MqttOutError(f"{host} is not this machine or a private network address: add --mqtt-allow-network if you really mean to publish there")
    return host, port


def _is_local(host: str) -> bool:
    if host == "localhost" or host.endswith(".local") or "." not in host and ":" not in host:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


class MqttSink:
    """Connects to the broker and publishes each message (QoS 1, waiting for the broker to take it)."""

    def __init__(self, url: str, *, username: str | None = None, password: str | None = None, allow_network: bool = False, client_id: str = "armor-simulator",
                 client_factory: Callable[[str], Any] | None = None, wait_s: float = 5.0) -> None:
        self.host, self.port = check_broker_url(url, allow_network)
        self._username, self._password, self._client_id, self._factory, self._wait_s = username, password, client_id, client_factory, wait_s
        self._client: Any = None
        self.published = 0

    def open(self) -> None:
        if self._factory is not None:
            client = self._factory(self._client_id)
        else:
            try:
                import paho.mqtt.client as mqtt
            except ImportError:
                raise MqttOutError("publishing on a broker needs paho-mqtt (pip install paho-mqtt)") from None
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self._client_id)
        if self._username:
            client.username_pw_set(self._username, self._password)
        connected, refused = threading.Event(), []

        def on_connect(_c: Any, _u: Any, _f: Any, reason: Any, _p: Any = None) -> None:
            if getattr(reason, "is_failure", False):
                refused.append(str(reason))
            connected.set()

        client.on_connect = on_connect
        try:
            client.connect(self.host, self.port, keepalive=30)
        except OSError as error:
            raise MqttOutError(f"the broker could not be reached: {error}") from None
        client.loop_start()
        if not connected.wait(self._wait_s) or refused:
            client.loop_stop()
            raise MqttOutError("the broker did not accept the simulator" + (f" ({refused[-1]})" if refused else " (no answer)") + ": check the address, the user and the password")
        self._client = client

    def publish(self, topic: str, payload: dict) -> None:
        if self._client is None:
            raise MqttOutError("the broker is not open")
        info = self._client.publish(topic, json.dumps(payload, separators=(",", ":"), sort_keys=True), qos=1)
        try:
            info.wait_for_publish(self._wait_s)
        except (ValueError, RuntimeError) as error:
            raise MqttOutError(f"the broker did not take {topic}: {error}") from None
        if getattr(info, "rc", 0) not in (0, None):
            raise MqttOutError(f"the broker refused {topic} (code {info.rc})")
        self.published += 1

    def close(self) -> None:
        if self._client is not None:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
