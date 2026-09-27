# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Contact cards managed through iCloud (CardDAV in Evolution Data Server).

Bluetooth cannot change the iPhone's contacts: PBAP only reads them and iOS
accepts no vCard push. The contacts the iPhone shows are those of the iCloud
account, so Covalence edits them there and iCloud brings the change back to the
iPhone within seconds.

The user picks the source in the Contacts page:
- "bluetooth": the phone book read over PBAP, cached, read only (default);
- "icloud": the iCloud address book, editable; needs the iCloud account.

All EBook calls are blocking: they run on a worker thread, and the results
come back on the main loop.
"""

import hashlib
import os

import gi

from .bmsg import normalize_address
from .messages import Worker
from .util import icloud_uid_prefix, log

try:
    gi.require_version("EDataServer", "1.2")
    gi.require_version("EBook", "1.2")
    gi.require_version("EBookContacts", "1.2")
    from gi.repository import EBook, EBookContacts, EDataServer
except (ImportError, ValueError):  # gir1.2-ebook-1.2 missing: iCloud mode unavailable
    EBook = EBookContacts = EDataServer = None

from gi.repository import GLib

SOURCES = ("bluetooth", "icloud")
PHOTO_DIR = os.path.join(GLib.get_user_data_dir(), "covalence", "contacts", "photos")

# Labels offered in the editor, with the vCard TYPE parameters Apple understands.
PHONE_LABELS = {"mobile": ["CELL", "VOICE"], "iphone": ["IPHONE", "CELL", "VOICE"],
                "domicile": ["HOME", "VOICE"], "travail": ["WORK", "VOICE"],
                "principal": ["MAIN"], "autre": ["OTHER", "VOICE"]}
EMAIL_LABELS = {"domicile": ["INTERNET", "HOME"], "travail": ["INTERNET", "WORK"],
                "autre": ["INTERNET", "OTHER"]}
# Apple's own labels (item1.X-ABLabel:_$!<Mobile>!$_) read back to ours.
APPLE_LABELS = {"mobile": "mobile", "home": "domicile", "work": "travail", "main": "principal",
                "iphone": "iphone", "other": "autre"}


def _label(attr, contact, labels):
    """Our label for a TEL or EMAIL attribute ('' when none is known)."""
    group = attr.get_group()
    if group:
        for other in EBookContacts.VCard.get_attributes(contact):
            if other.get_group() == group and other.get_name().upper() == "X-ABLABEL":
                raw = (other.get_value() or "").strip("_$!<>").lower()
                return APPLE_LABELS.get(raw, raw)
    types = [t.upper() for t in (attr.get_param("TYPE") or [])]
    if "IPHONE" in types and "iphone" in labels:
        return "iphone"
    for name, wanted in labels.items():
        # INTERNET and VOICE are on every entry: match on the distinctive type.
        key = next(t for t in wanted if t not in ("INTERNET", "VOICE"))
        if key in types:
            return name
    if "CELL" in types:
        return "mobile"
    return ""


def _replace(contact, name, values):
    """Set a single-instance vCard attribute (None removes it)."""
    for attr in list(EBookContacts.VCard.get_attributes(contact)):
        if attr.get_name().upper() == name:
            EBookContacts.VCard.remove_attribute(contact, attr)
    if values is None:
        return
    attr = EBookContacts.VCardAttribute.new(None, name)
    for value in values:
        attr.add_value(value)
    EBookContacts.VCard.append_attribute(contact, attr)


class ContactBook:
    def __init__(self, config, on_change):
        self.config = config
        self.on_change = on_change
        self.worker = None
        self.client = None
        self.state = "off"   # off, connecting, ready, no-account, missing, error
        self.cards = []      # [{'uid', 'name', 'addresses', 'photo'}]
        if self.source == "icloud":
            self._open()

    # --- settings ---------------------------------------------------------------------

    @property
    def source(self):
        try:
            value = self.config.keyfile.get_string("contacts", "source")
        except GLib.Error:
            return "bluetooth"
        return value if value in SOURCES else "bluetooth"

    def set_source(self, source):
        if source not in SOURCES:
            raise ValueError(source)
        self.config.keyfile.set_string("contacts", "source", source)
        self.config.save()
        log(f"contacts : gestion {'via iCloud' if source == 'icloud' else 'par Bluetooth'}")
        if source == "icloud":
            self._open()
        else:
            self.client = None
            self.cards = []
            self.state = "off"
        self.on_change()

    @property
    def editable(self):
        return self.source == "icloud" and self.state == "ready"

    # --- opening ----------------------------------------------------------------------

    def _submit(self, job, done):
        if self.worker is None:
            self.worker = Worker()
        self.worker.submit(job, done)

    def _open(self):
        if EBook is None:
            self.state = "missing"
            self.on_change()
            return
        self.state = "connecting"

        def job():
            registry = EDataServer.SourceRegistry.new_sync(None)
            for source in registry.list_sources(EDataServer.SOURCE_EXTENSION_ADDRESS_BOOK):
                if source.get_parent() == f"{icloud_uid_prefix()}-collection" and source.get_enabled():
                    client = EBook.BookClient.connect_sync(source, 30, None)
                    return client, self._read(client)
            return None, []

        self._submit(job, self._opened)

    def _opened(self, result, error):
        if self.source != "icloud":
            return
        if error:
            log(f"contacts : carnet iCloud illisible ({error})")
            self.state = "error"
        elif result[0] is None:
            self.state = "no-account"
        else:
            self.client, self.cards = result
            self.state = "ready"
            log(f"contacts : {len(self.cards)} fiches iCloud")
        self.on_change()

    def reload(self):
        if self.client is None:
            if self.source == "icloud":
                self._open()
            return
        client = self.client
        self._submit(lambda: self._read(client), self._reloaded)

    def _reloaded(self, cards, error):
        if not error and cards is not None:
            self.cards = cards
        self.on_change()

    # --- reading ----------------------------------------------------------------------

    @staticmethod
    def _contacts(client):
        _ok, contacts = client.get_contacts_sync('(exists "full_name")', None)
        return contacts

    def _read(self, client):
        cards = []
        for contact in self._contacts(client):
            uid = contact.get_property("id")
            addresses = []
            for attr in EBookContacts.VCard.get_attributes(contact):
                if attr.get_name().upper() in ("TEL", "EMAIL"):
                    address = normalize_address(attr.get_value() or "")
                    if address and address not in addresses:
                        addresses.append(address)
            # iOS often leaves FN empty and only fills N: build the name like the iPhone does.
            name = (contact.get_property("full-name") or "").strip() or " ".join(
                p for p in (contact.get_property("given-name"), contact.get_property("family-name"))
                if p and p.strip()) or (contact.get_property("org") or "").strip() \
                or (contact.get_property("nickname") or "").strip()
            cards.append({"uid": uid, "name": name, "addresses": addresses,
                          "photo": self._photo(uid, contact)})
        cards.sort(key=lambda c: c["name"].casefold())
        return cards

    @staticmethod
    def _photo(uid, contact):
        photo = contact.get_property("photo")
        if photo is None:
            return ""
        if photo.type == EBookContacts.ContactPhotoType.URI:
            # EDS keeps downloaded photos in its cache and points to them.
            uri = photo.get_uri() or ""
            path = GLib.filename_from_uri(uri)[0] if uri.startswith("file://") else ""
            return path if path and os.path.exists(path) else ""
        data = photo.get_inlined()
        data = bytes(data[0] if isinstance(data, tuple) else data or b"")
        if not data:
            return ""
        os.makedirs(PHOTO_DIR, mode=0o700, exist_ok=True)
        name = hashlib.sha1(uid.encode()).hexdigest()[:16]
        path = os.path.join(PHOTO_DIR, name + "-" + hashlib.sha1(data).hexdigest()[:8])
        if not os.path.exists(path):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        return path

    def details(self, uid, on_done):
        """Editable fields of one card: on_done(dict | None, error)."""
        client = self.client

        def job():
            _ok, contact = client.get_contact_sync(uid, None)
            phones, emails = [], []
            for attr in EBookContacts.VCard.get_attributes(contact):
                kind = attr.get_name().upper()
                if kind == "TEL":
                    phones.append((_label(attr, contact, PHONE_LABELS), attr.get_value() or ""))
                elif kind == "EMAIL":
                    emails.append((_label(attr, contact, EMAIL_LABELS), attr.get_value() or ""))
            return {"uid": uid,
                    "given": contact.get_property("given-name") or "",
                    "family": contact.get_property("family-name") or "",
                    "org": contact.get_property("org") or "",
                    "note": contact.get_property("note") or "",
                    "phones": phones, "emails": emails}

        if client is None:
            on_done(None, "carnet iCloud non ouvert")
            return
        self._submit(job, on_done)

    # --- writing ----------------------------------------------------------------------

    def save(self, card, on_done):
        """Create (no uid) or update a card; on_done(uid | None, error)."""
        client = self.client
        if client is None:
            on_done(None, "carnet iCloud non ouvert")
            return

        def job():
            uid = card.get("uid") or ""
            if uid:
                _ok, contact = client.get_contact_sync(uid, None)
            else:
                contact = EBookContacts.Contact.new()
            self._fill(contact, card)
            if uid:
                client.modify_contact_sync(contact, EBookContacts.BookOperationFlags.NONE, None)
            else:
                _ok, uid = client.add_contact_sync(contact, EBookContacts.BookOperationFlags.NONE, None)
            return uid

        def done(uid, error):
            if error:
                log(f"contacts : fiche non enregistrée ({error})")
            else:
                log("contacts : fiche enregistrée dans iCloud")
                self.reload()
            on_done(uid, error)

        self._submit(job, done)

    def delete(self, uid, on_done):
        client = self.client
        if client is None:
            on_done(None, "carnet iCloud non ouvert")
            return

        def done(result, error):
            if error:
                log(f"contacts : fiche non supprimée ({error})")
            else:
                log("contacts : fiche supprimée dans iCloud")
                self.reload()
            on_done(result, error)

        self._submit(lambda: client.remove_contact_by_uid_sync(
            uid, EBookContacts.BookOperationFlags.NONE, None), done)

    @staticmethod
    def _fill(contact, card):
        given = card.get("given", "").strip()
        family = card.get("family", "").strip()
        org = card.get("org", "").strip()
        # contact.set() takes a raw pointer that PyGObject cannot pass: write the attributes.
        _replace(contact, "N", [family, given, "", "", ""])
        _replace(contact, "FN", [" ".join(p for p in (given, family) if p) or org])
        _replace(contact, "ORG", [org] if org else None)
        _replace(contact, "NOTE", [card.get("note", "").strip()] if card.get("note", "").strip() else None)

        # Numbers and addresses are written again as a whole; Apple's label groups
        # (itemN.X-ABLabel) of the old ones go with them. Everything else is kept.
        groups = set()
        for attr in list(EBookContacts.VCard.get_attributes(contact)):
            if attr.get_name().upper() in ("TEL", "EMAIL"):
                if attr.get_group():
                    groups.add(attr.get_group())
                EBookContacts.VCard.remove_attribute(contact, attr)
        for attr in list(EBookContacts.VCard.get_attributes(contact)):
            if attr.get_group() in groups and attr.get_name().upper() == "X-ABLABEL":
                EBookContacts.VCard.remove_attribute(contact, attr)
        for kind, labels, entries in (("TEL", PHONE_LABELS, card.get("phones", [])),
                                      ("EMAIL", EMAIL_LABELS, card.get("emails", []))):
            first = True
            for label, value in entries:
                value = value.strip()
                if not value:
                    continue
                attr = EBookContacts.VCardAttribute.new(None, kind)
                types = list(labels.get(label, labels["autre"]))
                if first:
                    types.append("pref")
                    first = False
                for t in types:
                    param = EBookContacts.VCardAttributeParam.new("TYPE")
                    param.add_value(t)
                    attr.add_param(param)
                attr.add_value(value)
                EBookContacts.VCard.append_attribute(contact, attr)
