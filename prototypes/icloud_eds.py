#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""J0 prototype: connect iCloud to Evolution Data Server.

A single sign-in with an app-specific password makes iCloud Mail, Calendars,
Reminders and Contacts appear in the elementary OS apps (Mail, Tasks and any
EDS-based calendar), with no third-party server.

Credentials are checked against Apple's CalDAV and IMAP servers, then stored in
the GNOME keyring under the schema Evolution Data Server reads. The password is
never written to disk in clear nor printed.

Usage: python3 icloud_eds.py [--remove]
"""

import argparse
import base64
import imaplib
import os
import pwd
import sys
import threading
import urllib.error
import urllib.request

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Granite", "7.0")
gi.require_version("Secret", "1")
from gi.repository import Gio, GLib, Granite, Gtk, Secret  # noqa: E402

SOURCES_DIR = os.path.join(GLib.get_user_config_dir(), "evolution", "sources")
UID_PREFIX = "covalence-icloud"
COLLECTION_UID = f"{UID_PREFIX}-collection"
MAIL_ACCOUNT_UID = f"{UID_PREFIX}-mail"
MAIL_IDENTITY_UID = f"{UID_PREFIX}-mail-identity"
MAIL_TRANSPORT_UID = f"{UID_PREFIX}-mail-transport"
APP_PASSWORD_URL = "https://account.apple.com/account/manage/section/security"

# Same schema as Evolution Data Server (e-source-credentials-provider-impl-password).
EDS_SCHEMA = Secret.Schema.new(
    "org.gnome.Evolution.Data.Source",
    Secret.SchemaFlags.DONT_MATCH_NAME,
    {"e-source-uid": Secret.SchemaAttributeType.STRING},
)


def check_caldav(user, password):
    """True when Apple's CalDAV server accepts the credentials."""
    body = (b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop>'
            b"<d:current-user-principal/></d:prop></d:propfind>")
    request = urllib.request.Request("https://caldav.icloud.com/", data=body, method="PROPFIND")
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    request.add_header("Authorization", f"Basic {token}")
    request.add_header("Depth", "0")
    request.add_header("Content-Type", "application/xml")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status in (200, 207)
    except urllib.error.HTTPError as error:
        if error.code == 401:
            return False
        raise


def imap_login_name(user, password):
    """Return the IMAP user name iCloud accepts (full address or local part), or None."""
    for candidate in (user, user.split("@")[0]):
        try:
            with imaplib.IMAP4_SSL("imap.mail.me.com", 993, timeout=20) as imap:
                imap.login(candidate, password)
                return candidate
        except imaplib.IMAP4.error:
            continue
    return None


def keyfile(sections):
    lines = []
    for name, values in sections.items():
        lines.append(f"[{name}]")
        lines.extend(f"{key}={value}" for key, value in values.items())
        lines.append("")
    return "\n".join(lines)


