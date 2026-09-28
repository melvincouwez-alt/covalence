# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Pure helpers for the MAP and PBAP formats: no D-Bus, no I/O.

- bMessage (MAP 1.x, section 3.1.3): the envelope of one message, with the
  originator vCard, one or more recipient vCards and the body.
- vCard 2.1/3.0 as sent by PBAP and inside bMessages (FN, N, TEL, EMAIL).
- Addresses: phone numbers and e-mail addresses normalised so that the same
  person is recognised across MAP listings, bMessages, PBAP and ANCS.
- Timestamps of MAP listings ("20260926T153000", optional "+0200" or "Z").
"""

import base64
import binascii
import calendar
import hashlib
import quopri
import re
import time

DEFAULT_REGION_PREFIX = "+33"  # national numbers "0X XX XX XX XX" (France)


# --- addresses -------------------------------------------------------------------------

def normalize_address(address, region_prefix=DEFAULT_REGION_PREFIX):
    """Canonical form of a phone number or e-mail address ('' if empty)."""
    address = (address or "").strip()
    if not address:
        return ""
    if "@" in address:
        return address.lower()
    if address.lower().startswith("tel:"):
        address = address[4:]
    digits = "".join(c for c in address if c.isdigit())
    if not digits:
        return address  # alphanumeric sender ("Ameli", "INFO"): keep as is
    if address.lstrip().startswith("+"):
        return "+" + digits
    if digits.startswith("00"):
        return "+" + digits[2:]
    if digits.startswith("0") and len(digits) == 10 and region_prefix:
        return region_prefix + digits[1:]
    return digits  # short codes


def split_addresses(value):
    """MAP listing fields may hold several addresses separated by ';' or ','."""
    return [a for a in (normalize_address(p) for p in re.split(r"[;,]", value or "")) if a]


def is_phone(address):
    return bool(address) and "@" not in address and address.lstrip("+").isdigit()


def thread_id(participants):
    """Stable, opaque id of a conversation from its participants (never logged)."""
    key = "|".join(sorted(set(participants)))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


# --- timestamps -----------------------------------------------------------------------------

_TS = re.compile(r"^(\d{8})T(\d{6})(Z|[+-]\d{4})?$")


def parse_timestamp(value, now=None):
    """MAP listing timestamp -> Unix time. Without offset it is the phone's local time."""
    match = _TS.match((value or "").strip())
    if not match:
        return int(now if now is not None else time.time())
    date, clock, zone = match.groups()
    fields = (int(date[:4]), int(date[4:6]), int(date[6:8]),
              int(clock[:2]), int(clock[2:4]), int(clock[4:6]))
    if zone is None:
        return int(time.mktime(fields + (0, 0, -1)))
    epoch = calendar.timegm(fields + (0, 0, 0))
    if zone != "Z":
        sign = 1 if zone[0] == "+" else -1
        epoch -= sign * (int(zone[1:3]) * 3600 + int(zone[3:5]) * 60)
    return epoch


# --- vCard ------------------------------------------------------------------------------------

def _unfold(text):
    """Join folded lines and quoted-printable soft line breaks."""
    lines, qp_open = [], False
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if qp_open:
            lines[-1] = lines[-1][:-1] + raw
        elif raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
        qp_open = "QUOTED-PRINTABLE" in lines[-1].upper() and lines[-1].endswith("=")
    return lines


def _value(name_part, value):
    params = name_part.upper().split(";")[1:]
    if any("QUOTED-PRINTABLE" in p for p in params):
        value = quopri.decodestring(value.encode("latin-1", "replace")).decode("utf-8", "replace")
    return value.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ").strip()


