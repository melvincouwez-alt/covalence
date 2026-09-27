// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * Phone calls on this PC through the iPhone (HFP): the in-call window and the
 * keypad. The daemon opens the window when a call rings out or is answered;
 * incoming calls ring in a notification (Répondre / Refuser) and here if open.
 *
 * Audio goes through this PC's speakers and microphone while the hands-free
 * audio link is up; "Audio : iPhone" hands it back to the phone.
 */

namespace Covalence {
    /* 0-9, * and # as a 3 x 4 grid of round buttons, with letters like a phone. */
    public class Keypad : Gtk.Grid {
        public signal void pressed (string key);

        private const string[] KEYS = { "1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#" };
        private const string[] LETTERS = { "", "ABC", "DEF", "GHI", "JKL", "MNO", "PQRS", "TUV", "WXYZ",
                                           "", "+", "" };

        construct {
            row_spacing = 10;
            column_spacing = 16;
            halign = Gtk.Align.CENTER;
            for (int i = 0; i < KEYS.length; i++) {
                var key = KEYS[i];
                var digit = new Gtk.Label (key);
                digit.add_css_class ("keypad-digit");
                var letters = new Gtk.Label (LETTERS[i]);
                letters.add_css_class ("keypad-letters");
                var box = new Gtk.Box (Gtk.Orientation.VERTICAL, 0) { valign = Gtk.Align.CENTER };
                box.append (digit);
                box.append (letters);
                var button = new Gtk.Button () { child = box };
                button.add_css_class ("keypad-key");
                button.add_css_class ("circular");
                button.update_property (Gtk.AccessibleProperty.LABEL, key, -1);
                button.clicked.connect (() => pressed (key));
                attach (button, i % 3, i / 3);
            }
        }
    }

    /* Number field over the keypad, then Appeler (calls from the iPhone, on click only). */
    public class DialPad : Gtk.Box {
        public Daemon daemon { get; construct; }
        public signal void dialled ();
        private Gtk.Entry number;

        public DialPad (Daemon daemon) {
            Object (daemon: daemon, orientation: Gtk.Orientation.VERTICAL, spacing: 14);
        }

        construct {
            number = new Gtk.Entry () {
                placeholder_text = _("Numéro"),
                input_purpose = Gtk.InputPurpose.PHONE,
                xalign = 0.5f
            };
            number.add_css_class ("dial-number");
            var keypad = new Keypad ();
            keypad.pressed.connect ((key) => {
                number.text += key;
                number.set_position (-1);
            });
            var call = new CallButton (daemon, "", null) { halign = Gtk.Align.CENTER };
            call.remove_css_class ("flat");
            call.add_css_class ("call-green");
            call.add_css_class ("circular");
            call.number_source = () => number.text.strip ();
            call.dialled.connect (() => {
                number.text = "";
                dialled ();
            });
            number.activate.connect (() => call.clicked ());
            append (number);
            append (keypad);
            append (call);
        }

        public void focus_number () {
            number.grab_focus ();
        }
    }

    /* "Composer un numéro" button in the call list: the dial pad in a popover. */
    public class DialPopover : Gtk.Popover {
        public Daemon daemon { get; construct; }

        public DialPopover (Daemon daemon) {
            Object (daemon: daemon);
        }

        construct {
            var pad = new DialPad (daemon) {
                margin_top = 12,
                margin_bottom = 12,
                margin_start = 12,
                margin_end = 12
            };
            pad.dialled.connect (() => popdown ());
            child = pad;
            show.connect (() => pad.focus_number ());
        }
    }

    /* Téléphone tab: dial pad on the left, the call history on the right. */
    public class PhoneView : Gtk.Box {
        public Daemon daemon { get; construct; }
        public CallsView history { get; private set; }

        public PhoneView (Daemon daemon) {
            Object (daemon: daemon, orientation: Gtk.Orientation.HORIZONTAL, spacing: 0);
        }

        construct {
            var pad = new DialPad (daemon) {
                valign = Gtk.Align.CENTER,
                halign = Gtk.Align.CENTER,
                margin_start = 36,
                margin_end = 36,
                width_request = 280
            };
            history = new CallsView (daemon, false) { hexpand = true };
            append (pad);
            append (new Gtk.Separator (Gtk.Orientation.VERTICAL));
            append (history);
        }
    }

    public class CallWindow : Gtk.Window {
        private Daemon daemon;
        private Avatar avatar;
        private Gtk.Label name_label;
        private Gtk.Label status_label;
        private Gtk.Stack actions;
        private Gtk.ToggleButton mute;
        private Gtk.ToggleButton keypad_toggle;
        private Gtk.ToggleButton audio_pc;
        private Gtk.Revealer keypad_revealer;
        private string? call_path = null;
        private int duration = -1;
        private bool updating = false;
        private bool ended = false;
        private uint tick = 0;

