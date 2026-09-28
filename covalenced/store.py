# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Local message cache: ~/.local/share/covalence/messages/messages.db (SQLite).

iOS only exposes part of the history over MAP, so the cache is what lets
Covalence show conversations over time. The directory is 0700 and the files
0600: message text never leaves this user's account. Only the main thread
touches the database.

"seen" is Covalence's own read marker. It never changes the iPhone's state.
"""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
import unicodedata

from gi.repository import GLib

from .bmsg import thread_id
from .i18n import _

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
  key TEXT PRIMARY KEY,
  handle TEXT,
  thread TEXT NOT NULL,
  outgoing INTEGER NOT NULL,
  sender TEXT,
  sender_name TEXT,
  time INTEGER NOT NULL,
  body TEXT,
  complete INTEGER NOT NULL DEFAULT 0,
  kind TEXT,
  phone_read INTEGER NOT NULL DEFAULT 0,
  seen INTEGER NOT NULL DEFAULT 0,
  source TEXT,
  status TEXT
);
CREATE INDEX IF NOT EXISTS messages_thread ON messages(thread, time);
CREATE TABLE IF NOT EXISTS threads(
  id TEXT PRIMARY KEY,
  participants TEXT NOT NULL,
  title TEXT,
  is_group INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS contacts(address TEXT PRIMARY KEY, name TEXT NOT NULL, photo TEXT);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS drafts(thread TEXT PRIMARY KEY, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hidden(key TEXT PRIMARY KEY, thread TEXT, words TEXT, time INTEGER);
CREATE TABLE IF NOT EXISTS reactions(key TEXT PRIMARY KEY, target TEXT NOT NULL,
                                     thread TEXT NOT NULL, author TEXT, emoji TEXT NOT NULL,
                                     time INTEGER NOT NULL, removed INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS reactions_target ON reactions(target);
CREATE TABLE IF NOT EXISTS calls(pos INTEGER PRIMARY KEY, address TEXT, name TEXT,
                                 time INTEGER, kind TEXT);
CREATE TABLE IF NOT EXISTS thread_flags(thread TEXT PRIMARY KEY,
                                        pinned INTEGER NOT NULL DEFAULT 0,
                                        marked_unread INTEGER NOT NULL DEFAULT 0);
"""


# iOS titles a reply to one of your messages "<name> vous a répondu" / "<name> replied to
# you": the sender is the name alone, or the reply lands in a conversation of its own.
_REPLY_TITLE = re.compile(r"\s+(?:vous a répondu|a répondu|replied to you|replied)\s*$",
                          re.IGNORECASE)


def sender_from_title(title):
    return _REPLY_TITLE.sub("", (title or "").replace("\xa0", " ")).strip() or title


CONTACTS_SCHEMA = "2"  # 2: with photos
CLOCK_GAP = 120  # seconds of clock difference tolerated between the iPhone and the PC
REUSED_HANDLE_GAP = 2 * 24 * 3600  # same handle, another text, days apart: another message


def _words(text):
    return " ".join((text or "").split())


def _resolvable_private(address):
    """Bluetooth resolvable private address (top bits 01): random, not the phone's identity."""
    try:
        return int(address.split(":")[0], 16) & 0xC0 == 0x40
    except ValueError:
        return False


