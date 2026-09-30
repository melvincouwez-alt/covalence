# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Messages: SMS and iMessage from the iPhone through MAP (obexd), cached locally.

Sources, in order of preference:
- MAP (Message Access Profile) through obexd's org.bluez.obex on the session
  bus: folder listings (inbox, sent), full text with Message1.Get, new-message
  events through MNS, sending with PushMessage.
- ANCS notifications of the Messages app (com.apple.MobileSMS), when MAP is not
  available or misses a message: received messages only, title = sender or group.
- PBAP (phone book) for contact names, pulled at most once a day.

The iPhone gates MAP and PBAP behind two switches in Settings > Bluetooth >
(i) next to this PC: "Show Notifications" and "Sync Contacts".

Rules:
- Never delete a message nor change its read state on the iPhone. The MAP spec
  lets a phone mark a message read when it is downloaded, so full text is only
  fetched (Message1.Get) for messages the listing already reports as read, and
  for sent ones. Unread messages show the listing's subject, which iOS fills
  with the first 120 characters of the text (measured 2026-09-26; asking for a
  longer subject changes nothing). "fetch_unread=true" in the [messages] group
  of covalenced.conf lifts the restriction once it is known that iOS leaves the
  read state alone (prototypes/map_get_readstate.py tests it).
- Nothing is ever sent without an explicit request from the user (SendMessage).
- Logs record counts and states, never text, names or numbers.

