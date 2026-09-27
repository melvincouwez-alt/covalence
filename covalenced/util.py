# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Shared helpers: logging, D-Bus shortcuts and desktop notifications.

Privacy rule from the design document: logs record events, never content
(no notification text, no track titles, no phone numbers, no secrets).
"""

import os

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

APP_ID = "io.github.melvincouwez.Covalence"

# iCloud sources in Evolution Data Server. Sources made before the app was
# renamed from Tandem (2026-09-27) keep their uid: EDS keys secrets and caches by it.
ICLOUD_UID_PREFIX = "covalence-icloud"
LEGACY_ICLOUD_UID_PREFIX = "tandem-icloud"
ICLOUD_UID_PREFIXES = (ICLOUD_UID_PREFIX, LEGACY_ICLOUD_UID_PREFIX)


def icloud_uid_prefix():
    """Prefix of this user's iCloud sources: the legacy one when only it exists."""
    sources = os.path.join(GLib.get_user_config_dir(), "evolution", "sources")

    def has(prefix):
        return os.path.exists(os.path.join(sources, f"{prefix}-collection.source"))

    if not has(ICLOUD_UID_PREFIX) and has(LEGACY_ICLOUD_UID_PREFIX):
        return LEGACY_ICLOUD_UID_PREFIX
    return ICLOUD_UID_PREFIX
BLUEZ = "org.bluez"


def log(message):
    # journald adds the timestamp and the unit name.
    print(message, flush=True)


def call_sync(bus, name, path, interface, method, args=None, reply=None, timeout=5000):
    return bus.call_sync(name, path, interface, method, args,
                         GLib.VariantType(reply) if reply else None,
                         Gio.DBusCallFlags.NONE, timeout, None)


def call_async(bus, name, path, interface, method, args=None, on_done=None,
               timeout=-1, what=None):
    """Fire an asynchronous call; on_done(result_variant | None, error | None)."""

    def finish(conn, result, _data):
        try:
            value = conn.call_finish(result)
        except GLib.Error as error:
            if on_done:
                on_done(None, error)
            elif what:
                log(f"{what} : {error.message}")
            return
        if on_done:
            on_done(value, None)

    bus.call(name, path, interface, method, args, None, Gio.DBusCallFlags.NONE,
             timeout, None, finish, None)


def get_all(bus, name, path, interface):
    return call_sync(bus, name, path, "org.freedesktop.DBus.Properties", "GetAll",
                     GLib.Variant("(s)", (interface,)), "(a{sv})").unpack()[0]


def set_prop(bus, name, path, interface, prop, value, what=None):
    call_async(bus, name, path, "org.freedesktop.DBus.Properties", "Set",
               GLib.Variant("(ssv)", (interface, prop, value)), what=what)


class Notifier:
    """org.freedesktop.Notifications client with action callbacks."""

    NAME = "org.freedesktop.Notifications"
    PATH = "/org/freedesktop/Notifications"

    def __init__(self, bus):
        self.bus = bus
        self.handlers = {}  # notification id -> (on_action, on_closed)
        # No sender filter: GDBus matches well-known names only once resolved.
        bus.signal_subscribe(None, self.NAME, "ActionInvoked", self.PATH, None,
                             Gio.DBusSignalFlags.NONE, self._on_action)
        bus.signal_subscribe(None, self.NAME, "NotificationClosed", self.PATH, None,
                             Gio.DBusSignalFlags.NONE, self._on_closed)
        # KDE-style inline reply; elementary does not offer it (checked 2026-09-26).
        bus.signal_subscribe(None, self.NAME, "NotificationReplied", self.PATH, None,
                             Gio.DBusSignalFlags.NONE, self._on_replied)
        self._caps = None

    def capabilities(self):
        if self._caps is None:
            try:
                self._caps = set(call_sync(self.bus, self.NAME, self.PATH, self.NAME,
                                           "GetCapabilities", reply="(as)").unpack()[0])
            except GLib.Error:
                return set()  # server not up yet: ask again next time
        return self._caps

    def _on_replied(self, _conn, _sender, _path, _iface, _signal, params):
        notification_id, text = params.unpack()
        handler = self.handlers.get(notification_id)
        if handler and handler[0]:
            handler[0]("inline-reply:" + text)

    def notify(self, app_name, icon, summary, body="", actions=(), hints=None,
               replaces=0, timeout=-1, on_action=None, on_closed=None, own=False):
        """Show or replace a notification; returns its id (0 on failure).

        own=True ties the notification to the Covalence launcher (its name, icon and
        notification settings); iPhone notifications keep the phone name instead.
        """
        flat = []
        for key, label in actions:
            flat += [key, label]
        hint_dict = dict(hints or {})
        if own:
            hint_dict["desktop-entry"] = GLib.Variant("s", APP_ID)
        try:
            result = call_sync(self.bus, self.NAME, self.PATH, self.NAME, "Notify",
                               GLib.Variant("(susssasa{sv}i)", (
                                   app_name, replaces, icon, summary, body, flat,
                                   hint_dict, timeout)), "(u)")
        except GLib.Error as error:
            log(f"notification impossible : {error.message}")
            return 0
        notification_id = result.unpack()[0]
        if on_action or on_closed:
            self.handlers[notification_id] = (on_action, on_closed)
        else:
            self.handlers.pop(notification_id, None)
        return notification_id

    def close(self, notification_id):
        if not notification_id:
            return
        self.handlers.pop(notification_id, None)
        call_async(self.bus, self.NAME, self.PATH, self.NAME, "CloseNotification",
                   GLib.Variant("(u)", (notification_id,)))

    def _on_action(self, _conn, _sender, _path, _iface, _signal, params):
        notification_id, key = params.unpack()
        handler = self.handlers.get(notification_id)
        if handler and handler[0]:
            handler[0](key)

    def _on_closed(self, _conn, _sender, _path, _iface, _signal, params):
        notification_id, _reason = params.unpack()
        handler = self.handlers.pop(notification_id, None)
        if handler and handler[1]:
            handler[1]()
