#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Stand-in for covalenced with made-up data, for screenshots and demos.

It serves the real D-Bus interface (covalenced.service.XML) under another bus
name, so it never touches Bluetooth, iCloud or the user's messages:

    python3 tools/demo_daemon.py &
    COVALENCE_DAEMON_NAME=io.github.melvincouwez.Covalence.Demo \\
        COVALENCE_SNAPSHOT=/tmp/shot.png build/src/io.github.melvincouwez.Covalence --page messages

Everything shown (people, numbers, messages, notifications) is fictitious.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from gi.repository import Gio, GLib  # noqa: E402

from covalenced import service  # noqa: E402
from covalenced.headphones import features_for  # noqa: E402
from covalenced.util import APP_ID  # noqa: E402

# COVALENCE_DEMO_BUS picks another name, so that two demo runs never collide.
DEMO_NAME = os.environ.get("COVALENCE_DEMO_BUS", "io.github.melvincouwez.Covalence.Demo")
ARTWORK = ""
NOW = int(time.time())
MIN, HOUR, DAY = 60, 3600, 86400

PROPS = {
    "Version": "0.6.0", "BluetoothAvailable": True, "Advertising": True, "Pairing": False, "LinkProblem": "", "AdapterName": "Covalence-PC",
    "DeviceName": "iPhone de Camille", "DeviceAddress": "00:11:22:33:44:55", "Paired": True,
    "Connected": True, "NotificationsLinked": True, "MediaLinked": True, "CallsLinked": True,
    "CallsSupported": True, "Battery": 78, "ICloudState": "connected", "MessagesState": "ready",
    "MessagesSend": "yes", "ReactionsSend": True, "ContactsState": "ready", "AudioOnPC": True, "MicMuted": False,
    "PhoneAudio": "idle", "PhoneAudioOutput": "", "ContactsSource": "bluetooth",
    "ContactsBook": "", "UnreadMessages": 2, "MissedCalls": 1,
    "Modules": {m: True for m in ("notifications", "media", "calls", "battery", "messages",
                                  "icloud")},
}

# Demo data in the language of the screenshot (COVALENCE_DEMO_LANG, else LANGUAGE).
LANG = (os.environ.get("COVALENCE_DEMO_LANG") or os.environ.get("LANGUAGE") or "fr")[:2]
EN = LANG == "en"

PEOPLE = [
    ("Alice Martin", "+33600000001"), ("Bob Leroy", "+33600000002"),
    ("Mum" if EN else "Maman", "+33600000003"), ("Chloé Bernard", "+33600000004"),
    ("David Petit", "+33600000005"), ("Emma Robert", "+33600000006"),
    ("Hugo Richard", "+33600000007"), ("Léa Dubois", "+33600000008"),
]

if EN:
    PROPS["DeviceName"] = "Camille's iPhone"
    THREADS = {
        "t1": ("Mum", "+33600000003", [
            (False, "Hi! Are you coming for lunch on Sunday?", 3 * HOUR),
            (True, "Yes, I'll be there around half past twelve 🙂", 3 * HOUR - 5 * MIN),
            (False, "Perfect, I'm making lasagne.", 2 * HOUR),
            (False, "Don't forget the bread!", 20 * MIN),
        ], 1),
        "t2": ("Alice Martin", "+33600000001", [
            (False, "The meeting has moved to 3 pm.", DAY + 2 * HOUR),
            (True, "Thanks, noted.", DAY + HOUR),
            (False, "I'll send you the minutes tonight.", 45 * MIN),
        ], 1),
        "t3": ("Bob Leroy", "+33600000002", [
            (True, "Cinema at 8 pm?", 2 * DAY),
            (False, "Sure, I'll book the seats.", 2 * DAY - 10 * MIN),
        ], 0),
        "t4": ("Chloé Bernard", "+33600000004", [
            (False, "Your parcel arrived at my place 📦", 4 * DAY),
        ], 0),
    }
    NOTIFICATIONS = [
        (1, "com.example.chatter", "Chatter", "Bob Leroy", "Weekend photo 📷", 4 * MIN,
         "internet-chat"),
        (2, "com.apple.mobilemail", "Mail", "Club newsletter", "This season's programme", 18 * MIN,
         "io.elementary.mail"),
        (3, "com.apple.mobilecal", "Calendar", "Dentist", "Tomorrow at 9:30", HOUR,
         "io.github.melvincouwez.Covalence.Calendar"),
        (4, "com.apple.reminders", "Reminders", "Water the plants", "", 2 * HOUR,
         "io.elementary.tasks"),
    ]
