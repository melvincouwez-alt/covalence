# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Bounded download caches and the D-Bus method guard (offline)."""

import os
import tempfile
import time
import unittest

from covalenced import cachedir


class PruneTest(unittest.TestCase):
    def test_old_and_extra_files_go_recent_ones_stay(self):
        with tempfile.TemporaryDirectory() as d:
            now = time.time()
            for i in range(6):
                path = os.path.join(d, f"{i}.png")
                open(path, "wb").close()
                os.utime(path, (now - i * 3600, now - i * 3600))
            old = os.path.join(d, "old.png")
            open(old, "wb").close()
            os.utime(old, (now - 100 * 86400, now - 100 * 86400))
            self.assertEqual(cachedir.prune(d, max_files=4, max_age_days=30), 3)
            self.assertEqual(sorted(os.listdir(d)), ["0.png", "1.png", "2.png", "3.png"])

    def test_touch_keeps_a_used_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.jpg")
            open(path, "wb").close()
            os.utime(path, (1, 1))
            cachedir.touch(path)
            self.assertEqual(cachedir.prune(d, 10, 30), 0)

    def test_missing_directory_is_harmless(self):
        self.assertEqual(cachedir.prune("/nonexistent/covalence-test", 1, 1), 0)


class MethodGuardTest(unittest.TestCase):
    def test_exception_answers_the_caller(self):
        from covalenced import service

        class Invocation:
            error = None

            def return_dbus_error(self, name, message):
                self.error = (name, message)

        svc = service.Service.__new__(service.Service)
        svc._dispatch = lambda *a: (_ for _ in ()).throw(ValueError("boom"))
        inv = Invocation()
        svc._method(None, ":1.1", "/", "i", "Reconnect", None, inv)
        self.assertEqual(inv.error[0], f"{service.INTERFACE}.Error.Failed")
        self.assertIn("boom", inv.error[1])


if __name__ == "__main__":
    unittest.main()
