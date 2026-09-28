# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""covalenced: the Covalence daemon, sole owner of the iPhone link and of the secrets."""

import os
import signal
import sys

from gi.repository import Gio, GLib

from . import __version__
from .audio import PhoneAudio
from .calls import Calls
from .config import Config
from .contacts import ContactBook
from .files import Files
from .headphones import Headphones
from .hotspot import Hotspot
from .icloud import ICloud
from .link import Link
from .messages import Messages
from .migrate import migrate
from .mirror import Mirror
from .hid import Control
from .notifications import Notifications
from .proximity import Proximity
from .nowplaying import NowPlaying
from .photos_usb import PhotosUsb
from .mpris import MprisPlayer
from .service import Service
from .cloudprovider import DriveProvider
from .sounds import Sounds
from .updates import Updates
from .i18n import _
from .util import Notifier, log

LOW_BATTERY_LEVELS = (20, 10)


class Daemon:
    def __init__(self):
        self.loop = GLib.MainLoop()
        self.session = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.system = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        self.config = Config()
        self.notifier = Notifier(self.session)
        self.sounds = Sounds(self.config)
        self.battery_warned = set()
        self.battery_note = 0
        self.refresh_pending = False
        self.threads_pending = False
        self.link = None
        self.service = Service(self.session, self)
        self.calls = Calls(self.session, self.system, self.notifier, self.link_changed)
        self.calls.ringer = self.sounds
        self.icloud = ICloud(self.notifier, self.link_changed)
        self.mpris = MprisPlayer(self.session, "iPhone")
        self.messages = Messages(self.session, self.notifier, self)
        self.notifications = Notifications(self.config, self._notifications_changed)
        self.now_playing = NowPlaying(self.system, self.config, self.notifications.icons,
                                      self.link_changed)
        self.calls.on_ended = self.messages.refresh_calls
        self.calls.on_calls = self._calls_state_changed
        self.calls.on_started = self._call_started
        self.calls.on_show = self._open_call_window
        self.call_windows = set()
        self.contact_book = ContactBook(self.config, self._contacts_changed)
        self.headphones = Headphones(self.system, self.session, self.config, self._headphones_changed)
        self.audio = PhoneAudio(self.system, self.config, self.link_changed)
        self.updates = Updates(self.config, self.notifier, self.link_changed)
        self.hotspot = Hotspot(self.system, self._device_info, self.link_changed)
        self.proximity = Proximity(self.config, in_call=lambda: bool(self.calls.active_calls()),
                                   on_changed=self.link_changed, session_bus=self.session)
        self.files = Files(self.config, self.notifier, self.link_changed)
        self.mirror = Mirror(self.link_changed, self.config)
        self.control = Control(self.system, self.config,
                               lambda: self.link.adapter if self.link else None, self.link_changed)
        self.photos_usb = PhotosUsb(self.config, self.notifier, self.link_changed)
        self.drive_provider = DriveProvider(self.session)
        self.link = Link(self.system, self.notifier, self.config, self)
        self.now_playing.attach(self.link)
        if self.config.module_enabled("calls"):
            self.calls.enable()
        if self.config.module_enabled("icloud"):
            self.icloud.enable()
        if self.config.module_enabled("messages"):
            self.messages.enable()

    # --- properties exposed on D-Bus ---------------------------------------------------

    def properties(self):
        link = self.link
        props = link.props if link else {}
        address = props.get("Address", "") or self.config.device_address
        tethering = self.hotspot.state()
        return {
            "Version": __version__,
            "BluetoothAvailable": bool(link and link.adapter),
            "Advertising": bool(link and link.advertising),
            "Pairing": bool(link and link.pairing),
            "LinkProblem": link.problem if link else "",
            "AdapterName": link.adapter_name if link else "",
            "DeviceName": link.name if link and link.device else "",
            "DeviceAddress": address,
            "Paired": bool(props.get("Paired")),
            "Connected": bool(link and link.connected),
            "NotificationsLinked": bool(link and link.ancs),
            "MediaLinked": bool(link and link.ams),
            "CallsLinked": bool(address) and self.calls.ready_for(address),
            "CallsSupported": self.calls.supported,
            "Battery": int(link.battery) if link and link.device else -1,
            "ICloudState": self.icloud.state(),
            "MessagesState": self.messages.state(),
            "AudioOnPC": self.calls.audio_on_pc(),
            "MicMuted": self.calls.muted,
            "MessagesSend": self.messages.send_state(),
            "ReactionsSend": self.messages.reactions_enabled(),
            "OneTimeCodes": self.messages.code_mode(),
            "ContactsState": self.messages.contacts_state,
            "UnreadMessages": self.messages.unread_total() if self.config.module_enabled("messages") else 0,
            "MissedCalls": self.messages.missed_unseen() if self.config.module_enabled("messages") else 0,
            "ContactsSource": self.contact_book.source,
            "ContactsBook": self.contact_book.state,
            "PhoneAudio": self.audio.state(),
            "PhoneAudioOutput": self.audio.output,
            "Modules": self.config.modules(),
            "AlphaFeatures": self.config.alpha_features(),
            "FetchUnread": self.config.boolean("messages", "fetch_unread"),
            "Sounds": self.sounds.settings(),
            "NowPlaying": self.now_playing.state(),
            "Update": self.updates.state(),
            "Tethering": tethering["state"] == "on",
            "TetheringState": tethering["state"],
            "TetheringError": tethering["error"],
            "Proximity": self.proximity.state(),
            "Files": self.files.state(),
            "Mirror": self.mirror.state(),
            "Control": self.control.state(),
            "PhotosUsb": self.photos_usb.state(),
        }

    def link_changed(self):
        # Coalesce bursts of BlueZ signals into one PropertiesChanged.
        if not self.refresh_pending:
            self.refresh_pending = True
            GLib.idle_add(self._refresh)

    @property
    def device_name(self):
        return self.link.name if self.link else "iPhone"

    def messages_changed(self, threads=False):
        self.link_changed()
        if threads and not self.threads_pending:
            self.threads_pending = True
            GLib.idle_add(self._threads_changed)

    def _threads_changed(self):
        self.threads_pending = False
        self.service.threads_changed()
        self._update_badge()
        return False

    def send_progress(self, thread, key, fraction):
        self.service.send_progress(thread, key, fraction)

    def _update_badge(self):
        """Badges on the dock icons (LauncherEntry API): unread messages on Messages,
        missed calls on Téléphone, both on Covalence."""
        unread = self.messages.unread_total() if self.config.module_enabled("messages") else 0
        missed = self.messages.missed_unseen() if self.config.module_enabled("messages") else 0
        badges = {"io.github.melvincouwez.Covalence.desktop": unread + missed,
                  "io.github.melvincouwez.Covalence.Messages.desktop": unread,
                  "io.github.melvincouwez.Covalence.Phone.desktop": missed}
        previous = getattr(self, "badges", {})
        for desktop, count in badges.items():
            if previous.get(desktop) == count:
                continue
            self.session.emit_signal(
                None, "/io/github/melvincouwez/Covalence/LauncherEntry",
                "com.canonical.Unity.LauncherEntry", "Update",
                GLib.Variant("(sa{sv})", ("application://" + desktop, {
                    "count": GLib.Variant("x", count),
                    "count-visible": GLib.Variant("b", count > 0),
                })))
        self.badges = badges

    # --- iPhone notifications (ANCS hooks) ------------------------------------------

    def notification_seen(self, uid, app_id, app_name, title, body, category, actions=None):
        return self.notifications.seen(uid, app_id, app_name, title, body, category, actions)

    def notification_action(self, uid, key):
        """Alpha « ancs_actions »: the iPhone's positive/negative action, from the app."""
        ancs = self.link.ancs if self.link else None
        if not ancs or key not in ("positive", "negative"):
            return False
        ancs.perform_action(uid, key)
        return True

    def notification_app_named(self, app_id, name):
        self.notifications.app_named(app_id, name)

    def notification_icon(self, app_id, on_ready=None):
        return self.notifications.icons.lookup(app_id, on_ready)

    def notification_removed(self, uid):
        self.notifications.removed(uid)

    def _notifications_changed(self):
        if not getattr(self, "notifications_pending", False):
            self.notifications_pending = True

            def emit():
                self.notifications_pending = False
                self.service.notifications_changed()
                return False

            GLib.idle_add(emit)

    def calls_changed(self):
        self.service.calls_changed()
        self._update_badge()

    def _calls_state_changed(self):
        self.link_changed()
        self.service.active_calls_changed()

    def active_calls(self):
        from .bmsg import normalize_address
        from .messages import format_number
        result = []
        for call in self.calls.active_calls():
            address = normalize_address(call["number"])
            store = self.messages.store
            name = (store.contact_name(address) if store else "") or call["name"] \
                or format_number(address)
            result.append(dict(call, name=name,
                               avatar=store.photo(address) if store else ""))
        return result

    def _call_started(self, path):
        """Open the in-call window once per call, when it rings out or is answered."""
        if path in self.call_windows or not self.config.boolean("calls", "window", True):
            return
        self.call_windows.add(path)
        self._open_call_window()

    def _open_call_window(self):
        app = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])),
                           "io.github.melvincouwez.Covalence")
        try:
            Gio.Subprocess.new([app, "--call"], Gio.SubprocessFlags.NONE)
        except GLib.Error as error:
            log(f"appels : fenêtre d'appel non ouverte ({error.message})")

    def message_received(self, thread, key):
        self.service.message_received(thread, key)

    def _refresh(self):
        self.refresh_pending = False
        self.control.refresh()  # publish the HID accessory once the adapter is there
        if self.link:
            self.calls.device_name = self.link.name
            self.mpris.device_name = self.link.name
        self.service.refresh()
        return False

    # --- hooks called by the link and the GATT clients ---------------------------------

    def pairing_code(self, passkey):
        self.service.pairing_code(passkey)

    def pairing_code_answered(self, matches):
        self.service.pairing_code_answered(matches)

    def _headphones_changed(self):
        if not getattr(self, "headphones_pending", False):
            self.headphones_pending = True
            GLib.idle_add(self._emit_headphones)

    def _emit_headphones(self):
        self.headphones_pending = False
        self.service.headphones_changed()
        return False

    def contacts_changed(self):
        self._contacts_changed()

    def play_sound(self, kind):
        """Messages and iPhone notifications: True when Covalence played the sound itself."""
        return self.sounds.play(kind)

    def set_sound(self, kind, value):
        self.sounds.set(kind, value)
        self.link_changed()

    def set_fetch_unread(self, enabled):
        self.config.set_boolean("messages", "fetch_unread", enabled)
        log(f"messages : texte complet des non-lus {'activé' if enabled else 'désactivé'}")
        if enabled and self.messages.enabled:
            self.messages._fetch_bodies()
        self.link_changed()

    def set_alpha(self, name, enabled):
        self.config.set_alpha(name, enabled)
        log(f"fonction alpha {name} {'activée' if enabled else 'désactivée'}")
        if name == "pbap_favorites":
            self._contacts_changed()
        elif name == "ancs_actions":
            self._notifications_changed()
        elif name == "iphone_control":
            self.control.refresh(force=True)
        self.link_changed()

    def _contacts_changed(self):
        self.link_changed()
        self.service.contacts_changed()

    def contact_cards(self):
        """Cards shown in Contacts: iCloud's when chosen and open, else the iPhone's (PBAP)."""
        if self.contact_book.source == "icloud":
            store = self.messages.store
            if not store:
                return self.contact_book.cards
            # iCloud photos EDS has not downloaded yet: the iPhone's (PBAP) one if known.
            return self._with_favorites([dict(c, photo=c["photo"] or next(
                (p for p in map(store.photo, c["addresses"]) if p), ""))
                for c in self.contact_book.cards])
        return self._with_favorites(self.messages.contacts())

    def _with_favorites(self, cards):
        favorites = self.messages.favorites()
        return [dict(c, favorite=any(a in favorites for a in c["addresses"])) for c in cards]

    def device_chosen(self, device_path):
        self.audio.set_device(device_path)
        # AVRCP link and players already there at start: Now Playing picks them up.
        GLib.idle_add(lambda: self.media_changed() and False)

    def device_connected(self, device_path, address):
        # PipeWire usually connects HFP itself; if not, ask for it after a moment.
        # Only while this very connection is still up: asking for a profile opens a
        # new link, and with a pairing the iPhone forgot that looped every few seconds.
        GLib.timeout_add_seconds(8, lambda: self._ensure_hfp(device_path, address) and False)
        GLib.timeout_add_seconds(3, lambda: self.media_changed() and False)
        self.messages.device_connected(address)
        self.proximity.device_connected()

    def _ensure_hfp(self, device_path, address):
        link = self.link
        if not link or link.device != device_path or link.bond_lost \
                or not link.props.get("Connected"):
            return
        self.calls.ensure_hfp(device_path, address, on_error=link.connect_failed)

    def device_disconnected(self):
        self.messages.device_disconnected()
        self.proximity.device_disconnected()

    def device_rssi(self, value):
        self.proximity.rssi_sample(value)

    def _device_info(self):
        """(address, service UUIDs) of the iPhone, for the Bluetooth tethering."""
        props = self.link.props if self.link else {}
        address = props.get("Address", "") or self.config.device_address
        return address, list(props.get("UUIDs", []))

    def message_notification(self, title, subtitle, message, date=None, replay=False, uid=None,
                             modified=False):
        """ANCS notification from the Messages app: the messages module may take it."""
        return self.config.module_enabled("messages") and \
            self.messages.ancs_message(title, subtitle, message, date, replay, uid, modified)

    def suppress_incoming_call(self, title):
        """ANCS incoming-call notification: let the calls module show it when it can."""
        address = self.link.props.get("Address", "") if self.link else ""
        if self.config.module_enabled("calls") and self.calls.ready_for(address):
            self.calls.set_caller_hint(title)
            return True
        return False

    def battery_changed(self, level):
        self.link_changed()
        if not self.config.module_enabled("battery") or level < 0:
            return
        if level > max(LOW_BATTERY_LEVELS) + 5:
            self.battery_warned.clear()
            return
        for threshold in LOW_BATTERY_LEVELS:
            if level <= threshold and threshold not in self.battery_warned:
                self.battery_warned.update(t for t in LOW_BATTERY_LEVELS if t >= threshold)
                log(f"batterie de l'iPhone faible ({level} %)")
                self.battery_note = self.notifier.notify(
                    "Covalence", "battery-caution",
                    _("Batterie de {device} faible").format(device=self.link.name),
                    _("Il reste {level} %.").format(level=level), replaces=self.battery_note, own=True)
                break

    def media_changed(self):
        """AMS attached/detached or AVRCP player appeared/vanished."""
        link = self.link
        if link is None:
            return
        if link.device:
            try:
                self.now_playing.refresh_avrcp(link._objects())
            except GLib.Error:
                pass
        if link.ams and not link.has_avrcp_player():
            self.mpris.publish(link.ams)
        else:
            if link.ams and self.mpris.published:
                log("MPRIS : lecteur AVRCP présent, celui d'AMS est retiré pour éviter un doublon")
            self.mpris.withdraw()
        self.link_changed()

    def media_state_changed(self, changed):
        self.mpris.on_change(changed)
        self.link_changed()

    def avrcp_player_changed(self, path, changed):
        self.now_playing.avrcp_changed(path, changed)

    def avrcp_control_changed(self, path, changed):
        self.now_playing.control_changed(path, changed)

    # --- settings -------------------------------------------------------------------

    def set_module_enabled(self, module, enabled):
        self.config.set_module_enabled(module, enabled)
        log(f"module {module} {'activé' if enabled else 'désactivé'}")
        if module in ("notifications", "media"):
            self.link.module_toggled()
        elif module == "calls":
            (self.calls.enable if enabled else self.calls.disable)()
        elif module == "icloud":
            (self.icloud.enable if enabled else self.icloud.disable)()
        elif module == "messages":
            if enabled:
                self.messages.enable()
                if self.link and self.link.props.get("Connected"):
                    self.messages.device_connected(self.link.props.get("Address", ""))
            else:
                self.messages.disable()
        elif module == "battery" and not enabled:
            self.notifier.close(self.battery_note)
        self.link_changed()

    # --- lifecycle ---------------------------------------------------------------------

    def run(self):
        self.service.own_name(self._on_name_lost)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self.stop)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.stop)
        log(f"covalenced {__version__} démarré")
        self.updates.start()
        self.drive_provider.start()
        self.loop.run()

    def _on_name_lost(self, _conn, _name):
        log("une autre instance de covalenced tourne déjà : arrêt")
        self.loop.quit()
        sys.exit(1)

    def stop(self):
        log("arrêt")
        if self.link.pairing:
            self.link.stop_pairing()
        if self.link.advertising:
            try:
                self.system.call_sync("org.bluez", self.link.adapter,
                                      "org.bluez.LEAdvertisingManager1", "UnregisterAdvertisement",
                                      GLib.Variant("(o)", ("/io/github/melvincouwez/Covalence/advertisement",)),
                                      None, Gio.DBusCallFlags.NONE, 2000, None)
            except GLib.Error:
                pass
        self.mpris.withdraw()
        self.headphones.stop()
        self.messages.stop()
        self.files.stop()
        self.mirror.stop()
        self.control.withdraw()
        self.photos_usb.cancel()
        self.loop.quit()
        return False


def main():
    # Before anything reads settings: brings over what Tandem (the former name) left.
    migrate(log)
    Daemon().run()
    return 0