else:
    THREADS = {
        "t1": ("Maman", "+33600000003", [
            (False, "Coucou ! Tu passes dimanche midi ?", 3 * HOUR),
            (True, "Oui, j'arrive vers midi et demi 🙂", 3 * HOUR - 5 * MIN),
            (False, "Parfait, je fais des lasagnes.", 2 * HOUR),
            (False, "N'oublie pas le pain !", 20 * MIN),
        ], 1),
        "t2": ("Alice Martin", "+33600000001", [
            (False, "La réunion est déplacée à 15 h.", DAY + 2 * HOUR),
            (True, "Merci, c'est noté.", DAY + HOUR),
            (False, "Je t'envoie le compte rendu ce soir.", 45 * MIN),
        ], 1),
        "t3": ("Bob Leroy", "+33600000002", [
            (True, "On se retrouve au cinéma à 20 h ?", 2 * DAY),
            (False, "Carrément, je prends les places.", 2 * DAY - 10 * MIN),
        ], 0),
        "t4": ("Chloé Bernard", "+33600000004", [
            (False, "Ton colis est arrivé chez moi 📦", 4 * DAY),
        ], 0),
    }
    NOTIFICATIONS = [
        (1, "com.example.chatter", "Bavard", "Bob Leroy", "Photo du week-end 📷", 4 * MIN,
         "internet-chat"),
        (2, "com.apple.mobilemail", "Mail", "Newsletter du club", "Programme de la saison", 18 * MIN,
         "io.elementary.mail"),
        (3, "com.apple.mobilecal", "Calendrier", "Dentiste", "Demain à 9:30", HOUR,
         "io.github.melvincouwez.Covalence.Calendar"),
        (4, "com.apple.reminders", "Rappels", "Arroser les plantes", "", 2 * HOUR,
         "io.elementary.tasks"),
    ]


def demo_artwork():
    """A made-up cover (soft gradient with a sun), drawn here: no real album art."""
    import math
    import tempfile
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    size = 300
    pixels = bytearray(size * size * 3)
    for y in range(size):
        for x in range(size):
            t = y / size
            r, g, b = 255 - 90 * t, 140 + 40 * t, 90 + 140 * t
            d = math.hypot(x - 190, y - 120)
            if d < 55:
                r, g, b = 255, 225, 140
            elif y > 210 + 12 * math.sin(x / 25):
                r, g, b = 60 + 20 * t, 50, 110
            i = (y * size + x) * 3
            pixels[i:i + 3] = bytes((int(r), int(g), int(b)))
    pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(pixels)),
                                             GdkPixbuf.Colorspace.RGB, False, 8, size, size,
                                             size * 3)
    path = os.path.join(tempfile.mkdtemp(prefix="covalence-demo-"), "cover.png")
    pixbuf.savev(path, "png", [], [])
    return path


def now_playing():
    if os.environ.get("COVALENCE_DEMO_NOWPLAYING") == "0":
        return {"source": "avrcp-control", "status": "stopped", "volume": -1.0,
                "can_play": True}
    return {"source": "ams", "app": "Music" if EN else "Musique", "app_icon": "io.github.melvincouwez.Covalence.NowPlaying", "app_image": "",
            "title": "October Light" if EN else "Lumière d'octobre",
            "artist": "The Evening Travellers" if EN else "Les Voyageurs du Soir",
            "album": "Horizons", "duration": 214.0, "position": 83.0,
            "position_time": time.time(), "rate": 1.0, "status": "playing", "volume": 0.6,
            "can_volume": True, "artwork": ARTWORK, "can_play": True,
            "commands": ["play", "pause", "toggle", "next", "previous", "volume-up",
                         "volume-down"]}


def v(sig, value):
    return GLib.Variant(sig, value)


def dicts(items, types):
    return service._dicts(items, types)


def threads():
    out = []
    for tid, (name, number, msgs, unread) in THREADS.items():
        last = msgs[-1]
        out.append({"id": tid, "name": name, "snippet": last[1], "time": NOW - last[2],
                    "unread": unread, "group": False, "outgoing": last[0], "can_send": True,
                    "participants": [number], "avatar": "", "draft": ""})
    return sorted(out, key=lambda t: -t["time"])


# Made-up reactions: (thread, message index) -> [(emoji, author, mine, pending)]
REACTIONS = {
    ("t1", 1): [("❤️", "Maman", False, False)],
    ("t1", 2): [("😂", "Moi", True, False)],
    ("t3", 0): [("👍", "Bob Leroy", False, False)],
    ("t2", 0): [("‼️", "Moi", True, True)],
}


