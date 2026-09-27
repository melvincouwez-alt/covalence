# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Sounds chosen in Réglages for messages, iPhone notifications and incoming calls.

The daemon plays them itself (pw-play, else paplay or canberra-gtk-play) and sends
its notifications with suppress-sound, so a sound is never heard twice. Values
kept in covalenced.conf [sounds]: "none", "default", a sound name of the desktop
sound theme (freedesktop naming, e.g. "message-new-instant") or a file path.

Nothing is played while elementary's Do Not Disturb is on. The ringtone loops
while a call rings, unless the iPhone already rings in-band over the hands-free
audio link (then the PC would ring twice).
"""

import os
import shutil
import time

from gi.repository import Gio, GLib

from .i18n import N_, _
from .util import log

KINDS = ("messages", "notifications", "calls")
DEFAULTS = {"messages": "message-new-instant", "notifications": "dialog-information",
            "calls": "phone-incoming-call"}
EXTENSIONS = (".oga", ".ogg", ".wav", ".mp3", ".flac")
# Theme sounds that make no sense as an alert.
SKIP_PREFIXES = ("audio-channel-", "audio-test-signal", "audio-volume-change")

LABELS = {
    "message-new-instant": N_("Message instantané"), "message": N_("Message"),
    "dialog-information": N_("Information"), "dialog-warning": N_("Avertissement"),
    "dialog-error": N_("Erreur"), "bell": N_("Cloche"), "complete": N_("Terminé"),
    "phone-incoming-call": N_("Appel entrant"), "phone-outgoing-calling": N_("Appel sortant"),
    "phone-outgoing-busy": N_("Occupé"), "phone-hangup": N_("Raccrochage"),
    "alarm-clock-elapsed": N_("Réveil"), "window-attention": N_("Attention"),
    "window-question": N_("Question"), "camera-shutter": N_("Appareil photo"),
    "device-added": N_("Appareil branché"), "device-removed": N_("Appareil débranché"),
    "network-connectivity-established": N_("Réseau connecté"),
    "network-connectivity-lost": N_("Réseau perdu"), "power-plug": N_("Secteur branché"),
    "power-unplug": N_("Secteur débranché"), "screen-capture": N_("Capture d'écran"),
    "service-login": N_("Connexion"), "service-logout": N_("Déconnexion"),
    "suspend-error": N_("Erreur de mise en veille"), "trash-empty": N_("Corbeille vidée"),
}


# Sounds shipped with Covalence (data/sounds, credits in docs/credits-sons.md), listed first.
# Short alerts for messages and notifications, then ringtones (loopable, under 10 s).
BUNDLED = [
    ("rosee", N_("Rosée")), ("envol", N_("Envol")), ("vague", N_("Vague")),
    ("carillon", N_("Carillon")), ("cristal", N_("Cristal")),
    ("aurore", N_("Aurore (sonnerie)")), ("orbite", N_("Orbite (sonnerie)")),
    ("horizon", N_("Horizon (sonnerie)")),
]
BUNDLED_PREFIX = "covalence:"


def bundled_dir():
    """<datadir>/covalence/sounds once installed, data/sounds in the source tree."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for folder in (os.path.join(here, "sounds"), os.path.join(here, "data", "sounds")):
        if os.path.isdir(folder):
            return folder
    return None


def _bundled_path(name):
    folder = bundled_dir()
    path = os.path.join(folder, name + ".oga") if folder else None
    return path if path and os.path.isfile(path) else None


def _theme_name():
    source = Gio.SettingsSchemaSource.get_default()
    if source and source.lookup("org.gnome.desktop.sound", True):
        name = Gio.Settings.new("org.gnome.desktop.sound").get_string("theme-name")
        if name:
            return name
    return "freedesktop"


def _theme_dirs():
    """Sound folders, current theme first, then freedesktop, then the user's own."""
    roots = [os.path.join(GLib.get_user_data_dir(), "sounds")]
    roots += [os.path.join(d, "sounds") for d in GLib.get_system_data_dirs()]
    themes = [_theme_name(), "freedesktop"]
    dirs = []
    for theme in themes:
        for root in roots:
            dirs.append(os.path.join(root, theme, "stereo"))
    user = os.path.join(GLib.get_user_data_dir(), "sounds")
    if os.path.isdir(user):
        for theme in sorted(os.listdir(user)):
            dirs.append(os.path.join(user, theme, "stereo"))
        dirs.append(user)
    return [d for d in dict.fromkeys(dirs) if os.path.isdir(d)]


def resolve(value):
    """File to play for a value (a name of the sound theme or a path), or None."""
    if not value:
        return None
    if value.startswith(BUNDLED_PREFIX):
        return _bundled_path(value[len(BUNDLED_PREFIX):])
    if os.path.isabs(value):
        return value if os.path.isfile(value) else None
    for folder in _theme_dirs():
        for ext in EXTENSIONS:
            path = os.path.join(folder, value + ext)
            if os.path.isfile(path):
                return path
    return None


