# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""New versions of Covalence, from the project's GitHub releases.

Only one request leaves the PC: GET on the public releases list, with Covalence's version
as User-Agent. It runs at start (after a minute), then once a day, and when the user asks;
[updates] check=false in covalenced.conf turns the automatic checks off.

Installing downloads the release's .deb to ~/.cache/covalence/updates, checks it against
the SHA-256 digest GitHub publishes for the asset (no digest, no automatic install: only
the release page is offered), then runs `pkexec apt-get install -y` (polkit asks for the
password). Nothing is installed without the user's click.
"""

import hashlib
import json
import os
import re
import threading
import time
import urllib.request

from gi.repository import Gio, GLib

from . import __version__
from .i18n import _
from .util import log

RELEASES = "https://api.github.com/repos/melvincouwez-alt/covalence/releases"
FIRST_CHECK = 60          # seconds after start
CHECK_EVERY = 24 * 3600   # seconds between automatic checks
TIMEOUT = 15
MAX_DEB = 200 * 1024 * 1024

TYPES = {"current": "s", "latest": "s", "url": "s", "notes": "s", "checked": "x",
         "state": "s", "size": "x", "progress": "d", "error": "s", "can_install": "b",
         "auto": "b"}

_PRE_RANK = {"dev": 0, "a": 1, "alpha": 1, "b": 2, "beta": 2, "pre": 3, "rc": 3}
_VERSION = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-.~+]?([a-z]+)[.-]?(\d*))?",
                      re.IGNORECASE)


def version_key(text):
    """Sortable key: 0.3.0 > 0.3.0-rc1 > 0.3.0-beta.2 > 0.3.0-alpha > 0.2.9. None if unreadable."""
    found = _VERSION.match((text or "").strip())
    if not found:
        return None
    major, minor, patch, label, number = found.groups()
    base = (int(major), int(minor or 0), int(patch or 0))
    if not label:
        return base + (1, 0, 0)  # a final release comes after its pre-releases
    rank = _PRE_RANK.get(label.lower())
    if rank is None:
        return base + (1, 0, 0)  # unknown suffix (build metadata): treat as the release
    return base + (0, rank, int(number or 0))


def is_newer(candidate, current):
    a, b = version_key(candidate), version_key(current)
    return a is not None and b is not None and a > b


def pick(releases, current):
    """The newest release above current (drafts left out, pre-releases in), or None."""
    best, best_key = None, version_key(current)
    if best_key is None:
        return None
    for release in releases or []:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        key = version_key(release.get("tag_name") or release.get("name") or "")
        if key is not None and key > best_key:
            best, best_key = release, key
    return best


def deb_asset(release, arch="amd64"):
    """(url, size, sha256 or "") of the release's .deb for this architecture."""
    for asset in release.get("assets") or []:
        name = asset.get("name") or ""
        if name.endswith(f"_{arch}.deb") or (name.endswith(".deb") and arch in name):
            digest = asset.get("digest") or ""
            sha = digest[7:].lower() if digest.lower().startswith("sha256:") else ""
            if not re.fullmatch(r"[0-9a-f]{64}", sha):
                sha = ""
            return asset.get("browser_download_url") or "", int(asset.get("size") or 0), sha
    return "", 0, ""


