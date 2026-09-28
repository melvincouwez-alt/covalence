# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Offline checks of the 0.5 security fixes: pairing confirmation, callers of the D-Bus
API, bMessage framing, domain-bound SMS codes, LocalSend peers, updates, mirroring.

Nothing here touches Bluetooth, the network, polkit or the real daemon."""

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from gi.repository import GLib

from covalenced import bmsg, callers, link, localsend, mirror, otp, service, updates
from tests import test_link
from tests.test_link import ADAPTER, PHONE

KEYBOARD = ADAPTER + "/dev_11_22_33_44_55_66"
HFP = "0000111f-0000-1000-8000-00805f9b34fb"
HID = "00001124-0000-1000-8000-00805f9b34fb"


class Invocation:
    def __init__(self):
        self.value = self.error = None

    def return_value(self, value):
        self.value = ("ok", value)

    def return_dbus_error(self, name, message):
        self.error = name


class Notifier:
    def __init__(self):
        self.shown = []
        self.closed = []

    def notify(self, *args, **kwargs):
        self.shown.append(kwargs)
        return len(self.shown)

    def close(self, note):
        self.closed.append(note)


class PairingTest(unittest.TestCase):
    make = test_link.LinkTest.make  # the link tests' fake BlueZ (not their tests)

    def window(self, **phone):
        lk, fake = self.make(**phone)
        patch = mock.patch.object(link, "call_sync", lambda *a, **k: None)
        patch.start()
        self.addCleanup(patch.stop)
        known = lk._device_props
        lk._device_props = lambda path: known(path) if path in fake.objects() else {}
        lk.pairing = True
        lk.notifier = Notifier()
        return lk, fake

    def request(self, lk, device=PHONE, passkey=123456):
        invocation = Invocation()
        lk._agent_method(None, ":1.1", None, None, "RequestConfirmation",
                         GLib.Variant("(ou)", (device, passkey)), invocation)
        return invocation

    def test_code_waits_for_the_user(self):
        lk, _fake = self.window()
        invocation = self.request(lk)
        self.assertIsNone(invocation.value)  # BlueZ has no answer yet
        self.assertIsNone(invocation.error)
        self.assertTrue(lk.confirm_pairing(True))
        self.assertEqual(invocation.value[0], "ok")
        self.assertIn(PHONE, lk.confirmed)
        self.assertFalse(lk.confirm_pairing(True))  # nothing left to confirm

    def test_refused_code(self):
        lk, _fake = self.window()
        invocation = self.request(lk)
        lk.confirm_pairing(False)
        self.assertEqual(invocation.error, "org.bluez.Error.Rejected")
        self.assertNotIn(PHONE, lk.confirmed)

    def test_notification_button_answers_too(self):
        lk, _fake = self.window()
        invocation = self.request(lk)
        lk.notifier.shown[-1]["on_action"]("match")
        self.assertEqual(invocation.value[0], "ok")

    def test_window_closing_refuses_a_pending_code(self):
        lk, _fake = self.window()
        invocation = self.request(lk)
        lk.stop_pairing()
        self.assertEqual(invocation.error, "org.bluez.Error.Rejected")

    def test_not_a_phone_is_refused_at_once(self):
        lk, _fake = self.window(Icon="input-keyboard", Modalias="")
        invocation = self.request(lk)
        self.assertEqual(invocation.error, "org.bluez.Error.Rejected")

    def test_other_maker_is_refused(self):
        lk, _fake = self.window(Icon="phone", Modalias="bluetooth:v0075p1")
        self.assertEqual(self.request(lk).error, "org.bluez.Error.Rejected")

    def test_just_works_is_refused(self):
        lk, _fake = self.window()
        invocation = Invocation()
        lk._agent_method(None, ":1.1", None, None, "RequestAuthorization",
                         GLib.Variant("(o)", (PHONE,)), invocation)
        self.assertEqual(invocation.error, "org.bluez.Error.Rejected")

    def test_services(self):
        lk, _fake = self.window()
        lk.device = None
        self.assertFalse(lk.service_allowed(PHONE, HFP))  # not confirmed yet
        self.request(lk)
        lk.confirm_pairing(True)
        self.assertTrue(lk.service_allowed(PHONE, HFP))
        self.assertFalse(lk.service_allowed(PHONE, HID))  # never a keyboard
        self.assertFalse(lk.service_allowed(PHONE, "0000abcd-0000-1000-8000-00805f9b34fb"))
        self.assertFalse(lk.service_allowed(KEYBOARD, HFP))
        lk.pairing = False
        self.assertFalse(lk.service_allowed(PHONE, HFP))

    def test_unconfirmed_bond_is_not_trusted(self):
        lk, fake = self.window(Trusted=False)
        lk.device = None
        lk._pairing_done(PHONE, dict(fake.phone))
        self.assertNotIn((PHONE, "Trusted", True), fake.props)
        self.request(lk)
        lk.confirm_pairing(True)
        with mock.patch.object(lk, "_attach"), mock.patch.object(lk, "_set_device"):
            lk._pairing_done(PHONE, dict(fake.phone))
        self.assertIn((PHONE, "Trusted", True), fake.props)


class CallersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def binary(self, folder, name="io.github.melvincouwez.Covalence"):
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path, "w") as out:
            out.write("#!/bin/sh\n")
        os.chmod(path, 0o755)
        return path

    def test_app_next_to_the_daemon(self):
        prefix = os.path.join(self.tmp, "prefix")
        app = self.binary(os.path.join(prefix, "bin"))
        self.assertTrue(callers.is_app_executable(app, prefix=prefix))
        self.assertFalse(callers.is_app_executable(app, prefix=os.path.join(self.tmp, "other")))

    def test_other_programs(self):
        prefix = os.path.join(self.tmp, "prefix")
        fake = self.binary(os.path.join(prefix, "bin"), "python3")
        self.assertFalse(callers.is_app_executable(fake, prefix=prefix))
        self.assertFalse(callers.is_app_executable(sys.executable, prefix=prefix))
        self.assertFalse(callers.is_app_executable("", prefix=prefix))
        self.assertFalse(callers.is_app_executable(
            os.path.join(prefix, "bin", "io.github.melvincouwez.Covalence (deleted)"), prefix=prefix))

    def test_files_outside_home(self):
        home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(home, "Documents"))
        os.makedirs(os.path.join(home, ".ssh"))
        doc = os.path.join(home, "Documents", "a.pdf")
        key = os.path.join(home, ".ssh", "id_ed25519")
        link_to_key = os.path.join(home, "Documents", "harmless.pdf")
        for path in (doc, key):
            open(path, "w").close()
        os.symlink(key, link_to_key)
        self.assertEqual(service.outside_home([doc], home), [])
        self.assertEqual(service.outside_home([key, link_to_key, "/etc/passwd", home], home),
                         [key, link_to_key, "/etc/passwd", home])


class GuardTest(unittest.TestCase):
    """service.Service._method with a fake caller identity."""

    def make(self, trusted):
        svc = service.Service.__new__(service.Service)
        svc.callers = mock.Mock()
        svc.callers.describe.return_value = (trusted, "evil")
        svc.daemon = mock.Mock()
        svc.daemon.notifier = Notifier()
        svc.calls = []
        svc._call = lambda method, params, invocation: svc.calls.append(method)
        return svc

    def call(self, svc, method, args):
        invocation = Invocation()
        svc._method(None, ":1.9", None, None, method, args, invocation)
        return invocation

    def test_app_is_not_asked(self):
        svc = self.make(True)
        self.call(svc, "Dial", GLib.Variant("(s)", ("0600000000",)))
        self.assertEqual(svc.calls, ["Dial"])
        self.assertEqual(svc.daemon.notifier.shown, [])

    def test_reading_is_free(self):
        svc = self.make(False)
        self.call(svc, "ListThreads", None)
        self.assertEqual(svc.calls, ["ListThreads"])
        svc.callers.describe.assert_not_called()

    def test_other_program_needs_a_yes(self):
        svc = self.make(False)
        self.call(svc, "Dial", GLib.Variant("(s)", ("0899000000",)))
        self.assertEqual(svc.calls, [])
        note = svc.daemon.notifier.shown[-1]
        note["on_action"]("allow")
        self.assertEqual(svc.calls, ["Dial"])

    def test_refusal_and_dismissal(self):
        svc = self.make(False)
        invocation = self.call(svc, "SendMessage", GLib.Variant("(ss)", ("t", "coucou")))
        svc.daemon.notifier.shown[-1]["on_action"]("deny")
        self.assertEqual(invocation.error, f"{service.INTERFACE}.Error.Refused")
        invocation = self.call(svc, "InstallUpdate", None)
        svc.daemon.notifier.shown[-1]["on_closed"]()
        self.assertEqual(invocation.error, f"{service.INTERFACE}.Error.Refused")
        self.assertEqual(svc.calls, [])

    def test_app_only(self):
        svc = self.make(False)
        for method, args in (("ConfirmPairing", GLib.Variant("(b)", (True,))),
                             ("ControlText", GLib.Variant("(s)", ("hello",))),
                             ("LatestCode", GLib.Variant("(s)", ("copy",)))):
            invocation = self.call(svc, method, args)
            self.assertEqual(invocation.error, f"{service.INTERFACE}.Error.NotAllowed")
        self.assertEqual(svc.calls, [])
        self.assertEqual(svc.daemon.notifier.shown, [])
        self.call(svc, "LatestCode", GLib.Variant("(s)", ("browser",)))  # the browser host
        self.assertEqual(svc.calls, ["LatestCode"])

    def test_send_files_outside_home_is_refused_without_asking(self):
        svc = self.make(False)
        invocation = self.call(svc, "SendFiles", GLib.Variant("(sas)", ("peer", ["/etc/shadow"])))
        self.assertEqual(invocation.error, f"{service.INTERFACE}.Error.NotAllowed")
        self.assertEqual(svc.daemon.notifier.shown, [])


class BMessageTest(unittest.TestCase):
    def envelope(self, text, length=None):
        msg = "BEGIN:MSG\r\n" + text.replace("\n", "\r\n") + "\r\nEND:MSG\r\n"
        size = len(msg.encode("utf-8")) if length is None else length
        return ("BEGIN:BMSG\r\nVERSION:1.0\r\nSTATUS:READ\r\nTYPE:SMS_GSM\r\nFOLDER:TELECOM/MSG/INBOX\r\n"
                "BEGIN:VCARD\r\nVERSION:2.1\r\nN:Alice\r\nTEL:+33600000001\r\nEND:VCARD\r\n"
                "BEGIN:BENV\r\n"
                "BEGIN:VCARD\r\nVERSION:2.1\r\nN:\r\nTEL:+33600000002\r\nEND:VCARD\r\n"
                f"BEGIN:BBODY\r\nCHARSET:UTF-8\r\nLENGTH:{size}\r\n{msg}"
                "END:BBODY\r\nEND:BENV\r\nEND:BMSG\r\n")

    INJECTION = ("Salut\nEND:MSG\nEND:BBODY\nBEGIN:VCARD\nVERSION:2.1\nTEL:+33699999999\n"
                 "END:VCARD\nBEGIN:BBODY\nBEGIN:MSG\nfin")

    def test_text_cannot_add_recipients(self):
        parsed = bmsg.parse_bmessage(self.envelope(self.INJECTION))
        self.assertEqual([c["addresses"] for c in parsed["recipients"]], [["+33600000002"]])
        # Framed by LENGTH: the text keeps its first and last words (lines that look like
        # part markers are read as such, never as envelope data).
        self.assertTrue(parsed["body"].startswith("Salut") and parsed["body"].endswith("fin"))

    def test_without_length_the_last_end_wins(self):
        text = self.envelope(self.INJECTION).replace("LENGTH:", "X-LENGTH:")
        parsed = bmsg.parse_bmessage(text)
        self.assertEqual(len(parsed["recipients"]), 1)
        self.assertTrue(parsed["body"].startswith("Salut") and parsed["body"].endswith("fin"))

    def test_plain_message_and_accents(self):
        parsed = bmsg.parse_bmessage(self.envelope("Ça marche ? 👍"))
        self.assertEqual(parsed["body"], "Ça marche ? 👍")
        self.assertEqual(parsed["originator"]["addresses"], ["+33600000001"])
        self.assertEqual(parsed["type"], "SMS_GSM")

    def test_wrong_length_falls_back(self):
        parsed = bmsg.parse_bmessage(self.envelope("Bonjour", length=3))
        self.assertEqual(parsed["body"], "Bonjour")


class BoundCodeTest(unittest.TestCase):
    def test_bound(self):
        sms = "Votre code Ma Banque : 482913\n\n@banque.example #482913"
        self.assertEqual(otp.detect(sms), "482913")
        self.assertEqual(otp.bound_domains(sms, "482913"), ["banque.example"])
        self.assertEqual(otp.bound_domains("Code 482913\n@a.example #482913 %b.example", "482913"),
                         ["a.example", "b.example"])

    def test_not_bound(self):
        self.assertEqual(otp.bound_domains("Votre code : 482913", "482913"), [])
        self.assertEqual(otp.bound_domains("Code 482913\n@a.example #111111", "482913"), [])
        self.assertEqual(otp.bound_domains("Code 482913\n@a.example #482913 merci", "482913"), [])


class LocalSendPeersTest(unittest.TestCase):
    def test_http_peers_are_ignored(self):
        self.assertIsNone(localsend.peer_from({"fingerprint": "f", "protocol": "http"}, "192.0.2.4"))

    def test_known_peer_keeps_its_addresses(self):
        real = localsend.peer_from({"fingerprint": "f", "protocol": "https"}, "192.0.2.4")
        fake = localsend.peer_from({"fingerprint": "f", "protocol": "https"}, "192.0.2.66")
        merged = localsend.merge_peer(real, fake)
        self.assertEqual(merged["addresses"], ["192.0.2.66", "192.0.2.4"])

    def test_verified_address_is_used(self):
        peer = dict(localsend.peer_from({"fingerprint": "f"}, "192.0.2.4"),
                    addresses=["192.0.2.66", "192.0.2.4"])

        def request(candidate, *_args, **_kwargs):
            if candidate["address"] != "192.0.2.4":
                raise localsend.SendError("fingerprint")
            return 200, b"{}"

        with mock.patch.object(localsend, "_request", request):
            self.assertEqual(localsend.verified_peer(peer)["address"], "192.0.2.4")
            with self.assertRaises(localsend.SendError):
                localsend.verified_peer(dict(peer, addresses=["192.0.2.66"]))

    def test_size_limits(self):
        body = ('{"info": {"fingerprint": "f"}, "files": {"1": {"fileName": "a", "size": %d}}}'
                % (localsend.MAX_TOTAL + 1))
        with self.assertRaises(ValueError):
            localsend.parse_prepare(body)
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        self.assertTrue(localsend.room_for(os.path.join(folder, "Covalence"), 1))
        self.assertFalse(localsend.room_for(folder, 1 << 62))


class UpdateInstallerTest(unittest.TestCase):
    """bin/covalence-install-update, run without root: argument checks only."""

    def run_helper(self, *args):
        source = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "bin", "covalence-install-update.in")
        with open(source, encoding="utf-8") as f:
            code = f.read().replace("@PYTHON@", sys.executable)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        helper = os.path.join(tmp, "covalence-install-update")
        with open(helper, "w", encoding="utf-8") as out:
            out.write(code)
        os.chmod(helper, stat.S_IRWXU)
        return subprocess.run([helper, *args], capture_output=True, text=True, timeout=30)

    def test_arguments(self):
        self.assertEqual(self.run_helper().returncode, 2)
        self.assertEqual(self.run_helper("/tmp/x.deb", "nothex").returncode, 2)
        self.assertEqual(self.run_helper("/tmp/x.txt", "a" * 64).returncode, 2)
        if os.geteuid() != 0:
            result = self.run_helper("/tmp/x.deb", "a" * 64)
            self.assertEqual(result.returncode, 2)
            self.assertIn("root", result.stderr)

    def test_daemon_runs_the_helper_with_the_digest(self):
        spawned = []

        class Process:
            def communicate_utf8_async(self, *_args):
                spawned.append("waiting")

        sha = "b" * 64
        up = updates.Updates(mock.Mock(), mock.Mock(), None, current="0.4.2")
        up.release = {"tag_name": "v0.5.0", "assets": [
            {"name": "covalence_0.5.0-1_amd64.deb", "size": 1, "digest": "sha256:" + sha,
             "browser_download_url": "https://github.com/x/covalence_0.5.0-1_amd64.deb"}]}
        with mock.patch.object(updates, "installer_path", lambda: "/usr/libexec/covalence/h"), \
                mock.patch.object(updates, "_arch", lambda: "amd64"), \
                mock.patch.object(updates.Gio.Subprocess, "new",
                                  lambda argv, flags: spawned.append(argv) or Process()):
            up._downloaded("/home/u/.cache/covalence/updates/c.deb", None, lambda e: None)
        self.assertEqual(spawned[0], ["pkexec", "/usr/libexec/covalence/h",
                                      "/home/u/.cache/covalence/updates/c.deb", sha])

    def test_no_helper_no_install(self):
        errors = []
        up = updates.Updates(mock.Mock(), mock.Mock(), None, current="0.4.2")
        up.release = {"tag_name": "v0.5.0", "assets": []}
        with mock.patch.object(updates, "installer_path", lambda: ""):
            up._downloaded("/x.deb", None, errors.append)
        self.assertEqual(up.state_name, "error")
        self.assertTrue(errors)


class MirrorPinTest(unittest.TestCase):
    def test_pin_on_the_command_line(self):
        args = mirror.build_args("Covalence (PC)", pin="0427")
        self.assertEqual(args[args.index("-pin") + 1], "0427")
        self.assertNotIn("-pin", mirror.build_args("Covalence (PC)"))

    def test_pins(self):
        for _ in range(200):
            pin = mirror.new_pin()
            self.assertRegex(pin, r"^\d{4}$")
            self.assertNotEqual(pin, "0000")


if __name__ == "__main__":
    unittest.main()
