# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Contrôle de l'iPhone (experimental): the PC as a Bluetooth LE mouse and keyboard.

HID over GATT (service 0x1812): the daemon publishes a GATT server with one
keyboard report (id 1) and one relative mouse report (id 2), and a second
advertisement ("Covalence", appearance: HID). The iPhone pairs it in Réglages ›
Bluetooth; the pointer then needs AssistiveTouch (Accessibilité › Toucher ›
AssistiveTouch), which turns mouse moves into a pointer, a left click into a tap
and a right click into the AssistiveTouch menu.

Keys are sent by position (evdev key code of the PC's keyboard), so the layout
chosen on the iPhone (Réglages › Général › Clavier › Clavier physique) decides the
characters, as with a real keyboard. Text typed in Covalence's field goes through
the French PC (AZERTY) layout below.

Off by default ([alpha] iphone_control). Nothing is published while it is off.
"""

from gi.repository import Gio, GLib

from .util import BLUEZ, call_async, call_sync, log

SERVICE = "00001812-0000-1000-8000-00805f9b34fb"
APP_PATH = "/io/github/melvincouwez/Covalence/hid"
ADV_PATH = "/io/github/melvincouwez/Covalence/hid_advertisement"
APPEARANCE_HID = 0x03C0
SEND_INTERVAL_MS = 8  # between two reports: the iPhone drops reports sent too fast

KEYBOARD_ID, MOUSE_ID = 1, 2
TYPES = {"enabled": "b", "registered": "b", "connected": "b", "error": "s", "width": "i",
         "height": "i"}

# Keyboard (id 1): modifiers, reserved, six keys. Mouse (id 2): three buttons, x, y, wheel.
REPORT_MAP = bytes([
    0x05, 0x01, 0x09, 0x06, 0xA1, 0x01, 0x85, KEYBOARD_ID,
    0x05, 0x07, 0x19, 0xE0, 0x29, 0xE7, 0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x08, 0x81, 0x02,
    0x95, 0x01, 0x75, 0x08, 0x81, 0x01,
    0x95, 0x06, 0x75, 0x08, 0x15, 0x00, 0x25, 0x65, 0x05, 0x07, 0x19, 0x00, 0x29, 0x65, 0x81, 0x00,
    0xC0,
    0x05, 0x01, 0x09, 0x02, 0xA1, 0x01, 0x85, MOUSE_ID, 0x09, 0x01, 0xA1, 0x00,
    0x05, 0x09, 0x19, 0x01, 0x29, 0x03, 0x15, 0x00, 0x25, 0x01, 0x95, 0x03, 0x75, 0x01, 0x81, 0x02,
    0x95, 0x01, 0x75, 0x05, 0x81, 0x01,
    0x05, 0x01, 0x09, 0x30, 0x09, 0x31, 0x09, 0x38, 0x15, 0x81, 0x25, 0x7F, 0x75, 0x08, 0x95, 0x03,
    0x81, 0x06,
    0xC0, 0xC0,
])

LCTRL, LSHIFT, LALT, LGUI, RCTRL, RSHIFT, RALT, RGUI = (1 << i for i in range(8))
BUTTON_LEFT, BUTTON_RIGHT, BUTTON_MIDDLE = 1, 2, 4

# Linux evdev key code -> HID usage (keyboard page), by physical position.
EVDEV_TO_HID = {
    1: 0x29, 2: 0x1E, 3: 0x1F, 4: 0x20, 5: 0x21, 6: 0x22, 7: 0x23, 8: 0x24, 9: 0x25, 10: 0x26,
    11: 0x27, 12: 0x2D, 13: 0x2E, 14: 0x2A, 15: 0x2B, 16: 0x14, 17: 0x1A, 18: 0x08, 19: 0x15,
    20: 0x17, 21: 0x1C, 22: 0x18, 23: 0x0C, 24: 0x12, 25: 0x13, 26: 0x2F, 27: 0x30, 28: 0x28,
    30: 0x04, 31: 0x16, 32: 0x07, 33: 0x09, 34: 0x0A, 35: 0x0B, 36: 0x0D, 37: 0x0E, 38: 0x0F,
    39: 0x33, 40: 0x34, 41: 0x35, 43: 0x32, 44: 0x1D, 45: 0x1B, 46: 0x06, 47: 0x19, 48: 0x05,
    49: 0x11, 50: 0x10, 51: 0x36, 52: 0x37, 53: 0x38, 57: 0x2C, 58: 0x39,
    59: 0x3A, 60: 0x3B, 61: 0x3C, 62: 0x3D, 63: 0x3E, 64: 0x3F, 65: 0x40, 66: 0x41, 67: 0x42,
    68: 0x43, 87: 0x44, 88: 0x45, 86: 0x64, 96: 0x58, 102: 0x4A, 103: 0x52, 104: 0x4B, 105: 0x50,
    106: 0x4F, 107: 0x4D, 108: 0x51, 109: 0x4E, 110: 0x49, 111: 0x4C,
}
EVDEV_MODIFIERS = {29: LCTRL, 42: LSHIFT, 56: LALT, 125: LGUI, 97: RCTRL, 54: RSHIFT,
                   100: RALT, 126: RGUI}


def _azerty():
    """Character -> (HID usage, modifiers) on the French PC keyboard."""
    table = {}
    letters = {"a": 0x14, "z": 0x1A, "e": 0x08, "r": 0x15, "t": 0x17, "y": 0x1C, "u": 0x18,
               "i": 0x0C, "o": 0x12, "p": 0x13, "q": 0x04, "s": 0x16, "d": 0x07, "f": 0x09,
               "g": 0x0A, "h": 0x0B, "j": 0x0D, "k": 0x0E, "l": 0x0F, "m": 0x33, "w": 0x1D,
               "x": 0x1B, "c": 0x06, "v": 0x19, "b": 0x05, "n": 0x11}
    for char, usage in letters.items():
        table[char] = (usage, 0)
        table[char.upper()] = (usage, LSHIFT)
    plain = "&é\"'(-è_çà"
    for i, char in enumerate(plain):
        table[char] = (0x1E + i, 0)
        table["1234567890"[i]] = (0x1E + i, LSHIFT)
    for chars, usage in ((")°", 0x2D), ("=+", 0x2E), ("$£", 0x30), ("ù%", 0x34), ("*µ", 0x32),
                         ("<>", 0x64), (",?", 0x10), (";.", 0x36), (":/", 0x37), ("!§", 0x38),
                         ("²", 0x35)):
        table[chars[0]] = (usage, 0)
        if len(chars) > 1:
            table[chars[1]] = (usage, LSHIFT)
    for char, usage in (("#", 0x20), ("{", 0x21), ("[", 0x22), ("|", 0x23), ("\\", 0x25),
                        ("@", 0x27), ("]", 0x2D), ("}", 0x2E), ("€", 0x08), ("~", 0x1F),
                        ("`", 0x24), ("^", 0x26)):
        table[char] = (usage, RALT)
    table[" "] = (0x2C, 0)
    table["\n"] = (0x28, 0)
    table["\t"] = (0x2B, 0)
    return table


AZERTY = _azerty()


def keyboard_report(modifiers=0, keys=()):
    keys = list(keys)[:6]
    return bytes([modifiers & 0xFF, 0] + keys + [0] * (6 - len(keys)))


def _clamp(value):
    return max(-127, min(127, int(value)))


def mouse_report(buttons=0, dx=0, dy=0, wheel=0):
    return bytes([buttons & 0x07, _clamp(dx) & 0xFF, _clamp(dy) & 0xFF, _clamp(wheel) & 0xFF])


def split_move(dx, dy, step=127):
    """A move of any size as steps of at most `step` on each axis, same direction."""
    dx, dy = int(round(dx)), int(round(dy))
    moves = []
    while dx or dy:
        sx = max(-step, min(step, dx))
        sy = max(-step, min(step, dy))
        moves.append((sx, sy))
        dx -= sx
        dy -= sy
    return moves


def home_moves(width, height):
    """Enough large moves up and left to put the pointer in the top left corner."""
    return split_move(-2 * width - 254, -2 * height - 254)


def goto_moves(fx, fy, width, height):
    """From anywhere to a point of the screen given as fractions (0..1) of its size."""
    fx, fy = max(0.0, min(1.0, fx)), max(0.0, min(1.0, fy))
    return home_moves(width, height) + split_move(fx * width, fy * height)


def text_reports(text):
    """Key press and release reports for a text; characters with no key are skipped."""
    reports, skipped = [], 0
    for char in text:
        found = AZERTY.get(char)
        if found is None:
            skipped += 1
            continue
        usage, mods = found
        reports.append(keyboard_report(mods, [usage]))
        reports.append(keyboard_report())
    return reports, skipped


# --- GATT server ------------------------------------------------------------------------------

GATT_XML = """
<node>
  <interface name="org.freedesktop.DBus.ObjectManager">
    <method name="GetManagedObjects">
      <arg name="objects" type="a{oa{sa{sv}}}" direction="out"/>
    </method>
  </interface>
  <interface name="org.bluez.GattService1">
    <property name="UUID" type="s" access="read"/>
    <property name="Primary" type="b" access="read"/>
  </interface>
  <interface name="org.bluez.GattCharacteristic1">
    <method name="ReadValue">
      <arg name="options" type="a{sv}" direction="in"/><arg name="value" type="ay" direction="out"/>
    </method>
    <method name="WriteValue">
      <arg name="value" type="ay" direction="in"/><arg name="options" type="a{sv}" direction="in"/>
    </method>
    <method name="StartNotify"/>
    <method name="StopNotify"/>
    <property name="UUID" type="s" access="read"/>
    <property name="Service" type="o" access="read"/>
    <property name="Flags" type="as" access="read"/>
    <property name="Value" type="ay" access="read"/>
  </interface>
  <interface name="org.bluez.GattDescriptor1">
    <method name="ReadValue">
      <arg name="options" type="a{sv}" direction="in"/><arg name="value" type="ay" direction="out"/>
    </method>
    <property name="UUID" type="s" access="read"/>
    <property name="Characteristic" type="o" access="read"/>
    <property name="Flags" type="as" access="read"/>
  </interface>
  <interface name="org.bluez.LEAdvertisement1">
    <method name="Release"/>
    <property name="Type" type="s" access="read"/>
    <property name="LocalName" type="s" access="read"/>
    <property name="ServiceUUIDs" type="as" access="read"/>
    <property name="Appearance" type="q" access="read"/>
    <property name="Discoverable" type="b" access="read"/>
  </interface>
</node>
"""


def _uuid16(short):
    return "0000%04x-0000-1000-8000-00805f9b34fb" % short


def gatt_objects():
    """path -> (interface, properties without Service/Characteristic links, value)."""
    hid = APP_PATH + "/service0"
    info = APP_PATH + "/service1"
    objects = {
        hid: ("org.bluez.GattService1", {"UUID": SERVICE, "Primary": True}, None),
        hid + "/info": ("org.bluez.GattCharacteristic1",
                        {"UUID": _uuid16(0x2A4A), "Service": hid, "Flags": ["read"]},
                        bytes([0x11, 0x01, 0x00, 0x02])),  # HID 1.11, country 0, normally connectable
        hid + "/map": ("org.bluez.GattCharacteristic1",
                       {"UUID": _uuid16(0x2A4B), "Service": hid, "Flags": ["read", "encrypt-read"]},
                       REPORT_MAP),
        hid + "/control": ("org.bluez.GattCharacteristic1",
                           {"UUID": _uuid16(0x2A4C), "Service": hid,
                            "Flags": ["write-without-response"]}, bytes([0])),
        hid + "/protocol": ("org.bluez.GattCharacteristic1",
                            {"UUID": _uuid16(0x2A4E), "Service": hid,
                             "Flags": ["read", "write-without-response"]}, bytes([1])),
        hid + "/keyboard": ("org.bluez.GattCharacteristic1",
                            {"UUID": _uuid16(0x2A4D), "Service": hid,
                             "Flags": ["read", "notify", "encrypt-read"]}, keyboard_report()),
        hid + "/keyboard/ref": ("org.bluez.GattDescriptor1",
                                {"UUID": _uuid16(0x2908), "Characteristic": hid + "/keyboard",
                                 "Flags": ["read"]}, bytes([KEYBOARD_ID, 1])),
        hid + "/mouse": ("org.bluez.GattCharacteristic1",
                         {"UUID": _uuid16(0x2A4D), "Service": hid,
                          "Flags": ["read", "notify", "encrypt-read"]}, mouse_report()),
        hid + "/mouse/ref": ("org.bluez.GattDescriptor1",
                             {"UUID": _uuid16(0x2908), "Characteristic": hid + "/mouse",
                              "Flags": ["read"]}, bytes([MOUSE_ID, 1])),
        # Device Information › PnP ID: USB vendor source, generic ids.
        info: ("org.bluez.GattService1", {"UUID": _uuid16(0x180A), "Primary": True}, None),
        info + "/pnp": ("org.bluez.GattCharacteristic1",
                        {"UUID": _uuid16(0x2A50), "Service": info, "Flags": ["read"]},
                        bytes([0x02, 0x6B, 0x1D, 0x46, 0x02, 0x37, 0x05])),
    }
    return objects


def _props_variant(iface, props, value):
    out = {}
    for key, val in props.items():
        if key in ("Service", "Characteristic"):
            out[key] = GLib.Variant("o", val)
        elif key == "Flags":
            out[key] = GLib.Variant("as", val)
        elif key == "Primary":
            out[key] = GLib.Variant("b", val)
        else:
            out[key] = GLib.Variant("s", val)
    if iface == "org.bluez.GattCharacteristic1":
        out["Value"] = GLib.Variant("ay", value or b"")
    return out


class Control:
    """The HID accessory: GATT server, its advertisement and the report queue."""

    def __init__(self, bus, config, adapter, changed):
        self.bus = bus
        self.config = config
        self.adapter = adapter  # callable: current adapter path or None
        self.changed = changed
        self.objects = gatt_objects()
        self.values = {path: obj[2] for path, obj in self.objects.items()}
        self.registrations = []
        self.registered = False
        self.advertising = False
        self.notifying = set()
        self.queue = []
        self.bluez_name = ""  # bluetoothd's unique name, from its StartNotify
        self.timer = 0
        self.keys = []  # HID usages held down, in order
        self.modifiers = 0
        self.buttons = 0
        self.error = ""

    # --- state ----------------------------------------------------------------------------

    def enabled(self):
        return self.config.alpha("iphone_control")

    def state(self):
        return {"enabled": self.enabled(), "registered": self.registered,
                "connected": bool(self.notifying), "error": self.error,
                "width": self.size()[0], "height": self.size()[1]}

    def size(self):
        """Pointer travel of the whole iPhone screen, in mouse units (tuned by the user)."""
        try:
            width = self.config.keyfile.get_integer("control", "width")
            height = self.config.keyfile.get_integer("control", "height")
        except GLib.Error:
            width, height = 400, 870
        return max(50, width), max(50, height)

    def set_size(self, width, height):
        self.config.keyfile.set_integer("control", "width", int(width))
        self.config.keyfile.set_integer("control", "height", int(height))
        self.config.save()
        self.changed()

    # --- publication --------------------------------------------------------------------------

    def refresh(self, force=False):
        """Publish or withdraw the accessory to match the switch. After a refusal by BlueZ,
        only a new use of the switch tries again."""
        adapter = self.adapter()
        wanted = self.enabled() and adapter is not None
        if force:
            self.error = ""
        if wanted and not self.error and not (self.registered and self.advertising):
            self._start(adapter)
        elif not wanted and (self.registered or self.advertising or self.registrations):
            self._stop(adapter)

    def withdraw(self):
        self._stop(self.adapter())

    def _export(self):
        if self.registrations:
            return
        node = Gio.DBusNodeInfo.new_for_xml(GATT_XML)
        ifaces = {i.name: i for i in node.interfaces}
        self.registrations.append(self.bus.register_object(
            APP_PATH, ifaces["org.freedesktop.DBus.ObjectManager"], self._manager_method, None, None))
        for path, (iface, _props, _value) in self.objects.items():
            self.registrations.append(self.bus.register_object(
                path, ifaces[iface], self._object_method, self._object_property, None))
        self.registrations.append(self.bus.register_object(
            ADV_PATH, ifaces["org.bluez.LEAdvertisement1"], self._adv_method, self._adv_property,
            None))

    def _start(self, adapter):
        self._export()
        if not self.registered:
            call_async(self.bus, BLUEZ, adapter, "org.bluez.GattManager1", "RegisterApplication",
                       GLib.Variant("(oa{sv})", (APP_PATH, {})), on_done=self._on_registered)
            self.registered = True
        if not self.advertising:
            call_async(self.bus, BLUEZ, adapter, "org.bluez.LEAdvertisingManager1",
                       "RegisterAdvertisement", GLib.Variant("(oa{sv})", (ADV_PATH, {})),
                       on_done=self._on_advertising)
            self.advertising = True

    def _stop(self, adapter):
        if adapter and self.registered:
            call_async(self.bus, BLUEZ, adapter, "org.bluez.GattManager1", "UnregisterApplication",
                       GLib.Variant("(o)", (APP_PATH,)))
        if adapter and self.advertising:
            call_async(self.bus, BLUEZ, adapter, "org.bluez.LEAdvertisingManager1",
                       "UnregisterAdvertisement", GLib.Variant("(o)", (ADV_PATH,)))
        was = self.registered
        self.registered = self.advertising = False
        self.notifying.clear()
        self.queue.clear()
        for registration in self.registrations:
            self.bus.unregister_object(registration)
        self.registrations = []
        if was:
            log("contrôle : clavier et souris retirés")
            self.changed()

    def _on_registered(self, _value, error):
        if error:
            self.registered = False
            self.error = error.message
            log(f"contrôle : service HID refusé ({error.message})")
        else:
            self.error = ""
            log("contrôle : clavier et souris Bluetooth publiés")
        self.changed()

    def _on_advertising(self, _value, error):
        if error:
            self.advertising = False
            self.error = error.message
            log(f"contrôle : annonce refusée ({error.message})")
        self.changed()

    # --- D-Bus objects --------------------------------------------------------------------------

    def _from_bluez(self, sender):
        """Our GATT objects live on the system bus, where every local user can call them:
        only bluetoothd may read the reports (the keys typed on the iPhone) or subscribe."""
        try:
            owner = call_sync(self.bus, "org.freedesktop.DBus", "/org/freedesktop/DBus",
                              "org.freedesktop.DBus", "GetNameOwner", GLib.Variant("(s)", (BLUEZ,)),
                              "(s)").unpack()[0]
        except GLib.Error:
            return False
        return sender == owner

    def _manager_method(self, _conn, _sender, _path, _iface, method, _params, invocation):
        objects = {path: {iface: _props_variant(iface, props, self.values[path])}
                   for path, (iface, props, _value) in self.objects.items()}
        invocation.return_value(GLib.Variant("(a{oa{sa{sv}}})", (objects,)))

    def _object_property(self, _conn, _sender, path, iface, name):
        return _props_variant(iface, self.objects[path][1], self.values[path]).get(name)

    def _object_method(self, _conn, sender, path, _iface, method, params, invocation):
        if not self._from_bluez(sender):
            invocation.return_dbus_error("org.bluez.Error.NotPermitted", "bluetoothd only")
            return
        if method == "StartNotify":
            self.bluez_name = sender
        if method == "ReadValue":
            offset = params.unpack()[0].get("offset", 0)
            invocation.return_value(GLib.Variant("(ay)", (self.values[path][offset:],)))
            return
        if method == "WriteValue":
            value = bytes(params.unpack()[0])
            if path.endswith("/protocol") and value:
                self.values[path] = value[:1]
            invocation.return_value(None)
            return
        if method == "StartNotify":
            if not self.notifying:
                log("contrôle : l'iPhone utilise le clavier et la souris")
            self.notifying.add(path)
            self.changed()
        elif method == "StopNotify":
            self.notifying.discard(path)
            self.changed()
        invocation.return_value(None)

    def _adv_method(self, _conn, _sender, _path, _iface, method, _params, invocation):
        if method == "Release":
            self.advertising = False
        invocation.return_value(None)

    def _adv_property(self, _conn, _sender, _path, _iface, name):
        return {
            "Type": GLib.Variant("s", "peripheral"),
            "LocalName": GLib.Variant("s", "Covalence"),
            "ServiceUUIDs": GLib.Variant("as", ["1812"]),
            "Appearance": GLib.Variant("q", APPEARANCE_HID),
            "Discoverable": GLib.Variant("b", True),
        }.get(name)

    # --- reports ----------------------------------------------------------------------------------

    def _queue(self, which, report):
        if not self.registered:
            return False
        self.queue.append((APP_PATH + "/service0/" + which, report))
        if not self.timer:
            self.timer = GLib.timeout_add(SEND_INTERVAL_MS, self._pump)
        return True

    def _pump(self):
        if not self.queue:
            self.timer = 0
            return GLib.SOURCE_REMOVE
        path, report = self.queue.pop(0)
        self.values[path] = report
        if path in self.notifying and self.bluez_name:
            # Addressed to bluetoothd alone: a broadcast would let any local user read the keys.
            self.bus.emit_signal(self.bluez_name, path, "org.freedesktop.DBus.Properties",
                                 "PropertiesChanged",
                                 GLib.Variant("(sa{sv}as)", ("org.bluez.GattCharacteristic1",
                                                             {"Value": GLib.Variant("ay", report)},
                                                             [])))
        return GLib.SOURCE_CONTINUE

    def key(self, evdev_code, pressed):
        """A key of the PC's keyboard, pressed or released, sent by position."""
        if evdev_code in EVDEV_MODIFIERS:
            bit = EVDEV_MODIFIERS[evdev_code]
            self.modifiers = self.modifiers | bit if pressed else self.modifiers & ~bit
        else:
            usage = EVDEV_TO_HID.get(evdev_code)
            if usage is None:
                return False
            if pressed and usage not in self.keys:
                self.keys.append(usage)
            elif not pressed and usage in self.keys:
                self.keys.remove(usage)
        return self._queue("keyboard", keyboard_report(self.modifiers, self.keys[-6:]))

    def release_all(self):
        self.keys, self.modifiers, self.buttons = [], 0, 0
        self._queue("keyboard", keyboard_report())
        return self._queue("mouse", mouse_report())

    def text(self, text):
        reports, skipped = text_reports(text)
        for report in reports:
            if not self._queue("keyboard", report):
                return -1
        return skipped

    def shortcut(self, usage, modifiers):
        self._queue("keyboard", keyboard_report(modifiers, [usage]))
        return self._queue("keyboard", keyboard_report())

    def move(self, dx, dy):
        for sx, sy in split_move(dx, dy):
            if not self._queue("mouse", mouse_report(self.buttons, sx, sy)):
                return False
        return True

    def button(self, mask, pressed):
        self.buttons = self.buttons | mask if pressed else self.buttons & ~mask
        return self._queue("mouse", mouse_report(self.buttons))

    def click(self, mask):
        self.button(mask, True)
        return self.button(mask, False)

    def scroll(self, steps):
        for _ in range(min(abs(int(steps)), 20)):
            self._queue("mouse", mouse_report(self.buttons, 0, 0, 1 if steps > 0 else -1))
        return self.registered

    def goto(self, fx, fy):
        width, height = self.size()
        for sx, sy in goto_moves(fx, fy, width, height):
            if not self._queue("mouse", mouse_report(self.buttons, sx, sy)):
                return False
        return True
