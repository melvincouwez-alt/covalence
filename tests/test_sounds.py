# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Offline checks of the sounds chosen in Réglages (nothing is played): python3 -m unittest"""

import os
import tempfile
import unittest
from unittest import mock

from gi.repository import GLib

from covalenced import calls, sounds
from covalenced.config import Config


def private_config(tmp):
    config = Config()
    config.dir, config.path = tmp, os.path.join(tmp, "covalenced.conf")
    config.keyfile = GLib.KeyFile()
    return config


class SilentSounds(sounds.Sounds):
    """Records what would be played instead of playing it."""

    def __init__(self, config):
        super().__init__(config)
        self.played = []

    def _spawn(self, path, on_exit=None):
        self.played.append(path)
        return bool(path)


class SoundsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.theme = os.path.join(self.tmp.name, "share", "sounds", "freedesktop", "stereo")
        os.makedirs(self.theme)
        for name in ("message-new-instant.oga", "dialog-information.oga",
                     "phone-incoming-call.oga", "bell.oga", "audio-channel-front-left.oga"):
            open(os.path.join(self.theme, name), "wb").close()
        self.dirs = mock.patch.object(sounds, "_theme_dirs", return_value=[self.theme])
        self.dirs.start()
        self.dnd = mock.patch.object(sounds, "do_not_disturb", return_value=False)
        self.dnd_on = self.dnd.start()
        self.s = SilentSounds(private_config(self.tmp.name))

    def tearDown(self):
        mock.patch.stopall()
        self.tmp.cleanup()

    def test_defaults_and_list(self):
        self.assertEqual(self.s.settings(), {"messages": "default", "notifications": "default",
                                             "calls": "default"})
        names = [value for value, _label in sounds.available()]
        self.assertIn("bell", names)
        self.assertNotIn("audio-channel-front-left", names)
        self.assertTrue(self.s.play("messages"))
        self.assertTrue(self.s.played[-1].endswith("message-new-instant.oga"))

    def test_choice_none_and_file(self):
        self.s.set("messages", "none")
        self.assertFalse(self.s.play("messages"))
        custom = os.path.join(self.tmp.name, "ding.wav")
        open(custom, "wb").close()
        self.s.set("notifications", custom)
        self.s.last_alert = 0
        self.assertTrue(self.s.play("notifications"))
        self.assertEqual(self.s.played[-1], custom)
        with self.assertRaises(ValueError):
            self.s.set("calls", "/nowhere/missing.ogg")
        with self.assertRaises(ValueError):
            self.s.set("alarm", "bell")

    def test_do_not_disturb_and_bursts(self):
        self.dnd_on.return_value = True
        self.assertFalse(self.s.play("messages"))
        self.s.start_ring()
        self.assertFalse(self.s.ringing)
        self.dnd_on.return_value = False
        self.assertTrue(self.s.play("messages"))
        self.assertFalse(self.s.play("notifications"))  # a burst gives one sound

    def test_ring_follows_the_call(self):
        c = calls.Calls.__new__(calls.Calls)
        c.calls, c.transport, c.ringer, c.quiet = {}, {}, self.s, lambda: False
        c.calls["/call1"] = {"State": "incoming"}
        c._update_ring()
        self.assertTrue(self.s.ringing)
        self.assertTrue(self.s.played[-1].endswith("phone-incoming-call.oga"))
        c.calls["/call1"]["State"] = "active"
        c._update_ring()
        self.assertFalse(self.s.ringing)
        # the iPhone rings in-band over the hands-free audio: Covalence stays quiet
        c.calls["/call1"]["State"] = "incoming"
        c.transport["/gw"] = {"State": "active"}
        c._update_ring()
        self.assertFalse(self.s.ringing)


if __name__ == "__main__":
    unittest.main()
