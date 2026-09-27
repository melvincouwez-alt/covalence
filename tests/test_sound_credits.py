# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Covalence's own sounds: every file present, listed and credited (nothing is played)."""

import os
import unittest

from covalenced import sounds

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOUNDS = os.path.join(ROOT, "data", "sounds")


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class BundledSoundsTest(unittest.TestCase):
    def test_files_match_the_list(self):
        files = sorted(n[:-4] for n in os.listdir(SOUNDS) if n.endswith(".oga"))
        self.assertEqual(files, sorted(name for name, _title in sounds.BUNDLED))
        for name in files:
            with open(os.path.join(SOUNDS, name + ".oga"), "rb") as f:
                self.assertEqual(f.read(4), b"OggS", name)

    def test_every_sound_is_credited(self):
        credits, notice, copyright = (read("docs", "credits-sons.md"), read("data", "sounds", "NOTICE"),
                                      read("debian", "copyright"))
        for name, _title in sounds.BUNDLED:
            for text in (credits, notice, copyright):
                self.assertIn(f"{name}.oga", text)
        for license in ("Apache-2.0.txt", "CC0-1.0.txt"):
            self.assertTrue(os.path.isfile(os.path.join(SOUNDS, "LICENSES", license)))

    def test_listed_first_and_resolved(self):
        listed = [value for value, _label in sounds.available()]
        own = [sounds.BUNDLED_PREFIX + name for name, _title in sounds.BUNDLED]
        self.assertEqual(listed[:len(own)], own)
        for value in own:
            self.assertTrue(os.path.isfile(sounds.resolve(value)), value)
        self.assertIsNone(sounds.resolve(sounds.BUNDLED_PREFIX + "missing"))
        self.assertEqual(sounds.label("covalence:rosee"), "Covalence · Rosée")


if __name__ == "__main__":
    unittest.main()