def messages(tid):
    name, number, msgs, _ = THREADS.get(tid, ("", "", [], 0))
    return [{"id": f"{tid}-{i}", "outgoing": out, "sender": "" if out else name,
             "address": "" if out else number, "time": NOW - ago, "body": body,
             "complete": True, "source": "map", "status": "sent" if out else "", "avatar": "",
             "reactions": REACTIONS.get((tid, i), [])}
            for i, (out, body, ago) in enumerate(msgs)]


def contacts():
    return [{"name": n, "addresses": [a], "photo": "", "uid": f"c{i}"}
            for i, (n, a) in enumerate(PEOPLE)]


def calls():
    kinds = ["received", "missed", "dialed", "received", "dialed", "received"]
    return [{"address": PEOPLE[i][1], "name": PEOPLE[i][0], "time": NOW - (i + 1) * 5 * HOUR,
             "kind": kinds[i], "avatar": ""} for i in range(len(kinds))]


def notifications():
    return [{"uid": uid, "app": app, "app_name": name, "title": title, "body": body,
             "time": NOW - ago, "category": 0, "icon": icon, "image": ""}
            for uid, app, name, title, body, ago, icon in NOTIFICATIONS]


def notification_apps():
    return [{"id": app, "name": name, "enabled": True, "count": 1, "icon": icon, "image": ""}
            for _, app, name, _, _, _, icon in NOTIFICATIONS]


def headphones():
    return [{"address": "00:11:22:33:44:66", "name": "Camille's AirPods Pro" if EN else "AirPods Pro de Camille",
             "model": "AirPods Pro 2", "firmware": "7A305", "connected": True, "linked": True,
             "left": 85, "right": 80, "case": 60, "left_charging": False,
             "right_charging": False, "case_charging": True, "ear_left": "in", "ear_right": "in",
             "mode": 4, "cycle": 6, "conversation": 1, "adaptive": 50, "one_bud": 1,
             "features": sorted(features_for("AirPods Pro 2")), "auto_pause": True}]


REPLIES = {
    "ListThreads": lambda _: v("(aa{sv})", (dicts(threads(), service.THREAD_TYPES),)),
    "GetMessages": lambda p: v("(aa{sv})", (dicts(messages(p.unpack()[0]),
                                                   service.MESSAGE_TYPES),)),
    "SearchThreads": lambda _: v("(as)", ([],)),
    "ListContacts": lambda _: v("(aa{sv})", (dicts(contacts(), service.CONTACT_TYPES),)),
    "ListCalls": lambda _: v("(aa{sv})", (dicts(calls(), service.CALL_TYPES),)),
    "ListActiveCalls": lambda _: v("(aa{sv})", ([],)),
    "ListNotifications": lambda _: v("(aa{sv})", (dicts(notifications(),
                                                         service.NOTIFICATION_TYPES),)),
    "ListNotificationApps": lambda _: v("(aa{sv})", (dicts(notification_apps(),
                                                            service.APP_TYPES),)),
    "ListHeadphones": lambda _: v("(aa{sv})", (dicts(headphones(),
                                                      service.HEADPHONES_TYPES),)),
    "ListAudioOutputs": lambda _: v("(aa{sv})", (dicts(
        [{"name": "speakers", "description": "Speakers" if EN else "Haut-parleurs",
          "default": True}],
        service.OUTPUT_TYPES),)),
    "OpenConversation": lambda _: v("(a{sv})", ({},)),
    "GetContact": lambda _: v("(a{sv})", ({},)),
    "SaveContact": lambda _: v("(s)", ("",)),
    "MediaCommand": lambda _: v("(b)", (True,)),
}


def on_method(_conn, _sender, _path, _iface, method, params, invocation):
    reply = REPLIES.get(method)
    invocation.return_value(reply(params) if reply else None)


def on_get(_conn, _sender, _path, _iface, name):
    if name == "NowPlaying":
        return service._variant(name, now_playing())
    return v(service.SIGNATURES[name], PROPS[name])


def main():
    global ARTWORK
    ARTWORK = demo_artwork()
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    info = Gio.DBusNodeInfo.new_for_xml(service.XML).interfaces[0]
    bus.register_object(service.PATH, info, on_method, on_get, None)
    loop = GLib.MainLoop()
    Gio.bus_own_name_on_connection(bus, DEMO_NAME, Gio.BusNameOwnerFlags.NONE, None,
                                   lambda *_: (print(f"lost {DEMO_NAME}", flush=True),
                                               loop.quit()))
    print(f"demo daemon on {DEMO_NAME} (app id {APP_ID})", flush=True)
    loop.run()


if __name__ == "__main__":
    main()
