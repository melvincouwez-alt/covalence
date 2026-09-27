// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
// Covalence (alpha): below a one-time code field, offer the code the iPhone just received.
// The code reaches the page only when the user clicks the pill; the pill itself sits in a
// closed shadow root the page cannot read.
(() => {
    const POLL_MS = 3000;          // while a code field has the focus and no code is known
    const POLL_FOR_MS = 180000;    // the daemon forgets codes after 3 minutes anyway
    const MAX_AGE = 180;

    // Words of a code field (name, id, placeholder, label…), and of fields that only look like one.
    const CODE_WORDS = /(one[-_ ]?time|otp|totp|2fa|mfa|verif|v[ée]rif|sms|code|token|passcode|\bpin\b|auth|s[ée]curit)/i;
    const NOT_CODE = /(post|zip|promo|coupon|voucher|gift|cadeau|discount|r[ée]duc|country|pays|area|phone|t[ée]l[ée]phone|captcha|iban|bic|swift|card|carte|cvc|cvv|crypto|expir|search|recherche|referral|parrain|e-?mail|pass(word)?$|mot de passe)/i;
    const TEXT_TYPES = new Set(["", "text", "tel", "number"]);

    let field = null;        // the code field with the focus
    let host = null;         // the pill's element in the page
    let shown = "";          // the code on the pill
    let used = new Set();    // codes already filled in on this page
    let timer = 0;
    let pollUntil = 0;

    function describe(input) {
        const parts = [input.name, input.id, input.placeholder, input.getAttribute("aria-label"),
                       input.getAttribute("autocomplete")];
        if (input.labels) {
            for (const label of input.labels) {
                parts.push(label.textContent);
            }
        }
        return parts.filter(Boolean).join(" ");
    }

    function isCodeField(input) {
        if (!(input instanceof HTMLInputElement) || input.disabled || input.readOnly) {
            return false;
        }
        const autocomplete = (input.getAttribute("autocomplete") || "").toLowerCase();
        if (autocomplete.split(/\s+/).includes("one-time-code")) {
            return true;
        }
        if (!TEXT_TYPES.has((input.getAttribute("type") || "").toLowerCase())) {
            return false;
        }
        const words = describe(input);
        return CODE_WORDS.test(words) && !NOT_CODE.test(words);
    }

    /* Split fields (one digit per box): the boxes of the same group, in order. */
    function digitBoxes(input) {
        if (input.maxLength !== 1) {
            return null;
        }
        const scope = input.form || input.parentElement?.parentElement || document;
        const boxes = [...scope.querySelectorAll("input")].filter(
            (box) => box.maxLength === 1 && TEXT_TYPES.has((box.getAttribute("type") || "").toLowerCase()));
        return boxes.length >= 4 ? boxes : null;
    }

    function setValue(input, value) {
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
        setter.call(input, value);  // frameworks (React…) watch the native setter
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function fill(input, code) {
        const boxes = digitBoxes(input);
        if (boxes) {
            boxes.slice(0, code.length).forEach((box, i) => setValue(box, code[i]));
            boxes[Math.min(code.length, boxes.length) - 1].focus();
        } else {
            setValue(input, code);
        }
        used.add(code);
    }

    function hide() {
        if (host) {
            host.remove();
            host = null;
        }
        shown = "";
    }

    function place() {
        if (!host || !field) {
            return;
        }
        const rect = field.getBoundingClientRect();
        host.style.left = `${Math.max(4, rect.left)}px`;
        host.style.top = `${rect.bottom + 6}px`;
    }

    function show(code) {
        if (shown === code && host) {
            return;
        }
        hide();
        shown = code;
        host = document.createElement("covalence-code");
        host.style.cssText = "position:fixed;z-index:2147483647;left:0;top:0;";
        const root = host.attachShadow({ mode: "closed" });
        const style = document.createElement("style");
        style.textContent = `
            button {
                font: 500 13px system-ui, sans-serif;
                padding: 6px 12px;
                border-radius: 9999px;
                border: 1px solid rgba(0, 0, 0, 0.15);
                background: #ffffff;
                color: #1a1a1a;
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.18);
                cursor: pointer;
                display: flex;
                align-items: center;
                gap: 6px;
            }
            button:hover { background: #f2f2f2; }
            img { width: 16px; height: 16px; }
            @media (prefers-color-scheme: dark) {
                button { background: #2b2b2b; color: #f2f2f2; border-color: rgba(255, 255, 255, 0.15); }
                button:hover { background: #363636; }
            }`;
        const button = document.createElement("button");
        button.type = "button";
        button.title = api.i18n.getMessage("pillTitle");
        const icon = document.createElement("img");
        icon.src = api.runtime.getURL("icons/icon-32.png");
        icon.alt = "";
        button.append(icon, document.createTextNode(api.i18n.getMessage("pill", [code])));
        // mousedown would take the focus from the field (and blur would hide the pill).
        button.addEventListener("mousedown", (event) => event.preventDefault());
        button.addEventListener("click", (event) => {
            event.preventDefault();
            const target = field;
            hide();
            if (target) {
                fill(target, code);
            }
        });
        root.append(style, button);
        document.documentElement.append(host);
        place();
    }

    function ask() {
        timer = 0;
        if (!field) {
            return;
        }
        let request;
        try {
            request = api.runtime.sendMessage({ type: "latest" });
        } catch (error) {
            return;  // extension reloaded: this page's script is orphaned
        }
        request.then((reply) => {
            if (!field) {
                return;
            }
            const code = reply && typeof reply.code === "string" ? reply.code : "";
            if (/^\d{4,8}$/.test(code) && reply.age <= MAX_AGE && !used.has(code)) {
                show(code);
            } else if (Date.now() < pollUntil) {
                timer = setTimeout(ask, POLL_MS);
            }
        }, () => {});
    }

    function start(input) {
        stop();
        field = input;
        pollUntil = Date.now() + POLL_FOR_MS;
        ask();
    }

    function stop() {
        if (timer) {
            clearTimeout(timer);
            timer = 0;
        }
        field = null;
        hide();
    }

    document.addEventListener("focusin", (event) => {
        const target = event.composedPath ? event.composedPath()[0] : event.target;
        if (isCodeField(target)) {
            if (target !== field) {
                start(target);
            }
        } else if (field) {
            stop();
        }
    }, true);
    document.addEventListener("focusout", (event) => {
        if (event.target === field) {
            // A click elsewhere on the page; the pill's own clicks keep the focus.
            setTimeout(() => {
                if (field && document.activeElement !== field) {
                    stop();
                }
            }, 150);
        }
    }, true);
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && host) {
            hide();
        }
    }, true);
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);

    // A code field focused before the script ran (autofocus).
    if (document.activeElement && isCodeField(document.activeElement)) {
        start(document.activeElement);
    }
})();
