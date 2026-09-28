# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Proximity lock: lock the PC when the iPhone moves away. Never unlocks.

Two signs that the iPhone is away:
- its Bluetooth link is lost (out of range, about ten metres) for `delay` seconds;
- the signal strength BlueZ reports (Device1.RSSI, only known while BlueZ is
  discovering; an unprivileged process cannot read the RSSI of a connected
  link) stays below the chosen threshold for `delay` seconds.

Safety rules: nothing happens until the iPhone has been seen in this session,
nor during a call; one lock per absence (the iPhone must come back before the
next one). Settings in covalenced.conf [proximity]: enabled (false by default),
distance (near|medium|far), delay (seconds).
"""

import time

from gi.repository import Gio, GLib

from .util import log

# dBm under which the iPhone counts as away, and the margin to count as back.
THRESHOLDS = {"near": -62, "medium": -74, "far": -86}
HYSTERESIS = 6
SMOOTHING = 0.3  # weight of a new RSSI sample in the moving average
DELAYS = (10, 30, 60, 120)
DEFAULT_DELAY = 30
TICK = 5


class Proximity:
    def __init__(self, config, in_call=lambda: False, on_changed=lambda: None, locker=None,
                 clock=time.monotonic, session_bus=None):
        self.config = config
        self.in_call = in_call
        self.on_changed = on_changed
        self.clock = clock
        self.locker = locker or (lambda: lock_screen(session_bus))
        self.seen = False        # the iPhone has been connected or heard in this session
        self.connected = False
        self.rssi = None         # smoothed, dBm
        self.far = False
        self.far_since = None
        self.lost_since = None
        self.armed = True        # false after a lock, until the iPhone comes back
        self.timer = 0

    # --- settings -------------------------------------------------------------------------------

    @property
    def enabled(self):
        return self.config.boolean("proximity", "enabled", False)

    @property
    def distance(self):
        try:
            value = self.config.keyfile.get_string("proximity", "distance")
        except GLib.Error:
            value = "medium"
        return value if value in THRESHOLDS else "medium"

    @property
    def delay(self):
        try:
            value = self.config.keyfile.get_integer("proximity", "delay")
        except GLib.Error:
            value = DEFAULT_DELAY
        return value if value in DELAYS else DEFAULT_DELAY

    def configure(self, enabled, distance, delay):
        if distance not in THRESHOLDS or delay not in DELAYS:
            raise ValueError("unknown distance or delay")
        keyfile = self.config.keyfile
        keyfile.set_boolean("proximity", "enabled", enabled)
        keyfile.set_string("proximity", "distance", distance)
        keyfile.set_integer("proximity", "delay", delay)
        self.config.save()
        log(f"verrouillage de proximité {'activé' if enabled else 'désactivé'}")
        self.far, self.far_since = self._is_far(), None
        self.armed = True
        self._schedule()
        self.on_changed()

    def state(self):
        return {"enabled": self.enabled, "distance": self.distance, "delay": self.delay,
                "rssi": int(round(self.rssi)) if self.rssi is not None else 0,
                "near": self.connected and not self.far}

    # --- events -------------------------------------------------------------------------------------

    def device_connected(self):
        self.seen, self.connected = True, True
        self.lost_since = None
        if not self.far:
            self.armed = True
        self._schedule()

    def device_disconnected(self):
        self.connected = False
        self.rssi, self.far, self.far_since = None, False, None
        if self.seen:
            self.lost_since = self.clock()
        self._schedule()

    def rssi_sample(self, value):
        if value is None or value >= 0 or value < -127:
            return  # 0 and 127 mean "unknown" in HCI
        self.seen = True
        self.rssi = value if self.rssi is None else \
            SMOOTHING * value + (1 - SMOOTHING) * self.rssi
        far = self._is_far()
        if far and not self.far:
            self.far_since = self.clock()
        elif not far and self.far:
            self.far_since = None
            if self.connected:
                self.armed = True
        self.far = far
        self._schedule()

    def _is_far(self):
        if self.rssi is None:
            return False
        threshold = THRESHOLDS[self.distance]
        # Hysteresis: once away, the iPhone must come clearly closer to count as back.
        return self.rssi < (threshold + HYSTERESIS if self.far else threshold)

    # --- decision -----------------------------------------------------------------------------------

    def check(self):
        """Lock now if the iPhone has been away long enough. Returns True when it locked."""
        if not self.enabled or not self.seen or not self.armed or self.in_call():
            return False
        now = self.clock()
        since = [t for t in (self.lost_since, self.far_since) if t is not None]
        if not since or now - min(since) < self.delay:
            return False
        self.armed = False
        log("verrouillage de proximité : iPhone éloigné, écran verrouillé")
        self.locker()
        return True

    def _schedule(self):
        waiting = self.enabled and self.armed and (self.lost_since or self.far_since)
        if waiting and not self.timer:
            self.timer = GLib.timeout_add_seconds(TICK, self._tick)
        self.on_changed()

    def _tick(self):
        self.check()
        if self.enabled and self.armed and (self.lost_since or self.far_since):
            return True
        self.timer = 0
        return False


def lock_screen(bus=None):
    """Lock the session: the screensaver of elementary (Gala), else logind. Never unlocks."""
    bus = bus or Gio.bus_get_sync(Gio.BusType.SESSION)

    def fallback(_value, error):
        if error is None:
            return
        system = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        system.call("org.freedesktop.login1", "/org/freedesktop/login1/session/auto",
                    "org.freedesktop.login1.Session", "Lock", None, None,
                    Gio.DBusCallFlags.NONE, 5000, None, None, None)

    def finish(conn, result, _data):
        try:
            conn.call_finish(result)
            fallback(None, None)
        except GLib.Error as error:
            fallback(None, error)

    bus.call("org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver",
             "org.freedesktop.ScreenSaver", "Lock", None, None, Gio.DBusCallFlags.NONE,
             5000, None, finish, None)
