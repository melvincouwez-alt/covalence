# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Keeps Covalence's iCloud accounts in Evolution Data Server authenticated.

EDS asks a UI client for credentials (credentials-required) and does not read
the keyring on its own when no such client runs. Covalence answers for its own
sources only (uid prefix covalence-icloud or, before the rename, tandem-icloud; and the children of its collection)
with the app-specific password stored in the keyring by the sign-in helper.
The password is never logged.
"""

import time

import gi

gi.require_version("EDataServer", "1.2")
gi.require_version("Secret", "1")
from gi.repository import EDataServer, Secret  # noqa: E402

from .i18n import _  # noqa: E402
from .util import ICLOUD_UID_PREFIXES, icloud_uid_prefix, log  # noqa: E402

EDS_SCHEMA = Secret.Schema.new(
    "org.gnome.Evolution.Data.Source",
    Secret.SchemaFlags.DONT_MATCH_NAME,
    {"e-source-uid": Secret.SchemaAttributeType.STRING},
)
MAX_ATTEMPTS = 3  # per source and per 10 minutes, to never hammer Apple's servers
Reason = EDataServer.SourceCredentialsReason


class ICloud:
    def __init__(self, notifier, on_state):
        self.notifier = notifier
        self.on_state = on_state
        self.registry = None
        self.handlers = []
        self.enabled = False
        self.attempts = {}  # uid -> [monotonic times]
        self.rejected = False
        self.warned = False
        self.problems = set()  # uids EDS asked about and Covalence could not satisfy

    def enable(self):
        if self.enabled:
            return
        self.enabled = True
        if self.registry is None:
            EDataServer.SourceRegistry.new(None, self._on_registry)
        else:
            self._connect()

    def disable(self):
        self.enabled = False
        for handler in self.handlers:
            self.registry.disconnect(handler)
        self.handlers = []
        self.on_state()

    def _on_registry(self, _source, result):
        try:
            self.registry = EDataServer.SourceRegistry.new_finish(result)
        except Exception as error:  # GLib.Error: registry service missing
            log(f"iCloud : Evolution Data Server indisponible ({error})")
            return
        if self.enabled:
            self._connect()

    def _connect(self):
        r = self.registry
        self.handlers = [
            r.connect("credentials-required", self._on_credentials_required),
            r.connect("source-added", lambda *_: self.on_state()),
            r.connect("source-removed", lambda *_: self.on_state()),
            r.connect("source-changed", lambda *_: self.on_state()),
        ]
        Status = EDataServer.SourceConnectionStatus
        waiting = [s for s in self._our_sources()
                   if s.get_connection_status() == Status.AWAITING_CREDENTIALS]
        if waiting:
            log(f"iCloud : {len(waiting)} source(s) en attente d'authentification")
        for source in waiting:
            self._authenticate(source)
        self.on_state()

    def reset(self):
        """The sign-in helper rewrote the account: forget failures, try again."""
        self.rejected, self.warned = False, False
        self.problems.clear()
        self.attempts.clear()
        if self.enabled and self.registry is not None:
            for handler in self.handlers:
                self.registry.disconnect(handler)
            self._connect()
        self.on_state()

    # --- ownership -------------------------------------------------------------

    def _secret_uid(self, source):
        """The uid under which Covalence stored the password for this source, or None."""
        current, hops = source, 0
        while current is not None and hops < 5:
            if current.get_uid().startswith(ICLOUD_UID_PREFIXES):
                # Identities have no secret of their own: use the account's.
                return current.get_uid() if not current.get_uid().endswith("-identity") \
                    else current.get_parent()
            parent = current.get_parent()
            current = self.registry.ref_source(parent) if parent else None
            hops += 1
        return None

    def _our_sources(self):
        if self.registry is None:
            return []
        return [s for s in self.registry.list_sources(None) if self._secret_uid(s)]

    # --- authentication --------------------------------------------------------------

    def _on_credentials_required(self, _registry, source, reason, _pem, _errors, _error):
        if not self.enabled:
            return
        uid = self._secret_uid(source)
        if uid is None:
            return  # not ours: leave other accounts to their own clients
        name = source.get_display_name()
        if reason == Reason.REQUIRED:
            self._authenticate(source)
        elif reason == Reason.REJECTED:
            log(f"iCloud : mot de passe refusé pour « {name} »")
            self.rejected = True
            self._warn(_("iCloud a refusé le mot de passe pour app"),
                       _("Créez un nouveau mot de passe pour app puis reconnectez iCloud dans Covalence."))
            self.on_state()
        elif reason == Reason.SSL_FAILED:
            log(f"iCloud : certificat refusé pour « {name} »")
            self.problems.add(source.get_uid())
            self.on_state()
        else:
            log(f"iCloud : « {name} » en erreur ({reason.value_nick})")

    def _authenticate(self, source):
        uid = source.get_uid()
        now = time.monotonic()
        recent = [t for t in self.attempts.get(uid, []) if now - t < 600]
        if len(recent) >= MAX_ATTEMPTS:
            log(f"iCloud : trop de tentatives pour « {source.get_display_name()} », pause")
            self.problems.add(uid)
            self.on_state()
            return
        self.attempts[uid] = recent + [now]
        secret_uid = self._secret_uid(source)

        def on_secret(_src, result):
            try:
                password = Secret.password_lookup_finish(result)
            except Exception as error:
                log(f"iCloud : trousseau inaccessible ({error.__class__.__name__})")
                return
            if not password:
                log(f"iCloud : aucun secret enregistré pour {secret_uid}")
                self.problems.add(uid)
                self.on_state()
                self._warn(_("iCloud n'est plus connecté"),
                           _("Reconnectez iCloud depuis Covalence."))
                return
            credentials = EDataServer.NamedParameters.new()
            credentials.set(EDataServer.SOURCE_CREDENTIAL_PASSWORD, password)
            user = self._user(source)
            if user:
                credentials.set(EDataServer.SOURCE_CREDENTIAL_USERNAME, user)
            source.invoke_authenticate(credentials, None, self._on_authenticated, None)
            credentials.clear()

        Secret.password_lookup(EDS_SCHEMA, {"e-source-uid": secret_uid}, None, on_secret)

    def _user(self, source):
        current = source
        for _attempt in range(5):
            if current is None:
                return ""
            if current.has_extension(EDataServer.SOURCE_EXTENSION_AUTHENTICATION):
                user = current.get_extension(EDataServer.SOURCE_EXTENSION_AUTHENTICATION).get_user()
                if user:
                    return user
            parent = current.get_parent()
            current = self.registry.ref_source(parent) if parent else None
        return ""

    def _on_authenticated(self, source, result, _data):
        try:
            source.invoke_authenticate_finish(result)
            log(f"iCloud : « {source.get_display_name()} » authentifiée")
            self.rejected = False
            self.problems.discard(source.get_uid())
        except Exception as error:
            log(f"iCloud : authentification de « {source.get_display_name()} » échouée "
                f"({getattr(error, 'message', error.__class__.__name__)})")
            self.problems.add(source.get_uid())
        self.on_state()

    def _warn(self, summary, body):
        if self.warned:
            return
        self.warned = True
        self.notifier.notify("Covalence", "dialog-password", summary, body, own=True)

    # --- state -----------------------------------------------------------------

    def state(self):
        """absent | connected | attention | rejected | disabled | unavailable."""
        if not self.enabled:
            return "disabled"
        if self.registry is None:
            return "unavailable"
        if self.registry.ref_source(f"{icloud_uid_prefix()}-collection") is None:
            return "absent"
        if self.rejected:
            return "rejected"
        # The connection status alone is not reliable: EDS leaves sources that no
        # client has opened in awaiting-credentials after a successful answer.
        if self.problems:
            return "attention"
        return "connected"
