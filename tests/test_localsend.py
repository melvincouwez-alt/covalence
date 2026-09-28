# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""LocalSend v2: messages and the prepare-upload / upload flow, on localhost only."""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from covalenced import localsend  # noqa: E402

HAVE_OPENSSL = shutil.which("openssl") is not None


def direct(function, *args):
    function(*args)


class MessagesTest(unittest.TestCase):
    def test_device_info(self):
        info = localsend.device_info("Covalence (pc)", "ab" * 32, 53317, announce=True)
        self.assertEqual(info["version"], "2.1")
        self.assertEqual(info["protocol"], "https")
        self.assertTrue(info["announce"])
        self.assertFalse(info["download"])

    def test_peer_from(self):
        peer = localsend.peer_from({"alias": "iPhone de Alice", "fingerprint": "f00",
                                    "deviceModel": "iPhone", "deviceType": "mobile", "port": 53317,
                                    "protocol": "https"}, "192.0.2.4")
        self.assertEqual((peer["id"], peer["address"], peer["port"]), ("f00", "192.0.2.4", 53317))
        self.assertIsNone(localsend.peer_from({"alias": "x"}, "192.0.2.4"))
        self.assertIsNone(localsend.peer_from("junk", "192.0.2.4"))

    def test_safe_name(self):
        self.assertEqual(localsend.safe_name("../../etc/passwd"), "passwd")
        self.assertEqual(localsend.safe_name("dossier\\photo.jpg"), "photo.jpg")
        self.assertEqual(localsend.safe_name(".bashrc"), "_bashrc")
        self.assertEqual(localsend.safe_name(".."), "fichier")
        self.assertEqual(localsend.safe_name("a\x00b\nc.txt"), "abc.txt")

    def test_parse_prepare(self):
        body = json.dumps({"info": {"alias": "A", "fingerprint": "f"},
                           "files": {"1": {"id": "1", "fileName": "a/b.txt", "size": 3,
                                           "fileType": "text/plain"}}})
        info, files = localsend.parse_prepare(body)
        self.assertEqual(files, {"1": {"name": "b.txt", "size": 3, "type": "text/plain"}})
        for bad in ('{"info": {}, "files": {}}', '{"files": {"1": {"size": 1}}}',
                    '{"info": {}, "files": {"1": {"fileName": "a", "size": -1}}}', "not json"):
            with self.assertRaises(ValueError):
                localsend.parse_prepare(bad)

    def test_free_path(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        open(os.path.join(folder, "a.txt"), "w").close()
        self.assertEqual(os.path.basename(localsend.free_path(folder, "a.txt")), "a (2).txt")


@unittest.skipUnless(HAVE_OPENSSL, "openssl needed for the certificate")
class FlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys = tempfile.mkdtemp()
        cls.cert, cls.key, cls.fingerprint = localsend.ensure_certificate(cls.keys)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.keys)

    def setUp(self):
        self.inbox = tempfile.mkdtemp()
        self.outbox = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.inbox)
        self.addCleanup(shutil.rmtree, self.outbox)
        self.accept = True
        self.asked = []
        self.events = []
        identity = {"cert": self.cert, "key": self.key, "fingerprint": self.fingerprint,
                    "alias": "Covalence (test)"}
        self.receiver = localsend.Receiver(identity, self.inbox, self.ask,
                                           lambda kind, data: self.events.append(kind),
                                           direct, host="127.0.0.1", port=0)
        self.receiver.start()
        self.addCleanup(self.receiver.stop)
        self.peer = {"id": self.fingerprint, "alias": "Covalence (test)", "model": "",
                     "type": "desktop", "address": "127.0.0.1", "port": self.receiver.port,
                     "protocol": "https"}
        self.sender_info = localsend.device_info("iPhone de Alice", "0" * 64, 53317)

    def ask(self, session, answer):
        self.asked.append(sorted(f["name"] for f in session.files.values()))
        answer(self.accept)

    def write(self, name, data):
        path = os.path.join(self.outbox, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_accepted_transfer(self):
        paths = [self.write("photo.jpg", os.urandom(200000)), self.write("note.txt", b"bonjour")]
        seen = []
        taken = localsend.send_files(self.sender_info, self.peer, paths,
                                     lambda sent, total: seen.append((sent, total)))
        self.assertEqual(taken, 2)
        self.assertEqual(self.asked, [["note.txt", "photo.jpg"]])
        for path in paths:
            with open(path, "rb") as a, open(os.path.join(self.inbox, os.path.basename(path)), "rb") as b:
                self.assertEqual(a.read(), b.read())
        self.assertEqual(seen[-1][0], seen[-1][1])
        self.assertIn("finished", self.events)
        self.assertFalse([n for n in os.listdir(self.inbox) if n.endswith(".part")])

    def test_refused_transfer(self):
        self.accept = False
        with self.assertRaises(localsend.SendError) as caught:
            localsend.send_files(self.sender_info, self.peer, [self.write("a.txt", b"x")])
        self.assertEqual(str(caught.exception), "refused")
        self.assertEqual(os.listdir(self.inbox), [])

    def test_upload_needs_the_token(self):
        session = localsend.Session({"id": "f", "alias": "A"}, {"1": {"name": "a.txt", "size": 1,
                                                                     "type": ""}})
        session.tokens = {"1": "good"}
        self.receiver.session = session
        status, _ = localsend._request(self.peer, "POST",
                                       f"{localsend.API}/upload?sessionId={session.id}&fileId=1&token=bad",
                                       b"x", headers={"Content-Type": "application/octet-stream"})
        self.assertEqual(status, 403)
        self.assertEqual(os.listdir(self.inbox), [])

    def test_wrong_fingerprint_is_refused(self):
        peer = dict(self.peer, id="1" * 64)
        with self.assertRaises(localsend.SendError) as caught:
            localsend.send_files(self.sender_info, peer, [self.write("a.txt", b"x")])
        self.assertIn(str(caught.exception), ("unreachable", "fingerprint"))
        self.assertEqual(self.asked, [])

    def test_register_and_info(self):
        self.assertTrue(localsend.register(self.sender_info, self.peer))
        self.assertIn("peer", self.events)
        status, body = localsend._request(self.peer, "GET", localsend.API + "/info")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["fingerprint"], self.fingerprint)


if __name__ == "__main__":
    unittest.main()