def source_files(apple_id, imap_user, full_name):
    auth_caldav = {"Host": "caldav.icloud.com", "Port": "443", "User": apple_id,
                   "Method": "plain/password", "RememberPassword": "true"}
    return {
        COLLECTION_UID: {
            "Data Source": {"DisplayName": "iCloud", "Enabled": "true", "Parent": ""},
            "Collection": {
                "BackendName": "webdav", "Identity": apple_id,
                "CalendarEnabled": "true", "ContactsEnabled": "true", "MailEnabled": "false",
                "CalendarUrl": "https://caldav.icloud.com/",
                "ContactsUrl": "https://contacts.icloud.com/",
            },
            "Authentication": auth_caldav,
            "Security": {"Method": "tls"},
        },
        MAIL_ACCOUNT_UID: {
            "Data Source": {"DisplayName": "iCloud", "Enabled": "true", "Parent": ""},
            "Mail Account": {"BackendName": "imapx", "IdentityUid": MAIL_IDENTITY_UID,
                             "NeedsInitialSetup": "false"},
            "Imapx Backend": {"Host": "imap.mail.me.com", "Port": "993", "User": imap_user,
                              "AuthMechanism": "PLAIN", "SecurityMethod": "ssl-on-alternate-port"},
            "Authentication": {"Host": "imap.mail.me.com", "Port": "993", "User": imap_user,
                               "Method": "PLAIN", "RememberPassword": "true"},
            "Security": {"Method": "ssl-on-alternate-port"},
            "Offline": {"StaySynchronized": "true"},
        },
        MAIL_IDENTITY_UID: {
            "Data Source": {"DisplayName": apple_id, "Enabled": "true", "Parent": MAIL_ACCOUNT_UID},
            "Mail Identity": {"Address": apple_id, "Name": full_name},
            "Mail Submission": {"TransportUid": MAIL_TRANSPORT_UID,
                                "SentFolder": f"folder://{MAIL_ACCOUNT_UID}/Sent%20Messages"},
            "Mail Composition": {"DraftsFolder": f"folder://{MAIL_ACCOUNT_UID}/Drafts"},
        },
        MAIL_TRANSPORT_UID: {
            "Data Source": {"DisplayName": "iCloud (envoi)", "Enabled": "true",
                            "Parent": MAIL_ACCOUNT_UID},
            "Mail Transport": {"BackendName": "smtp"},
            "Smtp Backend": {"Host": "smtp.mail.me.com", "Port": "587", "User": imap_user,
                             "AuthMechanism": "PLAIN",
                             "SecurityMethod": "starttls-on-standard-port"},
            "Authentication": {"Host": "smtp.mail.me.com", "Port": "587", "User": imap_user,
                               "Method": "PLAIN", "RememberPassword": "true"},
            "Security": {"Method": "starttls-on-standard-port"},
        },
    }


def install(apple_id, imap_user, full_name, password):
    os.makedirs(SOURCES_DIR, exist_ok=True)
    # Secrets first: the registry asks for them as soon as a source file appears.
    for uid in (COLLECTION_UID, MAIL_ACCOUNT_UID, MAIL_TRANSPORT_UID):
        Secret.password_store_sync(
            EDS_SCHEMA, {"e-source-uid": uid}, Secret.COLLECTION_DEFAULT,
            f"Evolution Data Source « iCloud » ({uid})", password, None,
        )
    for uid, sections in source_files(apple_id, imap_user, full_name).items():
        path = os.path.join(SOURCES_DIR, f"{uid}.source")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(keyfile(sections))
        os.chmod(path, 0o600)


def remove():
    removed = 0
    for uid in (COLLECTION_UID, MAIL_ACCOUNT_UID, MAIL_IDENTITY_UID, MAIL_TRANSPORT_UID):
        path = os.path.join(SOURCES_DIR, f"{uid}.source")
        if os.path.exists(path):
            os.remove(path)
            removed += 1
        Secret.password_clear_sync(EDS_SCHEMA, {"e-source-uid": uid}, None)
    print(f"[covalence] {removed} source(s) iCloud retirée(s), secrets effacés")


class SignInWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Connecter iCloud", resizable=False)
        self.set_default_size(420, -1)
        header = Gtk.HeaderBar()
        header.add_css_class("flat")
        self.set_titlebar(header)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_start=24, margin_end=24, margin_bottom=24)
        self.set_child(box)

        title = Gtk.Label(label="Connecter iCloud", xalign=0)
        title.add_css_class(Granite.STYLE_CLASS_H2_LABEL)
        box.append(title)
        intro = Gtk.Label(
            label=("Mail, calendriers, rappels et contacts iCloud apparaîtront dans les applis "
                   "d'elementary. Utilisez un mot de passe pour app, jamais celui de votre "
                   "identifiant Apple."),
            wrap=True, xalign=0, max_width_chars=48,
        )
        intro.add_css_class(Granite.STYLE_CLASS_DIM_LABEL)
        box.append(intro)

        self.apple_id = self._field(box, "Identifiant Apple (adresse iCloud)", Gtk.Entry())
        self.apple_id.set_input_purpose(Gtk.InputPurpose.EMAIL)
        self.full_name = self._field(box, "Nom affiché dans vos e-mails", Gtk.Entry())
        self.full_name.set_text(pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0])
        self.password = self._field(box, "Mot de passe pour app", Gtk.PasswordEntry())
        self.password.set_show_peek_icon(True)
        self.password.connect("activate", lambda *_: self._connect())

        link = Gtk.LinkButton(uri=APP_PASSWORD_URL, label="Créer un mot de passe pour app…",
                              halign=Gtk.Align.START)
        box.append(link)

        self.status = Gtk.Label(wrap=True, xalign=0, visible=False)
        box.append(self.status)

        buttons = Gtk.Box(spacing=6, halign=Gtk.Align.END, margin_top=12)
        cancel = Gtk.Button(label="Annuler")
        cancel.connect("clicked", lambda *_: self.close())
        self.connect_button = Gtk.Button(label="Connecter")
        self.connect_button.add_css_class(Granite.STYLE_CLASS_SUGGESTED_ACTION)
        self.connect_handler = self.connect_button.connect("clicked", lambda *_: self._connect())
        self.spinner = Gtk.Spinner()
        buttons.append(self.spinner)
        buttons.append(cancel)
        buttons.append(self.connect_button)
        box.append(buttons)

    @staticmethod
    def _field(box, label, entry):
        caption = Gtk.Label(label=label, xalign=0)
        caption.add_css_class(Granite.STYLE_CLASS_SMALL_LABEL)
        box.append(caption)
        box.append(entry)
        return entry

    def _set_status(self, text, error=False):
        self.status.set_label(text)
        self.status.set_visible(bool(text))
        if error:
            self.status.add_css_class(Granite.STYLE_CLASS_ERROR)
        else:
            self.status.remove_css_class(Granite.STYLE_CLASS_ERROR)

    def _connect(self):
        apple_id = self.apple_id.get_text().strip()
        password = self.password.get_text().replace(" ", "")
        full_name = self.full_name.get_text().strip() or apple_id
        if "@" not in apple_id or not password:
            self._set_status("Renseignez l'identifiant Apple et le mot de passe pour app.", True)
            return
        self.connect_button.set_sensitive(False)
        self.spinner.start()
        self._set_status("Vérification auprès d'iCloud…")
        threading.Thread(target=self._worker, args=(apple_id, full_name, password),
                         daemon=True).start()

    def _worker(self, apple_id, full_name, password):
        try:
            if not check_caldav(apple_id, password):
                GLib.idle_add(self._done, "Identifiant ou mot de passe pour app refusé par iCloud.", True)
                return
            imap_user = imap_login_name(apple_id, password)
            if imap_user is None:
                GLib.idle_add(self._done, "Calendriers OK, mais iCloud Mail refuse la connexion. "
                                          "iCloud Mail est-il activé sur ce compte ?", True)
                return
            install(apple_id, imap_user, full_name, password)
            print("[covalence] sources iCloud créées (calendriers, rappels, contacts, mail)", flush=True)
            GLib.idle_add(self._done, "iCloud est connecté. Ouvrez Mail ou Tâches.", False)
        except Exception as error:  # réseau, trousseau verrouillé…
            GLib.idle_add(self._done, f"Échec : {error.__class__.__name__}", True)

    def _done(self, message, error):
        self.spinner.stop()
        self._set_status(message, error)
        self.connect_button.set_sensitive(error)
        if not error:
            self.connect_button.set_label("Fermer")
            self.connect_button.disconnect(self.connect_handler)
            self.connect_button.connect("clicked", lambda *_: self.close())
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--remove", action="store_true", help="retirer les sources iCloud de Covalence")
    args = parser.parse_args()
    if args.remove:
        remove()
        return 0

    app = Gtk.Application(application_id="io.github.melvincouwez.Covalence.iCloudProbe",
                          flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def on_activate(application):
        Granite.init()
        settings = Gtk.Settings.get_default()
        granite_settings = Granite.Settings.get_default()
        settings.set_property("gtk-application-prefer-dark-theme",
                              granite_settings.get_prefers_color_scheme() == Granite.SettingsColorScheme.DARK)
        SignInWindow(application).present()

    app.connect("activate", on_activate)
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
