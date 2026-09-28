# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""iPhone control (HID over GATT) and screen mirroring options: pure logic, no Bluetooth."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gi.repository import GLib  # noqa: E402

from covalenced import hid, mirror  # noqa: E402


def items(report_map):
    """(tag byte, data) pairs of a HID report descriptor (short items only)."""
    out, i = [], 0
    while i < len(report_map):
        prefix = report_map[i]
        size = {0: 0, 1: 1, 2: 2, 3: 4}[prefix & 0x03]
        out.append((prefix & 0xFC, report_map[i + 1:i + 1 + size]))
        i += 1 + size
    return out


class ReportMapTest(unittest.TestCase):
    def test_collections_balance_and_ids(self):
        tags = items(hid.REPORT_MAP)
        opened = sum(1 for tag, _ in tags if tag == 0xA0)
        closed = sum(1 for tag, _ in tags if tag == 0xC0)
        self.assertEqual(opened, closed)
        ids = [data[0] for tag, data in tags if tag == 0x84]
        self.assertEqual(ids, [hid.KEYBOARD_ID, hid.MOUSE_ID])

    def test_input_sizes_match_reports(self):
        # Sum report size x count of each Input item, per report id, in bits.
        bits, current, size, count = {}, None, 0, 0
        for tag, data in items(hid.REPORT_MAP):
            if tag == 0x84:
                current = data[0]
            elif tag == 0x74:
                size = data[0]
            elif tag == 0x94:
                count = data[0]
            elif tag == 0x80:
                bits[current] = bits.get(current, 0) + size * count
        self.assertEqual(bits[hid.KEYBOARD_ID], len(hid.keyboard_report()) * 8)
        self.assertEqual(bits[hid.MOUSE_ID], len(hid.mouse_report()) * 8)


class ReportsTest(unittest.TestCase):
    def test_keyboard_report(self):
        self.assertEqual(hid.keyboard_report(hid.LSHIFT, [0x14]), bytes([2, 0, 0x14, 0, 0, 0, 0, 0]))
        self.assertEqual(len(hid.keyboard_report(0, range(1, 10))), 8)  # at most six keys

    def test_mouse_report_clamps_and_signs(self):
        self.assertEqual(hid.mouse_report(hid.BUTTON_LEFT, -1, 300, 0), bytes([1, 0xFF, 127, 0]))

    def test_split_move(self):
        moves = hid.split_move(300, -50)
        self.assertEqual(sum(m[0] for m in moves), 300)
        self.assertEqual(sum(m[1] for m in moves), -50)
        self.assertTrue(all(abs(x) <= 127 and abs(y) <= 127 for x, y in moves))
        self.assertEqual(hid.split_move(0, 0), [])

    def test_goto_goes_home_then_to_the_point(self):
        moves = hid.goto_moves(0.5, 0.25, 400, 800)
        home = hid.home_moves(400, 800)
        self.assertEqual(moves[:len(home)], home)
        self.assertLessEqual(sum(m[0] for m in home), -800)
        rest = moves[len(home):]
        self.assertEqual((sum(m[0] for m in rest), sum(m[1] for m in rest)), (200, 200))

    def test_goto_clamps_fractions(self):
        rest = hid.goto_moves(2.0, -1.0, 100, 100)[len(hid.home_moves(100, 100)):]
        self.assertEqual((sum(m[0] for m in rest), sum(m[1] for m in rest)), (100, 0))


