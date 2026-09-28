# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Icons of the iPhone apps behind ANCS notifications.

ANCS only gives the app's bundle identifier. Built-in Apple apps map to local
icons; other apps get their public App Store artwork (iTunes lookup API), cut
to a rounded square and cached in ~/.cache/covalence/app-icons. Only the
bundle identifier is sent, never notification content. "app-icons=false" in
the [notifications] group of covalenced.conf turns the download off.
"""

import json
import os
import threading
import time
import urllib.parse
import urllib.request

from gi.repository import GLib

from . import cachedir
from .util import APP_ID, log

LOOKUP = "https://itunes.apple.com/lookup?bundleId={}&country={}"
RETRY_MISSING = 7 * 24 * 3600
ICONS_MAX_FILES = 400  # two files per app (rounded and square)
ICONS_MAX_DAYS = 180
RETRY_FAILED = 3600

# Built-in apps (not on the App Store): themed icon names.
BUILTIN = {
    "com.apple.MobileSMS": "internet-chat",
    "com.apple.mobilephone": APP_ID + ".Phone",
    "com.apple.facetime": APP_ID + ".Phone",
    "com.apple.MobileAddressBook": APP_ID + ".Contacts",
    "com.apple.mobilemail": "io.elementary.mail",
    "com.apple.mobilecal": "x-office-calendar",
    "com.apple.reminders": "io.elementary.tasks",
    "com.apple.Music": APP_ID + ".NowPlaying",  # the elementary 16 px audio icon is blank
    "com.apple.mobileslideshow": "io.elementary.photos",
    "com.apple.camera": "camera-photo",
    "com.apple.mobiletimer": "preferences-system-time",
    "com.apple.weather": "applications-internet",
    "com.apple.findmy": "find-location",
    "com.apple.Health": "applications-science",
    "com.apple.Passbook": "payment-card",
    "com.apple.AppStore": "system-software-install",
    "com.apple.Preferences": "preferences-system",
    "com.apple.mobilesafari": "applications-internet",
    "com.apple.mobilenotes": "accessories-text-editor",
    "com.apple.news": "application-rss+xml",
    "com.apple.podcasts": APP_ID + ".NowPlaying",
}


def _safe(app_id):
    return "".join(c if c.isalnum() or c in ".-_" else "_" for c in app_id)


class AppIcons:
    def __init__(self, config, directory=None):
        self.config = config
        self.dir = directory or os.path.join(GLib.get_user_cache_dir(), "covalence", "app-icons")
        self.busy = set()
        self.lock = threading.Lock()
        cachedir.prune(self.dir, ICONS_MAX_FILES, ICONS_MAX_DAYS)

    def enabled(self):
        return self.config.boolean("notifications", "app-icons", True)

    def _path(self, app_id):
        return os.path.join(self.dir, _safe(app_id) + ".png")

    def _missing_path(self, app_id):
        return os.path.join(self.dir, _safe(app_id) + ".missing")

    def lookup(self, app_id, on_ready=None):
        """(themed icon name or "", image file or ""); starts a download if needed."""
        if not app_id:
            return "", ""
        if app_id in BUILTIN:
            return BUILTIN[app_id], ""
        path = self._path(app_id)
        if os.path.exists(path) and os.path.exists(square_path(path)):
            cachedir.touch(path)  # recently used: kept by the next prune
            cachedir.touch(square_path(path))
            return "", path
        if app_id.startswith("com.apple.") or not self.enabled():
            return "", ""
        missing = self._missing_path(app_id)
        if os.path.exists(missing) and time.time() - os.path.getmtime(missing) < RETRY_MISSING:
            return "", ""
        with self.lock:
            if app_id in self.busy:
                return "", ""
            self.busy.add(app_id)
        threading.Thread(target=self._fetch, args=(app_id, on_ready), daemon=True).start()
        return "", ""

    def _fetch(self, app_id, on_ready):
        path = ""
        try:
            os.makedirs(self.dir, mode=0o700, exist_ok=True)
            country = (GLib.get_language_names()[0][3:5] or "us").lower()
            url = LOOKUP.format(urllib.parse.quote(app_id), country if len(country) == 2 else "us")
            with urllib.request.urlopen(url, timeout=15) as reply:
                results = json.load(reply).get("results", [])
            art = results[0].get("artworkUrl512") or results[0].get("artworkUrl100") \
                if results else ""
            if not art.startswith("https://"):
                open(self._missing_path(app_id), "w").close()
                log("icône d'app introuvable sur l'App Store")
                return
            art = art.rsplit("/", 1)[0] + "/256x256bb.png"
            with urllib.request.urlopen(art, timeout=15) as reply:
                data = reply.read(4 * 1024 * 1024)
            path = self._path(app_id)
            _square(data, square_path(path))
            _rounded(data, path)
            log("icône d'app enregistrée")
        except Exception as error:  # network, JSON, image: no icon, never an error shown
            log(f"icône d'app non récupérée ({type(error).__name__})")
            path = ""
            try:  # try again in an hour, not at every notification
                open(self._missing_path(app_id), "w").close()
                os.utime(self._missing_path(app_id),
                         (time.time(), time.time() - RETRY_MISSING + RETRY_FAILED))
            except OSError:
                pass
        finally:
            with self.lock:
                self.busy.discard(app_id)
        if path and on_ready:
            GLib.idle_add(lambda: on_ready(app_id, path) and False)


def square_path(path):
    """The plain square artwork next to the rounded one: notifications get it, and
    elementary's notification server rounds it in its own style."""
    return path[:-len(".png")] + ".square.png"


