# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Reactions sent as SMS text: parsing, badges, removal, sending (offline)."""

import tempfile
import unittest

from covalenced import messages, reactions, store
from tests.test_offline import FakeNotifier, MessagesHooks, listing

ME = "+33600000009"
ALICE = "+33600000004"


class ParseTest(unittest.TestCase):
    def check(self, text, emoji, quote, removed=False):
        found = reactions.parse(text)
        self.assertIsNotNone(found, text)
        self.assertEqual((found["emoji"], found["quote"], found["removed"]),
                         (emoji, quote, removed), text)

    def test_french(self):
        self.check("A adoré « à demain »", "❤️", "à demain")
        self.check("A aimé « à demain »", "👍", "à demain")
        self.check("N’a pas aimé « bof »", "👎", "bof")
        self.check("A ri de « trop drôle… »", "😂", "trop drôle…")
        self.check("A mis en évidence « RDV 18h »", "‼️", "RDV 18h")
        self.check("A souligné « RDV 18h »", "‼️", "RDV 18h")
        self.check("A posé une question sur « tu viens ? »", "❓", "tu viens ?")
        self.check("S'est interrogé(e) sur « ok »", "❓", "ok")
        self.check("A réagi avec 😂 à « lol »", "😂", "lol")
        self.check("A réagi avec 🔥", "🔥", None)
        self.check("a ajouté un « J'aime » à « Message »", "👍", "Message")
        self.check("A aimé « à demain »", "👍", "à demain")

    def test_english(self):
        self.check("Loved “see you”", "❤️", "see you")
        self.check("Liked 'I'm fine'", "👍", "I'm fine")
        self.check("Disliked “meh”", "👎", "meh")
        self.check('Laughed at "haha"', "😂", "haha")
        self.check("Emphasized “x”", "‼️", "x")
        self.check("Questioned “y?”", "❓", "y?")
        self.check("Reacted 😂 to “lol”", "😂", "lol")
        self.check("😍 to “great”", "😍", "great")
        self.check("Reacted ❤ to “z”", "❤️", "z")

    def test_removals(self):
        self.check("A retiré un J’aime de « à demain »", "👍", "à demain", True)
        self.check("A retiré 😂 de « lol »", "😂", "lol", True)
        self.check("Removed a heart from “see you”", "❤️", "see you", True)
        self.check("Removed a like from “x”", "👍", "x", True)
        self.check("Removed a dislike from “x”", "👎", "x", True)

    def test_not_reactions(self):
        for text in ("Bonjour « toi »", "Liked it a lot", "A aimé ça", "", "😂", "lol 😂",
                     "J'ai adoré « le film »"):
            self.assertIsNone(reactions.parse(text), text)

    def test_matching_and_building(self):
        self.assertTrue(reactions.matches("trop drôle…", "Trop drôle, vraiment"))
        self.assertTrue(reactions.matches("rdv 18h", "RDV  18h"))
        self.assertFalse(reactions.matches("à demain", "à plus"))
        self.assertEqual(reactions.build("❤️", "à demain", "fr"), "A adoré « à demain »")
        self.assertEqual(reactions.build("👍", "see you", "en"), "Liked “see you”")
        self.assertEqual(reactions.build("🔥", "x", "fr"), "A réagi avec 🔥 à « x »")
        long = reactions.build("😂", "a" * 60, "en")
        self.assertTrue(long.endswith("…”") and len(long) < 70)
        for emoji in ("❤️", "👍", "👎", "😂", "‼️", "❓", "🔥"):
            for lang in ("fr", "en"):
                found = reactions.parse(reactions.build(emoji, "à demain", lang))
                self.assertEqual((found["emoji"], found["quote"]), (emoji, "à demain"))


class BadgesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.notifier = FakeNotifier()
        self.m = messages.Messages(None, self.notifier, MessagesHooks())
        self.m.store = store.Store(self.tmp.name)
        self.m.enabled = True
        self.m._merge({"inbox": dict([
            listing("1", SenderAddress=ALICE, Sender="Alice", RecipientAddress=ME,
                    Timestamp="20260927T100000", Subject="On se voit à demain ?", Size=21,
                    Read=True),
        ]), "sent": dict([
            listing("2", SenderAddress=ME, RecipientAddress=ALICE,
                    Timestamp="20260927T100100", Subject="Oui, à demain !", Size=15, Read=True),
        ])}, initial=True)
        self.tid = self.m.threads()[0]["id"]

    def tearDown(self):
        self.m.store.close()
        self.tmp.cleanup()

    def receive(self, handle, text, stamp):
        self.m._merge({"inbox": dict([listing(
            handle, SenderAddress=ALICE, Sender="Alice", RecipientAddress=ME,
            Timestamp=stamp, Subject=text, Size=len(text.encode()), Read=False)])},
            initial=False)

    def bubbles(self):
        return self.m.messages(self.tid)

    def test_reaction_becomes_badge_and_notifies(self):
        self.receive("3", "A adoré « Oui, à demain ! »", "20260927T100200")
        msgs = self.bubbles()
        self.assertEqual([m["body"] for m in msgs], ["On se voit à demain ?", "Oui, à demain !"])
        self.assertEqual(msgs[1]["reactions"], [("❤️", "Alice", False, False)])
        self.assertEqual(msgs[0]["reactions"], [])
        body = self.notifier.shown[-1]["body"]
        self.assertIn("❤️", body)
        self.assertIn("Oui, à demain !", body)
        self.assertEqual(self.m.threads()[0]["snippet"], "Oui, à demain !")
        self.assertEqual(self.m.threads()[0]["unread"], 0)

    def test_truncated_quote_and_english(self):
        self.receive("3", "Laughed at “On se voit…”", "20260927T100200")
        self.assertEqual(self.bubbles()[0]["reactions"], [("😂", "Alice", False, False)])

    def test_new_reaction_replaces_and_removal_cancels(self):
        self.receive("3", "A aimé « Oui, à demain ! »", "20260927T100200")
        self.receive("4", "A adoré « Oui, à demain ! »", "20260927T100300")
        self.assertEqual(self.bubbles()[1]["reactions"], [("❤️", "Alice", False, False)])
        self.receive("5", "A retiré un cœur de « Oui, à demain ! »", "20260927T100400")
        self.assertEqual(self.bubbles()[1]["reactions"], [])
        self.assertEqual(len(self.bubbles()), 2)  # no bubble for any of the three

    def test_no_match_stays_a_bubble(self):
        self.receive("3", "A aimé « quelque chose d'autre »", "20260927T100200")
        self.assertEqual(self.bubbles()[-1]["body"], "A aimé « quelque chose d'autre »")

    def test_group_thread(self):
        self.m._merge({"inbox": dict([
            listing("10", SenderAddress=ALICE, Sender="Alice",
                    RecipientAddress=f"{ME};+33600000005", Timestamp="20260927T110000",
                    Subject="Pizza ce soir ?", Size=15, Read=True),
            listing("11", SenderAddress="+33600000005", Sender="Alice",
                    RecipientAddress=f"{ME};{ALICE}", Timestamp="20260927T110100",
                    Subject="Loved “Pizza ce soir ?”", Size=24, Read=False),
        ])}, initial=False)
        group = [t for t in self.m.threads() if t["group"]][0]
        msgs = self.m.messages(group["id"])
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["reactions"], [("❤️", "Alice", False, False)])

    def test_sent_reaction_is_pending_then_a_bubble_if_it_fails(self):
        errors = []
        self.m.send_reaction("map:1", "👍", errors.append)  # no MAP session: fails
        self.assertTrue(errors[0])
        msgs = self.bubbles()
        self.assertEqual(msgs[-1]["status"], "failed")  # retry or delete, like any send
        self.assertEqual(msgs[0]["reactions"], [])
        # while sending, the reaction shows as a pending badge
        key = "covalence:test"
        self.m.store.upsert(key, self.tid, True, "", "", 2000000000,
                            reactions.build("👍", "On se voit à demain ?", "fr"), True,
                            kind="sms", source="covalence", status="sending")
        self.m._classify(key)
        self.assertIn(("👍", self.m._author_name(""), True, True), self.bubbles()[0]["reactions"])

    def test_turned_off(self):
        class Off:
            def boolean(self, *_a):
                return False
        self.m.hooks.config = Off()
        errors = []
        self.m.send_reaction("map:1", "👍", errors.append)
        self.assertEqual(errors, ["reactions are turned off"])


if __name__ == "__main__":
    unittest.main()
