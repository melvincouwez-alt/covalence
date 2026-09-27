# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Update checks against GitHub releases (offline: the release list is made up)."""

import unittest

from covalenced import updates

SHA = "0" * 63 + "1"


def release(tag, prerelease=False, draft=False, digest=True, name=None):
    asset = {"name": name or f"covalence_{tag.lstrip('v')}-1_amd64.deb", "size": 1000,
             "browser_download_url": f"https://github.com/melvincouwez-alt/covalence/releases/"
                                     f"download/{tag}/covalence_{tag.lstrip('v')}-1_amd64.deb"}
    if digest:
        asset["digest"] = "sha256:" + SHA
    return {"tag_name": tag, "prerelease": prerelease, "draft": draft, "assets": [asset],
            "html_url": f"https://github.com/melvincouwez-alt/covalence/releases/tag/{tag}",
            "body": "Nouveautés"}


class FakeConfig:
    def __init__(self):
        self.values = {}

    def boolean(self, group, key, default=False):
        return self.values.get((group, key), default)

    def set_boolean(self, group, key, value):
        self.values[(group, key)] = value

    def string(self, group, key, default=""):
        return self.values.get((group, key), default)

    def set_string(self, group, key, value):
        self.values[(group, key)] = value


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def notify(self, app_name, icon, summary, body="", actions=(), **kwargs):
        self.sent.append((summary, [key for key, _label in actions]))
        return len(self.sent)


class VersionTest(unittest.TestCase):
    def test_order(self):
        ordered = ["0.1.9", "0.2.0-alpha", "0.2.0-alpha.2", "0.2.0-beta1", "0.2.0-rc.1",
                   "0.2.0", "v0.2.1", "0.10.0", "1.0"]
        keys = [updates.version_key(v) for v in ordered]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(set(keys)), len(keys))

    def test_newer(self):
        self.assertTrue(updates.is_newer("v0.3.0", "0.2.0"))
        self.assertTrue(updates.is_newer("0.2.0", "0.2.0-alpha"))
        self.assertFalse(updates.is_newer("v0.2.0", "0.2.0"))
        self.assertFalse(updates.is_newer("0.2.0-rc1", "0.2.0"))
        self.assertFalse(updates.is_newer("nightly", "0.2.0"))

    def test_pick(self):
        found = updates.pick([release("v0.2.0", prerelease=True), release("v0.4.0", draft=True),
                              release("v0.3.0-alpha", prerelease=True), {"junk": 1}], "0.2.0")
        self.assertEqual(found["tag_name"], "v0.3.0-alpha")  # pre-release in, draft out
        self.assertIsNone(updates.pick([release("v0.2.0")], "0.2.0"))

    def test_deb_asset(self):
        url, size, sha = updates.deb_asset(release("v0.3.0"))
        self.assertTrue(url.endswith("_amd64.deb"))
        self.assertEqual((size, sha), (1000, SHA))
        self.assertEqual(updates.deb_asset(release("v0.3.0", digest=False))[2], "")
        self.assertEqual(updates.deb_asset(release("v0.3.0", name="notes.txt"))[0], "")


class CheckTest(unittest.TestCase):
    def make(self, releases):
        self.notifier = FakeNotifier()
        self.changes = 0

        def changed():
            self.changes += 1

        u = updates.Updates(FakeConfig(), self.notifier, changed, current="0.2.0",
                            fetch=lambda url: releases, cache_dir="/nonexistent")
        return u

    def test_available_notified_once_per_version(self):
        u = self.make([release("v0.3.0")])
        results = []
        u.waiters.append(lambda latest, error: results.append((latest, error)))
        u._checked([release("v0.3.0")], None)
        u._checked([release("v0.3.0")], None)
        self.assertEqual(results, [("0.3.0", None)])
        state = u.state()
        self.assertEqual((state["state"], state["latest"], state["can_install"]),
                         ("available", "0.3.0", True))
        self.assertEqual(len(self.notifier.sent), 1)
        self.assertIn("install", self.notifier.sent[0][1])
        self.assertEqual(u.available(), 1)
        self.assertGreater(state["checked"], 0)

    def test_up_to_date(self):
        u = self.make([])
        u._checked([release("v0.2.0")], None)
        self.assertEqual((u.state()["state"], u.state()["latest"]), ("idle", ""))
        self.assertEqual(self.notifier.sent, [])

    def test_error(self):
        u = self.make([])
        results = []
        u.waiters.append(lambda latest, error: results.append((latest, error)))
        u._checked(None, "URLError")
        self.assertEqual(u.state()["state"], "error")
        self.assertEqual(results[0][0], "")
        self.assertIn("URLError", results[0][1])

    def test_no_digest_no_install(self):
        u = self.make([])
        u._checked([release("v0.3.0", digest=False)], None)
        self.assertFalse(u.state()["can_install"])
        self.assertNotIn("install", self.notifier.sent[0][1])
        errors = []
        u.install(errors.append)
        self.assertEqual(len(errors), 1)
        self.assertEqual(u.state()["state"], "available")  # nothing started

    def test_auto_setting(self):
        u = self.make([])
        self.assertTrue(u.auto)
        u.set_auto(False)
        self.assertFalse(u.auto)
        self.assertFalse(u.state()["auto"])


if __name__ == "__main__":
    unittest.main()
