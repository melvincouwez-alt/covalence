# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Daemon settings, stored in ~/.config/covalence/covalenced.conf (GKeyFile)."""

import os

from gi.repository import GLib

from .util import log

MODULES = ("notifications", "media", "calls", "battery", "messages", "icloud")
# Experimental features, off by default: each one relies on iPhone behaviour not yet measured.
ALPHA = ("map_history", "mark_read", "ancs_actions", "pbap_favorites")


class Config:
    def __init__(self):
        self.dir = os.path.join(GLib.get_user_config_dir(), "covalence")
        self.path = os.path.join(self.dir, "covalenced.conf")
        self.keyfile = GLib.KeyFile()
        try:
            self.keyfile.load_from_file(self.path, GLib.KeyFileFlags.KEEP_COMMENTS)
        except GLib.Error:
            pass  # first run: defaults below

    def module_enabled(self, name):
        try:
            return self.keyfile.get_boolean("modules", name)
        except GLib.Error:
            return True

    def set_module_enabled(self, name, enabled):
        self.keyfile.set_boolean("modules", name, enabled)
        self.save()

    def modules(self):
        return {name: self.module_enabled(name) for name in MODULES}

    def alpha(self, name):
        return name in ALPHA and self.boolean("alpha", name, False)

    def set_alpha(self, name, enabled):
        self.keyfile.set_boolean("alpha", name, enabled)
        self.save()

    def alpha_features(self):
        return {name: self.alpha(name) for name in ALPHA}

    def set_boolean(self, group, key, value):
        self.keyfile.set_boolean(group, key, value)
        self.save()

    def boolean(self, group, key, default=False):
        try:
            return self.keyfile.get_boolean(group, key)
        except GLib.Error:
            return default

    def string(self, group, key, default=""):
        return self._string(group, key, default)

    def set_string(self, group, key, value):
        self.keyfile.set_string(group, key, value)
        self.save()

    def _string(self, group, key, default=""):
        try:
            return self.keyfile.get_string(group, key)
        except GLib.Error:
            return default

    @property
    def device_address(self):
        return self._string("device", "address")

    @device_address.setter
    def device_address(self, address):
        if address != self.device_address:
            self.keyfile.set_string("device", "address", address)
            self.save()

    def save(self):
        os.makedirs(self.dir, exist_ok=True)
        try:
            self.keyfile.save_to_file(self.path)
        except GLib.Error as error:
            log(f"réglages non enregistrés : {error.message}")
