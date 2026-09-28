# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Offline checks of the protocol parsers (no Bluetooth needed): python3 -m unittest"""

import os
import struct
import unittest

import tempfile

from covalenced import ams, ancs, bmsg, calls, messages, notifications, store
from covalenced.config import Config


class FakeNotifier:
    def __init__(self):
        self.shown = []

    def notify(self, app, icon, summary, body="", actions=(), hints=None, replaces=0,
               timeout=-1, on_action=None, on_closed=None, own=False):
        self.shown.append({"summary": summary, "body": body, "actions": list(actions),
                           "on_action": on_action})
        return len(self.shown)

    def close(self, _id):
        pass


class Hooks:
    def suppress_incoming_call(self, _title):
        return False


class AncsTest(unittest.TestCase):
    def test_back_to_back_responses_are_all_delivered(self):
        # Regression: the parser read one attribute less than requested, the leftover bytes
        # swallowed the next response and one notification in two was lost.
        notifier = FakeNotifier()
        client = ancs.AncsClient(None, {}, "iPhone", notifier, Hooks())
        client.write = lambda *a, **k: None
        client.response_complete = lambda: None
        payload = b""
        for uid, text in ((1, b"Un"), (2, b"Deux"), (3, b"Trois")):
            client.pending[uid] = (0, 0, False)
            attrs = [(0, b"com.example.app"), (1, b"Titre"), (2, b""), (3, text),
                     (5, b"20260928T110936"), (6, b""), (7, b"")]
            payload += struct.pack("<BI", 0, uid) + b"".join(
                struct.pack("<BH", i, len(v)) + v for i, v in attrs)
        client.buffer = payload
        for _ in range(3):
            client._parse_data_source()
        self.assertEqual([n["body"] for n in notifier.shown], ["Un", "Deux", "Trois"])

    def test_split_response_with_actions(self):
        notifier = FakeNotifier()
        client = ancs.AncsClient(None, {}, "iPhone", notifier, Hooks())
        client.write = lambda *a, **k: None
        client.response_complete = lambda: None
        client.pending[7] = (4, ancs.FLAG_POSITIVE_ACTION | ancs.FLAG_NEGATIVE_ACTION, False)
        attrs = [(0, b"com.apple.MobileSMS"), (1, b"Alice"), (2, b""), (3, b"Salut"),
                 (5, b"20260928T110936"), (6, b"Repondre"), (7, b"Effacer")]
        payload = struct.pack("<BI", 0, 7) + b"".join(
            struct.pack("<BH", i, len(v)) + v for i, v in attrs)
        client.buffer = payload[:10]
        client._parse_data_source()
        self.assertEqual(notifier.shown, [])  # incomplete: waits for the rest
        client.buffer += payload[10:]
        client._parse_data_source()
        shown = notifier.shown[0]
        self.assertEqual(shown["body"], "Salut")
        self.assertEqual([k for k, _ in shown["actions"]], ["positive", "negative"])
        sent = []
        client.write = lambda uuid, data, **k: sent.append(data)
        shown["on_action"]("negative")
        self.assertEqual(sent[0], struct.pack("<BIB", 2, 7, 1))


class AmsTest(unittest.TestCase):
    def test_entity_updates(self):
        changes = []
        client = ams.AmsClient(None, {}, changes.append)
        client.chars = {ams.ENTITY_UPDATE: "/eu", ams.REMOTE_COMMAND: "/rc"}
        client.on_value("/eu", bytes([2, 2, 0]) + "Titre".encode())
        client.on_value("/eu", bytes([0, 1, 0]) + b"1,1.0,12.5")
        client.on_value("/rc", bytes([0, 1, 2, 3, 4]))
        self.assertEqual(client.state["title"], "Titre")
        self.assertEqual(client.state["status"], "Playing")
        self.assertGreaterEqual(client.position(), 12.5)
        self.assertIn(ams.CMD_NEXT, client.supported)


    def test_registration_waits_for_subscriptions(self):
        # Writing Entity Update before notifications are on gets ATT 0xA0 from the iPhone.
        client = ams.AmsClient(None, {ams.ENTITY_UPDATE: "/eu", ams.REMOTE_COMMAND: "/rc"},
                               lambda _c: None)
        answers, writes = [], []
        client.subscribe = lambda uuids, then=None: answers.append(then)
        client.write = lambda uuid, data, **k: writes.append(uuid)
        client.start()
        self.assertEqual(writes, [])  # nothing sent before StartNotify answered
        answers[0]()
        self.assertEqual(writes, [ams.ENTITY_UPDATE] * 3)


def _config(tmp):
    from gi.repository import GLib
    config = Config()
    config.dir, config.path = tmp, os.path.join(tmp, "covalenced.conf")
    config.keyfile = GLib.KeyFile()  # never the user's real settings
    return config


class FakeAms:
    def __init__(self, supported=()):
        self.supported = set(supported)
        self.sent = []
        self.state = {"player": "Musique", "status": "Stopped", "rate": 0.0, "elapsed": 0.0,
                      "stamp": 0.0, "wall": 0.0, "volume": 0.5, "title": "", "artist": "",
                      "album": "", "duration": 0.0}

    def command(self, cid):
        if self.supported and cid not in self.supported:
            return False
        self.sent.append(cid)
        return True


