# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Optional apps Covalence offers to install: Agenda and Cassette.

Their packages are published with Covalence's own releases on GitHub, beside
covalence_X.Y.Z_amd64.deb. Installing one goes the same way as an update of
Covalence (updates.py): the newest release carrying the package is found, its .deb
is downloaded to ~/.cache/covalence/apps, checked against the SHA-256 digest GitHub
publishes, then `pkexec covalence-install-update <deb> <sha256> <package>` installs
it; that helper only accepts the packages it names. Nothing happens without the
user's click, and nothing is fetched until the user opens the page offering them.
"""

import os
import threading

from gi.repository import Gio, GLib

from .i18n import _
from .updates import (RELEASES, _arch, _get_json, deb_asset, download_verified,
                      installer_path, version_key)
from .util import log

# package -> desktop id of the app it installs
CATALOG = {"agenda": "io.github.melvincouwez.Agenda",
           "cassette": "io.github.melvincouwez.Cassette"}

TYPES = {"state": "s", "version": "s", "size": "x", "progress": "d", "error": "s",
         "installed": "b"}


def newest_with(releases, package, arch):
    """(release, url, size, sha) of the newest non-draft release carrying the package."""
    best = None
    for release in releases or []:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        url, size, sha = deb_asset(release, arch, package)
        if not url:
            continue
        key = version_key(release.get("tag_name") or "")
        if key is not None and (best is None or key > best[0]):
            best = (key, release, url, size, sha)
    return best[1:] if best else None


def _installed(package):
    return Gio.DesktopAppInfo.new(CATALOG[package] + ".desktop") is not None


class OptionalApps:
    def __init__(self, on_changed, fetch=_get_json, cache_dir=None):
        self.on_changed = on_changed
        self.fetch = fetch
        self.dir = cache_dir or os.path.join(GLib.get_user_cache_dir(), "covalence", "apps")
        self.found = {}                               # package -> (release, url, size, sha)
        self.states = {p: {"state": "idle", "progress": 0.0, "error": ""} for p in CATALOG}
        self.checking = False

    def state(self):
        result = {}
        for package in CATALOG:
            found = self.found.get(package)
            version = (found[0].get("tag_name") or "").lstrip("vV") if found else ""
            entry = dict(self.states[package], version=version, size=found[2] if found else 0,
                         installed=_installed(package))
            result[package] = {k: v for k, v in entry.items() if k in TYPES}
        return result

    def _changed(self):
        if self.on_changed:
            self.on_changed()

    def check(self):
        """Look for the packages in Covalence's releases (one GET, in a thread)."""
        if self.checking:
            return
        self.checking = True

        def job():
            try:
                releases = self.fetch(RELEASES)
                error = None
            except Exception as failure:
                releases, error = None, type(failure).__name__
            GLib.idle_add(lambda: self._checked(releases, error) and False)

        threading.Thread(target=job, name="covalence-apps-check", daemon=True).start()

    def _checked(self, releases, error):
        self.checking = False
        if error:
            log(f"apps : liste des versions indisponible ({error})")
        else:
            for package in CATALOG:
                found = newest_with(releases, package, _arch())
                if found:
                    self.found[package] = found
        self._changed()

    def install(self, package, on_done):
        """on_done(error or None); progress and outcome also go through state()."""
        if package not in CATALOG:
            return on_done(_("application inconnue"))
        state = self.states[package]
        if state["state"] in ("downloading", "installing"):
            return on_done(None)
        found = self.found.get(package)
        if not found or not found[3]:
            return on_done(_("pas de paquet vérifiable pour cette application"))
        _release, url, size, sha = found
        if not url.startswith(("https://github.com/", "https://objects.githubusercontent.com/")):
            return on_done(_("adresse de téléchargement inattendue"))
        state.update(state="downloading", progress=0.0, error="")
        self._changed()
        target = os.path.join(self.dir, url.rsplit("/", 1)[-1])

        def report(fraction):
            state["progress"] = fraction * 0.9
            self._changed()
            return False

        def job():
            error = None
            try:
                os.makedirs(self.dir, mode=0o700, exist_ok=True)
                download_verified(url, size, sha, target, report)
            except Exception as failure:
                error = str(failure) if isinstance(failure, ValueError) else type(failure).__name__
            GLib.idle_add(lambda: self._downloaded(package, target, sha, error, on_done) and False)

        threading.Thread(target=job, name="covalence-apps-download", daemon=True).start()

    def _downloaded(self, package, target, sha, error, on_done):
        state = self.states[package]
        if error:
            return self._failed(package, _("Téléchargement impossible ({reason})").format(reason=error), on_done)
        installer = installer_path()
        if not installer:
            return self._failed(package, _("Installation impossible (programme d'installation absent)"),
                                on_done)
        state.update(state="installing", progress=0.9)
        self._changed()
        try:
            process = Gio.Subprocess.new(["pkexec", installer, target, sha, package],
                                         Gio.SubprocessFlags.STDOUT_SILENCE
                                         | Gio.SubprocessFlags.STDERR_PIPE)
        except GLib.Error as failure:
            return self._failed(package, _("Installation impossible ({reason})").format(
                reason=failure.message), on_done)

        def finished(proc, result):
            try:
                err = proc.communicate_utf8_finish(result)[-1]
            except GLib.Error as failure:
                return self._failed(package, failure.message, on_done)
            status = proc.get_exit_status()
            if status == 0:
                state.update(state="idle", progress=1.0, error="")
                log(f"apps : {package} installée")
                self._changed()
                on_done(None)
            elif status in (126, 127):
                self._failed(package, _("Installation annulée"), on_done)
            else:
                last = (err or "").strip().splitlines()[-1:] or [""]
                self._failed(package, _("Installation impossible ({reason})").format(
                    reason=last[0][:160] or status), on_done)

        process.communicate_utf8_async(None, None, finished)

    def _failed(self, package, message, on_done):
        self.states[package].update(state="error", error=message, progress=0.0)
        log(f"apps : échec de l'installation de {package}")
        self._changed()
        on_done(message)
