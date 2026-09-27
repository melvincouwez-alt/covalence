# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""MPRIS player backed by the iPhone's Apple Media Service.

The player appears in the sound indicator like any desktop player. It is only
published while AMS is linked and no AVRCP player (BlueZ + mpris-proxy) already
represents the same iPhone, to avoid two identical entries.
"""

from gi.repository import Gio, GLib

from . import ams
from .util import APP_ID, log

BUS_NAME = "org.mpris.MediaPlayer2.Covalence"
PATH = "/org/mpris/MediaPlayer2"
ROOT = "org.mpris.MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"

XML = """
<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/>
    <method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="DesktopEntry" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/>
    <method name="Previous"/>
    <method name="Pause"/>
    <method name="PlayPause"/>
    <method name="Stop"/>
    <method name="Play"/>
    <method name="Seek"><arg type="x" direction="in"/></method>
    <method name="SetPosition"><arg type="o" direction="in"/><arg type="x" direction="in"/></method>
    <method name="OpenUri"><arg type="s" direction="in"/></method>
    <signal name="Seeked"><arg type="x"/></signal>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="LoopStatus" type="s" access="readwrite"/>
    <property name="Rate" type="d" access="readwrite"/>
    <property name="Shuffle" type="b" access="readwrite"/>
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="Volume" type="d" access="readwrite"/>
    <property name="Position" type="x" access="read"/>
    <property name="MinimumRate" type="d" access="read"/>
    <property name="MaximumRate" type="d" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
  </interface>
</node>
"""

# Which MPRIS properties to refresh for each kind of AMS change.
CHANGES = {
    "identity": [],
    "playback": ["PlaybackStatus", "Rate"],
    "volume": ["Volume"],
    "shuffle": ["Shuffle"],
    "repeat": ["LoopStatus"],
    "metadata": ["Metadata"],
    "commands": ["CanGoNext", "CanGoPrevious", "CanPlay", "CanPause"],
}


class MprisPlayer:
    def __init__(self, bus, device_name):
        self.bus = bus
        self.device_name = device_name
        self.client = None
        self.registrations = []
        self.owner_id = 0

    @property
    def published(self):
        return bool(self.registrations)

    def publish(self, client):
        self.client = client
        if self.published:
            return
        node = Gio.DBusNodeInfo.new_for_xml(XML)
        for info in node.interfaces:
            self.registrations.append(self.bus.register_object(
                PATH, info, self._method, self._get, self._set))
        self.owner_id = Gio.bus_own_name_on_connection(
            self.bus, BUS_NAME, Gio.BusNameOwnerFlags.NONE, None, None)
        log("MPRIS : lecteur de l'iPhone publié")

    def withdraw(self):
        if not self.published:
            return
        Gio.bus_unown_name(self.owner_id)
        for reg in self.registrations:
            self.bus.unregister_object(reg)
        self.registrations, self.owner_id = [], 0
        log("MPRIS : lecteur de l'iPhone retiré")

    def on_change(self, changed):
        if not self.published:
            return
        names = sorted({n for key in changed for n in CHANGES.get(key, [])})
        if not names:
            return
        values = {n: self._value(n) for n in names}
        self.bus.emit_signal(None, PATH, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                             GLib.Variant("(sa{sv}as)", (PLAYER, values, [])))
        if "playback" in changed:
            self.bus.emit_signal(None, PATH, PLAYER, "Seeked",
                                 GLib.Variant("(x)", (int(self.client.position() * 1e6),)))

    # --- D-Bus handlers ---------------------------------------------------------

    def _method(self, _conn, _sender, _path, interface, method, params, invocation):
        c = self.client
        if interface == PLAYER and c:
            status = c.state["status"]
            if method == "Next":
                c.command(ams.CMD_NEXT)
            elif method == "Previous":
                c.command(ams.CMD_PREVIOUS)
            elif method in ("Pause", "Stop"):
                c.command(ams.CMD_PAUSE)
            elif method == "Play":
                c.command(ams.CMD_PLAY)
            elif method == "PlayPause":
                if not c.command(ams.CMD_TOGGLE):
                    c.command(ams.CMD_PAUSE if status == "Playing" else ams.CMD_PLAY)
            elif method == "Seek":
                offset = params.unpack()[0]
                c.command(ams.CMD_SKIP_FORWARD if offset > 0 else ams.CMD_SKIP_BACKWARD)
        invocation.return_value(None)

    def _get(self, _conn, _sender, _path, interface, name):
        return self._value(name)

    def _value(self, name):
        s = self.client.state if self.client else {}
        supported = self.client.supported if self.client else set()

        def can(command):
            return bool(self.client) and (not supported or command in supported)

        values = {
            "CanQuit": ("b", False), "CanRaise": ("b", False), "HasTrackList": ("b", False),
            "Identity": ("s", f"{self.device_name}" + (f" · {s['player']}" if s.get("player") else "")),
            "DesktopEntry": ("s", APP_ID),
            "SupportedUriSchemes": ("as", []), "SupportedMimeTypes": ("as", []),
            "PlaybackStatus": ("s", s.get("status", "Stopped")),
            "LoopStatus": ("s", s.get("repeat", "None")),
            "Rate": ("d", 1.0), "MinimumRate": ("d", 1.0), "MaximumRate": ("d", 1.0),
            "Shuffle": ("b", s.get("shuffle", False)),
            "Metadata": ("a{sv}", self._metadata()),
            "Volume": ("d", s.get("volume", 0.0)),
            "Position": ("x", int(self.client.position() * 1e6) if self.client else 0),
            "CanGoNext": ("b", can(ams.CMD_NEXT)),
            "CanGoPrevious": ("b", can(ams.CMD_PREVIOUS)),
            "CanPlay": ("b", can(ams.CMD_PLAY) or can(ams.CMD_TOGGLE)),
            "CanPause": ("b", can(ams.CMD_PAUSE) or can(ams.CMD_TOGGLE)),
            "CanSeek": ("b", False),
            "CanControl": ("b", True),
        }
        signature, value = values[name]
        return GLib.Variant(signature, value)

    def _metadata(self):
        s = self.client.state if self.client else None
        if not s or not s["title"]:
            return {"mpris:trackid": GLib.Variant("o", "/org/mpris/MediaPlayer2/TrackList/NoTrack")}
        meta = {
            "mpris:trackid": GLib.Variant("o", f"/io/github/melvincouwez/Covalence/track/{s['track_serial']}"),
            "xesam:title": GLib.Variant("s", s["title"]),
        }
        if s["artist"]:
            meta["xesam:artist"] = GLib.Variant("as", [s["artist"]])
        if s["album"]:
            meta["xesam:album"] = GLib.Variant("s", s["album"])
        if s["duration"] > 0:
            meta["mpris:length"] = GLib.Variant("x", int(s["duration"] * 1e6))
        return meta

    def _set(self, _conn, _sender, _path, _interface, name, value):
        c = self.client
        if not c:
            return False
        if name == "Volume":
            # AMS only has relative volume steps.
            target = value.unpack()
            c.command(ams.CMD_VOLUME_UP if target > c.state["volume"] else ams.CMD_VOLUME_DOWN)
        elif name == "Shuffle":
            if value.unpack() != c.state["shuffle"]:
                c.command(ams.CMD_ADVANCE_SHUFFLE)
        elif name == "LoopStatus":
            if value.unpack() != c.state["repeat"]:
                c.command(ams.CMD_ADVANCE_REPEAT)
        return True
