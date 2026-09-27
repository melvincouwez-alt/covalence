# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Download the official rclone build, only when the user asks for it.

iCloud Drive and iCloud Photos need rclone 1.69 or later, newer than some
distributions ship (Ubuntu 24.04, base of elementary OS 8, has 1.60). Covalence
does not redistribute rclone (MIT licence, (c) Nick Craig-Wood and the rclone
contributors): on a click, this module fetches the release published on
https://downloads.rclone.org, checks the archive against the release's
SHA256SUMS (both over HTTPS) and installs the single binary in
~/.local/libexec/covalence/rclone, readable by the user only.

Run as `covalenced --fetch-rclone`: prints "progress N" lines (0 to 100), then
"ok VERSION"; errors go to stderr with exit status 1.
"""

import hashlib
import os
import platform
import re
import sys
import tempfile
import urllib.request
import zipfile

from .i18n import _

BASE = "https://downloads.rclone.org"
PRIVATE_RCLONE = os.path.join(os.path.expanduser("~"), ".local", "libexec", "covalence", "rclone")
MINIMUM = (1, 69)
ARCHES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
CHUNK = 256 * 1024


class FetchError(Exception):
    pass


def arch():
    name = ARCHES.get(platform.machine().lower())
    if name is None:
        raise FetchError(_("architecture non prise en charge : {arch}").format(arch=platform.machine()))
    return name


def _get(url, opener, timeout=30):
    if not url.startswith("https://"):
        raise FetchError(_("adresse non sécurisée refusée"))
    return opener(url, timeout=timeout)


def latest_version(opener=urllib.request.urlopen):
    with _get(f"{BASE}/version.txt", opener) as response:
        text = response.read(200).decode("ascii", "replace")
    match = re.match(r"rclone v(\d+)\.(\d+)\.(\d+)", text.strip())
    if not match:
        raise FetchError(_("version de rclone illisible"))
    version = tuple(int(part) for part in match.groups())
    if version[:2] < MINIMUM:
        raise FetchError(_("la dernière version publiée est trop ancienne"))
    return "v%d.%d.%d" % version


def expected_sha256(sums, filename):
    """The hash of filename in a (possibly PGP clear-signed) SHA256SUMS text."""
    for line in sums.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[1].lstrip("*") == filename and re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            return parts[0]
    raise FetchError(_("{file} absent de SHA256SUMS").format(file=filename))


def fetch(dest=PRIVATE_RCLONE, progress=lambda percent: None, opener=urllib.request.urlopen):
    """Download, verify and install rclone; returns the installed version."""
    version = latest_version(opener)
    name = f"rclone-{version}-linux-{arch()}"
    with _get(f"{BASE}/{version}/SHA256SUMS", opener) as response:
        sums = response.read(1 << 20).decode("utf-8", "replace")
    want = expected_sha256(sums, name + ".zip")

    directory = os.path.dirname(dest)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory) as tmp:
        archive = os.path.join(tmp, name + ".zip")
        digest = hashlib.sha256()
        with _get(f"{BASE}/{version}/{name}.zip", opener, timeout=60) as response, \
                open(archive, "wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if total:
                    progress(min(99, done * 100 // total))
        if digest.hexdigest() != want:
            raise FetchError(_("l'empreinte SHA-256 du fichier téléchargé ne correspond pas"))
        with zipfile.ZipFile(archive) as bundle:
            try:
                data = bundle.read(f"{name}/rclone")
            except KeyError as e:
                raise FetchError(_("binaire rclone absent de l'archive")) from e
        binary = os.path.join(tmp, "rclone")
        with open(binary, "wb") as out:
            out.write(data)
        os.chmod(binary, 0o700)
        os.replace(binary, dest)
    progress(100)
    return version


def main():
    try:
        version = fetch(progress=lambda percent: print(f"progress {percent}", flush=True))
    except (FetchError, OSError, zipfile.BadZipFile) as e:
        print(f"rclone : {e}", file=sys.stderr)
        return 1
    print(f"ok {version}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
