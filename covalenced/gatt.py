# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Minimal BlueZ GATT client helpers shared by ANCS and AMS."""

from gi.repository import GLib

from .util import BLUEZ, call_async, log

CHARACTERISTIC = "org.bluez.GattCharacteristic1"


def find_service(objects, device_path, service_uuid):
    """Return {characteristic uuid: object path} for a service of a device, or None."""
    service = next((path for path, ifaces in objects.items()
                    if path.startswith(device_path + "/")
                    and ifaces.get("org.bluez.GattService1", {}).get("UUID", "").lower()
                    == service_uuid), None)
    if service is None:
        return None
    return {ifaces[CHARACTERISTIC]["UUID"].lower(): path
            for path, ifaces in objects.items()
            if path.startswith(service + "/") and CHARACTERISTIC in ifaces}


class GattClient:
    """Serialises writes to characteristics (one outstanding request at a time)."""

    def __init__(self, bus, chars, label):
        self.bus = bus
        self.chars = chars
        self.label = label
        self.queue = []  # (uuid, bytes, waits_for_response, then)
        self.busy = False
        self.notifying = []
        self.on_link_lost = None  # set by the link: drop this client, attach again later

    def subscribe(self, uuids, then=None):
        """StartNotify on each; `then` runs once every answer came back."""
        waiting = set(uuids)
        for uuid in uuids:
            call_async(self.bus, BLUEZ, self.chars[uuid], CHARACTERISTIC, "StartNotify",
                       on_done=lambda _v, error, u=uuid: self._on_subscribed(u, error, waiting,
                                                                              then))

    def _link_lost(self, error):
        """« Not connected »: the GATT database is BlueZ's cache, not a live link."""
        if error is None or "Not connected" not in error.message or not self.on_link_lost:
            return False
        log(f"{self.label} : liaison absente, client retiré en attendant l'iPhone")
        callback, self.on_link_lost = self.on_link_lost, None
        self.queue = []
        GLib.idle_add(lambda: callback() and False)
        return True

    def _on_subscribed(self, uuid, error, waiting=None, then=None):
        if self._link_lost(error):
            return
        if error:
            log(f"{self.label} : abonnement {uuid[:8]} refusé ({error.message})")
        else:
            self.notifying.append(uuid)
        if waiting is not None:
            waiting.discard(uuid)
            if not waiting and then:
                then()

    def stop(self):
        for uuid in self.notifying:
            call_async(self.bus, BLUEZ, self.chars[uuid], CHARACTERISTIC, "StopNotify")
        self.notifying = []
        self.queue = []

    def owns(self, path):
        return path in self.chars.values()

    def uuid_of(self, path):
        return next((u for u, p in self.chars.items() if p == path), None)

    def write(self, uuid, data, waits_for_response=False, then=None):
        """Queue a write; `then` runs once it has been acknowledged."""
        self.queue.append((uuid, bytes(data), waits_for_response, then))
        self._pump()

    def _pump(self):
        if self.busy or not self.queue:
            return
        uuid, data, waits, then = self.queue.pop(0)
        self.current_uuid = uuid
        self.busy = True
        self.serial = getattr(self, "serial", 0) + 1
        serial = self.serial

        def done(_value, error):
            if self._link_lost(error):
                self.busy = False
                return
            if error:
                log(f"{self.label} : écriture refusée ({error.message})")
                self.on_request_failed()
            elif then:
                then()
            if error or not waits:
                self.response_complete()
            else:
                # Watchdog: never stay stuck if a response is lost.
                GLib.timeout_add_seconds(5, lambda: self._expire(serial))

        call_async(self.bus, BLUEZ, self.chars[uuid], CHARACTERISTIC, "WriteValue",
                   GLib.Variant("(aya{sv})", (data, {"type": GLib.Variant("s", "request")})),
                   on_done=done)

    def _expire(self, serial):
        if self.busy and self.serial == serial:
            log(f"{self.label} : réponse perdue, requête abandonnée")
            self.on_request_failed()
            self.response_complete()
        return False

    def on_request_failed(self):
        """Hook for subclasses (e.g. drop a partial response buffer)."""

    def response_complete(self):
        self.busy = False
        self._pump()

    def read(self, uuid, on_value):
        def done(value, error):
            if error:
                log(f"{self.label} : lecture refusée ({error.message})")
                return
            on_value(bytes(value.unpack()[0]))

        call_async(self.bus, BLUEZ, self.chars[uuid], CHARACTERISTIC, "ReadValue",
                   GLib.Variant("(a{sv})", ({},)), on_done=done)
