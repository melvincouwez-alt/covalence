# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Session bus API of the daemon: io.github.melvincouwez.Covalence1.

The app only talks to the daemon through this interface. The bus name is
io.github.melvincouwez.Covalence.Daemon: the app itself (GtkApplication) owns
io.github.melvincouwez.Covalence.
"""

import os

from gi.repository import Gio, GLib

from .callers import Callers
from .config import ALPHA, MODULES
from .i18n import _
from .util import log

BUS_NAME = "io.github.melvincouwez.Covalence.Daemon"
PATH = "/io/github/melvincouwez/Covalence/Daemon"
INTERFACE = "io.github.melvincouwez.Covalence1"

XML = f"""
<node>
  <interface name="{INTERFACE}">
    <method name="SetModuleEnabled">
      <arg name="module" type="s" direction="in"/>
      <arg name="enabled" type="b" direction="in"/>
    </method>
    <method name="StartPairing"/>
    <method name="ConfirmPairing">
      <arg name="matches" type="b" direction="in"/>
    </method>
    <method name="StopPairing"/>
    <method name="Reconnect"/>
    <method name="Forget"/>
    <method name="ICloudUpdated"/>
    <method name="ListThreads">
      <arg name="threads" type="aa{{sv}}" direction="out"/>
    </method>
    <method name="GetMessages">
      <arg name="thread" type="s" direction="in"/>
      <arg name="messages" type="aa{{sv}}" direction="out"/>
    </method>
    <method name="SendMessage">
      <arg name="thread" type="s" direction="in"/>
      <arg name="text" type="s" direction="in"/>
    </method>
    <method name="MarkThreadSeen">
      <arg name="thread" type="s" direction="in"/>
    </method>
    <method name="SyncMessages"/>
    <method name="Sync">
      <arg name="new_messages" type="u" direction="out"/>
    </method>
    <method name="ReadFullText">
      <arg name="message" type="s" direction="in"/>
    </method>
    <method name="SetSound">
      <arg name="kind" type="s" direction="in"/>
      <arg name="value" type="s" direction="in"/>
    </method>
    <method name="ListSounds">
      <arg name="sounds" type="a(ss)" direction="out"/>
    </method>
    <method name="PlaySound">
      <arg name="kind" type="s" direction="in"/>
      <arg name="value" type="s" direction="in"/>
    </method>
    <method name="StopSound"/>
    <method name="SetTethering">
      <arg name="enabled" type="b" direction="in"/>
    </method>
    <method name="SetProximity">
      <arg name="enabled" type="b" direction="in"/>
      <arg name="distance" type="s" direction="in"/>
      <arg name="delay" type="u" direction="in"/>
    </method>
    <method name="SetCallsQuiet">
      <arg name="enabled" type="b" direction="in"/>
    </method>
    <method name="SetFetchUnread">
      <arg name="enabled" type="b" direction="in"/>
    </method>
    <method name="SetAlphaFeature">
      <arg name="feature" type="s" direction="in"/>
      <arg name="enabled" type="b" direction="in"/>
    </method>
    <method name="NotificationAction">
      <arg name="uid" type="u" direction="in"/>
      <arg name="action" type="s" direction="in"/>
    </method>
    <property name="AlphaFeatures" type="a{{sb}}" access="read"/>
    <property name="FetchUnread" type="b" access="read"/>
    <property name="CallsQuiet" type="b" access="read"/>
    <property name="Sounds" type="a{{ss}}" access="read"/>
    <method name="SetDraft">
      <arg name="thread" type="s" direction="in"/>
      <arg name="text" type="s" direction="in"/>
    </method>
    <method name="SearchThreads">
      <arg name="query" type="s" direction="in"/>
      <arg name="threads" type="as" direction="out"/>
    </method>
    <method name="SearchMessages">
      <arg name="query" type="s" direction="in"/>
      <arg name="results" type="aa{{sv}}" direction="out"/>
    </method>
    <method name="PinThread">
      <arg name="thread" type="s" direction="in"/>
      <arg name="pinned" type="b" direction="in"/>
    </method>
    <method name="MarkThreadUnread">
      <arg name="thread" type="s" direction="in"/>
      <arg name="unread" type="b" direction="in"/>
    </method>
    <method name="SetViewing">
      <arg name="thread" type="s" direction="in"/>
    </method>
    <method name="ListActiveCalls">
      <arg name="calls" type="aa{{sv}}" direction="out"/>
    </method>
    <method name="CallAction">
      <arg name="call" type="o" direction="in"/>
      <arg name="action" type="s" direction="in"/>
    </method>
    <method name="SetCallAudio">
      <arg name="on_pc" type="b" direction="in"/>
    </method>
    <method name="SimulateCall">
      <arg name="kind" type="s" direction="in"/>
    </method>
    <method name="SetMuted">
      <arg name="muted" type="b" direction="in"/>
    </method>
    <method name="SendTones">
      <arg name="tones" type="s" direction="in"/>
    </method>
    <signal name="ActiveCallsChanged"/>
    <property name="AudioOnPC" type="b" access="read"/>
    <property name="MicMuted" type="b" access="read"/>
    <method name="ListNotifications">
      <arg name="notifications" type="aa{{sv}}" direction="out"/>
    </method>
    <method name="ListNotificationApps">
      <arg name="apps" type="aa{{sv}}" direction="out"/>
    </method>
    <method name="SetNotificationApp">
      <arg name="app" type="s" direction="in"/>
      <arg name="enabled" type="b" direction="in"/>
    </method>
    <method name="ClearNotifications"/>
    <method name="MarkCallsSeen"/>
    <signal name="NotificationsChanged"/>
    <method name="ListCalls">
      <arg name="calls" type="aa{{sv}}" direction="out"/>
    </method>
    <method name="Dial">
      <arg name="number" type="s" direction="in"/>
    </method>
    <signal name="CallsChanged"/>
    <method name="RetryMessage">
      <arg name="message" type="s" direction="in"/>
    </method>
    <method name="DiscardMessage">
      <arg name="message" type="s" direction="in"/>
    </method>
    <method name="SendReaction">
      <arg name="message" type="s" direction="in"/>
      <arg name="emoji" type="s" direction="in"/>
    </method>
    <method name="LatestCode">
      <arg name="purpose" type="s" direction="in"/>
      <arg name="code" type="s" direction="out"/>
      <arg name="age" type="u" direction="out"/>
    </method>
    <method name="LatestCodeFor">
      <arg name="purpose" type="s" direction="in"/>
      <arg name="code" type="s" direction="out"/>
      <arg name="age" type="u" direction="out"/>
      <arg name="domains" type="as" direction="out"/>
      <arg name="sender" type="s" direction="out"/>
    </method>
    <method name="SetOneTimeCodes">
      <arg name="mode" type="s" direction="in"/>
    </method>
    <method name="SetAutoCopyCodes">
      <arg name="enabled" type="b" direction="in"/>
    </method>
    <method name="CheckUpdates">
      <arg name="latest" type="s" direction="out"/>
    </method>
    <method name="InstallUpdate"/>
    <method name="SetUpdateChecks">
      <arg name="enabled" type="b" direction="in"/>
    </method>
    <method name="RestartDaemon"/>
    <method name="CheckApps"/>
    <method name="InstallApp">
      <arg name="package" type="s" direction="in"/>
    </method>
    <property name="Update" type="a{{sv}}" access="read"/>
    <property name="Apps" type="a{{sv}}" access="read"/>
    <property name="Tethering" type="b" access="read"/>
    <property name="TetheringState" type="s" access="read"/>
    <property name="TetheringError" type="s" access="read"/>
    <property name="Proximity" type="a{{sv}}" access="read"/>
    <method name="SetLocalSend">
      <arg name="enabled" type="b" direction="in"/>
    </method>
    <method name="ListFilePeers">
      <arg name="peers" type="aa{{sv}}" direction="out"/>
    </method>
    <method name="RefreshFilePeers"/>
    <method name="SendFiles">
      <arg name="peer" type="s" direction="in"/>
      <arg name="paths" type="as" direction="in"/>
    </method>
    <method name="CancelFiles"/>
    <property name="Files" type="a{{sv}}" access="read"/>
    <method name="StartMirror"/>
    <method name="StopMirror"/>
    <property name="Mirror" type="a{{sv}}" access="read"/>
    <method name="SetMirrorOption">
      <arg name="key" type="s" direction="in"/>
      <arg name="value" type="s" direction="in"/>
    </method>
    <property name="Control" type="a{{sv}}" access="read"/>
    <method name="ControlKey">
      <arg name="evdev_code" type="u" direction="in"/>
      <arg name="pressed" type="b" direction="in"/>
    </method>
    <method name="ControlShortcut">
      <arg name="usage" type="u" direction="in"/>
      <arg name="modifiers" type="u" direction="in"/>
    </method>
    <method name="ControlText">
      <arg name="text" type="s" direction="in"/>
      <arg name="skipped" type="i" direction="out"/>
    </method>
    <method name="ControlMove">
      <arg name="dx" type="i" direction="in"/>
      <arg name="dy" type="i" direction="in"/>
    </method>
    <method name="ControlButton">
      <arg name="button" type="u" direction="in"/>
      <arg name="pressed" type="b" direction="in"/>
    </method>
    <method name="ControlClick">
      <arg name="button" type="u" direction="in"/>
    </method>
    <method name="ControlScroll">
      <arg name="steps" type="i" direction="in"/>
    </method>
    <method name="ControlGoto">
      <arg name="x" type="d" direction="in"/>
      <arg name="y" type="d" direction="in"/>
    </method>
    <method name="ControlRelease"/>
    <method name="SetControlSize">
      <arg name="width" type="u" direction="in"/>
      <arg name="height" type="u" direction="in"/>
    </method>
    <method name="RefreshPhotosUsb"/>
    <method name="PairPhotosUsb"/>
    <method name="ImportPhotosUsb"/>
    <method name="CancelPhotosUsb"/>
    <method name="SetConvertHeic">
      <arg name="enabled" type="b" direction="in"/>
    </method>
    <property name="PhotosUsb" type="a{{sv}}" access="read"/>
    <method name="InstallBrowserHost">
      <arg name="browsers" type="as" direction="out"/>
    </method>
    <property name="OneTimeCodes" type="s" access="read"/>
    <property name="AutoCopyCodes" type="b" access="read"/>
    <method name="DeleteMessage">
      <arg name="message" type="s" direction="in"/>
    </method>
    <method name="DeleteConversation">
      <arg name="thread" type="s" direction="in"/>
    </method>
    <signal name="SendProgress">
      <arg name="thread" type="s"/>
      <arg name="message" type="s"/>
      <arg name="fraction" type="d"/>
    </signal>
    <method name="ListContacts">
      <arg name="contacts" type="aa{{sv}}" direction="out"/>
    </method>
    <method name="OpenConversation">
      <arg name="address" type="s" direction="in"/>
      <arg name="thread" type="a{{sv}}" direction="out"/>
    </method>
    <method name="ListHeadphones">
      <arg name="headphones" type="aa{{sv}}" direction="out"/>
    </method>
    <method name="SetHeadphones">
      <arg name="address" type="s" direction="in"/>
      <arg name="key" type="s" direction="in"/>
      <arg name="value" type="v" direction="in"/>
    </method>
    <signal name="HeadphonesChanged"/>
    <method name="SetContactsSource">
      <arg name="source" type="s" direction="in"/>
    </method>
    <method name="GetContact">
      <arg name="uid" type="s" direction="in"/>
      <arg name="card" type="a{{sv}}" direction="out"/>
    </method>
    <method name="SaveContact">
      <arg name="card" type="a{{sv}}" direction="in"/>
      <arg name="uid" type="s" direction="out"/>
    </method>
    <method name="DeleteContact">
      <arg name="uid" type="s" direction="in"/>
    </method>
    <signal name="ContactsChanged"/>
    <property name="ContactsSource" type="s" access="read"/>
    <property name="UnreadMessages" type="u" access="read"/>
    <property name="MissedCalls" type="u" access="read"/>
    <property name="ContactsBook" type="s" access="read"/>
    <method name="SetPhoneAudio">
      <arg name="receive" type="b" direction="in"/>
    </method>
    <method name="SetPhoneAudioOutput">
      <arg name="output" type="s" direction="in"/>
    </method>
    <method name="ListAudioOutputs">
      <arg name="outputs" type="aa{{sv}}" direction="out"/>
    </method>
    <property name="PhoneAudio" type="s" access="read"/>
    <property name="PhoneAudioOutput" type="s" access="read"/>
    <signal name="PairingCode"><arg name="passkey" type="u"/></signal>
    <signal name="PairingCodeAnswered"><arg name="matches" type="b"/></signal>
    <signal name="ThreadsChanged"/>
    <signal name="MessageReceived">
      <arg name="thread" type="s"/>
      <arg name="message" type="s"/>
    </signal>
    <property name="Version" type="s" access="read"/>
    <property name="BluetoothAvailable" type="b" access="read"/>
    <property name="Advertising" type="b" access="read"/>
    <property name="Pairing" type="b" access="read"/>
    <property name="LinkProblem" type="s" access="read"/>
    <property name="AdapterName" type="s" access="read"/>
    <property name="DeviceName" type="s" access="read"/>
    <property name="DeviceAddress" type="s" access="read"/>
    <property name="Paired" type="b" access="read"/>
    <property name="Connected" type="b" access="read"/>
    <property name="NotificationsLinked" type="b" access="read"/>
    <property name="MediaLinked" type="b" access="read"/>
    <property name="CallsLinked" type="b" access="read"/>
    <property name="CallsSupported" type="b" access="read"/>
    <property name="Battery" type="i" access="read"/>
    <property name="ICloudState" type="s" access="read"/>
    <property name="MessagesState" type="s" access="read"/>
    <property name="MessagesSend" type="s" access="read"/>
    <property name="ReactionsSend" type="b" access="read"/>
    <property name="ContactsState" type="s" access="read"/>
    <property name="Modules" type="a{{sb}}" access="read"/>
    <property name="NowPlaying" type="a{{sv}}" access="read"/>
    <method name="MediaCommand">
      <arg name="command" type="s" direction="in"/>
      <arg name="sent" type="b" direction="out"/>
    </method>
    <method name="SetMediaVolume">
      <arg name="volume" type="d" direction="in"/>
    </method>
  </interface>