class NowPlayingTest(unittest.TestCase):
    def setUp(self):
        from covalenced import nowplaying
        self.np = nowplaying
        self.tmp = tempfile.TemporaryDirectory()
        self.config = _config(self.tmp.name)
        self.player = nowplaying.NowPlaying(None, self.config, None, lambda: None)
        self.player.artwork = nowplaying.Artwork(self.config, os.path.join(self.tmp.name, "art"),
                                                 fetch=lambda url: {"results": []})
        self.player.artwork.enabled = lambda: False  # no lookup unless a test wants one

    def tearDown(self):
        self.tmp.cleanup()

    def link(self, ams_client=None, device="/org/bluez/hci0/dev_X"):
        class Link:
            pass
        link = Link()
        link.ams, link.device = ams_client, device
        self.player.attach(link)
        return link

    def test_position_extrapolation(self):
        self.assertEqual(self.np.extrapolate(10.0, 1.0, False, 100.0, 130.0), 10.0)
        self.assertEqual(self.np.extrapolate(10.0, 1.0, True, 100.0, 130.0), 40.0)
        self.assertEqual(self.np.extrapolate(10.0, 2.0, True, 100.0, 105.0), 20.0)
        self.assertEqual(self.np.extrapolate(10.0, 1.0, True, 100.0, 90.0), 10.0)  # clock skew

    def test_source_choice(self):
        self.assertEqual(self.np.choose_source(True, "/p"), "ams")
        self.assertEqual(self.np.choose_source(False, "/p"), "avrcp")
        self.assertEqual(self.np.choose_source(False, None, "/dev"), "avrcp-control")
        self.assertEqual(self.np.choose_source(False, None), "")

    def test_ams_state_and_play_with_nothing_playing(self):
        client = FakeAms(supported=(ams.CMD_TOGGLE, ams.CMD_NEXT))
        self.link(client)
        state = self.player.state()
        self.assertEqual((state["source"], state["title"], state["status"]), ("ams", "", "stopped"))
        self.assertTrue(state["can_play"])  # the button stays, the iPhone resumes its audio
        self.assertTrue(self.player.command("play"))  # Play refused: TogglePlayPause instead
        self.assertEqual(client.sent, [ams.CMD_TOGGLE])
        client.state.update(title="Chanson", artist="Artiste", status="Playing", elapsed=30.0,
                            wall=1000.0, rate=1.0, duration=200.0)
        state = self.player.state()
        self.assertEqual((state["status"], state["position"], state["position_time"]),
                         ("playing", 30.0, 1000.0))
        self.assertIn("next", state["commands"])
        self.assertNotIn("previous", state["commands"])

    def test_avrcp_state_and_bare_link(self):
        link = self.link()
        dev = link.device
        objects = {dev: {"org.bluez.MediaControl1": {"Connected": True}}}
        self.player.refresh_avrcp(objects)
        state = self.player.state()
        self.assertEqual(state["source"], "avrcp-control")
        self.assertTrue(state["can_play"])
        calls_made = []
        import covalenced.nowplaying as mod
        original = mod.call_async
        mod.call_async = lambda bus, name, path, iface, method, *a, **k: calls_made.append(
            (path, iface, method))
        try:
            self.assertTrue(self.player.command("toggle"))
            objects[dev + "/player0"] = {"org.bluez.MediaPlayer1": {
                "Status": "playing", "Position": 5000,
                "Track": {"Title": "T", "Artist": "A", "Duration": 60000}}}
            self.player.refresh_avrcp(objects)
            state = self.player.state()
            self.assertEqual((state["source"], state["title"], state["duration"], state["position"]),
                             ("avrcp", "T", 60.0, 5.0))
            self.assertTrue(self.player.command("toggle"))
        finally:
            mod.call_async = original
        self.assertEqual(calls_made, [(dev, "org.bluez.MediaControl1", "Play"),
                                      (dev + "/player0", "org.bluez.MediaPlayer1", "Pause")])

    def test_media_module_off_hides_everything(self):
        self.link(FakeAms())
        self.config.set_module_enabled("media", False)
        self.assertEqual(self.player.state()["source"], "")
        self.assertFalse(self.player.command("play"))

    def test_artwork_match(self):
        match = self.np.matches
        result = {"artistName": "Les Voyageurs du Soir", "trackName": "Lumière d'octobre (Remastered)"}
        self.assertTrue(match(result, "Les Voyageurs du Soir", "Lumiere d'Octobre"))
        self.assertTrue(match(result, "Voyageurs du Soir", "Lumière d'octobre"))
        self.assertFalse(match(result, "Autre Artiste", "Lumière d'octobre"))
        self.assertFalse(match(result, "Les Voyageurs du Soir", "Épisode 12 : la mer"))
        self.assertFalse(match({"artistName": "", "trackName": "x"}, "", "x"))

    def test_artwork_lookup_keeps_only_matches(self):
        import time as _t
        from unittest import mock
        seen = []
        art = self.np.Artwork(self.config, os.path.join(self.tmp.name, "cover"),
                              fetch=lambda url: seen.append(url) or {"results": [
                                  {"artistName": "Someone Else", "trackName": "Podcast",
                                   "artworkUrl100": "https://example.invalid/a/100x100bb.jpg"}]})
        self.assertEqual(art.lookup("Radio", "Podcast du matin"), "")  # started in background
        for _ in range(50):
            if not art.busy:
                break
            _t.sleep(0.05)
        self.assertEqual(len(seen), 1)
        self.assertIn("Radio", seen[0])
        self.assertEqual([f for f in os.listdir(art.dir) if f.endswith(".jpg")], [])
        self.assertEqual(art.lookup("Radio", "Podcast du matin"), "")  # remembered as missing
        self.assertEqual(len(seen), 1)
        self.assertEqual(os.stat(art.dir).st_mode & 0o777, 0o700)

        good = self.np.Artwork(self.config, os.path.join(self.tmp.name, "good"),
                               fetch=lambda url: {"results": [
                                   {"artistName": "Artiste", "trackName": "Chanson",
                                    "artworkUrl100": "https://example.invalid/b/100x100bb.jpg"}]})
        reply = mock.MagicMock()
        reply.__enter__.return_value.read.return_value = b"\xff\xd8jpeg"
        with mock.patch("urllib.request.urlopen", return_value=reply) as opened:
            good.lookup("Artiste", "Chanson")
            for _ in range(50):
                if not good.busy:
                    break
                _t.sleep(0.05)
        self.assertEqual(opened.call_args[0][0], "https://example.invalid/b/600x600bb.jpg")
        path = good.lookup("Artiste", "Chanson")
        self.assertTrue(path.endswith(".jpg"))
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.config.keyfile.set_boolean("media", "artwork", False)
        self.assertEqual(self.np.Artwork(self.config, good.dir).lookup("Artiste", "Chanson"), "")


