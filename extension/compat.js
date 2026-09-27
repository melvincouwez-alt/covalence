// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
// One name for the WebExtension API: `browser` in Firefox, `chrome` in Chrome, Chromium and Edge.
// Both return promises in Manifest V3.
var api = (typeof browser !== "undefined" && browser.runtime) ? browser : chrome;
