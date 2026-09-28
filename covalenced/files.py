# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Fichiers: LocalSend on the daemon side (see localsend.py for the protocol).

Off by default. Turned on, it listens on the local network (port 53317) and
announces "Covalence (<computer>)". Every incoming transfer is asked for in a
notification (Accepter / Refuser): a sender's identity cannot be proven on the
receiving side (see localsend.py), so no device is accepted without asking.
"""

import os
import socket
import threading
import time

from gi.repository import GLib

from . import localsend
from .i18n import _, ngettext
from .util import log

APP_ICON = "io.github.melvincouwez.Covalence"
# Types of the Files property (a{sv}).
TYPES = {"enabled": "b", "state": "s", "error": "s", "alias": "s", "folder": "s",
         "activity": "s", "progress": "d", "peers": "u", "sending": "b"}


def _dispatch(function, *args):
    GLib.idle_add(lambda: function(*args) and False)


def downloads_folder():
    base = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD) \
        or os.path.join(os.path.expanduser("~"), "Downloads")
    return os.path.join(base, "Covalence")


class Files:
    def __init__(self, config, notifier, changed):
        self.config = config
        self.notifier = notifier
        self.changed = changed
        self.receiver = None
        self.discovery = None
        self.info = None
        self.peers = {}
        self.error = ""
        self.activity = ""
        self.progress = 0.0
        self.sending = False
        self.cancel_send = False
        self.asks = {}  # session id -> notification id
        self.progress_note = 0
        self.alias = "Covalence (%s)" % (socket.gethostname().split(".")[0] or "PC")
        if self.enabled:
            GLib.idle_add(lambda: self.start() and False)

    @property
    def enabled(self):
        return self.config.boolean("files", "localsend", False)

    def state(self):
        now = time.time()
        live = [p for p in self.peers.values() if now - p["seen"] < localsend.PEER_TTL]
        state = "off"
        if self.enabled:
            state = "listening" if self.receiver else "error"
        return {"enabled": self.enabled, "state": state, "error": self.error, "alias": self.alias,
                "folder": downloads_folder(), "activity": self.activity,
                "progress": float(self.progress), "peers": len(live), "sending": self.sending}

    def list_peers(self):
        now = time.time()
        return [{"id": p["id"], "alias": p["alias"], "model": p["model"], "type": p["type"]}
                for p in sorted(self.peers.values(), key=lambda p: p["alias"].casefold())
                if now - p["seen"] < localsend.PEER_TTL]

    def set_enabled(self, enabled):
        self.config.set_boolean("files", "localsend", bool(enabled))
        if enabled:
            self.start()
        else:
            self.stop()
        self.changed()

    def start(self):
        if self.receiver is not None:
            return
        self.error = ""
        try:
            directory = os.path.join(GLib.get_user_data_dir(), "covalence", "localsend")
            cert, key, fingerprint = localsend.ensure_certificate(directory)
            identity = {"cert": cert, "key": key, "fingerprint": fingerprint, "alias": self.alias}
            self.receiver = localsend.Receiver(identity, downloads_folder(), self._ask,
                                               self._on_event, _dispatch)
            self.info = self.receiver.info()
            self.receiver.start()
        except OSError as error:
            self.receiver = None
            # EADDRINUSE: the LocalSend app itself probably runs on this PC.
            self.error = _("Port 53317 déjà utilisé (LocalSend est-il ouvert sur ce PC ?)") \
                if getattr(error, "errno", 0) == 98 else _("Démarrage impossible")
            log(f"fichiers : démarrage impossible ({type(error).__name__})")
            self.changed()
            return
        except Exception as error:  # openssl missing or failing
            self.receiver = None
            self.error = _("Certificat impossible à créer (openssl)")
            log(f"fichiers : certificat impossible ({type(error).__name__})")
            self.changed()
            return
        try:
            self.discovery = localsend.Discovery(self.info, self._on_peer, _dispatch,
                                                 lambda peer: localsend.register(self.info, peer))
            self.discovery.start()
        except OSError as error:
            self.discovery = None
            log(f"fichiers : découverte impossible ({type(error).__name__})")
        log("fichiers : LocalSend à l'écoute")
        self.changed()

    def stop(self):
        if self.discovery:
            self.discovery.stop()
            self.discovery = None
        if self.receiver:
            self.receiver.stop()
            self.receiver = None
            log("fichiers : LocalSend arrêté")
        self.peers.clear()
        self.activity, self.progress = "", 0.0

    def refresh(self):
        if self.discovery:
            self.discovery.announce()

    # --- peers ---------------------------------------------------------------------------------

    def _on_peer(self, peer):
        known = self.peers.get(peer["id"])
        self.peers[peer["id"]] = localsend.merge_peer(known, peer)
        if known is None:
            self.changed()

    # --- receiving -----------------------------------------------------------------------------

    def _ask(self, session, answer):
        peer = session.peer
        count = len(session.files)
        names = ", ".join(f["name"] for f in list(session.files.values())[:3])
        if count > 3:
            names += ", …"
        body = ngettext("{name} veut vous envoyer {n} fichier ({size}) : {names}",
                        "{name} veut vous envoyer {n} fichiers ({size}) : {names}", count).format(
            name=peer.get("alias") or "LocalSend", n=count,
            size=localsend.human_size(session.total), names=names)
        settled = []

        def decide(accept):
            if settled:
                return
            settled.append(True)
            self.asks.pop(session.id, None)
            answer(accept)

        actions = [("accept", _("Accepter")), ("refuse", _("Refuser"))]
        self.asks[session.id] = self.notifier.notify(
            "Covalence", APP_ICON, _("Fichiers reçus avec LocalSend"), body, actions,
            {"urgency": GLib.Variant("y", 2)}, own=True,
            on_action=lambda action: decide(action == "accept"),
            on_closed=lambda: decide(False))

    def _on_event(self, kind, data):
        if kind == "peer":
            self._on_peer(data)
            return
        session = data
        if kind == "started":
            self.activity = _("Réception de {name}").format(name=session.peer.get("alias") or "LocalSend")
            self.progress = 0.0
        elif kind == "progress":
            self.progress = session.received / session.total if session.total else 1.0
        elif kind in ("finished", "cancelled", "refused"):
            self.activity, self.progress = "", 0.0
            note = self.asks.pop(session.id, 0)
            if note:
                self.notifier.close(note)
            if kind == "finished":
                count = len(session.saved)
                log(f"fichiers : {count} fichier(s) reçu(s)")
                self.notifier.notify(
                    "Covalence", APP_ICON,
                    ngettext("{n} fichier reçu", "{n} fichiers reçus", count).format(n=count),
                    _("Enregistré dans {folder}").format(folder=downloads_folder()),
                    [("open", _("Ouvrir le dossier"))], own=True,
                    on_action=lambda _a: GLib.spawn_async(
                        ["xdg-open", downloads_folder()], flags=GLib.SpawnFlags.SEARCH_PATH))
            elif kind == "cancelled":
                log("fichiers : réception annulée")
        self.changed()

    def cancel(self):
        if self.receiver:
            self.receiver.cancel_current()
        self.cancel_send = True

    # --- sending -------------------------------------------------------------------------------

    def send(self, peer_id, paths):
        """Start sending; returns an error message, or None once the transfer is under way."""
        peer = self.peers.get(peer_id)
        if not self.receiver or peer is None:
            return _("Appareil introuvable")
        paths = [p for p in paths if os.path.isfile(p)]
        if not paths:
            return _("Aucun fichier à envoyer")
        if self.sending:
            return _("Un envoi est déjà en cours")
        self.sending, self.cancel_send = True, False
        self.activity = _("Envoi à {name} : en attente de son accord").format(name=peer["alias"])
        self.progress = 0.0
        self.changed()
        info = self.info

        def progress(sent, total):
            _dispatch(self._send_progress, peer["alias"], sent / total if total else 1.0)

        def job():
            error, taken = "", 0
            try:
                taken = localsend.send_files(info, peer, paths, progress, lambda: self.cancel_send)
            except localsend.SendError as failure:
                error = {"refused": _("Refusé sur l'autre appareil"),
                         "busy": _("L'autre appareil est occupé"),
                         "fingerprint": _("Appareil non vérifié (empreinte différente)"),
                         "cancelled": _("Envoi annulé"),
                         "unreachable": _("Appareil injoignable")}.get(str(failure),
                                                                      _("Envoi interrompu"))
            except OSError:
                error = _("Fichier illisible")
            _dispatch(self._sent, peer["alias"], taken, error)

        threading.Thread(target=job, name="covalence-localsend-send", daemon=True).start()
        return None

    def _send_progress(self, alias, fraction):
        self.activity = _("Envoi à {name}").format(name=alias)
        self.progress = fraction
        self.changed()

    def _sent(self, alias, taken, error):
        self.sending = False
        self.activity, self.progress = "", 0.0
        log(f"fichiers : envoi {'échoué' if error else 'terminé'} ({taken} fichier(s))")
        if error:
            self.notifier.notify("Covalence", APP_ICON, _("Envoi impossible"), error, own=True)
        else:
            self.notifier.notify(
                "Covalence", APP_ICON,
                ngettext("{n} fichier envoyé", "{n} fichiers envoyés", taken).format(n=taken),
                _("Reçu par {name}").format(name=alias), own=True)
        self.changed()
