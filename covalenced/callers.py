# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Who is calling the daemon's session bus API.

Every program of the user's session can reach io.github.melvincouwez.Covalence1,
Flatpak apps with a broad bus access included. Reading state is harmless; acting
on the user's behalf is not: dialling a number, sending a text or files, pairing
a new device, installing an update, typing on the iPhone. Those actions run at
once only for the Covalence app itself; any other program gets a desktop
notification asking the user first (see service.GUARDED), or a plain refusal for
actions that make no sense outside the app (typing on the iPhone).

The app is recognised by the executable of the calling process
(/proc/<pid>/exe, which a program cannot fake by renaming itself): a Covalence
binary installed by the package (owned by root), or one next to this daemon
(meson install in ~/.local). A process of the same user could still start the
real app with its own arguments; the app only acts on explicit clicks, so that
is out of scope here.
"""

import os

from gi.repository import GLib

from .i18n import _
from .util import call_sync, log

APP_BINARY = "io.github.melvincouwez.Covalence"
BUS_DAEMON = ("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus")


def _own_prefix():
    """Install prefix of this daemon (<prefix>/share/covalence/covalenced/…), or None."""
    here = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
    parts = here.split(os.sep)
    if len(parts) >= 4 and parts[-3:-1] == ["share", "covalence"]:
        return os.sep.join(parts[:-3])
    return None


def is_app_executable(exe, prefix=None):
    """True for a Covalence app binary we trust (see the module comment)."""
    if not exe or not os.path.basename(exe).startswith(APP_BINARY):
        return False
    if exe.endswith(" (deleted)"):
        return False  # replaced on disk since it started: not the file we would check
    try:
        info = os.stat(exe)
    except OSError:
        return False
    if info.st_uid == 0 and not info.st_mode & 0o022:
        return True  # installed by the package
    prefix = prefix if prefix is not None else _own_prefix()
    return bool(prefix) and os.path.dirname(exe) == os.path.join(prefix, "bin")


class Callers:
    def __init__(self, bus):
        self.bus = bus
        self.cache = {}  # unique bus name -> (trusted, program name); names are never reused

    def describe(self, sender):
        """(trusted, program) for a unique bus name."""
        if sender in self.cache:
            return self.cache[sender]
        result = (False, _("un programme inconnu"))
        try:
            pid = call_sync(self.bus, *BUS_DAEMON, "GetConnectionUnixProcessID",
                            GLib.Variant("(s)", (sender,)), "(u)").unpack()[0]
            exe = os.readlink(f"/proc/{pid}/exe")
            result = (is_app_executable(exe), os.path.basename(exe).replace(" (deleted)", ""))
        except (GLib.Error, OSError) as error:
            log(f"appelant non identifié ({getattr(error, 'message', error)})")
        if len(self.cache) > 512:
            self.cache.clear()
        self.cache[sender] = result
        return result

    def trusted(self, sender):
        return self.describe(sender)[0]