def label(value):
    if value.startswith(BUNDLED_PREFIX):
        name = value[len(BUNDLED_PREFIX):]
        return _("Covalence · {name}").format(name=_(dict(BUNDLED).get(name, name)))
    if os.path.isabs(value):
        return os.path.splitext(os.path.basename(value))[0]
    if value in LABELS:
        return _(LABELS[value])
    return value.replace("-", " ").replace("_", " ").capitalize()


def available():
    """[(value, label)]: Covalence's own sounds first, then the theme sounds found on this
    computer, sorted by label."""
    own = [(BUNDLED_PREFIX + name, label(BUNDLED_PREFIX + name)) for name, _title in BUNDLED
           if _bundled_path(name)]
    names = {}
    for folder in _theme_dirs():
        for entry in os.listdir(folder):
            name, ext = os.path.splitext(entry)
            if ext.lower() in EXTENSIONS and not name.startswith(SKIP_PREFIXES):
                names.setdefault(name, label(name))
    return own + sorted(names.items(), key=lambda item: item[1].casefold())


def do_not_disturb():
    source = Gio.SettingsSchemaSource.get_default()
    schema = source.lookup("io.elementary.notifications", True) if source else None
    if schema is None or not schema.has_key("do-not-disturb"):
        return False
    return Gio.Settings.new("io.elementary.notifications").get_boolean("do-not-disturb")


def _player():
    for name, args in (("pw-play", []), ("paplay", []), ("canberra-gtk-play", ["-f"])):
        path = shutil.which(name)
        if path:
            return [path] + args
    return None


class Sounds:
    def __init__(self, config):
        self.config = config
        self.process = None  # the sound being played (one at a time)
        self.ringing = False
        self.ring_timer = 0
        self.last_alert = 0.0  # a burst of notifications gives one sound

    def value(self, kind):
        value = self.config._string("sounds", kind, "default") if kind in KINDS else "none"
        return value or "default"

    def settings(self):
        return {kind: self.value(kind) for kind in KINDS}

    def set(self, kind, value):
        if kind not in KINDS:
            raise ValueError(kind)
        value = (value or "default").strip()
        if value not in ("none", "default") and not resolve(value):
            raise ValueError(value)
        self.config.keyfile.set_string("sounds", kind, value)
        self.config.save()
        log(f"sons : {kind} → {'fichier' if os.path.isabs(value) else value}")

    def _file(self, kind, value=None):
        value = value or self.value(kind)
        if value == "none":
            return None
        if value == "default":
            value = DEFAULTS[kind]
        return resolve(value) or resolve(DEFAULTS[kind])

    def _spawn(self, path, on_exit=None):
        player = _player()
        if not player or not path:
            return False
        self.stop()
        try:
            process = Gio.Subprocess.new(player + [path], Gio.SubprocessFlags.STDOUT_SILENCE
                                         | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error as error:
            log(f"sons : lecture impossible ({error.message})")
            return False
        self.process = process

        def done(proc, result):
            try:
                proc.wait_finish(result)
            except GLib.Error:
                pass
            if self.process is proc:
                self.process = None
                if on_exit:
                    on_exit()

        process.wait_async(None, done)
        return True

    def play(self, kind):
        """An alert for a message or an iPhone notification. True if a sound was played
        (the notification then asks the server for silence)."""
        if kind == "calls" or self.ringing or do_not_disturb():
            return False
        now = time.monotonic()
        if now - self.last_alert < 2:
            return False
        self.last_alert = now
        return self._spawn(self._file(kind))

    def preview(self, kind, value):
        """The ▶ button in Réglages: plays even under Do Not Disturb, once."""
        if kind not in KINDS:
            return False
        self.stop_ring()
        return self._spawn(self._file(kind, value))

    def start_ring(self):
        if self.ringing:
            return
        if do_not_disturb():
            log("sons : sonnerie coupée (Ne pas déranger)")
            return
        path = self._file("calls")
        if not path:
            return
        self.ringing = True
        self._ring_once(path)

    def _ring_once(self, path):
        def again():
            if self.ringing:
                # a short pause between two rings, as a phone does
                self.ring_timer = GLib.timeout_add(800, lambda: self._ring_tick(path))

        if not self._spawn(path, on_exit=again):
            self.ringing = False

    def _ring_tick(self, path):
        self.ring_timer = 0
        if self.ringing:
            self._ring_once(path)
        return GLib.SOURCE_REMOVE

    def stop_ring(self):
        if not self.ringing:
            return
        self.ringing = False
        if self.ring_timer:
            GLib.source_remove(self.ring_timer)
            self.ring_timer = 0
        self.stop()

    def stop(self):
        process, self.process = self.process, None
        if process is not None:
            process.force_exit()
