# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Bluetooth link with the iPhone: advertisement, pairing agent, device tracking.

The PC advertises itself as a Bluetooth LE accessory soliciting ANCS, so that
the iPhone connects to it and exposes ANCS and AMS. Classic profiles (HFP for
calls, A2DP/AVRCP) ride on the same bond through the identity address.

Pairing is only accepted inside an explicit pairing window started from the
app: outside it, the agent is not the default one and confirmations are refused.
Inside it, nothing is accepted on its own: the numeric comparison code waits for
the user to confirm in the app (or the notification) that the iPhone shows the
same code, « Just Works » requests are refused, and profiles are authorised only
for the expected iPhone services of the device the user confirmed (never HID:
a nearby keyboard must not slip in while the PC is visible).
During the window the PC is also discoverable over classic Bluetooth, so the
iPhone lists it in Settings › Bluetooth and pairs from there (no third-party
app needed); iOS derives the LE keys from that pairing, then opens the LE link
to our advertisement by itself.

BlueZ may list the iPhone twice: the bonded object (classic pairing, identity
address) and a second one created when the iPhone opens LE with a private
address, whose Address later turns into the same identity. Both are the same
phone: the bonded one is `device`, the other is a « shadow » that may carry the
GATT services (ANCS, AMS). Pairing is never requested again on a shadow (BlueZ
answers AlreadyExists), and an unpaired shadow is dropped once disconnected.