def image_data(path):
    """"image-data" notification hint (iiibiiay) of the square artwork, or None.

    elementary's server ignores file paths as app icon; raw pixels always work."""
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    try:
        p = GdkPixbuf.Pixbuf.new_from_file_at_size(square_path(path), 128, 128)
    except GLib.Error:
        return None
    return GLib.Variant("(iiibiiay)", (p.get_width(), p.get_height(), p.get_rowstride(),
                                       p.get_has_alpha(), p.get_bits_per_sample(),
                                       p.get_n_channels(), p.get_pixels()))


def _square(data, path):
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    loader = GdkPixbuf.PixbufLoader()
    loader.write(data)
    loader.close()
    pixbuf = loader.get_pixbuf().scale_simple(256, 256, GdkPixbuf.InterpType.BILINEAR)
    tmp = path + ".part"
    pixbuf.savev(tmp, "png", [], [])
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _rounded(data, path):
    """Store the artwork as a PNG with iOS-like rounded corners (pure GdkPixbuf)."""
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    loader = GdkPixbuf.PixbufLoader()
    loader.write(data)
    loader.close()
    size, radius = 256, 56
    pixbuf = loader.get_pixbuf().scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
    pixbuf = pixbuf.add_alpha(False, 0, 0, 0)
    stride = pixbuf.get_rowstride()
    pixels = bytearray(pixbuf.get_pixels())
    for y in range(size):
        dy = max(radius - y - 0.5, y + 0.5 - (size - radius), 0)
        if not dy:
            continue
        for x in range(size):
            dx = max(radius - x - 0.5, x + 0.5 - (size - radius), 0)
            if not dx:
                continue
            # Antialiased edge: coverage from the distance to the corner circle.
            cover = min(max(radius - (dx * dx + dy * dy) ** 0.5 + 0.5, 0.0), 1.0)
            i = y * stride + x * 4 + 3
            pixels[i] = int(pixels[i] * cover)
    shaped = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(pixels)),
                                             GdkPixbuf.Colorspace.RGB, True, 8, size, size, stride)
    tmp = path + ".part"
    shaped.savev(tmp, "png", [], [])
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
