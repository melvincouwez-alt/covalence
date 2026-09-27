#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Covalence iCloud Drive sign-in: connect iCloud Drive (or iCloud Photos) through rclone.

Apple's app-specific passwords do not open iCloud Drive: rclone's iclouddrive
backend signs in like icloud.com does, with the Apple ID password and a
two-factor code shown on the user's trusted devices. It only works when
Advanced Data Protection is off.

Secrets:
- The Apple ID password is typed here only, sent to rclone over a private
  Unix socket (never on a command line, never logged) and kept by rclone in
  its config, obscured.
- That config (~/.config/covalence/rclone.conf, 0600) is encrypted by rclone
  with a random key stored in the GNOME keyring; rclone reads the key with
  secret-tool (--password-command).

iCloud Photos uses the same backend (service=photos) in its own remote,
mounted read-only: albums are folders, "All Photos" holds the whole library.

Usage: covalence-icloud-drive [--photos] [--remove | --bookmark]
"""

import argparse
import http.client
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Granite", "7.0")
from gi.repository import Gio, GLib, Granite, Gtk  # noqa: E402

from .i18n import _, ngettext  # noqa: E402
from .util import icloud_uid_prefix  # noqa: E402

PRIVATE_RCLONE = os.path.join(os.path.expanduser("~"), ".local", "libexec", "covalence", "rclone")
# iCloud Drive and iCloud Photos need rclone 1.69 or later (Ubuntu 24.04 ships 1.60).
RCLONE_MIN = (1, 69)


def rclone_version(path):
    try:
        out = subprocess.run([path, "version"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.match(r"rclone v(\d+)\.(\d+)", out)
    return (int(match.group(1)), int(match.group(2))) if match else None


def find_rclone():
    """The system rclone when recent enough, else Covalence's own copy (rclone_fetch.py)."""
    system = shutil.which("rclone")
    if system and (rclone_version(system) or (0, 0)) >= RCLONE_MIN:
        return system
    return PRIVATE_RCLONE


RCLONE = find_rclone()
CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "covalence")
CONFIG = os.path.join(CONFIG_DIR, "rclone.conf")
KEY_ATTRS = ["application", "io.github.melvincouwez.Covalence", "kind", "rclone-config"]
PASSWORD_COMMAND = "secret-tool lookup " + " ".join(KEY_ATTRS)
APP_ID = "io.github.melvincouwez.Covalence.DriveSignin"
PHOTOS_APP_ID = "io.github.melvincouwez.Covalence.PhotosSignin"
BOOKMARKS = os.path.join(GLib.get_user_config_dir(), "gtk-3.0", "bookmarks")


def _pictures_dir():
    return GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) \
        or os.path.join(os.path.expanduser("~"), "Images")


class Service:
    """One iCloud service mounted by Covalence: its rclone remote, unit, options file and folder."""

    def __init__(self, key, name, remote, root, unit, env_key, default_dir):
        self.key = key
        self.name = name              # "iCloud Drive", also the bookmark label
        self.remote = remote          # rclone remote name
        self.root = root              # folder listed to check the connection
        self.unit = unit
        self.env = os.path.join(CONFIG_DIR, key + ".env")
        self.env_key = env_key
        self.default_dir = default_dir


SERVICES = {
    "drive": Service("drive", "iCloud Drive", "icloud", "", "covalence-icloud-drive.service",
                     "COVALENCE_DRIVE_DIR", os.path.join(os.path.expanduser("~"), "iCloud Drive")),
    "photos": Service("photos", "iCloud Photos", "icloud-photos", "PrimarySync",
                      "covalence-icloud-photos.service", "COVALENCE_PHOTOS_DIR",
                      os.path.join(_pictures_dir(), "iCloud Photos")),
}
SERVICE = SERVICES["drive"]  # chosen by --photos in main()


def mount_point():
    """Folder chosen in the service's options, else its default folder."""
    try:
        with open(SERVICE.env, encoding="utf-8") as f:
            for line in f:
                if line.startswith(SERVICE.env_key + "="):
                    return line.split("=", 1)[1].strip().strip('"')
    except FileNotFoundError:
        pass
    return SERVICE.default_dir
def collection_source():
    return os.path.join(GLib.get_user_config_dir(), "evolution", "sources",
                        f"{icloud_uid_prefix()}-collection.source")