        public CallWindow (Gtk.Application app) {
            Object (application: app, title: _("Appel"), default_width: 340, resizable: false);
        }

        construct {
            add_css_class ("call-window");
            var header = new Gtk.HeaderBar ();
            header.add_css_class ("flat");
            header.title_widget = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 0);
            titlebar = header;

            avatar = new Avatar (96);
            name_label = new Gtk.Label ("") { wrap = true, justify = Gtk.Justification.CENTER };
            name_label.add_css_class (Granite.HeaderLabel.Size.H2.to_string ());
            status_label = new Gtk.Label ("") { justify = Gtk.Justification.CENTER };
            status_label.add_css_class (Granite.CssClass.DIM);
            status_label.add_css_class ("numeric");

            mute = option ("microphone-sensitivity-muted-symbolic", _("Micro coupé"));
            mute.toggled.connect (() => {
                if (!updating) {
                    daemon.call.begin ("SetMuted", new Variant ("(b)", mute.active));
                }
            });
            keypad_toggle = option ("input-dialpad-symbolic", _("Clavier"));
            audio_pc = option ("audio-speakers-symbolic", _("Audio sur ce PC"));
            audio_pc.toggled.connect (() => {
                if (!updating) {
                    daemon.call_send.begin ("SetCallAudio", new Variant ("(b)", audio_pc.active));
                }
            });
            var options = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 18) { halign = Gtk.Align.CENTER };
            options.append (labelled (mute, _("Silence")));
            options.append (labelled (keypad_toggle, _("Clavier")));
            options.append (labelled (audio_pc, _("Audio PC")));

            var keypad = new Keypad () { margin_top = 6 };
            keypad.pressed.connect ((key) => {
                daemon.call_send.begin ("SendTones", new Variant ("(s)", key));
            });
            keypad_revealer = new Gtk.Revealer () { child = keypad };
            keypad_toggle.bind_property ("active", keypad_revealer, "reveal-child");

