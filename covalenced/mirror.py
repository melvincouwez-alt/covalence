# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Recopie d'écran: the iPhone's screen on the PC through UxPlay (experimental).

UxPlay (https://github.com/FDH2/UxPlay, GPL-3.0) is a free AirPlay mirroring
receiver, packaged by Ubuntu as "uxplay". Covalence only starts and stops it,
on the user's request, under the name "Covalence (<computer>)"; the iPhone then
lists it in Control Centre › Screen Mirroring. It needs Avahi (mDNS) to be seen.
Nothing listens on the network while it is stopped. While it runs, AirPlay asks
for a 4-digit code (UxPlay -pin), drawn anew at each start and shown in the Recopie
app: another device on the network cannot put its own picture on the PC's screen.

The video stays in UxPlay's own window: UxPlay is a separate program, so its
GStreamer video sink cannot draw inside Covalence's GTK window (that would need
the frames sent between processes, e.g. shmsink/shmsrc, left for later). The
Recopie app is the control panel: start, stop, profile, rotation, full screen,
and the iPhone control pad.

Options ([mirror] in covalenced.conf):
- profile: "fluid" (default: no audio/video sync, lowest latency) or "quality"
  (audio kept in sync with the picture, a little more delay);
- rotation: "", "R" or "L"; fullscreen: true or false;
- screen: "WxH" of the PC's screen, sent by the app, asked of the iPhone (-s).
The H.264 decoder is chosen once: NVIDIA (nvh264dec, needs libcuda), then VA-API
(vah264dec, needs a render node), then software (libav). If UxPlay stops with an
error on a hardware decoder, it is restarted once in software.
"""

import glob
import os
import secrets
import shutil
import socket

from gi.repository import Gio, GLib

from .util import log

# GStreamer plugins UxPlay needs at start ("Required gstreamer plugin … not found"),
# by file name, with the package that provides them.
PLUGINS = {"libgstvideoparsersbad.so": "gstreamer1.0-plugins-bad",
           "libgstlibav.so": "gstreamer1.0-libav"}
LOG = os.path.join(GLib.get_user_cache_dir(), "covalence", "uxplay.log")
PROFILES = ("fluid", "quality")
ROTATIONS = ("", "R", "L")

TYPES = {"available": "b", "running": "b", "name": "s", "error": "s", "missing": "as",
         "profile": "s", "rotation": "s", "fullscreen": "b", "decoder": "s", "pin": "s"}


def _plugin_dirs():
    return glob.glob("/usr/lib/*/gstreamer-1.0") + glob.glob("/usr/lib/gstreamer-1.0")


def _has_plugin(name, dirs=None):
    return any(os.path.exists(os.path.join(d, name)) for d in (dirs or _plugin_dirs()))


def pick_decoder(dirs=None, cuda=None, render=None):
    """"nvidia", "vaapi" or "software", from what the system offers."""
    dirs = dirs if dirs is not None else _plugin_dirs()
    if cuda is None:
        cuda = bool(glob.glob("/usr/lib/*/libcuda.so.1") or glob.glob("/usr/lib/libcuda.so.1"))
    if render is None:
        render = bool(glob.glob("/dev/dri/renderD*"))
    if cuda and _has_plugin("libgstnvcodec.so", dirs):
        return "nvidia"
    if render and _has_plugin("libgstva.so", dirs):
        return "vaapi"
    return "software"


def new_pin():
    """A 4-digit AirPlay code, never 0000 (UxPlay reads a missing code as « draw one »)."""
    return "%04d" % (1 + secrets.randbelow(9999))


def build_args(name, profile="fluid", rotation="", fullscreen=False, screen="", decoder="software",
               pin=""):
    """UxPlay's command line for these options."""
    args = ["uxplay", "-n", name, "-nh", "-fps", "60"]
    if pin:
        args += ["-pin", pin]
    if profile != "quality":
        args += ["-vsync", "no"]  # no audio/video timestamp sync: lowest latency
    size = _screen(screen)
    if size:
        args += ["-s", "%dx%d@60" % size]
    if decoder == "nvidia":
        args += ["-vd", "nvh264dec", "-vs", "glimagesink"]
    elif decoder == "vaapi":
        args += ["-vd", "vah264dec"]
    else:
        args += ["-avdec"]
    if rotation in ("R", "L"):
        args += ["-r", rotation]
    if fullscreen:
        args += ["-fs"]
    return args


def _screen(text):
    """"2560x1600" -> (2560, 1600), capped to what AirPlay mirroring asks for."""
    try:
        width, height = (int(v) for v in (text or "").lower().split("x", 1))
    except ValueError:
        return None
    if width < 320 or height < 240:
        return None
    # The iPhone sends at most 1920 wide in mirroring; a larger request only costs bandwidth.
    if width > 1920:
        height = height * 1920 // width
        width = 1920
    return width, height