def rclone_env():
    env = dict(os.environ)
    env.pop("RCLONE_CONFIG_PASS", None)
    return env


def rclone(*args, check=True):
    return subprocess.run([RCLONE, "--config", CONFIG, "--password-command", PASSWORD_COMMAND,
                           "--ask-password=false", *args],
                          capture_output=True, text=True, env=rclone_env(), check=check)


def ensure_key():
    """Random config key in the keyring (created once)."""
    found = subprocess.run(["secret-tool", "lookup", *KEY_ATTRS], capture_output=True, text=True)
    if found.returncode == 0 and found.stdout.strip():
        return
    subprocess.run(["secret-tool", "store", "--label", "Covalence : clé de la configuration iCloud Drive",
                    *KEY_ATTRS], input=secrets.token_urlsafe(32), text=True, check=True)


def ensure_config():
    """Empty, encrypted rclone config owned by Covalence."""
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    ensure_key()
    if not os.path.exists(CONFIG) or os.path.getsize(CONFIG) == 0:
        fd = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.close(fd)
        rclone("config", "encryption", "set")
    os.chmod(CONFIG, 0o600)


def default_apple_id():
    """The Apple ID Covalence already uses for iCloud (EDS collection), if any."""
    keyfile = GLib.KeyFile()
    try:
        keyfile.load_from_file(collection_source(), GLib.KeyFileFlags.NONE)
        return keyfile.get_string("Authentication", "User")
    except GLib.Error:
        return ""


def set_bookmark(present):
    """The service in the sidebar of Files (GTK bookmarks), at the current mount point."""
    try:
        with open(BOOKMARKS, encoding="utf-8") as f:
            lines = [line.rstrip("\n") for line in f if line.strip()]
    except FileNotFoundError:
        lines = []
    # Drop any earlier bookmark of this service (the folder may have moved).
    label = " " + SERVICE.name
    kept = [line for line in lines if not line.endswith(label)]
    if present:
        kept.append(GLib.filename_to_uri(mount_point(), None) + label)
    if kept != lines:
        os.makedirs(os.path.dirname(BOOKMARKS), exist_ok=True)
        with open(BOOKMARKS, "w", encoding="utf-8") as f:
            f.write("".join(line + "\n" for line in kept))


def enable_mount():
    if not os.path.exists(SERVICE.env):
        # The unit's default folder name is a guess ("Images"): write the real one.
        os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
        fd = os.open(SERVICE.env, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"# Written by Covalence ({SERVICE.name}).\n{SERVICE.env_key}=\"{SERVICE.default_dir}\"\n")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "--now", SERVICE.unit], check=True,
                   capture_output=True)
    set_bookmark(True)


def disable_mount():
    subprocess.run(["systemctl", "--user", "disable", "--now", SERVICE.unit], check=False,
                   capture_output=True)
    set_bookmark(False)


