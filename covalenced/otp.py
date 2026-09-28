# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""One-time codes received by SMS ("Votre code de vérification est 482913").

detect() finds the code the way iOS suggests it above the keyboard: a word such as
"code", "OTP" or "vérification" in the text, and a group of 4 to 8 digits (maybe
split by one space or dash) that is not an amount, a date, a time or a phone number.
When several groups qualify, the one closest to the keyword wins.

The code itself never goes to the logs. OneTimeCodes keeps the latest one in memory
for a few minutes: the Covalence app copies it, the browser extension offers it.

Domain-bound codes (the format iOS and Android autofill use): a last line
"@example.com #482913", optionally followed by "%other.example" for a code used
inside another site's frame. bound_domains() reads those names: the browser
extension fills such a code by itself on that site only, and never offers it on
another one (a phishing page asking for the bank's code gets nothing).
"""

import re
import time
import unicodedata

KEEP_SECONDS = 180

# Case-folded words that announce a code (French and English).
_KEYWORD = re.compile(
    r"\b(?:codes?(?! (?:postal|promo|promotionnel|de réduction|réduction|avantage|client|"
    r"parrain|parrainage|cadeau|wifi|wi-fi))|otp|passcode|pin|2fa|mfa|v[ée]rification|verify|verification|"
    r"authentification|authentication|identification|confirmation|validation|"
    r"s[ée]curit[ée]|security|usage unique|one[- ]time|mot de passe temporaire|"
    r"temporary password|login|connexion|sign[- ]in)\b")

# 4 to 8 digits, or two groups of 3-4 digits split by one space or dash ("482 913").
# Not part of a longer number, a word, a decimal, a date (12/10/2026, 12.10.2026),
# a time (14:30) or a sign-led number (+33…, -5).
_CANDIDATE = re.compile(
    r"(?<![\w.,/€$£+])(?<!\d:)(?<!\d-)(?<!\d )"
    r"(\d{3,4}[ \-]\d{3,4}|\d{4,8})"
    r"(?![\w/€$£])(?![.,:]\d)(?!\s?\d)(?![ \-]\d)")

# What follows or leads an amount, a duration or a quantity: not a code.
_UNIT_AFTER = re.compile(
    r"\s?(?:€|eur\b|euros?\b|\$|usd\b|£|%|h\b|min\b|minutes?\b|km\b|kg\b|go\b|mo\b|gb\b|mb\b|"
    r"points?\b|pts\b|jours?\b|days?\b|ans?\b|years?\b)")
_LEAD_BEFORE = re.compile(
    r"(?:[€$£] ?$|(?:montant|amount|total|stop au|stop to|stop|appelez le|appelez|call|au|to|"
    r"tél\.?|tel\.?|n°|numéro|number|réf\.?|ref\.?|référence|reference|commande|order|"
    r"dossier|colis|suivi|tracking|facture|invoice|contrat|client|postal)\s*:?\s*$)")

_SPACES = re.compile(r"[\s   ]+")

_BOUND = re.compile(r"(?:^|\s)@([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}"
                    r"[a-z0-9])?)+)\s+#([0-9]{4,10})(?:\s+%([a-z0-9.-]+))?\s*$", re.IGNORECASE)


def bound_domains(text, code):
    """Domains the SMS binds this code to ("@example.com #482913"), lower case; [] if none."""
    last = (text or "").strip().splitlines()[-1:] or [""]
    found = _BOUND.search(last[0])
    if not found or found.group(2) != code:
        return []
    return [d.lower().rstrip(".") for d in (found.group(1), found.group(3)) if d]


def _clean(text):
    text = unicodedata.normalize("NFC", text or "")
    return _SPACES.sub(" ", text).strip()


def detect(text):
    """The one-time code in an SMS, digits only, or None."""
    text = _clean(text)
    if not text or len(text) > 600:
        return None
    folded = text.casefold()
    keywords = [m.start() for m in _KEYWORD.finditer(folded)]
    if not keywords:
        return None
    best = None
    for match in _CANDIDATE.finditer(folded):
        start, end = match.span(1)
        if _UNIT_AFTER.match(folded, end):
            continue
        if _LEAD_BEFORE.search(folded[max(0, start - 16):start]):
            continue
        digits = re.sub(r"\D", "", match.group(1))
        if not 4 <= len(digits) <= 8:
            continue
        # Distance to the nearest keyword; a code usually comes after its keyword.
        distance = min(start - k if k <= start else (k - end) + 20 for k in keywords)
        if best is None or distance < best[0]:
            best = (distance, digits)
    return best[1] if best else None


class OneTimeCodes:
    """The latest code, in memory only, forgotten after KEEP_SECONDS."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.code = ""
        self.key = ""  # the message that carried it
        self.when = 0.0

    def remember(self, code, key=""):
        self.code, self.key, self.when = code, key, self.clock()

    def latest(self):
        """(code, age in seconds, message key), ("", 0, "") when none or too old."""
        if not self.code:
            return "", 0, ""
        age = self.clock() - self.when
        if age > KEEP_SECONDS or age < 0:
            self.forget()
            return "", 0, ""
        return self.code, int(age), self.key

    def forget(self):
        self.code, self.key, self.when = "", "", 0.0