class NotificationsTest(unittest.TestCase):
    def test_list_and_app_choice(self):
        import os
        tmp = tempfile.TemporaryDirectory()
        config = Config()
        config.dir, config.path = tmp.name, os.path.join(tmp.name, "covalenced.conf")
        from gi.repository import GLib
        config.keyfile = GLib.KeyFile()  # not the user's real choices
        changes = []
        n = notifications.Notifications(config, lambda: changes.append(1))
        n.icons.enabled = lambda: False  # no App Store lookup from the tests
        n.icons.dir = tmp.name
        self.assertTrue(n.seen(1, "com.example.app", "Exemple", "Titre", "Texte", 4))
        n.set_app_enabled("com.example.app", False)
        self.assertFalse(n.seen(2, "com.example.app", "Exemple", "Titre 2", "", 4))
        self.assertEqual([i["uid"] for i in n.listing()], [2, 1])  # newest first, still listed
        apps = n.apps()
        self.assertEqual((apps[0]["name"], apps[0]["enabled"], apps[0]["count"]), ("Exemple", False, 2))
        n.removed(1)
        self.assertEqual(len(n.listing()), 1)
        self.assertTrue(os.path.exists(config.path))  # choices persist, not the texts
        with open(config.path, encoding="utf-8") as f:
            self.assertNotIn("Titre", f.read())
        tmp.cleanup()


class CallsTest(unittest.TestCase):
    def test_call_published_under_the_gateway(self):
        from gi.repository import GLib
        notifier = FakeNotifier()
        c = calls.Calls(None, None, notifier, lambda: None)
        started = []
        c.on_started = started.append
        # PipeWire publishes calls as children of /org/pipewire/Telephony/ag1.
        params = GLib.Variant("(oa{sa{sv}})", ("/org/pipewire/Telephony/ag1/call1", {
            calls.CALL: {"State": GLib.Variant("s", "dialing"),
                         "LineIdentification": GLib.Variant("s", "+33600000000")}}))
        c._on_added(None, None, "/org/pipewire/Telephony/ag1", None, None, params)
        self.assertIn("Appel sortant", notifier.shown[-1]["summary"])
        self.assertEqual(started, ["/org/pipewire/Telephony/ag1/call1"])
        # The oFono-style CallAdded for the same call does not duplicate it.
        c._on_call_added(None, None, None, None, None, GLib.Variant("(oa{sv})", (
            "/org/pipewire/Telephony/ag1/call1", {"State": GLib.Variant("s", "alerting")})))
        self.assertEqual(len(c.calls), 1)
        self.assertEqual(len(c.active_calls()), 1)

    def test_simulated_call_touches_nothing_real(self):
        notifier = FakeNotifier()
        c = calls.Calls(None, None, notifier, lambda: None)
        path = c.simulate("outgoing")
        self.assertIn("Appel sortant", notifier.shown[-1]["summary"])
        c._demo_state(path, "active")
        c.set_muted(True)  # no wpctl for a demonstration
        self.assertTrue(c.muted and c.mute_restore is None)
        done = []
        c.set_audio_on_pc(False, done.append)
        self.assertFalse(c.audio_on_pc())
        c.call_action(path, "hangup", done.append)
        self.assertEqual(c.active_calls(), [])
        self.assertFalse(c.muted)

    def test_incoming_call_notification(self):
        notifier = FakeNotifier()
        c = calls.Calls(None, None, notifier, lambda: None)
        c.calls["/call1"] = {"State": "incoming", "LineIdentification": "+33600000000"}
        c.set_caller_hint("Alice")
        shown = notifier.shown[-1]
        self.assertIn("Alice", shown["summary"])
        self.assertEqual([k for k, _ in shown["actions"]], ["answer", "hangup"])


class MessagesHooks:
    device_name = "iPhone"

    def __init__(self):
        self.received = []

    def messages_changed(self, threads=False):
        pass

    def message_received(self, thread, key):
        self.received.append((thread, key))


def listing(handle, **props):
    return (f"/org/bluez/obex/client/session0/message{handle}", props)


class MessagesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hooks = MessagesHooks()
        self.notifier = FakeNotifier()
        self.m = messages.Messages(None, self.notifier, self.hooks)
        self.m.store = store.Store(self.tmp.name)
        self.m.enabled = True

    def tearDown(self):
        self.m.store.close()
        self.tmp.cleanup()

    def test_private_files(self):
        import os
        import stat
        self.assertEqual(stat.S_IMODE(os.stat(self.m.store.dir).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(self.m.store.path).st_mode), 0o600)

    def test_addresses(self):
        self.assertEqual(bmsg.normalize_address("06 12 34 56 78"), "+33612345678")
        self.assertEqual(bmsg.normalize_address("0033 6 12 34 56 78"), "+33612345678")
        self.assertEqual(bmsg.normalize_address("Bob@Example.org"), "bob@example.org")
        self.assertEqual(bmsg.normalize_address("36179"), "36179")
        self.assertEqual(bmsg.parse_timestamp("20260926T120000Z"), 1790424000)
        self.assertEqual(bmsg.parse_timestamp("20260926T140000+0200"), 1790424000)

    def test_bmessage_roundtrip_and_group(self):
        built = bmsg.build_bmessage("+33600000001", "ligne 1\nligne 2", "Alice")
        parsed = bmsg.parse_bmessage(built)
        self.assertEqual(parsed["body"], "ligne 1\nligne 2")
        self.assertEqual(parsed["recipients"][0]["addresses"], ["+33600000001"])
        group = ("BEGIN:BMSG\r\nVERSION:1.0\r\nSTATUS:READ\r\nTYPE:MMS\r\n"
                 "FOLDER:TELECOM/MSG/INBOX\r\n"
                 "BEGIN:VCARD\r\nVERSION:2.1\r\nFN:Bob\r\nTEL:+33600000002\r\nEND:VCARD\r\n"
                 "BEGIN:BENV\r\n"
                 "BEGIN:VCARD\r\nVERSION:2.1\r\nTEL:+33600000009\r\nEND:VCARD\r\n"
                 "BEGIN:VCARD\r\nVERSION:2.1\r\nTEL:+33600000003\r\nEND:VCARD\r\n"
                 "BEGIN:BBODY\r\nCHARSET:UTF-8\r\nLENGTH:24\r\n"
                 "BEGIN:MSG\r\ntest\r\nEND:MSG\r\nEND:BBODY\r\nEND:BENV\r\nEND:BMSG\r\n")
        parsed = bmsg.parse_bmessage(group)
        self.assertEqual(parsed["originator"]["addresses"], ["+33600000002"])
        self.assertEqual(len(parsed["recipients"]), 2)
        self.assertEqual(parsed["body"], "test")

    def test_grouping_and_notifications(self):
        me = "+33600000009"
        first = dict([
            listing("1", SenderAddress="+33600000001", Sender="Alice", RecipientAddress=me,
                    Timestamp="20260926T100000", Subject="un", Size=2, Read=True, Type="sms-gsm"),
            listing("2", SenderAddress="+33600000002", Sender="Bob",
                    RecipientAddress=f"{me};+33600000003", Timestamp="20260926T100100",
                    Subject="deux", Size=4, Read=False, Type="mms"),
        ])
        sent = dict([listing("3", RecipientAddress="+33600000001", Timestamp="20260926T100200",
                             Subject="trois", Size=5, Read=True, Type="sms-gsm")])
        self.m._merge({"inbox": first, "sent": sent}, initial=True)
        threads = {t["name"]: t for t in self.m.threads()}
        self.assertEqual(len(threads), 2)
        alice = threads["Alice"]
        self.assertFalse(alice["group"])
        self.assertEqual(alice["unread"], 0)
        self.assertTrue(alice["outgoing"])
        self.assertEqual(len(self.m.messages(alice["id"])), 2)
        group = [t for t in threads.values() if t["group"]][0]
        self.assertEqual(group["unread"], 1)
        self.assertEqual(self.m.messages(group["id"])[0]["sender"], "Bob")
        self.assertEqual(self.notifier.shown, [])  # first sync: no notification burst
        self.m._merge({"inbox": dict([listing(
            "4", SenderAddress="+33600000001", Sender="Alice", RecipientAddress=me,
            Timestamp="20260926T110000", Subject="quatre", Size=6, Read=False)])}, initial=False)
        self.assertEqual(len(self.hooks.received), 1)
        self.assertEqual(self.notifier.shown[-1]["summary"], "Alice")
        self.assertEqual([k for k, _ in self.notifier.shown[-1]["actions"]], ["default", "reply"])
        self.assertEqual(self.m.threads()[0]["unread"], 1)
        self.m.mark_seen(self.m.threads()[0]["id"])
        self.assertEqual(self.m.threads()[0]["unread"], 0)

    def test_listing_subject_never_overwrites_full_text(self):
        me = "+33600000009"
        entry = dict([listing("5", SenderAddress="+33600000001", RecipientAddress=me,
                              Timestamp="20260926T100000", Subject="début", Size=300,
                              Read=True)])
        self.m._merge({"inbox": entry}, initial=True)
        self.assertEqual([m["handle"] for m in self.m.store.needing_body()], ["5"])
        self.m.listed.add("5")
        self.m._on_bodies({"map:5": {"originator": None, "recipients": [], "body": "début et fin"}},
                          None)
        self.m._merge({"inbox": entry}, initial=False)
        msgs = self.m.messages(self.m.threads()[0]["id"])
        self.assertEqual(msgs[0]["body"], "début et fin")
        self.assertTrue(msgs[0]["complete"])

    def test_ancs_fallback_then_map_dedup(self):
        self.assertTrue(self.m.ancs_message("Alice", "", "coucou toi"))
        self.m._flush_ancs(self.m.ancs_pending[0])
        self.assertEqual(len(self.m.threads()), 1)
        self.assertEqual(self.notifier.shown[-1]["summary"], "Alice")
        import time as _t
        stamp = _t.strftime("%Y%m%dT%H%M%S")
        self.m._merge({"inbox": dict([listing(
            "6", SenderAddress="+33600000001", Sender="Alice", RecipientAddress="+33600000009",
            Timestamp=stamp, Subject="coucou toi", Size=10, Read=False)])}, initial=False)
        bodies = [m["source"] for t in self.m.threads() for m in self.m.messages(t["id"])]
        self.assertEqual(bodies, ["map"])
        self.assertEqual(len(self.notifier.shown), 1)  # not notified a second time

    def test_map_then_ancs_is_not_doubled(self):
        import time as _t
        stamp = _t.strftime("%Y%m%dT%H%M%S")
        self.m._merge({"inbox": dict([listing(
            "7", SenderAddress="+33600000002", Sender="Bob", RecipientAddress="+33600000009",
            Timestamp=stamp, Subject="salut", Size=5, Read=False)])}, initial=False)
        shown = len(self.notifier.shown)
        self.assertTrue(self.m.ancs_message("Bob", "", "salut"))
        self.m._flush_ancs(self.m.ancs_pending[0])
        sources = [m["source"] for t in self.m.threads() for m in self.m.messages(t["id"])]
        self.assertEqual(sources, ["map"])
        self.assertEqual(len(self.notifier.shown), shown)

    def test_deleted_messages_stay_deleted(self):
        import time as _t
        now = int(_t.time())
        stamp = _t.strftime("%Y%m%dT%H%M%S", _t.localtime(now - 60))
        inbox = {"inbox": dict([
            listing("8", SenderAddress="+33600000003", Sender="Carl",
                    RecipientAddress="+33600000009", Timestamp=stamp, Subject="un", Size=2,
                    Read=True),
            listing("9", SenderAddress="+33600000003", Sender="Carl",
                    RecipientAddress="+33600000009", Timestamp=stamp, Subject="deux", Size=4,
                    Read=True)])}
        self.m._merge(inbox, initial=False)
        tid = self.m.threads()[0]["id"]
        first = [m for m in self.m.messages(tid) if m["body"] == "un"][0]
        self.m.delete_message(first["id"])
        self.m._merge(inbox, initial=False)  # the iPhone still lists it
        self.assertEqual([m["body"] for m in self.m.messages(tid)], ["deux"])
        self.m.ancs_message("Carl", "", "un")  # nor through a notification
        self.m._flush_ancs(self.m.ancs_pending[0])
        self.assertEqual([m["body"] for t in self.m.threads() for m in self.m.messages(t["id"])],
                         ["deux"])
        self.m.delete_conversation(tid)
        self.m._merge(inbox, initial=False)
        self.assertEqual(self.m.threads(), [])
        later = _t.strftime("%Y%m%dT%H%M%S", _t.localtime(now + 120))
        self.m._merge({"inbox": dict([listing(
            "10", SenderAddress="+33600000003", Sender="Carl", RecipientAddress="+33600000009",
            Timestamp=later, Subject="trois", Size=5, Read=False)])}, initial=False)
        self.assertEqual([m["body"] for m in self.m.messages(tid)], ["trois"])

    def test_contact_photos_are_private(self):
        import os
        import stat
        self.m.store.replace_contacts([{"name": "Alice", "addresses": ["+33600000001"],
                                        "photo": b"\xff\xd8img"}])
        tid = self.m.store.ensure_thread(["+33600000001"])
        self.m.store.upsert("map:9", tid, False, "+33600000001", "", 1, "x", True)
        thread = self.m.threads()[0]
        self.assertEqual(thread["name"], "Alice")
        self.assertTrue(thread["avatar"])
        self.assertEqual(stat.S_IMODE(os.stat(thread["avatar"]).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.m.store.photos).st_mode), 0o700)

    def test_contacts_and_new_conversation(self):
        self.m.store.replace_contacts([
            {"name": "bob", "addresses": ["+33600000002", "bob@example.org"], "photo": None},
            {"name": "Alice", "addresses": ["+33600000001"], "photo": None}])
        cards = self.m.contacts()
        self.assertEqual([c["name"] for c in cards], ["Alice", "bob"])
        self.assertEqual(sorted(cards[1]["addresses"]), ["+33600000002", "bob@example.org"])
        thread = self.m.open_conversation("06 00 00 00 01")
        self.assertEqual(thread["name"], "Alice")
        self.assertTrue(thread["can_send"])
        self.assertFalse(self.m.open_conversation("bob@example.org")["can_send"])
        self.assertIsNone(self.m.open_conversation("  "))

    def test_failed_send_is_kept_and_retryable(self):
        self.hooks.send_progress = lambda *a: None
        tid = self.m.open_conversation("0600000001")["id"]
        errors = []
        self.m.send(tid, "bonjour", errors.append)  # no MAP session: kept as failed
        self.assertTrue(errors[0])
        msgs = self.m.messages(tid)
        self.assertEqual([(m["status"], m["body"]) for m in msgs], [("failed", "bonjour")])
        self.m.retry_message(msgs[0]["id"], errors.append)
        self.assertEqual(len(self.m.messages(tid)), 1)  # same message, not a copy
        self.m.store.set_meta("can_send", "no")
        self.assertTrue(self.m.can_send(self.m.store.thread(tid)))  # never a hard block
        self.m.discard_message(msgs[0]["id"])
        self.assertEqual(self.m.messages(tid), [])

    def test_sent_message_with_line_break_is_not_doubled(self):
        st = self.m.store
        tid = self.m.open_conversation("0600000002")["id"]
        text = "Salut\nligne deux " + "x" * 200
        st.upsert("covalence:1", tid, True, "", "", 1000, text, True,
                  kind="sms", source="covalence", status="sent")
        subject = " ".join(text.split())[:120]  # iOS listing: flattened and cut
        self.assertEqual(st.find_pending_outgoing(tid, subject, 1003), "covalence:1")
        self.assertEqual(st.find_pending_outgoing(tid, text, 1003), "covalence:1")
        self.assertIsNone(st.find_pending_outgoing(tid, "autre chose " * 5, 1003))

    def test_drafts_search_and_viewing(self):
        tid = self.m.open_conversation("0600000001")["id"]
        self.m.store.upsert("map:1", tid, False, "+33600000001", "Alice", 1, "Rendez-vous au parc", True)
        self.m.store.commit()
        self.m.set_draft(tid, "à tout")
        self.assertEqual(self.m.threads()[0]["draft"], "à tout")
        self.assertEqual(self.m.search("PARC"), [tid])
        self.assertEqual(self.m.search("100%"), [])
        self.assertEqual(self.m.unread_total(), 1)
        self.m.set_viewing(tid)
        self.m._notify(tid, "map:1")
        self.assertEqual(self.notifier.shown, [])  # on screen: no banner
        self.m.set_viewing("")
        self.m._notify(tid, "map:1")
        self.assertEqual(len(self.notifier.shown), 1)

    def test_call_history(self):
        text = ("BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Alice\r\nTEL;TYPE=CELL:06 00 00 00 01\r\n"
                "X-IRMC-CALL-DATETIME;MISSED:20260926T101010\r\nEND:VCARD\r\n"
                "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:\r\nN:\r\nTEL:\r\n"
                "X-IRMC-CALL-DATETIME;TYPE=DIALED:20260925T090000\r\nEND:VCARD\r\n")
        calls = bmsg.parse_call_history(text)
        self.assertEqual([(c["kind"], c["address"], c["name"]) for c in calls],
                         [("missed", "+33600000001", "Alice"), ("dialed", "", "")])
        self.m.store.replace_calls(calls)
        history = self.m.call_history()
        self.assertEqual(history[0]["name"], "Alice")
        self.assertEqual(history[1]["name"], "Numéro masqué")

    def test_send_refused_for_groups(self):
        errors = []
        tid = self.m.store.ensure_thread(["+33600000001", "+33600000002"])
        self.m.send(tid, "x", errors.append)
        self.assertTrue(errors and errors[0])