            var hangup = round ("call-stop-symbolic", "call-red", _("Raccrocher"));
            hangup.clicked.connect (() => act ("hangup"));
            var decline = round ("call-stop-symbolic", "call-red", _("Refuser"));
            decline.clicked.connect (() => act ("hangup"));
            var answer = round ("call-start-symbolic", "call-green", C_("call", "Répondre"));
            answer.clicked.connect (() => act ("answer"));
            var ringing = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 64) { halign = Gtk.Align.CENTER };
            ringing.append (labelled (decline, _("Refuser")));
            ringing.append (labelled (answer, C_("call", "Répondre")));
            var in_call = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 0) { halign = Gtk.Align.CENTER };
            in_call.append (labelled (hangup, _("Raccrocher")));
            actions = new Gtk.Stack () { vhomogeneous = false };
            actions.add_named (ringing, "ringing");
            actions.add_named (in_call, "call");
            actions.add_named (new Gtk.Box (Gtk.Orientation.VERTICAL, 0), "none");

            var content = new Gtk.Box (Gtk.Orientation.VERTICAL, 12) {
                margin_start = 24,
                margin_end = 24,
                margin_bottom = 24
            };
            content.append (avatar);
            content.append (name_label);
            content.append (status_label);
            content.append (new Gtk.Box (Gtk.Orientation.VERTICAL, 0) { height_request = 12 });
            content.append (options);
            content.append (keypad_revealer);
            content.append (new Gtk.Box (Gtk.Orientation.VERTICAL, 0) { height_request = 12 });
            content.append (actions);
            child = content;

            daemon = new Daemon ();
            daemon.active_calls_changed.connect (() => reload.begin ());
            daemon.changed.connect (update_toggles);
            daemon.connect_bus.begin ((obj, res) => {
                daemon.connect_bus.end (res);
                reload.begin ();
            });
            tick = Timeout.add_seconds (1, () => {
                if (duration >= 0) {
                    duration++;
                    status_label.label = _("Appel en cours · %s").printf (format_duration (duration));
                }
                return Source.CONTINUE;
            });
            close_request.connect (() => {
                if (tick != 0) {
                    Source.remove (tick);
                    tick = 0;
                }
                return false;
            });
        }

        private static string format_duration (int seconds) {
            return seconds >= 3600
                ? "%d:%02d:%02d".printf (seconds / 3600, (seconds / 60) % 60, seconds % 60)
                : "%02d:%02d".printf (seconds / 60, seconds % 60);
        }

        private Gtk.ToggleButton option (string icon, string tip) {
            var button = new Gtk.ToggleButton () { icon_name = icon, tooltip_text = tip };
            button.add_css_class ("circular");
            button.add_css_class ("call-option");
            return button;
        }

        private Gtk.Button round (string icon, string css, string tip) {
            var button = new Gtk.Button.from_icon_name (icon) { tooltip_text = tip };
            button.add_css_class ("circular");
            button.add_css_class (css);
            return button;
        }

        private Gtk.Widget labelled (Gtk.Widget button, string text) {
            var label = new Gtk.Label (text);
            label.add_css_class (Granite.CssClass.SMALL);
            label.add_css_class (Granite.CssClass.DIM);
            var box = new Gtk.Box (Gtk.Orientation.VERTICAL, 4);
            box.append (button);
            box.append (label);
            return box;
        }

        private void act (string action) {
            if (call_path == null) {
                return;
            }
            daemon.call_send.begin ("CallAction", new Variant ("(os)", call_path, action));
        }

        private void update_toggles () {
            updating = true;
            mute.active = daemon.get_bool ("MicMuted");
            audio_pc.active = daemon.get_bool ("AudioOnPC");
            updating = false;
        }

        private async void reload () {
            var calls = yield daemon.call_list ("ListActiveCalls");
            VariantDict? chosen = null;
            foreach (var item in calls) {
                var d = new VariantDict (item);
                var state = dict_string (d, "state");
                if (chosen == null || state == "active" || state == "incoming") {
                    chosen = d;
                }
            }
            update_toggles ();
            if (chosen == null) {
                if (call_path != null && !ended) {
                    ended = true;
                    duration = -1;
                    status_label.label = _("Appel terminé");
                    actions.visible_child_name = "none";
                    Timeout.add_seconds (2, () => {
                        close ();
                        return Source.REMOVE;
                    });
                } else if (call_path == null) {
                    status_label.label = _("Aucun appel");
                    actions.visible_child_name = "none";
                }
                return;
            }
            ended = false;
            var v = chosen.lookup_value ("path", VariantType.OBJECT_PATH);
            call_path = v != null ? v.get_string () : null;
            var name = dict_string (chosen, "name");
            name_label.label = name;
            avatar.show_person (name, dict_string (chosen, "avatar"));
            var state = dict_string (chosen, "state");
            var dur = chosen.lookup_value ("duration", VariantType.INT32);
            switch (state) {
                case "incoming":
                case "waiting":
                    duration = -1;
                    status_label.label = state == "incoming" ? _("Appel entrant") : _("Appel en attente");
                    actions.visible_child_name = "ringing";
                    break;
                case "dialing":
                case "alerting":
                    duration = -1;
                    status_label.label = _("Appel en cours de numérotation…");
                    actions.visible_child_name = "call";
                    break;
                case "held":
                    duration = -1;
                    status_label.label = _("En attente");
                    actions.visible_child_name = "call";
                    break;
                default:
                    duration = dur != null ? dur.get_int32 () : 0;
                    status_label.label = _("Appel en cours · %s").printf (format_duration (int.max (duration, 0)));
                    actions.visible_child_name = "call";
                    break;
            }
        }
    }
}

namespace Covalence {
    /*
     * Green bar at the top of Covalence's windows while a call is going on: who,
     * how long, and the everyday controls (mute, audio on this PC, keypad in the
     * call window, hang up; answer or decline while it rings).
     */
    public class CallBar : Gtk.Box {
        public Daemon daemon { get; construct; }

        private Gtk.Revealer revealer;
        private Avatar avatar;
        private Gtk.Label name_label;
        private Gtk.Label status_label;
        private Gtk.ToggleButton mute;
        private Gtk.ToggleButton audio;
        private Gtk.Button answer;
        private Gtk.Button hangup;
        private string? path = null;
        private int duration = -1;
        private bool updating = false;
        private bool loaded = false;

        public CallBar (Daemon daemon) {
            Object (daemon: daemon, orientation: Gtk.Orientation.VERTICAL, spacing: 0);
        }

        construct {
            avatar = new Avatar (32);
            name_label = new Gtk.Label ("") { xalign = 0, ellipsize = Pango.EllipsizeMode.END };
            name_label.add_css_class ("call-bar-name");
            status_label = new Gtk.Label ("") { xalign = 0 };
            status_label.add_css_class ("numeric");
            status_label.add_css_class (Granite.CssClass.SMALL);
            var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 0) { hexpand = true, valign = Gtk.Align.CENTER };
            text.append (name_label);
            text.append (status_label);

