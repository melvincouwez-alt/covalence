# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""One-time codes in SMS: detection and memory (offline, fictional texts)."""

import json
import os
import tempfile
import time
import unittest

from covalenced import browser_host, messages, otp, store
from tests.test_offline import FakeNotifier, MessagesHooks, listing


class DetectTest(unittest.TestCase):
    def check(self, text, code):
        self.assertEqual(otp.detect(text), code, text)

    def test_french(self):
        self.check("Doctolib : votre code de vérification est 482913. Il expire dans 10 minutes.",
                   "482913")
        self.check("La Poste : votre code de confirmation est le 8412. Valable 15 min.", "8412")
        self.check("Banque Exemple : code de sécurité 3D Secure pour un paiement de 49,90 EUR "
                   "chez BOUTIQUE : 739201", "739201")
        self.check("Paiement de 1250 € chez Exemple. Code : 482913", "482913")
        self.check("Votre code d'identification Apple est : 482913. Ne le communiquez à personne.",
                   "482913")
        self.check("G-482913 est votre code de validation Google.", "482913")
        self.check("Votre code de sécurité : 12345678", "12345678")
        self.check("Code:5521", "5521")
        self.check("Votre code de vérification : 482 913", "482913")
        self.check("Votre mot de passe à usage unique est 70-4412", None)  # not a code shape
        self.check("Votre code à usage unique : 7044-12", None)
        self.check("Mon Espace Santé : 55 12 88 est votre code", None)
        self.check("Votre code d'accès pour le 12/10/2026 à 14:30 est 90817", "90817")

    def test_english(self):
        self.check("Your verification code is 552 118. Don't share it.", "552118")
        self.check("Your Example Bank one-time passcode: 3391", "3391")
        self.check("123456 is your Example login code", "123456")
        self.check("Your Apple Account code is: 482913. Don't share it with anyone.\n\n"
                   "@apple.com #482913 %apple.com", "482913")

    def test_nothing(self):
        self.check("On se voit demain à 18h ?", None)
        self.check("Ton colis 6A12345678901 arrive demain", None)
        self.check("Rappelle-moi au 06 12 34 56 78", None)
        self.check("Rappelle-moi au 0612345678, code postal 75011", None)
        self.check("Votre facture de 1250 € est disponible", None)
        self.check("Votre code promo expire le 12.10.2026", None)
        self.check("Pour ne plus recevoir de codes, STOP au 36111", None)
        self.check("", None)

    def test_amounts_and_times_are_skipped(self):
        self.check("Code de sécurité pour 2500 € : 661204", "661204")
        self.check("Code valable 5 min, commande n° 88213 : 440921", "440921")


class MemoryTest(unittest.TestCase):
    def test_forgotten_after_three_minutes(self):
        now = [100.0]
        codes = otp.OneTimeCodes(clock=lambda: now[0])
        self.assertEqual(codes.latest(), ("", 0, ""))
        codes.remember("482913", "map:1")
        now[0] += 30
        self.assertEqual(codes.latest(), ("482913", 30, "map:1"))
        now[0] += otp.KEEP_SECONDS
        self.assertEqual(codes.latest(), ("", 0, ""))
        self.assertEqual(codes.code, "")


class FakeConfig:
    def __init__(self, mode):
        self.values = {("messages", "one_time_codes"): mode}

    def string(self, group, key, default=""):
        return self.values.get((group, key), default)

    def set_string(self, group, key, value):
        self.values[(group, key)] = value

    def boolean(self, group, key, default=False):
        return default