class HeadphonesTest(unittest.TestCase):
    """AAP packets, examples from LibrePods' docs/AAP Definitions.md."""

    class Owner:
        auto_pause = False

        def __init__(self):
            self.changes = 0
            self.ears = []

        def cycle(self, _address):
            return 0

        def changed(self):
            self.changes += 1

        def linked(self, _pods):
            pass

        def ear_changed(self, pods, before):
            self.ears.append((before, list(pods.ear)))

    def pods(self):
        from covalenced import headphones
        return headphones.Pods(self.Owner(), "/dev", {"Address": "AA:BB:CC:DD:EE:FF",
                                                      "Alias": "AirPods", "Connected": False})

    def test_battery(self):
        from covalenced import headphones as h
        p = self.pods()
        p._parse(bytes.fromhex("040004000400030201640201040163010108011102 01".replace(" ", "")))
        self.assertEqual(p.battery, {h.LEFT: 99, h.RIGHT: 100, h.CASE: 17})
        self.assertTrue(p.charging[h.LEFT])
        self.assertFalse(p.charging[h.RIGHT])
        self.assertEqual(p.order, [h.RIGHT, h.LEFT])
        self.assertTrue(p.linked)

    def test_ear_and_modes(self):
        from covalenced import headphones as h
        p = self.pods()
        p._parse(bytes.fromhex("040004000400030201640201040163010108011102 01".replace(" ", "")))
        p._parse(bytes.fromhex("0400040006000001"))
        self.assertEqual((p.ear_of(h.RIGHT), p.ear_of(h.LEFT)), ("in", "out"))
        p._parse(bytes.fromhex("0400040009000d03000000"))
        p._parse(bytes.fromhex("04000400090028010000 00".replace(" ", "")))
        self.assertEqual((p.mode, p.conversation), (3, 1))
        self.assertEqual(h.control(h.CMD_ADAPTIVE, 50), bytes.fromhex("0400040009002e32000000"))
        self.assertEqual(h.rename_packet("AB"), bytes.fromhex("040004001a0001020041 42".replace(" ", "")))

    def test_metadata(self):
        p = self.pods()
        p._parse(bytes.fromhex(
            "040004001d0002d5000400416972506f64732050726f004133303438004170706c6520496e632e00"
            "51584e524848595850360036312e313836383034303030323030303030302e32373133003631"))
        self.assertEqual(p.model, "AirPods Pro 2 (USB-C)")


