# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""What the iPhone is playing ("Now Playing" page), from one of two sources.

- AMS (Apple Media Service, over the BLE link): app name, title, artist, album,
  duration, playback state with elapsed time and rate, volume, remote commands.
- AVRCP (BlueZ org.bluez.MediaPlayer1, over the classic link) when AMS is not
  there: the same minus the app name and the volume.

The artwork is not sent by the iPhone. When [media] artwork is on (default),
it is looked up on Apple's public iTunes Search service with the artist and
the title only, kept only if both match, and cached in
~/.cache/covalence/artwork (directory 0700, files 0600).
"""

import hashlib
import json
import os
import threading
import time
import unicodedata
import urllib.parse
import urllib.request

from gi.repository import GLib

from . import ams, cachedir
from .util import BLUEZ, call_async, log

PLAYER_IFACE = "org.bluez.MediaPlayer1"
CONTROL_IFACE = "org.bluez.MediaControl1"  # the device's AVRCP link, even with no player
SEARCH = "https://itunes.apple.com/search?term={}&entity=song&limit=5&country={}"
RETRY_MISSING = 30 * 24 * 3600
ARTWORK_MAX_FILES = 300  # covers of the iPhone's music, least recently shown dropped first
ARTWORK_MAX_DAYS = 90
RETRY_FAILED = 3600

# AMS gives the player's display name only: known names -> bundle id (for its icon).
PLAYER_BUNDLES = {
    "music": "com.apple.Music", "musique": "com.apple.Music",
    "podcasts": "com.apple.podcasts",
    "books": "com.apple.iBooks", "livres": "com.apple.iBooks",
    "spotify": "com.spotify.client",
    "deezer": "com.deezer.Deezer",
    "youtube": "com.google.ios.youtube",
    "youtube music": "com.google.ios.youtubemusic",
    "soundcloud": "com.soundcloud.TouchApp",
    "audible": "com.audible.iphone",
    "amazon music": "com.amazon.mp3.AmazonMP3",
    "tidal": "com.aspiro.TIDAL",
    "qobuz": "com.qobuz.QobuzMobile",
    "radio france": "com.radiofrance.radio",
    "safari": "com.apple.mobilesafari",
}

COMMANDS = {
    "play": ams.CMD_PLAY, "pause": ams.CMD_PAUSE, "toggle": ams.CMD_TOGGLE,
    "next": ams.CMD_NEXT, "previous": ams.CMD_PREVIOUS,
    "skip-forward": ams.CMD_SKIP_FORWARD, "skip-backward": ams.CMD_SKIP_BACKWARD,
    "volume-up": ams.CMD_VOLUME_UP, "volume-down": ams.CMD_VOLUME_DOWN,
}
AVRCP_METHODS = {
    "play": "Play", "pause": "Pause", "next": "Next", "previous": "Previous",
    "skip-forward": "FastForward", "skip-backward": "Rewind",
}

# D-Bus signature of each NowPlaying field.
TYPES = {
    "source": "s", "app": "s", "app_icon": "s", "app_image": "s", "title": "s", "artist": "s",
    "album": "s", "duration": "d", "position": "d", "position_time": "d", "rate": "d",
    "status": "s", "volume": "d", "can_volume": "b", "artwork": "s", "commands": "as",
    "can_play": "b",
}


def normalize(text):
    """Lower case, no accents, no punctuation or bracketed extras ("(Remastered)")."""
    text = unicodedata.normalize("NFKD", text or "").casefold()
    text = "".join(c for c in text if not unicodedata.combining(c))
    for opening, closing in ("()", "[]"):
        while opening in text and closing in text.split(opening, 1)[1]:
            before, rest = text.split(opening, 1)
            text = before + rest.split(closing, 1)[1]
    text = text.split(" - ")[0]
    return " ".join("".join(c if c.isalnum() else " " for c in text).split())


def matches(result, artist, title):
    """True when an iTunes result is really this song (never a lookalike)."""
    got_artist, got_title = normalize(result.get("artistName")), normalize(result.get("trackName"))
    want_artist, want_title = normalize(artist), normalize(title)
    if not (got_artist and got_title and want_artist and want_title):
        return False
    title_ok = got_title == want_title or got_title.startswith(want_title) \
        or want_title.startswith(got_title)
    artist_ok = want_artist in got_artist or got_artist in want_artist
    return title_ok and artist_ok


def extrapolate(position, rate, playing, since, now):
    """Position now, from the last reported one (never past a known duration: caller clamps)."""
    if not playing:
        return position
    return position + (rate or 1.0) * max(now - since, 0.0)


def choose_source(ams_linked, avrcp_player, avrcp_control=False):
    """AMS when linked (richer: app name, volume), else an AVRCP player, else the bare
    AVRCP link (nothing known, but Play still works), else nothing."""
    if ams_linked:
        return "ams"
    if avrcp_player:
        return "avrcp"
    if avrcp_control:
        return "avrcp-control"
    return ""


class Artwork:
    def __init__(self, config, directory=None, fetch=None):
        self.config = config
        self.dir = directory or os.path.join(GLib.get_user_cache_dir(), "covalence", "artwork")
        self.fetch_json = fetch or _fetch_json
        self.busy = set()
        self.lock = threading.Lock()
        cachedir.prune(self.dir, ARTWORK_MAX_FILES, ARTWORK_MAX_DAYS)

    def enabled(self):
        return self.config.boolean("media", "artwork", True)

    def _key(self, artist, title):
        return hashlib.sha1(f"{normalize(artist)}|{normalize(title)}".encode()).hexdigest()[:20]

    def lookup(self, artist, title, on_ready=None):
        """Cached artwork file, or "" (then fetched in the background if allowed)."""
        if not (artist and title) or not self.enabled():
            return ""
        key = self._key(artist, title)
        path = os.path.join(self.dir, key + ".jpg")
        if os.path.exists(path):
            cachedir.touch(path)  # recently used: kept by the next prune
            return path
        missing = os.path.join(self.dir, key + ".missing")
        if os.path.exists(missing) and time.time() - os.path.getmtime(missing) < RETRY_MISSING:
            return ""
        with self.lock:
            if key in self.busy:
                return ""
            self.busy.add(key)
        threading.Thread(target=self._fetch, args=(key, artist, title, on_ready),
                         daemon=True).start()
        return ""

    def _mark_missing(self, key, retry):
        try:
            missing = os.path.join(self.dir, key + ".missing")
            open(missing, "w").close()
            os.chmod(missing, 0o600)
            now = time.time()
            os.utime(missing, (now, now - RETRY_MISSING + retry))
        except OSError:
            pass

    def _fetch(self, key, artist, title, on_ready):
        path = ""
        try:
            os.makedirs(self.dir, mode=0o700, exist_ok=True)
            os.chmod(self.dir, 0o700)
            country = (GLib.get_language_names()[0][3:5] or "us").lower()
            url = SEARCH.format(urllib.parse.quote(f"{artist} {title}"),
                                country if len(country) == 2 else "us")
            results = self.fetch_json(url).get("results", [])
            found = next((r for r in results if matches(r, artist, title)), None)
            art = (found or {}).get("artworkUrl100", "")
            if not art.startswith("https://"):
                self._mark_missing(key, RETRY_MISSING)
                log("pochette introuvable")
                return
            art = art.rsplit("/", 1)[0] + "/600x600bb.jpg"
            with urllib.request.urlopen(art, timeout=15) as reply:
                data = reply.read(4 * 1024 * 1024)
            path = os.path.join(self.dir, key + ".jpg")
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
            log("pochette enregistrée")
        except Exception as error:  # network, JSON: no artwork, never an error shown
            log(f"pochette non récupérée ({type(error).__name__})")
            path = ""
            self._mark_missing(key, RETRY_FAILED)
        finally:
            with self.lock:
                self.busy.discard(key)
        if path and on_ready:
            GLib.idle_add(lambda: on_ready() and False)


def _fetch_json(url):
    with urllib.request.urlopen(url, timeout=15) as reply:
        return json.load(reply)


class NowPlaying:
    def __init__(self, system, config, icons, on_changed):
        self.system = system
        self.config = config
        self.icons = icons  # AppIcons, for the source app's icon
        self.on_changed = on_changed
        self.artwork = Artwork(config)
        self.link = None
        self.avrcp = {}  # path of the iPhone's MediaPlayer1 -> its properties
        self.avrcp_stamp = 0.0
        self.control = None  # device path when its AVRCP link (MediaControl1) is up

    # --- sources ---------------------------------------------------------------------

    def attach(self, link):
        self.link = link

    def _ams(self):
        link = self.link
        return link.ams if link and link.ams and self.config.module_enabled("media") else None

    def _avrcp_path(self):
        return next(iter(self.avrcp), None) if self.config.module_enabled("media") else None

    def refresh_avrcp(self, objects):
        """Re-read the iPhone's AVRCP players from BlueZ's objects."""
        device = self.link.device if self.link else None
        self.avrcp = {p: dict(i[PLAYER_IFACE]) for p, i in objects.items()
                      if device and p.startswith(device + "/") and PLAYER_IFACE in i}
        control = objects.get(device, {}).get(CONTROL_IFACE, {}) if device else {}
        self.control = device if control.get("Connected") else None
        self.avrcp_stamp = time.time()
        self.on_changed()

    def control_changed(self, path, changed):
        if "Connected" in changed and self.link and path == self.link.device:
            self.control = path if changed["Connected"] else None
            self.on_changed()

    def avrcp_changed(self, path, changed):
        if path in self.avrcp:
            self.avrcp[path].update(changed)
            if "Position" in changed or "Status" in changed:
                self.avrcp_stamp = time.time()
            self.on_changed()

    # --- state -----------------------------------------------------------------------

    def _app_icon(self, app):
        bundle = PLAYER_BUNDLES.get((app or "").casefold())
        if not bundle:
            names = {}
            try:
                for key in self.config.keyfile.get_keys("notification-app-names")[0]:
                    names[self.config._string("notification-app-names", key).casefold()] = key
            except GLib.Error:
                pass
            bundle = names.get((app or "").casefold())
        if not bundle or not self.icons:
            return "", ""
        return self.icons.lookup(bundle, lambda *_: self.on_changed())

    def state(self):
        control = self.control if self.config.module_enabled("media") else None
        source = choose_source(self._ams() is not None, self._avrcp_path(), control)
        empty = {k: ("" if t == "s" else [] if t == "as" else False if t == "b" else 0.0)
                 for k, t in TYPES.items()}
        empty["status"], empty["volume"] = "stopped", -1.0
        if source == "ams":
            client = self._ams()
            s = client.state
            wall = s.get("wall") or 0.0
            state = dict(empty, source="ams", app=s["player"], title=s["title"],
                         artist=s["artist"], album=s["album"], duration=s["duration"],
                         position=s["elapsed"], position_time=wall, rate=s["rate"] or 1.0,
                         status={"Playing": "playing", "Paused": "paused"}.get(
                             s["status"], "stopped"),
                         volume=s["volume"] if s["player"] else -1.0,
                         can_volume=True,
                         commands=[name for name, cid in COMMANDS.items()
                                   if not client.supported or cid in client.supported])
        elif source == "avrcp":
            p = self.avrcp[self._avrcp_path()]
            track = p.get("Track", {}) or {}
            status = str(p.get("Status", "stopped"))
            state = dict(empty, source="avrcp", title=str(track.get("Title", "")),
                         artist=str(track.get("Artist", "")), album=str(track.get("Album", "")),
                         duration=float(track.get("Duration", 0)) / 1000.0,
                         position=float(p.get("Position", 0)) / 1000.0,
                         position_time=self.avrcp_stamp, rate=1.0,
                         status=status if status in ("playing", "paused") else "stopped",
                         commands=list(AVRCP_METHODS) + ["toggle"])
        elif source == "avrcp-control":
            state = dict(empty, source=source, commands=list(AVRCP_METHODS) + ["toggle"])
        else:
            return empty
        # Play always reaches the iPhone when a link is there: it resumes its last audio.
        state["can_play"] = True
        if not state["title"]:
            state["status"] = "stopped" if state["status"] != "playing" else "playing"
        state["app_icon"], state["app_image"] = self._app_icon(state["app"])
        state["artwork"] = self.artwork.lookup(state["artist"], state["title"], self.on_changed)
        return state

    # --- control ---------------------------------------------------------------------

    def command(self, name):
        """Returns False when the command cannot be sent.

        "play" and "toggle" also work with nothing playing: the iPhone resumes its last
        audio (AMS Play / TogglePlayPause, or AVRCP Play on the player or the link)."""
        client = self._ams()
        if client:
            playing = client.state["status"] == "Playing"
            if name == "toggle":
                return client.command(ams.CMD_TOGGLE) or \
                    client.command(ams.CMD_PAUSE if playing else ams.CMD_PLAY)
            if name == "play":
                return client.command(ams.CMD_PLAY) or client.command(ams.CMD_TOGGLE)
            return name in COMMANDS and client.command(COMMANDS[name])
        path = self._avrcp_path()
        control = self.control if self.config.module_enabled("media") else None
        if path or control:
            if name == "toggle":
                playing = path and self.avrcp[path].get("Status") == "playing"
                name = "pause" if playing else "play"
            method = AVRCP_METHODS.get(name)
            if method:
                call_async(self.system, BLUEZ, path or control,
                           PLAYER_IFACE if path else CONTROL_IFACE, method)
                return True
        return False

    def set_volume(self, target):
        """AMS has relative steps only: one step towards the target."""
        client = self._ams()
        if not client:
            return False
        current = client.state["volume"]
        if abs(target - current) < 0.02:
            return True
        return client.command(ams.CMD_VOLUME_UP if target > current else ams.CMD_VOLUME_DOWN)
