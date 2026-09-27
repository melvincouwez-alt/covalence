# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Session bus API of the daemon: io.github.melvincouwez.Covalence1.

The app only talks to the daemon through this interface. The bus name is
io.github.melvincouwez.Covalence.Daemon: the app itself (GtkApplication) owns
io.github.melvincouwez.Covalence.
"""

from gi.repository import Gio, GLib

from .config import MODULES
from .i18n import _

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
    <method name="StopPairing"/>
    <method name="Reconnect"/>
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
    <method name="SetDraft">
      <arg name="thread" type="s" direction="in"/>
      <arg name="text" type="s" direction="in"/>
    </method>
    <method name="SearchThreads">
      <arg name="query" type="s" direction="in"/>
      <arg name="threads" type="as" direction="out"/>
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
    <signal name="ThreadsChanged"/>
    <signal name="MessageReceived">
      <arg name="thread" type="s"/>
      <arg name="message" type="s"/>
    </signal>
    <property name="Version" type="s" access="read"/>
    <property name="BluetoothAvailable" type="b" access="read"/>
    <property name="Advertising" type="b" access="read"/>
    <property name="Pairing" type="b" access="read"/>
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
    "DeviceName": "s", "DeviceAddress": "s", "Paired": "b", "Connected": "b",
    "NotificationsLinked": "b", "MediaLinked": "b", "CallsLinked": "b", "CallsSupported": "b",
    "Battery": "i",
    "ICloudState": "s", "Modules": "a{sb}", "MessagesState": "s", "MessagesSend": "s", "ReactionsSend": "b",
    "ContactsState": "s", "AudioOnPC": "b", "MicMuted": "b",
    "PhoneAudio": "s", "PhoneAudioOutput": "s", "ContactsSource": "s", "ContactsBook": "s",
    "UnreadMessages": "u", "MissedCalls": "u", "NowPlaying": "a{sv}",
}


def _variant(name, value):
    if name == "NowPlaying":
        from .nowplaying import TYPES
        return GLib.Variant("a{sv}", {k: GLib.Variant(TYPES[k], v) for k, v in value.items()
                                      if k in TYPES})
    return GLib.Variant(SIGNATURES[name], value)

THREAD_TYPES = {"id": "s", "name": "s", "snippet": "s", "time": "x", "unread": "u",
                "group": "b", "outgoing": "b", "can_send": "b", "participants": "as",
                "avatar": "s", "draft": "s"}
MESSAGE_TYPES = {"id": "s", "outgoing": "b", "sender": "s", "address": "s", "time": "x",
                 "body": "s", "complete": "b", "source": "s", "status": "s", "avatar": "s",
                 "reactions": "a(ssbb)"}


CONTACT_TYPES = {"name": "s", "addresses": "as", "photo": "s", "uid": "s"}
CARD_TYPES = {"uid": "s", "given": "s", "family": "s", "org": "s", "note": "s",
              "phones": "a(ss)", "emails": "a(ss)"}
ACTIVE_TYPES = {"path": "o", "state": "s", "number": "s", "name": "s", "duration": "i",
                "avatar": "s"}
NOTIFICATION_TYPES = {"uid": "u", "app": "s", "app_name": "s", "title": "s", "body": "s",
                      "time": "x", "category": "u", "icon": "s", "image": "s"}
APP_TYPES = {"id": "s", "name": "s", "enabled": "b", "count": "u", "icon": "s", "image": "s"}
OUTPUT_TYPES = {"name": "s", "description": "s", "default": "b"}
HEADPHONES_TYPES = {"address": "s", "name": "s", "model": "s", "firmware": "s", "connected": "b",
                    "linked": "b", "left": "i", "right": "i", "case": "i", "left_charging": "b",
                    "right_charging": "b", "case_charging": "b", "ear_left": "s", "ear_right": "s",
                    "mode": "i", "cycle": "i", "conversation": "i", "adaptive": "i", "one_bud": "i",
                    "features": "as", "auto_pause": "b"}
CALL_TYPES = {"address": "s", "name": "s", "time": "x", "kind": "s", "avatar": "s"}


def _dicts(items, types):
    return [{k: GLib.Variant(types[k], v) for k, v in item.items() if k in types}
            for item in items]


class Service:
    def __init__(self, bus, daemon):
        self.bus = bus
        self.daemon = daemon
        self.cache = {}
        info = Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0]
        self.registration = bus.register_object(PATH, info, self._method, self._get, None)

    def own_name(self, on_lost):
        # DO_NOT_QUEUE: a second instance must exit instead of waiting.
        return Gio.bus_own_name_on_connection(
            self.bus, BUS_NAME, Gio.BusNameOwnerFlags.DO_NOT_QUEUE, None, on_lost)

    def _method(self, _conn, _sender, _path, _iface, method, params, invocation):
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
        elif method == "StopPairing":
            d.link.stop_pairing()
        elif method == "Reconnect":
            d.link.reconnect_now()
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
        elif method == "MediaCommand":
            sent = d.now_playing.command(params.unpack()[0])
            invocation.return_value(GLib.Variant("(b)", (bool(sent),)))
            return
        elif method == "SetMediaVolume":
            d.now_playing.set_volume(params.unpack()[0])
        elif method == "SetViewing":
            d.messages.set_viewing(params.unpack()[0])
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
