# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Browser integration (alpha): one-time codes offered next to the code field of a web page.

Two halves:
- install() writes the native messaging manifest "com.covalence.otp" for each browser
  found (Chrome, Chromium, Edge, Firefox), pointing at the covalence-otp-host program;
- main() is that program: the browser starts it for each request from the Covalence
  extension, it asks the daemon for the latest code (LatestCode "browser") and answers.

`covalenced --install-browser-host` runs install() from a terminal.
Flatpak and Snap browsers run the host inside their sandbox, out of reach of the
daemon: not supported (see docs/navigateurs.md).
"""

import json
import os
import shutil
import struct
import sys

HOST_NAME = "com.covalence.otp"
# The unpacked extension carries a "key" in manifest.json, so its id is the same everywhere.
CHROMIUM_ID = "bbnmajflfndmkepfcnmpabhmneoplfkk"
FIREFOX_ID = "otp@covalence.melvincouwez.github.io"
HOST_PROGRAM = "covalence-otp-host"

# Browser name, its settings folder (to know it is there), its commands, its manifest folder.
BROWSERS = [
    ("Google Chrome", ".config/google-chrome", ("google-chrome", "google-chrome-stable"),
     ".config/google-chrome/NativeMessagingHosts", "chromium"),
    ("Chromium", ".config/chromium", ("chromium", "chromium-browser"),
     ".config/chromium/NativeMessagingHosts", "chromium"),
    ("Microsoft Edge", ".config/microsoft-edge", ("microsoft-edge", "microsoft-edge-stable"),
     ".config/microsoft-edge/NativeMessagingHosts", "chromium"),
    ("Firefox", ".mozilla", ("firefox", "firefox-esr"),
     ".mozilla/native-messaging-hosts", "firefox"),
]


def host_path():
    """The installed covalence-otp-host, next to covalenced; COVALENCE_OTP_HOST in development."""
    override = os.environ.get("COVALENCE_OTP_HOST")
    if override:
        return os.path.abspath(override)
    here = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), HOST_PROGRAM)
    if os.access(here, os.X_OK):
        return here
    return shutil.which(HOST_PROGRAM) or ""


def manifest(kind, path):
    data = {"name": HOST_NAME, "description": "Covalence: one-time codes received by SMS",
            "path": path, "type": "stdio"}
    if kind == "firefox":
        data["allowed_extensions"] = [FIREFOX_ID]
    else:
        data["allowed_origins"] = [f"chrome-extension://{CHROMIUM_ID}/"]
    return data


def install(home=None, which=shutil.which):
    """Write the manifests for the browsers found; returns their names. Raises OSError."""
    home = home or os.path.expanduser("~")
    path = host_path()
    if not path:
        raise OSError(f"{HOST_PROGRAM} introuvable")
    installed = []
    for name, settings, commands, folder, kind in BROWSERS:
        present = os.path.isdir(os.path.join(home, settings)) or any(which(c) for c in commands)
        if not present:
            continue
        directory = os.path.join(home, folder)
        os.makedirs(directory, exist_ok=True)
        target = os.path.join(directory, HOST_NAME + ".json")
        with open(target + ".tmp", "w", encoding="utf-8") as out:
            json.dump(manifest(kind, path), out, indent=2)
            out.write("\n")
        os.replace(target + ".tmp", target)
        installed.append(name)
    return installed


# --- the native messaging host ----------------------------------------------------------------------

def _read(stream):
    header = stream.read(4)
    if len(header) < 4:
        return None
    size = struct.unpack("=I", header)[0]
    if size > 64 * 1024:
        return None
    return json.loads(stream.read(size).decode("utf-8"))


def _write(stream, data):
    raw = json.dumps(data).encode("utf-8")
    stream.write(struct.pack("=I", len(raw)))
    stream.write(raw)
    stream.flush()


def _latest_code():
    from gi.repository import Gio, GLib
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = bus.call_sync(
            "io.github.melvincouwez.Covalence.Daemon", "/io/github/melvincouwez/Covalence/Daemon",
            "io.github.melvincouwez.Covalence1", "LatestCodeFor", GLib.Variant("(s)", ("browser",)),
            GLib.VariantType("(suass)"), Gio.DBusCallFlags.NO_AUTO_START, 3000, None)
    except GLib.Error:
        return {"code": "", "age": 0, "error": "daemon"}
    code, age, domains, sender = reply.unpack()
    return {"code": code, "age": age, "domains": list(domains), "sender": sender}


def main():
    """One request, one answer: {"type": "latest"} ->
    {"code": "482913", "age": 12, "domains": ["example.com"], "sender": "Ma Banque"}."""
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    try:
        request = _read(stdin)
    except (ValueError, UnicodeDecodeError):
        request = None
    if not isinstance(request, dict) or request.get("type") != "latest":
        _write(stdout, {"code": "", "age": 0, "error": "request"})
        return 1
    _write(stdout, _latest_code())
    return 0


def install_main():
    """covalenced --install-browser-host"""
    try:
        installed = install()
    except OSError as error:
        print(f"Intégration navigateur non installée : {error}", file=sys.stderr)
        return 1
    if not installed:
        print("Aucun navigateur pris en charge trouvé (Chrome, Chromium, Edge, Firefox).")
        return 1
    print("Intégration navigateur installée pour : " + ", ".join(installed))
    print("Chargez ensuite l'extension : voir docs/navigateurs.md")
    return 0
