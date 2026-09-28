# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Internet through the iPhone: Bluetooth tethering (PAN, the iPhone as network access point).

NetworkManager does the work. Covalence reuses a Bluetooth "panu" connection
bound to the iPhone's address (elementary's Network settings may have made one)
or creates one ("Covalence · iPhone", no autoconnect), then activates or
deactivates it on request only. The iPhone accepts only when Personal Hotspot
has "Allow Others to Join" on.

States: unavailable (no iPhone, no NetworkManager, or the iPhone offers no
network access point), off, connecting, on, failed.
"""

import uuid

from gi.repository import Gio, GLib

from .i18n import _
from .util import log

NM = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
SETTINGS_PATH = "/org/freedesktop/NetworkManager/Settings"
NAP_UUID = "00001116-0000-1000-8000-00805f9b34fb"
CONNECTION_NAME = "Covalence · iPhone"

# NMActiveConnectionState
ACTIVATING, ACTIVATED, DEACTIVATING = 1, 2, 3


def mac_bytes(address):
    return bytes(int(part, 16) for part in address.split(":"))


class NetworkManagerClient:
    """The few NetworkManager calls used here (replaced by a fake in the tests)."""

    def __init__(self, bus):
        self.bus = bus

    def _call(self, path, iface, method, args=None, reply=None):
        return self.bus.call_sync(NM, path, iface, method, args,
                                  GLib.VariantType(reply) if reply else None,
                                  Gio.DBusCallFlags.NONE, 10000, None)

    def _get(self, path, iface, prop):
        return self._call(path, "org.freedesktop.DBus.Properties", "Get",
                          GLib.Variant("(ss)", (iface, prop)), "(v)").unpack()[0]

    def available(self):
        try:
            self._get(NM_PATH, NM, "Version")
            return True
        except GLib.Error:
            return False

    def connections(self):
        """[(path, settings dict)]."""
        paths = self._call(SETTINGS_PATH, NM + ".Settings", "ListConnections",
                           None, "(ao)").unpack()[0]
        result = []
        for path in paths:
            try:
                settings = self._call(path, NM + ".Settings.Connection", "GetSettings",
                                      None, "(a{sa{sv}})").unpack()[0]
            except GLib.Error:
                continue
            result.append((path, settings))
        return result

    def add_connection(self, settings):
        variant = GLib.Variant("(a{sa{sv}})", (settings,))
        return self._call(SETTINGS_PATH, NM + ".Settings", "AddConnection", variant,
                          "(o)").unpack()[0]

    def device_for(self, address):
        for path in self._call(NM_PATH, NM, "GetDevices", None, "(ao)").unpack()[0]:
            try:
                if self._get(path, NM + ".Device", "Interface").upper() == address.upper():
                    return path
            except GLib.Error:
                continue
        return "/"

    def activate(self, connection, device):
        return self._call(NM_PATH, NM, "ActivateConnection",
                          GLib.Variant("(ooo)", (connection, device, "/")), "(o)").unpack()[0]

    def deactivate(self, active):
        self._call(NM_PATH, NM, "DeactivateConnection", GLib.Variant("(o)", (active,)))

    def active_for(self, connection):
        """(active connection path, state) of that connection, or (None, 0)."""
        for active in self._get(NM_PATH, NM, "ActiveConnections"):
            try:
                if self._get(active, NM + ".Connection.Active", "Connection") == connection:
                    return active, self._get(active, NM + ".Connection.Active", "State")
            except GLib.Error:
                continue
        return None, 0


def _is_ours(settings, address):
    conn = settings.get("connection", {})
    bt = settings.get("bluetooth", {})
    return conn.get("type") == "bluetooth" and bt.get("type") == "panu" \
        and bytes(bt.get("bdaddr", b"")) == mac_bytes(address)


class Hotspot:
    def __init__(self, system_bus, device_info, on_changed=lambda: None, client=None):
        """device_info() -> (address, uuids of the iPhone) or ("", [])."""
        self.client = client or NetworkManagerClient(system_bus)
        self.device_info = device_info
        self.on_changed = on_changed
        self.error = ""
        self.pending = False
        self.timer = 0
        self.cached = (None, None)  # (address, connection path): state() runs on each refresh

    def _find(self, address):
        if self.cached[0] == address and self.cached[1]:
            return self.cached[1]
        for path, settings in self.client.connections():
            if _is_ours(settings, address):
                self.cached = (address, path)
                return path
        return None

    def state(self):
        address, uuids = self.device_info()
        if not address or NAP_UUID not in [u.lower() for u in uuids]:
            return {"state": "unavailable", "error": ""}
        try:
            if not self.client.available():
                return {"state": "unavailable", "error": _("NetworkManager ne répond pas")}
            path = self._find(address)
            _active, state = self.client.active_for(path) if path else (None, 0)
        except GLib.Error as error:
            self.cached = (None, None)
            return {"state": "failed", "error": error.message}
        if state == ACTIVATED:
            name = "on"
        elif state in (ACTIVATING, DEACTIVATING) or self.pending:
            name = "connecting"
        elif self.error:
            name = "failed"
        else:
            name = "off"
        return {"state": name, "error": self.error}

    def connect(self):
        """Tether through the iPhone (explicit user request only)."""
        address, uuids = self.device_info()
        if not address:
            raise RuntimeError(_("aucun iPhone associé"))
        if NAP_UUID not in [u.lower() for u in uuids]:
            raise RuntimeError(_("l'iPhone ne propose pas de partage de connexion Bluetooth"))
        path = self._find(address)
        if path is None:
            path = self.client.add_connection({
                "connection": {"id": GLib.Variant("s", CONNECTION_NAME),
                               "uuid": GLib.Variant("s", str(uuid.uuid4())),
                               "type": GLib.Variant("s", "bluetooth"),
                               "autoconnect": GLib.Variant("b", False)},
                "bluetooth": {"bdaddr": GLib.Variant("ay", mac_bytes(address)),
                              "type": GLib.Variant("s", "panu")},
                "ipv4": {"method": GLib.Variant("s", "auto")},
                "ipv6": {"method": GLib.Variant("s", "auto")},
            })
            log("partage de connexion : connexion NetworkManager créée")
        self.error, self.pending = "", True
        try:
            self.client.activate(path, self.client.device_for(address))
        except GLib.Error as error:
            self.pending = False
            self.error = explain(error.message)
            log("partage de connexion : activation refusée")
            self.on_changed()
            raise RuntimeError(self.error)
        log("partage de connexion : activation demandée")
        self._watch()
        self.on_changed()

    def disconnect(self):
        address, _uuids = self.device_info()
        path = self._find(address) if address else None
        active, _state = self.client.active_for(path) if path else (None, 0)
        self.pending, self.error = False, ""
        if active:
            self.client.deactivate(active)
            log("partage de connexion : coupé")
        self.on_changed()

    # NetworkManager takes a few seconds: follow the attempt, then say why it failed.
    def _watch(self, tries=15):
        if self.timer:
            GLib.source_remove(self.timer)
        count = [tries]

        def tick():
            count[0] -= 1
            state = self.state()["state"]
            if state == "on" or count[0] <= 0:
                if state != "on" and self.pending:
                    self.error = _("L'iPhone n'a pas accepté. Sur l'iPhone, ouvrez Réglages › "
                                   "Partage de connexion et activez « Autoriser d'autres "
                                   "utilisateurs », puis réessayez.")
                self.pending, self.timer = False, 0
                self.on_changed()
                return False
            self.on_changed()
            return True

        self.timer = GLib.timeout_add_seconds(2, tick)


def explain(message):
    """A NetworkManager error in plain words."""
    lower = (message or "").lower()
    if "bluetooth" in lower or "nap" in lower or "timed out" in lower or "timeout" in lower:
        return _("L'iPhone n'a pas accepté. Sur l'iPhone, ouvrez Réglages › Partage de connexion "
                 "et activez « Autoriser d'autres utilisateurs », puis réessayez.")
    return message or _("échec inconnu")