class ComponentsTest(unittest.TestCase):
    def test_old_pipewire_is_not_installable(self):
        from unittest import mock
        from covalenced import components
        with mock.patch.object(components, "_pipewire_version", return_value=(1, 0, 5)):
            found = {package: installable for package, _label, installable in components.missing()}
        self.assertIs(found.get("pipewire"), False)

    def test_everything_missing_maps_to_packages(self):
        from unittest import mock
        from covalenced import components
        with mock.patch.object(components, "_any", return_value=False), \
                mock.patch.object(components.shutil, "which", return_value=None), \
                mock.patch.object(components, "PRIVATE_OBEXD", "/nonexistent"), \
                mock.patch.object(components, "_pipewire_version", return_value=None):
            packages = [package for package, _label, _installable in components.missing()]
        for package in ("bluez", "bluez-obexd", "libsecret-tools", "evolution-data-server", "fuse3",
                        "pipewire", "libspa-0.2-bluetooth", "wireplumber"):
            self.assertIn(package, packages)

    def test_rclone_missing_is_downloadable(self):
        from unittest import mock
        from covalenced import components
        with mock.patch.object(components, "rclone_ok", return_value=False):
            found = {package: installable for package, _label, installable in components.missing()}
        self.assertEqual(found.get("rclone"), components.DOWNLOADABLE)

    def test_calls_unsupported_on_old_pipewire(self):
        from unittest import mock
        from covalenced import components
        with mock.patch.object(components, "_pipewire_version", return_value=(1, 0, 5)):
            c = calls.Calls(None, None, FakeNotifier(), lambda: None)
        self.assertFalse(c.supported)
        with mock.patch.object(components, "_pipewire_version", return_value=(1, 6, 2)):
            c = calls.Calls(None, None, FakeNotifier(), lambda: None)
        self.assertTrue(c.supported)


