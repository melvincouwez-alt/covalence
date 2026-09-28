# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""iCloud Drive in Files' sidebar: state rules, and the D-Bus export on a private bus."""

import unittest

from gi.repository import Gio, GLib

from covalenced import cloudprovider as cp


class StatusTest(unittest.TestCase):
    def test_not_set_up(self):
        self.assertIsNone(cp.status_of("inactive", "disabled", False, None))
        self.assertIsNone(cp.status_of("", "", False, None))

    def test_idle_when_nothing_waits(self):
        stats = {"diskCache": {"uploadsInProgress": 0, "uploadsQueued": 0, "erroredFiles": 0}}
        self.assertEqual(cp.status_of("active", "enabled", True, stats)[0], cp.IDLE)
        self.assertEqual(cp.status_of("active", "enabled", True, None)[0], cp.IDLE)

    def test_syncing_while_uploading(self):
        stats = {"diskCache": {"uploadsInProgress": 1, "uploadsQueued": 2}}
        status, details = cp.status_of("active", "enabled", True, stats)
        self.assertEqual(status, cp.SYNCING)
        self.assertIn("3", details)

    def test_errors_win(self):
        stats = {"diskCache": {"uploadsInProgress": 1, "erroredFiles": 2}}
        self.assertEqual(cp.status_of("active", "enabled", True, stats)[0], cp.ERROR)
        self.assertEqual(cp.status_of("failed", "enabled", False, None)[0], cp.ERROR)

    def test_connecting(self):
        self.assertEqual(cp.status_of("activating", "enabled", False, None)[0], cp.SYNCING)
        self.assertEqual(cp.status_of("active", "enabled", False, None)[0], cp.SYNCING)

    def test_enabled_but_stopped_is_an_error(self):
        self.assertEqual(cp.status_of("inactive", "enabled", False, None)[0], cp.ERROR)


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.dbus = Gio.TestDBus.new(Gio.TestDBusFlags.NONE)
        self.dbus.up()
        flags = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | \
            Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
        self.bus = Gio.DBusConnection.new_for_address_sync(self.dbus.get_bus_address(), flags,
                                                           None, None)
        self.client = Gio.DBusConnection.new_for_address_sync(self.dbus.get_bus_address(), flags,
                                                              None, None)
        self.provider = cp.DriveProvider(self.bus, read_stats=lambda: None)
        self.provider.start()
        GLib.source_remove(self.provider.timer)  # no systemd on the test bus
        self.provider.timer = 0

    def tearDown(self):
        self.provider.stop()
        self.client.close_sync(None)
        self.bus.close_sync(None)
        self.dbus.down()

    def call(self, path, iface, method, args=None):
        """Call the provider from another connection while its main context turns."""
        loop = GLib.MainLoop()
        box = {}

        def done(conn, result):
            box["value"] = conn.call_finish(result).unpack()[0]
            loop.quit()

        self.client.call(self.bus.get_unique_name(), path, iface, method, args, None,
                         Gio.DBusCallFlags.NONE, 2000, None, done)
        loop.run()
        return box["value"]

    def managed(self):
        return self.call(cp.ROOT, cp.MANAGER_IFACE, "GetManagedObjects")

    def test_account_appears_and_goes(self):
        self.assertEqual(list(self.managed()), [cp.PROVIDER])
        self.provider._set_account({"Name": "iCloud Drive", "Path": "/tmp/iCloud Drive",
                                    "Icon": cp.ICON, "Status": cp.IDLE, "StatusDetails": "À jour"})
        objects = self.managed()
        account = objects[cp.ACCOUNT][cp.ACCOUNT_IFACE]
        self.assertEqual(account["Name"], "iCloud Drive")
        self.assertEqual(account["Status"], cp.IDLE)
        name = self.call(cp.PROVIDER, "org.freedesktop.DBus.Properties", "Get",
                         GLib.Variant("(ss)", (cp.PROVIDER_IFACE, "Name")))
        self.assertEqual(name, "Covalence")
        self.provider._set_account(None)
        self.assertEqual(list(self.managed()), [cp.PROVIDER])

    def test_menu_is_exported(self):
        self.provider._set_account({"Name": "iCloud Drive", "Path": "/tmp/x", "Icon": cp.ICON,
                                    "Status": cp.SYNCING, "StatusDetails": ""})
        actions = self.call(cp.ACCOUNT, "org.gtk.Actions", "List")
        self.assertEqual(sorted(actions), ["disconnect", "open", "options"])


if __name__ == "__main__":
    unittest.main()
