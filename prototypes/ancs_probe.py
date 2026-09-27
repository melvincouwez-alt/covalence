#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""J0 prototype: show iPhone notifications on elementary OS through ANCS.

The PC advertises itself as a Bluetooth LE accessory that solicits the Apple
Notification Center Service. Once the iPhone connects and pairs from
Settings > Bluetooth, the PC acts as a GATT client of ANCS, subscribes to the
notification stream and re-emits every notification through the desktop
notification server.

Privacy rule from the design document: logs record events, never content.

Usage: python3 ancs_probe.py [--seconds N]
"""

import argparse
import struct
import sys

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

BLUEZ = "org.bluez"
ADAPTER_PATH = "/org/bluez/hci0"
AGENT_PATH = "/io/github/melvincouwez/Covalence/agent"
ADV_PATH = "/io/github/melvincouwez/Covalence/advertisement"

ANCS_SERVICE = "7905f431-b5ce-4e99-a40f-4b1e122d00d0"
NOTIFICATION_SOURCE = "9fbf120d-6301-42d9-8c58-25e699a21dbd"
CONTROL_POINT = "69d1d8f3-45e1-49a8-9821-9bbdfdaad9d9"
DATA_SOURCE = "22eac6e9-24d6-4bb5-be44-b36ace7c7bfb"

EVENT_ADDED, EVENT_MODIFIED, EVENT_REMOVED = 0, 1, 2
EVENT_FLAG_PREEXISTING = 1 << 2
CMD_GET_NOTIFICATION_ATTRIBUTES = 0
CMD_GET_APP_ATTRIBUTES = 1
ATTR_APP_IDENTIFIER, ATTR_TITLE, ATTR_SUBTITLE, ATTR_MESSAGE = 0, 1, 2, 3
APP_ATTR_DISPLAY_NAME = 0

CATEGORIES = {
    0: "autre", 1: "appel entrant", 2: "appel manqué", 3: "messagerie vocale",
    4: "social", 5: "agenda", 6: "e-mail", 7: "actualités", 8: "santé",
    9: "finances", 10: "localisation", 11: "divertissement",
}

AGENT_XML = """
<node>
  <interface name="org.bluez.Agent1">
    <method name="Release"/>
    <method name="RequestPinCode"><arg type="o" direction="in"/><arg type="s" direction="out"/></method>
    <method name="DisplayPinCode"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
    <method name="RequestPasskey"><arg type="o" direction="in"/><arg type="u" direction="out"/></method>
    <method name="DisplayPasskey"><arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/></method>
    <method name="RequestConfirmation"><arg type="o" direction="in"/><arg type="u" direction="in"/></method>
    <method name="RequestAuthorization"><arg type="o" direction="in"/></method>
    <method name="AuthorizeService"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
    <method name="Cancel"/>
  </interface>
</node>
"""

ADV_XML = """
<node>
  <interface name="org.bluez.LEAdvertisement1">
    <method name="Release"/>
    <property name="Type" type="s" access="read"/>
    <property name="LocalName" type="s" access="read"/>
    <property name="SolicitUUIDs" type="as" access="read"/>
    <property name="Discoverable" type="b" access="read"/>
    <property name="Includes" type="as" access="read"/>
  </interface>
