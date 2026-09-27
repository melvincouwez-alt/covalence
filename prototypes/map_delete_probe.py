#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Does the iPhone honour a MAP delete (SetMessageStatus, deletedStatus)?

Only acts on a test message: its text must contain the marker "covalence-test".
Ask someone to send you an SMS containing it, or send one from another phone.
Prints handles, dates, read flags and whether the marker is present, never
text or numbers.

    export COVALENCE_PHONE=XX:XX:XX:XX:XX:XX                # the iPhone Bluetooth address
    python3 prototypes/map_delete_probe.py                  # list, show test handles
    python3 prototypes/map_delete_probe.py HANDLE --delete  # delete that test message

The iPhone accepts one MAP session only: when covalenced holds it, the probe
borrows covalenced's session instead of opening its own. After --delete, look in Messages
on the iPhone: gone from the conversation? in "Recently Deleted"?

Result (2026-09-27): the iPhone accepts the request and moves the message
to its MAP "deleted" folder, but it stays in the Messages app. Covalence
therefore deletes messages in Covalence only.
"""

import os
import sys

from gi.repository import Gio, GLib

ADDRESS = os.environ.get("COVALENCE_PHONE") or sys.exit("set COVALENCE_PHONE to the iPhone Bluetooth address (bluetoothctl devices)")
MARKER = "covalence-test"
MAP = "org.bluez.obex.MessageAccess1"
bus = Gio.bus_get_sync(Gio.BusType.SESSION)


def call(path, iface, method, args=None, reply=None):
    return bus.call_sync("org.bluez.obex", path, iface, method, args,
                         GLib.VariantType(reply) if reply else None,
                         Gio.DBusCallFlags.NONE, 60000, None).unpack()


def listing(session, folder):
    call(session, MAP, "SetFolder", GLib.Variant("(s)", ("/telecom/msg",)))
    return call(session, MAP, "ListMessages",
                GLib.Variant("(sa{sv})", (folder, {})), "(a{oa{sv}})")[0]


def show(session, folder):
    items = listing(session, folder)
    print(f"-- {folder}: {len(items)}")
    tests = {}
    for path, props in sorted(items.items(), key=lambda i: i[1].get("Timestamp", "")):
        handle = path.rsplit("/message", 1)[-1]
        test = MARKER in (props.get("Subject") or "").lower()
        if test:
            tests[handle] = path
        print(f"{handle}  {props.get('Timestamp')}  read={props.get('Read')}  "
              f"deleted={props.get('Deleted')}  {'TEST' if test else ''}")
    return tests


def borrowed_session():
    xml = call("/org/bluez/obex/client", "org.freedesktop.DBus.Introspectable",
               "Introspect", None, "(s)")[0]
    for node in Gio.DBusNodeInfo.new_for_xml(xml).nodes:
        path = f"/org/bluez/obex/client/{node.path}"
        props = call(path, "org.freedesktop.DBus.Properties", "GetAll",
                     GLib.Variant("(s)", ("org.bluez.obex.Session1",)), "(a{sv})")[0]
        if props.get("Destination") == ADDRESS and props.get("Target", "").lower().startswith("00001132"):
            return path
    sys.exit("no MAP session found")


def main():
    handle = sys.argv[1] if len(sys.argv) > 1 else None
    own = True
    try:
        session = call("/org/bluez/obex", "org.bluez.obex.Client1", "CreateSession",
                       GLib.Variant("(sa{sv})", (ADDRESS, {"Target": GLib.Variant("s", "map")})),
                       "(o)")[0]
    except GLib.Error:
        session, own = borrowed_session(), False
        print(f"borrowing {session}")
    try:
        tests = show(session, "inbox")
        show(session, "deleted")
        if not handle or "--delete" not in sys.argv:
            return
        if handle not in tests:
            sys.exit(f"{handle}: not a test message (text must contain '{MARKER}'), nothing done")
        try:
            bus.call_sync("org.bluez.obex", tests[handle], "org.freedesktop.DBus.Properties",
                          "Set", GLib.Variant("(ssv)", ("org.bluez.obex.Message1", "Deleted",
                                                        GLib.Variant("b", True))),
                          None, Gio.DBusCallFlags.NONE, 60000, None)
            print("SetMessageStatus deleted: accepted by the iPhone")
        except GLib.Error as e:
            print(f"SetMessageStatus deleted: refused ({e.message})")
        print("after:")
        show(session, "inbox")
        show(session, "deleted")
    finally:
        if own:
            call("/org/bluez/obex", "org.bluez.obex.Client1", "RemoveSession",
                 GLib.Variant("(o)", (session,)))


main()
