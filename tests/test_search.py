# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Message search (accents and case ignored), pinned threads, local unread mark (offline)."""

import tempfile
import unittest

from covalenced import messages, store
from tests.test_offline import FakeNotifier, MessagesHooks, listing

ME = "+33600000009"
ALICE = "+33600000004"
BRUNO = "+33600000005"


class FoldTest(unittest.TestCase):
    def test_fold(self):
        self.assertEqual(store.fold("Élodie À BIENTÔT"), "elodie a bientot")
        self.assertEqual(store.fold("Œuvre ﬁn"), "œuvre fin")
        self.assertEqual(store.fold(None), "")

    def test_excerpt_keeps_the_original_text(self):
        self.assertEqual(store.excerpt("On se voit à Noël ?", "noel"),
                         ("On se voit à ", "Noël", " ?"))
        self.assertEqual(store.excerpt("CAFÉ", "cafe"), ("", "CAFÉ", ""))
        self.assertIsNone(store.excerpt("Bonjour", "salut"))
        before, match, after = store.excerpt("x " * 60 + "trouvé" + " y" * 80, "trouve")
        self.assertEqual(match, "trouvé")
        self.assertTrue(before.startswith("…") and after.endswith("…"))


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.m = messages.Messages(None, FakeNotifier(), MessagesHooks())
        self.m.store = store.Store(self.tmp.name)
        self.m.enabled = True
        self.m._merge({"inbox": dict([
            listing("1", SenderAddress=ALICE, Sender="Alice Émeraude", RecipientAddress=ME,
                    Timestamp="20260927T100000", Subject="Tu viens au café demain ?", Size=25,
                    Read=True),
            listing("2", SenderAddress=BRUNO, Sender="Bruno Martin", RecipientAddress=ME,
                    Timestamp="20260927T110000", Subject="Le CAFE est fermé", Size=17,
                    Read=False),
            listing("3", SenderAddress=ALICE, Sender="Alice Émeraude", RecipientAddress=ME,
                    Timestamp="20260927T120000", Subject="Finalement, thé !", Size=17, Read=True),
        ])}, initial=True)

    def tearDown(self):
        self.m.store.close()
        self.tmp.cleanup()

    def thread_of(self, address):
        return next(t["id"] for t in self.m.threads() if t["participants"] == [address])

    def test_accents_and_case_ignored(self):
        hits = self.m.search_messages("cafe")
        self.assertEqual([h["match"] for h in hits], ["CAFE", "café"])
        self.assertEqual(hits[0]["thread"], self.thread_of(BRUNO))  # newest hit first
        self.assertEqual(hits[1]["before"], "Tu viens au ")
        self.assertEqual(hits[1]["after"], " demain ?")
        self.assertTrue(all(h["message"] for h in hits))
        self.assertEqual(self.m.search_messages("THÉ")[0]["match"], "thé")
        self.assertEqual(self.m.search_messages("  "), [])
        self.assertEqual(self.m.search_messages("100%"), [])
        self.assertEqual(sorted(self.m.search("CAFÉ")), sorted([self.thread_of(ALICE),
                                                               self.thread_of(BRUNO)]))

    def test_name_match_first_and_grouped(self):
        hits = self.m.search_messages("émer")
        self.assertEqual(hits[0]["message"], "")
        self.assertEqual(hits[0]["match"], "Émer")
        self.assertEqual(hits[0]["thread"], self.thread_of(ALICE))

    def test_hits_grouped_by_conversation(self):
        self.m._merge({"inbox": dict([
            listing("4", SenderAddress=BRUNO, Sender="Bruno Martin", RecipientAddress=ME,
                    Timestamp="20260927T090000", Subject="un café ?", Size=9, Read=True),
        ])}, initial=False)
        threads = [h["thread"] for h in self.m.search_messages("cafe")]
        self.assertEqual(threads, [self.thread_of(BRUNO), self.thread_of(BRUNO),
                                   self.thread_of(ALICE)])

    def test_pinned_first_in_pin_order(self):
        alice, bruno = self.thread_of(ALICE), self.thread_of(BRUNO)
        self.assertEqual([t["id"] for t in self.m.threads()], [alice, bruno])
        self.m.set_pinned(bruno, True)
        self.assertEqual([t["id"] for t in self.m.threads()], [bruno, alice])
        self.m.set_pinned(alice, True)
        self.m.set_pinned(bruno, True)  # already pinned: keeps its place
        self.assertEqual([t["id"] for t in self.m.threads()], [bruno, alice])
        self.assertTrue(all(t["pinned"] for t in self.m.threads()))
        self.m.set_pinned(bruno, False)
        self.assertEqual([t["id"] for t in self.m.threads()], [alice, bruno])
        self.assertFalse(self.m.threads()[1]["pinned"])

    def test_marked_unread_is_local_and_cleared_on_open(self):
        alice = self.thread_of(ALICE)
        before = self.m.unread_total()
        self.m.set_marked_unread(alice, True)
        row = next(t for t in self.m.threads() if t["id"] == alice)
        self.assertEqual((row["unread"], row["marked_unread"]), (1, True))
        self.assertEqual(self.m.unread_total(), before + 1)
        self.m.mark_seen(alice)
        row = next(t for t in self.m.threads() if t["id"] == alice)
        self.assertEqual((row["unread"], row["marked_unread"]), (0, False))
        self.assertEqual(self.m.unread_total(), before)

    def test_marked_on_a_thread_with_real_unread_counts_once(self):
        bruno = self.thread_of(BRUNO)
        self.m.set_marked_unread(bruno, True)
        row = next(t for t in self.m.threads() if t["id"] == bruno)
        self.assertEqual((row["unread"], row["marked_unread"]), (1, False))
        self.assertEqual(self.m.unread_total(), 1)

    def test_deleting_a_conversation_drops_its_flags(self):
        alice = self.thread_of(ALICE)
        self.m.set_pinned(alice, True)
        self.m.delete_conversation(alice)
        self.assertIsNone(self.m.store.db.execute(
            "SELECT 1 FROM thread_flags WHERE thread=?", (alice,)).fetchone())


if __name__ == "__main__":
    unittest.main()
