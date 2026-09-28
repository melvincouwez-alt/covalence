# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Message cache stability: group threads, own sends, copies from notifications,
one cache per iPhone, reused handles, cleanups (offline)."""

import os
import tempfile
import time
import unittest

from covalenced import messages, store
from tests.test_offline import FakeNotifier, MessagesHooks

ALICE = "+33600000001"
BOB = "+33600000002"
NOW = int(time.time())


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = store.Store(self.tmp.name)

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def put(self, key, tid, body, when, outgoing=False, source="map", sender=ALICE, **kw):
        return self.s.upsert(key, tid, outgoing, "" if outgoing else sender, "", when, body,
                             True, source=source, **kw)

    def test_group_message_stays_in_its_group(self):
        one = self.s.ensure_thread([ALICE])
        group = self.s.ensure_thread([ALICE, BOB], is_group=True)
        self.put("map:1", group, "Salut à tous", NOW)
        self.put("map:1", one, "Salut à tous", NOW)  # next listing: sender only
        self.assertEqual(self.s.message("map:1")["thread"], group)

    def test_old_same_text_does_not_take_a_newer_send(self):
        tid = self.s.ensure_thread([ALICE])
        self.put("covalence:a", tid, "Ok", NOW, outgoing=True, source="covalence")
        self.assertIsNone(self.s.find_pending_outgoing(tid, "Ok", NOW - 300))
        self.assertEqual(self.s.find_pending_outgoing(tid, "Ok", NOW + 5), "covalence:a")

    def test_missing_timestamp_keeps_the_stored_time(self):
        tid = self.s.ensure_thread([ALICE])
        self.put("map:2", tid, "Bonjour", NOW - 3600)
        self.put("map:2", tid, "Bonjour", NOW, time_known=False)
        self.assertEqual(self.s.message("map:2")["time"], NOW - 3600)

    def test_reused_handle_keeps_the_old_message(self):
        tid = self.s.ensure_thread([ALICE])
        self.put("map:3", tid, "Message de l'an dernier", NOW - 300 * 86400)
        self.assertTrue(self.put("map:3", tid, "Tout autre chose", NOW))
        bodies = sorted(r["body"] for r in self.s.db.execute("SELECT body FROM messages"))
        self.assertEqual(bodies, ["Message de l'an dernier", "Tout autre chose"])

    def test_hidden_key_does_not_hide_a_reused_handle(self):
        tid = self.s.ensure_thread([ALICE])
        self.put("map:4", tid, "À supprimer", NOW - 300 * 86400)
        self.s.hide("map:4")
        self.assertFalse(self.put("map:4", tid, "À supprimer", NOW - 300 * 86400))
        self.assertTrue(self.put("map:4", tid, "Nouveau", NOW))

    def test_other_iphone_archives_the_cache(self):
        tid = self.s.ensure_thread([ALICE])
        self.put("map:5", tid, "Ancien téléphone", NOW)
        self.assertIsNone(self.s.claim_device("AA:AA:AA:AA:AA:AA"))  # upgrade: kept
        self.assertIsNone(self.s.claim_device("AA:AA:AA:AA:AA:AA"))
        self.assertEqual(self.s.counts()[0], 1)
        archive = self.s.claim_device("BB:BB:BB:BB:BB:BB")
        self.assertTrue(archive and os.path.exists(archive))
        self.assertEqual(os.stat(archive).st_mode & 0o777, 0o600)
        self.assertEqual(self.s.counts()[0], 0)
        self.assertEqual(self.s.meta("device"), "BB:BB:BB:BB:BB:BB")

    def test_private_address_never_archives(self):
        self.put("map:9", self.s.ensure_thread([ALICE]), "Gardé", NOW)
        self.assertIsNone(self.s.claim_device("B8:01:1F:20:DB:5E"))
        self.assertIsNone(self.s.claim_device("77:3A:10:00:00:01"))  # resolvable private
        self.assertEqual(self.s.counts()[0], 1)
        self.assertEqual(self.s.meta("device"), "B8:01:1F:20:DB:5E")

    def test_merge_respects_deleted_conversation_and_existing_copy(self):
        self.s.replace_contacts([{"name": "Alice", "addresses": [ALICE]}])
        number = self.s.ensure_thread([ALICE])
        self.put("map:6", number, "Déjà là", NOW - 100)
        self.s.hide_thread(number)
        self.put("map:7", number, "Après suppression", NOW + 10)
        named = self.s.ensure_thread(["name:Alice"], is_group=False)
        self.put("ancs:x", named, "Déjà là", NOW - 100, source="ancs", sender="")
        self.put("ancs:y", named, "Après suppression", NOW + 20, source="ancs", sender="")
        self.put("ancs:z", named, "Nouveau", NOW + 30, source="ancs", sender="")
        self.assertEqual(self.s.merge_name_threads(), 1)
        bodies = [m["body"] for m in self.s.messages(number)]
        self.assertEqual(bodies, ["Après suppression", "Nouveau"])

    def test_one_off_cleanup_keeps_the_map_copy(self):
        tid = self.s.ensure_thread([ALICE])
        self.put("map:8", tid, "Coucou toi", NOW)
        self.put("ancs:a", tid, "Coucou toi", NOW + 30, source="ancs")
        self.put("ancs:b", tid, "Rien à voir", NOW + 30, source="ancs")
        self.put("ancs:c", tid, "Deux fois", NOW + 60, source="ancs")
        self.put("ancs:d", tid, "Deux fois", NOW + 120, source="ancs")
        self.assertEqual(self.s.remove_duplicates(), 2)
        keys = sorted(r[0] for r in self.s.db.execute("SELECT key FROM messages"))
        self.assertEqual(keys, ["ancs:b", "ancs:c", "map:8"])


class AncsMapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.notifier = FakeNotifier()
        self.m = messages.Messages(None, self.notifier, MessagesHooks())
        self.m.store = store.Store(self.tmp.name)
        self.m.enabled = True
        self.m.store.replace_contacts([{"name": "Alice", "addresses": [ALICE]},
                                       {"name": "Bob", "addresses": [BOB]}])

    def tearDown(self):
        self.m.store.close()
        self.tmp.cleanup()

    def notify(self, title, text, date=None, uid=None, modified=False):
        self.m.ancs_message(title, "", text, date, False, uid, modified)
        self.m._flush_ancs(self.m.ancs_pending[-1])

    def test_short_texts_match_only_when_equal(self):
        self.assertFalse(self.m._same_text("Oui", "Oui mais non"))
        self.assertTrue(self.m._same_text("Oui", " Oui "))
        long = "Je serai là vers dix-huit heures ce soir"
        self.assertTrue(self.m._same_text(long + " sans faute", long))

    def test_map_copy_only_replaces_the_same_persons_notification(self):
        self.notify("Alice", "Oui", NOW)
        bob = self.m.store.ensure_thread([BOB])
        self.assertIsNone(self.m._drop_ancs_duplicate("Oui", NOW, bob, BOB, "Bob"))
        alice = self.m.store.ensure_thread([ALICE])
        self.assertIsNotNone(self.m._drop_ancs_duplicate("Oui", NOW, alice, ALICE, "Alice"))

    def test_edited_imessage_updates_its_bubble(self):
        self.notify("Alice", "Rendez-vous à 18h", NOW, uid=41)
        self.notify("Alice", "Rendez-vous à 19h", NOW, uid=41, modified=True)
        bodies = [r[0] for r in self.m.store.db.execute("SELECT body FROM messages")]
        self.assertEqual(bodies, ["Rendez-vous à 19h"])

    def test_contacts_pull_is_a_no_op_when_the_module_never_started(self):
        m = messages.Messages(None, FakeNotifier(), MessagesHooks())
        m.address = ALICE
        m._maybe_pull_contacts(calls_only=True)  # no store, no worker: must not raise
        m.refresh_calls()


if __name__ == "__main__":
    unittest.main()