class Mirror:
    def __init__(self, changed, config=None):
        self.changed = changed
        self.config = config
        self.process = None
        self.error = ""
        self.decoder = ""
        self.fallback = False
        self.pin = ""
        self.name = "Covalence (%s)" % (socket.gethostname().split(".")[0] or "PC")

    @staticmethod
    def missing():
        found = []
        if shutil.which("uxplay") is None:
            found.append("uxplay")
        if shutil.which("avahi-daemon") is None and not GLib.file_test(
                "/usr/sbin/avahi-daemon", GLib.FileTest.EXISTS):
            found.append("avahi-daemon")
        dirs = _plugin_dirs()
        for plugin, package in PLUGINS.items():
            if not _has_plugin(plugin, dirs):
                found.append(package)
        return found

    # --- options ----------------------------------------------------------------------------

    def _get(self, key, default=""):
        if self.config is None:
            return default
        try:
            return self.config.keyfile.get_string("mirror", key)
        except GLib.Error:
            return default

    def option(self, key):
        if key == "fullscreen":
            return self._get("fullscreen", "false") == "true"
        if key == "profile":
            value = self._get("profile", "fluid")
            return value if value in PROFILES else "fluid"
        if key == "rotation":
            value = self._get("rotation", "")
            return value if value in ROTATIONS else ""
        return self._get(key, "")

    def set_option(self, key, value):
        """profile, rotation, fullscreen or screen; applied at the next start."""
        if key == "profile" and value not in PROFILES or key == "rotation" and value not in ROTATIONS:
            return False
        if key == "fullscreen":
            value = "true" if value in ("true", "1", "yes") else "false"
        if key not in ("profile", "rotation", "fullscreen", "screen"):
            return False
        if self.config is not None and self._get(key, None) != value:
            self.config.keyfile.set_string("mirror", key, value)
            self.config.save()
        self.changed()
        return True

    def state(self):
        missing = self.missing()
        return {"available": not missing, "running": self.process is not None,
                "name": self.name, "error": self.error, "missing": missing,
                "profile": self.option("profile"), "rotation": self.option("rotation"),
                "fullscreen": self.option("fullscreen"),
                "decoder": self.decoder or pick_decoder(),
                "pin": self.pin if self.process is not None else ""}

    # --- process ------------------------------------------------------------------------------

    def start(self, decoder=None):
        if self.process is not None:
            return True
        if self.missing():
            self.error = "missing"
            self.changed()
            return False
        self.error = ""
        self.decoder = decoder or pick_decoder()
        self.fallback = decoder is not None
        if not self.fallback or not self.pin:
            self.pin = new_pin()
        args = build_args(self.name, self.option("profile"), self.option("rotation"),
                          self.option("fullscreen"), self.option("screen"), self.decoder, self.pin)
        try:
            # Its output goes to a file (a pipe left unread would block it); read on exit.
            os.makedirs(os.path.dirname(LOG), exist_ok=True)
            launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.NONE)
            launcher.set_stdout_file_path(LOG)
            launcher.set_stderr_file_path(LOG)
            self.process = launcher.spawnv(args)
        except GLib.Error as error:
            self.error = error.message
            log("recopie : lancement impossible")
            self.changed()
            return False
        self.process.wait_async(None, self._ended)
        log(f"recopie : récepteur AirPlay démarré (décodage {self.decoder}, "
            f"profil {self.option('profile')})")
        self.changed()
        return True

    def _ended(self, process, result):
        try:
            process.wait_finish(result)
        except GLib.Error:
            pass
        if process is not self.process:
            return
        status = process.get_exit_status() if process.get_if_exited() else 0
        self.process = None
        failed = status not in (0,) and not process.get_if_signaled()
        if failed and self.decoder != "software" and not self.fallback:
            log(f"recopie : échec avec le décodage {self.decoder}, nouvel essai en logiciel")
            self.start(decoder="software")
            return
        if failed:
            self.error = self._reason() or "exited"
        log("recopie : récepteur AirPlay arrêté")
        self.changed()

    @staticmethod
    def _reason():
        """The first error UxPlay printed, e.g. "Required gstreamer plugin 'x' not found"."""
        try:
            with open(LOG, encoding="utf-8", errors="replace") as f:
                lines = [line.strip() for line in f.readlines()[-40:]]
        except OSError:
            return ""
        for line in lines:
            if "not found" in line or "ERROR" in line or "rror" in line:
                return line.strip("* ")[:200]
        return ""

    def stop(self):
        if self.process is not None:
            self.process.send_signal(15)
        else:
            self.changed()  # also a refresh after installing UxPlay