Blocking OBEX calls run in one worker thread; everything else, including the
database, stays on the main thread.
"""

import hashlib
import itertools
import json
import os
import queue
import re
import shutil
import sys
import threading
import time
import uuid

from gi.repository import Gio, GLib

from . import bmsg
from . import i18n
from . import otp
from . import reactions
from . import store as store_module
from .store import Store, excerpt, sender_from_title
from .i18n import _, ngettext
from .util import log

OBEX = "org.bluez.obex"
OBEX_ROOT = "/org/bluez/obex"
CLIENT = "org.bluez.obex.Client1"
SESSION = "org.bluez.obex.Session1"
MAP = "org.bluez.obex.MessageAccess1"
MESSAGE = "org.bluez.obex.Message1"
TRANSFER = "org.bluez.obex.Transfer1"
PBAP = "org.bluez.obex.PhonebookAccess1"
MOBILE_SMS = "com.apple.MobileSMS"
APP_ID = "io.github.melvincouwez.Covalence"

# obexd from the bluez-obexd package is D-Bus activated. Without root, a copy
# extracted from that package can be placed here (see README): Covalence starts it
# with only the MNS server plugin, so the PC exposes no file or contact service.
PRIVATE_OBEXD = os.path.join(os.path.expanduser("~"), ".local", "libexec", "covalence", "obexd")

FOLDERS = ("inbox", "outbox", "sent")
INITIAL_COUNT = 1000
EVENT_COUNT = 20
PERIODIC_SYNC = 300  # seconds: catches events MNS may have missed
FORBIDDEN_RETRY = 600
ERROR_RETRY = 120
CONTACTS_MAX_AGE = 24 * 3600
CONTACTS_RETRY_EVERY = 30  # seconds between automatic asks after a refusal
CONTACTS_RETRIES = 20  # that is 10 minutes
CALLS_MAX = 100
BODY_FETCH_LIMIT = 40
COPY_GRANT_SECONDS = 20  # the clipboard helper has this long to fetch the code
ANCS_GRACE_MS = 6000  # wait this long for MAP to report the same message
ANCS_SAME_WINDOW = 3 * 24 * 3600  # undated copy: same text, same sender within 3 days
SHORT_TEXT = 20  # characters: below this, two texts are the same message only if equal
MAX_ANCS_KEYS = 200
_TIMESTAMP = re.compile(r"^\d{8}T\d{6}(Z|[+-]\d{4})?$")  # MAP listing Timestamp
ANCS_SAME_DATED = 600  # dated copy: same text within 10 min (a second « Ok » stays)
NOTIFY_BURST = 3
SEND_CONFIRM = 45  # seconds before looking for a sent message in outbox/sent
SEND_TIMEOUT = 45
MAX_TEXT = 2000  # characters: beyond that an SMS becomes a long chain of parts
SYNC_TIMEOUT = 150  # seconds: a manual sync not over by then is reported as failed
HISTORY_PAGE = 500  # alpha « map_history »: listing pages beyond the usual one
HISTORY_PAGES = 6
HISTORY_DAYS = 365



def format_number(address):
    """+33612345678 -> 06 12 34 56 78 for display; anything else unchanged."""
    if address.startswith("+33") and len(address) == 12:
        national = "0" + address[3:]
        return " ".join(national[i:i + 2] for i in range(0, 10, 2))
    return address or _("Numéro masqué")


def _is_forbidden(message):
    text = (message or "").lower()
    return any(k in text for k in ("0x43", "0x41", "forbidden", "unauthorized", "not authorized"))


def _is_unsupported(message):
    text = (message or "").lower()
    return _is_forbidden(message) or any(
        k in text for k in ("0x51", "0x4f", "0x50", "not implemented", "not supported",
                            "unsupported", "not acceptable", "0x46"))


def favorite_addresses(cards):
    """Addresses of the cards pulled from the PBAP « fav » folder."""
    return {a for card in cards or [] for a in card.get("addresses", []) if a}


def history_listing(list_messages, base, now=None):
    """Alpha « map_history »: ask the iPhone for more than the default listing.

    list_messages(filters) returns {path: props} (may raise). base: what the usual listing
    gave. Returns (extra listing, counters); only the counters are logged: how many new
    messages each approach brought, -1 when the iPhone refused it.
    """
    extra, counts = {}, {}

    def new_ones(page):
        return {k: v for k, v in page.items() if k not in base and k not in extra}

    # 1. Pages after the first one (Offset). iOS may ignore the offset and repeat itself.
    offset, found = len(base), 0
    try:
        for _page in range(HISTORY_PAGES):
            page = list_messages({"Offset": GLib.Variant("q", min(offset, 0xFFFF)),
                                  "MaxCount": GLib.Variant("q", HISTORY_PAGE)})
            fresh = new_ones(page)
            if not fresh:
                break
            extra.update(fresh)
            found += len(fresh)
            offset += len(page)
            if len(page) < HISTORY_PAGE or offset >= 0xFFFF:
                break
        counts["offset"] = found
    except (GLib.Error, RuntimeError) as error:
        counts["offset"] = found or -1
        log(f"messages (alpha) : pagination refusée ({getattr(error, 'message', error)})")
    # 2. A period filter, then read messages only: iOS may list more when asked precisely.
    begin = time.strftime("%Y%m%dT%H%M%S",
                          time.localtime((now or time.time()) - HISTORY_DAYS * 86400))
    for name, filters in (("period", {"PeriodBegin": GLib.Variant("s", begin)}),
                          ("read", {"Read": GLib.Variant("b", True)})):
        try:
            fresh = new_ones(list_messages(dict(filters, MaxCount=GLib.Variant("q", INITIAL_COUNT))))
            extra.update(fresh)
            counts[name] = len(fresh)
        except (GLib.Error, RuntimeError) as error:
            counts[name] = -1
            log(f"messages (alpha) : filtre {name} refusé ({getattr(error, 'message', error)})")
    return extra, counts


class Worker(threading.Thread):
    """Runs blocking OBEX jobs one after the other; results come back on the main loop."""

    def __init__(self):
        super().__init__(daemon=True, name="covalence-obex")
        # Urgent jobs (a message the user is sending) go before waiting ones (a phone book
        # with photos can take minutes); jobs of the same rank keep their order, which
        # RemoveSession then CreateSession rely on.
        self.jobs = queue.PriorityQueue()
        self.count = itertools.count()
        self.start()

    def submit(self, job, done=None, urgent=False):
        self.jobs.put((0 if urgent else 1, next(self.count), job, done))

    def run(self):
        while True:
            _rank, _n, job, done = self.jobs.get()
            try:
                result, error = job(), None
            except GLib.Error as e:
                result, error = None, e.message
            except Exception as e:  # noqa: BLE001 - reported to the main thread
                result, error = None, f"{e.__class__.__name__}: {e}"
            if done:
                GLib.idle_add(lambda d=done, r=result, e=error: d(r, e) or False)


class Messages:
    def __init__(self, bus, notifier, hooks):
        self.bus = bus
        self.notifier = notifier
        self.hooks = hooks  # Daemon: messages_changed(), message_received(tid, key), device_name
        self.enabled = False
        self.store = None
        self.worker = None
        self.obex_owner = None
        self.obex_watch = 0
        self.obex_process = None
        self.subscriptions = []
        self.address = ""  # public address of the connected iPhone
        self.session = None
        self.opening = False
        self.map_state = "idle"  # idle | connecting | ready | forbidden | error
        self.contacts_state = "unknown"  # unknown | ready | forbidden | error
        self.contacts_retry_timer = 0
        self.contacts_retries = 0
        self.syncing = False
        self.sync_again = None
        self.listed = set()  # handles seen in listings of this session
        self.read_anyway = set()  # unread messages the user asked to read in full
        self.announced = set()  # handles announced by MNS, not yet listed
        self.event_timer = 0
        self.periodic_timer = 0
        self.retry_timer = 0
        self.ancs_pending = []
        self.ancs_keys = {}  # ANCS uid -> message key, to update an edited iMessage
        self.notifications = {}  # thread id -> desktop notification id
        self.first_sync_done = False
        self.viewing = ""
        self.pbap_busy = False
        self.sync_waiters = []  # manual syncs: (on_done(new count, error), messages before)
        self.manual_again = False
        self.manual_after_open = False
        self.waiters_timer = 0
        self.codes = otp.OneTimeCodes()  # latest one-time code, in memory only

    # --- lifecycle ------------------------------------------------------------------------

    def enable(self):
        if self.enabled:
            return
        self.enabled = True
        if self.store is None:
            self.store = Store()
            # A send interrupted by a stop of the daemon: offer it again, never resend it.
            self.store.db.execute(
                "UPDATE messages SET status='failed' WHERE source='covalence' AND status='sending'")
            self.store.commit()
            self._classify_all()
            if not self.store.meta("cleanup:duplicates-1"):
                removed = self.store.remove_duplicates()
                self.store.set_meta("cleanup:duplicates-1", int(time.time()))
                self.store.commit()
                if removed:
                    log(f"messages : {removed} doublon(s) d'anciennes versions retiré(s)")
            count, threads = self.store.counts()
            log(f"messages : cache ouvert ({count} messages, {threads} fils)")
        if self.worker is None:
            self.worker = Worker()
        self.obex_watch = Gio.bus_watch_name_on_connection(
            self.bus, OBEX, Gio.BusNameWatcherFlags.AUTO_START,
            self._on_obex_appeared, self._on_obex_vanished)
        self.hooks.messages_changed()

    def disable(self):
        if not self.enabled:
            return
        self.enabled = False
        if self.obex_watch:
            Gio.bus_unwatch_name(self.obex_watch)
            self.obex_watch = 0
        self._close_session()
        self._unsubscribe()
        for tid in list(self.notifications):
            self.notifier.close(self.notifications.pop(tid))
        self.hooks.messages_changed()

    def stop(self):
        self.disable()
        if self.obex_process:
            self.obex_process.force_exit()
            self.obex_process = None

    def state(self):
        """disabled | no-obex | absent | connecting | forbidden | ready | error."""
        if not self.enabled:
            return "disabled"
        if not self.obex_owner:
            return "no-obex"
        if not self.address:
            return "absent"
        if self.map_state in ("ready", "forbidden", "error"):
            return self.map_state
        return "connecting"

    def send_state(self):
        """unknown (never tried) | yes | no, as learnt from the first real send."""
        return self.store.meta("can_send", "unknown") if self.store else "unknown"

    # --- obexd ------------------------------------------------------------------------------

    def _on_obex_appeared(self, _conn, _name, owner):
        self.obex_owner = owner
        log("messages : obexd disponible")
        self._unsubscribe()
        for member, handler in (("InterfacesAdded", self._on_added),
                                ("InterfacesRemoved", self._on_removed)):
            self.subscriptions.append(self.bus.signal_subscribe(
                owner, "org.freedesktop.DBus.ObjectManager", member, None, None,
                Gio.DBusSignalFlags.NONE, handler))
        self.subscriptions.append(self.bus.signal_subscribe(
            owner, "org.freedesktop.DBus.Properties", "PropertiesChanged", None, MESSAGE,
            Gio.DBusSignalFlags.NONE, self._on_message_changed))
        self.session = None
        if self.address:
            self._open_session()
        self.hooks.messages_changed()

    def _on_obex_vanished(self, _conn, _name):
        had = self.obex_owner is not None
        self.obex_owner = None
        self.session = None
        self.map_state = "idle"
        self._unsubscribe()
        if had:
            log("messages : obexd arrêté")
        if self.enabled and not self._obex_activatable():
            self._spawn_private_obexd()
        self.hooks.messages_changed()

    def _obex_activatable(self):
        try:
            names = self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                       "org.freedesktop.DBus", "ListActivatableNames", None,
                                       GLib.VariantType("(as)"), Gio.DBusCallFlags.NONE,
                                       2000, None).unpack()[0]
        except GLib.Error:
            return False
        return OBEX in names

    def _spawn_private_obexd(self):
        if self.obex_process is not None:
            return
        if not os.access(PRIVATE_OBEXD, os.X_OK):
            log("messages : obexd introuvable (paquet bluez-obexd absent)")
            return
        try:
            self.obex_process = Gio.Subprocess.new(
                [PRIVATE_OBEXD, "-n", "-p", "bluetooth,mns"],
                # obexd also logs to the journal itself: drop the duplicate copy.
                Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error as error:
            log(f"messages : obexd privé non démarré ({error.message})")
            return
        log("messages : obexd privé démarré (serveur MNS seulement)")
        self.obex_process.wait_async(None, self._on_obex_exited)

    def _on_obex_exited(self, process, result):
        try:
            process.wait_finish(result)
        except GLib.Error:
            pass
        self.obex_process = None
        if self.enabled:
            log("messages : obexd privé terminé, relance dans 30 s")
            GLib.timeout_add_seconds(30, lambda: self._restart_private() and False)

    def _restart_private(self):
        if self.enabled and not self.obex_owner:
            self._spawn_private_obexd()

    def _unsubscribe(self):
        for sub in self.subscriptions:
            self.bus.signal_unsubscribe(sub)
        self.subscriptions = []

    def _call(self, path, interface, method, args=None, reply=None, timeout=30000):
        """Blocking obexd call: worker thread only."""
        return self.bus.call_sync(OBEX, path, interface, method, args,
                                  GLib.VariantType(reply) if reply else None,
                                  Gio.DBusCallFlags.NONE, timeout, None).unpack()

    def _wait_transfer(self, path, timeout=60, progress=None):
        """Poll an obexd transfer until it ends (worker thread only)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                props = self._call(path, "org.freedesktop.DBus.Properties", "GetAll",
                                   GLib.Variant("(s)", (TRANSFER,)), "(a{sv})")[0]
            except GLib.Error:
                return  # obexd drops the transfer object once it is over
            status = props.get("Status")
            if progress and props.get("Size"):
                progress(0.1 + 0.85 * min(1.0, props.get("Transferred", 0) / props["Size"]))
            if status == "complete":
                return
            if status == "error":
                raise RuntimeError("transfer failed")
            time.sleep(0.1)
        raise RuntimeError("transfer timed out")

    # --- device presence -----------------------------------------------------------------------

    def device_connected(self, address):
        if not address:
            return
        self.address = address
        if self.store:
            archive = self.store.claim_device(address)
            if archive:
                # MAP handles are per phone: another iPhone starts from an empty cache.
                log(f"messages : autre iPhone, ancien cache archivé ({os.path.basename(archive)})")
                self.listed.clear()
                self.announced.clear()
                self.contacts_state = "unknown"
                self.hooks.messages_changed(threads=True)
        if self.enabled and self.obex_owner:
            # Let HFP and A2DP settle first: iOS dislikes a burst of connections.
            self._schedule_retry(5)
        self.hooks.messages_changed()

    def device_disconnected(self):
        if not self.address:
            return
        self.address = ""
        self._close_session()
        self.hooks.messages_changed()

    def _schedule_retry(self, seconds):
        if self.retry_timer:
            GLib.source_remove(self.retry_timer)

        def fire():
            self.retry_timer = 0
            self._open_session()
            return False

        self.retry_timer = GLib.timeout_add_seconds(seconds, fire)

    # --- MAP session -----------------------------------------------------------------------------

    def _open_session(self):
        if not self.enabled or not self.obex_owner or not self.address:
            return
        if self.session or self.opening:
            return
        self.opening = True
        self.map_state = "connecting"
        address = self.address
        self.hooks.messages_changed()

        def job():
            return self._call(OBEX_ROOT, CLIENT, "CreateSession",
                              GLib.Variant("(sa{sv})", (address, {"Target": GLib.Variant("s", "map")})),
                              "(o)", timeout=45000)[0]

        self.worker.submit(job, self._on_session)

    def _on_session(self, path, error):
        self.opening = False
        if error:
            forbidden = _is_forbidden(error)
            state = "forbidden" if forbidden else "error"
            if state != self.map_state:
                log("messages : accès MAP refusé par l'iPhone (réglage « Afficher les "
                    "notifications » de ce PC)" if forbidden else f"messages : session MAP impossible ({error})")
            self.map_state = state
            if self.address:
                self._schedule_retry(FORBIDDEN_RETRY if forbidden else ERROR_RETRY)
            self.manual_after_open = False
            self._finish_waiters(_("accès aux messages refusé par l'iPhone") if forbidden
                                 else _("iPhone injoignable"))
            self.hooks.messages_changed()
            return
        if not self.address or not self.enabled:
            self.worker.submit(lambda: self._call(OBEX_ROOT, CLIENT, "RemoveSession",
                                                  GLib.Variant("(o)", (path,))))
            return
        self.session = path
        self.map_state = "ready"
        self.listed.clear()
        self.first_sync_done = False
        log("messages : session MAP ouverte")
        self.hooks.messages_changed()
        manual, self.manual_after_open = self.manual_after_open, False
        self.sync(initial=True, manual=manual)
        if not self.periodic_timer:
            self.periodic_timer = GLib.timeout_add_seconds(PERIODIC_SYNC, self._periodic)

    def _close_session(self):
        for attr in ("retry_timer", "periodic_timer", "event_timer"):
            if getattr(self, attr):
                GLib.source_remove(getattr(self, attr))
                setattr(self, attr, 0)
        path, self.session = self.session, None
        self.map_state = "idle"
        self.listed.clear()  # both are about this session's listings and events
        self.announced.clear()
        if path and self.obex_owner:
            self.worker.submit(lambda: self._call(OBEX_ROOT, CLIENT, "RemoveSession",
                                                  GLib.Variant("(o)", (path,))))

    def _periodic(self):
        if self.session:
            self.sync(count=50)
            self.periodic_ticks = getattr(self, "periodic_ticks", 0) + 1
            if self.periodic_ticks % 3 == 0:
                self._maybe_pull_contacts(calls_only=True)
        return True

    def retry(self):
        """App request: try again now (e.g. after the user allowed MAP on the iPhone)."""
        # Contacts first: a refusal is sticky until retried, and the MAP session being open
        # (messages fine) used to skip them, so "Réessayer" never asked the iPhone again.
        self.retry_contacts()
        if self.session:
            self.sync(count=100)
        else:
            self.map_state = "idle"
            self._open_session()

    def retry_contacts(self):
        """Ask the iPhone for the phone book again, even if it refused before or the cache is fresh."""
        if self.contacts_state == "forbidden":
            self.contacts_state = "unknown"
        self._maybe_pull_contacts(force=True)

    def manual_sync(self, on_done):
        """The Sync button: list the folders again (after UpdateInbox), fetch full texts, read
        contacts and the call history. on_done(new messages, error) once it is over."""
        if not self.enabled or not self.store:
            on_done(None, _("module Messages désactivé"))
            return
        if not self.address or not self.obex_owner:
            on_done(None, _("iPhone non connecté"))
            return
        self.sync_waiters.append((on_done, self.store.counts()[0]))
        if not self.waiters_timer:
            self.waiters_timer = GLib.timeout_add_seconds(SYNC_TIMEOUT, self._waiters_timeout)
        if self.session:
            self.sync(manual=True)
        else:
            self.manual_after_open = True
            self.map_state = "idle"
            if self.contacts_state == "forbidden":
                self.contacts_state = "unknown"
            self._open_session()

    def _waiters_timeout(self):
        self.waiters_timer = 0
        self._finish_waiters(_("l'iPhone ne répond pas"))
        return False

    def _finish_waiters(self, error=None):
        if self.waiters_timer:
            GLib.source_remove(self.waiters_timer)
            self.waiters_timer = 0
        waiters, self.sync_waiters = self.sync_waiters, []
        now = self.store.counts()[0] if self.store and not error else 0
        for on_done, before in waiters:
            if error:
                on_done(None, error)
            else:
                on_done(max(0, now - before), None)

    # --- listing and merge --------------------------------------------------------------------------

    def _alpha(self, name):
        config = getattr(self.hooks, "config", None)
        return bool(config and hasattr(config, "alpha") and config.alpha(name))

    def sync(self, initial=False, count=EVENT_COUNT, manual=False):
        if not self.session:
            return
        if self.syncing:
            self.sync_again = max(self.sync_again or 0, count)
            self.manual_again = self.manual_again or manual
            return
        self.syncing = True
        session = self.session
        max_count = INITIAL_COUNT if initial or manual else count
        history = (initial or manual) and self._alpha("map_history")

        def job():
            if manual:
                try:  # ask the iPhone to refresh its listing first; may not be supported
                    self._call(session, MAP, "UpdateInbox")
                except GLib.Error as error:
                    log(f"messages : UpdateInbox non pris en charge ({error.message})")
            self._call(session, MAP, "SetFolder", GLib.Variant("(s)", ("/telecom/msg",)))
            available = [f["Name"] for f in self._call(
                session, MAP, "ListFolders", GLib.Variant("(a{sv})", ({},)), "(aa{sv})")[0]]
            listing, counts = {}, {}
            for folder in FOLDERS:
                if folder not in available:
                    continue

                def list_messages(filters, folder=folder):
                    filters = dict(filters, SubjectLength=GLib.Variant("y", 255))
                    return self._call(session, MAP, "ListMessages",
                                      GLib.Variant("(sa{sv})", (folder, filters)),
                                      "(a{oa{sv}})", timeout=60000)[0]

                listing[folder] = list_messages({"MaxCount": GLib.Variant("q", max_count)})
                if history:
                    extra, counts[folder] = history_listing(list_messages, listing[folder])
                    listing[folder].update(extra)
            return available, listing, counts

        self.worker.submit(job, lambda r, e: self._on_listing(session, initial, r, e, manual))

    def _on_listing(self, session, initial, result, error, manual=False):
        self.syncing = False
        if session != self.session:
            if manual:
                self._finish_waiters(_("connexion à l'iPhone perdue"))
            return
        if error:
            log(f"messages : lecture des dossiers impossible ({error})")
            if _is_forbidden(error):
                self.map_state = "forbidden"
                self.hooks.messages_changed()
            if manual:
                self._finish_waiters(_("lecture des messages impossible"))
        else:
            available, listing, counts = result
            if counts:
                log("messages (alpha) : historique étendu, nouveaux messages par méthode : "
                    + " ; ".join(f"{folder} {c}" for folder, c in counts.items()))
            initial = initial or manual  # notify only what arrived since the last sync
            if initial:
                total = sum(len(v) for v in listing.values())
                kinds = {}
                for msgs in listing.values():
                    for props in msgs.values():
                        kind = props.get("Type") or "?"
                        kinds[kind] = kinds.get(kind, 0) + 1
                log(f"messages : dossiers {', '.join(sorted(available))} ; "
                    + ", ".join(f"{f} {len(v)}" for f, v in listing.items())
                    + f" (total {total}, types {kinds})")
            self._merge(listing, initial)
            self._fetch_bodies()
            if initial:
                self._maybe_pull_contacts(force=manual)
            if manual:
                self._finish_waiters()
        if self.sync_again or self.manual_again:
            count, self.sync_again = self.sync_again or EVENT_COUNT, None
            manual, self.manual_again = self.manual_again, False
            self.sync(count=count, manual=manual)

    def _entries(self, listing):
        entries = []
        for folder, messages in listing.items():
            for path, props in messages.items():
                handle = path.rsplit("/message", 1)[-1]
                entry = bmsg.listing_entry(handle, props, folder)
                # No usable timestamp: the parser gave "now", which must not move a stored
                # message to the bottom of its conversation at every sync.
                entry["time_known"] = bool(_TIMESTAMP.match((props.get("Timestamp") or "").strip()))
                entries.append(entry)
        return entries

    def _participants(self, entry, selves):
        if entry["outgoing"]:
            people = [r for r in entry["recipients"] if r not in selves] or entry["recipients"]
            if not people and entry["recipient_names"]:
                people = ["name:" + n for n in entry["recipient_names"]]
            return people
        sender = entry["sender"] or ("name:" + entry["sender_name"] if entry["sender_name"] else "")
        others = [r for r in entry["recipients"] if r not in selves and r != entry["sender"]]
        if len(entry["recipients"]) <= 1:
            others = []  # one recipient: this phone, a one-to-one message
        return [p for p in [sender] + others if p]

    def _merge(self, listing, initial):
        store = self.store
        entries = self._entries(listing)
        for e in entries:
            if not e["outgoing"] and len(e["recipients"]) == 1:
                store.add_self_address(e["recipients"][0])
            if e["outgoing"] and e["sender"]:
                store.add_self_address(e["sender"])
        selves = store.self_addresses()
        last_sync = int(store.meta("last_sync", "0") or 0)
        fresh = []
        for e in entries:
            self.listed.add(e["handle"])
            self.announced.discard(e["handle"])
            people = self._participants(e, selves)
            body = e["subject"]
            key = "map:" + e["handle"]
            known = store.message(key) is not None
            if e["outgoing"] and not people and not known:
                # iOS leaves recipients empty: recognise our own sends by their text.
                pending = store.find_pending_outgoing(None, body, e["time"])
                if pending:
                    people = store.thread(store.message(pending)["thread"])["participants"]
            if not people:
                if known:
                    store.upsert(key, store.message(key)["thread"], e["outgoing"], e["sender"],
                                 e["sender_name"], e["time"], body, False, kind=e["type"],
                                 phone_read=e["read"], seen=e["read"], source="map",
                                 handle=e["handle"], time_known=e["time_known"])
                continue
            tid = store.ensure_thread(people)
            complete = e["size"] > 0 and len(body.encode("utf-8")) >= e["size"]
            if e["outgoing"] and not known:
                # Only a message the phone lists for the first time can be one of our sends.
                pending = store.find_pending_outgoing(tid, body, e["time"])
                if pending:
                    store.delete(pending)
            already = None if e["outgoing"] or known else \
                self._drop_ancs_duplicate(body, e["time"], tid, e["sender"], e["sender_name"])
            is_new = store.upsert(key, tid, e["outgoing"], e["sender"], e["sender_name"],
                                  e["time"], body, complete, kind=e["type"],
                                  phone_read=e["read"], seen=e["read"] or bool(already),
                                  source="map", handle=e["handle"], time_known=e["time_known"])
            # already: shown earlier from its ANCS notification, not notified twice
            if is_new and already is None and not e["outgoing"] and not e["read"] and \
                    (not initial or (last_sync and e["time"] > last_sync)):
                fresh.append((tid, key))
        # Reactions carried as SMS text become badges on the message they quote.
        reacted = []
        for e in entries:
            key = "map:" + e["handle"]
            found = self._classify(key)
            if found is None:
                continue
            m = store.message(key)
            if m and (m["thread"], key) in fresh:
                fresh.remove((m["thread"], key))
                if not found["removed"] and not found["duplicate"]:
                    reacted.append((m["thread"], key, found))
        store.set_meta("last_sync", int(time.time()))
        store.commit()
        self.first_sync_done = True
        for tid, key, found in reacted[-NOTIFY_BURST:]:
            self._settle_ancs(key)
            self._notify_reaction(tid, key, found)
        if fresh:
            log(f"messages : {len(fresh)} nouveau(x) message(s)")
        if entries or fresh or reacted:
            self.hooks.messages_changed(threads=True)
        for tid, key in fresh[-NOTIFY_BURST:]:
            self._settle_ancs(key)
            self._notify(tid, key)
            self.hooks.message_received(tid, key)
        if len(fresh) > NOTIFY_BURST:
            self.notifier.notify(f"Covalence ({self.hooks.device_name})", "io.github.melvincouwez.Covalence.Messages",
                                 ngettext("{n} nouveau message", "{n} nouveaux messages",
                                          len(fresh)).format(n=len(fresh)), "", own=True)

    # --- full text -----------------------------------------------------------------------------------

    def _fetch_bodies(self):
        config = getattr(self.hooks, "config", None)
        unread = bool(config and config.boolean("messages", "fetch_unread"))
        wanted = [m for m in self.store.needing_body(BODY_FETCH_LIMIT, True)
                  if m["handle"] in self.listed and
                  (unread or m["phone_read"] or m["outgoing"] or m["key"] in self.read_anyway)]
        if not wanted or not self.session:
            return
        session, tmp = self.session, self.store.tmp

        def job():
            results = {}
            for m in wanted:
                target = os.path.join(tmp, f"get-{uuid.uuid4().hex}.bmsg")
                try:
                    transfer = self._call(f"{session}/message{m['handle']}", MESSAGE, "Get",
                                          GLib.Variant("(sb)", (target, False)), "(oa{sv})")[0]
                    self._wait_transfer(transfer)
                    with open(target, encoding="utf-8", errors="replace") as f:
                        results[m["key"]] = bmsg.parse_bmessage(f.read())
                except (GLib.Error, OSError, RuntimeError):
                    results[m["key"]] = None
                finally:
                    if os.path.exists(target):
                        os.unlink(target)
            return results

        self.worker.submit(job, self._on_bodies)

    def read_full(self, key):
        """The user asked for the whole text of an unread message (it may turn read on the
        iPhone: MAP lets a phone mark a downloaded message read)."""
        m = self.store.message(key) if self.store else None
        if not m or m["complete"] or m["source"] != "map":
            return False
        self.read_anyway.add(key)
        self._fetch_bodies()
        return True

    def _on_bodies(self, results, error):
        if error or not results:
            return
        store = self.store
        selves = store.self_addresses()
        got = 0
        for key, parsed in results.items():
            self.read_anyway.discard(key)
            m = store.message(key)
            if m is None or parsed is None:
                continue
            got += 1
            tid = m["thread"]
            people = [a for card in parsed["recipients"] for a in card["addresses"]
                      if a not in selves]
            origin = parsed["originator"]["addresses"] if parsed["originator"] else []
            if not m["outgoing"]:
                sender = m["sender"] or (origin[0] if origin else "")
                people = [sender] + [p for p in people if p != sender]
            people = [p for p in dict.fromkeys(people) if p]
            if len(people) > 1:  # the envelope reveals a group conversation
                tid = store.ensure_thread(people, is_group=True)
            if m["outgoing"]:
                # Full text known now: drop Covalence's own copy if the subject missed it.
                pending = store.find_pending_outgoing(tid, parsed["body"], m["time"])
                if pending:
                    store.delete(pending)
            store.upsert(key, tid, bool(m["outgoing"]), m["sender"], m["sender_name"], m["time"],
                         parsed["body"], True, kind=m["kind"], phone_read=bool(m["phone_read"]),
                         source="map", handle=m["handle"])
            self._classify(key)
        store.commit()
        if got:
            log(f"messages : texte complet récupéré pour {got} message(s)")
            self.hooks.messages_changed(threads=True)

    # --- MNS events and read-status changes ----------------------------------------------------------

    def _on_added(self, _conn, _sender, _path, _iface, _signal, params):
        path, interfaces = params.unpack()
        if not self.session or MESSAGE not in interfaces or not path.startswith(self.session + "/"):
            return
        handle = path.rsplit("/message", 1)[-1]
        if handle in self.listed or self.store.has_handle(handle):
            return
        self.announced.add(handle)
        if not self.event_timer:
            self.event_timer = GLib.timeout_add(800, self._on_event_timer)

    def _on_event_timer(self):
        self.event_timer = 0
        if self.announced and not self.syncing:
            log("messages : événement « nouveau message » reçu")
            self.sync(count=EVENT_COUNT)
        elif self.announced:
            self.sync_again = max(self.sync_again or 0, EVENT_COUNT)
        return False

    def _on_removed(self, _conn, _sender, _path, _iface, _signal, params):
        path, interfaces = params.unpack()
        if path == self.session and SESSION in interfaces:
            log("messages : session MAP fermée par obexd")
            self.session = None
            self.map_state = "idle"
            if self.address:
                self._schedule_retry(10)
            self.hooks.messages_changed()

    def _on_message_changed(self, _conn, _sender, path, _iface, _signal, params):
        if not self.session or not path.startswith(self.session + "/"):
            return
        _interface, changed, _invalid = params.unpack()
        if "Read" not in changed:
            return
        key = "map:" + path.rsplit("/message", 1)[-1]
        m = self.store.message(key)
        if m and bool(m["phone_read"]) != bool(changed["Read"]):
            self.store.upsert(key, m["thread"], bool(m["outgoing"]), m["sender"], m["sender_name"],
                              m["time"], m["body"], bool(m["complete"]), kind=m["kind"],
                              phone_read=bool(changed["Read"]), source="map", handle=m["handle"])
            self.store.commit()
            self.hooks.messages_changed(threads=True)

    # --- contacts (PBAP) ---------------------------------------------------------------------------

    def _maybe_pull_contacts(self, calls_only=False, force=False):
        """PBAP: the phone book at most once a day, the call history every time."""
        if not self.enabled or not self.store or not self.worker:
            return  # module off, or never switched on: nothing to pull into
        if not self.address or self.contacts_state == "forbidden" or self.pbap_busy:
            return
        age = time.time() - int(self.store.meta("contacts_time", "0") or 0)
        if self.store.meta("contacts_schema") != store_module.CONTACTS_SCHEMA:
            age = CONTACTS_MAX_AGE  # older cache without photos: pull again
        want_book = not calls_only and (force or age >= CONTACTS_MAX_AGE)
        want_favorites = want_book and self._alpha("pbap_favorites")
        if age < CONTACTS_MAX_AGE:
            self.contacts_state = "ready"
        address, tmp = self.address, self.store.tmp
        self.pbap_busy = True

        def pull(session, book, fields, max_count=None):
            target = os.path.join(tmp, f"pb-{uuid.uuid4().hex}.vcf")
            try:
                self._call(session, PBAP, "Select", GLib.Variant("(ss)", ("int", book)))
                options = {"Format": GLib.Variant("s", "vcard30"),
                           "Fields": GLib.Variant("as", fields)}
                if max_count:
                    options["MaxCount"] = GLib.Variant("q", max_count)
                transfer = self._call(session, PBAP, "PullAll",
                                      GLib.Variant("(sa{sv})", (target, options)), "(oa{sv})")[0]
                self._wait_transfer(transfer, timeout=120)
                with open(target, encoding="utf-8", errors="replace") as f:
                    return f.read()
            finally:
                if os.path.exists(target):
                    os.unlink(target)

        def job():
            session = self._call(OBEX_ROOT, CLIENT, "CreateSession",
                                 GLib.Variant("(sa{sv})", (address, {"Target": GLib.Variant("s", "pbap")})),
                                 "(o)", timeout=45000)[0]
            try:
                cards = bmsg.parse_vcards(pull(session, "pb", ["FN", "N", "TEL", "EMAIL", "PHOTO"])) \
                    if want_book else None
                history = bmsg.parse_call_history(
                    pull(session, "cch", ["FN", "N", "TEL", "X-IRMC-CALL-DATETIME"], CALLS_MAX))
                favorites = None
                if want_favorites:
                    try:  # PBAP « fav » folder (PBAP 1.2): iOS may not expose it
                        favorites = favorite_addresses(bmsg.parse_vcards(
                            pull(session, "fav", ["FN", "N", "TEL", "EMAIL"])))
                    except (GLib.Error, OSError, RuntimeError) as error:
                        log(f"contacts (alpha) : favoris non disponibles "
                            f"({getattr(error, 'message', error)})")
                return cards, history, favorites
            finally:
                self._call(OBEX_ROOT, CLIENT, "RemoveSession", GLib.Variant("(o)", (session,)))

        self.worker.submit(job, self._on_phonebook)

    def _on_phonebook(self, result, error):
        self.pbap_busy = False
        if error:
            self._on_contacts(None, error)
            return
        cards, history, favorites = result
        if cards is not None:
            self._on_contacts(cards, None)
        if favorites is not None:
            self.store.set_meta("pbap_favorites", json.dumps(sorted(favorites)))
            log(f"contacts (alpha) : {len(favorites)} adresse(s) en favori sur l'iPhone")
            changed = getattr(self.hooks, "contacts_changed", None)
            if changed:
                changed()
        self.store.replace_calls(history)
        self.store.commit()
        missed = sum(1 for c in history if c["kind"] == "missed")
        log(f"appels : journal lu ({len(history)} appels, {missed} manqués)")
        self.hooks.calls_changed()

    def favorites(self):
        """Addresses in the iPhone's favourites (alpha « pbap_favorites »), else empty."""
        if not self.store or not self._alpha("pbap_favorites"):
            return set()
        try:
            return set(json.loads(self.store.meta("pbap_favorites", "[]") or "[]"))
        except ValueError:
            return set()

    def call_history(self):
        if not self.store:
            return []
        result = []
        for c in self.store.calls():
            name = self.store.contact_name(c["address"]) or c["name"] or ""
            result.append({"address": c["address"], "name": name or format_number(c["address"]),
                           "time": c["time"], "kind": c["kind"],
                           "avatar": self.store.photo(c["address"])})
        return result

    def missed_unseen(self):
        """Missed calls newer than the last look at the call history."""
        if not self.store:
            return 0
        seen = int(self.store.meta("calls_seen", "0") or 0)
        if not seen:
            # First run: what was already in the history counts as seen.
            self.store.set_meta("calls_seen", int(time.time()))
            return 0
        return sum(1 for c in self.store.calls() if c["kind"] == "missed" and c["time"] > seen)

    def mark_calls_seen(self):
        if self.store:
            self.store.set_meta("calls_seen", int(time.time()))
            self.hooks.calls_changed()

    def refresh_calls(self):
        """A call just ended: read the history again shortly after."""
        GLib.timeout_add_seconds(5, lambda: self._maybe_pull_contacts(calls_only=True) and False)

    def _schedule_contacts_retry(self):
        """iOS only shows « Synchroniser les contacts » once a PBAP request was refused, and
        never tells when the user turns it on: ask again every 30 s for 10 minutes."""
        if self.contacts_retry_timer:
            return
        self.contacts_retries = 0

        def tick():
            self.contacts_retries += 1
            if self.contacts_state != "forbidden" or not self.address \
                    or self.contacts_retries > CONTACTS_RETRIES:
                self.contacts_retry_timer = 0
                return False
            self.contacts_state = "unknown"
            self._maybe_pull_contacts(force=True)
            return True

        self.contacts_retry_timer = GLib.timeout_add_seconds(CONTACTS_RETRY_EVERY, tick)

    def _on_contacts(self, cards, error):
        if error:
            self.contacts_state = "forbidden" if _is_forbidden(error) else "error"
            log("messages : contacts refusés par l'iPhone (réglage « Synchroniser les contacts »)"
                if self.contacts_state == "forbidden" else f"messages : contacts illisibles ({error})")
            if self.contacts_state == "forbidden":
                self._schedule_contacts_retry()
        else:
            self.store.replace_contacts(cards)
            merged = self.store.merge_name_threads()
            if merged:
                log(f"messages : {merged} conversation(s) rattachée(s) au numéro du contact")
            self.contacts_state = "ready"
            photos = sum(1 for c in cards if c.get("photo"))
            log(f"messages : {len(cards)} contacts lus sur l'iPhone ({photos} avec photo)")
        self.hooks.messages_changed(threads=not error)

    # --- ANCS fallback -------------------------------------------------------------------------------

    def ancs_message(self, title, subtitle, message, date=None, replay=False, uid=None,
                     modified=False):
        """ANCS notification from the Messages app. True: this module shows it.

        modified: the iPhone changed a notification it already sent (an edited iMessage):
        the bubble it made is updated rather than doubled."""
        if not self.enabled or not title:
            return False
        now = int(time.time())
        when = date if date and date <= now + 60 else now
        entry = {"title": sender_from_title(title), "subtitle": subtitle, "message": message,
                 "time": when, "dated": bool(date),
                 # Replayed by the iPhone after a reconnection or a re-pairing: stored with
                 # its own time, never announced as new.
                 "old": replay, "uid": uid, "modified": modified}
        self.ancs_pending.append(entry)
        GLib.timeout_add(ANCS_GRACE_MS, lambda: self._flush_ancs(entry) and False)
        return True

    @staticmethod
    def _same_text(a, b):
        """Same message seen twice (a listing subject may be cut): a short text must match
        exactly, or « Oui » would match « Oui mais non »."""
        a, b = " ".join((a or "").split()), " ".join((b or "").split())
        if not a or not b:
            return False
        if min(len(a), len(b)) < SHORT_TEXT:
            return a == b
        a, b = a[:40], b[:40]
        return a.startswith(b) or b.startswith(a)

    def _from_same_person(self, title, sender, sender_name):
        """An ANCS title (the name iOS shows) and a MAP sender are the same person."""
        if not title:
            return False
        if sender_name and sender_name == title:
            return True
        if sender and (self.store.address_for_name(title) == sender
                       or self.store.display_name(sender) == title):
            return True
        return False

    def _settle_ancs(self, key):
        """A MAP message was notified: forget the ANCS copy of it."""
        m = self.store.message(key)
        if not m:
            return
        for entry in list(self.ancs_pending):
            if self._same_text(entry["message"], m["body"]) and \
                    self._from_same_person(entry["title"], m["sender"], m["sender_name"]):
                self.ancs_pending.remove(entry)
                return

    def _drop_ancs_duplicate(self, body, when, tid, sender, sender_name):
        """Remove the ANCS copy of a message MAP now lists; None, or its seen flag.
        Only a copy from the same person: « Oui » from Bob is not « Oui » from Alice."""
        for row in self.store.db.execute(
                "SELECT key, body, seen, thread, sender, sender_name FROM messages "
                "WHERE source='ancs' AND ABS(time-?)<600", (int(when),)).fetchall():
            same_person = row["thread"] == tid or (sender and row["sender"] == sender) or \
                self._from_same_person(row["sender_name"], sender, sender_name)
            if same_person and self._same_text(row["body"], body):
                self.store.delete(row["key"])
                return int(row["seen"])
        return None

    def _already_have(self, tid, body, when, window):
        """The same text from this sender is already in the thread (MAP or an older ANCS copy
        from before the iPhone gave dates): do not store it twice."""
        for row in self.store.db.execute(
                "SELECT body FROM messages WHERE thread=? AND outgoing=0 AND ABS(time-?)<?",
                (tid, int(when), window)).fetchall():
            if " ".join((row["body"] or "").split()) == " ".join((body or "").split()):
                return True
        return False

    def _flush_ancs(self, entry):
        if entry not in self.ancs_pending:
            return  # MAP reported it in the meantime
        self.ancs_pending.remove(entry)
        store = self.store
        address = store.address_for_name(entry["title"])
        # An edited iMessage: the iPhone sends the same notification again with the new text.
        earlier = self.ancs_keys.get(entry["uid"]) if entry["modified"] else None
        if earlier and store.message(earlier):
            body = entry["message"]
            store.db.execute("UPDATE messages SET body=?, complete=? WHERE key=?",
                             (body, int(len(body) < 500), earlier))
            store.commit()
            log("messages : message modifié sur l'iPhone, bulle mise à jour")
            self.hooks.messages_changed(threads=True)
            return
        # MAP may have listed it before the notification came: already shown.
        for row in store.db.execute(
                "SELECT body, thread, sender, sender_name FROM messages WHERE source='map' "
                "AND outgoing=0 AND ABS(time-?)<600", (entry["time"],)).fetchall():
            if self._same_text(row["body"], entry["message"]) and (
                    (address and row["sender"] == address)
                    or self._from_same_person(entry["title"], row["sender"], row["sender_name"])):
                return
        people = [address] if address else ["name:" + entry["title"]]
        tid = store.ensure_thread(people, title=entry["title"], is_group=False)
        # Key from the iPhone's own date when it gave one: the same notification replayed
        # at the next connection gets the same key instead of a new copy each time.
        stamp = entry["time"] if entry["dated"] else entry["time"] // 60
        digest = hashlib.sha1(f"{entry['title']}|{entry['message']}|{stamp}"
                              .encode("utf-8")).hexdigest()[:16]
        key = "ancs:" + digest
        body = entry["message"]
        window = ANCS_SAME_DATED if entry["dated"] else ANCS_SAME_WINDOW
        if not store.message(key) and self._already_have(tid, body, entry["time"], window):
            return
        new = store.upsert(key, tid, False, address, entry["title"], entry["time"], body,
                           len(body) < 500, kind="notification", source="ancs")
        if entry["uid"] is not None:
            self.ancs_keys[entry["uid"]] = key
            while len(self.ancs_keys) > MAX_ANCS_KEYS:
                del self.ancs_keys[next(iter(self.ancs_keys))]
        found = self._classify(key) if new else None
        store.commit()
        if new:
            log("messages : message reçu par notification (ANCS)")
            self.hooks.messages_changed(threads=True)
            if found is not None:
                if not found["removed"] and not found["duplicate"]:
                    self._notify_reaction(tid, key, found)
                return
            if entry["old"]:
                return  # history replayed by the iPhone, not a new message
            self._notify(tid, key, subtitle=entry["subtitle"])
            self.hooks.message_received(tid, key)

    # --- notifications ---------------------------------------------------------------------------------

    def _notify(self, tid, key, subtitle=""):
        m = self.store.message(key)
        thread = self.store.thread(tid)
        if not m or not thread:
            return
        code = None
        if not m["outgoing"] and self.code_mode() != "off":
            code = otp.detect(m["body"] or "")
            if code:
                self.codes.remember(code, key)
                log("messages : code à usage unique reçu")  # never the code itself
                if self.auto_copy_codes():
                    # Straight to the clipboard, even with the conversation on screen.
                    self._copy_code(key, False)
        if tid == self.viewing:
            return  # the conversation is on screen: the new bubble is enough
        sender = self.store.display_name(m["sender"], m["sender_name"] or _("Inconnu"))
        if thread["is_group"]:
            summary = f"{sender} · {self.store.thread_title(thread)}"
        else:
            summary = self.store.thread_title(thread) or sender
        body = "\n".join(filter(None, [subtitle, m["body"] or ""]))
        actions = [("default", _("Ouvrir"))]
        if code:
            # As on the iPhone: the code is one click away; nobody answers these senders.
            actions += [("copy-code", _("Copier le code")),
                        ("copy-code-delete", _("Copier et supprimer"))]
        elif self.can_send(thread):
            inline = "inline-reply" in self.notifier.capabilities() \
                if hasattr(self.notifier, "capabilities") else False
            actions.append(("inline-reply" if inline else "reply", _("Répondre")))
        hints = {"category": GLib.Variant("s", "im.received")}
        photo = self.store.photo(m["sender"] or "")
        if photo:
            hints["image-path"] = GLib.Variant("s", photo)
        self._sound(hints)
        self.notifications[tid] = self.notifier.notify(
            f"Covalence ({self.hooks.device_name})", "io.github.melvincouwez.Covalence.Messages", summary, body, actions, hints,
            replaces=self.notifications.get(tid, 0),
            on_action=lambda action, t=tid, k=key: self._on_notification_action(t, action, k),
            on_closed=lambda t=tid: self.notifications.pop(t, None))

    def _sound(self, hints):
        """The sound chosen in Réglages, played by the daemon; the server stays silent."""
        play = getattr(self.hooks, "play_sound", None)
        if play:
            play("messages")
            hints["suppress-sound"] = GLib.Variant("b", True)

    # --- one-time codes ----------------------------------------------------------------------------

    def code_mode(self):
        """off | copy (notification with a copy button) | browser (also offered in the browser)."""
        config = getattr(self.hooks, "config", None)
        mode = config.string("messages", "one_time_codes", "copy") if config else "copy"
        return mode if mode in ("off", "copy", "browser") else "copy"

    def set_code_mode(self, mode):
        config = getattr(self.hooks, "config", None)
        if mode not in ("off", "copy", "browser") or not config:
            return
        config.set_string("messages", "one_time_codes", mode)
        if mode == "off":
            self.codes.forget()

    def auto_copy_codes(self):
        """Copy a code as soon as it arrives, without waiting for « Copier le code »."""
        config = getattr(self.hooks, "config", None)
        return config.boolean("messages", "auto_copy_codes", True) if config else True

    def set_auto_copy_codes(self, enabled):
        config = getattr(self.hooks, "config", None)
        if config:
            config.set_boolean("messages", "auto_copy_codes", bool(enabled))

    def latest_code(self, purpose):
        """(code, age in seconds) for the Covalence app ("copy") or the browser extension
        ("browser"); ("", 0) when there is none, it is too old, or the setting refuses it."""
        mode = self.code_mode()
        if mode == "off" or (purpose == "browser" and mode != "browser"):
            return "", 0
        if purpose != "browser":
            # "copy" only answers the helper the daemon itself just started after a click on
            # « Copier le code » (see _copy_code), once: not any program that asks.
            granted, self.copy_granted = getattr(self, "copy_granted", 0.0), 0.0
            if not granted or time.monotonic() - granted > COPY_GRANT_SECONDS:
                return "", 0
        code, age, _key = self.codes.latest()
        return code, age

    def _copy_code(self, key, delete):
        """The daemon has no clipboard: the Covalence app copies the code and clears it later."""
        app = self._app_path((APP_ID,))
        if not app:
            log("messages : application Covalence introuvable")
            return
        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.NONE)
        self.copy_granted = time.monotonic()
        if os.environ.get("DISPLAY"):
            # Wayland gives the clipboard to the focused window only; XWayland shares it anyway.
            launcher.setenv("GDK_BACKEND", "x11", True)
        try:
            launcher.spawnv([app, "--copy-code"])
        except GLib.Error as error:
            log(f"messages : copie du code impossible ({error.message})")
            return
        if delete and key:
            self.delete_message(key)

    # --- reactions ---------------------------------------------------------------------------------

    def _classify(self, key):
        """If this message is a reaction sent as text (see reactions.py) to a message of the
        same thread, record it as a badge and hide the bubble. Returns what was found."""
        store = self.store
        m = store.message(key) if store else None
        if not m or m["kind"] == "reaction" or m["status"] == "failed":
            return None
        names = []
        if not m["outgoing"]:
            full = store.display_name(m["sender"], m["sender_name"] or "") if m["sender"] \
                else (m["sender_name"] or "")
            for name in (full, m["sender_name"] or ""):
                if name:
                    names += [name, name.split()[0]]
        found = reactions.parse(m["body"], names)
        if found is None:
            return None
        target = store.reaction_target(m["thread"], found["quote"], m["time"], exclude=key)
        author = "" if m["outgoing"] else (m["sender"] or ("name:" + (m["sender_name"] or "")))
        thread = store.thread(m["thread"])
        if author and thread and not thread["is_group"]:
            # One person on the other side: MAP (number) and ANCS (name) copies share an author.
            people = thread["participants"] or []
            if len(people) == 1 and people[0]:
                author = people[0]
        if target is None:
            # The quoted message is not here (sent from the iPhone, MAP does not list it): the
            # reaction stays as a short note; a second copy (MAP + ANCS) is hidden behind it.
            note = None
            for row in store.db.execute(
                    "SELECT key, body, sender, sender_name, outgoing FROM messages "
                    "WHERE thread=? AND kind='reaction-note' AND key<>? AND ABS(time-?)<600",
                    (m["thread"], key, m["time"])):
                other = reactions.parse(row["body"], names)
                if other and other["emoji"] == found["emoji"] and \
                        other["removed"] == found["removed"] and \
                        reactions.normalize(other["quote"] or "") == \
                        reactions.normalize(found["quote"] or ""):
                    note = row["key"]
                    break
            if note is None:
                store.db.execute("UPDATE messages SET kind='reaction-note' WHERE key=?", (key,))
                return dict(found, target=None, author=author, duplicate=False)
            store.add_reaction(key, "note:" + note, m["thread"], author, found["emoji"],
                               m["time"], found["removed"])
            return dict(found, target=None, author=author, duplicate=True)
        # The same reaction reported by MAP and by the notification: shown and notified once.
        duplicate = store.db.execute(
            "SELECT 1 FROM reactions WHERE thread=? AND target=? AND COALESCE(author, '')=? "
            "AND emoji=? AND removed=? AND key<>? AND ABS(time-?)<600",
            (m["thread"], target, author, found["emoji"], int(found["removed"]), key,
             m["time"])).fetchone() is not None
        store.add_reaction(key, target, m["thread"], author, found["emoji"], m["time"],
                           found["removed"])
        log("messages : réaction reconnue")
        return dict(found, target=target, author=author, duplicate=duplicate)

    def _classify_all(self):
        """Reactions stored as bubbles (older parser, ANCS copies): make them badges."""
        store = self.store
        rows = store.db.execute(
            "SELECT key FROM messages WHERE COALESCE(kind, '')<>'reaction' "
            "AND COALESCE(status, '')<>'failed' ORDER BY time DESC LIMIT 2000").fetchall()
        count = 0
        for row in reversed(rows):
            found = self._classify(row["key"])
            count += bool(found and (found["target"] or found["duplicate"]))
        if count:
            store.commit()
            log(f"messages : {count} réaction(s) rattachée(s) au message cité")

    def _notify_reaction(self, tid, key, found):
        m, thread = self.store.message(key), self.store.thread(tid)
        target = self.store.message(found["target"]) if found["target"] else None
        if not m or not thread or tid == self.viewing:
            return
        name = self.store.display_name(m["sender"], m["sender_name"] or _("Inconnu"))
        quote = reactions.quote_of(target["body"] if target else found["quote"] or "")
        body = _("{name} a réagi {emoji} à « {quote} »").format(
            name=name, emoji=found["emoji"], quote=quote)
        summary = self.store.thread_title(thread) or name
        hints = {"category": GLib.Variant("s", "im.received")}
        photo = self.store.photo(m["sender"] or "")
        if photo:
            hints["image-path"] = GLib.Variant("s", photo)
        self._sound(hints)
        self.notifications[tid] = self.notifier.notify(
            f"Covalence ({self.hooks.device_name})", "io.github.melvincouwez.Covalence.Messages",
            summary, body, [("default", _("Ouvrir"))], hints,
            replaces=self.notifications.get(tid, 0),
            on_action=lambda action, t=tid: self._on_notification_action(t, action),
            on_closed=lambda t=tid: self.notifications.pop(t, None))

    def reactions_enabled(self):
        config = getattr(self.hooks, "config", None)
        return not config or config.boolean("messages", "send_reactions", True)

    def send_reaction(self, key, emoji, on_done):
        """React to a message: an SMS in the iPhone's own words, only on the user's request."""
        m = self.store.message(key) if self.store else None
        if not m or m["kind"] == "reaction":
            return on_done("no such message")
        if not self.reactions_enabled():
            return on_done("reactions are turned off")
        emoji = (emoji or "").strip()
        if not emoji or len(emoji) > 16:
            return on_done("invalid emoji")
        self.send(m["thread"], reactions.build(emoji, m["body"] or "", i18n.language()), on_done)

    @staticmethod
    def _app_path(names):
        for name in names:
            path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), name)
            app = path if os.access(path, os.X_OK) else (shutil.which(name) or "")
            if app:
                return app
        return ""

    def _on_notification_action(self, tid, action, key=""):
        self.notifications.pop(tid, None)
        if action in ("copy-code", "copy-code-delete"):
            self._copy_code(key, action == "copy-code-delete")
            return
        if action.startswith("inline-reply:"):
            # Typed in the notification itself: that is the user's explicit request.
            self.send(tid, action.split(":", 1)[1],
                      lambda error: error and log("messages : réponse rapide non envoyée"))
            self.mark_seen(tid)
            return
        app = self._app_path((APP_ID + ".Messages", APP_ID))  # the Messages app, else Covalence
        if not app:
            log("messages : application Covalence introuvable")
            return
        args = [app, "--reply" if action == "reply" else "--thread", tid]
        try:
            Gio.Subprocess.new(args, Gio.SubprocessFlags.NONE)
        except GLib.Error as error:
            log(f"messages : ouverture de l'application impossible ({error.message})")

    # --- API for the D-Bus service -----------------------------------------------------------------------

    def can_send(self, thread):
        if not thread or thread["is_group"]:
            return False
        people = thread["participants"]
        return len(people) == 1 and bmsg.is_phone(people[0])

    def threads(self):
        if not self.store:
            return []
        result = []
        drafts = self.store.drafts()
        for t in self.store.threads():
            result.append({
                "id": t["id"], "name": t["name"], "snippet": t["snippet"], "time": t["time"],
                "unread": t["unread"], "group": t["is_group"], "outgoing": t["last_outgoing"],
                "can_send": self.can_send(t), "participants": t["participants"],
                "avatar": "" if t["is_group"] or not t["participants"]
                else self.store.photo(t["participants"][0]),
                "draft": drafts.get(t["id"], ""),
                "pinned": t["pinned"], "marked_unread": t["marked_unread"],
            })
        return result

    def set_pinned(self, tid, pinned):
        if self.store and self.store.thread(tid):
            self.store.set_pinned(tid, pinned)
            self.hooks.messages_changed(threads=True)

    def set_marked_unread(self, tid, marked):
        """Local only: the iPhone keeps its own read state."""
        if self.store and self.store.thread(tid):
            self.store.set_marked_unread(tid, marked)
            self.hooks.messages_changed(threads=True)

    def set_draft(self, tid, text):
        if self.store and self.store.thread(tid):
            self.store.set_draft(tid, text[:MAX_TEXT])
            self.hooks.messages_changed(threads=True)

    def search(self, query):
        query = (query or "").strip()
        return self.store.search(query) if self.store and query else []

    def search_messages(self, query, limit=200):
        """Conversations whose name matches, then messages containing query, grouped by
        conversation (the conversation with the newest hit first). Case and accents are
        ignored. Each result: thread, name, avatar, message key ("" for a name match),
        time, and the excerpt as before / match / after."""
        query = " ".join((query or "").split())
        if not self.store or not query:
            return []
        store = self.store
        threads = {t["id"]: t for t in store.threads()}
        results = []
        for t in threads.values():
            cut = excerpt(t["name"], query)
            if cut:
                results.append(self._hit(t, "", t["time"], cut))
        by_thread = {}
        order = []
        for m in store.search_messages(query, limit):
            t = threads.get(m["thread"])
            cut = excerpt(m["body"], query)
            if t is None or cut is None:
                continue
            if m["thread"] not in by_thread:
                by_thread[m["thread"]] = []
                order.append(m["thread"])
            by_thread[m["thread"]].append(self._hit(t, m["key"], m["time"], cut,
                                                    outgoing=bool(m["outgoing"])))
        for tid in order:
            results.extend(by_thread[tid])
        return results

    def _hit(self, thread, key, when, cut, outgoing=False):
        before, match, after = cut
        return {"thread": thread["id"], "name": thread["name"], "message": key, "time": when,
                "before": before, "match": match, "after": after, "outgoing": outgoing,
                "group": thread["is_group"],
                "avatar": "" if thread["is_group"] or not thread["participants"]
                else self.store.photo(thread["participants"][0])}

    def unread_total(self):
        return self.store.unread_total() if self.store else 0

    def set_viewing(self, tid):
        """The app shows this thread in a focused window ('' when not): no banner for it."""
        self.viewing = tid or ""

    def contacts(self):
        return self.store.contact_cards() if self.store else []

    def open_conversation(self, address):
        """Thread for one address, created if needed (a new message). None if invalid."""
        address = bmsg.normalize_address(address)
        if not self.store or not address:
            return None
        tid = self.store.ensure_thread([address])
        self.store.commit()
        thread = self.store.thread(tid)
        return {"id": tid, "name": self.store.display_name(address), "snippet": "", "time": 0,
                "unread": 0, "group": False, "outgoing": False,
                "can_send": self.can_send(thread), "participants": [address],
                "avatar": self.store.photo(address)}

    def messages(self, tid):
        if not self.store:
            return []
        result = []
        badges = self.store.reactions_for(tid)
        for m in self.store.messages(tid):
            result.append({
                "id": m["key"], "outgoing": bool(m["outgoing"]),
                "sender": "" if m["outgoing"] else self.store.display_name(
                    m["sender"], m["sender_name"] or _("Inconnu")),
                "address": m["sender"] or "", "time": m["time"], "body": m["body"] or "",
                "complete": bool(m["complete"]), "source": m["source"] or "",
                "status": m["status"] or "",
                "avatar": "" if m["outgoing"] else self.store.photo(m["sender"] or ""),
                "reactions": [(emoji, self._author_name(author), not author, pending)
                              for emoji, author, pending in badges.get(m["key"], [])],
                "note": self._reaction_note(m) if m["kind"] == "reaction-note" else "",
            })
        return result

    def _reaction_note(self, m):
        """« Alice a réagi ❤️ à « … » » for a reaction whose message is not in Covalence."""
        name = self.store.display_name(m["sender"], m["sender_name"] or "") if m["sender"] \
            else (m["sender_name"] or "")
        names = [name, name.split()[0]] if name else []
        found = reactions.parse(m["body"] or "", names)
        if not found:
            return ""
        who = _("Moi") if m["outgoing"] else (name or _("Inconnu"))
        if found["removed"]:
            text = _("{name} a retiré {emoji}")
        else:
            text = _("{name} a réagi {emoji}")
        text = text.format(name=who, emoji=found["emoji"])
        if found["quote"]:
            text += " " + _("à « {quote} »").format(quote=reactions.quote_of(found["quote"]))
        return text

    def _author_name(self, author):
        if not author:
            return _("Moi")
        if author.startswith("name:"):
            return author[5:] or _("Inconnu")
        return self.store.display_name(author, author)

    def mark_seen(self, tid):
        if self.store:
            self.store.mark_seen(tid)
            self.notifier.close(self.notifications.pop(tid, 0))
            self.hooks.messages_changed(threads=True)
            if self._alpha("mark_read"):
                self._mark_read_on_phone(tid)

    def _read_candidates(self, tid):
        """Unread received messages of the thread that this MAP session has listed."""
        rows = self.store.db.execute(
            "SELECT key, handle FROM messages WHERE thread=? AND source='map' AND outgoing=0 "
            "AND phone_read=0 AND COALESCE(handle, '')<>''", (tid,)).fetchall()
        return [(row["key"], row["handle"]) for row in rows if row["handle"] in self.listed]

    def _mark_read_on_phone(self, tid):
        """Alpha « mark_read »: MAP Message1.Read = true on the iPhone for this thread."""
        session = self.session
        wanted = self._read_candidates(tid) if session and self.worker else []
        if not wanted:
            return

        def job():
            done = []
            for key, handle in wanted:
                try:
                    self._call(f"{session}/message{handle}", "org.freedesktop.DBus.Properties",
                               "Set", GLib.Variant("(ssv)", (MESSAGE, "Read", GLib.Variant("b", True))))
                    done.append(key)
                except GLib.Error as error:
                    log(f"messages (alpha) : marquage lu refusé ({error.message})")
            return done

        def finished(done, error):
            if error or not done:
                return
            for key in done:
                self.store.db.execute("UPDATE messages SET phone_read=1 WHERE key=?", (key,))
            self.store.commit()
            log(f"messages (alpha) : {len(done)}/{len(wanted)} message(s) marqué(s) lu(s) "
                "sur l'iPhone")
            self.hooks.messages_changed(threads=True)

        self.worker.submit(job, finished)

    def send(self, tid, text, on_done, retry_key=None):
        """Send one SMS through MAP PushMessage, only on the user's request.

        The message is stored first (status "sending"), so its text is never lost:
        on failure it stays in the thread as "failed" and can be sent again with
        retry(). Nothing is ever resent automatically: after a timeout the phone
        may already have sent it, and a duplicate SMS cannot be taken back.
        on_done(error_message | None).
        """
        thread = self.store.thread(tid) if self.store else None
        text = (text or "").strip()
        if not text:
            return on_done("empty message")
        if len(text) > MAX_TEXT:
            return on_done("message too long")
        if not self.can_send(thread):
            return on_done("this conversation cannot be answered from the PC")
        if retry_key:
            key = retry_key
        else:
            key = "covalence:" + uuid.uuid4().hex
        self.store.upsert(key, tid, True, "", "", int(time.time()), text, True,
                          kind="sms", source="covalence", status="sending")
        self._classify(key)  # a reaction shows as a badge "Moi", pending until listed
        self.store.commit()
        self.hooks.messages_changed(threads=True)

        if not self.session:
            self._send_failed(key, "the iPhone is not connected for messages")
            self._open_session()
            return on_done("the iPhone is not connected for messages")

        number = thread["participants"][0]
        name = self.store.display_name(number, "")
        session, tmp = self.session, self.store.tmp
        target = os.path.join(tmp, f"push-{uuid.uuid4().hex}.bmsg")
        old_umask = os.umask(0o077)
        try:
            with open(target, "w", encoding="utf-8", newline="") as f:
                f.write(bmsg.build_bmessage(number, text, name))
        finally:
            os.umask(old_umask)

        def progress(fraction):
            GLib.idle_add(lambda: self.hooks.send_progress(tid, key, fraction) and False)

        def job():
            try:
                progress(0.05)
                self._call(session, MAP, "SetFolder", GLib.Variant("(s)", ("/telecom/msg",)))
                transfer = self._call(session, MAP, "PushMessage", GLib.Variant("(ssa{sv})", (
                    target, "outbox", {"Charset": GLib.Variant("s", "utf8")})), "(oa{sv})")[0]
                self._wait_transfer(transfer, timeout=SEND_TIMEOUT, progress=progress)
                progress(1.0)
            finally:
                if os.path.exists(target):
                    os.unlink(target)

        def done(_result, error):
            if error:
                if _is_unsupported(error):
                    # Remembered for the explanation, but never a hard block.
                    self.store.set_meta("can_send", "no")
                    log("messages : l'iPhone a refusé l'envoi par MAP")
                else:
                    log(f"messages : envoi échoué ({error})")
                self._send_failed(key, error)
                on_done(error)
                return
            # On 2026-09-26 the iPhone did send what it accepted (the recipient
            # answered) although outbox and sent stayed empty for a while.
            self.store.set_meta("can_send", "yes")
            self.store.set_draft(tid, "")
            self.store.upsert(key, tid, True, "", "", int(time.time()), text, True,
                              kind="sms", source="covalence", status="sent")
            self.store.commit()
            log("messages : message transmis à l'iPhone")
            self.hooks.messages_changed(threads=True)
            on_done(None)
            GLib.timeout_add_seconds(5, lambda: self.sync(count=10) and False)
            GLib.timeout_add_seconds(SEND_CONFIRM, lambda: self.sync(count=10) and False)

        self.worker.submit(job, done, urgent=True)

    def _send_failed(self, key, _error):
        m = self.store.message(key)
        if m:
            self.store.drop_reaction(key)  # a failed reaction is a bubble again: retry or delete
            m = self.store.message(key)
            self.store.upsert(key, m["thread"], True, "", "", m["time"], m["body"], True,
                              kind=m["kind"], source="covalence", status="failed")
            self.store.commit()
        self.hooks.messages_changed(threads=True)

    def retry_message(self, key, on_done):
        """Send a failed message again (explicit user request)."""
        m = self.store.message(key) if self.store else None
        if not m or m["source"] != "covalence" or m["status"] != "failed":
            return on_done("nothing to send again")
        self.send(m["thread"], m["body"], on_done, retry_key=key)

    def delete_message(self, key):
        """Remove a message from Covalence (the iPhone keeps it)."""
        if self.store and self.store.hide(key):
            self.store.commit()
            self.hooks.messages_changed(threads=True)

    def delete_conversation(self, tid):
        if self.store and self.store.thread(tid):
            self.store.hide_thread(tid)
            self.store.commit()
            if self.viewing == tid:
                self.viewing = ""
            self.hooks.messages_changed(threads=True)

    def discard_message(self, key):
        """Forget a failed message that the user does not want to send."""
        m = self.store.message(key) if self.store else None
        if m and m["source"] == "covalence" and m["status"] == "failed":
            self.store.delete(key)
            self.store.commit()
            self.hooks.messages_changed(threads=True)
