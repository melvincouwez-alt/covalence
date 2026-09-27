# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Apple Notification Center Service client: iPhone notifications on the desktop.

The iPhone is the GATT server; the PC subscribes to Notification Source and
Data Source, asks for the attributes of each new notification and re-emits it
through org.freedesktop.Notifications. Positive and negative ANCS actions
(e.g. accept/decline, mark as read/delete) become notification buttons.
"""

import struct

from gi.repository import GLib

from .gatt import GattClient
from .i18n import _
from . import appicons
from .util import log

SERVICE = "7905f431-b5ce-4e99-a40f-4b1e122d00d0"
NOTIFICATION_SOURCE = "9fbf120d-6301-42d9-8c58-25e699a21dbd"
CONTROL_POINT = "69d1d8f3-45e1-49a8-9821-9bbdfdaad9d9"
DATA_SOURCE = "22eac6e9-24d6-4bb5-be44-b36ace7c7bfb"

EVENT_ADDED, EVENT_MODIFIED, EVENT_REMOVED = 0, 1, 2
FLAG_SILENT = 1 << 0
FLAG_IMPORTANT = 1 << 1
FLAG_PREEXISTING = 1 << 2
FLAG_POSITIVE_ACTION = 1 << 3
FLAG_NEGATIVE_ACTION = 1 << 4

CMD_GET_NOTIFICATION_ATTRIBUTES = 0
CMD_GET_APP_ATTRIBUTES = 1
CMD_PERFORM_NOTIFICATION_ACTION = 2
ACTION_POSITIVE, ACTION_NEGATIVE = 0, 1

ATTR_APP_IDENTIFIER, ATTR_TITLE, ATTR_SUBTITLE, ATTR_MESSAGE = 0, 1, 2, 3
ATTR_POSITIVE_LABEL, ATTR_NEGATIVE_LABEL = 6, 7
APP_ATTR_DISPLAY_NAME = 0
MOBILE_SMS = "com.apple.MobileSMS"

CATEGORY_INCOMING_CALL, CATEGORY_MISSED_CALL = 1, 2
CATEGORIES = {
    0: "autre", 1: "appel entrant", 2: "appel manqué", 3: "messagerie vocale",
    4: "social", 5: "agenda", 6: "e-mail", 7: "actualités", 8: "santé",
    9: "finances", 10: "localisation", 11: "divertissement",
}
CATEGORY_HINTS = {1: "call.incoming", 2: "call.unanswered", 6: "email.arrived",
                  4: "im.received"}


class AncsClient(GattClient):
    def __init__(self, bus, chars, device_name, notifier, hooks):
        super().__init__(bus, chars, "ANCS")
        self.device_name = device_name
        self.notifier = notifier
        # hooks.suppress_incoming_call(title) -> bool : the calls module shows it
        self.hooks = hooks
        self.buffer = b""
        self.pending = {}  # uid -> (category, flags)
        self.app_names = {}
        self.pending_apps = set()
        self.desktop_ids = {}  # ANCS uid -> desktop notification id

    def start(self):
        self.subscribe((DATA_SOURCE, NOTIFICATION_SOURCE))

    def stop(self):
        super().stop()

    def on_value(self, path, value):
        uuid = self.uuid_of(path)
        if uuid == NOTIFICATION_SOURCE:
            self._on_notification_source(value)
        elif uuid == DATA_SOURCE:
            self.buffer += value
            self._parse_data_source()

    def on_request_failed(self):
        self.buffer = b""

    # --- Notification Source ------------------------------------------------

    def _on_notification_source(self, value):
        if len(value) < 8:
            return
        event, flags, category, _count, uid = struct.unpack("<BBBBI", value[:8])
        if event == EVENT_REMOVED:
            log(f"notification {uid} retirée")
            gone = getattr(self.hooks, "notification_removed", None)
            if gone:
                gone(uid)
            self.notifier.close(self.desktop_ids.pop(uid, 0))
            return
        if flags & FLAG_PREEXISTING:
            return  # already on the iPhone before we connected: not replayed
        label = CATEGORIES.get(category, str(category))
        log(f"notification {uid} {'ajoutée' if event == EVENT_ADDED else 'modifiée'} ({label})")
        self.pending[uid] = (category, flags if event == EVENT_ADDED else flags | FLAG_SILENT)
        request = struct.pack("<BI", CMD_GET_NOTIFICATION_ATTRIBUTES, uid)
        request += bytes([ATTR_APP_IDENTIFIER])
        request += struct.pack("<BH", ATTR_TITLE, 64)
        request += struct.pack("<BH", ATTR_SUBTITLE, 64)
        request += struct.pack("<BH", ATTR_MESSAGE, 512)
        request += bytes([ATTR_POSITIVE_LABEL, ATTR_NEGATIVE_LABEL])
        self.write(CONTROL_POINT, request, waits_for_response=True)

    # --- Data Source --------------------------------------------------------

    def _parse_data_source(self):
        """Consume one complete response from the buffer once it has fully arrived."""
        data = self.buffer
        if not data:
            return
        if data[0] == CMD_GET_NOTIFICATION_ATTRIBUTES:
            if len(data) < 5:
                return
            parsed = self._parse_attributes(data[5:], 6)
            if parsed is None:
                return  # rest of the response comes in the next packet
            attrs, used = parsed
            self.buffer = data[5 + used:]
            self._deliver(struct.unpack("<I", data[1:5])[0], attrs)
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
            named = getattr(self.hooks, "notification_app_named", None)
            if named:
                named(app_id, self.app_names[app_id])
            self.pending_apps.discard(app_id)
        else:
            self.buffer = b""
        self.response_complete()

    @staticmethod
    def _parse_attributes(data, count):
        attrs, offset = {}, 0
        for _index in range(count):
            if len(data) < offset + 3:
                return None
            attr_id, length = struct.unpack("<BH", data[offset:offset + 3])
            if len(data) < offset + 3 + length:
                return None
            attrs[attr_id] = data[offset + 3:offset + 3 + length].decode("utf-8", "replace")
            offset += 3 + length
        return attrs, offset

    def _deliver(self, uid, attrs):
        category, flags = self.pending.pop(uid, (0, 0))
        title = attrs.get(ATTR_TITLE, "")
        if category == CATEGORY_INCOMING_CALL and self.hooks.suppress_incoming_call(title):
            log(f"notification {uid} confiée au module Appels")
            return
        app_id = attrs.get(ATTR_APP_IDENTIFIER, "")
        take_message = getattr(self.hooks, "message_notification", None)
        if app_id == MOBILE_SMS and take_message and take_message(
                title, attrs.get(ATTR_SUBTITLE, ""), attrs.get(ATTR_MESSAGE, "")):
            log(f"notification {uid} confiée au module Messages")
            return
        if app_id and app_id not in self.app_names and app_id not in self.pending_apps:
            self.pending_apps.add(app_id)
            self.write(CONTROL_POINT, bytes([CMD_GET_APP_ATTRIBUTES]) + app_id.encode() + b"\0"
                       + bytes([APP_ATTR_DISPLAY_NAME]), waits_for_response=True)
        app_name = self.app_names.get(app_id, app_id.rsplit(".", 1)[-1] if app_id else "")

        summary = title or app_name or "iPhone"
        if app_name and title and app_name != title:
            summary = f"{app_name} · {title}"
        body = "\n".join(filter(None, [attrs.get(ATTR_SUBTITLE), attrs.get(ATTR_MESSAGE)]))

        actions = []
        if flags & FLAG_POSITIVE_ACTION:
            actions.append(("positive", attrs.get(ATTR_POSITIVE_LABEL) or "OK"))
        if flags & FLAG_NEGATIVE_ACTION:
            actions.append(("negative", attrs.get(ATTR_NEGATIVE_LABEL) or _("Effacer")))

        # Kept in memory for the Notifications tab; shown on the desktop only if wanted.
        seen = getattr(self.hooks, "notification_seen", None)
        if seen and not seen(uid, app_id, app_name, title, body, category, dict(actions)):
            log(f"notification {uid} non affichée (app masquée)")
            return

        hints = {}
        if category in (CATEGORY_INCOMING_CALL, CATEGORY_MISSED_CALL) or flags & FLAG_IMPORTANT:
            hints["urgency"] = GLib.Variant("y", 2)
        play = getattr(self.hooks, "play_sound", None)
        if play:
            # The sound chosen in Réglages, played by the daemon (none for a silent one).
            if not flags & (FLAG_SILENT | FLAG_PREEXISTING) and category != CATEGORY_INCOMING_CALL:
                play("notifications")
            hints["suppress-sound"] = GLib.Variant("b", True)
        elif flags & FLAG_SILENT:
            hints["suppress-sound"] = GLib.Variant("b", True)
        if category in CATEGORY_HINTS:
            hints["category"] = GLib.Variant("s", CATEGORY_HINTS[category])

        icon = "phone"
        find_icon = getattr(self.hooks, "notification_icon", None)
        if find_icon:
            themed, image = find_icon(app_id)
            pixels = appicons.image_data(image) if image else None
            if pixels is not None:
                hints["image-data"] = pixels
            icon = themed or icon
        self.desktop_ids[uid] = self.notifier.notify(
            # The iPhone app's own name: the notification centre groups and titles by it.
            app_name or f"Covalence ({self.device_name})", icon, summary, body, actions, hints,
            replaces=self.desktop_ids.get(uid, 0),
            on_action=(lambda key, u=uid: self.perform_action(u, key)) if actions else None,
        )
        log(f"notification {uid} affichée")

    def perform_action(self, uid, key):
        action = {"positive": ACTION_POSITIVE, "negative": ACTION_NEGATIVE}.get(key)
        if action is None:
            return
        log(f"notification {uid} : action {'positive' if action == 0 else 'négative'} envoyée")
        self.write(CONTROL_POINT, struct.pack("<BIB", CMD_PERFORM_NOTIFICATION_ACTION, uid, action))
