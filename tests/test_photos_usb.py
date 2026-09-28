# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Photo import from a (fake) mounted iPhone: which files, where, and no duplicates."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from covalenced import photos_usb  # noqa: E402


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.phone = tempfile.mkdtemp()
        self.dest = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.phone)
        self.addCleanup(shutil.rmtree, self.dest)
        for folder, name, size in (("100APPLE", "IMG_0001.JPG", 10), ("100APPLE", "IMG_0002.HEIC", 20),
                                   ("101APPLE", "IMG_0003.MOV", 30), ("101APPLE", "IMG_0003.AAE", 5),
                                   ("101APPLE", "IMG_0001.JPG", 11)):
            path = os.path.join(self.phone, "DCIM", folder)
            os.makedirs(path, exist_ok=True)
            with open(os.path.join(path, name), "wb") as f:
                f.write(b"x" * size)

    def run_import(self):
        steps = []
        counts = photos_usb.import_files(self.phone, self.dest, False,
                                         lambda *args: steps.append(args), lambda: False)
        return counts, steps

    def test_media_only(self):
        names = [os.path.basename(p) for p, _size in photos_usb.media_files(self.phone)]
        self.assertNotIn("IMG_0003.AAE", names)
        self.assertEqual(len(names), 4)

    def test_import_then_nothing_twice(self):
        (imported, skipped), steps = self.run_import()
        self.assertEqual((imported, skipped), (4, 0))
        self.assertEqual(steps[-1][:2], (4, 4))
        # Same name, other size: kept under another name.
        self.assertTrue(os.path.exists(os.path.join(self.dest, "IMG_0001_2.JPG")))
        (imported, skipped), _steps = self.run_import()
        self.assertEqual((imported, skipped), (0, 4))

    def test_existing_file_same_size_is_skipped(self):
        with open(os.path.join(self.dest, "IMG_0003.MOV"), "wb") as f:
            f.write(b"x" * 30)
        (imported, skipped), _steps = self.run_import()
        self.assertEqual((imported, skipped), (3, 1))

    def test_heic_target_becomes_jpg(self):
        target = photos_usb.target_for(self.dest, "DCIM/100APPLE/IMG_0002.HEIC", 20, True)
        self.assertEqual(os.path.basename(target), "IMG_0002.jpg")


if __name__ == "__main__":
    unittest.main()
