# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Translations of the daemon and its helper windows (gettext domain "covalence").

The source strings are French; po/en.po holds the English translation (beta).
The language comes from [general] language in ~/.config/covalence/apps.conf:
"fr", "en" or "system" (default). "system" means French when the session
language is French, English otherwise. Logs are never translated.
"""

import gettext
import os

from gi.repository import GLib

DOMAIN = "covalence"
# Installed as <datadir>/covalence/covalenced/i18n.py: catalogs are in <datadir>/locale.
LOCALEDIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          os.pardir, os.pardir, "locale"))


def prefs_path():
    return os.path.join(GLib.get_user_config_dir(), "covalence", "apps.conf")


def chosen_language():
    """"fr", "en" or "system", as set in apps.conf."""
    keyfile = GLib.KeyFile()
    try:
        keyfile.load_from_file(prefs_path(), GLib.KeyFileFlags.NONE)
        value = keyfile.get_string("general", "language").strip()
    except GLib.Error:
        return "system"
    return value if value in ("fr", "en") else "system"


def language():
    """The language actually used: "fr" or "en"."""
    chosen = chosen_language()
    if chosen != "system":
        return chosen
    for name in GLib.get_language_names():
        if name in ("C", "POSIX"):
            continue
        return "fr" if name.startswith("fr") else "en"
    return "en"


def _load():
    lang = language()
    if lang == "fr":
        return gettext.NullTranslations()  # the source strings are French
    return gettext.translation(DOMAIN, LOCALEDIR, languages=[lang], fallback=True)


_translations = _load()


def reload():
    global _translations
    _translations = _load()


def _(message):
    return _translations.gettext(message)


def ngettext(singular, plural, n):
    return _translations.ngettext(singular, plural, n)


def pgettext(context, message):
    return _translations.pgettext(context, message)


def N_(message):
    return message
