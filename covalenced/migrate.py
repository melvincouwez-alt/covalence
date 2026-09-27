# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""One-time move from Tandem, the app's name until 2026-09-27, to Covalence.

Runs at every start of covalenced and does nothing once done: each step first
checks that there is something to move and that the new place is free. It never
logs content (paths only). Only files the old version created are touched, by
their exact names.

- ~/.config/tandem -> ~/.config/covalence (tandemd.conf -> covalenced.conf,
  apps.conf keys and ids, TANDEM_* names in drive.env and photos.env)
- ~/.local/share/tandem/{messages,contacts} -> ~/.local/share/covalence/
  (the old installed code in ~/.local/share/tandem/{tandemd,docs} is removed)
- ~/.local/libexec/tandem -> ~/.local/libexec/covalence (obexd, rclone)
- keyring: the rclone config key is copied under the new attributes, and the
  old item is cleared only once the new one reads back identical
- systemd user units: old units stopped and disabled, the new ones enabled in
  their place, old unit files removed
- launchers, icons, D-Bus activation and metainfo of the old ~/.local install
- GTK bookmarks pointing into the old folders (mount points do not move)

iCloud sources in Evolution Data Server keep their tandem-icloud-* uids (see
util.ICLOUD_UID_PREFIXES).
"""

import os
import re
import shutil
import subprocess

OLD_ID = "io.github.melvincouwez.Tandem"
NEW_ID = "io.github.melvincouwez.Covalence"
OLD_KEY = ["application", OLD_ID, "kind", "rclone-config"]
NEW_KEY = ["application", NEW_ID, "kind", "rclone-config"]
KEY_LABEL = "Covalence : clé de la configuration iCloud Drive"
# old unit -> new unit
UNITS = {"tandemd.service": "covalenced.service",
         "tandem-icloud-drive.service": "covalence-icloud-drive.service",
         "tandem-icloud-photos.service": "covalence-icloud-photos.service"}
SUFFIXES = ("", ".Messages", ".Contacts", ".Phone", ".Headphones")
OLD_BINARIES = ["tandemd", "tandem-icloud-signin", "tandem-icloud-drive", "tandem-rclone"] + \
               [OLD_ID + s for s in SUFFIXES]


def _run(args, stdin=None):
    try:
        return subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None


class Migration:
    def __init__(self, home=None, run=_run, log=print):
        self.home = home or os.path.expanduser("~")
        self.run = run
        self.log = log
        self.config = os.environ.get("XDG_CONFIG_HOME") if home is None else None
        self.config = self.config or os.path.join(self.home, ".config")
        self.data = os.environ.get("XDG_DATA_HOME") if home is None else None
        self.data = self.data or os.path.join(self.home, ".local", "share")
        self.local = os.path.join(self.home, ".local")
        self.done = []

    def _p(self, *parts):
        return os.path.join(*parts)

    # --- folders ----------------------------------------------------------------------

    def _move(self, old, new):
        if os.path.exists(old) and not os.path.exists(new):
            os.makedirs(os.path.dirname(new), exist_ok=True)
            shutil.move(old, new)
            self.done.append(f"{old} -> {new}")
            return True
        return False

    def _rewrite(self, path, fixes):
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except (FileNotFoundError, UnicodeDecodeError):
            return
        new = text
        for old, repl in fixes:
            new = re.sub(old, repl, new)
        if new != text:
            mode = os.stat(path).st_mode & 0o777
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
            os.chmod(path, mode)
            self.done.append(f"réécrit {path}")

    def folders(self):
        old_conf, new_conf = self._p(self.config, "tandem"), self._p(self.config, "covalence")
        self._move(old_conf, new_conf)
        self._move(self._p(new_conf, "tandemd.conf"), self._p(new_conf, "covalenced.conf"))
        self._rewrite(self._p(new_conf, "apps.conf"),
                      [(r"\bTANDEM_MODE_", "COVALENCE_MODE_"), (re.escape(OLD_ID), NEW_ID)])
        for env in ("drive.env", "photos.env"):
            self._rewrite(self._p(new_conf, env),
                          [(r"(?m)^TANDEM_", "COVALENCE_"), (r"Written by Tandem", "Written by Covalence")])

        old_data, new_data = self._p(self.data, "tandem"), self._p(self.data, "covalence")
        for sub in ("messages", "contacts"):
            self._move(self._p(old_data, sub), self._p(new_data, sub))
        # Code and docs of the old ~/.local install (a system install lives in /usr).
        for sub in ("tandemd", "docs"):
            path = self._p(old_data, sub)
            if old_data.startswith(self.local) and os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
                self.done.append(f"supprimé {path}")
        try:
            os.rmdir(old_data)
        except OSError:
            pass

        self._move(self._p(self.local, "libexec", "tandem"),
                   self._p(self.local, "libexec", "covalence"))

    # --- keyring ----------------------------------------------------------------------

    def keyring(self):
        old = self.run(["secret-tool", "lookup", *OLD_KEY])
        if old is None or old.returncode != 0 or not old.stdout:
            return
        new = self.run(["secret-tool", "lookup", *NEW_KEY])
        if new is None or new.returncode != 0 or not new.stdout:
            self.run(["secret-tool", "store", "--label", KEY_LABEL, *NEW_KEY], stdin=old.stdout)
            new = self.run(["secret-tool", "lookup", *NEW_KEY])
        if new is not None and new.returncode == 0 and new.stdout == old.stdout:
            self.run(["secret-tool", "clear", *OLD_KEY])
            self.done.append("clé rclone du trousseau reprise")
        else:
            self.log("migration : clé rclone non recopiée, l'ancienne est gardée")

    # --- systemd user units --------------------------------------------------------------

    def units(self):
        dirs = [self._p(self.data, "systemd", "user"), self._p(self.config, "systemd", "user")]
        present = [u for u in UNITS if any(os.path.exists(self._p(d, u)) for d in dirs)]
        if not present:
            return
        states = {}
        for unit in present:
            enabled = self.run(["systemctl", "--user", "is-enabled", unit])
            active = self.run(["systemctl", "--user", "is-active", unit])
            states[unit] = (enabled is not None and enabled.stdout.strip() == "enabled",
                            active is not None and active.stdout.strip() == "active")
        # Stop the old ones first: the mounts use the same folders.
        for unit in present:
            self.run(["systemctl", "--user", "disable", "--now", unit])
        for d in dirs:
            for unit in present:
                path = self._p(d, unit)
                if os.path.isfile(path) or os.path.islink(path):
                    os.unlink(path)
                    self.done.append(f"supprimé {path}")
        self.run(["systemctl", "--user", "daemon-reload"])
        for unit in present:
            enabled, active = states[unit]
            new = UNITS[unit]
            if unit == "tandemd.service":
                # This process is covalenced itself: only make it start at login.
                if enabled:
                    self.run(["systemctl", "--user", "enable", new])
                continue
            if enabled:
                self.run(["systemctl", "--user", "enable", new])
            if active:
                self.run(["systemctl", "--user", "start", new])
            self.done.append(f"{unit} -> {new}")

    # --- old ~/.local install --------------------------------------------------------------

    def launchers(self):
        share = self._p(self.local, "share")
        paths = [self._p(self.local, "bin", b) for b in OLD_BINARIES]
        paths += [self._p(share, "applications", OLD_ID + s + ".desktop") for s in SUFFIXES]
        paths += [self._p(share, "icons", "hicolor", "scalable", "apps", OLD_ID + s + ".svg")
                  for s in SUFFIXES]
        paths += [self._p(share, "metainfo", OLD_ID + ".metainfo.xml"),
                  self._p(share, "dbus-1", "services", OLD_ID + ".Daemon.service")]
        removed = False
        for path in paths:
            if os.path.isfile(path) or os.path.islink(path):
                os.unlink(path)
                self.done.append(f"supprimé {path}")
                removed = True
        if removed:
            self.run(["update-desktop-database", self._p(share, "applications")])
            self.run(["gtk-update-icon-cache", "-q", "-t", "-f", self._p(share, "icons", "hicolor")])

    def bookmarks(self):
        path = self._p(self.config, "gtk-3.0", "bookmarks")
        self._rewrite(path, [(re.escape("file://" + self._p(self.data, "tandem")),
                              "file://" + self._p(self.data, "covalence")),
                             (re.escape("file://" + self._p(self.config, "tandem")),
                              "file://" + self._p(self.config, "covalence"))])

    def run_all(self):
        for step in (self.folders, self.keyring, self.units, self.launchers, self.bookmarks):
            try:
                step()
            except OSError as e:
                self.log(f"migration : étape {step.__name__} incomplète ({e.strerror})")
        if self.done:
            self.log(f"migration depuis Tandem : {len(self.done)} élément(s) repris")
        return self.done


def migrate(log=print):
    return Migration(log=log).run_all()
