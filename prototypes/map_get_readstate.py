#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Does downloading a message over MAP mark it read on the iPhone?

Run by the user only, on a message they chose (for instance one they sent
themselves from another device): the test may mark that message read.
It prints handles, dates, read flags and lengths, never text or numbers.

    systemctl --user stop covalenced
    ~/.local/libexec/covalence/obexd -n -p bluetooth,mns &   # unless bluez-obexd is installed
    export COVALENCE_PHONE=XX:XX:XX:XX:XX:XX               # the iPhone Bluetooth address
    python3 prototypes/map_get_readstate.py                # list unread inbox handles
    python3 prototypes/map_get_readstate.py HANDLE --get   # download that one, compare Read
    systemctl --user start covalenced

If "Read" stays False after --get (and the message is still unread in Messages
on the iPhone), set fetch_unread=true in the [messages] group of
~/.config/covalence/covalenced.conf so that Covalence fetches the full text of long
unread messages.
"""

import os
import sys
import tempfile
import time

from gi.repository import Gio, GLib

ADDRESS = os.environ.get("COVALENCE_PHONE") or sys.exit("set COVALENCE_PHONE to the iPhone Bluetooth address (bluetoothctl devices)")
bus = Gio.bus_get_sync(Gio.BusType.SESSION)


def call(path, iface, method, args=None, reply=None):
    return bus.call_sync("org.bluez.obex", path, iface, method, args,
                         GLib.VariantType(reply) if reply else None,
                         Gio.DBusCallFlags.NONE, 60000, None).unpack()


def inbox(session):
    call(session, "org.bluez.obex.MessageAccess1", "SetFolder", GLib.Variant("(s)", ("/telecom/msg",)))
    return call(session, "org.bluez.obex.MessageAccess1", "ListMessages",
                GLib.Variant("(sa{sv})", ("inbox", {})), "(a{oa{sv}})")[0]


def main():
    handle = sys.argv[1] if len(sys.argv) > 1 else None
    session = call("/org/bluez/obex", "org.bluez.obex.Client1", "CreateSession",
                   GLib.Variant("(sa{sv})", (ADDRESS, {"Target": GLib.Variant("s", "map")})), "(o)")[0]
    try:
        listing = inbox(session)
        for path, props in sorted(listing.items(), key=lambda i: i[1].get("Timestamp", "")):
            h = path.rsplit("/message", 1)[-1]
            print(f"{h}  {props.get('Timestamp')}  read={props.get('Read')}  "
                  f"type={props.get('Type')}  size={props.get('Size')}  "
                  f"subject={len(props.get('Subject') or '')} chars")
        if not handle or "--get" not in sys.argv:
            return
        path = f"{session}/message{handle}"
        before = listing.get(path, {}).get("Read")
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, 0o700)
            target = os.path.join(tmp, "m.bmsg")
            call(path, "org.bluez.obex.Message1", "Get", GLib.Variant("(sb)", (target, False)),
                 "(oa{sv})")
            for _ in range(100):
                if os.path.exists(target) and os.path.getsize(target):
                    break
                time.sleep(0.1)
            time.sleep(1)
            print(f"downloaded: {os.path.getsize(target)} bytes")
        after = inbox(session).get(path, {}).get("Read")
        print(f"Read before: {before}  after: {after}")
    finally:
        call("/org/bluez/obex", "org.bluez.obex.Client1", "RemoveSession",
             GLib.Variant("(o)", (session,)))


main()