class FlowTest(unittest.TestCase):
    SMS = "Doctolib : votre code de vérification est 482913. Il expire dans 10 minutes."

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

    def receive_ancs_then_map(self):
        self.assertTrue(self.m.ancs_message("Doctolib", "", self.SMS))
        self.m._flush_ancs(self.m.ancs_pending[0])
        self.m._merge({"inbox": dict([listing(
            "20", SenderAddress="Doctolib", Sender="Doctolib", RecipientAddress="+33600000009",
            Timestamp=time.strftime("%Y%m%dT%H%M%S"), Subject=self.SMS, Size=len(self.SMS),
            Read=False)])}, initial=False)

    def test_one_notification_with_copy(self):
        self.receive_ancs_then_map()
        self.assertEqual(len(self.notifier.shown), 1)  # ANCS and MAP: one notification
        keys = [k for k, _ in self.notifier.shown[0]["actions"]]
        self.assertEqual(keys, ["default", "copy-code", "copy-code-delete"])
        self.assertEqual(self.m.latest_code("copy")[0], "482913")
        self.assertEqual(self.m.latest_code("browser"), ("", 0))  # default mode: copy only

    def test_copy_action(self):
        self.receive_ancs_then_map()
        copied = []
        self.m._copy_code = lambda key, delete: copied.append((key, delete))
        self.notifier.shown[0]["on_action"]("copy-code-delete")
        self.assertEqual(len(copied), 1)
        self.assertTrue(copied[0][1])

    def test_browser_mode_and_off(self):
        self.hooks.config = FakeConfig("browser")
        self.receive_ancs_then_map()
        self.assertEqual(self.m.latest_code("browser")[0], "482913")
        self.m.set_code_mode("off")
        self.assertEqual(self.m.latest_code("copy"), ("", 0))
        self.assertEqual(self.m.codes.code, "")  # forgotten at once

    def test_off_means_plain_notification(self):
        self.hooks.config = FakeConfig("off")
        self.receive_ancs_then_map()
        keys = [k for k, _ in self.notifier.shown[0]["actions"]]
        self.assertNotIn("copy-code", keys)
        self.assertEqual(self.m.codes.code, "")


class BrowserHostTest(unittest.TestCase):
    def test_manifests_for_present_browsers(self):
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, ".config", "google-chrome"))
            os.makedirs(os.path.join(home, ".mozilla"))
            os.environ["COVALENCE_OTP_HOST"] = "/opt/covalence/covalence-otp-host"
            try:
                installed = browser_host.install(home=home, which=lambda _c: None)
            finally:
                del os.environ["COVALENCE_OTP_HOST"]
            self.assertEqual(installed, ["Google Chrome", "Firefox"])
            with open(os.path.join(home, ".config/google-chrome/NativeMessagingHosts",
                                   "com.covalence.otp.json")) as f:
                chrome = json.load(f)
            self.assertEqual(chrome["allowed_origins"],
                             ["chrome-extension://bbnmajflfndmkepfcnmpabhmneoplfkk/"])
            self.assertEqual(chrome["path"], "/opt/covalence/covalence-otp-host")
            with open(os.path.join(home, ".mozilla/native-messaging-hosts",
                                   "com.covalence.otp.json")) as f:
                firefox = json.load(f)
            self.assertEqual(firefox["allowed_extensions"], ["otp@covalence.melvincouwez.github.io"])
            self.assertNotIn("allowed_origins", firefox)

    def test_extension_id_matches_key(self):
        import base64
        import hashlib
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "extension", "manifest.json")) as f:
            key = base64.b64decode(json.load(f)["key"])
        digest = hashlib.sha256(key).hexdigest()[:32]
        self.assertEqual("".join(chr(ord("a") + int(c, 16)) for c in digest),
                         browser_host.CHROMIUM_ID)

    def test_host_protocol(self):
        import io
        import struct
        request = json.dumps({"type": "nope"}).encode()
        stdin = io.BytesIO(struct.pack("=I", len(request)) + request)
        self.assertEqual(browser_host._read(stdin), {"type": "nope"})
        out = io.BytesIO()
        browser_host._write(out, {"code": "", "age": 0})
        size = struct.unpack("=I", out.getvalue()[:4])[0]
        self.assertEqual(json.loads(out.getvalue()[4:4 + size]), {"code": "", "age": 0})


if __name__ == "__main__":
    unittest.main()
