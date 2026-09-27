# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""System components Covalence relies on, and the Debian package that brings each one.

Run as `covalenced --check-components`: prints one line per missing component,
"package<TAB>label<TAB>installable" (installable is 1 when the distribution can
provide it through PackageKit, 0 when only a newer system can, 2 when Covalence
can download it on request: rclone, see rclone_fetch.py). No output means
nothing is missing.

This must work when the daemon itself cannot start (a typelib is missing), so it
only imports gi inside a try block and probes files and typelibs, never dpkg:
a component also counts as present when it was installed another way.
"""

import glob
import os
import re
import shutil
import subprocess
import sys

try:  # translations need GLib, which may be the missing component
    from .i18n import N_, _
except ImportError:
    def _(message):
        return message
    N_ = _

PRIVATE_RCLONE = os.path.join(os.path.expanduser("~"), ".local", "libexec", "covalence", "rclone")
# iCloud Drive and iCloud Photos: rclone's iclouddrive backend needs 1.69 or later.
RCLONE_MIN = (1, 69)
DOWNLOADABLE = 2
PRIVATE_OBEXD = os.path.join(os.path.expanduser("~"), ".local", "libexec", "covalence", "obexd")
# org.pipewire.Telephony (calls through the iPhone) first shipped in PipeWire 1.4.0.
PIPEWIRE_MIN = (1, 4, 0)

TYPELIBS = (
    ("EDataServer", "1.2", "gir1.2-edataserver-1.2", N_("Comptes iCloud (Evolution Data Server)")),
    ("EBook", "1.2", "gir1.2-ebook-1.2", N_("Contacts iCloud")),
    ("EBookContacts", "1.2", "gir1.2-ebookcontacts-1.2", N_("Fiches de contact iCloud")),
    ("Secret", "1", "gir1.2-secret-1", N_("Trousseau (mots de passe)")),
)


def _any(patterns):
    return any(glob.glob(pattern) for pattern in patterns)


def _pipewire_version():
    try:
        out = subprocess.run(["pipewire", "--version"], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"Linked with libpipewire (\d+)\.(\d+)\.(\d+)", out) or re.search(r"(\d+)\.(\d+)\.(\d+)", out)
    return tuple(int(part) for part in match.groups()) if match else None


def _rclone_version(path):
    try:
        out = subprocess.run([path, "version"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.match(r"rclone v(\d+)\.(\d+)", out)
    return (int(match.group(1)), int(match.group(2))) if match else None


def rclone_ok():
    for path in (shutil.which("rclone"), PRIVATE_RCLONE):
        if path and os.access(path, os.X_OK) and (_rclone_version(path) or (0, 0)) >= RCLONE_MIN:
            return True
    return False


def missing():
    """[(package, label, installable)] for every component that is not there."""
    found = []

    if not _any(["/usr/sbin/bluetoothd", "/usr/libexec/bluetooth/bluetoothd", "/usr/lib/bluetooth/bluetoothd"]):
        found.append(("bluez", _("Bluetooth (BlueZ)"), True))
    # obexd: messages and contacts. Covalence's private copy (README) also does the job.
    if not _any(["/usr/libexec/bluetooth/obexd", "/usr/lib/bluetooth/obexd"]) \
            and not os.access(PRIVATE_OBEXD, os.X_OK):
        found.append(("bluez-obexd", _("Messages et contacts par Bluetooth (obexd)"), True))

    try:
        import gi
        repository = gi.Repository.get_default()
    except (ImportError, AttributeError):
        found.append(("python3-gi", _("Liaison Python de GLib (PyGObject)"), True))
        repository = None
    if repository is not None:
        for namespace, version, package, label in TYPELIBS:
            if version not in repository.enumerate_versions(namespace):
                found.append((package, _(label), True))

    if shutil.which("secret-tool") is None:
        found.append(("libsecret-tools", _("Outil du trousseau (secret-tool)"), True))
    if not _any(["/usr/libexec/evolution-source-registry",
                 "/usr/libexec/evolution-data-server/evolution-source-registry",
                 "/usr/lib/evolution/evolution-source-registry"]):
        found.append(("evolution-data-server", _("Evolution Data Server"), True))
    if shutil.which("fusermount3") is None:
        found.append(("fuse3", _("Montage d'iCloud Drive et iCloud Photos (FUSE)"), True))

    if not rclone_ok():
        found.append(("rclone", _("iCloud Drive et iCloud Photos (rclone 1.69 ou plus récent)"),
                      DOWNLOADABLE))

    version = _pipewire_version()
    if version is None:
        found.append(("pipewire", _("Son (PipeWire)"), True))
    elif version < PIPEWIRE_MIN:
        found.append(("pipewire", _("PipeWire %d.%d ou plus récent pour les appels (installé : %d.%d)")
                      % (PIPEWIRE_MIN[:2] + version[:2]), False))
    if not _any(["/usr/lib/*/spa-0.2/bluez5/libspa-bluez5.so", "/usr/lib/spa-0.2/bluez5/libspa-bluez5.so",
                 "/usr/lib64/spa-0.2/bluez5/libspa-bluez5.so"]):
        found.append(("libspa-0.2-bluetooth", _("Son et appels par Bluetooth (PipeWire)"), True))
    if shutil.which("wireplumber") is None:
        found.append(("wireplumber", _("Gestion des périphériques audio (WirePlumber)"), True))
    return found


def main():
    for package, label, installable in missing():
        state = installable if installable == DOWNLOADABLE else (1 if installable else 0)
        print(f"{package}\t{label}\t{state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
