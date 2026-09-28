# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Messages received by notification (ANCS): replays after a reconnection, reply titles,
conversations known by name only (offline)."""

import tempfile
import time
import unittest

from covalenced import ancs, messages, store
from tests.test_offline import FakeNotifier, MessagesHooks

AMIE = "+33600000001"


class HelpersTest(unittest.TestCase):
    def test_date(self):
        when = ancs.parse_date("20260928T110936")
        self.assertEqual(time.strftime("%Y%m%d%H%M%S", time.localtime(when)), "20260928110936")
        self.assertIsNone(ancs.parse_date(""))
        self.assertIsNone(ancs.parse_date("demain"))

    def test_reply_title(self):
        self.assertEqual(store.sender_from_title("Camille Martin\xa0vous a répondu"), "Camille Martin")
        self.assertEqual(store.sender_from_title("Camille replied to you"), "Camille")
        self.assertEqual(store.sender_from_title("Camille"), "Camille")


class ReplayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.notifier = FakeNotifier()
        self.m = messages.Messages(None, self.notifier, MessagesHooks())
        self.m.store = store.Store(self.tmp.name)
        self.m.enabled = True

    def tearDown(self):
        self.m.store.close()
        self.tmp.cleanup()

    def notify(self, title, text, date, replay=False):
        self.m.ancs_message(title, "", text, date, replay)
        self.m._flush_ancs(self.m.ancs_pending[-1])

    def rows(self):
        return self.m.store.db.execute("SELECT thread, time, body FROM messages").fetchall()

    def test_replay_is_stored_once_with_its_own_time(self):
        sent = int(time.time()) - 3 * 3600
        self.notify("Camille", "Coucou toi !", sent)
        self.notify("Camille", "Coucou toi !", sent)  # replayed at the next connection
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["time"], sent)

    def test_replayed_notification_is_not_announced(self):
        self.notify("Camille", "Bon courage !", int(time.time()) - 3600, replay=True)
        self.assertEqual(self.notifier.shown, [])
        self.notify("Camille", "Tu es là ?", int(time.time()) - 3600)  # late but live: shown
        self.assertEqual(len(self.notifier.shown), 1)

    def test_same_short_reply_twice_is_kept_when_dated(self):
        now = int(time.time())
        self.notify("Camille", "Ok", now - 3000)
        self.notify("Camille", "Ok", now - 60)
        self.assertEqual(len(self.rows()), 2)

    def test_undated_copy_of_a_known_text_is_skipped(self):
        self.notify("Camille", "Trop cool !", int(time.time()) - 600)
        self.notify("Camille", "Trop cool !", None)
        self.assertEqual(len(self.rows()), 1)

    def test_reply_title_joins_the_same_conversation(self):
        self.notify("Camille", "Premier", int(time.time()) - 60)
        self.notify("Camille\xa0vous a répondu", "Deuxième", int(time.time()) - 30)
        self.assertEqual(len({r["thread"] for r in self.rows()}), 1)

    def test_name_conversation_merged_when_contacts_arrive(self):
        self.notify("Camille", "Avant le carnet", int(time.time()) - 60)
        self.m.store.replace_contacts([{"name": "Camille", "addresses": [AMIE]}])
        self.assertEqual(self.m.store.merge_name_threads(), 1)
        threads = self.m.store.threads()
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]["participants"], [AMIE])


if __name__ == "__main__":
    unittest.main()
