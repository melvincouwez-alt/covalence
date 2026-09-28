# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Bounded download caches (artwork, app icons): files unused for a long time, and the
least recently used beyond a count, are removed. A file is "used" when its mtime is
refreshed with touch()."""

import os
import time


def touch(path):
    try:
        os.utime(path)
    except OSError:
        pass


def prune(directory, max_files, max_age_days):
    """Remove old files first, then the least recently used beyond max_files.
    Returns how many were removed; never raises."""
    try:
        entries = []
        with os.scandir(directory) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False):
                    entries.append((entry.stat(follow_symlinks=False).st_mtime, entry.path))
    except OSError:
        return 0
    entries.sort(reverse=True)  # most recently used first
    limit = time.time() - max_age_days * 86400
    removed = 0
    for index, (mtime, path) in enumerate(entries):
        if index >= max_files or mtime < limit:
            try:
                os.unlink(path)
                removed += 1
            except OSError:
                pass
    return removed
