# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Offline checks of the proximity lock and the Bluetooth tethering: python3 -m unittest

Nothing here locks the screen or touches NetworkManager: both are fakes."""

import os
import tempfile
import unittest

from gi.repository import GLib

from covalenced import hotspot, proximity
from covalenced.config import Config

PHONE = "AA:BB:CC:00:11:22"


def private_config(tmp):
    config = Config()
    config.dir, config.path = tmp, os.path.join(tmp, "covalenced.conf")
    config.keyfile = GLib.KeyFile()
    return config


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class ProximityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = private_config(self.tmp.name)
        self.clock = Clock()
        self.locks = 0
        self.calling = False
        self.p = proximity.Proximity(self.config, in_call=lambda: self.calling,
                                     locker=self._lock, clock=self.clock)
        self.p._schedule = lambda: None  # no GLib timer in the tests

    def tearDown(self):
        self.tmp.cleanup()

    def _lock(self):
        self.locks += 1

    def enable(self, distance="medium", delay=30):
        self.p.configure(True, distance, delay)

    def test_off_by_default(self):
        self.assertFalse(self.p.enabled)
        self.p.device_connected()
        self.p.device_disconnected()
        self.clock.now += 600
        self.assertFalse(self.p.check())
        self.assertEqual(self.locks, 0)

    def test_link_lost_locks_after_delay_once(self):
        self.enable(delay=30)
        self.p.device_connected()
        self.p.device_disconnected()
        self.clock.now += 29
        self.assertFalse(self.p.check())
        self.clock.now += 2
        self.assertTrue(self.p.check())
        self.clock.now += 300
        self.assertFalse(self.p.check())  # one lock per absence
        self.assertEqual(self.locks, 1)
        self.p.device_connected()  # back: armed again
        self.p.device_disconnected()
        self.clock.now += 31
        self.assertTrue(self.p.check())
        self.assertEqual(self.locks, 2)

    def test_never_seen_never_locks(self):
        self.enable()
        self.p.device_disconnected()
        self.clock.now += 600
        self.assertFalse(self.p.check())

    def test_no_lock_during_a_call(self):
        self.enable(delay=10)
        self.p.device_connected()
        self.p.device_disconnected()
        self.calling = True
        self.clock.now += 60
        self.assertFalse(self.p.check())
        self.calling = False
        self.assertTrue(self.p.check())

    def test_weak_signal_smoothed_with_hysteresis(self):
        self.enable(distance="medium", delay=10)  # away under -74 dBm
        self.p.device_connected()
        self.p.rssi_sample(-60)
        self.p.rssi_sample(-95)  # one bad sample is smoothed away
        self.assertFalse(self.p.far)
        for _ in range(6):
            self.p.rssi_sample(-90)
        self.assertTrue(self.p.far)
        self.p.rssi_sample(-72)  # just above the threshold: still away (hysteresis)
        self.assertTrue(self.p.far)
        self.clock.now += 11
        self.assertTrue(self.p.check())
        for _ in range(8):
            self.p.rssi_sample(-55)
        self.assertFalse(self.p.far)
        self.assertTrue(self.p.armed)

    def test_unknown_rssi_ignored(self):
        self.enable()
        self.p.rssi_sample(0)
        self.p.rssi_sample(127)
        self.assertIsNone(self.p.rssi)
        self.assertFalse(self.p.seen)

    def test_settings_checked_and_saved(self):
        with self.assertRaises(ValueError):
            self.p.configure(True, "moon", 30)
        with self.assertRaises(ValueError):
            self.p.configure(True, "near", 7)
        self.p.configure(True, "far", 60)
        again = private_config(self.tmp.name)
        again.keyfile.load_from_file(again.path, GLib.KeyFileFlags.NONE)
        self.assertEqual(proximity.Proximity(again).state()["distance"], "far")
        self.assertEqual(proximity.Proximity(again).state()["delay"], 60)


class FakeNM:
    def __init__(self, connections=(), active=None, fail=None):
        self.conns = list(connections)
        self.active = dict(active or {})  # connection path -> state
        self.fail = fail
        self.activated, self.deactivated, self.added = [], [], []

    def available(self):
        return True

    def connections(self):
        return self.conns

    def add_connection(self, settings):
        path = f"/nm/Settings/{len(self.conns) + 1}"
        unpacked = {group: {k: v.unpack() for k, v in values.items()}
                    for group, values in settings.items()}
        self.conns.append((path, unpacked))
        self.added.append(unpacked)
        return path

    def device_for(self, address):
        return "/nm/Devices/7"

    def activate(self, connection, device):
        if self.fail:
            raise GLib.Error(self.fail)
        self.activated.append((connection, device))
        self.active[connection] = hotspot.ACTIVATING
        return "/nm/Active/1"

    def deactivate(self, active):
        self.deactivated.append(active)

    def active_for(self, connection):
        state = self.active.get(connection, 0)
        return ("/nm/Active/1", state) if state else (None, 0)


def panu(address, name="Réseau iPhone"):
    return {"connection": {"type": "bluetooth", "id": name},
            "bluetooth": {"type": "panu", "bdaddr": hotspot.mac_bytes(address)}}


class HotspotTest(unittest.TestCase):
    def make(self, nm, uuids=(hotspot.NAP_UUID,), address=PHONE):
        h = hotspot.Hotspot(None, lambda: (address, list(uuids)), client=nm)
        h._watch = lambda tries=15: None  # no GLib timer in the tests
        return h

    def test_unavailable_without_nap(self):
        self.assertEqual(self.make(FakeNM(), uuids=[]).state()["state"], "unavailable")
        self.assertEqual(self.make(FakeNM(), address="").state()["state"], "unavailable")

    def test_reuses_existing_connection(self):
        nm = FakeNM([("/nm/Settings/3", panu("11:11:11:11:11:11")),
                     ("/nm/Settings/4", panu(PHONE))])
        h = self.make(nm)
        self.assertEqual(h.state()["state"], "off")
        h.connect()
        self.assertEqual(nm.activated, [("/nm/Settings/4", "/nm/Devices/7")])
        self.assertEqual(nm.added, [])
        self.assertEqual(h.state()["state"], "connecting")
        nm.active["/nm/Settings/4"] = hotspot.ACTIVATED
        self.assertEqual(h.state()["state"], "on")
        h.disconnect()
        self.assertEqual(nm.deactivated, ["/nm/Active/1"])

    def test_creates_a_connection_without_autoconnect(self):
        nm = FakeNM()
        self.make(nm).connect()
        self.assertEqual(len(nm.added), 1)
        added = nm.added[0]
        self.assertEqual(added["bluetooth"]["type"], "panu")
        self.assertEqual(bytes(added["bluetooth"]["bdaddr"]), hotspot.mac_bytes(PHONE))
        self.assertFalse(added["connection"]["autoconnect"])

    def test_refusal_is_explained(self):
        nm = FakeNM([("/nm/Settings/4", panu(PHONE))],
                    fail="org.freedesktop.NetworkManager: Bluetooth connection timed out")
        h = self.make(nm)
        with self.assertRaises(RuntimeError) as caught:
            h.connect()
        self.assertIn("Autoriser d'autres utilisateurs", str(caught.exception))
        self.assertEqual(h.state()["state"], "failed")

    def test_no_phone_no_connection(self):
        with self.assertRaises(RuntimeError):
            self.make(FakeNM(), address="").connect()


if __name__ == "__main__":
    unittest.main()