def parse_vcards(text):
    """Every vCard in text -> [{'name': str, 'addresses': [normalised], 'photo': bytes|None}]."""
    cards, current = [], None
    for line in _unfold(text):
        upper = line.upper()
        if upper.startswith("BEGIN:VCARD"):
            current = {"fn": "", "n": "", "addresses": [], "photo": None}
            continue
        if upper.startswith("END:VCARD"):
            if current is not None:
                name = current["fn"] or current["n"]
                cards.append({"name": name, "addresses": current["addresses"],
                              "photo": current["photo"]})
            current = None
            continue
        if current is None or ":" not in line:
            continue
        name_part, value = line.split(":", 1)
        key = name_part.split(";", 1)[0].upper()
        if "." in key:  # item1.TEL
            key = key.split(".", 1)[1]
        if key == "FN":
            current["fn"] = _value(name_part, value)
        elif key == "N":
            parts = [p for p in _value(name_part, value).split(";") if p.strip()]
            # N: family;given;middle;prefix;suffix
            current["n"] = " ".join(reversed(parts[:2])) if parts else ""
        elif key == "PHOTO":
            params = name_part.upper()
            if "ENCODING=B" in params or "BASE64" in params:
                try:
                    current["photo"] = base64.b64decode("".join(value.split()), validate=False)
                except (binascii.Error, ValueError):
                    current["photo"] = None
        elif key in ("TEL", "EMAIL"):
            address = normalize_address(_value(name_part, value))
            if address and address not in current["addresses"]:
                current["addresses"].append(address)
    return cards


# --- call history (PBAP cch) ----------------------------------------------------------------

CALL_KINDS = {"MISSED": "missed", "RECEIVED": "received", "DIALED": "dialed"}


def parse_call_history(text):
    """PBAP call history vCards -> [{'address', 'name', 'time', 'kind'}], newest first."""
    calls, current = [], None
    for line in _unfold(text):
        upper = line.upper()
        if upper.startswith("BEGIN:VCARD"):
            current = {"address": "", "name": "", "time": 0, "kind": ""}
        elif upper.startswith("END:VCARD"):
            if current and current["kind"]:
                calls.append(current)
            current = None
        elif current is not None and ":" in line:
            name_part, value = line.split(":", 1)
            key = name_part.split(";", 1)[0].upper()
            if key == "X-IRMC-CALL-DATETIME":
                params = name_part.upper()
                current["kind"] = next((v for k, v in CALL_KINDS.items() if k in params), "")
                current["time"] = parse_timestamp(value.strip()) if value.strip() else 0
            elif key == "TEL" and not current["address"]:
                current["address"] = normalize_address(_value(name_part, value))
            elif key == "FN" and value.strip():
                current["name"] = _value(name_part, value)
            elif key == "N" and not current["name"]:
                parts = [p for p in _value(name_part, value).split(";") if p.strip()]
                current["name"] = " ".join(reversed(parts[:2])) if parts else ""
    return calls


# --- bMessage -----------------------------------------------------------------------------------

def _msg_text(chunk):
    """Text of a BBODY content: its BEGIN:MSG / END:MSG parts joined (long SMS)."""
    lines = chunk.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    parts, current = [], None
    for line in lines:
        upper = line.strip().upper()
        if upper == "BEGIN:MSG":
            current = []
        elif upper == "END:MSG":
            if current is not None:
                parts.append("\n".join(current))
            current = None
        elif current is not None:
            current.append(line)
    if current:  # no closing END:MSG (a LENGTH a little short): keep what we have
        parts.append("\n".join(current))
    return "\n".join(parts).strip("\n")


def parse_bmessage(text):
    """bMessage -> {'status', 'type', 'folder', 'originator', 'recipients', 'body'}.

    originator/recipients are vCard dicts as returned by parse_vcards. Nested
    envelopes (forwarded messages) contribute their recipients too.

    The message text is whatever the sender typed, so it must never be read as
    structure: the body is exactly the LENGTH bytes announced after BEGIN:BBODY
    (the bMessage specification), and nothing after BEGIN:BBODY counts as an
    envelope. Otherwise an SMS containing "END:MSG" then "BEGIN:VCARD…TEL:…" lines
    would cut its own text short and add made-up recipients (moving the message
    into a forged group conversation). When LENGTH is missing or does not frame a
    BEGIN:MSG block, the body runs from the first BEGIN:MSG to the LAST END:MSG,
    which the text cannot fake either.
    """
    result = {"status": "", "type": "", "folder": "", "originator": None,
              "recipients": [], "body": ""}
    raw = text.encode("utf-8", "replace")
    pos, depth_benv, card = 0, 0, None
    while pos < len(raw):
        stop = raw.find(b"\n", pos)
        stop = len(raw) if stop < 0 else stop
        line = raw[pos:stop].decode("utf-8", "replace").rstrip("\r")
        pos = stop + 1
        upper = line.strip().upper()
        if upper == "BEGIN:BBODY":
            result["body"] = _read_bbody(raw, pos)
            break  # the rest is the text itself and closing lines: no more envelope data
        if upper == "BEGIN:VCARD":
            card = [line]
            continue
        if card is not None:
            card.append(line)
            if upper == "END:VCARD":
                parsed = parse_vcards("\n".join(card))
                card = None
                if parsed:
                    if depth_benv == 0 and result["originator"] is None:
                        result["originator"] = parsed[0]
                    elif depth_benv > 0:
                        result["recipients"].append(parsed[0])
            continue
        if upper == "BEGIN:BENV":
            depth_benv += 1
        elif upper == "END:BENV":
            depth_benv -= 1
        elif depth_benv == 0 and ":" in line:
            key, value = line.split(":", 1)
            key = key.strip().upper()
            if key in ("STATUS", "TYPE", "FOLDER"):
                result[key.lower()] = value.strip()
    return result


