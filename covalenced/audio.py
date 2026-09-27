# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Sound of the iPhone on the PC (A2DP: the iPhone is the source, the PC the sink).

PipeWire plays the iPhone's stream (bluez_input.<address>) on the default
output. Covalence adds two settings:

- receive: when off, the A2DP link is dropped whenever the iPhone opens it,
  so video or music stays on the iPhone. HFP (calls) is left alone.
- output: a PipeWire sink name, or "" for the default output. It is applied
  through the "default" metadata (target.object) each time the stream appears,
  since the node is created again on every connection.

The iPhone can also pick its output itself (AirPlay button in Control Center).
"""

import json
import subprocess

from gi.repository import Gio, GLib

from .util import BLUEZ, call_async, log

TRANSPORT = "org.bluez.MediaTransport1"
A2DP_SINK = "0000110b-0000-1000-8000-00805f9b34fb"    # our endpoint: we receive
A2DP_SOURCE = "0000110a-0000-1000-8000-00805f9b34fb"  # the iPhone's role
ROUTE_ATTEMPTS = 10  # the PipeWire node shows up a moment after the transport


def pw_nodes():
    try:
        out = subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=5).stdout
        objects = json.loads(out or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    return [o for o in objects if o.get("type") == "PipeWire:Interface:Node"]


def default_sink_name():
    try:
        out = subprocess.run(["pw-metadata", "-n", "default", "0", "default.audio.sink"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""
    # update: id:0 key:'default.audio.sink' value:'{"name":"..."}' type:'Spa:String:JSON'
    start = out.find("value:'")
    if start < 0:
        return ""
    try:
        return json.loads(out[start + 7:out.index("'", start + 7)]).get("name", "")
    except ValueError:
        return ""


class PhoneAudio:
    def __init__(self, system, config, on_change):
        self.bus = system
        self.config = config
        self.on_change = on_change
        self.transports = {}  # path -> MediaTransport1 properties (our A2DP sink only)
        self.device = None    # BlueZ path of the iPhone
        self.routed = None    # node id the output was applied to
        self.route_timer = 0
        for member, handler in (("InterfacesAdded", self._on_added),
                                ("InterfacesRemoved", self._on_removed)):
            system.signal_subscribe(BLUEZ, "org.freedesktop.DBus.ObjectManager", member,
                                    None, None, Gio.DBusSignalFlags.NONE, handler)
        system.signal_subscribe(BLUEZ, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                None, TRANSPORT, Gio.DBusSignalFlags.NONE, self._on_changed)
        call_async(system, BLUEZ, "/", "org.freedesktop.DBus.ObjectManager",
                   "GetManagedObjects", None, self._on_objects)

    # --- settings ----------------------------------------------------------------------

    @property
    def receive(self):
        return self.config.boolean("audio", "receive", True)

    @property
    def output(self):
        try:
            return self.config.keyfile.get_string("audio", "output")
        except GLib.Error:
            return ""

    def set_receive(self, receive):
        self.config.keyfile.set_boolean("audio", "receive", receive)
        self.config.save()
        log(f"son de l'iPhone sur le PC {'autorisé' if receive else 'refusé'}")
        if self.device:
            method = "ConnectProfile" if receive else "DisconnectProfile"
            call_async(self.bus, BLUEZ, self.device, "org.bluez.Device1", method,
                       GLib.Variant("(s)", (A2DP_SOURCE,)), what=f"son de l'iPhone ({method})")
        self.on_change()

    def set_output(self, name):
        self.config.keyfile.set_string("audio", "output", name)
        self.config.save()
        self.routed = None
        self._route()
        self.on_change()

    def outputs(self):
        """Sinks of the PC (not Bluetooth ones), the default first."""
        default = default_sink_name()
        sinks = []
        for node in pw_nodes():
            props = node.get("info", {}).get("props", {})
            if props.get("media.class") != "Audio/Sink" or props.get("device.api") == "bluez5":
                continue
            name = props.get("node.name", "")
            sinks.append({"name": name,
                          "description": props.get("node.description") or name,
                          "default": name == default})
        sinks.sort(key=lambda s: (not s["default"], s["description"]))
        return sinks

    def state(self):
        """off (refused), idle (allowed, nothing playing) or playing."""
        if not self.receive:
            return "off"
        return "playing" if any(p.get("State") == "active" for p in self._mine()) else "idle"

    # --- device ------------------------------------------------------------------------

    def set_device(self, path):
        self.device = path
        self._enforce()
        self.on_change()

    def _mine(self):
        return [p for p in self.transports.values() if p.get("Device") == self.device]

    def _enforce(self):
        """Receiving refused: drop the A2DP link as soon as the iPhone opens it."""
        if not self.receive and self.device and self._mine():
            log("son de l'iPhone refusé : liaison A2DP fermée")
            call_async(self.bus, BLUEZ, self.device, "org.bluez.Device1", "DisconnectProfile",
                       GLib.Variant("(s)", (A2DP_SOURCE,)), what="son de l'iPhone")

    # --- BlueZ signals -----------------------------------------------------------------

    def _on_objects(self, value, error):
        if error:
            return
        for path, interfaces in value.unpack()[0].items():
            self._add(path, interfaces)

    def _on_added(self, _conn, _sender, _path, _iface, _signal, params):
        path, interfaces = params.unpack()
        self._add(path, interfaces)

    def _add(self, path, interfaces):
        props = interfaces.get(TRANSPORT)
        if props is None or props.get("UUID") != A2DP_SINK:
            return
        self.transports[path] = props
        if props.get("Device") == self.device:
            self._enforce()
            self._schedule_route()
        self.on_change()

    def _on_removed(self, _conn, _sender, path, _iface, _signal, params):
        _path, interfaces = params.unpack()
        if TRANSPORT in interfaces and self.transports.pop(path, None) is not None:
            self.routed = None
            self.on_change()

    def _on_changed(self, _conn, _sender, path, _iface, _signal, params):
        if path not in self.transports:
            return
        _iface_name, changed, _invalid = params.unpack()
        self.transports[path].update(changed)
        if "State" in changed:
            if changed["State"] in ("pending", "active"):
                self._schedule_route()
            self.on_change()

    # --- routing -----------------------------------------------------------------------

    def _schedule_route(self):
        if self.route_timer:
            return
        attempts = [ROUTE_ATTEMPTS]

        def tick():
            attempts[0] -= 1
            if self._route() or attempts[0] <= 0:
                self.route_timer = 0
                return False
            return True

        self.route_timer = GLib.timeout_add(500, tick)

    def _stream_node(self):
        if not self.device:
            return None
        address = self.device.rsplit("dev_", 1)[-1]  # AA_BB_CC_...
        for node in pw_nodes():
            name = node.get("info", {}).get("props", {}).get("node.name", "")
            if name.startswith("bluez_input." + address):
                return node["id"]
        return None

    def _route(self):
        """Point the iPhone stream at the chosen output. True once the node was found."""
        node = self._stream_node()
        if node is None:
            return False
        if node == self.routed:
            return True
        output = self.output
        if output and output not in (s["name"] for s in self.outputs()):
            output = ""  # unplugged device: fall back to the default output
        if output:
            args = ["pw-metadata", "-n", "default", str(node), "target.object", output]
        else:
            args = ["pw-metadata", "-n", "default", "-d", str(node), "target.object"]
        try:
            subprocess.run(args, capture_output=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            log(f"son de l'iPhone : sortie non appliquée ({error})")
            return True
        self.routed = node
        return True