def _get_json(url):
    request = urllib.request.Request(url, headers={
        "User-Agent": f"Covalence/{__version__}", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as reply:
        return json.loads(reply.read(4 * 1024 * 1024).decode("utf-8"))


def _arch():
    try:
        machine = os.uname().machine
    except AttributeError:
        return "amd64"
    return {"x86_64": "amd64", "aarch64": "arm64"}.get(machine, machine)


class Updates:
    def __init__(self, config, notifier, on_changed, current=__version__, fetch=_get_json,
                 cache_dir=None, spawn=None):
        self.config = config
        self.notifier = notifier
        self.on_changed = on_changed
        self.current = current
        self.fetch = fetch
        self.dir = cache_dir or os.path.join(GLib.get_user_cache_dir(), "covalence", "updates")
        self.spawn = spawn or _spawn
        self.release = None
        self.state_name = "idle"
        self.progress = 0.0
        self.error = ""
        self.busy = False
        self.waiters = []
        self.notification = 0
        self.timer = 0

    # --- settings --------------------------------------------------------------------------

    @property
    def auto(self):
        return self.config.boolean("updates", "check", True)

    def set_auto(self, enabled):
        self.config.set_boolean("updates", "check", bool(enabled))
        log(f"mises à jour : recherche automatique {'activée' if enabled else 'désactivée'}")
        self._changed()

    @property
    def checked(self):
        try:
            return int(self.config.string("updates", "checked", "0") or 0)
        except ValueError:
            return 0

    # --- state exposed on D-Bus --------------------------------------------------------------

    def state(self):
        latest, url, notes, size, can_install = "", "", "", 0, False
        if self.release:
            latest = (self.release.get("tag_name") or "").lstrip("vV")
            url = self.release.get("html_url") or ""
            notes = self.release.get("body") or ""
            deb, size, sha = deb_asset(self.release, _arch())
            can_install = bool(deb and sha)
        return {"current": self.current, "latest": latest, "url": url, "notes": notes,
                "checked": self.checked, "state": self.state_name, "size": size,
                "progress": self.progress, "error": self.error, "can_install": can_install,
                "auto": self.auto}

    def available(self):
        return 1 if self.release and self.state_name in ("available", "error") else 0

    def _changed(self):
        if self.on_changed:
            self.on_changed()

    # --- checking ------------------------------------------------------------------------------

    def start(self):
        """Automatic checks: a minute after start, then every day (if allowed)."""
        GLib.timeout_add_seconds(FIRST_CHECK, self._first)
        self.timer = GLib.timeout_add_seconds(3600, self._hourly)

    def _first(self):
        if self.auto:
            self.check()
        return False

    def _hourly(self):
        if self.auto and time.time() - self.checked >= CHECK_EVERY - 60:
            self.check()
        return True

    def check(self, on_done=None):
        """on_done(latest version or "", error or None)."""
        if on_done:
            self.waiters.append(on_done)
        if self.busy:
            return
        if self.state_name in ("downloading", "installing"):
            return self._finish_waiters()
        self.busy = True
        self.state_name = "checking"
        self.error = ""
        self._changed()

        def job():
            try:
                result, error = self.fetch(RELEASES), None
            except Exception as failure:  # network, JSON, HTTP: reported, never raised
                result, error = None, type(failure).__name__
            GLib.idle_add(lambda: self._checked(result, error) and False)

        threading.Thread(target=job, name="covalence-updates", daemon=True).start()

    def _checked(self, result, error):
        self.busy = False
        if error is not None or not isinstance(result, list):
            self.state_name = "error"
            self.error = _("Recherche impossible ({reason})").format(reason=error or "format")
            log(f"mises à jour : recherche impossible ({error or 'format'})")
        else:
            self.config.set_string("updates", "checked", str(int(time.time())))
            self.release = pick(result, self.current)
            self.state_name = "available" if self.release else "idle"
            latest = self.state()["latest"]
            log(f"mises à jour : {'version ' + latest + ' disponible' if latest else 'à jour'}")
            if latest and self.config.string("updates", "notified", "") != latest:
                self.config.set_string("updates", "notified", latest)
                self._notify(latest)
        self._changed()
        self._finish_waiters()

    def _finish_waiters(self):
        waiters, self.waiters = self.waiters, []
        latest = self.state()["latest"] if self.release else ""
        error = self.error if self.state_name == "error" else None
        for on_done in waiters:
            on_done(latest, error)

    def _notify(self, latest):
        actions = [("default", _("Réglages")), ("notes", _("Voir les nouveautés"))]
        if self.state()["can_install"]:
            actions.append(("install", _("Installer")))
        self.notification = self.notifier.notify(
            "Covalence", "io.github.melvincouwez.Covalence",
            _("Covalence {version} est disponible").format(version=latest),
            _("La mise à jour se trouve dans Réglages."), actions,
            replaces=self.notification, on_action=self._on_action, own=True)

    def _on_action(self, action):
        if action == "notes":
            url = self.state()["url"]
            if url:
                try:
                    Gio.AppInfo.launch_default_for_uri(url, None)
                except GLib.Error as error:
                    log(f"mises à jour : page non ouverte ({error.message})")
        elif action == "install":
            self.install(lambda error: None)
        else:
            self.spawn([_app_path(), "--page", "settings"])

    # --- installing ----------------------------------------------------------------------------

    def install(self, on_done):
        """on_done(error or None) once the package is installed (or failed)."""
        if not self.release or self.state_name not in ("available", "error"):
            return on_done(_("aucune mise à jour à installer"))
        url, size, sha = deb_asset(self.release, _arch())
        if not url or not sha:
            return on_done(_("pas de paquet vérifiable pour cette version : "
                             "installez-la depuis la page GitHub"))
        if not url.startswith("https://github.com/") and \
                not url.startswith("https://objects.githubusercontent.com/"):
            return on_done(_("adresse de téléchargement inattendue"))
        self.state_name, self.progress, self.error = "downloading", 0.0, ""
        self._changed()
        target = os.path.join(self.dir, url.rsplit("/", 1)[-1])

        def report(fraction):
            self.progress = fraction
            self._changed()
            return False

        def job():
            error = None
            try:
                os.makedirs(self.dir, mode=0o700, exist_ok=True)
                digest = hashlib.sha256()
                done = 0
                request = urllib.request.Request(url, headers={
                    "User-Agent": f"Covalence/{__version__}"})
                with urllib.request.urlopen(request, timeout=TIMEOUT) as reply, \
                        open(target + ".part", "wb") as out:
                    last = 0.0
                    while True:
                        chunk = reply.read(256 * 1024)
                        if not chunk:
                            break
                        done += len(chunk)
                        if done > MAX_DEB:
                            raise OSError("package too large")
                        digest.update(chunk)
                        out.write(chunk)
                        if size and done / size - last >= 0.02:
                            last = done / size
                            GLib.idle_add(report, min(last, 1.0) * 0.9)
                if digest.hexdigest() != sha:
                    raise ValueError("SHA-256 mismatch")
                os.chmod(target + ".part", 0o644)  # apt's _apt user reads it
                os.replace(target + ".part", target)
            except Exception as failure:
                error = type(failure).__name__ if not isinstance(failure, ValueError) \
                    else str(failure)
                try:
                    os.unlink(target + ".part")
                except OSError:
                    pass
            GLib.idle_add(lambda: self._downloaded(target, error, on_done) and False)

        threading.Thread(target=job, name="covalence-update-download", daemon=True).start()

    def _downloaded(self, target, error, on_done):
        if error:
            self._failed(_("Téléchargement impossible ({reason})").format(reason=error), on_done)
            return
        log("mises à jour : paquet téléchargé et vérifié (SHA-256)")
        self.state_name, self.progress = "installing", 0.9
        self._changed()
        try:
            process = Gio.Subprocess.new(["pkexec", "apt-get", "install", "-y", target],
                                         Gio.SubprocessFlags.STDOUT_SILENCE
                                         | Gio.SubprocessFlags.STDERR_PIPE)
        except GLib.Error as failure:
            self._failed(_("Installation impossible ({reason})").format(reason=failure.message),
                         on_done)
            return

        def finished(proc, result):
            try:
                _out, err = proc.communicate_utf8_finish(result)
            except GLib.Error as failure:
                self._failed(failure.message, on_done)
                return
            status = proc.get_exit_status()
            if status == 0:
                self.state_name, self.progress = "ready", 1.0
                self.release = None
                log("mises à jour : paquet installé, redémarrage à proposer")
                self._changed()
                on_done(None)
            elif status in (126, 127):  # polkit: dialog dismissed or not authorised
                self._failed(_("Installation annulée"), on_done)
            else:
                last = (err or "").strip().splitlines()[-1:] or [""]
                self._failed(_("Installation impossible ({reason})").format(
                    reason=last[0][:160] or status), on_done)

        process.communicate_utf8_async(None, None, finished)

    def _failed(self, message, on_done):
        self.state_name, self.error, self.progress = "error", message, 0.0
        log("mises à jour : échec de l'installation")
        self._changed()
        on_done(message)


def _app_path():
    import sys
    return os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])),
                        "io.github.melvincouwez.Covalence")


def restart_daemon():
    """After an update: the service manager starts the new daemon (the app reconnects)."""
    _spawn(["systemctl", "--user", "restart", "covalenced.service"])


def _spawn(argv):
    try:
        Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE)
    except GLib.Error as error:
        log(f"mises à jour : {argv[0]} non lancé ({error.message})")
