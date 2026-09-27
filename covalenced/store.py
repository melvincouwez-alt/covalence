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
import shutil
import sqlite3
import time

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
"""


CONTACTS_SCHEMA = "2"  # 2: with photos


def _words(text):
    return " ".join((text or "").split())


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
        rows = self.db.execute("""
            SELECT t.*, m.body AS body, m.time AS time, m.outgoing AS outgoing,
                   (SELECT COUNT(*) FROM messages u WHERE u.thread=t.id AND u.outgoing=0
                    AND u.seen=0) AS unread
            FROM threads t JOIN messages m ON m.key = (
                SELECT key FROM messages WHERE thread=t.id AND COALESCE(kind, '')<>'reaction'
                ORDER BY time DESC LIMIT 1)
            ORDER BY m.time DESC""").fetchall()
        result = []
        for row in rows:
            thread = {"id": row["id"], "participants": json.loads(row["participants"]),
                      "title": row["title"] or "", "is_group": bool(row["is_group"])}
            thread.update(name=self.thread_title(thread), snippet=row["body"] or "",
                          time=row["time"], unread=row["unread"],
                          last_outgoing=bool(row["outgoing"]))
            result.append(thread)
        return result

    # --- messages ----------------------------------------------------------------------------

    def message(self, key):
        row = self.db.execute("SELECT * FROM messages WHERE key=?", (key,)).fetchone()
        return dict(row) if row else None

    def has_handle(self, handle):
        return self.db.execute("SELECT 1 FROM messages WHERE handle=?", (handle,)).fetchone() \
            is not None

    def upsert(self, key, thread, outgoing, sender, sender_name, when, body, complete,
               kind="", phone_read=False, seen=False, source="map", handle=None, status=""):
        """Insert or merge a message; returns True if it is new."""
        if self.is_hidden(key, thread, body, when):
            return False  # deleted in Covalence: the iPhone keeps listing it
        old = self.message(key)
        if old is None:
            self.db.execute(
                "INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (key, handle, thread, int(outgoing), sender, sender_name, int(when), body,
                 int(complete), kind, int(phone_read), int(seen or outgoing), source, status))
            return True
        if old["kind"] in ("reaction", "reaction-note"):
            kind = old["kind"]  # shown as a badge; a new listing must not make it a bubble again
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

    def find_pending_outgoing(self, thread, body, when, window=900):
        """A message sent from Covalence that the phone now lists (subject may be cut at 120)."""
        # iOS flattens line breaks in the listing's subject: compare words only.
        body = _words(body)
        for row in self.db.execute(
                "SELECT key, thread, body FROM messages WHERE outgoing=1 AND source='covalence' "
                "AND ABS(time-?)<? ORDER BY time DESC", (int(when), window)):
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

    def is_hidden(self, key, thread, body, when):
        if int(when) <= int(self.meta("cleared:" + thread, "0") or 0):
            return True
        if self.db.execute("SELECT 1 FROM hidden WHERE key=?", (key,)).fetchone():
            return True
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

    def search(self, query, limit=200):
        """Threads whose messages contain query (case-insensitive), newest first."""
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = self.db.execute(
            "SELECT thread, MAX(time) FROM messages WHERE body LIKE ? ESCAPE '\\' "
            "GROUP BY thread ORDER BY MAX(time) DESC LIMIT ?", (pattern, limit))
        return [r[0] for r in rows]

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
        return self.db.execute(
            "SELECT COUNT(*) FROM messages WHERE outgoing=0 AND seen=0").fetchone()[0]

    def mark_seen(self, tid):
        self.db.execute("UPDATE messages SET seen=1 WHERE thread=? AND seen=0", (tid,))
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