Reconnection backs off (10 s up to 5 min) and restarts at once after resume
from suspend or when the adapter powers on. When the iPhone has forgotten the
PC (« key missing »), every automatic attempt stops until the user pairs again:
retrying only makes the link flap.
"""

from gi.repository import Gio, GLib

from . import ams, ancs
from .gatt import find_service
from .i18n import _
from .util import BLUEZ, call_async, call_sync, get_all, log, set_prop

AGENT_PATH = "/io/github/melvincouwez/Covalence/agent"
ADV_PATH = "/io/github/melvincouwez/Covalence/advertisement"
APPLE_MODALIAS = "v004C"
RECONNECT_DELAYS = (10, 30, 60, 120, 300)  # seconds, one step per failed attempt
PAIRING_SECONDS = 180
CONFIRM_SECONDS = 60  # the user has this long to say the codes match
_BASE = "-0000-1000-8000-00805f9b34fb"
# Profiles the iPhone may open during the pairing window (16-bit Bluetooth SIG ids):
# HSP/HFP, A2DP, AVRCP, PBAP, MAP/MNS, PnP information, generic access/attribute.
IPHONE_SERVICES = {f"0000{short}{_BASE}" for short in (
    "1108", "1112", "111e", "111f", "110a", "110b", "110d", "110c", "110e", "110f",
    "112f", "1130", "1132", "1133", "1134", "1200", "1800", "1801")} | {
    ancs.SERVICE.lower(), ams.SERVICE.lower()}
# Never authorised from the agent, whatever the device: human interface devices.
HID_SERVICES = {f"0000{short}{_BASE}" for short in ("1124", "1812")}
# Errors meaning the iPhone no longer has our keys: only a new pairing helps.
BOND_LOST_ERRORS = ("key-missing", "AuthenticationFailed", "Authentication Failed",
                    "AuthenticationRejected", "Authentication Rejected")
SHADOW_KEYS = {"Connected", "ServicesResolved", "Paired", "Bonded", "Address"}
NOT_A_PHONE_ICONS = ("input-", "audio-", "camera-", "printer")


def bond_lost_error(error):
    return error is not None and any(k in error.message for k in BOND_LOST_ERRORS)

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
        self.pending_code = None  # {device, passkey, invocation, timer} waiting for the user
        self.confirmed = set()  # device paths and addresses the user confirmed this window
        self.previous_discoverable = None
        self.subscriptions = []
        self.registrations = []
        self.reconnect_timer = 0
        self.reconnect_failures = 0
        self.connecting = False
        self.le_connected = False  # a shadow object carries a live LE link
        self.pair_requested = set()
        self.bond_lost = False  # the iPhone removed the pairing: wait for a new one
        self.adapter_name = ""
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
        self.subscriptions.append(self.bus.signal_subscribe(
            "org.freedesktop.login1", "org.freedesktop.login1.Manager", "PrepareForSleep",
            "/org/freedesktop/login1", None, Gio.DBusSignalFlags.NONE, self._on_sleep))
        self.adapter_name = objects[self.adapter]["org.bluez.Adapter1"].get("Alias", "")
        self._pick_device(objects)
        self.update_advertising()
        self._schedule_reconnect(3)
        self.owner.link_changed()

    def _on_bluez_gone(self, _conn, _name):
        if self.adapter is None and not self.registrations:
            return
        log("Bluetooth : service BlueZ absent")
        for sub in self.subscriptions:
            self.bus.signal_unsubscribe(sub)
        for reg in self.registrations:
            self.bus.unregister_object(reg)
        for timer in (self.reconnect_timer, self.pairing_timer):
            if timer:
                GLib.source_remove(timer)
        self.subscriptions, self.registrations = [], []
        self.reconnect_timer = self.pairing_timer = 0
        self.connecting = self.pairing = False
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
                # The bonded object first, before an unpaired shadow with the same address.
                candidates.insert(0 if dev.get("Paired") else len(candidates), path)
            elif dev.get("Paired") and self._looks_like_iphone(dev):
                candidates.append(path)
        if candidates:
            self._set_device(candidates[0], objects)

    @property
    def address(self):
        return self.props.get("Address", "").upper()

    def _shadows(self, objects):
        """Other BlueZ objects of the same iPhone (same identity address)."""
        if not self.device or not self.address:
            return []
        return [p for p, i in objects.items()
                if p != self.device and p.startswith(self.adapter + "/")
                and i.get("org.bluez.Device1", {}).get("Address", "").upper() == self.address]

    def _is_shadow(self, path):
        if not self.device or path == self.device or not path.startswith(self.adapter + "/dev_"):
            return False
        try:
            dev = get_all(self.bus, BLUEZ, path, "org.bluez.Device1")
        except GLib.Error:
            return False
        return bool(self.address) and dev.get("Address", "").upper() == self.address

    @property
    def connected(self):
        """Any link up with the iPhone, classic or LE (possibly on a shadow)."""
        return bool(self.props.get("Connected") or self.le_connected)

    @staticmethod
    def _looks_like_iphone(dev, strict=True):
        icon = dev.get("Icon", "")
        if strict:
            return APPLE_MODALIAS in dev.get("Modalias", "") and icon == "phone"
        # Right after pairing Modalias and Icon may still be missing.
        return not icon.startswith(NOT_A_PHONE_ICONS)

    @staticmethod
    def plausible_iphone(dev):
        """Right after pairing: not something else (keyboard, headphones), and an Apple
        device whenever BlueZ already knows the maker."""
        if dev.get("Icon", "").startswith(NOT_A_PHONE_ICONS):
            return False
        modalias = dev.get("Modalias", "")
        return not modalias or APPLE_MODALIAS in modalias

    def _device_props(self, path):
        try:
            return get_all(self.bus, BLUEZ, path, "org.bluez.Device1")
        except GLib.Error:
            return {}

    def _set_device(self, path, objects=None):
        objects = objects or self._objects()
        ifaces = objects.get(path, {})
        self.device = path
        self.props = dict(ifaces.get("org.bluez.Device1", {}))
        self.battery = ifaces.get("org.bluez.Battery1", {}).get("Percentage", -1)
        if self.props.get("Paired") and self.props.get("AddressType") == "public":
            self.config.device_address = self.props.get("Address", "")
        if self.props.get("Paired") and not self.props.get("Trusted"):
            # Untrusted, BlueZ asks an agent for every profile the iPhone opens and
            # refuses them outside the pairing window: messages, calls and sound drop.
            self._trust(path)
        log(f"iPhone connu : {self.props.get('Alias', '?')}"
            f" ({'connecté' if self.props.get('Connected') else 'absent'})")
        self.owner.device_chosen(path)
        if self.props.get("Connected"):
            self._on_device_connected()
        self._attach(objects)

    def _trust(self, path):
        set_prop(self.bus, BLUEZ, path, "org.bluez.Device1", "Trusted", GLib.Variant("b", True),
                 what="iPhone non marqué de confiance")

    def forget(self):
        """Remove the iPhone from BlueZ (keys included), to pair again from scratch."""
        if not self.adapter or not self.device:
            return False
        path = self.device
        try:
            shadows = self._shadows(self._objects())
        except GLib.Error:
            shadows = []
        log("iPhone oublié à la demande")
        self._detach()
        for shadow in shadows:
            call_async(self.bus, BLUEZ, self.adapter, "org.bluez.Adapter1", "RemoveDevice",
                       GLib.Variant("(o)", (shadow,)))
        self.owner.device_disconnected()
        self.device, self.props, self.bond_lost, self.le_connected = None, {}, False, False
        self.config.device_address = ""
        call_async(self.bus, BLUEZ, self.adapter, "org.bluez.Adapter1", "RemoveDevice",
                   GLib.Variant("(o)", (path,)), what="oubli de l'iPhone")
        self.owner.link_changed()
        return True

    @property
    def problem(self):
        return "bond-lost" if self.bond_lost and self.device else ""

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
            # BlueZ drops advertisements when the adapter powers off: register again later.
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
        if self.bond_lost and self.device:
            # Our keys are stale: drop them so the iPhone's new pairing is a clean one.
            self.forget()
        if not self.pairing:
            try:
                call_sync(self.bus, BLUEZ, "/org/bluez", "org.bluez.AgentManager1", "RegisterAgent",
                          GLib.Variant("(os)", (AGENT_PATH, "DisplayYesNo")))
            except GLib.Error as error:
                if "AlreadyExists" not in error.message:
                    raise
            # Default agent: the one BlueZ asks when the iPhone starts pairing.
            call_sync(self.bus, BLUEZ, "/org/bluez", "org.bluez.AgentManager1",
                      "RequestDefaultAgent", GLib.Variant("(o)", (AGENT_PATH,)))
            adapter = get_all(self.bus, BLUEZ, self.adapter, "org.bluez.Adapter1")
            self.adapter_name = adapter.get("Alias", self.adapter_name)
            self.previous_pairable = adapter.get("Pairable")
            self.previous_discoverable = adapter.get("Discoverable")
            set_prop(self.bus, BLUEZ, self.adapter, "org.bluez.Adapter1", "Pairable",
                     GLib.Variant("b", True))
            # Classic discoverability: the iPhone lists the PC under Settings › Bluetooth.
            set_prop(self.bus, BLUEZ, self.adapter, "org.bluez.Adapter1", "DiscoverableTimeout",
                     GLib.Variant("u", PAIRING_SECONDS + 10))
            set_prop(self.bus, BLUEZ, self.adapter, "org.bluez.Adapter1", "Discoverable",
                     GLib.Variant("b", True), what="appairage : PC non visible")
            self.pairing = True
            self.pair_requested = set()
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
        if self.adapter:
            if self.previous_pairable is False:
                set_prop(self.bus, BLUEZ, self.adapter, "org.bluez.Adapter1", "Pairable",
                         GLib.Variant("b", False))
            if not self.previous_discoverable:
                set_prop(self.bus, BLUEZ, self.adapter, "org.bluez.Adapter1", "Discoverable",
                         GLib.Variant("b", False))
        self._answer_code(False)
        self.confirmed = set()
        self.notifier.close(self.pairing_note)
        self.pairing_note = 0
        log("appairage : fenêtre fermée")
        self.update_advertising()
        self.owner.link_changed()
        return False

    def _agent_method(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method == "RequestConfirmation":
            device, passkey = params.unpack()
            if not self.pairing:
                invocation.return_dbus_error("org.bluez.Error.Rejected", "not in pairing mode")
                return
            if not self.plausible_iphone(self._device_props(device)):
                log("appairage : appareil refusé (pas un iPhone)")
                invocation.return_dbus_error("org.bluez.Error.Rejected", "not an iPhone")
                return
            # Secure Simple Pairing / LE Secure Connections numeric comparison: the iPhone
            # shows the same code, and the user must say so here before BlueZ gets an answer.
            self._answer_code(False)  # a newer request replaces an unanswered one
            log("appairage : code de comparaison affiché, en attente de l'utilisateur")
            self.pending_code = {"device": device, "passkey": passkey, "invocation": invocation,
                                 "timer": GLib.timeout_add_seconds(
                                     CONFIRM_SECONDS, lambda: self._answer_code(False) and False)}
            self.pairing_note = self.notifier.notify(
                "Covalence", "bluetooth", _("Appairage avec l'iPhone"),
                _("L'iPhone affiche-t-il le code {code} ?").format(code=f"{passkey:06d}"),
                actions=[("match", _("Le code correspond")), ("cancel", _("Annuler"))],
                replaces=self.pairing_note, own=True,
                on_action=lambda key: self.confirm_pairing(key == "match"))
            self.owner.pairing_code(passkey)
        elif method == "RequestAuthorization":
            # « Just Works » pairing, without any code to compare: an iPhone never needs it.
            log("appairage sans code refusé")
            invocation.return_dbus_error("org.bluez.Error.Rejected", "no code to compare")
        elif method == "AuthorizeService":
            device, uuid = params.unpack()
            if self.service_allowed(device, uuid):
                invocation.return_value(None)
            else:
                log("appairage : profil refusé")
                invocation.return_dbus_error("org.bluez.Error.Rejected", "service not allowed")
        elif method == "Cancel":
            self._answer_code(False, reply=False)
            invocation.return_value(None)
        elif method in ("Release", "DisplayPinCode", "DisplayPasskey"):
            invocation.return_value(None)
        else:
            invocation.return_dbus_error("org.bluez.Error.Rejected", "unsupported")

    def service_allowed(self, device, uuid):
        """AuthorizeService during the window: iPhone profiles of the confirmed device."""
        uuid = (uuid or "").lower()
        if not self.pairing or uuid in HID_SERVICES or uuid not in IPHONE_SERVICES:
            return False
        if device == self.device or device in self.confirmed:
            return True
        address = self._device_props(device).get("Address", "").upper()
        return bool(address) and address in self.confirmed

    def confirm_pairing(self, matches):
        """The user's answer to the code comparison. False: no code was waiting."""
        if not self.pending_code:
            return False
        self._answer_code(bool(matches))
        return True

    def _answer_code(self, matches, reply=True):
        pending, self.pending_code = self.pending_code, None
        if not pending:
            return False
        if pending["timer"]:
            GLib.source_remove(pending["timer"])
        if not reply:
            return False  # BlueZ cancelled the request itself
        if not matches:
            log("appairage : code non confirmé, refusé")
            pending["invocation"].return_dbus_error("org.bluez.Error.Rejected", "code refused")
            self.owner.pairing_code_answered(False)
            return False
        device = pending["device"]
        self.confirmed.add(device)
        address = self._device_props(device).get("Address", "").upper()
        if address:
            self.confirmed.add(address)
        log("appairage : code confirmé par l'utilisateur")
        pending["invocation"].return_value(None)
        self.owner.pairing_code_answered(True)
        # Re-pairing a device BlueZ already lists may not change Paired: check later.
        GLib.timeout_add_seconds(6, lambda: self._check_paired(device) and False)
        return False

    def _pair(self, path):
        """The iPhone connected over LE during the window without pairing: ask it to."""
        if path in self.pair_requested or (self.props.get("Paired") and self._is_shadow(path)):
            return
        self.pair_requested.add(path)
        log("appairage : demande envoyée à l'iPhone")

        def done(_value, error):
            if error and "AlreadyExists" not in error.message:
                log(f"appairage échoué : {error.message}")
                self.pair_requested.discard(path)
                return
            self._check_paired(path)

        call_async(self.bus, BLUEZ, path, "org.bluez.Device1", "Pair", on_done=done, timeout=60000)

    def _check_paired(self, path):
        if not self.pairing:
            return
        try:
            dev = get_all(self.bus, BLUEZ, path, "org.bluez.Device1")
        except GLib.Error:
            return
        if dev.get("Paired"):
            self._pairing_done(path, dev)

    def _pairing_done(self, path, dev=None):
        if not self.pairing:
            return
        if dev is None:
            try:
                dev = get_all(self.bus, BLUEZ, path, "org.bluez.Device1")
            except GLib.Error:
                return
        address = dev.get("Address", "").upper()
        if path not in self.confirmed and address not in self.confirmed:
            # Paired without the user confirming our code (another agent, another device):
            # never trusted nor taken for the iPhone.
            return
        if not self.plausible_iphone(dev):
            # Something else paired meanwhile (mouse, headphones): not our business.
            return
        log("appairage terminé")
        self.bond_lost = False
        self.reconnect_failures = 0
        self._trust(path)
        if path != self.device and not (self.props.get("Paired") and self._is_shadow(path)):
            self._set_device(path)
        self.stop_pairing()
        self._attach()

    # --- signals ------------------------------------------------------------------------------------

    def _on_properties_changed(self, _conn, _sender, path, _iface, _signal, params):
        interface, changed, _invalid = params.unpack()
        if interface == "org.bluez.GattCharacteristic1" and "Value" in changed:
            for client in (self.ancs, self.ams):
                if client and client.owns(path):
                    client.on_value(path, bytes(changed["Value"]))
            return
        if interface == "org.bluez.Adapter1" and path == self.adapter:
            if "Alias" in changed:
                self.adapter_name = changed["Alias"]
                self.owner.link_changed()
            if changed.get("Powered") is True:
                self.update_advertising()
                self.reconnect_failures = 0
                self._schedule_reconnect(2)
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
        if self.pairing and (changed.get("Paired") is True or changed.get("Bonded") is True):
            self._pairing_done(path)
            if path != self.device:
                return
        if path != self.device and not SHADOW_KEYS.intersection(changed):
            return
        if path != self.device and self._is_shadow(path):
            self._shadow_changed(path, changed)
            return
        if path != self.device:
            if self.pairing and changed.get("Connected") is True:
                # Connected over LE (our advertisement) but not paired yet: ask for it.
                try:
                    if not get_all(self.bus, BLUEZ, path, "org.bluez.Device1").get("Paired"):
                        self._pair(path)
                except GLib.Error:
                    pass
            elif self.device is None and changed.get("Paired") is True:
                # Paired elsewhere (system settings): adopt it if it is an iPhone.
                try:
                    dev = get_all(self.bus, BLUEZ, path, "org.bluez.Device1")
                except GLib.Error:
                    return
                if self._looks_like_iphone(dev):
                    self._set_device(path)
            return
        was_connected = self.props.get("Connected")
        self.props.update(changed)
        if "RSSI" in changed:
            self.owner.device_rssi(changed["RSSI"])
        if changed.get("Connected") is True and not was_connected:
            log("iPhone connecté")
            self.reconnect_failures = 0
            self._on_device_connected()
        if changed.get("Connected") is False and was_connected:
            log("iPhone déconnecté")
            self._detach_under(path)
            self.owner.device_disconnected()
            self.reconnect_failures = 0
            self._schedule_reconnect()
        if changed.get("ServicesResolved") is False:
            self._detach_under(path)
        if changed.get("Paired") is True or changed.get("ServicesResolved") is True:
            if changed.get("Paired") is True:
                self._trust(path)
            # iOS exposes ANCS only once the link is encrypted: look again shortly.
            GLib.timeout_add_seconds(2, lambda: self._attach() and False)
        if changed.get("Paired") is False:
            log("iPhone : appairage supprimé")
            self.bond_lost = True
            self._detach()
        if "Address" in changed and self.props.get("AddressType") == "public" \
                and self.props.get("Paired"):
            self.config.device_address = changed["Address"]
        self.owner.link_changed()

    def _shadow_changed(self, path, changed):
        if changed.get("Connected") is True or changed.get("ServicesResolved") is True:
            GLib.timeout_add_seconds(2, lambda: self._attach() and False)
        if changed.get("Paired") is True:
            self._trust(path)
        if changed.get("Connected") is False:
            self._detach_under(path)
            try:
                dev = get_all(self.bus, BLUEZ, path, "org.bluez.Device1")
            except GLib.Error:
                dev = {}
            if not dev.get("Paired") and not self.pairing:
                # A leftover LE object: BlueZ makes a new one next time the iPhone comes.
                call_async(self.bus, BLUEZ, self.adapter, "org.bluez.Adapter1", "RemoveDevice",
                           GLib.Variant("(o)", (path,)))
        self._update_le()
        self.owner.link_changed()

    def _update_le(self, objects=None):
        try:
            objects = objects or self._objects()
        except GLib.Error:
            return
        self.le_connected = any(objects[p]["org.bluez.Device1"].get("Connected")
                                for p in self._shadows(objects))

    def _on_sleep(self, _conn, _sender, _path, _iface, _signal, params):
        (going_to_sleep,) = params.unpack()
        if not going_to_sleep:
            log("reprise après veille : reconnexion")
            self.reconnect_failures = 0
            self._schedule_reconnect(5)

    def _on_added(self, _conn, _sender, _path, _iface, _signal, params):
        path, interfaces = params.unpack()
        if self.device and "org.bluez.GattCharacteristic1" in interfaces \
                and not path.startswith(self.device + "/"):
            GLib.timeout_add(500, lambda: self._attach() and False)
        if self.device and path.startswith(self.device + "/"):
            if "org.bluez.GattCharacteristic1" in interfaces:
                GLib.timeout_add(500, lambda: self._attach() and False)
            if "org.bluez.MediaPlayer1" in interfaces:
                self.owner.media_changed()
        elif "org.bluez.Device1" in interfaces and self.device is None:
            dev = interfaces["org.bluez.Device1"]
            if dev.get("Paired") and self._looks_like_iphone(dev):
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
            self.device, self.props, self.bond_lost = None, {}, False
            try:
                self._pick_device(self._objects())
            except GLib.Error:
                pass
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

    def _gatt_hosts(self, objects):
        """Objects of the iPhone with a live, resolved link. BlueZ keeps the GATT
        database of a bonded device while it is away: subscribing to that cache only
        brings « Not connected » errors."""
        hosts = []
        for path in [self.device] + self._shadows(objects):
            dev = objects.get(path, {}).get("org.bluez.Device1", {})
            if dev.get("Connected") and dev.get("ServicesResolved"):
                hosts.append(path)
        return hosts

    def _find(self, objects, hosts, uuid):
        return next((c for c in (find_service(objects, h, uuid) for h in hosts) if c), None)

    def _attach(self, objects=None):
        if not self.device:
            return
        objects = objects or self._objects()
        self._update_le(objects)
        hosts = self._gatt_hosts(objects)
        if not hosts:
            return
        if self.ancs is None and self.config.module_enabled("notifications"):
            chars = self._find(objects, hosts, ancs.SERVICE)
            if chars and all(u in chars for u in (ancs.NOTIFICATION_SOURCE, ancs.CONTROL_POINT,
                                                   ancs.DATA_SOURCE)):
                log("ANCS : service trouvé, abonnement")
                self.bond_lost = False
                self.ancs = ancs.AncsClient(self.bus, chars, self.name, self.notifier, self.owner)
                self.ancs.on_link_lost = lambda: self._detach(("ancs",))
                self.ancs.start()
                self.owner.link_changed()
        if self.ams is None and self.config.module_enabled("media"):
            chars = self._find(objects, hosts, ams.SERVICE)
            if chars and all(u in chars for u in (ams.REMOTE_COMMAND, ams.ENTITY_UPDATE)):
                self.ams = ams.AmsClient(self.bus, chars, self.owner.media_state_changed)
                self.ams.on_link_lost = lambda: self._detach(("ams",))
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

    def _detach_under(self, path):
        """Drop the GATT clients living on this object (its link went down)."""
        for attr in ("ancs", "ams"):
            client = getattr(self, attr)
            if client and any(p.startswith(path + "/") for p in client.chars.values()):
                self._detach((attr,))

    def _detach_if_gone(self):
        objects = self._objects()
        hosts = [self.device] + self._shadows(objects)
        if self.ancs and self._find(objects, hosts, ancs.SERVICE) is None:
            self._detach(("ancs",))
        if self.ams and self._find(objects, hosts, ams.SERVICE) is None:
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

    def _schedule_reconnect(self, delay=None):
        if self.reconnect_timer:
            GLib.source_remove(self.reconnect_timer)
        if delay is None:
            delay = RECONNECT_DELAYS[min(self.reconnect_failures, len(RECONNECT_DELAYS) - 1)]
        self.reconnect_timer = GLib.timeout_add_seconds(delay, self._reconnect_tick)

    def _should_reconnect(self):
        if not self.adapter or not self.device or self.bond_lost or self.pairing:
            return False
        if self.props.get("Connected") or not self.props.get("Paired"):
            return False
        try:
            return bool(get_all(self.bus, BLUEZ, self.adapter, "org.bluez.Adapter1").get("Powered"))
        except GLib.Error:
            return False

    def _reconnect_tick(self):
        """Bring the classic link back (HFP, AVRCP, MAP) when the iPhone is around.

        LE (ANCS/AMS) cannot be initiated from the PC: the iPhone's advertisements
        are not connectable, so it has to connect to our advertisement itself.
        """
        self.reconnect_timer = 0
        if self.connecting or not self._should_reconnect():
            return False
        self.connecting = True

        def done(_value, error):
            self.connecting = False
            if error is None:
                log("reconnexion : iPhone reconnecté")
                self.reconnect_failures = 0
                self.bond_lost = False
                return
            self.connect_failed(error)
            if not self.bond_lost and not self.props.get("Connected"):
                self._schedule_reconnect()

        call_async(self.bus, BLUEZ, self.device, "org.bluez.Device1", "Connect",
                   on_done=done, timeout=30000)
        return False

    def connect_failed(self, error):
        """A connection or profile request to the iPhone failed (also used by calls)."""
        if bond_lost_error(error):
            if not self.bond_lost:
                log("iPhone : il ne reconnaît plus ce PC (appairage supprimé sur l'iPhone),"
                    " reconnexions automatiques suspendues")
                self.bond_lost = True
                if self.reconnect_timer:
                    GLib.source_remove(self.reconnect_timer)
                    self.reconnect_timer = 0
                self.owner.link_changed()
            return
        self.reconnect_failures += 1
        if self.reconnect_failures in (1, 5) or self.reconnect_failures % 20 == 0:
            log(f"reconnexion : iPhone injoignable ({error.message}),"
                f" {self.reconnect_failures} essai(s)")

    def reconnect_now(self):
        self.reconnect_failures = 0
        self.bond_lost = False  # the user may have fixed it on the iPhone: try once
        self._schedule_reconnect(0)
