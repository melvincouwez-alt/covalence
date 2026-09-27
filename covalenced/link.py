# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Bluetooth link with the iPhone: advertisement, pairing agent, device tracking.

The PC advertises itself as a Bluetooth LE accessory soliciting ANCS, so that
the iPhone connects to it and exposes ANCS and AMS. Classic profiles (HFP for
calls, A2DP/AVRCP) ride on the same bond through the identity address.

Pairing is only accepted inside an explicit pairing window started from the
app: outside it, the agent is not the default one and confirmations are refused.
"""

from gi.repository import Gio, GLib

from . import ams, ancs
from .gatt import find_service
from .i18n import _
from .util import BLUEZ, call_async, call_sync, get_all, log, set_prop

AGENT_PATH = "/io/github/melvincouwez/Covalence/agent"
ADV_PATH = "/io/github/melvincouwez/Covalence/advertisement"
APPLE_MODALIAS = "v004C"
RECONNECT_INTERVAL = 120  # seconds between classic reconnection attempts
PAIRING_SECONDS = 180

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


class Link:
    def __init__(self, system, notifier, config, owner):
        self.bus = system
        self.notifier = notifier
        self.config = config
        self.owner = owner  # the Daemon: hooks and state changes
        self.adapter = None
        self.device = None  # object path of the known iPhone
        self.props = {}  # its Device1 properties
        self.battery = -1
        self.ancs = None
        self.ams = None
        self.advertising = False
        self.adv_wanted = False
        self.pairing = False
        self.pairing_timer = 0
        self.pairing_note = 0
        self.previous_pairable = None
        self.subscriptions = []
        self.registrations = []
        self.reconnect_timer = 0
        self.reconnect_failures = 0
        self.watch_id = Gio.bus_watch_name_on_connection(
            system, BLUEZ, Gio.BusNameWatcherFlags.NONE, self._on_bluez, self._on_bluez_gone)

    # --- BlueZ availability ---------------------------------------------------------

    def _on_bluez(self, _conn, _name, _owner):
        objects = self._objects()
        self.adapter = next((p for p, i in sorted(objects.items()) if "org.bluez.Adapter1" in i), None)
        if self.adapter is None:
            log("aucun adaptateur Bluetooth")
            return
        log(f"Bluetooth : adaptateur {self.adapter}")
        self._export()
        for member, handler in (("InterfacesAdded", self._on_added),
                                ("InterfacesRemoved", self._on_removed)):
            self.subscriptions.append(self.bus.signal_subscribe(
                BLUEZ, "org.freedesktop.DBus.ObjectManager", member, None, None,
                Gio.DBusSignalFlags.NONE, handler))
        self.subscriptions.append(self.bus.signal_subscribe(
            BLUEZ, "org.freedesktop.DBus.Properties", "PropertiesChanged", None, None,
            Gio.DBusSignalFlags.NONE, self._on_properties_changed))
        self._pick_device(objects)
        self.update_advertising()
        self.reconnect_timer = GLib.timeout_add_seconds(RECONNECT_INTERVAL, self._reconnect_tick)
        GLib.timeout_add_seconds(3, lambda: self._reconnect_tick() and False)
        self.owner.link_changed()

    def _on_bluez_gone(self, _conn, _name):
        if self.adapter is None and not self.registrations:
            return
        log("Bluetooth : service BlueZ absent")
        for sub in self.subscriptions:
            self.bus.signal_unsubscribe(sub)
        for reg in self.registrations:
            self.bus.unregister_object(reg)
        if self.reconnect_timer:
            GLib.source_remove(self.reconnect_timer)
        self.subscriptions, self.registrations, self.reconnect_timer = [], [], 0
        self._detach()
        self.adapter, self.device, self.props, self.advertising = None, None, {}, False
        self.owner.link_changed()

    def _objects(self):
        return call_sync(self.bus, BLUEZ, "/", "org.freedesktop.DBus.ObjectManager",
                         "GetManagedObjects", reply="(a{oa{sa{sv}}})").unpack()[0]

    def _export(self):
        for xml, path, method, prop in ((AGENT_XML, AGENT_PATH, self._agent_method, None),
                                        (ADV_XML, ADV_PATH, self._adv_method, self._adv_property)):
            info = Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0]
            self.registrations.append(self.bus.register_object(path, info, method, prop, None))

    # --- known device ---------------------------------------------------------------------

    def _pick_device(self, objects):
        wanted = self.config.device_address.upper()
        candidates = []
        for path, ifaces in objects.items():
            dev = ifaces.get("org.bluez.Device1")
            if not dev or not path.startswith(self.adapter + "/"):
                continue
            if wanted and dev.get("Address", "").upper() == wanted:
                candidates.insert(0, path)
            elif not wanted and dev.get("Paired") and APPLE_MODALIAS in dev.get("Modalias", "") \
                    and dev.get("Icon") == "phone":
                candidates.append(path)
        if candidates:
            self._set_device(candidates[0], objects)

    def _set_device(self, path, objects=None):
        objects = objects or self._objects()
        ifaces = objects.get(path, {})
        self.device = path
        self.props = dict(ifaces.get("org.bluez.Device1", {}))
        self.battery = ifaces.get("org.bluez.Battery1", {}).get("Percentage", -1)
        if self.props.get("Paired") and self.props.get("AddressType") == "public":
            self.config.device_address = self.props.get("Address", "")
        log(f"iPhone connu : {self.props.get('Alias', '?')}"
            f" ({'connecté' if self.props.get('Connected') else 'absent'})")
        self.owner.device_chosen(path)
        if self.props.get("Connected"):
            self._on_device_connected()
        self._attach(objects)

    @property
    def name(self):
        return self.props.get("Alias") or "iPhone"

    # --- advertisement ------------------------------------------------------------------------

    def update_advertising(self):
        wanted = self.adapter is not None and (
            self.pairing or self.config.module_enabled("notifications")
            or self.config.module_enabled("media"))
        self.adv_wanted = wanted
        if wanted and not self.advertising:
            # Asynchronous: BlueZ reads our properties before replying.
            call_async(self.bus, BLUEZ, self.adapter, "org.bluez.LEAdvertisingManager1",
                       "RegisterAdvertisement", GLib.Variant("(oa{sv})", (ADV_PATH, {})),
                       on_done=self._on_advertising)
            self.advertising = True
        elif not wanted and self.advertising:
            call_async(self.bus, BLUEZ, self.adapter, "org.bluez.LEAdvertisingManager1",
                       "UnregisterAdvertisement", GLib.Variant("(o)", (ADV_PATH,)))
            self.advertising = False
            log("Bluetooth : annonce arrêtée")

    def _on_advertising(self, _value, error):
        if error:
            self.advertising = False
            log(f"Bluetooth : annonce refusée ({error.message})")
        else:
            log("Bluetooth : annonce « Covalence » active")
        self.owner.link_changed()

    def _adv_method(self, _conn, _sender, _path, _iface, method, _params, invocation):
        if method == "Release":
            self.advertising = False
        invocation.return_value(None)

    def _adv_property(self, _conn, _sender, _path, _iface, name):
        return {
            "Type": GLib.Variant("s", "peripheral"),
            "LocalName": GLib.Variant("s", "Covalence"),
            "SolicitUUIDs": GLib.Variant("as", [ancs.SERVICE]),
            # General discoverable flag: without it the iPhone does not list the accessory.
            # No Appearance: with the 128-bit UUID the packet would exceed 31 bytes.
            "Discoverable": GLib.Variant("b", True),
            "Includes": GLib.Variant("as", []),
        }[name]

    # --- pairing ------------------------------------------------------------------------------------

    def start_pairing(self):
        if self.adapter is None:
            return False
        if not self.pairing:
            call_sync(self.bus, BLUEZ, "/org/bluez", "org.bluez.AgentManager1", "RegisterAgent",
                      GLib.Variant("(os)", (AGENT_PATH, "DisplayYesNo")))
            # Default agent: the one BlueZ asks when the iPhone starts pairing.
            call_sync(self.bus, BLUEZ, "/org/bluez", "org.bluez.AgentManager1",
                      "RequestDefaultAgent", GLib.Variant("(o)", (AGENT_PATH,)))
            self.previous_pairable = get_all(self.bus, BLUEZ, self.adapter,
                                             "org.bluez.Adapter1").get("Pairable")
            set_prop(self.bus, BLUEZ, self.adapter, "org.bluez.Adapter1", "Pairable",
                     GLib.Variant("b", True))
            self.pairing = True
            log("appairage : fenêtre ouverte")
        if self.pairing_timer:
            GLib.source_remove(self.pairing_timer)
        self.pairing_timer = GLib.timeout_add_seconds(PAIRING_SECONDS, self.stop_pairing)
        self.update_advertising()
        self.owner.link_changed()
        return True

    def stop_pairing(self):
        if self.pairing_timer:
            GLib.source_remove(self.pairing_timer)
            self.pairing_timer = 0
        if not self.pairing:
            return False
        self.pairing = False
        try:
            call_sync(self.bus, BLUEZ, "/org/bluez", "org.bluez.AgentManager1", "UnregisterAgent",
                      GLib.Variant("(o)", (AGENT_PATH,)))
        except GLib.Error:
            pass
        if self.previous_pairable is False:
            set_prop(self.bus, BLUEZ, self.adapter, "org.bluez.Adapter1", "Pairable",
                     GLib.Variant("b", False))
        log("appairage : fenêtre fermée")
        self.update_advertising()
        self.owner.link_changed()
        return False

    def _agent_method(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method == "RequestConfirmation":
            if not self.pairing:
                invocation.return_dbus_error("org.bluez.Error.Rejected", "not in pairing mode")
                return
            _device, passkey = params.unpack()
            # LE Secure Connections numeric comparison: the iPhone shows the same code.
            log("appairage : code de comparaison affiché")
            self.pairing_note = self.notifier.notify(
                "Covalence", "bluetooth", _("Appairage avec l'iPhone"),
                _("Vérifiez que l'iPhone affiche le code {code}").format(code=f"{passkey:06d}"),
                replaces=self.pairing_note, own=True)
            self.owner.pairing_code(passkey)
            invocation.return_value(None)
        elif method in ("RequestAuthorization", "AuthorizeService"):
            if self.pairing:
                invocation.return_value(None)
            else:
                invocation.return_dbus_error("org.bluez.Error.Rejected", "not in pairing mode")
        elif method in ("Release", "Cancel", "DisplayPinCode", "DisplayPasskey"):
            invocation.return_value(None)
        else:
            invocation.return_dbus_error("org.bluez.Error.Rejected", "unsupported")

    def _pair(self, path):
        log("appairage : demande envoyée à l'iPhone")

        def done(_value, error):
            if error:
                log(f"appairage échoué : {error.message}")
                return
            set_prop(self.bus, BLUEZ, path, "org.bluez.Device1", "Trusted", GLib.Variant("b", True))

        call_async(self.bus, BLUEZ, path, "org.bluez.Device1", "Pair", on_done=done, timeout=60000)

    # --- signals ------------------------------------------------------------------------------------

    def _on_properties_changed(self, _conn, _sender, path, _iface, _signal, params):
        interface, changed, _invalid = params.unpack()
        if interface == "org.bluez.GattCharacteristic1" and "Value" in changed:
            for client in (self.ancs, self.ams):
                if client and client.owns(path):
                    client.on_value(path, bytes(changed["Value"]))
            return
        if interface == "org.bluez.Adapter1" and path == self.adapter and changed.get("Powered"):
            GLib.timeout_add_seconds(2, lambda: self._reconnect_tick() and False)
            return
        if interface == "org.bluez.MediaPlayer1" and self.device and path.startswith(self.device + "/"):
            self.owner.avrcp_player_changed(path, changed)
            return
        if interface == "org.bluez.MediaControl1" and path == self.device:
            self.owner.avrcp_control_changed(path, changed)
            return
        if interface == "org.bluez.Battery1" and path == self.device and "Percentage" in changed:
            self.battery = changed["Percentage"]
            self.owner.battery_changed(self.battery)
            return
        if interface != "org.bluez.Device1":
            return
        if path != self.device:
            # A phone connecting during the pairing window is paired here.
            if self.pairing and changed.get("Connected") is True:
                self._pair(path)
            if changed.get("Paired") is True and self.pairing:
                log("appairage terminé")
                self.notifier.close(self.pairing_note)
                self.pairing_note = 0
                self._set_device(path)
                self.stop_pairing()
            return
        was_connected = self.props.get("Connected")
        self.props.update(changed)
        if changed.get("Connected") is True and not was_connected:
            log("iPhone connecté")
            self.reconnect_failures = 0
            self._on_device_connected()
        if changed.get("Connected") is False:
            log("iPhone déconnecté")
            self._detach()
            self.owner.device_disconnected()
        if changed.get("Paired") is True or changed.get("ServicesResolved") is True:
            # iOS exposes ANCS only once the link is encrypted: look again shortly.
            GLib.timeout_add_seconds(2, lambda: self._attach() and False)
        if "Address" in changed and self.props.get("AddressType") == "public" \
                and self.props.get("Paired"):
            self.config.device_address = changed["Address"]
        self.owner.link_changed()

    def _on_added(self, _conn, _sender, _path, _iface, _signal, params):
        path, interfaces = params.unpack()
        if self.device and path.startswith(self.device + "/"):
            if "org.bluez.GattCharacteristic1" in interfaces:
                GLib.timeout_add(500, lambda: self._attach() and False)
            if "org.bluez.MediaPlayer1" in interfaces:
                self.owner.media_changed()
        elif "org.bluez.Device1" in interfaces and self.device is None:
            dev = interfaces["org.bluez.Device1"]
            if dev.get("Paired") and APPLE_MODALIAS in dev.get("Modalias", ""):
                self._set_device(path)
        if path == self.device and "org.bluez.MediaControl1" in interfaces:
            self.owner.media_changed()
        if path == self.device and "org.bluez.Battery1" in interfaces:
            self.battery = interfaces["org.bluez.Battery1"].get("Percentage", -1)
            self.owner.battery_changed(self.battery)

    def _on_removed(self, _conn, _sender, path, _iface, _signal, params):
        path, interfaces = params.unpack()
        if path == self.device and "org.bluez.Device1" in interfaces:
            log("iPhone retiré de BlueZ")
            self._detach()
            self.owner.device_disconnected()
            self.device, self.props = None, {}
            self.owner.link_changed()
        elif self.device and path.startswith(self.device + "/"):
            if "org.bluez.MediaPlayer1" in interfaces:
                self.owner.media_changed()
            if "org.bluez.GattService1" in interfaces:
                self._detach_if_gone()
        if path == self.device and "org.bluez.Battery1" in interfaces:
            self.battery = -1
            self.owner.battery_changed(-1)

    # --- GATT services ------------------------------------------------------------------------

    def _attach(self, objects=None):
        if not self.device:
            return
        objects = objects or self._objects()
        if self.ancs is None and self.config.module_enabled("notifications"):
            chars = find_service(objects, self.device, ancs.SERVICE)
            if chars and all(u in chars for u in (ancs.NOTIFICATION_SOURCE, ancs.CONTROL_POINT,
                                                   ancs.DATA_SOURCE)):
                log("ANCS : service trouvé, abonnement")
                self.ancs = ancs.AncsClient(self.bus, chars, self.name, self.notifier, self.owner)
                self.ancs.start()
                self.owner.link_changed()
        if self.ams is None and self.config.module_enabled("media"):
            chars = find_service(objects, self.device, ams.SERVICE)
            if chars and all(u in chars for u in (ams.REMOTE_COMMAND, ams.ENTITY_UPDATE)):
                self.ams = ams.AmsClient(self.bus, chars, self.owner.media_state_changed)
                self.ams.start()
                self.owner.media_changed()

    def _detach(self, which=("ancs", "ams")):
        for attr in which:
            client = getattr(self, attr)
            if client:
                client.stop()
                setattr(self, attr, None)
        self.owner.media_changed()
        self.owner.link_changed()

    def _detach_if_gone(self):
        objects = self._objects()
        if self.ancs and find_service(objects, self.device, ancs.SERVICE) is None:
            self._detach(("ancs",))
        if self.ams and find_service(objects, self.device, ams.SERVICE) is None:
            self._detach(("ams",))

    def module_toggled(self):
        """Apply notifications/media module switches."""
        if self.ancs and not self.config.module_enabled("notifications"):
            self._detach(("ancs",))
        if self.ams and not self.config.module_enabled("media"):
            self._detach(("ams",))
        self._attach()
        self.update_advertising()

    def has_avrcp_player(self):
        if not self.device:
            return False
        return any(p.startswith(self.device + "/") and "org.bluez.MediaPlayer1" in i
                   for p, i in self._objects().items())

    # --- reconnection -----------------------------------------------------------------------

    def _on_device_connected(self):
        self.owner.device_connected(self.device, self.props.get("Address", ""))

    def _reconnect_tick(self):
        """Bring the classic link back (HFP, AVRCP) when the iPhone is around.

        LE (ANCS/AMS) cannot be initiated from the PC: the iPhone's advertisements
        are not connectable, so it has to connect to our advertisement itself.
        """
        if not self.device or self.props.get("Connected") or not self.props.get("Paired"):
            return True
        powered = get_all(self.bus, BLUEZ, self.adapter, "org.bluez.Adapter1").get("Powered")
        if not powered:
            return True

        def done(_value, error):
            if error:
                self.reconnect_failures += 1
                if self.reconnect_failures in (1, 10) or self.reconnect_failures % 30 == 0:
                    log(f"reconnexion : iPhone injoignable ({error.message}),"
                        f" {self.reconnect_failures} essai(s)")
            else:
                log("reconnexion : iPhone reconnecté")

        call_async(self.bus, BLUEZ, self.device, "org.bluez.Device1", "Connect",
                   on_done=done, timeout=30000)
        return True

    def reconnect_now(self):
        self.reconnect_failures = 0
        self._reconnect_tick()