</node>
"""

SIGNATURES = {
    "Version": "s", "BluetoothAvailable": "b", "Advertising": "b", "Pairing": "b",
    "LinkProblem": "s", "AdapterName": "s",
    "DeviceName": "s", "DeviceAddress": "s", "Paired": "b", "Connected": "b",
    "NotificationsLinked": "b", "MediaLinked": "b", "CallsLinked": "b", "CallsSupported": "b",
    "Battery": "i",
    "ICloudState": "s", "Modules": "a{sb}", "MessagesState": "s", "MessagesSend": "s", "ReactionsSend": "b",
    "OneTimeCodes": "s", "AutoCopyCodes": "b",
    "ContactsState": "s", "AudioOnPC": "b", "MicMuted": "b",
    "PhoneAudio": "s", "PhoneAudioOutput": "s", "ContactsSource": "s", "ContactsBook": "s",
    "UnreadMessages": "u", "MissedCalls": "u", "NowPlaying": "a{sv}", "AlphaFeatures": "a{sb}", "FetchUnread": "b", "CallsQuiet": "b", "Sounds": "a{ss}",
    "Update": "a{sv}", "Apps": "a{sv}", "Proximity": "a{sv}",
    "Tethering": "b", "TetheringState": "s", "TetheringError": "s",
    "Files": "a{sv}", "Mirror": "a{sv}", "PhotosUsb": "a{sv}", "Control": "a{sv}",
}

PROXIMITY_TYPES = {"enabled": "b", "distance": "s", "delay": "u", "rssi": "i", "near": "b"}


def _variant(name, value):
    if name in ("Files", "Mirror", "PhotosUsb", "Control"):
        from . import files, hid, mirror, photos_usb
        types = {"Files": files.TYPES, "Mirror": mirror.TYPES, "PhotosUsb": photos_usb.TYPES,
                 "Control": hid.TYPES}[name]
        return GLib.Variant("a{sv}", {k: GLib.Variant(types[k], v)
                                      for k, v in value.items() if k in types})
    if name == "Update":
        from .updates import TYPES as UPDATE_TYPES
        return GLib.Variant("a{sv}", {k: GLib.Variant(UPDATE_TYPES[k], v)
                                      for k, v in value.items() if k in UPDATE_TYPES})
    if name == "Apps":
        from .apps import TYPES as APP_TYPES
        return GLib.Variant("a{sv}", {
            package: GLib.Variant("a{sv}", {k: GLib.Variant(APP_TYPES[k], v)
                                            for k, v in entry.items() if k in APP_TYPES})
            for package, entry in value.items()})
    if name == "Proximity":
        return GLib.Variant("a{sv}", {k: GLib.Variant(PROXIMITY_TYPES[k], v)
                                      for k, v in value.items() if k in PROXIMITY_TYPES})
    if name == "NowPlaying":
        from .nowplaying import TYPES
        return GLib.Variant("a{sv}", {k: GLib.Variant(TYPES[k], v) for k, v in value.items()
                                      if k in TYPES})
    return GLib.Variant(SIGNATURES[name], value)

THREAD_TYPES = {"id": "s", "name": "s", "snippet": "s", "time": "x", "unread": "u",
                "group": "b", "outgoing": "b", "can_send": "b", "participants": "as",
                "avatar": "s", "draft": "s", "pinned": "b", "marked_unread": "b"}
SEARCH_TYPES = {"thread": "s", "name": "s", "message": "s", "time": "x", "before": "s",
                "match": "s", "after": "s", "outgoing": "b", "group": "b", "avatar": "s"}
MESSAGE_TYPES = {"id": "s", "outgoing": "b", "sender": "s", "address": "s", "time": "x",
                 "body": "s", "complete": "b", "source": "s", "status": "s", "avatar": "s",
                 "reactions": "a(ssbb)", "note": "s"}


CONTACT_TYPES = {"name": "s", "addresses": "as", "photo": "s", "uid": "s", "favorite": "b"}
CARD_TYPES = {"uid": "s", "given": "s", "family": "s", "org": "s", "note": "s",
              "phones": "a(ss)", "emails": "a(ss)"}
ACTIVE_TYPES = {"path": "o", "state": "s", "number": "s", "name": "s", "duration": "i",
                "avatar": "s"}
NOTIFICATION_TYPES = {"uid": "u", "app": "s", "app_name": "s", "title": "s", "body": "s",
                      "time": "x", "category": "u", "icon": "s", "image": "s",
                      "positive": "s", "negative": "s"}
APP_TYPES = {"id": "s", "name": "s", "enabled": "b", "count": "u", "icon": "s", "image": "s"}
OUTPUT_TYPES = {"name": "s", "description": "s", "default": "b"}
HEADPHONES_TYPES = {"address": "s", "name": "s", "model": "s", "firmware": "s", "connected": "b",
                    "linked": "b", "left": "i", "right": "i", "case": "i", "left_charging": "b",
                    "right_charging": "b", "case_charging": "b", "ear_left": "s", "ear_right": "s",
                    "mode": "i", "cycle": "i", "conversation": "i", "adaptive": "i", "one_bud": "i",
                    "features": "as", "auto_pause": "b"}
PEER_TYPES = {"id": "s", "alias": "s", "model": "s", "type": "s"}
CALL_TYPES = {"address": "s", "name": "s", "time": "x", "kind": "s", "avatar": "s"}


# Actions on the user's behalf: run at once for the Covalence app, after a confirmation
# notification for any other program (see callers.py). Each entry gives the text of
# that confirmation from the call's arguments.
def _excerpt(text, size=60):
    text = " ".join((text or "").split())
    return text if len(text) <= size else text[:size - 1] + "…"


GUARDED = {
    "Dial": lambda a: _("appeler le {number}").format(number=_excerpt(a[0], 30)),
    "SendMessage": lambda a: _("envoyer le message « {text} »").format(text=_excerpt(a[1])),
    "SendReaction": lambda a: _("envoyer une réaction {emoji}").format(emoji=_excerpt(a[1], 8)),
    "RetryMessage": lambda a: _("renvoyer un message"),
    "SendFiles": lambda a: _("envoyer {count} fichier(s) à un appareil du réseau").format(
        count=len(a[1])),
    "StartPairing": lambda a: _("rendre ce PC visible pour appairer un appareil Bluetooth"),
    "Forget": lambda a: _("oublier l'iPhone appairé"),
    "InstallUpdate": lambda a: _("installer une mise à jour de Covalence"),
    "InstallApp": lambda a: _("installer l'application {name}").format(name=_excerpt(a[0], 20)),
    "InstallBrowserHost": lambda a: _("installer l'intégration navigateur des codes SMS"),
    "DeleteMessage": lambda a: _("supprimer un message"),
    "DeleteConversation": lambda a: _("supprimer une conversation"),
    "SaveContact": lambda a: _("modifier un contact iCloud"),
    "DeleteContact": lambda a: _("supprimer un contact iCloud"),
}
# Only ever from the app: confirming a pairing code is the check itself, and typing on
# the iPhone key by key cannot be confirmed one notification at a time.
APP_ONLY = {"ConfirmPairing", "ControlKey", "ControlShortcut", "ControlText", "ControlMove",
            "ControlButton", "ControlClick", "ControlScroll", "ControlGoto", "ControlRelease"}
CONFIRM_SECONDS = 60


def outside_home(paths, home=None):
    """Paths SendFiles refuses for another program: outside the home folder or in a
    hidden one (~/.ssh, ~/.config, …). Symbolic links are resolved first."""
    home = os.path.realpath(home or os.path.expanduser("~"))
    refused = []
    for path in paths:
        rel = os.path.relpath(os.path.realpath(path), home)
        if rel == "." or rel.startswith("..") or any(p.startswith(".") for p in rel.split(os.sep)):
            refused.append(path)
    return refused


def _dicts(items, types):
    return [{k: GLib.Variant(types[k], v) for k, v in item.items() if k in types}
            for item in items]


class Service:
    def __init__(self, bus, daemon):
        self.bus = bus
        self.daemon = daemon
        self.cache = {}
        self.callers = Callers(bus)
        info = Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0]
        self.registration = bus.register_object(PATH, info, self._method, self._get, None)

    def own_name(self, on_lost):
        # DO_NOT_QUEUE: a second instance must exit instead of waiting.
        return Gio.bus_own_name_on_connection(
            self.bus, BUS_NAME, Gio.BusNameOwnerFlags.DO_NOT_QUEUE, None, on_lost)

    def _method(self, _conn, sender, _path, _iface, method, params, invocation):
        # An exception must still answer the caller (otherwise the app waits for the D-Bus
        # timeout) and must not take the daemon's main loop with it.
        self._safely(method, invocation, self._guard, sender, method, params, invocation)

    def _guard(self, sender, method, params, invocation):
        args = params.unpack() if params is not None else ()
        # LatestCode "copy" hands the code to the app's clipboard helper only.
        copy_code = method in ("LatestCode", "LatestCodeFor") and args[0] != "browser"
        if method not in GUARDED and method not in APP_ONLY and not copy_code:
            self._call(method, params, invocation)
            return
        trusted, program = self.callers.describe(sender)
        if trusted:
            self._call(method, params, invocation)
            return
        if method in APP_ONLY or copy_code:
            log(f"appel {method} refusé : {program} n'est pas l'application Covalence")
            invocation.return_dbus_error(f"{INTERFACE}.Error.NotAllowed",
                                         _("réservé à l'application Covalence"))
            return
        if method == "SendFiles" and outside_home(args[1]):
            log(f"appel SendFiles refusé : fichiers hors du dossier personnel ({program})")
            invocation.return_dbus_error(f"{INTERFACE}.Error.NotAllowed",
                                         _("fichiers hors du dossier personnel ou cachés"))
            return

        def decided(ok):
            if ok:
                self._call(method, params, invocation)
            else:
                invocation.return_dbus_error(f"{INTERFACE}.Error.Refused",
                                             _("refusé par l'utilisateur"))

        self.confirm(self.daemon.notifier, program, GUARDED[method](args), decided)

    @staticmethod
    def confirm(notifier, program, action, on_result):
        """Ask the user, by notification, whether another program may do this. No answer
        within a minute, a dismissed notification or no notification server: refused."""
        state = {"done": False, "note": 0, "timer": 0}

        def answer(ok):
            if state["done"]:
                return
            state["done"] = True
            if state["timer"]:
                GLib.source_remove(state["timer"])
            notifier.close(state["note"])
            log(f"demande d'un autre programme ({program}) : {'acceptée' if ok else 'refusée'}")
            on_result(ok)

        state["note"] = notifier.notify(
            "Covalence", "dialog-warning", _("Autoriser {program} ?").format(program=program),
            _("« {program} » demande à Covalence de {action}. Refusez si ce n'est pas vous.")
            .format(program=program, action=action),
            actions=[("allow", _("Autoriser")), ("deny", _("Refuser"))],
            hints={"urgency": GLib.Variant("y", 2)}, own=True,
            on_action=lambda key: answer(key == "allow"),
            on_closed=lambda: answer(False))
        if not state["note"]:
            answer(False)
            return
        if not state["done"]:
            state["timer"] = GLib.timeout_add_seconds(CONFIRM_SECONDS,
                                                      lambda: answer(False) or False)

    @staticmethod
    def _safely(method, invocation, fn, *args):
        try:
            fn(*args)
        except GLib.Error as e:
            log(f"D-Bus : {method} a échoué ({e.message})")
            invocation.return_dbus_error(f"{INTERFACE}.Error.Failed", e.message)
        except Exception as e:  # noqa: BLE001 - reported to the caller and to the journal
            log(f"D-Bus : {method} a échoué ({e.__class__.__name__}: {e})")
            invocation.return_dbus_error(f"{INTERFACE}.Error.Failed", f"{e.__class__.__name__}: {e}")

    def _call(self, method, params, invocation):
        # Also reached from a confirmation callback, outside _method's own guard.
        self._safely(method, invocation, self._dispatch, method, params, invocation)

    def _dispatch(self, method, params, invocation):
        d = self.daemon
        if method == "SetModuleEnabled":
            module, enabled = params.unpack()
            if module not in MODULES:
                invocation.return_dbus_error(f"{INTERFACE}.Error.UnknownModule", module)
                return
            d.set_module_enabled(module, enabled)
        elif method == "StartPairing":
            if not d.link.start_pairing():
                invocation.return_dbus_error(f"{INTERFACE}.Error.NoAdapter",
                                             "no Bluetooth adapter")
                return
        elif method == "ConfirmPairing":
            if not d.link.confirm_pairing(params.unpack()[0]):
                invocation.return_dbus_error(f"{INTERFACE}.Error.NoPairing",
                                             _("aucun code en attente"))
                return
        elif method == "StopPairing":
            d.link.stop_pairing()
        elif method == "Reconnect":
            d.link.reconnect_now()
        elif method == "Forget":
            d.link.forget()
        elif method == "ICloudUpdated":
            d.icloud.reset()
        elif method == "ListThreads":
            invocation.return_value(GLib.Variant(
                "(aa{sv})", (_dicts(d.messages.threads(), THREAD_TYPES),)))
            return
        elif method == "GetMessages":
            (thread,) = params.unpack()
            invocation.return_value(GLib.Variant(
                "(aa{sv})", (_dicts(d.messages.messages(thread), MESSAGE_TYPES),)))
            return
        elif method == "ListContacts":
            invocation.return_value(GLib.Variant(
                "(aa{sv})", (_dicts(d.contact_cards(), CONTACT_TYPES),)))
            return
        elif method == "OpenConversation":
            thread = d.messages.open_conversation(params.unpack()[0])
            if thread is None:
                invocation.return_dbus_error(f"{INTERFACE}.Error.InvalidAddress",
                                             "not a phone number or e-mail address")
            else:
                invocation.return_value(GLib.Variant(
                    "(a{sv})", (_dicts([thread], THREAD_TYPES)[0],)))
            return
        elif method == "MarkThreadSeen":
            d.messages.mark_seen(params.unpack()[0])
        elif method == "SyncMessages":
            d.messages.retry()
        elif method == "Sync":
            def synced(count, error):
                if error:
                    invocation.return_dbus_error(f"{INTERFACE}.Error.SyncFailed", error)
                else:
                    invocation.return_value(GLib.Variant("(u)", (int(count),)))

            d.messages.manual_sync(synced)
            return
        elif method == "ReadFullText":
            if not d.messages.read_full(params.unpack()[0]):
                invocation.return_dbus_error(f"{INTERFACE}.Error.NoSuchMessage",
                                             "no truncated message with this id")
                return
        elif method == "SetSound":
            kind, value = params.unpack()
            try:
                d.set_sound(kind, value)
            except ValueError:
                invocation.return_dbus_error(f"{INTERFACE}.Error.InvalidSound",
                                             _("son introuvable"))
                return
        elif method == "ListSounds":
            from .sounds import available
            invocation.return_value(GLib.Variant("(a(ss))", (available(),)))
            return
        elif method == "PlaySound":
            kind, value = params.unpack()
            if not d.sounds.preview(kind, value):
                invocation.return_dbus_error(f"{INTERFACE}.Error.CannotPlay",
                                             _("lecture impossible"))
                return
        elif method == "StopSound":
            d.sounds.stop()
        elif method == "SetTethering":
            try:
                if params.unpack()[0]:
                    d.hotspot.connect()
                else:
                    d.hotspot.disconnect()
            except (RuntimeError, GLib.Error) as error:
                invocation.return_dbus_error(f"{INTERFACE}.Error.Tethering",
                                             getattr(error, "message", None) or str(error))
                return
        elif method == "SetProximity":
            enabled, distance, delay = params.unpack()
            try:
                d.proximity.configure(enabled, distance, int(delay))
            except ValueError as error:
                invocation.return_dbus_error(f"{INTERFACE}.Error.InvalidArgs", str(error))
                return
        elif method == "SetCallsQuiet":
            d.set_calls_quiet(params.unpack()[0])
        elif method == "SetFetchUnread":
            d.set_fetch_unread(params.unpack()[0])
        elif method == "SetAlphaFeature":
            feature, enabled = params.unpack()
            if feature not in ALPHA:
                invocation.return_dbus_error(f"{INTERFACE}.Error.UnknownFeature", feature)
                return
            d.set_alpha(feature, enabled)
        elif method == "NotificationAction":
            uid, action = params.unpack()
            if not d.config.alpha("ancs_actions"):
                invocation.return_dbus_error(f"{INTERFACE}.Error.Disabled", "ancs_actions is off")
                return
            if not d.notification_action(uid, action):
                invocation.return_dbus_error(f"{INTERFACE}.Error.NotLinked",
                                             _("notifications de l'iPhone non reliées"))
                return
        elif method == "ListNotifications":
            invocation.return_value(GLib.Variant(
                "(aa{sv})", (_dicts(d.notifications.listing(), NOTIFICATION_TYPES),)))
            return
        elif method == "ListNotificationApps":
            invocation.return_value(GLib.Variant(
                "(aa{sv})", (_dicts(d.notifications.apps(), APP_TYPES),)))
            return
        elif method == "SetNotificationApp":
            d.notifications.set_app_enabled(*params.unpack())
        elif method == "ClearNotifications":
            d.notifications.clear()
        elif method == "ListHeadphones":
            invocation.return_value(GLib.Variant(
                "(aa{sv})", (_dicts(d.headphones.listing(), HEADPHONES_TYPES),)))
            return
        elif method == "SetHeadphones":
            address, key, value = params.unpack()
            try:
                ok = d.headphones.set(address, key, value)
            except (KeyError, ValueError, TypeError):
                ok = False
            if not ok:
                invocation.return_dbus_error(f"{INTERFACE}.Error.Headphones",
                                             _("écouteurs non connectés ou réglage refusé"))
                return
        elif method == "SetContactsSource":
            try:
                d.contact_book.set_source(params.unpack()[0])
            except ValueError:
                invocation.return_dbus_error(f"{INTERFACE}.Error.InvalidArgs", "bluetooth or icloud")
                return
        elif method in ("GetContact", "SaveContact", "DeleteContact"):
            self._contact_method(method, params, invocation)
            return
        elif method == "SetPhoneAudio":
            d.audio.set_receive(params.unpack()[0])
        elif method == "SetPhoneAudioOutput":
            d.audio.set_output(params.unpack()[0])
        elif method == "ListAudioOutputs":
            invocation.return_value(GLib.Variant(
                "(aa{sv})", (_dicts(d.audio.outputs(), OUTPUT_TYPES),)))
            return
        elif method == "MarkCallsSeen":
            d.messages.mark_calls_seen()
        elif method == "ListActiveCalls":
            invocation.return_value(GLib.Variant(
                "(aa{sv})", (_dicts(d.active_calls(), ACTIVE_TYPES),)))
            return
        elif method in ("CallAction", "SetCallAudio", "SendTones"):
            def finished(error):
                if error:
                    invocation.return_dbus_error(f"{INTERFACE}.Error.CallFailed", error)
                else:
                    invocation.return_value(None)

            if method == "CallAction":
                d.calls.call_action(*params.unpack(), finished)
            elif method == "SetCallAudio":
                d.calls.set_audio_on_pc(params.unpack()[0], finished)
            else:
                d.calls.send_tones(params.unpack()[0], finished)
            return
        elif method == "SimulateCall":
            kind = params.unpack()[0]
            d.calls.simulate("incoming" if kind == "incoming" else "outgoing")
        elif method == "SetMuted":
            d.calls.set_muted(params.unpack()[0])
        elif method == "ListCalls":
            invocation.return_value(GLib.Variant(
                "(aa{sv})", (_dicts(d.messages.call_history(), CALL_TYPES),)))
            return
        elif method == "Dial":
            number = params.unpack()[0].strip()
            if not number:
                invocation.return_dbus_error(f"{INTERFACE}.Error.InvalidAddress", "empty number")
                return

            def dialled(error):
                if error:
                    invocation.return_dbus_error(f"{INTERFACE}.Error.DialFailed", error)
                else:
                    invocation.return_value(None)

            d.calls.dial(number, dialled)
            return
        elif method == "SetDraft":
            d.messages.set_draft(*params.unpack())
        elif method == "SearchThreads":
            invocation.return_value(GLib.Variant("(as)", (d.messages.search(params.unpack()[0]),)))
            return
        elif method == "SearchMessages":
            invocation.return_value(GLib.Variant(
                "(aa{sv})", (_dicts(d.messages.search_messages(params.unpack()[0]), SEARCH_TYPES),)))
            return
        elif method == "PinThread":
            d.messages.set_pinned(*params.unpack())
        elif method == "MarkThreadUnread":
            d.messages.set_marked_unread(*params.unpack())
        elif method == "MediaCommand":
            sent = d.now_playing.command(params.unpack()[0])
            invocation.return_value(GLib.Variant("(b)", (bool(sent),)))
            return
        elif method == "SetMediaVolume":
            d.now_playing.set_volume(params.unpack()[0])
        elif method == "SetViewing":
            d.messages.set_viewing(params.unpack()[0])
        elif method == "LatestCode":
            code, age = d.messages.latest_code(params.unpack()[0])
            invocation.return_value(GLib.Variant("(su)", (code, age)))
            return
        elif method == "LatestCodeFor":
            # For the browser extension: the code, the sites it is bound to (if the SMS says
            # so) and who sent it, so a page never gets a code without the user seeing that.
            purpose = params.unpack()[0]
            code, age = d.messages.latest_code(purpose)
            domains, sender = [], ""
            if code:
                from .otp import bound_domains
                key = d.messages.codes.latest()[2]
                m = d.messages.store.message(key) if key and d.messages.store else None
                if m:
                    domains = bound_domains(m["body"] or "", code)
                    sender = d.messages.store.display_name(m["sender"], m["sender_name"] or "")
            invocation.return_value(GLib.Variant("(suass)", (code, age, domains, sender)))
            return
        elif method == "SetOneTimeCodes":
            d.messages.set_code_mode(params.unpack()[0])
            d.link_changed()
        elif method == "SetAutoCopyCodes":
            d.messages.set_auto_copy_codes(params.unpack()[0])
            d.link_changed()
        elif method == "SetLocalSend":
            d.files.set_enabled(params.unpack()[0])
        elif method == "ListFilePeers":
            invocation.return_value(GLib.Variant("(aa{sv})", (_dicts(d.files.list_peers(), PEER_TYPES),)))
            return
        elif method == "RefreshFilePeers":
            d.files.refresh()
        elif method == "SendFiles":
            # Returns once the transfer starts: the iPhone asks its user, which can take
            # minutes. The outcome comes as a notification and through the Files property.
            peer, paths = params.unpack()
            error = d.files.send(peer, paths)
            if error:
                invocation.return_dbus_error(f"{INTERFACE}.Error.SendFailed", error)
                return
        elif method == "CancelFiles":
            d.files.cancel()
        elif method == "StartMirror":
            if not d.mirror.start():
                invocation.return_dbus_error(f"{INTERFACE}.Error.MirrorFailed",
                                             d.mirror.error or "failed")
                return
        elif method == "StopMirror":
            d.mirror.stop()
        elif method == "SetMirrorOption":
            key, value = params.unpack()
            if not d.mirror.set_option(key, value):
                invocation.return_dbus_error(f"{INTERFACE}.Error.InvalidOption", key)
                return
        elif method.startswith("Control") or method == "SetControlSize":
            control = d.control
            if method == "SetControlSize":
                control.set_size(*params.unpack())
            elif not control.registered:
                invocation.return_dbus_error(f"{INTERFACE}.Error.ControlOff",
                                             "iPhone control is not published")
                return
            elif method == "ControlKey":
                control.key(*params.unpack())
            elif method == "ControlShortcut":
                control.shortcut(*params.unpack())
            elif method == "ControlText":
                invocation.return_value(GLib.Variant("(i)", (control.text(params.unpack()[0]),)))
                return
            elif method == "ControlMove":
                control.move(*params.unpack())
            elif method == "ControlButton":
                control.button(*params.unpack())
            elif method == "ControlClick":
                control.click(params.unpack()[0])
            elif method == "ControlScroll":
                control.scroll(params.unpack()[0])
            elif method == "ControlGoto":
                control.goto(*params.unpack())
            elif method == "ControlRelease":
                control.release_all()
        elif method == "RefreshPhotosUsb":
            d.photos_usb.refresh()
        elif method == "PairPhotosUsb":
            d.photos_usb.pair()
        elif method == "ImportPhotosUsb":
            d.photos_usb.import_photos()
        elif method == "CancelPhotosUsb":
            d.photos_usb.cancel()
        elif method == "SetConvertHeic":
            d.photos_usb.set_convert_heic(params.unpack()[0])
        elif method == "CheckUpdates":
            def checked(latest, error):
                if error:
                    invocation.return_dbus_error(f"{INTERFACE}.Error.UpdateCheckFailed", error)
                else:
                    invocation.return_value(GLib.Variant("(s)", (latest,)))

            d.updates.check(checked)
            return
        elif method == "InstallUpdate":
            # Download and install take minutes (polkit asks for the password): the call
            # returns at once, progress and outcome go through the Update property.
            refused = []
            d.updates.install(lambda error: refused.append(error) if error else None)
            if refused and d.updates.state_name not in ("downloading", "installing"):
                invocation.return_dbus_error(f"{INTERFACE}.Error.UpdateFailed", refused[0])
                return
        elif method == "CheckApps":
            d.apps.check()
        elif method == "InstallApp":
            # Like InstallUpdate: returns at once, the Apps property carries the rest.
            refused = []
            d.apps.install(params.unpack()[0], lambda error: refused.append(error) if error else None)
            if refused:
                invocation.return_dbus_error(f"{INTERFACE}.Error.InstallFailed", refused[0])
                return
        elif method == "SetUpdateChecks":
            d.updates.set_auto(params.unpack()[0])
        elif method == "RestartDaemon":
            from .updates import restart_daemon
            invocation.return_value(None)
            GLib.timeout_add(300, lambda: restart_daemon() and False)
            return
        elif method == "InstallBrowserHost":
            from . import browser_host
            try:
                installed = browser_host.install()
            except OSError as error:
                invocation.return_dbus_error(f"{INTERFACE}.Error.Failed", str(error))
                return
            invocation.return_value(GLib.Variant("(as)", (installed,)))
            return
        elif method == "DeleteMessage":
            d.messages.delete_message(params.unpack()[0])
        elif method == "DeleteConversation":
            d.messages.delete_conversation(params.unpack()[0])
        elif method == "DiscardMessage":
            d.messages.discard_message(params.unpack()[0])
        elif method == "RetryMessage":
            def retried(error):
                if error:
                    invocation.return_dbus_error(f"{INTERFACE}.Error.SendFailed", error)
                else:
                    invocation.return_value(None)

            d.messages.retry_message(params.unpack()[0], retried)
            return
        elif method == "SendReaction":
            message, emoji = params.unpack()

            def reacted(error):
                if error:
                    invocation.return_dbus_error(f"{INTERFACE}.Error.SendFailed", error)
                else:
                    invocation.return_value(None)

            d.messages.send_reaction(message, emoji, reacted)
            return
        elif method == "SendMessage":
            thread, text = params.unpack()

            def done(error):
                if error:
                    invocation.return_dbus_error(f"{INTERFACE}.Error.SendFailed", error)
                else:
                    invocation.return_value(None)

            d.messages.send(thread, text, done)
            return
        invocation.return_value(None)

    def _contact_method(self, method, params, invocation):
        book = self.daemon.contact_book

        def failed(error):
            invocation.return_dbus_error(f"{INTERFACE}.Error.Contacts", str(error))

        if not book.editable:
            failed(_("contacts iCloud non disponibles"))
            return
        (arg,) = params.unpack()
        if method == "GetContact":
            book.details(arg, lambda card, error: failed(error) if error else
                         invocation.return_value(GLib.Variant(
                             "(a{sv})", (_dicts([card], CARD_TYPES)[0],))))
        elif method == "SaveContact":
            card = {k: v for k, v in arg.items() if k in CARD_TYPES}
            card["phones"] = [list(p) for p in card.get("phones", [])]
            card["emails"] = [list(e) for e in card.get("emails", [])]
            book.save(card, lambda uid, error: failed(error) if error else
                      invocation.return_value(GLib.Variant("(s)", (uid or "",))))
        else:
            book.delete(arg, lambda _r, error: failed(error) if error else
                        invocation.return_value(None))

    def headphones_changed(self):
        self.bus.emit_signal(None, PATH, INTERFACE, "HeadphonesChanged", None)

    def contacts_changed(self):
        self.bus.emit_signal(None, PATH, INTERFACE, "ContactsChanged", None)

    def _get(self, _conn, _sender, _path, _iface, name):
        return _variant(name, self.daemon.properties()[name])

    def refresh(self):
        """Emit PropertiesChanged for whatever changed since the last call."""
        current = self.daemon.properties()
        changed = {k: _variant(k, v) for k, v in current.items() if self.cache.get(k) != v}
        self.cache = current
        if changed:
            self.bus.emit_signal(None, PATH, "org.freedesktop.DBus.Properties",
                                 "PropertiesChanged",
                                 GLib.Variant("(sa{sv}as)", (INTERFACE, changed, [])))

    def threads_changed(self):
        self.bus.emit_signal(None, PATH, INTERFACE, "ThreadsChanged", None)

    def send_progress(self, thread, key, fraction):
        self.bus.emit_signal(None, PATH, INTERFACE, "SendProgress",
                             GLib.Variant("(ssd)", (thread, key, fraction)))

    def notifications_changed(self):
        self.bus.emit_signal(None, PATH, INTERFACE, "NotificationsChanged", None)

    def active_calls_changed(self):
        self.bus.emit_signal(None, PATH, INTERFACE, "ActiveCallsChanged", None)

    def calls_changed(self):
        self.bus.emit_signal(None, PATH, INTERFACE, "CallsChanged", None)

    def message_received(self, thread, key):
        self.bus.emit_signal(None, PATH, INTERFACE, "MessageReceived",
                             GLib.Variant("(ss)", (thread, key)))

    def pairing_code(self, passkey):
        self.bus.emit_signal(None, PATH, INTERFACE, "PairingCode", GLib.Variant("(u)", (passkey,)))

    def pairing_code_answered(self, matches):
        self.bus.emit_signal(None, PATH, INTERFACE, "PairingCodeAnswered",
                             GLib.Variant("(b)", (bool(matches),)))