def fold(text):
    """Comparable form for search: no accents, case-folded ("Élodie" -> "elodie")."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _folded_spans(text):
    """fold(text) and, for each of its characters, the index of the source character."""
    out, where = [], []
    for i, c in enumerate(text or ""):
        for f in fold(c):
            out.append(f)
            where.append(i)
    return "".join(out), where


def excerpt(text, query, width=70):
    """(before, match, after) around the first match of query in text, accents ignored;
    None when absent. before and after are cut to about width characters."""
    text = " ".join((text or "").split())
    folded, where = _folded_spans(text)
    q = fold(query)
    pos = folded.find(q) if q else -1
    if pos < 0:
        return None
    start, end = where[pos], where[pos + len(q) - 1] + 1
    before, match, after = text[:start], text[start:end], text[end:]
    if len(before) > width // 2:
        before = "…" + before[-(width // 2):].lstrip()
    if len(after) > width:
        after = after[:width].rstrip() + "…"
    return before, match, after


def private_dir(path):
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return path


class Store:
    def __init__(self, directory=None):
        self.dir = private_dir(directory or os.path.join(GLib.get_user_data_dir(), "covalence",
                                                         "messages"))
        self.tmp = private_dir(os.path.join(self.dir, "tmp"))
        self.path = os.path.join(self.dir, "messages.db")
        old_umask = os.umask(0o077)  # database and its journal files: 0600
        try:
            self.db = sqlite3.connect(self.path)
        finally:
            os.umask(old_umask)
        os.chmod(self.path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.create_function("fold", 1, fold, deterministic=True)
        self.db.executescript(SCHEMA)
        columns = [r[1] for r in self.db.execute("PRAGMA table_info(contacts)")]
        if "photo" not in columns:
            self.db.execute("ALTER TABLE contacts ADD COLUMN photo TEXT")
        self.photos = os.path.join(self.dir, "photos")
        self._upgrade_after_rename()
        self.db.commit()
        self._contacts = None

    def _upgrade_after_rename(self):
        """The app was called Tandem until 2026-09-27: its own sends were tagged "tandem",
        and the cache moved folder (photo paths are absolute)."""
        for table in ("messages", "hidden"):
            self.db.execute(f"UPDATE {table} SET key='covalence:' || substr(key, 8) "
                            "WHERE key LIKE 'tandem:%'")
        self.db.execute("UPDATE messages SET source='covalence' WHERE source='tandem'")
        for address, photo in self.db.execute(
                "SELECT address, photo FROM contacts WHERE photo LIKE '/%'").fetchall():
            moved = os.path.join(self.photos, os.path.basename(photo))
            if photo != moved and not os.path.exists(photo):
                self.db.execute("UPDATE contacts SET photo=? WHERE address=?", (moved, address))

    def close(self):
        self.db.close()

    # --- meta -----------------------------------------------------------------------------

    def meta(self, key, default=""):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES(?, ?)", (key, str(value)))
        self.db.commit()

    def self_addresses(self):
        return set(json.loads(self.meta("self_addresses", "[]")))

    def add_self_address(self, address):
        known = self.self_addresses()
        if address and address not in known:
            known.add(address)
            self.set_meta("self_addresses", json.dumps(sorted(known)))

    # --- contacts ----------------------------------------------------------------------------

    def replace_contacts(self, cards):
        """Replace the phone book; photos go to photos/ (0700 directory, 0600 files)."""
        self.db.execute("DELETE FROM contacts")
        shutil.rmtree(self.photos, ignore_errors=True)
        private_dir(self.photos)
        old_umask = os.umask(0o077)
        try:
            for card in cards:
                if not card["name"] or not card["addresses"]:
                    continue
                photo = ""
                if card.get("photo"):
                    key = f"{card['name']}|{card['addresses'][0]}".encode("utf-8")
                    photo = os.path.join(self.photos, hashlib.sha1(key).hexdigest()[:16])
                    with open(photo, "wb") as f:
                        f.write(card["photo"])
                for address in card["addresses"]:
                    self.db.execute("INSERT OR REPLACE INTO contacts VALUES(?, ?, ?)",
                                    (address, card["name"], photo))
        finally:
            os.umask(old_umask)
        self.set_meta("contacts_time", int(time.time()))
        self.set_meta("contacts_schema", CONTACTS_SCHEMA)
        self._contacts = None

    def contacts(self):
        if self._contacts is None:
            self._contacts = dict(self.db.execute("SELECT address, name FROM contacts"))
        return self._contacts

    def contact_cards(self):
        """The iPhone phone book as cards: [{'name', 'addresses', 'photo'}], sorted by name."""
        cards = {}
        for address, name, photo in self.db.execute(
                "SELECT address, name, COALESCE(photo, '') FROM contacts"):
            card = cards.setdefault((name, photo), {"name": name, "addresses": [],
                                                    "photo": photo if photo and os.path.exists(photo) else ""})
            card["addresses"].append(address)
        return sorted(cards.values(), key=lambda c: c["name"].casefold())

    def photo(self, address):
        if not address:
            return ""
        row = self.db.execute("SELECT photo FROM contacts WHERE address=?", (address,)).fetchone()
        return row[0] if row and row[0] and os.path.exists(row[0]) else ""

    def contact_name(self, address):
        return self.contacts().get(address, "")

    def address_for_name(self, name):
        """Address of a contact or known sender with exactly this display name."""
        for address, contact in self.contacts().items():
            if contact == name:
                return address
        row = self.db.execute(
            "SELECT sender FROM messages WHERE sender_name=? AND sender<>'' "
            "ORDER BY time DESC LIMIT 1", (name,)).fetchone()
        return row[0] if row else ""

    def display_name(self, address, fallback=""):
        if not address:
            return fallback
        name = self.contact_name(address)
        if name:
            return name
        row = self.db.execute(
            "SELECT sender_name FROM messages WHERE sender=? AND sender_name<>'' "
            "ORDER BY time DESC LIMIT 1", (address,)).fetchone()
        return row[0] if row else (fallback or address)

    # --- threads -----------------------------------------------------------------------------

    def ensure_thread(self, participants, title="", is_group=None):
        participants = sorted(set(p for p in participants if p))
        tid = thread_id(participants)
        group = len(participants) > 1 if is_group is None else is_group
        row = self.db.execute("SELECT title FROM threads WHERE id=?", (tid,)).fetchone()
        if row is None:
            self.db.execute("INSERT INTO threads VALUES(?, ?, ?, ?)",
                            (tid, json.dumps(participants), title, int(group)))
        elif title and not row[0]:
            self.db.execute("UPDATE threads SET title=? WHERE id=?", (title, tid))
        return tid

    def merge_name_threads(self):
        """Move 1:1 conversations known only by a name ("name:Alice …", from notifications that
        came before the phone book) into the conversation of that contact's number.
        Returns how many were merged."""
        merged = 0
        for row in self.db.execute("SELECT id, participants FROM threads").fetchall():
            people = json.loads(row["participants"])
            if len(people) != 1 or not people[0].startswith("name:"):
                continue
            address = self.address_for_name(sender_from_title(people[0][5:]))
            if not address:
                continue
            target = self.ensure_thread([address], is_group=False)
            if target == row["id"]:
                continue
            # A conversation deleted in Covalence stays deleted, and a message the number's
            # conversation already has (its MAP copy) is not brought in twice.
            cleared = int(self.meta("cleared:" + target, "0") or 0)
            for m in self.db.execute("SELECT key, body, time FROM messages WHERE thread=?",
                                     (row["id"],)).fetchall():
                if int(m["time"]) <= cleared or self._hidden_like(target, m["body"], m["time"]) \
                        or self._same_text_near(target, m["body"], m["time"], exclude=m["key"]):
                    self.delete(m["key"])
            for table in ("messages", "reactions", "hidden"):
                self.db.execute(f"UPDATE {table} SET thread=? WHERE thread=?", (target, row["id"]))
            self.db.execute("UPDATE messages SET sender=? WHERE thread=? AND outgoing=0 "
                            "AND COALESCE(sender, '')=''", (address, target))
            self.db.execute("INSERT OR IGNORE INTO drafts SELECT ?, text FROM drafts WHERE thread=?",
                            (target, row["id"]))
            for table, column in (("drafts", "thread"), ("thread_flags", "thread"), ("threads", "id")):
                self.db.execute(f"DELETE FROM {table} WHERE {column}=?", (row["id"],))
            merged += 1
        if merged:
            self.commit()
        return merged

    def _same_text_near(self, tid, body, when, window=600, exclude=""):
        words = _words(body)
        if not words:
            return False
        for row in self.db.execute(
                "SELECT body FROM messages WHERE thread=? AND key<>? AND ABS(time-?)<?",
                (tid, exclude, int(when), window)):
            if _words(row["body"]) == words:
                return True
        return False

    def _hidden_like(self, tid, body, when):
        words = _words(body)[:40]
        if not words:
            return False
        for row in self.db.execute("SELECT words FROM hidden WHERE thread=? AND ABS(time-?)<600",
                                   (tid, int(when))):
            if row[0] and (words.startswith(row[0]) or row[0].startswith(words)):
                return True
        return False

    def remove_duplicates(self):
        """One-off cleanup of copies left by older versions: a notification (ANCS) copy of a
        message that the same conversation also has from MAP or from another notification,
        same words within 10 minutes. The MAP copy (or the oldest one) is kept."""
        removed = 0
        rows = self.db.execute(
            "SELECT key, thread, body, time FROM messages WHERE source='ancs' "
            "AND COALESCE(kind, '') NOT IN ('reaction', 'reaction-note') ORDER BY time").fetchall()
        for row in rows:
            if self.message(row["key"]) is None:
                continue
            words = _words(row["body"])
            if not words:
                continue
            for other in self.db.execute(
                    "SELECT key, body, source, time FROM messages WHERE thread=? AND key<>? "
                    "AND ABS(time-?)<600", (row["thread"], row["key"], int(row["time"]))).fetchall():
                if _words(other["body"]) != words:
                    continue
                if other["source"] != "ancs" or \
                        (other["time"], other["key"]) < (row["time"], row["key"]):
                    self.delete(row["key"])
                    removed += 1
                    break
        return removed

    # --- device identity ----------------------------------------------------------------------

    def claim_device(self, address):
        """The cache belongs to one iPhone: MAP handles are only unique on that phone.
        First connection after an upgrade: the existing cache is taken as this phone's.
        Another iPhone: the current cache is archived next to it (never deleted) and an
        empty one starts. Returns the archive path, or None."""
        if not address or _resolvable_private(address):
            # A private address changes over time and becomes the identity address once
            # the phone's key is resolved: never a reason to archive anything.
            return None
        owner = self.meta("device")
        if not owner:
            self.set_meta("device", address)
            self.commit()
            return None
        if owner == address:
            return None
        stamp = time.strftime("%Y%m%d-%H%M%S")
        tag = "".join(c for c in owner if c.isalnum())
        archive = os.path.join(self.dir, f"messages-{tag}-{stamp}.db")
        self.db.commit()
        old_umask = os.umask(0o077)
        try:
            self.db.execute("VACUUM INTO ?", (archive,))
        finally:
            os.umask(old_umask)
        os.chmod(archive, 0o600)
        for table in ("messages", "threads", "contacts", "drafts", "hidden", "reactions",
                      "calls", "thread_flags", "meta"):
            self.db.execute(f"DELETE FROM {table}")
        if os.path.isdir(self.photos):
            os.replace(self.photos, os.path.join(self.dir, f"photos-{tag}-{stamp}"))
        private_dir(self.photos)
        self._contacts = None
        self.set_meta("device", address)
        self.commit()
        return archive

    def thread(self, tid):
        row = self.db.execute("SELECT * FROM threads WHERE id=?", (tid,)).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "participants": json.loads(row["participants"]),
                "title": row["title"] or "", "is_group": bool(row["is_group"])}

    def thread_title(self, thread):
        if thread["title"] and not thread["participants"]:
            return thread["title"]
        names = [self.display_name(p) for p in thread["participants"]
                 if not p.startswith("name:")]
        names += [p[5:] for p in thread["participants"] if p.startswith("name:")]
        if thread["is_group"] and len(names) > 1:
            return ", ".join(n.split(" ")[0] if len(names) > 2 else n for n in names)
        return names[0] if names else (thread["title"] or _("Inconnu"))

    def threads(self):
        """Pinned threads first (in the order they were pinned), then the newest."""
        rows = self.db.execute("""
            SELECT t.*, m.body AS body, m.time AS time, m.outgoing AS outgoing,
                   (SELECT COUNT(*) FROM messages u WHERE u.thread=t.id AND u.outgoing=0
                    AND u.seen=0) AS unread,
                   COALESCE(f.pinned, 0) AS pinned, COALESCE(f.marked_unread, 0) AS marked
            FROM threads t JOIN messages m ON m.key = (
                SELECT key FROM messages WHERE thread=t.id AND COALESCE(kind, '')<>'reaction'
                ORDER BY time DESC LIMIT 1)
            LEFT JOIN thread_flags f ON f.thread = t.id
            ORDER BY COALESCE(f.pinned, 0) = 0, COALESCE(f.pinned, 0), m.time DESC""").fetchall()
        result = []
        for row in rows:
            thread = {"id": row["id"], "participants": json.loads(row["participants"]),
                      "title": row["title"] or "", "is_group": bool(row["is_group"])}
            marked = bool(row["marked"]) and row["unread"] == 0
            thread.update(name=self.thread_title(thread), snippet=row["body"] or "",
                          time=row["time"], unread=row["unread"] or (1 if marked else 0),
                          last_outgoing=bool(row["outgoing"]), pinned=bool(row["pinned"]),
                          marked_unread=marked)
            result.append(thread)
        return result

    def _set_flag(self, tid, column, value):
        self.db.execute("INSERT OR IGNORE INTO thread_flags(thread) VALUES(?)", (tid,))
        self.db.execute(f"UPDATE thread_flags SET {column}=? WHERE thread=?", (value, tid))
        self.db.execute("DELETE FROM thread_flags WHERE pinned=0 AND marked_unread=0")
        self.commit()

    def set_pinned(self, tid, pinned):
        """Pinned threads keep the order they were pinned in."""
        if pinned:
            top = self.db.execute("SELECT COALESCE(MAX(pinned), 0) FROM thread_flags").fetchone()[0]
            current = self.db.execute("SELECT pinned FROM thread_flags WHERE thread=?",
                                      (tid,)).fetchone()
            if current and current[0]:
                return
            self._set_flag(tid, "pinned", int(top) + 1)
        else:
            self._set_flag(tid, "pinned", 0)

    def set_marked_unread(self, tid, marked):
        """Covalence's own "unread" mark; the iPhone is never told."""
        self._set_flag(tid, "marked_unread", int(bool(marked)))

    # --- messages ----------------------------------------------------------------------------

    def message(self, key):
        row = self.db.execute("SELECT * FROM messages WHERE key=?", (key,)).fetchone()
        return dict(row) if row else None

    def has_handle(self, handle):
        return self.db.execute("SELECT 1 FROM messages WHERE handle=?", (handle,)).fetchone() \
            is not None

    def upsert(self, key, thread, outgoing, sender, sender_name, when, body, complete,
               kind="", phone_read=False, seen=False, source="map", handle=None, status="",
               time_known=True):
        """Insert or merge a message; returns True if it is new.

        time_known=False: the listing had no usable timestamp, keep the stored time."""
        old = self.message(key)
        if old is not None and source == "map" and old["source"] == "map" \
                and self._reused_handle(old, body, when):
            # iOS gave this handle to another message (restored or reset phone): the old one
            # keeps its place under a key of its own.
            self._rekey(key, f"{key}@{old['time']}")
            old = None
        if self.is_hidden(key, thread, body, when):
            return False  # deleted in Covalence: the iPhone keeps listing it
        if old is None:
            self.db.execute(
                "INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (key, handle, thread, int(outgoing), sender, sender_name, int(when), body,
                 int(complete), kind, int(phone_read), int(seen or outgoing), source, status))
            return True
        if old["kind"] in ("reaction", "reaction-note"):
            kind = old["kind"]  # shown as a badge; a new listing must not make it a bubble again
        if not time_known:
            when = old["time"]
        if thread != old["thread"]:
            here = self.thread(old["thread"])
            there = self.thread(thread)
            # The envelope put it in a group conversation: a later listing (one sender,
            # no recipients) must not bring it back to the one-to-one conversation.
            if here and here["is_group"] and not (there and there["is_group"]):
                thread = old["thread"]
        # Never replace a complete body by the (truncated) listing subject.
        if old["complete"] and not complete:
            body, complete = old["body"], 1
        elif not complete and len(old["body"] or "") > len(body or ""):
            body = old["body"]
        self.db.execute(
            "UPDATE messages SET thread=?, sender=?, sender_name=?, time=?, body=?, complete=?,"
            " kind=?, phone_read=?, seen=MAX(seen, ?), status=? WHERE key=?",
            (thread, sender or old["sender"], sender_name or old["sender_name"], int(when), body,
             int(complete), kind or old["kind"], int(phone_read), int(phone_read or seen),
             status or old["status"], key))
        return False

    def _reused_handle(self, old, body, when):
        if abs(int(old["time"]) - int(when)) < REUSED_HANDLE_GAP:
            return False
        a, b = _words(old["body"]), _words(body).rstrip("…").rstrip()
        return bool(a) and bool(b) and not (a.startswith(b) or b.startswith(a))

    def _rekey(self, old_key, new_key):
        self.db.execute("UPDATE messages SET key=?, handle=NULL WHERE key=?", (new_key, old_key))
        self.db.execute("UPDATE reactions SET target=? WHERE target=?", (new_key, old_key))
        self.db.execute("UPDATE reactions SET key=? WHERE key=?", (new_key, old_key))
        self.db.execute("UPDATE hidden SET key=? WHERE key=?", (new_key, old_key))

    def find_pending_outgoing(self, thread, body, when, window=900):
        """A message sent from Covalence that the phone now lists (subject may be cut at 120).

        Only a send made before the listed time (give or take a clock gap) can be it: an older
        message with the same text must not take the place of a newer send."""
        # iOS flattens line breaks in the listing's subject: compare words only.
        body = _words(body)
        for row in self.db.execute(
                "SELECT key, thread, body FROM messages WHERE outgoing=1 AND source='covalence' "
                "AND time<=?+? AND ?-time<? ORDER BY time DESC",
                (int(when), CLOCK_GAP, int(when), window)):
            sent = _words(row["body"])
            same_text = sent == body or (len(body) >= 20 and sent.startswith(body.rstrip("…").rstrip()))
            if same_text and (thread is None or row["thread"] == thread):
                return row["key"]
        return None

    def delete(self, key):
        self.db.execute("DELETE FROM messages WHERE key=?", (key,))
        self.db.execute("DELETE FROM reactions WHERE key=? OR target=?", (key, key))

    # --- reactions (tapbacks received or sent as SMS text) --------------------------------------

    def add_reaction(self, key, target, thread, author, emoji, when, removed=False):
        """key: the SMS carrying the reaction; author "" means the user."""
        self.db.execute("INSERT OR REPLACE INTO reactions VALUES(?, ?, ?, ?, ?, ?, ?)",
                        (key, target, thread, author or "", emoji, int(when), int(removed)))
        self.db.execute("UPDATE messages SET kind='reaction', seen=1 WHERE key=?", (key,))

    def drop_reaction(self, key):
        """The SMS behind a reaction is a plain message again (a failed send)."""
        self.db.execute("DELETE FROM reactions WHERE key=?", (key,))
        self.db.execute("UPDATE messages SET kind='sms' WHERE key=? AND kind='reaction'", (key,))

    def reaction(self, key):
        row = self.db.execute("SELECT * FROM reactions WHERE key=?", (key,)).fetchone()
        return dict(row) if row else None

    def reactions_for(self, tid):
        """{target key: [(emoji, author, pending), ...]}: reactions add up, one per emoji and
        author; removing one takes only that emoji away. pending: sent by the user, not yet
        listed by the phone."""
        latest = {}
        for row in self.db.execute(
                "SELECT r.*, m.source AS source FROM reactions r LEFT JOIN messages m "
                "ON m.key = r.key WHERE r.thread=? ORDER BY r.time", (tid,)):
            latest[(row["target"], row["author"] or "", row["emoji"])] = row
        result = {}
        for (target, author, emoji), row in latest.items():
            if row["removed"]:
                continue
            pending = row["source"] == "covalence"
            result.setdefault(target, []).append((emoji, author, pending))
        return result

    def reaction_target(self, tid, quote, before, exclude=None):
        """Key of the most recent message of the thread, older than the reaction, that the
        quoted text designates; with no quote, the latest message sent by the user."""
        from .reactions import matches
        rows = self.db.execute(
            "SELECT key, body, outgoing FROM messages WHERE thread=? AND time<=? "
            "AND COALESCE(kind, '') NOT IN ('reaction', 'reaction-note') "
            "ORDER BY time DESC LIMIT 400",
            (tid, int(before) + 60))
        for row in rows:
            if row["key"] == exclude:
                continue
            if quote is None:
                if row["outgoing"]:
                    return row["key"]
            elif matches(quote, row["body"]):
                return row["key"]
        return None

    # --- deletion by the user (Covalence only: iOS ignores MAP deletes, tested 2026-09-27) ----------

    def hide(self, key):
        """Delete a message and keep it from coming back from MAP or ANCS."""
        m = self.message(key)
        if m is None:
            return None
        self.db.execute("INSERT OR REPLACE INTO hidden VALUES(?, ?, ?, ?)",
                        (key, m["thread"], _words(m["body"])[:40], m["time"]))
        self.delete(key)
        return m["thread"]

    def hide_thread(self, tid):
        """Delete a conversation: everything up to now stays hidden, new messages show."""
        last = self.db.execute("SELECT MAX(time) FROM messages WHERE thread=?", (tid,)).fetchone()[0]
        self.set_meta("cleared:" + tid, max(int(last or 0), int(time.time())))
        self.db.execute("DELETE FROM messages WHERE thread=?", (tid,))
        self.db.execute("DELETE FROM reactions WHERE thread=?", (tid,))
        self.db.execute("DELETE FROM drafts WHERE thread=?", (tid,))
        self.db.execute("DELETE FROM thread_flags WHERE thread=?", (tid,))

    def is_hidden(self, key, thread, body, when):
        if int(when) <= int(self.meta("cleared:" + thread, "0") or 0):
            return True
        row = self.db.execute("SELECT time FROM hidden WHERE key=?", (key,)).fetchone()
        if row and abs(int(row[0]) - int(when)) < REUSED_HANDLE_GAP:
            return True  # (far apart in time: a reused handle, another message)
        # Same message under another key (ANCS copy, Covalence's own copy of a send).
        words = _words(body)[:40]
        if not words:
            return False
        for row in self.db.execute("SELECT words FROM hidden WHERE thread=? AND ABS(time-?)<600",
                                   (thread, int(when))):
            if row[0] and (words.startswith(row[0]) or row[0].startswith(words)):
                return True
        return False

    def messages(self, tid, limit=500):
        rows = self.db.execute(
            "SELECT * FROM (SELECT * FROM messages WHERE thread=? AND COALESCE(kind, '')<>'reaction'"
            " ORDER BY time DESC LIMIT ?)"
            " ORDER BY time", (tid, limit)).fetchall()
        return [dict(r) for r in rows]

    # --- drafts, search, unread ---------------------------------------------------------------

    def drafts(self):
        return dict(self.db.execute("SELECT thread, text FROM drafts"))

    def set_draft(self, tid, text):
        if text.strip():
            self.db.execute("INSERT OR REPLACE INTO drafts VALUES(?, ?)", (tid, text))
        else:
            self.db.execute("DELETE FROM drafts WHERE thread=?", (tid,))
        self.commit()

    @staticmethod
    def _pattern(query):
        q = fold(query)
        return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

    def search(self, query, limit=200):
        """Threads whose messages contain query (case and accents ignored), newest first."""
        rows = self.db.execute(
            "SELECT thread, MAX(time) FROM messages WHERE fold(body) LIKE ? ESCAPE '\\' "
            "AND COALESCE(kind, '')<>'reaction' "
            "GROUP BY thread ORDER BY MAX(time) DESC LIMIT ?", (self._pattern(query), limit))
        return [r[0] for r in rows]

    def search_messages(self, query, limit=200):
        """Messages whose text contains query (case and accents ignored), newest first."""
        return [dict(r) for r in self.db.execute(
            "SELECT key, thread, time, body, outgoing, sender, sender_name FROM messages "
            "WHERE fold(body) LIKE ? ESCAPE '\\' AND COALESCE(kind, '')<>'reaction' "
            "ORDER BY time DESC LIMIT ?", (self._pattern(query), limit))]

    def replace_calls(self, calls):
        self.db.execute("DELETE FROM calls")
        for pos, c in enumerate(calls):
            self.db.execute("INSERT INTO calls VALUES(?, ?, ?, ?, ?)",
                            (pos, c["address"], c["name"], c["time"], c["kind"]))
        self.set_meta("calls_time", int(time.time()))

    def calls(self):
        return [{"address": r[0] or "", "name": r[1] or "", "time": r[2] or 0, "kind": r[3] or ""}
                for r in self.db.execute("SELECT address, name, time, kind FROM calls ORDER BY pos")]

    def unread_total(self):
        """Unread received messages, plus one per thread marked unread by the user."""
        real = self.db.execute(
            "SELECT COUNT(*) FROM messages WHERE outgoing=0 AND seen=0").fetchone()[0]
        marked = self.db.execute(
            "SELECT COUNT(*) FROM thread_flags f WHERE marked_unread=1 AND NOT EXISTS("
            "SELECT 1 FROM messages m WHERE m.thread=f.thread AND m.outgoing=0 AND m.seen=0) "
            "AND EXISTS(SELECT 1 FROM messages m WHERE m.thread=f.thread)").fetchone()[0]
        return real + marked

    def mark_seen(self, tid):
        self.db.execute("UPDATE messages SET seen=1 WHERE thread=? AND seen=0", (tid,))
        self.db.execute("UPDATE thread_flags SET marked_unread=0 WHERE thread=?", (tid,))
        self.db.execute("DELETE FROM thread_flags WHERE pinned=0 AND marked_unread=0")
        self.commit()

    def needing_body(self, limit=40, include_unread=False):
        """Messages whose full text is not cached: by default only those already read
        on the iPhone (or sent), since downloading may mark a message read."""
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM messages WHERE source='map' AND complete=0 AND handle IS NOT NULL "
            "AND (phone_read=1 OR outgoing=1 OR ?) ORDER BY time DESC LIMIT ?",
            (int(include_unread), limit))]

    def counts(self):
        messages = self.db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        threads = self.db.execute("SELECT COUNT(DISTINCT thread) FROM messages").fetchone()[0]
        return messages, threads

    def commit(self):
        self.db.commit()