            mute = new Gtk.ToggleButton () { icon_name = "microphone-sensitivity-muted-symbolic",
                                             tooltip_text = _("Couper le micro") };
            mute.toggled.connect (() => {
                if (!updating) {
                    daemon.call.begin ("SetMuted", new Variant ("(b)", mute.active));
                }
            });
            audio = new Gtk.ToggleButton () { icon_name = "audio-speakers-symbolic",
                                              tooltip_text = _("Son sur ce PC (sinon sur l'iPhone)") };
            audio.toggled.connect (() => {
                if (!updating) {
                    daemon.call_send.begin ("SetCallAudio", new Variant ("(b)", audio.active));
                }
            });
            var show = new Gtk.Button.from_icon_name ("input-dialpad-symbolic") {
                tooltip_text = _("Afficher l'appel et le clavier")
            };
            show.clicked.connect (() => {
                var app = GLib.Application.get_default ();
                if (app != null) {
                    app.activate_action ("show-call", null);
                }
            });
            answer = new Gtk.Button.from_icon_name ("call-start-symbolic") { tooltip_text = C_("call", "Répondre") };
            answer.add_css_class ("call-green-small");
            answer.clicked.connect (() => act ("answer"));
            hangup = new Gtk.Button.from_icon_name ("call-stop-symbolic") { tooltip_text = _("Raccrocher") };
            hangup.add_css_class ("call-red-small");
            hangup.clicked.connect (() => act ("hangup"));
            foreach (var b in new Gtk.Widget[] { mute, audio, show, answer, hangup }) {
                b.add_css_class ("circular");
                b.valign = Gtk.Align.CENTER;
            }

            var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 8) {
                margin_top = 6,
                margin_bottom = 6,
                margin_start = 12,
                margin_end = 12
            };
            box.add_css_class ("call-bar-content");
            box.append (avatar);
            box.append (text);
            box.append (mute);
            box.append (audio);
            box.append (show);
            box.append (answer);
            box.append (hangup);
            var bar = new Gtk.Box (Gtk.Orientation.VERTICAL, 0);
            bar.add_css_class ("call-bar");
            bar.append (box);
            revealer = new Gtk.Revealer () { child = bar, reveal_child = false };
            append (revealer);

            daemon.active_calls_changed.connect (() => reload.begin ());
            daemon.changed.connect (() => {
                // First contact with the daemon: a call may already be going on.
                if (!loaded && daemon.running) {
                    loaded = true;
                    reload.begin ();
                }
                updating = true;
                mute.active = daemon.get_bool ("MicMuted");
                audio.active = daemon.get_bool ("AudioOnPC");
                updating = false;
            });
            map.connect (() => reload.begin ());
            Timeout.add_seconds (1, () => {
                if (duration >= 0) {
                    duration++;
                    status_label.label = _("En cours · %02d:%02d").printf (duration / 60, duration % 60);
                }
                return Source.CONTINUE;
            });
        }

        private void act (string action) {
            if (path != null) {
                daemon.call_send.begin ("CallAction", new Variant ("(os)", path, action));
            }
        }

        private async void reload () {
            var calls = yield daemon.call_list ("ListActiveCalls");
            VariantDict? chosen = null;
            foreach (var item in calls) {
                var d = new VariantDict (item);
                var state = dict_string (d, "state");
                if (chosen == null || state == "active" || state == "incoming") {
                    chosen = d;
                }
            }
            revealer.reveal_child = chosen != null;
            if (chosen == null) {
                path = null;
                duration = -1;
                return;
            }
            var v = chosen.lookup_value ("path", VariantType.OBJECT_PATH);
            path = v != null ? v.get_string () : null;
            var name = dict_string (chosen, "name");
            name_label.label = name;
            avatar.show_person (name, dict_string (chosen, "avatar"));
            var state = dict_string (chosen, "state");
            var ringing = state == "incoming" || state == "waiting";
            answer.visible = ringing;
            mute.visible = !ringing;
            audio.visible = !ringing;
            hangup.tooltip_text = ringing ? _("Refuser") : _("Raccrocher");
            if (state == "active") {
                var dur = chosen.lookup_value ("duration", VariantType.INT32);
                duration = dur != null ? int.max (dur.get_int32 (), 0) : 0;
                status_label.label = _("En cours · %02d:%02d").printf (duration / 60, duration % 60);
            } else {
                duration = -1;
                status_label.label = ringing ? _("Appel entrant")
                                   : state == "held" ? _("En attente") : _("Appel sortant…");
            }
        }
    }
}
