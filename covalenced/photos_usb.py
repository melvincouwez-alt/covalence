# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Photos: import the iPhone's photos over a USB cable (libimobiledevice).

The iPhone is found with idevice_id, paired with idevicepair (the user taps
"Trust" on the phone), its camera roll mounted read-only with ifuse, then the
photos and videos of DCIM are copied to ~/Images/iPhone. A file already
imported (same name and same size, remembered in .covalence-import.json in the
destination) is skipped. HEIC photos can be converted to JPEG with heif-convert.

Nothing is ever written to the iPhone. Logs record counts and states only.
"""

import json
import os
import shutil
import subprocess
import tempfile
import threading

from gi.repository import GLib

from .util import log

TOOLS = (("idevice_id", "libimobiledevice-utils"), ("idevicepair", "libimobiledevice-utils"),
         ("ideviceinfo", "libimobiledevice-utils"), ("ifuse", "ifuse"),
         ("fusermount3", "fuse3"))
EXTENSIONS = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".gif", ".mov", ".mp4", ".m4v",
              ".dng", ".webp"}
MANIFEST = ".covalence-import.json"
TYPES = {"missing": "as", "heic_tool": "b", "device": "s", "udid": "s", "paired": "b",
         "state": "s", "total": "u", "done": "u", "imported": "u", "skipped": "u",
         "error": "s", "folder": "s", "convert_heic": "b"}


def pictures_folder():
    base = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) \
        or os.path.join(os.path.expanduser("~"), "Pictures")
    return os.path.join(base, "iPhone")


def missing_packages():
    return sorted({package for tool, package in TOOLS if shutil.which(tool) is None})


def _run(argv, timeout=20):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return done.returncode, (done.stdout or "") + (done.stderr or "")
    except (OSError, subprocess.SubprocessError) as error:
        return -1, str(error)


def media_files(root):
    """[(path relative to root, size)] of the photos and videos under root/DCIM, sorted."""
    found = []
    dcim = os.path.join(root, "DCIM")
    for folder, _dirs, names in os.walk(dcim):
        for name in names:
            if os.path.splitext(name)[1].lower() in EXTENSIONS:
                path = os.path.join(folder, name)
                try:
                    found.append((os.path.relpath(path, root), os.path.getsize(path)))
                except OSError:
                    continue
    return sorted(found)


def load_manifest(folder):
    try:
        with open(os.path.join(folder, MANIFEST), encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError, TypeError):
        return set()


def save_manifest(folder, keys):
    path = os.path.join(folder, MANIFEST)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(sorted(keys), f)
    os.replace(path + ".tmp", path)


def key_of(name, size):
    return f"{os.path.basename(name)}|{size}"


def target_for(folder, name, size, convert):
    """Where a file goes, or None when a file of that name and size is already there."""
    base, ext = os.path.splitext(os.path.basename(name))
    if convert and ext.lower() in (".heic", ".heif"):
        ext = ".jpg"
    path, n = os.path.join(folder, base + ext), 2
    while os.path.exists(path):
        if not convert and os.path.getsize(path) == size:
            return None
        path = os.path.join(folder, f"{base}_{n}{ext}")
        n += 1
    return path


def import_files(root, folder, convert, progress, cancelled):
    """Copy the media of root/DCIM to folder. Returns (imported, skipped)."""
    os.makedirs(folder, exist_ok=True)
    done_keys = load_manifest(folder)
    files = media_files(root)
    imported = skipped = 0
    converter = shutil.which("heif-convert") if convert else None
    for index, (relative, size) in enumerate(files):
        if cancelled():
            break
        key = key_of(relative, size)
        is_heic = os.path.splitext(relative)[1].lower() in (".heic", ".heif")
        target = None if key in done_keys else \
            target_for(folder, relative, size, bool(converter and is_heic))
        if target is None:
            skipped += 1
        else:
            source = os.path.join(root, relative)
            part = target + ".part"
            try:
                if converter and is_heic:
                    code, _out = _run([converter, "-q", "92", source, part + ".jpg"], timeout=120)
                    if code != 0:
                        raise OSError("heif-convert")
                    os.replace(part + ".jpg", target)
                else:
                    shutil.copyfile(source, part)
                    shutil.copystat(source, part)
                    os.replace(part, target)
                imported += 1
                done_keys.add(key)
            except OSError:
                for leftover in (part, part + ".jpg"):
                    if os.path.exists(leftover):
                        os.unlink(leftover)
                skipped += 1
        progress(index + 1, len(files), imported, skipped)
        if (index + 1) % 50 == 0:
            save_manifest(folder, done_keys)
    save_manifest(folder, done_keys)
    return imported, skipped


class PhotosUsb:
    def __init__(self, config, notifier, changed):
        self.config = config
        self.notifier = notifier
        self.changed = changed
        self.device = ""
        self.udid = ""
        self.paired = False
        self.state_name = "idle"
        self.total = self.done = self.imported = self.skipped = 0
        self.error = ""
        self.busy = False
        self.stop_requested = False

    @property
    def convert_heic(self):
        return self.config.boolean("photos", "convert_heic", False)

    def state(self):
        return {"missing": missing_packages(), "heic_tool": shutil.which("heif-convert") is not None,
                "device": self.device, "udid": self.udid, "paired": self.paired,
                "state": self.state_name, "total": self.total, "done": self.done,
                "imported": self.imported, "skipped": self.skipped, "error": self.error,
                "folder": pictures_folder(), "convert_heic": self.convert_heic}

    def set_convert_heic(self, enabled):
        self.config.set_boolean("photos", "convert_heic", bool(enabled))
        self.changed()

    def _background(self, job, done):
        def run():
            result = job()
            GLib.idle_add(lambda: done(result) and False)
        threading.Thread(target=run, name="covalence-photos-usb", daemon=True).start()

    # --- the device -----------------------------------------------------------------------------

    def refresh(self):
        """Look for an iPhone on USB (cheap: a few short commands in a thread)."""
        if self.busy or missing_packages():
            self.changed()
            return

        def job():
            code, out = _run(["idevice_id", "-l"])
            udids = [line.strip() for line in out.splitlines() if code == 0 and line.strip()]
            if not udids:
                return "", "", False
            udid = udids[0]
            _code, name = _run(["ideviceinfo", "-u", udid, "-k", "DeviceName"])
            code, _out = _run(["idevicepair", "-u", udid, "validate"])
            name = name.strip().splitlines()[0] if name.strip() and _code == 0 else "iPhone"
            return udid, name, code == 0

        def done(result):
            self.udid, self.device, self.paired = result
            if self.state_name in ("idle", "unplugged", "done", "error") and not self.busy:
                self.state_name = "ready" if self.udid else "unplugged"
            self.changed()

        self._background(job, done)

    def pair(self):
        """Ask the iPhone to trust this PC; the user taps Trust and enters the code."""
        if self.busy or not self.udid:
            return
        self.busy, self.state_name, self.error = True, "pairing", ""
        self.changed()
        udid = self.udid

        def job():
            for _attempt in range(30):  # about a minute to tap Trust on the iPhone
                code, out = _run(["idevicepair", "-u", udid, "pair"])
                if code == 0:
                    return True
                if "trust" not in out.lower() and "passcode" not in out.lower() \
                        and "pairing_dialog" not in out.lower():
                    return False
                GLib.usleep(2 * 1000 * 1000)
            return False

        def done(ok):
            self.busy = False
            self.paired = ok
            self.state_name = "ready" if ok else "error"
            self.error = "" if ok else "pairing"
            log(f"photos : appairage USB {'réussi' if ok else 'échoué'}")
            self.changed()

        self._background(job, done)

    def import_photos(self):
        if self.busy or not self.udid or not self.paired:
            return False
        self.busy, self.stop_requested = True, False
        self.state_name, self.error = "importing", ""
        self.total = self.done = self.imported = self.skipped = 0
        self.changed()
        udid, convert, folder = self.udid, self.convert_heic, pictures_folder()

        def progress(done, total, imported, skipped):
            GLib.idle_add(lambda: self._progress(done, total, imported, skipped) and False)

        def job():
            mount = tempfile.mkdtemp(prefix="covalence-iphone-")
            try:
                code, _out = _run(["ifuse", "-u", udid, "-o", "ro", mount], timeout=30)
                if code != 0:
                    return None, "mount"
                try:
                    return import_files(mount, folder, convert, progress,
                                        lambda: self.stop_requested), ""
                finally:
                    _run(["fusermount3", "-u", mount])
            except OSError:
                return None, "copy"
            finally:
                try:
                    os.rmdir(mount)
                except OSError:
                    pass

        def done(result):
            counts, error = result
            self.busy = False
            if counts is None:
                self.state_name, self.error = "error", error
                log(f"photos : import impossible ({error})")
            else:
                self.imported, self.skipped = counts
                self.state_name = "done"
                log(f"photos : {self.imported} importée(s), {self.skipped} déjà là")
            self.changed()

        self._background(job, done)
        return True

    def _progress(self, done, total, imported, skipped):
        self.done, self.total, self.imported, self.skipped = done, total, imported, skipped
        self.changed()

    def cancel(self):
        self.stop_requested = True