class AzertyTest(unittest.TestCase):
    def test_letters_by_position(self):
        self.assertEqual(hid.AZERTY["a"], (0x14, 0))  # the key where QWERTY has Q
        self.assertEqual(hid.AZERTY["q"], (0x04, 0))
        self.assertEqual(hid.AZERTY["m"], (0x33, 0))
        self.assertEqual(hid.AZERTY["W"], (0x1D, hid.LSHIFT))

    def test_digits_need_shift_and_accents_do_not(self):
        self.assertEqual(hid.AZERTY["1"], (0x1E, hid.LSHIFT))
        self.assertEqual(hid.AZERTY["é"], (0x1F, 0))
        self.assertEqual(hid.AZERTY["à"], (0x27, 0))
        self.assertEqual(hid.AZERTY["@"], (0x27, hid.RALT))
        self.assertEqual(hid.AZERTY["?"], (0x10, hid.LSHIFT))

    def test_text_reports(self):
        reports, skipped = hid.text_reports("Ça va ?")
        self.assertEqual(skipped, 1)  # "Ç": no key on the French PC keyboard
        self.assertEqual(len(reports), 12)  # press + release for six characters
        self.assertEqual(reports[1], hid.keyboard_report())

    def test_evdev_letters_are_positions(self):
        self.assertEqual(hid.EVDEV_TO_HID[16], 0x14)  # KEY_Q: top row, first letter
        self.assertEqual(hid.EVDEV_MODIFIERS[100], hid.RALT)  # AltGr


class FakeConfig:
    def __init__(self):
        self.keyfile = GLib.KeyFile()

    def alpha(self, name):
        return True

    def save(self):
        pass


class ControlTest(unittest.TestCase):
    def setUp(self):
        self.control = hid.Control(None, FakeConfig(), lambda: None, lambda: None)
        self.control.registered = True
        self.control.timer = -1  # no GLib timer: reports stay in the queue

    def reports(self):
        return [report for _path, report in self.control.queue]

    def test_modifier_keys_are_held(self):
        self.control.key(100, True)   # AltGr
        self.control.key(11, True)    # key 0 -> "@" with AltGr on AZERTY
        self.control.key(11, False)
        self.control.key(100, False)
        self.assertEqual(self.reports()[1], hid.keyboard_report(hid.RALT, [0x27]))
        self.assertEqual(self.reports()[-1], hid.keyboard_report())

    def test_unknown_key_is_ignored(self):
        self.assertFalse(self.control.key(999, True))
        self.assertEqual(self.reports(), [])

    def test_drag_keeps_button(self):
        self.control.button(hid.BUTTON_LEFT, True)
        self.control.move(10, 0)
        self.assertEqual(self.reports()[-1], hid.mouse_report(hid.BUTTON_LEFT, 10, 0))

    def test_default_size_and_setting(self):
        self.assertEqual(self.control.size(), (400, 870))
        self.control.set_size(500, 1000)
        self.assertEqual(self.control.size(), (500, 1000))

    def test_nothing_sent_when_not_published(self):
        self.control.registered = False
        self.assertFalse(self.control.move(5, 5))


class MirrorOptionsTest(unittest.TestCase):
    def test_fluid_nvidia(self):
        args = mirror.build_args("Covalence (PC)", "fluid", "", False, "2560x1600", "nvidia")
        self.assertIn("-vsync", args)
        self.assertEqual(args[args.index("-s") + 1], "1920x1200@60")
        self.assertEqual(args[args.index("-vd") + 1], "nvh264dec")
        self.assertEqual(args[args.index("-fps") + 1], "60")

    def test_quality_software_rotated_fullscreen(self):
        args = mirror.build_args("X", "quality", "R", True, "", "software")
        self.assertNotIn("-vsync", args)
        self.assertNotIn("-s", args)
        self.assertIn("-avdec", args)
        self.assertEqual(args[args.index("-r") + 1], "R")
        self.assertIn("-fs", args)

    def test_pick_decoder(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("libgstnvcodec.so", "libgstva.so"):
                open(os.path.join(tmp, name), "w").close()
            self.assertEqual(mirror.pick_decoder([tmp], cuda=True, render=True), "nvidia")
            self.assertEqual(mirror.pick_decoder([tmp], cuda=False, render=True), "vaapi")
            self.assertEqual(mirror.pick_decoder([tmp], cuda=False, render=False), "software")

    def test_options_are_checked(self):
        config = FakeConfig()
        m = mirror.Mirror(lambda: None, config)
        self.assertTrue(m.set_option("profile", "quality"))
        self.assertFalse(m.set_option("profile", "turbo"))
        self.assertTrue(m.set_option("fullscreen", "true"))
        self.assertEqual((m.option("profile"), m.option("fullscreen")), ("quality", True))


if __name__ == "__main__":
    unittest.main()