class RcloneFetchTest(unittest.TestCase):
    """Download of the official rclone build, with a fake network."""

    def setUp(self):
        import hashlib
        import io
        import zipfile
        from covalenced import rclone_fetch
        self.fetch = rclone_fetch
        self.name = f"rclone-v1.71.0-linux-{rclone_fetch.arch()}"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            bundle.writestr(f"{self.name}/rclone", b"#!/bin/sh\necho rclone v1.71.0\n")
        self.archive = buffer.getvalue()
        self.sums = ("-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\n"
                     f"{hashlib.sha256(self.archive).hexdigest()}  {self.name}.zip\n"
                     f"{'0' * 64}  rclone-v1.71.0-windows-amd64.zip\n"
                     "-----BEGIN PGP SIGNATURE-----\nxx\n-----END PGP SIGNATURE-----\n")
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = os.path.join(self.tmp.name, "libexec", "rclone")

    def tearDown(self):
        self.tmp.cleanup()

    def opener(self, archive=None):
        import io

        class Response(io.BytesIO):
            def __init__(self, data):
                super().__init__(data)
                self.headers = {"Content-Length": str(len(data))}

        pages = {"https://downloads.rclone.org/version.txt": b"rclone v1.71.0\n",
                 "https://downloads.rclone.org/v1.71.0/SHA256SUMS": self.sums.encode(),
                 f"https://downloads.rclone.org/v1.71.0/{self.name}.zip": archive or self.archive}
        return lambda url, timeout=0: Response(pages[url])

    def test_download_verified_and_installed(self):
        steps = []
        self.assertEqual(self.fetch.fetch(self.dest, steps.append, self.opener(),
                                          verify=lambda sums: None), "v1.71.0")
        self.assertTrue(os.access(self.dest, os.X_OK))
        self.assertEqual(os.stat(self.dest).st_mode & 0o777, 0o700)
        self.assertEqual(steps[-1], 100)
        self.assertEqual(os.listdir(os.path.dirname(self.dest)), ["rclone"])  # no leftovers

    def test_tampered_archive_is_refused(self):
        with self.assertRaises(self.fetch.FetchError):
            self.fetch.fetch(self.dest, lambda p: None, self.opener(self.archive + b"x"),
                             verify=lambda sums: None)
        self.assertFalse(os.path.exists(self.dest))

    def test_bad_signature_is_refused(self):
        with self.assertRaises(self.fetch.FetchError):
            self.fetch.fetch(self.dest, lambda p: None, self.opener(), verify=lambda sums: False)
        self.assertFalse(os.path.exists(self.dest))

    def test_real_release_signature(self):
        import shutil
        if not shutil.which("gpg"):
            self.skipTest("GnuPG absent")
        path = os.path.join(os.path.dirname(__file__), "data", "rclone-v1.75.1-SHA256SUMS")
        with open(path, encoding="utf-8") as f:
            sums = f.read()
        self.assertTrue(self.fetch.verify_signature(sums))
        self.assertFalse(self.fetch.verify_signature(sums.replace("linux-amd64.zip", "linux-amd64.zi_")))
        self.assertFalse(self.fetch.verify_signature(self.sums))  # "xx" is no signature
        self.assertIsNone(self.fetch.verify_signature(sums, gpg=""))

    def test_only_https(self):
        with self.assertRaises(self.fetch.FetchError):
            self.fetch._get("http://downloads.rclone.org/version.txt", lambda *a, **k: None)


