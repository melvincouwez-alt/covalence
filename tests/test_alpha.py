# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Offline checks of the Sync button and the alpha features: python3 -m unittest"""

import os
import tempfile
import unittest

from gi.repository import GLib

from covalenced import messages, notifications, store
from covalenced.config import ALPHA, Config


def private_config(tmp):
    config = Config()
    config.dir, config.path = tmp, os.path.join(tmp, "covalenced.conf")
    config.keyfile = GLib.KeyFile()  # not the user's real choices
    return config


class Hooks:
    device_name = "iPhone"

    def __init__(self, config):
        self.config = config
        self.changed = 0

    def messages_changed(self, threads=False):
        self.changed += 1

    def message_received(self, thread, key):
        pass

    def contacts_changed(self):
        pass


class Notifier:
    def notify(self, *args, **kwargs):
        return 1

    def close(self, _id):
        pass


def path(handle):
    return f"/org/bluez/obex/client/session0/message{handle}"


class ConfigTest(unittest.TestCase):
    def test_alpha_off_by_default_and_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = private_config(tmp)
            self.assertEqual(config.alpha_features(), {name: False for name in ALPHA})
            config.set_alpha("mark_read", True)
            self.assertTrue(config.alpha("mark_read"))
            self.assertFalse(config.alpha("unknown"))
            again = private_config(tmp)
            again.keyfile.load_from_file(again.path, GLib.KeyFileFlags.NONE)
            self.assertTrue(again.alpha("mark_read"))
            self.assertFalse(again.alpha("map_history"))


class HistoryListingTest(unittest.TestCase):
    def test_pages_until_nothing_new(self):
        everything = {path(i): {"n": i} for i in range(1200)}
        base = {k: everything[k] for k in list(everything)[:100]}
        asked = []

        def list_messages(filters):
            asked.append(set(filters))
            if "Offset" in filters:
                start = filters["Offset"].unpack()
                size = filters["MaxCount"].unpack()
                return {k: everything[k] for k in list(everything)[start:start + size]}
            return dict(base)  # period and read filters: nothing more

        extra, counts = messages.history_listing(list_messages, base)
        self.assertEqual(len(extra), 1100)
        self.assertEqual(counts, {"offset": 1100, "period": 0, "read": 0})
        self.assertTrue(all(k not in base for k in extra))

    def test_offset_ignored_and_filters_refused(self):
        base = {path(1): {}, path(2): {}}

        def list_messages(filters):
            if "Offset" in filters:
                return dict(base)  # iOS repeats the first page
            raise GLib.Error("Forbidden")

        extra, counts = messages.history_listing(list_messages, base)
        self.assertEqual(extra, {})
        self.assertEqual(counts, {"offset": 0, "period": -1, "read": -1})


class MessagesAlphaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = private_config(self.tmp.name)
        self.m = messages.Messages(None, Notifier(), Hooks(self.config))
        self.m.store = store.Store(os.path.join(self.tmp.name, "messages"))
        self.m.enabled = True

    def tearDown(self):
        self.m.store.close()
        self.tmp.cleanup()

    def test_sync_without_iphone(self):
        results = []
        self.m.manual_sync(lambda count, error: results.append((count, error)))
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0][0])
        self.assertTrue(results[0][1])

    def test_sync_counts_new_messages(self):
        results = []
        self.m.sync_waiters.append((lambda c, e: results.append((c, e)), 0))
        tid = self.m.store.ensure_thread(["+33600000001"])
        self.m.store.upsert("map:1", tid, False, "+33600000001", "Alice", 100, "salut", True,
                            source="map", handle="1")
        self.m._finish_waiters()
        self.assertEqual(results, [(1, None)])
        self.assertEqual(self.m.sync_waiters, [])

    def test_read_candidates_only_listed_unread_received(self):
        s = self.m.store
        tid = s.ensure_thread(["+33600000001"])
        s.upsert("map:1", tid, False, "+33600000001", "Alice", 100, "un", True,
                 source="map", handle="1")
        s.upsert("map:2", tid, False, "+33600000001", "Alice", 101, "deux", True,
                 phone_read=True, source="map", handle="2")
        s.upsert("map:3", tid, True, "", "", 102, "trois", True, source="map", handle="3")
        s.upsert("map:4", tid, False, "+33600000001", "Alice", 103, "quatre", True,
                 source="map", handle="4")
        self.m.listed = {"1", "2", "3"}  # 4 not listed in this session: no object to set
        self.assertEqual(self.m._read_candidates(tid), [("map:1", "1")])

    def test_favorites_follow_the_switch(self):
        self.m.store.set_meta("pbap_favorites", '["+33600000001"]')
        self.assertEqual(self.m.favorites(), set())
        self.config.set_alpha("pbap_favorites", True)
        self.assertEqual(self.m.favorites(), {"+33600000001"})
        cards = [{"name": "Alice", "addresses": ["+33600000001", "alice@example.org"]},
                 {"name": "Bob", "addresses": []}]
        self.assertEqual(messages.favorite_addresses(cards),
                         {"+33600000001", "alice@example.org"})


class NotificationActionsTest(unittest.TestCase):
    def test_labels_kept_for_the_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            n = notifications.Notifications(private_config(tmp), lambda: None)
            n.icons.enabled = lambda: False
            n.icons.dir = tmp
            n.seen(1, "com.example.mail", "Courrier", "Titre", "Texte", 6,
                   {"positive": "Marquer comme lu", "negative": "Supprimer"})
            n.seen(2, "com.example.app", "Exemple", "Titre", "", 4)
            items = {i["uid"]: i for i in n.listing()}
            self.assertEqual((items[1]["positive"], items[1]["negative"]),
                             ("Marquer comme lu", "Supprimer"))
            self.assertEqual((items[2]["positive"], items[2]["negative"]), ("", ""))


if __name__ == "__main__":
    unittest.main()
