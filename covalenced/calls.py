# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Phone calls through PipeWire's native HFP hands-free role.

PipeWire (WirePlumber) publishes org.pipewire.Telephony on the session bus once
the iPhone's Hands-Free Audio Gateway profile is connected: one object per
audio gateway (AudioGateway1, oFono-compatible VoiceCallManager) and one per
call (Call1: Answer, Hangup, State, LineIdentification, Name).

This module never dials: it only follows calls, and answers or hangs up on
the user's request from the notification buttons.
"""

import time

from gi.repository import Gio, GLib

from .i18n import N_, _, pgettext
from .util import BLUEZ, call_async, log

TELEPHONY = "org.pipewire.Telephony"
ROOT = "/org/pipewire/Telephony"
GATEWAY = "org.pipewire.Telephony.AudioGateway1"
TRANSPORT = "org.pipewire.Telephony.AudioGatewayTransport1"
CALL = "org.pipewire.Telephony.Call1"
HFP_AG_UUID = "0000111f-0000-1000-8000-00805f9b34fb"

STATE_LABELS = {
    "incoming": N_("Appel entrant"), "waiting": N_("Appel en attente"),
    "dialing": N_("Appel sortant"), "alerting": N_("Appel sortant"),
    "active": N_("Appel en cours"), "held": N_("Appel en attente"),
}


class Calls:
    def __init__(self, session, system, notifier, on_state):
        self.session = session
        self.system = system
        self.notifier = notifier
        self.on_state = on_state  # callable() when gateways change
        self.enabled = False
        self.owner = None
        self.gateways = {}  # path -> address
        self.calls = {}  # path -> properties
        self.notifications = {}  # call path -> notification id
        self.subscriptions = []
        self.watch_id = 0
        self.caller_hint = ("", 0.0)  # name from ANCS, monotonic time
        self.device_name = "iPhone"
        self.on_ended = None  # callable() once a call is over
        self.on_calls = None  # callable() when calls, audio route or mute change
        self.on_started = None  # callable(path) when a call starts ringing out or is answered
        self.on_show = None  # callable() to bring the call window up
        self.ringer = None  # sounds.Sounds: the ringtone chosen in Réglages
        self.started = {}  # call path -> monotonic time it became active
        self.transport = {}  # gateway path -> {"State", "RejectSCO"}
        # org.pipewire.Telephony first shipped in PipeWire 1.4;
        # with an older PipeWire, calls are shown as unavailable.
        from .components import PIPEWIRE_MIN, _pipewire_version
        version = _pipewire_version()
        self.supported = version is None or version >= PIPEWIRE_MIN
        self.muted = False
        self.mute_restore = None  # default source mute state before a call
        # Demonstration calls: shown like real ones, but nothing reaches the
        # iPhone, PipeWire or the microphone.
        self.demo = set()
        self.demo_audio_on_pc = True
        self.demo_counter = 0

    # --- lifecycle ------------------------------------------------------------

    def enable(self):
        if self.enabled:
            return
        self.enabled = True
        self.watch_id = Gio.bus_watch_name_on_connection(
            self.session, TELEPHONY, Gio.BusNameWatcherFlags.NONE,
            self._on_appeared, self._on_vanished)

    def disable(self):
        if not self.enabled:
            return
        self.enabled = False
        Gio.bus_unwatch_name(self.watch_id)
        self._on_vanished(None, None)

    def _on_appeared(self, _conn, _name, owner):
        self.owner = owner
        self.supported = True
        # Calls are children of each gateway (/org/pipewire/Telephony/agN), which is an
        # ObjectManager of its own: listen on every path, not only the root.
        for member, handler in (("InterfacesAdded", self._on_added),
                                ("InterfacesRemoved", self._on_removed)):
            self.subscriptions.append(self.session.signal_subscribe(
                owner, "org.freedesktop.DBus.ObjectManager", member, None, None,
                Gio.DBusSignalFlags.NONE, handler))
        # oFono-style signals too, in case a PipeWire version only emits these.
        self.subscriptions.append(self.session.signal_subscribe(
            owner, "org.ofono.VoiceCallManager", "CallAdded", None, None,
            Gio.DBusSignalFlags.NONE, self._on_call_added))
        self.subscriptions.append(self.session.signal_subscribe(
            owner, "org.ofono.VoiceCallManager", "CallRemoved", None, None,
            Gio.DBusSignalFlags.NONE, self._on_call_removed))
        self.subscriptions.append(self.session.signal_subscribe(
            owner, "org.freedesktop.DBus.Properties", "PropertiesChanged", None, CALL,
            Gio.DBusSignalFlags.NONE, self._on_call_changed))
        self.subscriptions.append(self.session.signal_subscribe(
            owner, "org.freedesktop.DBus.Properties", "PropertiesChanged", None, TRANSPORT,
            Gio.DBusSignalFlags.NONE, self._on_transport_changed))
        call_async(self.session, owner, ROOT, "org.freedesktop.DBus.ObjectManager",
                   "GetManagedObjects", on_done=self._on_objects)

    def _on_vanished(self, _conn, _name):
        for sub in self.subscriptions:
            self.session.signal_unsubscribe(sub)
        self.subscriptions = []
        self.owner = None
        for path in list(self.calls):
            self._call_gone(path)
        if self.gateways:
            self.gateways = {}
            self.on_state()

    def _on_objects(self, value, error):
        if error:
            log(f"téléphonie PipeWire illisible : {error.message}")
            return
        for path, interfaces in value.unpack()[0].items():
            self._add(path, interfaces)

    def _on_added(self, _conn, _sender, _path, _iface, _signal, params):
        path, interfaces = params.unpack()
        self._add(path, interfaces)

    def _on_call_added(self, _conn, _sender, _path, _iface, _signal, params):
        path, props = params.unpack()
        self._add(path, {CALL: props})

    def _on_call_removed(self, _conn, _sender, _path, _iface, _signal, params):
        self._call_gone(params.unpack()[0])

    def _on_removed(self, _conn, _sender, _path, _iface, _signal, params):
        path, interfaces = params.unpack()
        if TRANSPORT in interfaces:
            self.transport.pop(path, None)
        if GATEWAY in interfaces and path in self.gateways:
            del self.gateways[path]
            log("appels : passerelle mains libres retirée")
            self.on_state()
        if CALL in interfaces:
            self._call_gone(path)

    def _add(self, path, interfaces):
        if TRANSPORT in interfaces:
            self.transport[path] = dict(interfaces[TRANSPORT])
        if GATEWAY in interfaces and path not in self.gateways:
            self.gateways[path] = interfaces[GATEWAY].get("Address", "")
            log("appels : passerelle mains libres de l'iPhone disponible")
            self.on_state()
            # Calls already in progress when Covalence starts are listed by the gateway.
            if self.owner:
                call_async(self.session, self.owner, path, "org.freedesktop.DBus.ObjectManager",
                           "GetManagedObjects", on_done=self._on_objects)
        if CALL in interfaces:
            known = path in self.calls
            self.calls.setdefault(path, {}).update(interfaces[CALL])
            state = self.calls[path].get("State", "?")
            if not known:
                log(f"appels : nouvel appel ({state})")
            self._refresh(path)
            self._state_entered(path, state)
            self._changed()

    def _on_call_changed(self, _conn, _sender, path, _iface, _signal, params):
        _interface, changed, _invalid = params.unpack()
        if path not in self.calls:
            return
        previous = self.calls[path].get("State")
        self.calls[path].update(changed)
        state = self.calls[path].get("State")
        if state != previous:
            log(f"appels : état {previous} → {state}")
            self._state_entered(path, state)
        self._refresh(path)
        self._changed()

    # --- HFP link ---------------------------------------------------------------

    def ready_for(self, address):
        return any(a.upper() == address.upper() for a in self.gateways.values())

    def ensure_hfp(self, device_path, address, on_error=None):
        """Connect the iPhone's hands-free gateway if PipeWire has not done it."""
        if not self.enabled or not address or self.ready_for(address):
            return
        log("appels : connexion du profil mains libres")

        def done(_value, error):
            if error:
                log(f"appels : profil mains libres non connecté : {error.message}")
                if on_error:
                    on_error(error)

        call_async(self.system, BLUEZ, device_path, "org.bluez.Device1", "ConnectProfile",
                   GLib.Variant("(s)", (HFP_AG_UUID,)), timeout=30000, on_done=done)

    def dial(self, number, on_done):
        """Call a number from the iPhone. Only ever on an explicit click in the app."""
        if not self.enabled or not self.owner or not self.gateways:
            on_done("hands-free link to the iPhone not connected")
            return
        path = next(iter(self.gateways))
        log("appels : appel sortant demandé")

        def done(_value, error):
            on_done(error.message if error else None)

        call_async(self.session, self.owner, path, "org.ofono.VoiceCallManager", "Dial",
                   GLib.Variant("(s)", (number,)), on_done=done, timeout=30000)

    # --- notifications ------------------------------------------------------------

    def set_caller_hint(self, name):
        self.caller_hint = (name, time.monotonic())
        for path, props in self.calls.items():
            if props.get("State") in ("incoming", "waiting"):
                self._refresh(path)

    def has_ringing_call(self):
        return any(c.get("State") in ("incoming", "waiting") for c in self.calls.values())

    def _caller(self, props):
        name = props.get("Name") or ""
        hint, stamp = self.caller_hint
        if not name and hint and time.monotonic() - stamp < 60:
            name = hint
        number = props.get("LineIdentification") or ""
        if name and number and name != number:
            return f"{name} ({number})"
        return name or number or _("Numéro masqué")

    def _refresh(self, path):
        props = self.calls[path]
        state = props.get("State", "")
        if state not in STATE_LABELS:
            self._call_gone(path, keep_record=True)
            return
        summary = f"{_(STATE_LABELS[state])} · {self._caller(props)}"
        body = _("Sur {device}").format(device=self.device_name)
        if state in ("incoming", "waiting"):
            actions = [("answer", pgettext("call", "Répondre")), ("hangup", _("Refuser"))]
            hints = {"urgency": GLib.Variant("y", 2),
                     "category": GLib.Variant("s", "call.incoming"),
                     "resident": GLib.Variant("b", True),
                     "suppress-sound": GLib.Variant("b", True)}
            timeout = 0
        else:
            actions = [("show", _("Afficher")), ("hangup", _("Raccrocher"))]
            hints = {"urgency": GLib.Variant("y", 1),
                     "resident": GLib.Variant("b", True),
                     "suppress-sound": GLib.Variant("b", True)}
            timeout = 0
        self._update_ring()
        self.notifications[path] = self.notifier.notify(
            f"Covalence ({self.device_name})", "io.github.melvincouwez.Covalence.Phone", summary, body, actions, hints,
            replaces=self.notifications.get(path, 0), timeout=timeout,
            on_action=lambda key, p=path: self._on_action(p, key))

    def _update_ring(self):
        """Ring while a call is incoming (not a second call waiting during one), unless the
        iPhone already rings in-band: its ringtone then comes over the hands-free audio."""
        if self.ringer is None:
            return
        incoming = any(c.get("State") == "incoming" for c in self.calls.values())
        in_band = any(t.get("State") == "active" for t in self.transport.values())
        if incoming and not in_band:
            self.ringer.start_ring()
        else:
            self.ringer.stop_ring()

    def _on_action(self, path, key):
        if key in ("show", "default"):
            if self.on_show:
                self.on_show()
            return
        method = {"answer": "Answer", "hangup": "Hangup"}.get(key)
        if not method or path not in self.calls or not self.owner:
            return
        log(f"appels : {'réponse' if method == 'Answer' else 'raccrochage'} demandé")
        call_async(self.session, self.owner, path, CALL, method,
                   what=f"appels : {method} refusé")

    def _state_entered(self, path, state):
        if state == "active" and path not in self.started:
            self.started[path] = time.monotonic()
        if state in ("active", "dialing", "alerting") and self.on_started:
            self.on_started(path)

    def _on_transport_changed(self, _conn, _sender, path, _iface, _signal, params):
        _interface, changed, _invalid = params.unpack()
        self.transport.setdefault(path, {}).update(changed)
        if "State" in changed:
            log(f"appels : audio {'sur ce PC' if changed['State'] == 'active' else 'hors du PC'}")
            self._update_ring()
        self._changed()

    def _changed(self):
        if self.on_calls:
            self.on_calls()

    # --- in-call controls (always on an explicit request from the app) -----------

    # --- demonstration ---------------------------------------------------------------

    DEMO_PATH = "/io/github/melvincouwez/Covalence/demo/call"

    def simulate(self, kind="outgoing", number="+33600000000", name=None):
        """Fake call for trying the interface: no number is dialled."""
        name = name or _("Appel de démonstration")
        self.demo_counter += 1
        path = f"{self.DEMO_PATH}{self.demo_counter}"
        self.demo.add(path)
        self.demo_audio_on_pc = True
        first = "dialing" if kind == "outgoing" else "incoming"
        log(f"appels : simulation d'un appel {'sortant' if kind == 'outgoing' else 'entrant'} "
            "(aucun numéro composé)")
        self._add(path, {CALL: {"State": first, "LineIdentification": number, "Name": name}})
        if kind == "outgoing":
            GLib.timeout_add_seconds(3, lambda: self._demo_state(path, "alerting") and False)
            GLib.timeout_add_seconds(7, lambda: self._demo_state(path, "active") and False)
        GLib.timeout_add_seconds(90, lambda: self._demo_end(path) and False)
        return path

    def _demo_state(self, path, state):
        if path not in self.calls:
            return
        previous = self.calls[path].get("State")
        if previous == state:
            return
        self.calls[path]["State"] = state
        log(f"appels : simulation {previous} → {state}")
        self._state_entered(path, state)
        self._refresh(path)
        self._changed()

    def _demo_end(self, path):
        if path in self.calls:
            log("appels : simulation terminée")
            self.calls[path]["State"] = "disconnected"
            self._refresh(path)  # unknown state: closes the notification, keeps the record
            self.calls.pop(path, None)
            self._call_gone(path, keep_record=True)
        self.demo.discard(path)

    def _only_demo(self):
        live = [p for p, c in self.calls.items() if c.get("State") in STATE_LABELS]
        return bool(live) and all(p in self.demo for p in live)

    def active_calls(self):
        now = time.monotonic()
        result = []
        for path, props in self.calls.items():
            state = props.get("State", "")
            if state not in STATE_LABELS:
                continue
            result.append({
                "path": path, "state": state,
                "number": props.get("LineIdentification") or "",
                "name": props.get("Name") or "",
                "duration": int(now - self.started[path]) if path in self.started else -1,
            })
        return result

    def audio_on_pc(self):
        if self._only_demo():
            return self.demo_audio_on_pc
        return any(t.get("State") == "active" for t in self.transport.values())

    def call_action(self, path, action, on_done):
        if path in self.demo:
            if action == "answer":
                self._demo_state(path, "active")
            elif action == "hangup":
                self._demo_end(path)
            on_done(None)
            return
        method = {"answer": "Answer", "hangup": "Hangup"}.get(action)
        if not method or path not in self.calls or not self.owner:
            on_done("no such call")
            return
        log(f"appels : {'réponse' if method == 'Answer' else 'raccrochage'} demandé")
        call_async(self.session, self.owner, path, CALL, method,
                   on_done=lambda _v, e: on_done(e.message if e else None))

    def set_audio_on_pc(self, on_pc, on_done):
        """Audio of the call on this PC (SCO link up) or on the iPhone (SCO refused)."""
        if self._only_demo():
            self.demo_audio_on_pc = on_pc
            self._changed()
            on_done(None)
            return
        if not self.owner or not self.transport:
            on_done("no hands-free audio link")
            return
        path = next(iter(self.transport))
        log(f"appels : audio demandé {'sur ce PC' if on_pc else 'sur l’iPhone'}")
        call_async(self.session, self.owner, path, "org.freedesktop.DBus.Properties", "Set",
                   GLib.Variant("(ssv)", (TRANSPORT, "RejectSCO", GLib.Variant("b", not on_pc))))
        if on_pc:
            call_async(self.session, self.owner, path, TRANSPORT, "Activate",
                       on_done=lambda _v, e: on_done(e.message if e else None))
        else:
            on_done(None)

    def send_tones(self, tones, on_done):
        tones = "".join(c for c in tones if c in "0123456789*#ABCD")
        if self._only_demo():
            on_done(None)  # a demonstration sends nothing
            return
        if not tones or not self.owner or not self.gateways:
            on_done("nothing to send")
            return
        path = next(iter(self.gateways))
        call_async(self.session, self.owner, path, "org.ofono.VoiceCallManager", "SendTones",
                   GLib.Variant("(s)", (tones,)),
                   on_done=lambda _v, e: on_done(e.message if e else None))

    def set_muted(self, muted):
        """Mute this PC's microphone for the call (default PipeWire source)."""
        if muted == self.muted:
            return
        if self._only_demo():
            self.muted = muted  # shown in the interface, the real microphone is untouched
            self._changed()
            return
        self.muted = muted
        try:
            if muted and self.mute_restore is None:
                out = GLib.spawn_command_line_sync("wpctl get-volume @DEFAULT_AUDIO_SOURCE@")[1]
                self.mute_restore = b"MUTED" in (out or b"")
            GLib.spawn_command_line_async(
                f"wpctl set-mute @DEFAULT_AUDIO_SOURCE@ {1 if muted else 0}")
        except GLib.Error as error:
            log(f"appels : micro non modifié ({error.message})")
        log(f"appels : micro {'coupé' if muted else 'rétabli'}")
        self._changed()

    def _restore_microphone(self):
        if self.mute_restore is not None:
            try:
                GLib.spawn_command_line_async(
                    f"wpctl set-mute @DEFAULT_AUDIO_SOURCE@ {1 if self.mute_restore else 0}")
            except GLib.Error:
                pass
        self.mute_restore = None
        self.muted = False

    def _call_gone(self, path, keep_record=False):
        self.notifier.close(self.notifications.pop(path, 0))
        if self.ringer is not None and not any(
                p != path and c.get("State") == "incoming" for p, c in self.calls.items()):
            self.ringer.stop_ring()
        self.started.pop(path, None)
        if not any(p != path and c.get("State") in STATE_LABELS for p, c in self.calls.items()):
            if path in self.demo:
                self.muted = False
            else:
                self._restore_microphone()
        GLib.idle_add(lambda: self._changed() and False)
        if not keep_record:
            if self.calls.pop(path, None) is not None:
                log("appels : appel terminé")
                if self.on_ended and path not in self.demo:
                    self.on_ended()