</node>
"""


def log(message):
    print(f"[covalence] {message}", flush=True)


class NotificationBridge:
    """Re-emits ANCS notifications through org.freedesktop.Notifications."""

    def __init__(self, bus):
        self.bus = bus
        self.desktop_ids = {}  # ANCS notification UID -> desktop notification id

    def show(self, uid, device_name, app_name, title, body, category):
        summary = title or app_name or "iPhone"
        if app_name and title and app_name != title:
            summary = f"{app_name} · {title}"
        replaces = self.desktop_ids.get(uid, 0)
        # Pas de hint desktop-entry : le serveur afficherait le nom du lanceur
        # au lieu de « Covalence (nom de l'iPhone) ».
        hints = {}
        if category in (1, 2):
            hints["urgency"] = GLib.Variant("y", 2)
        result = self.bus.call_sync(
            "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
            "org.freedesktop.Notifications", "Notify",
            GLib.Variant("(susssasa{sv}i)", (
                f"Covalence ({device_name})", replaces, "phone", summary, body or "", [], hints, -1,
            )),
            GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, -1, None,
        )
        self.desktop_ids[uid] = result.unpack()[0]

    def close(self, uid):
        desktop_id = self.desktop_ids.pop(uid, None)
        if desktop_id is None:
            return
        self.bus.call_sync(
            "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
            "org.freedesktop.Notifications", "CloseNotification",
            GLib.Variant("(u)", (desktop_id,)), None, Gio.DBusCallFlags.NONE, -1, None,
        )


class AncsClient:
    """GATT client of the iPhone's ANCS service for one connected device."""

    def __init__(self, system_bus, bridge, chars, device_name):
        self.bus = system_bus
        self.device_name = device_name
        self.bridge = bridge
        self.chars = chars  # uuid -> characteristic object path
        self.pending = {}  # uid -> category, waiting for attributes
        self.buffer = b""
        self.app_names = {}
        self.pending_apps = set()
        self.queue = []  # control point requests, sent one at a time
        self.busy = False

    def start(self):
        for uuid in (DATA_SOURCE, NOTIFICATION_SOURCE):
            self.bus.call(
                BLUEZ, self.chars[uuid], "org.bluez.GattCharacteristic1", "StartNotify",
                None, None, Gio.DBusCallFlags.NONE, -1, None, self._on_start_notify, uuid,
            )

    def _on_start_notify(self, bus, result, uuid):
        try:
            bus.call_finish(result)
            log(f"abonné à {'Notification Source' if uuid == NOTIFICATION_SOURCE else 'Data Source'}")
        except GLib.Error as error:
            log(f"échec d'abonnement ({uuid[:8]}) : {error.message}")

    def on_value(self, char_path, value):
        if char_path == self.chars[NOTIFICATION_SOURCE]:
            self._on_notification_source(value)
        elif char_path == self.chars[DATA_SOURCE]:
            self.buffer += value
            self._parse_data_source()

    def _on_notification_source(self, value):
        if len(value) < 8:
            return
        event, flags, category, _count, uid = struct.unpack("<BBBBI", value[:8])
        label = CATEGORIES.get(category, str(category))
        if event == EVENT_REMOVED:
            log(f"notification {uid} retirée")
            self.bridge.close(uid)
            return
        if flags & EVENT_FLAG_PREEXISTING:
            return  # déjà présente sur l'iPhone avant la connexion : on ne rejoue pas
        log(f"notification {uid} {'ajoutée' if event == EVENT_ADDED else 'modifiée'} ({label})")
        self.pending[uid] = category
        request = struct.pack("<BI", CMD_GET_NOTIFICATION_ATTRIBUTES, uid)
        request += bytes([ATTR_APP_IDENTIFIER])
        request += struct.pack("<BH", ATTR_TITLE, 64)
        request += struct.pack("<BH", ATTR_SUBTITLE, 64)
        request += struct.pack("<BH", ATTR_MESSAGE, 512)
        self._send(request)

    def _send(self, request):
        self.queue.append(request)
        self._pump()

    def _pump(self):
        if self.busy or not self.queue:
            return
        self.busy = True
        request = self.queue.pop(0)
        self.bus.call(
            BLUEZ, self.chars[CONTROL_POINT], "org.bluez.GattCharacteristic1", "WriteValue",
            GLib.Variant("(aya{sv})", (request, {})), None, Gio.DBusCallFlags.NONE, -1, None,
            self._on_written, None,
        )

    def _on_written(self, bus, result, _data):
        try:
            bus.call_finish(result)
        except GLib.Error as error:
            log(f"écriture refusée par l'iPhone : {error.message}")
            self.buffer = b""
            self.busy = False
            self._pump()

    def _parse_data_source(self):
        """Parse one complete response from the buffer, if it has fully arrived."""
        data = self.buffer
        if not data:
            return
        if data[0] == CMD_GET_NOTIFICATION_ATTRIBUTES:
            parsed = self._parse_attributes(data[5:], 4)
            if parsed is None:
                return  # réponse incomplète : la suite arrive dans le paquet suivant
            attrs, used = parsed
            self.buffer = data[5 + used:]
            uid = struct.unpack("<I", data[1:5])[0]
            self._deliver(uid, attrs)
        elif data[0] == CMD_GET_APP_ATTRIBUTES:
            end = data.find(b"\0", 1)
            if end < 0:
                return
            app_id = data[1:end].decode("utf-8", "replace")
            parsed = self._parse_attributes(data[end + 1:], 1)
            if parsed is None:
                return
            attrs, used = parsed
            self.buffer = data[end + 1 + used:]
            self.app_names[app_id] = attrs.get(APP_ATTR_DISPLAY_NAME) or app_id
            self.pending_apps.discard(app_id)
        else:
            self.buffer = b""
        self.busy = False
        self._pump()

    @staticmethod
    def _parse_attributes(data, count):
        attrs, offset = {}, 0
        for _ in range(count):
            if len(data) < offset + 3:
                return None
            attr_id, length = struct.unpack("<BH", data[offset:offset + 3])
            if len(data) < offset + 3 + length:
                return None
            attrs[attr_id] = data[offset + 3:offset + 3 + length].decode("utf-8", "replace")
            offset += 3 + length
        return attrs, offset

    def _deliver(self, uid, attrs):
        category = self.pending.pop(uid, 0)
        app_id = attrs.get(ATTR_APP_IDENTIFIER, "")
        if app_id and app_id not in self.app_names and app_id not in self.pending_apps:
            self.pending_apps.add(app_id)
            self._send(bytes([CMD_GET_APP_ATTRIBUTES]) + app_id.encode() + b"\0"
                       + bytes([APP_ATTR_DISPLAY_NAME]))
        app_name = self.app_names.get(app_id, app_id.rsplit(".", 1)[-1] if app_id else "")
        body = "\n".join(filter(None, [attrs.get(ATTR_SUBTITLE), attrs.get(ATTR_MESSAGE)]))
        self.bridge.show(uid, self.device_name, app_name, attrs.get(ATTR_TITLE, ""), body, category)
        log(f"notification {uid} affichée")


