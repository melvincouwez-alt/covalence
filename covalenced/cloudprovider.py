# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""iCloud Drive in Files' sidebar, with its sync state (libcloudproviders).

Files (io.elementary.files) has a cloud providers plugin: it reads
cloud-providers/*.ini in the data dirs, then asks the named bus for accounts.
The daemon exports, in the layout of libcloudproviders 0.4 (the provider is an
object of the manager, as its own exporter does):
- org.freedesktop.DBus.ObjectManager on ROOT, listing PROVIDER and the account;
- org.freedesktop.CloudProviders.Provider on PROVIDER (Name), always;
- org.freedesktop.CloudProviders.Account on ACCOUNT (Name, Path, Icon, Status,
  StatusDetails), with its menu (org.gtk.Menus) and actions (org.gtk.Actions,
  prefix "cloudprovider" on the client side).

The state comes from the covalence-icloud-drive unit (systemd) and from
rclone's own counters (vfs/stats on the mount's private rc socket, in the
user's runtime dir): files waiting to go up mean "syncing", files that could
not be sent mean "error". Nothing is ever changed through that socket.
"""

import http.client
import json
import os
import socket
import threading

from gi.repository import Gio, GLib

from .i18n import _, ngettext
from .util import log

BUS_NAME = "io.github.melvincouwez.Covalence.Daemon"
ROOT = "/io/github/melvincouwez/Covalence/CloudProviders"
PROVIDER = ROOT + "/Provider"
ACCOUNT = ROOT + "/drive"
UNIT = "covalence-icloud-drive.service"
RC_SOCKET = os.path.join(GLib.get_user_runtime_dir(), "covalence", "drive-rc.sock")
DRIVE_ENV = os.path.join(GLib.get_user_config_dir(), "covalence", "drive.env")
APP = "io.github.melvincouwez.Covalence"
ICON = "folder-remote"

# CloudProvidersAccountStatus
INVALID, IDLE, SYNCING, ERROR = 0, 1, 2, 3

POLL_ACTIVE = 5     # seconds, while the mount runs
POLL_IDLE = 30      # seconds, otherwise

XML = """
<node>
  <interface name="org.freedesktop.CloudProviders.Provider">
    <property type="s" name="Name" access="read"/>
  </interface>
  <interface name="org.freedesktop.DBus.ObjectManager">
    <method name="GetManagedObjects">
      <arg type="a{oa{sa{sv}}}" name="objects" direction="out"/>
    </method>
    <signal name="InterfacesAdded">
      <arg type="o" name="object"/>
      <arg type="a{sa{sv}}" name="interfaces"/>
    </signal>
    <signal name="InterfacesRemoved">
      <arg type="o" name="object"/>
      <arg type="as" name="interfaces"/>
    </signal>
  </interface>
  <interface name="org.freedesktop.CloudProviders.Account">
    <property type="s" name="Name" access="read"/>
    <property type="s" name="Path" access="read"/>
    <property type="s" name="Icon" access="read"/>
    <property type="i" name="Status" access="read"/>
    <property type="s" name="StatusDetails" access="read"/>
  </interface>
</node>
"""
PROVIDER_IFACE = "org.freedesktop.CloudProviders.Provider"
MANAGER_IFACE = "org.freedesktop.DBus.ObjectManager"
ACCOUNT_IFACE = "org.freedesktop.CloudProviders.Account"
TYPES = {"Name": "s", "Path": "s", "Icon": "s", "Status": "i", "StatusDetails": "s"}


def drive_folder():
    """The mount point chosen in the iCloud Drive options, else the unit's default."""
    try:
        with open(DRIVE_ENV, encoding="utf-8") as f:
            for line in f:
                if line.startswith("COVALENCE_DRIVE_DIR="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return os.path.join(os.path.expanduser("~"), "iCloud Drive")


def status_of(active_state, file_state, mounted, stats):
    """(status, details) for the account, or None when iCloud Drive is not set up."""
    if active_state in ("inactive", "") and file_state != "enabled":
        return None
    if active_state == "failed":
        return ERROR, _("Connexion à iCloud Drive impossible")
    if active_state in ("activating", "reloading") or (active_state == "active" and not mounted):
        return SYNCING, _("Connexion à iCloud Drive…")
    if active_state != "active":
        return ERROR, _("iCloud Drive n'est pas monté")
    cache = (stats or {}).get("diskCache") or {}
    waiting = int(cache.get("uploadsInProgress") or 0) + int(cache.get("uploadsQueued") or 0)
    failed = int(cache.get("erroredFiles") or 0)
    if failed:
        return ERROR, ngettext("{n} fichier non envoyé", "{n} fichiers non envoyés",
                               failed).format(n=failed)
    if waiting:
        return SYNCING, ngettext("Envoi de {n} fichier…", "Envoi de {n} fichiers…",
                                 waiting).format(n=waiting)
    return IDLE, _("À jour")


def rc_stats(path=RC_SOCKET, timeout=2):
    """rclone's VFS counters, read on the mount's private socket; None if unavailable."""
    if not os.path.exists(path):
        return None
    try:
        conn = http.client.HTTPConnection("localhost", timeout=timeout)
        conn.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.sock.settimeout(timeout)
        conn.sock.connect(path)
        conn.request("POST", "/vfs/stats", "{}", {"Content-Type": "application/json"})
        response = conn.getresponse()
        data = json.loads(response.read() or b"{}")
        conn.close()
        return data if response.status == 200 else None
    except (OSError, ValueError, http.client.HTTPException):
        return None


class DriveProvider:
    def __init__(self, bus, read_stats=rc_stats):
        self.bus = bus
        self.read_stats = read_stats
        self.info = Gio.DBusNodeInfo.new_for_xml(XML)
        self.registrations = []
        self.account = None          # dict of account properties while exported
        self.account_regs = []
        self.menu_id = self.actions_id = 0
        self.timer = 0
        self.busy = False

    # --- lifecycle -------------------------------------------------------------------------

    def start(self):
        if self.registrations:
            return
        self.registrations.append(self.bus.register_object(
            ROOT, self.info.lookup_interface(MANAGER_IFACE), self._call, self._get, None))
        self.registrations.append(self.bus.register_object(
            PROVIDER, self.info.lookup_interface(PROVIDER_IFACE), self._call, self._get, None))
        self._schedule(1)

    def stop(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        self._set_account(None)
        for reg in self.registrations:
            self.bus.unregister_object(reg)
        self.registrations = []

    # --- D-Bus ------------------------------------------------------------------------------

    def _get(self, _conn, _sender, path, iface, name):
        if iface == PROVIDER_IFACE and name == "Name":
            return GLib.Variant("s", "Covalence")
        if iface == ACCOUNT_IFACE and self.account and name in TYPES:
            return GLib.Variant(TYPES[name], self.account[name])
        return None

    def _call(self, _conn, _sender, _path, _iface, method, _params, invocation):
        if method == "GetManagedObjects":
            objects = {PROVIDER: {PROVIDER_IFACE: {"Name": GLib.Variant("s", "Covalence")}}}
            if self.account:
                objects[ACCOUNT] = {ACCOUNT_IFACE: self._props()}
            invocation.return_value(GLib.Variant("(a{oa{sa{sv}}})", (objects,)))
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    def _props(self, names=None):
        return {k: GLib.Variant(TYPES[k], v) for k, v in self.account.items()
                if names is None or k in names}

    def _set_account(self, props):
        if props is None:
            if self.account is None:
                return
            self.account = None
            self._unexport_account()
            self.bus.emit_signal(None, ROOT, MANAGER_IFACE, "InterfacesRemoved",
                                 GLib.Variant("(oas)", (ACCOUNT, [ACCOUNT_IFACE])))
            log("iCloud Drive : retiré de la barre latérale de Fichiers")
            return
        if self.account is None:
            self.account = dict(props)
            self._export_account()
            self.bus.emit_signal(None, ROOT, MANAGER_IFACE, "InterfacesAdded",
                                 GLib.Variant("(oa{sa{sv}})", (ACCOUNT, {ACCOUNT_IFACE: self._props()})))
            log("iCloud Drive : affiché dans la barre latérale de Fichiers")
            return
        changed = [k for k, v in props.items() if self.account.get(k) != v]
        if not changed:
            return
        self.account.update(props)
        self.bus.emit_signal(None, ACCOUNT, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                             GLib.Variant("(sa{sv}as)", (ACCOUNT_IFACE, self._props(changed), [])))

    def _export_account(self):
        self.account_regs.append(self.bus.register_object(
            ACCOUNT, self.info.lookup_interface(ACCOUNT_IFACE), self._call, self._get, None))
        menu = Gio.Menu()
        menu.append(_("Ouvrir"), "cloudprovider.open")
        menu.append(_("Options d'iCloud Drive…"), "cloudprovider.options")
        menu.append(_("Déconnecter…"), "cloudprovider.disconnect")
        group = Gio.SimpleActionGroup()
        for name, handler in (("open", self._open), ("options", self._manage),
                              ("disconnect", self._manage)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            group.add_action(action)
        try:
            self.menu_id = self.bus.export_menu_model(ACCOUNT, menu)
            self.actions_id = self.bus.export_action_group(ACCOUNT, group)
        except GLib.Error as error:
            log(f"iCloud Drive : menu de Fichiers non exporté ({error.message})")

    def _unexport_account(self):
        if self.menu_id:
            self.bus.unexport_menu_model(self.menu_id)
            self.menu_id = 0
        if self.actions_id:
            self.bus.unexport_action_group(self.actions_id)
            self.actions_id = 0
        for reg in self.account_regs:
            self.bus.unregister_object(reg)
        self.account_regs = []

    # --- menu actions -------------------------------------------------------------------------

    def _open(self, _action, _param):
        folder = self.account["Path"] if self.account else drive_folder()
        Gio.AppInfo.launch_default_for_uri_async(Gio.File.new_for_path(folder).get_uri(),
                                                 None, None, None, None)

    def _manage(self, _action, _param):
        # Options and disconnection are asked and confirmed in Covalence itself.
        try:
            Gio.Subprocess.new([APP, "--page", "services"], Gio.SubprocessFlags.NONE)
        except GLib.Error as error:
            log(f"iCloud Drive : Covalence non lancée ({error.message})")

    # --- state ------------------------------------------------------------------------------------

    def _schedule(self, seconds):
        if self.timer:
            GLib.source_remove(self.timer)
        self.timer = GLib.timeout_add_seconds(seconds, self._poll)

    def _poll(self):
        self.timer = 0
        if self.busy:
            self._schedule(POLL_IDLE)
            return False
        self.busy = True
        self.bus.call("org.freedesktop.systemd1", "/org/freedesktop/systemd1",
                      "org.freedesktop.systemd1.Manager", "LoadUnit", GLib.Variant("(s)", (UNIT,)),
                      GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, 3000, None, self._on_unit)
        return False

    def _on_unit(self, bus, result):
        try:
            path = bus.call_finish(result).unpack()[0]
        except GLib.Error:
            return self._update("", "", None)
        bus.call("org.freedesktop.systemd1", path, "org.freedesktop.DBus.Properties", "GetAll",
                 GLib.Variant("(s)", ("org.freedesktop.systemd1.Unit",)),
                 GLib.VariantType("(a{sv})"), Gio.DBusCallFlags.NONE, 3000, None, self._on_props)

    def _on_props(self, bus, result):
        try:
            props = bus.call_finish(result).unpack()[0]
        except GLib.Error:
            return self._update("", "", None)
        if props.get("LoadState") != "loaded":
            return self._update("", "", None)
        active, file_state = props.get("ActiveState", ""), props.get("UnitFileState", "")
        if active != "active":
            return self._update(active, file_state, None)
        read_stats = self.read_stats

        def job():
            stats = read_stats()
            GLib.idle_add(lambda: self._update(active, file_state, stats) and False)

        threading.Thread(target=job, name="covalence-drive-stats", daemon=True).start()

    def _update(self, active, file_state, stats):
        self.busy = False
        folder = drive_folder()
        state = status_of(active, file_state, os.path.ismount(folder), stats)
        if state is None:
            self._set_account(None)
        else:
            status, details = state
            self._set_account({"Name": "iCloud Drive", "Path": folder, "Icon": ICON,
                               "Status": status, "StatusDetails": details})
        self._schedule(POLL_ACTIVE if active == "active" else POLL_IDLE)
        return False
