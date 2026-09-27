#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Build the Covalence browser extension for each browser family from one source.

extension/ itself is the Chromium build (Chrome, Chromium, Edge load it unpacked).
Firefox needs another manifest: no "key", a background script instead of a service
worker, and its add-on id. Output (default extension/out/):
  chromium/                         unpacked extension for Chrome, Chromium, Edge
  firefox/                          unpacked extension for Firefox (about:debugging)
  covalence-codes-firefox.xpi       the same, zipped (unsigned: Developer Edition/Nightly)
  LISEZMOI.md                       docs/navigateurs.md, the instructions

Usage: build.py [OUTPUT_DIR]; meson runs it at install time with --install DIR.
"""

import json
import os
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ["compat.js", "background.js", "content.js", "_locales", "icons"]
FIREFOX_ID = "otp@covalence.melvincouwez.github.io"
FIREFOX_MIN = "115.0"  # ESR with Manifest V3 background scripts and nativeMessaging


def firefox_manifest(manifest):
    manifest = dict(manifest)
    manifest.pop("key", None)
    manifest["background"] = {"scripts": ["compat.js", "background.js"]}
    manifest["browser_specific_settings"] = {
        "gecko": {"id": FIREFOX_ID, "strict_min_version": FIREFOX_MIN}}
    return manifest


def _copy(target, manifest):
    if os.path.isdir(target):
        shutil.rmtree(target)
    os.makedirs(target)
    for name in FILES:
        source = os.path.join(HERE, name)
        if os.path.isdir(source):
            shutil.copytree(source, os.path.join(target, name))
        else:
            shutil.copy2(source, target)
    with open(os.path.join(target, "manifest.json"), "w", encoding="utf-8") as out:
        json.dump(manifest, out, indent=2, ensure_ascii=False)
        out.write("\n")


def build(output):
    with open(os.path.join(HERE, "manifest.json"), encoding="utf-8") as source:
        manifest = json.load(source)
    _copy(os.path.join(output, "chromium"), manifest)
    firefox = os.path.join(output, "firefox")
    _copy(firefox, firefox_manifest(manifest))
    xpi = os.path.join(output, "covalence-codes-firefox.xpi")
    with zipfile.ZipFile(xpi, "w", zipfile.ZIP_DEFLATED) as archive:
        for folder, _dirs, files in os.walk(firefox):
            for name in sorted(files):
                path = os.path.join(folder, name)
                archive.write(path, os.path.relpath(path, firefox))
    guide = os.path.join(HERE, os.pardir, "docs", "navigateurs.md")
    if os.path.exists(guide):
        shutil.copy2(guide, os.path.join(output, "LISEZMOI.md"))
    return output


def main(argv):
    if argv[:1] == ["--install"]:
        # meson install: honour DESTDIR (packaging).
        target = argv[1]
        destdir = os.environ.get("DESTDIR", "")
        if destdir:
            target = os.path.join(destdir, os.path.relpath(target, os.sep))
        build(target)
        return 0
    output = argv[0] if argv else os.path.join(HERE, "out")
    print(build(output))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