class MigrationTest(unittest.TestCase):
    """Tandem (the former name) to Covalence, on a throwaway home folder."""

    def test_cache_from_tandem(self):
        import os
        d = tempfile.mkdtemp()
        st = store.Store(d)
        st.db.execute("INSERT INTO messages(key, thread, outgoing, time, source, status) "
                      "VALUES('tandem:ab', 't', 1, 1, 'tandem', 'sent')")
        st.db.execute("INSERT INTO hidden VALUES('tandem:cd', 't', 'x', 1)")
        os.makedirs(os.path.join(d, "photos"))
        open(os.path.join(d, "photos", "p1"), "w").close()
        st.db.execute("INSERT INTO contacts VALUES('+33600000001', 'A', '/gone/tandem/photos/p1')")
        st.db.commit()
        st.close()
        st = store.Store(d)
        row = st.message("covalence:ab")
        self.assertEqual(row["source"], "covalence")
        self.assertTrue(st.db.execute("SELECT 1 FROM hidden WHERE key='covalence:cd'").fetchone())
        photo = st.db.execute("SELECT photo FROM contacts").fetchone()[0]
        self.assertEqual(photo, os.path.join(d, "photos", "p1"))

    def test_move_from_tandem(self):
        import os
        import subprocess
        from covalenced.migrate import Migration

        home = tempfile.mkdtemp()
        j = os.path.join

        def write(path, text="x", mode=0o644):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(text)
            os.chmod(path, mode)

        conf, share, local = j(home, ".config"), j(home, ".local", "share"), j(home, ".local")
        write(j(conf, "tandem", "tandemd.conf"), "[device]\naddress=AA\n")
        write(j(conf, "tandem", "apps.conf"),
              "[launchers]\nTANDEM_MODE_MESSAGES=false\n[default-apps]\n"
              "contacts=io.github.melvincouwez.Tandem.Contacts\n")
        write(j(conf, "tandem", "drive.env"), '# Written by Tandem (iCloud Drive options).\n'
              'TANDEM_DRIVE_DIR="/x/iCloud Drive"\nRCLONE_READ_ONLY=false\n', 0o600)
        write(j(share, "tandem", "messages", "messages.db"), "db", 0o600)
        write(j(share, "tandem", "tandemd", "__init__.py"))
        write(j(share, "tandem", "docs", "guide.html"))
        write(j(local, "libexec", "tandem", "obexd"))
        write(j(share, "systemd", "user", "tandemd.service"))
        write(j(share, "systemd", "user", "tandem-icloud-drive.service"))
        write(j(local, "bin", "tandemd"))
        write(j(share, "applications", "io.github.melvincouwez.Tandem.Messages.desktop"))
        write(j(share, "applications", "other.desktop"))
        write(j(conf, "gtk-3.0", "bookmarks"), "file:///x/iCloud%20Drive iCloud Drive\n")

        keyring, calls = {"io.github.melvincouwez.Tandem": "secret\n"}, []

        def run(args, stdin=None):
            calls.append(args)
            out, code = "", 0
            if args[:2] == ["secret-tool", "lookup"]:
                out = keyring.get(args[3], "")
                code = 0 if out else 1
            elif args[:2] == ["secret-tool", "store"]:
                keyring[args[args.index("application") + 1]] = stdin
            elif args[:2] == ["secret-tool", "clear"]:
                keyring.pop(args[3], None)
            elif args[-2:] == ["is-enabled", "tandem-icloud-drive.service"] or \
                    args[-2:] == ["is-enabled", "tandemd.service"]:
                out = "enabled\n"
            elif args[-2:] == ["is-active", "tandem-icloud-drive.service"]:
                out = "active\n"
            return subprocess.CompletedProcess(args, code, out, "")

        done = Migration(home=home, run=run, log=lambda m: None).run_all()
        self.assertTrue(done)
        self.assertFalse(os.path.exists(j(conf, "tandem")))
        with open(j(conf, "covalence", "covalenced.conf")) as f:
            self.assertIn("address=AA", f.read())
        with open(j(conf, "covalence", "apps.conf")) as f:
            apps = f.read()
        self.assertIn("COVALENCE_MODE_MESSAGES=false", apps)
        self.assertIn("io.github.melvincouwez.Covalence.Contacts", apps)
        with open(j(conf, "covalence", "drive.env")) as f:
            self.assertIn('COVALENCE_DRIVE_DIR="/x/iCloud Drive"', f.read())
        self.assertEqual(os.stat(j(conf, "covalence", "drive.env")).st_mode & 0o777, 0o600)
        self.assertTrue(os.path.exists(j(share, "covalence", "messages", "messages.db")))
        self.assertFalse(os.path.exists(j(share, "tandem")))
        self.assertTrue(os.path.exists(j(local, "libexec", "covalence", "obexd")))
        self.assertEqual(keyring, {"io.github.melvincouwez.Covalence": "secret\n"})
        self.assertFalse(os.path.exists(j(share, "systemd", "user", "tandemd.service")))
        self.assertIn(["systemctl", "--user", "disable", "--now", "tandem-icloud-drive.service"], calls)
        self.assertIn(["systemctl", "--user", "enable", "covalence-icloud-drive.service"], calls)
        self.assertIn(["systemctl", "--user", "start", "covalence-icloud-drive.service"], calls)
        self.assertIn(["systemctl", "--user", "enable", "covalenced.service"], calls)
        self.assertNotIn(["systemctl", "--user", "start", "covalenced.service"], calls)
        self.assertFalse(os.path.exists(j(local, "bin", "tandemd")))
        self.assertFalse(os.path.exists(
            j(share, "applications", "io.github.melvincouwez.Tandem.Messages.desktop")))
        self.assertTrue(os.path.exists(j(share, "applications", "other.desktop")))
        # Second start: nothing left to do.
        calls.clear()
        self.assertEqual(Migration(home=home, run=run, log=lambda m: None).run_all(), [])


if __name__ == "__main__":
    unittest.main()
