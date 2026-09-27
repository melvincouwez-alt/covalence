# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Apple Media Service client: what the iPhone is playing, and remote control.

The PC registers for player, queue and track attributes on Entity Update and
sends commands through Remote Command. State is kept here and exposed as an
MPRIS player by mpris.py.
"""

import time

from gi.repository import GLib

from .gatt import GattClient
from .util import log

SERVICE = "89d3502b-0f36-433a-8ef4-c502ad55f8dc"
REMOTE_COMMAND = "9b3c81d8-57b1-4a8a-b8df-0e56f7ca51c2"
ENTITY_UPDATE = "2f7cabce-808d-411f-9a0c-bb92ba96c102"
ENTITY_ATTRIBUTE = "c6b2f38c-23ab-46d8-a6ab-a3a870bbd5d7"

ENTITY_PLAYER, ENTITY_QUEUE, ENTITY_TRACK = 0, 1, 2
PLAYER_NAME, PLAYER_PLAYBACK_INFO, PLAYER_VOLUME = 0, 1, 2
QUEUE_INDEX, QUEUE_COUNT, QUEUE_SHUFFLE, QUEUE_REPEAT = 0, 1, 2, 3
TRACK_ARTIST, TRACK_ALBUM, TRACK_TITLE, TRACK_DURATION = 0, 1, 2, 3
FLAG_TRUNCATED = 1

(CMD_PLAY, CMD_PAUSE, CMD_TOGGLE, CMD_NEXT, CMD_PREVIOUS, CMD_VOLUME_UP, CMD_VOLUME_DOWN,
 CMD_ADVANCE_REPEAT, CMD_ADVANCE_SHUFFLE, CMD_SKIP_FORWARD, CMD_SKIP_BACKWARD) = range(11)

PLAYBACK_STATES = {0: "Paused", 1: "Playing", 2: "Playing", 3: "Playing"}
SHUFFLE = {0: False, 1: True, 2: True}  # off, one, all
REPEAT = {0: "None", 1: "Track", 2: "Playlist"}  # off, one, all


def _float(text, default=0.0):
    try:
        return float(text)
    except ValueError:
        return default


class AmsClient(GattClient):
    def __init__(self, bus, chars, on_change):
        super().__init__(bus, chars, "AMS")
        self.on_change = on_change  # callable(set of changed keys)
        self.supported = set()
        self.state = {
            "player": "", "status": "Stopped", "rate": 0.0, "elapsed": 0.0, "stamp": 0.0, "wall": 0.0,
            "volume": 0.0, "shuffle": False, "repeat": "None",
            "title": "", "artist": "", "album": "", "duration": 0.0, "track_serial": 0,
        }

    def start(self):
        # Registering before Entity Update notifications are on gets ATT error 0xA0
        # (AMS "Invalid State"): wait for both subscriptions first.
        self.attempts = 0
        self.subscribe((REMOTE_COMMAND, ENTITY_UPDATE), then=self._register)

    def _register(self):
        self.attempts += 1
        self.failed = False
        # One registration per entity, sent in sequence by the write queue.
        self.write(ENTITY_UPDATE, bytes([ENTITY_PLAYER, PLAYER_NAME, PLAYER_PLAYBACK_INFO,
                                         PLAYER_VOLUME]))
        self.write(ENTITY_UPDATE, bytes([ENTITY_QUEUE, QUEUE_SHUFFLE, QUEUE_REPEAT]))
        self.write(ENTITY_UPDATE, bytes([ENTITY_TRACK, TRACK_ARTIST, TRACK_ALBUM, TRACK_TITLE,
                                         TRACK_DURATION]), then=self._registered)

    def _registered(self):
        if not self.failed:
            log("AMS : suivi du lecteur de l'iPhone")

    def on_request_failed(self):
        # A refused registration (the iPhone was not ready): try again a little later.
        if getattr(self, "current_uuid", None) == ENTITY_UPDATE and getattr(self, "attempts", 0) \
                and not getattr(self, "failed", False) and self.attempts < 3:
            self.failed = True
            self.queue = [q for q in self.queue if q[0] != ENTITY_UPDATE]
            GLib.timeout_add_seconds(3 * self.attempts, lambda: self._register() and False)

    def on_value(self, path, value):
        uuid = self.uuid_of(path)
        if uuid == REMOTE_COMMAND:
            self.supported = set(value)
            self.on_change({"commands"})
        elif uuid == ENTITY_UPDATE and len(value) >= 3:
            entity, attribute, flags = value[0], value[1], value[2]
            text = value[3:].decode("utf-8", "replace")
            if flags & FLAG_TRUNCATED:
                self._read_full(entity, attribute)
            self._apply(entity, attribute, text)

    def _read_full(self, entity, attribute):
        if ENTITY_ATTRIBUTE not in self.chars:
            return
        self.write(ENTITY_ATTRIBUTE, bytes([entity, attribute]), then=lambda: self.read(
            ENTITY_ATTRIBUTE,
            lambda data: self._apply(entity, attribute, data.decode("utf-8", "replace"))))

    def _apply(self, entity, attribute, text):
        s, changed = self.state, set()
        if entity == ENTITY_PLAYER:
            if attribute == PLAYER_NAME:
                s["player"] = text
                changed.add("identity")
            elif attribute == PLAYER_PLAYBACK_INFO:
                parts = (text.split(",") + ["", "", ""])[:3]
                state = int(_float(parts[0], 0))
                s["status"] = PLAYBACK_STATES.get(state, "Paused") if text else "Stopped"
                s["rate"] = _float(parts[1])
                s["elapsed"] = _float(parts[2])
                s["stamp"] = time.monotonic()
                s["wall"] = time.time()
                changed.add("playback")
            elif attribute == PLAYER_VOLUME:
                s["volume"] = _float(text)
                changed.add("volume")
        elif entity == ENTITY_QUEUE:
            if attribute == QUEUE_SHUFFLE:
                s["shuffle"] = SHUFFLE.get(int(_float(text, 0)), False)
                changed.add("shuffle")
            elif attribute == QUEUE_REPEAT:
                s["repeat"] = REPEAT.get(int(_float(text, 0)), "None")
                changed.add("repeat")
        elif entity == ENTITY_TRACK:
            key = {TRACK_ARTIST: "artist", TRACK_ALBUM: "album", TRACK_TITLE: "title"}.get(attribute)
            if key:
                s[key] = text
            elif attribute == TRACK_DURATION:
                s["duration"] = _float(text)
            if attribute == TRACK_TITLE:
                s["track_serial"] += 1
            changed.add("metadata")
        if changed:
            self.on_change(changed)

    def position(self):
        """Current position in seconds, extrapolated from the last playback info."""
        s = self.state
        if s["status"] != "Playing":
            return s["elapsed"]
        return s["elapsed"] + s["rate"] * (time.monotonic() - s["stamp"])

    def command(self, command_id):
        if self.supported and command_id not in self.supported:
            return False
        self.write(REMOTE_COMMAND, bytes([command_id]))
        return True