class Probe:
    def __init__(self, seconds):
        self.loop = GLib.MainLoop()
        self.system = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        self.session = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.bridge = NotificationBridge(self.session)
        self.clients = {}  # device path -> AncsClient
        self.seconds = seconds
        self.registrations = []

    # --- D-Bus objects exported to BlueZ -----------------------------------

    def _export(self, xml, path, method_handler, property_handler=None):
        info = Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0]
        reg = self.system.register_object(path, info, method_handler, property_handler, None)
        self.registrations.append(reg)

    def _agent_method(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method == "RequestConfirmation":
            device, passkey = params.unpack()
            # Comparaison numérique LE Secure Connections : le même code s'affiche sur l'iPhone.
            log(f"appairage : vérifier que l'iPhone affiche le code {passkey:06d}")
            self._notify_pairing(passkey)
            invocation.return_value(None)
        elif method in ("RequestAuthorization", "AuthorizeService", "Release", "Cancel",
                        "DisplayPinCode", "DisplayPasskey"):
            invocation.return_value(None)
        else:
            invocation.return_dbus_error("org.bluez.Error.Rejected", "unsupported")

    def _notify_pairing(self, passkey):
        self.session.call_sync(
            "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
            "org.freedesktop.Notifications", "Notify",
            GLib.Variant("(susssasa{sv}i)", (
                "Covalence", 0, "bluetooth", "Appairage avec l'iPhone",
                f"Vérifiez que l'iPhone affiche le code {passkey:06d}", [], {}, -1,
            )),
            None, Gio.DBusCallFlags.NONE, -1, None,
        )

    def _adv_method(self, _conn, _sender, _path, _iface, method, _params, invocation):
        invocation.return_value(None)

    def _adv_property(self, _conn, _sender, _path, _iface, name):
        return {
            "Type": GLib.Variant("s", "peripheral"),
            "LocalName": GLib.Variant("s", "Covalence"),
            "SolicitUUIDs": GLib.Variant("as", [ANCS_SERVICE]),
            # Drapeau « découvrable général » : sans lui, l'iPhone ne liste pas l'accessoire.
            # Pas d'Appearance : avec l'UUID 128 bits, le paquet dépasserait 31 octets.
            "Discoverable": GLib.Variant("b", True),
            "Includes": GLib.Variant("as", []),
        }[name]

    # --- BlueZ object tracking ----------------------------------------------

    def _managed_objects(self):
        result = self.system.call_sync(
            BLUEZ, "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects",
            None, None, Gio.DBusCallFlags.NONE, -1, None,
        )
        return result.unpack()[0]

    def _try_attach(self, device_path):
        if device_path in self.clients:
            return
        objects = self._managed_objects()
        service = next((p for p, ifs in objects.items()
                        if p.startswith(device_path + "/")
                        and ifs.get("org.bluez.GattService1", {}).get("UUID") == ANCS_SERVICE), None)
        if service is None:
            return
        chars = {ifs["org.bluez.GattCharacteristic1"]["UUID"]: p
                 for p, ifs in objects.items()
                 if p.startswith(service + "/") and "org.bluez.GattCharacteristic1" in ifs}
        if not all(u in chars for u in (NOTIFICATION_SOURCE, CONTROL_POINT, DATA_SOURCE)):
            return
        name = objects.get(device_path, {}).get("org.bluez.Device1", {}).get("Alias", "iPhone")
        log(f"service ANCS trouvé sur {name}")
        client = AncsClient(self.system, self.bridge, chars, name)
        self.clients[device_path] = client
        client.start()

    def _on_properties_changed(self, _conn, _sender, path, _iface, _signal, params):
        interface, changed, _invalid = params.unpack()
        if interface == "org.bluez.GattCharacteristic1" and "Value" in changed:
            for device_path, client in self.clients.items():
                if path.startswith(device_path + "/"):
                    client.on_value(path, bytes(changed["Value"]))
        elif interface == "org.bluez.Device1":
            if changed.get("Connected") is True:
                log("iPhone connecté")
                self._pair_if_needed(path)
            if changed.get("Paired") is True:
                log("appairage terminé")
                # iOS n'expose ANCS qu'après le chiffrement du lien : on recherche à nouveau.
                GLib.timeout_add_seconds(2, lambda: self._try_attach(path) and False)
            if changed.get("ServicesResolved") is True:
                self._try_attach(path)
            if changed.get("Connected") is False and path in self.clients:
                log("iPhone déconnecté")
                del self.clients[path]

    def _pair_if_needed(self, device_path):
        props = self.system.call_sync(
            BLUEZ, device_path, "org.freedesktop.DBus.Properties", "GetAll",
            GLib.Variant("(s)", ("org.bluez.Device1",)), None, Gio.DBusCallFlags.NONE, -1, None,
        ).unpack()[0]
        if props.get("Paired"):
            return
        log("demande d'appairage envoyée à l'iPhone")
        self.system.call(
            BLUEZ, device_path, "org.bluez.Device1", "Pair", None, None,
            Gio.DBusCallFlags.NONE, 60000, None, self._on_paired, device_path,
        )

    def _on_paired(self, bus, result, device_path):
        try:
            bus.call_finish(result)
            self.system.call_sync(
                BLUEZ, device_path, "org.freedesktop.DBus.Properties", "Set",
                GLib.Variant("(ssv)", ("org.bluez.Device1", "Trusted", GLib.Variant("b", True))),
                None, Gio.DBusCallFlags.NONE, -1, None,
            )
        except GLib.Error as error:
            log(f"appairage échoué : {error.message}")

    def _on_interfaces_added(self, _conn, _sender, _path, _iface, _signal, params):
        path, interfaces = params.unpack()
        if "org.bluez.GattCharacteristic1" in interfaces:
            device_path = "/".join(path.split("/")[:5])
            GLib.timeout_add(500, lambda: self._try_attach(device_path) and False)

    # --- lifecycle ------------------------------------------------------------

    def run(self):
        self._export(AGENT_XML, AGENT_PATH, self._agent_method)
        self._export(ADV_XML, ADV_PATH, self._adv_method, self._adv_property)
        self.system.call_sync(
            BLUEZ, "/org/bluez", "org.bluez.AgentManager1", "RegisterAgent",
            GLib.Variant("(os)", (AGENT_PATH, "DisplayYesNo")), None, Gio.DBusCallFlags.NONE, -1, None,
        )
        # Agent par défaut : c'est lui que BlueZ consulte quand l'iPhone lance l'appairage.
        self.system.call_sync(
            BLUEZ, "/org/bluez", "org.bluez.AgentManager1", "RequestDefaultAgent",
            GLib.Variant("(o)", (AGENT_PATH,)), None, Gio.DBusCallFlags.NONE, -1, None,
        )
        self.system.signal_subscribe(BLUEZ, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                     None, None, Gio.DBusSignalFlags.NONE, self._on_properties_changed)
        self.system.signal_subscribe(BLUEZ, "org.freedesktop.DBus.ObjectManager", "InterfacesAdded",
                                     None, None, Gio.DBusSignalFlags.NONE, self._on_interfaces_added)
        # Asynchrone : BlueZ relit nos propriétés d'annonce avant de répondre,
        # un appel synchrone bloquerait la boucle qui doit lui répondre.
        self.system.call(
            BLUEZ, ADAPTER_PATH, "org.bluez.LEAdvertisingManager1", "RegisterAdvertisement",
            GLib.Variant("(oa{sv})", (ADV_PATH, {})), None, Gio.DBusCallFlags.NONE, -1, None,
            self._on_advertising, None,
        )
        for path, ifs in self._managed_objects().items():
            if ifs.get("org.bluez.Device1", {}).get("ServicesResolved"):
                self._try_attach(path)
        if self.seconds:
            GLib.timeout_add_seconds(self.seconds, self.stop)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, 2, self.stop)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, 15, self.stop)
        self.loop.run()

    def _on_advertising(self, bus, result, _data):
        try:
            bus.call_finish(result)
            log("annonce Bluetooth « Covalence » active. Sur l'iPhone : Réglages > Bluetooth > Covalence")
        except GLib.Error as error:
            log(f"annonce refusée par BlueZ : {error.message}")
            self.stop()

    def stop(self):
        for call in (
            (ADAPTER_PATH, "org.bluez.LEAdvertisingManager1", "UnregisterAdvertisement", ADV_PATH),
            ("/org/bluez", "org.bluez.AgentManager1", "UnregisterAgent", AGENT_PATH),
        ):
            try:
                self.system.call_sync(BLUEZ, call[0], call[1], call[2], GLib.Variant("(o)", (call[3],)),
                                      None, Gio.DBusCallFlags.NONE, -1, None)
            except GLib.Error:
                pass
        log("arrêt")
        self.loop.quit()
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seconds", type=int, default=0, help="arrêt automatique après N secondes")
    args = parser.parse_args()
    try:
        Probe(args.seconds).run()
    except GLib.Error as error:
        log(f"erreur BlueZ : {error.message}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