def _read_bbody(raw, pos):
    """The message text of a BBODY starting at byte pos (just after BEGIN:BBODY)."""
    length = None
    while pos < len(raw):
        stop = raw.find(b"\n", pos)
        stop = len(raw) if stop < 0 else stop
        line = raw[pos:stop].decode("utf-8", "replace").strip()
        if line.upper().startswith("BEGIN:MSG"):
            break  # no LENGTH line before the content
        pos = stop + 1
        if line.upper().startswith("LENGTH:"):
            try:
                length = int(line.split(":", 1)[1].strip())
            except ValueError:
                length = None
            break
    if length is not None and 0 <= length <= len(raw) - pos:
        chunk = raw[pos:pos + length].decode("utf-8", "replace")
        if chunk.lstrip().upper().startswith("BEGIN:MSG"):
            return _msg_text(chunk)
    # Fallback: from the first BEGIN:MSG to the last END:MSG.
    rest = raw[pos:].decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
    lines = rest.split("\n")
    upper = [line.strip().upper() for line in lines]
    try:
        first = upper.index("BEGIN:MSG")
    except ValueError:
        return ""
    last = max((i for i, u in enumerate(upper) if u == "END:MSG" and i > first), default=len(lines))
    return "\n".join(lines[first + 1:last]).strip("\n")


def build_bmessage(recipient_number, text, recipient_name=""):
    """SMS bMessage for PushMessage (UTF-8, one recipient, outbox)."""
    text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    msg = "BEGIN:MSG\r\n" + text + "\r\nEND:MSG\r\n"
    name = recipient_name.replace(";", " ").replace("\r", " ").replace("\n", " ")
    return ("BEGIN:BMSG\r\nVERSION:1.0\r\nSTATUS:UNREAD\r\nTYPE:SMS_GSM\r\n"
            "FOLDER:TELECOM/MSG/OUTBOX\r\n"
            "BEGIN:VCARD\r\nVERSION:2.1\r\nN:\r\nEND:VCARD\r\n"
            "BEGIN:BENV\r\n"
            f"BEGIN:VCARD\r\nVERSION:2.1\r\nN:{name}\r\nTEL:{recipient_number}\r\nEND:VCARD\r\n"
            "BEGIN:BBODY\r\nCHARSET:UTF-8\r\n"
            f"LENGTH:{len(msg.encode('utf-8'))}\r\n"
            f"{msg}"
            "END:BBODY\r\nEND:BENV\r\nEND:BMSG\r\n")


# --- MAP listings --------------------------------------------------------------------------------

def listing_entry(handle, props, folder):
    """obexd Message1 properties from ListMessages -> normalised dict."""
    outgoing = folder in ("sent", "outbox") or (bool(props.get("Sent")) and folder != "inbox")
    return {
        "handle": handle,
        "folder": folder,
        "outgoing": outgoing,
        "sender": normalize_address(props.get("SenderAddress") or ""),
        "sender_name": (props.get("Sender") or "").strip(),
        "recipients": split_addresses(props.get("RecipientAddress") or ""),
        "recipient_names": [n.strip() for n in re.split(r"[;,]", props.get("Recipient") or "")
                            if n.strip()],
        "time": parse_timestamp(props.get("Timestamp")),
        "subject": props.get("Subject") or "",
        "size": int(props.get("Size") or 0),
        "type": (props.get("Type") or "").lower(),
        "read": bool(props.get("Read")),
    }