class RcloneRC:
    """rclone rcd on a private Unix socket: config calls without secrets on argv."""

    def __init__(self):
        runtime = GLib.get_user_runtime_dir()  # 0700, this user only
        self.dir = tempfile.mkdtemp(prefix="covalence-rclone-", dir=runtime)
        self.path = os.path.join(self.dir, "rc.sock")
        self.process = subprocess.Popen(
            [RCLONE, "rcd", "--config", CONFIG, "--password-command", PASSWORD_COMMAND,
             "--ask-password=false", "--rc-addr", f"unix://{self.path}", "--rc-no-auth"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=rclone_env())
        for _attempt in range(100):
            if os.path.exists(self.path):
                return
            time.sleep(0.05)
        raise RuntimeError("rclone rcd did not start")

    def call(self, method, params, timeout=90):
        conn = http.client.HTTPConnection("localhost", timeout=timeout)
        conn.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.sock.settimeout(timeout)
        conn.sock.connect(self.path)
        body = json.dumps(params)
        conn.request("POST", "/" + method, body, {"Content-Type": "application/json"})
        response = conn.getresponse()
        data = json.loads(response.read() or b"{}")
        conn.close()
        if response.status != 200:
            raise RuntimeError(data.get("error") or f"HTTP {response.status}")
        return data

    def close(self):
        self.process.terminate()
        try:
            self.process.wait(5)
        except subprocess.TimeoutExpired:
            self.process.kill()
        for name in os.listdir(self.dir):
            os.unlink(os.path.join(self.dir, name))
        os.rmdir(self.dir)


def friendly(error):
    text = str(error)
    lowered = text.lower()
    if "adp" in lowered or "advanced data protection" in lowered or "pcs" in lowered:
        return _("Apple refuse l'accès : la Protection avancée des données semble active sur ce "
                 "compte. Désactivez-la sur l'iPhone (Réglages › votre nom › iCloud) puis réessayez.")
    if "401" in text or "invalid" in lowered or "incorrect" in lowered or "unauthorized" in lowered:
        return _("Identifiant ou mot de passe refusé par Apple.")
    if "2fa" in lowered or "code" in lowered:
        return _("Code de vérification refusé ou expiré. Recommencez la connexion.")
    return _("Connexion impossible : {error}").format(error=text.splitlines()[0][:200])


class Window(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=SERVICE.name, default_width=460, resizable=False)
        self.rc = None
        self.state = ""
        header = Gtk.HeaderBar()
        header.add_css_class("flat")
        self.set_titlebar(header)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vhomogeneous=False)
        self.stack.add_named(self._rclone_page(), "rclone")
        self.stack.add_named(self._credentials_page(), "credentials")
        self.stack.add_named(self._code_page(), "code")
        self.stack.add_named(self._busy_page(), "busy")
        self.done = Granite.Placeholder(title=_("{service} est connecté").format(service=SERVICE.name),
                                        icon=Gio.ThemedIcon.new("process-completed"))
        self.stack.add_named(self.done, "done")

        self.error = Gtk.Label(wrap=True, xalign=0, visible=False)
        self.error.add_css_class("error")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_start=24, margin_end=24, margin_bottom=24)
        box.append(self.stack)
        box.append(self.error)
        self.set_child(box)
        if not os.access(RCLONE, os.X_OK):
            self.stack.set_visible_child_name("rclone")
        else:
            self.stack.set_visible_child_name("credentials")
        self.connect("close-request", lambda *_: self._cleanup() or False)

    # --- pages -----------------------------------------------------------------

    def _title(self, text, sub):
        title = Gtk.Label(label=text, xalign=0, wrap=True)
        title.add_css_class("title-2")
        hint = Gtk.Label(label=sub, xalign=0, wrap=True, use_markup=True)
        hint.add_css_class("dim-label")
        return title, hint

    def _credentials_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for widget in self._title(
                _("Connecter {service}").format(service=SERVICE.name),
                _("Le <b>mot de passe pour app</b> ne suffit pas pour {service} : saisissez le "
                  "mot de passe de votre <b>compte Apple</b>. Apple enverra ensuite un code sur "
                  "votre iPhone. La <b>Protection avancée des données</b> doit être "
                  "désactivée.").format(service=SERVICE.name)):
            box.append(widget)
        self.apple_id = Gtk.Entry(text=default_apple_id(), placeholder_text=_("Identifiant Apple"),
                                  input_purpose=Gtk.InputPurpose.EMAIL)
        self.password = Gtk.PasswordEntry(show_peek_icon=True, placeholder_text=_("Mot de passe du compte Apple"))
        self.password.connect("activate", lambda *_: self._sign_in())
        note = Gtk.Label(
            label=_("Le mot de passe va directement à rclone, qui le garde dans une configuration "
                    "chiffrée dont la clé est dans votre trousseau. Il n'est jamais écrit en clair "
                    "ni transmis ailleurs qu'à Apple."), wrap=True, xalign=0)
        note.add_css_class("dim-label")
        note.add_css_class("small-label")
        risks = Gtk.Label(
            label=_("{service} passe par rclone, un outil tiers qui se connecte comme le site "
                    "icloud.com, avec le mot de passe de votre compte Apple. Apple ne propose pas "
                    "officiellement cet accès : ses conditions d'utilisation d'iCloud limitent l'accès "
                    "automatisé et l'autorisent à suspendre un compte. Il faut aussi désactiver la "
                    "Protection avancée des données, ce qui réduit le chiffrement de bout en bout de "
                    "vos données iCloud. Vous utilisez cette fonction à vos risques.").format(
                        service=SERVICE.name),
            wrap=True, xalign=0)
        risks.add_css_class("small-label")
        self.accept = Gtk.CheckButton(label=_("J'ai compris et j'accepte ces risques"))
        self.sign_in_button = Gtk.Button(label=_("Se connecter"), halign=Gtk.Align.END, sensitive=False)
        self.sign_in_button.add_css_class("suggested-action")
        self.sign_in_button.connect("clicked", lambda *_: self._sign_in())
        self.accept.connect("toggled", lambda check: self.sign_in_button.set_sensitive(check.get_active()))
        credit = Gtk.Label(
            label=_('Fonctionne grâce à <a href="https://github.com/rclone/rclone">rclone</a> '
                    "(Nick Craig-Wood et contributeurs, licence MIT)."),
            use_markup=True, wrap=True, xalign=0)
        credit.add_css_class("dim-label")
        credit.add_css_class("small-label")
        for widget in (self.apple_id, self.password, note, risks, self.accept,
                       self.sign_in_button, credit):
            box.append(widget)
        return box

    def _rclone_page(self):
        """rclone is missing or too old: offer to download the official build."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for widget in self._title(
                _("rclone est nécessaire"),
                _("{service} passe par rclone 1.69 ou plus récent, absent de ce système. "
                  "Covalence peut télécharger la version officielle depuis "
                  '<a href="https://rclone.org">rclone.org</a> (licence MIT, environ 25 Mo) et '
                  "vérifier son empreinte avant de l'installer pour vous seul.").format(
                      service=SERVICE.name)):
            box.append(widget)
        self.fetch_bar = Gtk.ProgressBar(visible=False)
        button = Gtk.Button(label=_("Télécharger rclone"), halign=Gtk.Align.END)
        button.add_css_class("suggested-action")
        button.connect("clicked", lambda b: self._fetch_rclone(b))
        box.append(self.fetch_bar)
        box.append(button)
        return box

    def _fetch_rclone(self, button):
        from . import rclone_fetch
        button.set_sensitive(False)
        self.error.set_visible(False)
        self.fetch_bar.set_visible(True)

        def progress(percent):
            GLib.idle_add(lambda: self.fetch_bar.set_fraction(percent / 100) or False)

        def thread():
            try:
                rclone_fetch.fetch(RCLONE, progress)
                error = None
            except Exception as e:  # noqa: BLE001 - shown to the user
                error = e
            GLib.idle_add(lambda: done(error) or False)

        def done(error):
            button.set_sensitive(True)
            self.fetch_bar.set_visible(False)
            if error:
                self.error.set_label(_("Le téléchargement n'a pas abouti : {error}").format(error=error))
                self.error.set_visible(True)
            else:
                self.stack.set_visible_child_name("credentials")

        threading.Thread(target=thread, daemon=True).start()

    def _code_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        title, self.code_hint = self._title(_("Code de vérification"),
                                            _("Saisissez le code à six chiffres affiché sur votre iPhone."))
        box.append(title)
        box.append(self.code_hint)
        self.code = Gtk.Entry(placeholder_text="123456", input_purpose=Gtk.InputPurpose.DIGITS,
                              max_length=6, xalign=0.5)
        self.code.connect("activate", lambda *_: self._send_code())
        button = Gtk.Button(label=_("Valider"), halign=Gtk.Align.END)
        button.add_css_class("suggested-action")
        button.connect("clicked", lambda *_: self._send_code())
        box.append(self.code)
        box.append(button)
        return box

    def _busy_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=24, margin_bottom=24)
        spinner = Gtk.Spinner(spinning=True, width_request=32, height_request=32)
        self.busy_label = Gtk.Label(label=_("Connexion à Apple…"))
        box.append(spinner)
        box.append(self.busy_label)
        return box

    # --- flow ------------------------------------------------------------------------

    def _run(self, label, work, then):
        self.error.set_visible(False)
        self.busy_label.set_label(label)
        self.stack.set_visible_child_name("busy")

        def thread():
            try:
                result, error = work(), None
            except Exception as e:  # noqa: BLE001 - shown to the user, never logged
                result, error = None, e
            GLib.idle_add(lambda: then(result, error) or False)

        threading.Thread(target=thread, daemon=True).start()

    def _fail(self, error, page):
        self.error.set_label(friendly(error))
        self.error.set_visible(True)
        self.stack.set_visible_child_name(page)

    def _sign_in(self):
        apple_id = self.apple_id.get_text().strip()
        password = self.password.get_text()
        if not apple_id or not password or not self.accept.get_active():
            return
        self.password.set_text("")

        def work():
            ensure_config()
            if self.rc is None:
                self.rc = RcloneRC()
            if SERVICE.remote in self.rc.call("config/listremotes", {}).get("remotes", []):
                self.rc.call("config/delete", {"name": SERVICE.remote})
            return self.rc.call("config/create", {
                "name": SERVICE.remote, "type": "iclouddrive",
                "parameters": {"apple_id": apple_id, "password": password, "service": SERVICE.key},
                "opt": {"obscure": True, "nonInteractive": True},
            })

        self._run(_("Connexion à Apple…"), work, self._after_step)

    def _send_code(self):
        code = "".join(c for c in self.code.get_text() if c.isdigit())
        if len(code) != 6:
            return
        self.code.set_text("")
        state = self.state

        def work():
            return self.rc.call("config/update", {
                "name": SERVICE.remote, "parameters": {},
                "opt": {"continue": True, "state": state, "result": code, "nonInteractive": True},
            })

        self._run(_("Vérification du code…"), work, self._after_step)

    def _after_step(self, answer, error):
        if error:
            self._fail(error, "credentials")
            return
        if answer.get("Error"):
            self._fail(answer["Error"], "credentials")
            return
        self.state = answer.get("State") or ""
        option = answer.get("Option") or {}
        if self.state and option:
            help_text = (option.get("Help") or "").strip()
            if help_text:
                self.code_hint.set_label(GLib.markup_escape_text(help_text.splitlines()[0]))
            self.stack.set_visible_child_name("code")
            self.code.grab_focus()
            return
        self._run(_("Lecture d'{service}…").format(service=SERVICE.name), self._check, self._after_check)

    def _check(self):
        listing = self.rc.call("operations/list", {"fs": SERVICE.remote + ":", "remote": SERVICE.root},
                               timeout=120)
        return len(listing.get("list", []))

    def _after_check(self, count, error):
        if error:
            self._fail(error, "credentials")
            return
        self._cleanup()
        try:
            enable_mount()
            folder = os.path.basename(mount_point())
            where = (_("Il apparaît dans Fichiers, dans le dossier « {folder} » (lecture seule).")
                     if SERVICE.key == "photos"
                     else _("Il apparaît dans Fichiers, dans le dossier « {folder} ».")).format(folder=folder)
        except subprocess.CalledProcessError:
            where = _("Le dossier « {service} » n'a pas pu être monté : voir « journalctl --user -u "
                      "{unit} ».").format(service=SERVICE.name, unit=SERVICE.unit)
        found = (ngettext("{count} album", "{count} albums", count) if SERVICE.key == "photos"
                 else ngettext("{count} élément à la racine", "{count} éléments à la racine",
                               count)).format(count=count)
        self.done.set_description(f"{found}. {where}")
        self.stack.set_visible_child_name("done")

    def _cleanup(self):
        if self.rc is not None:
            self.rc.close()
            self.rc = None


def remove():
    disable_mount()
    if os.path.exists(CONFIG) and os.access(RCLONE, os.X_OK):
        rclone("config", "delete", SERVICE.remote, check=False)
    print(_("{service} retiré de la configuration de Covalence.").format(service=SERVICE.name))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--photos", action="store_true", help="iCloud Photos au lieu d'iCloud Drive")
    parser.add_argument("--remove", action="store_true", help="oublier la connexion")
    parser.add_argument("--bookmark", action="store_true",
                        help="mettre à jour le signet de Fichiers après un changement d'emplacement")
    args = parser.parse_args()
    global SERVICE
    SERVICE = SERVICES["photos" if args.photos else "drive"]
    if args.bookmark:
        set_bookmark(True)
        return 0
    if args.remove:
        return remove()
    app = Gtk.Application(application_id=APP_ID if not args.photos else PHOTOS_APP_ID)
    app.connect("startup", lambda a: Granite.init())
    app.connect("activate", lambda a: (a.get_active_window() or Window(a)).present())
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
