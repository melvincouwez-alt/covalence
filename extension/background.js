// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
// Asks covalence-otp-host (native messaging) for the latest code on behalf of the pages.
// Chrome runs this file as a service worker, Firefox as a background script after compat.js.
if (typeof importScripts === "function") {
    importScripts("compat.js");
}

const HOST = "com.covalence.otp";

api.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (!message || message.type !== "latest") {
        return false;
    }
    api.runtime.sendNativeMessage(HOST, { type: "latest" }).then(
        (reply) => sendResponse(reply && typeof reply.code === "string" ? reply : { code: "" }),
        (error) => sendResponse({ code: "", error: String((error && error.message) || error) })
    );
    return true;  // the answer comes later
});
