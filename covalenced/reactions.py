# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Reactions ("tapbacks") carried as plain SMS text.

MAP only carries text: when someone reacts to an SMS on an iPhone or in Google
Messages, the other side receives a text such as « A aimé « à demain » » or
“Loved “see you””. parse() recognises those texts; the messages module then
shows the reaction as a badge on the quoted message instead of a bubble.

The patterns live in the tables below, easy to extend. Sources for the labels:
Apple's Tapback names (Loved, Liked, Disliked, Laughed at, Emphasized,
Questioned; https://support.apple.com/guide/iphone/react-with-tapbacks-iph018d3c336/ios),
Google Messages' SMS fallback (“<emoji> to “text””, 9to5google 2022-09-30),
and the French texts reported by iGeneration and iPhoneSoft (« a ajouté un
« J'aime » à « … » »).
"""

import re
import unicodedata

HEART, LIKE, DISLIKE, LAUGH, EMPHASIS, QUESTION = "❤️", "👍", "👎", "😂", "‼️", "❓"

# Verb phrases before the quoted text, lower case, apostrophes normalised to "'".
ADD = [
    # iOS, French
    ("a adoré", HEART), ("a aimé", LIKE), ("n'a pas aimé", DISLIKE), ("a désapprouvé", DISLIKE),
    ("n'aime pas", DISLIKE), ("a ri de", LAUGH), ("a ri à", LAUGH), ("a ri à propos de", LAUGH),
    ("a mis en évidence", EMPHASIS), ("a souligné", EMPHASIS), ("a mis l'accent sur", EMPHASIS),
    ("a insisté sur", EMPHASIS), ("a posé une question sur", QUESTION), ("a questionné", QUESTION),
    ("s'est interrogé sur", QUESTION), ("s'est interrogée sur", QUESTION),
    ("s'est interrogé(e) sur", QUESTION),
    # Google Messages, French
    ("a ajouté un « j'adore » à", HEART), ("a ajouté un « j'aime » à", LIKE),
    ("a ajouté un « je n'aime pas » à", DISLIKE), ("a ajouté un « haha » à", LAUGH),
    ("a ajouté un « ha ha » à", LAUGH), ("a ajouté un « !! » à", EMPHASIS),
    ("a ajouté un « ? » à", QUESTION),
    # iOS, English
    ("loved", HEART), ("liked", LIKE), ("disliked", DISLIKE), ("laughed at", LAUGH),
    ("emphasized", EMPHASIS), ("emphasised", EMPHASIS), ("questioned", QUESTION),
]

# Removal phrases: a keyword picks the reaction, else the emoji in the text.
REMOVE_PREFIXES = ["a retiré", "a supprimé", "a enlevé", "removed"]
REMOVE_WORDS = [
    ("cœur", HEART), ("coeur", HEART), ("j'adore", HEART), ("adoré", HEART), ("heart", HEART),
    ("love", HEART), ("je n'aime pas", DISLIKE), ("dislike", DISLIKE), ("j'aime", LIKE),
    ("like", LIKE), ("rire", LAUGH), ("ha ha", LAUGH), ("haha", LAUGH), ("laugh", LAUGH),
    ("exclamation", EMPHASIS), ("!!", EMPHASIS), ("emphasis", EMPHASIS), ("accent", EMPHASIS),
    ("question", QUESTION), ("?", QUESTION),
]

# "Reacted 😂 to", "A réagi avec 😂 à", "😂 to", "😂 à": {emoji} is where the emoji sits.
EMOJI_FORMS = [
    "a réagi avec {e} à", "a réagi par {e} à", "a réagi {e} à", "réaction {e} à",
    "a ajouté {e} à", "a ajouté un {e} à", "a ajouté une réaction {e} à", "added {e} to",
    "reacted {e} to", "reacted with {e} to", "{e} to", "{e} à",
    "a réagi avec {e}", "a réagi par {e}", "reacted {e}", "reacted with {e}",
]

QUOTES = [("«", "»"), ("“", "”"), ("„", "“"), ('"', '"'), ("‘", "’"), ("'", "'")]
_SPACES = re.compile(r"[\s   ]+")
_EMOJI = re.compile(
    "(?:[\U0001F000-\U0001FAFF☀-➿⬀-⯿‼⁉™ℹ〰〽]"
    "[️‍\U0001F3FB-\U0001F3FF☀-➿\U0001F000-\U0001FAFF]*)+")


def _clean(text):
    text = unicodedata.normalize("NFC", text or "")
    return _SPACES.sub(" ", text).strip()


def _apostrophes(text):
    return text.replace("’", "'").replace("ʼ", "'")


def normalize(text):
    """Comparable form of a message or quote: words only, case-folded, no ellipsis."""
    text = _apostrophes(_clean(text)).casefold()
    return text.rstrip(".… ").strip()


def _split_quote(text):
    """(before, quote) when text ends with a quoted part, else (text, None)."""
    for opening, closing in QUOTES:
        end = len(text) - len(closing)
        if not text.endswith(closing) or end <= 0:
            continue
        if opening != closing:
            start = text.rfind(opening, 0, end)
        else:  # same mark on both sides: the first one that opens a word
            found = re.search(r"(?:^|\s)" + re.escape(opening), text[:end])
            start = found.end() - len(opening) if found else -1
        if start < 0:
            continue
        quote = text[start + len(opening):end].strip()
        if quote:
            return text[:start].strip(), quote
    return text, None


def _strip_name(text, names):
    """iOS and notifications may start with the sender's name: "Alice reacted 😂 to …"."""
    folded = _apostrophes(text).casefold()
    for name in sorted({_clean(n) for n in names or () if n and _clean(n)}, key=len, reverse=True):
        name = _apostrophes(name).casefold()
        if folded.startswith(name + " "):
            return text[len(name) + 1:].lstrip()
    return text


def parse(text, names=()):
    """{"emoji", "quote" (None when the text names no message), "removed"} or None.
    names: the sender's names, which may lead the text."""
    text = _clean(text)
    if not text or len(text) > 400:
        return None
    text = _strip_name(text, names)
    text = re.sub(r"(?<=[»”\"’'])\s*[.!]$", "", text)  # « … ». : closing full stop
    before, quote = _split_quote(text)
    if quote is None:
        # "A réagi avec 😂" / "Reacted 😂": a reaction to the latest message.
        before = text
    head = _apostrophes(before).casefold().rstrip(" :")

    for prefix in REMOVE_PREFIXES:
        if head.startswith(prefix):
            emoji = _EMOJI.search(before)
            if emoji:
                return {"emoji": _canon(emoji.group(0)), "quote": quote, "removed": True}
            for word, mark in REMOVE_WORDS:
                if word in head:
                    return {"emoji": mark, "quote": quote, "removed": True}
            return None

    if quote is not None:
        for phrase, mark in ADD:
            if head == phrase:
                return {"emoji": mark, "quote": quote, "removed": False}
    emoji = _EMOJI.search(before)
    if emoji:
        rest = head.replace(emoji.group(0).casefold(), "{e}", 1)
        for form in EMOJI_FORMS:
            if rest == form and ("{e}" in form):
                wants_quote = form.endswith(" à") or form.endswith(" to")
                if wants_quote == (quote is not None):
                    return {"emoji": _canon(emoji.group(0)), "quote": quote, "removed": False}
    return None


def _canon(emoji):
    """Same badge for ❤ and ❤️, ‼ and ‼️."""
    base = emoji.replace("️", "")
    for mark in (HEART, EMPHASIS, QUESTION, LIKE, DISLIKE, LAUGH):
        if base == mark.replace("️", ""):
            return mark
    return emoji


def matches(quote, body):
    """Does the quoted text (maybe cut short) designate this message?"""
    q, b = normalize(quote), normalize(body)
    if not q or not b:
        return False
    return b == q or b.startswith(q) or (len(b) >= 8 and q.startswith(b))


# --- sending ----------------------------------------------------------------------------------------

SEND_FR = {HEART: "A adoré", LIKE: "A aimé", DISLIKE: "N'a pas aimé", LAUGH: "A ri de",
           EMPHASIS: "A mis en évidence", QUESTION: "A posé une question sur"}
SEND_EN = {HEART: "Loved", LIKE: "Liked", DISLIKE: "Disliked", LAUGH: "Laughed at",
           EMPHASIS: "Emphasized", QUESTION: "Questioned"}
QUOTE_MAX = 40


def quote_of(body, limit=QUOTE_MAX):
    body = _clean(body)
    return body if len(body) <= limit else body[:limit].rstrip() + "…"


def build(emoji, body, language):
    """The SMS text for a reaction, as an iPhone would write it in that language."""
    emoji = _canon(emoji)
    q = quote_of(body)
    if language == "fr":
        verb = SEND_FR.get(emoji)
        return f"{verb} « {q} »" if verb else f"A réagi avec {emoji} à « {q} »"
    verb = SEND_EN.get(emoji)
    return f"{verb} “{q}”" if verb else f"Reacted {emoji} to “{q}”"
