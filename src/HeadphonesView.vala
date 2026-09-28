// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * Écouteurs: battery and settings of AirPods paired with this PC.
 *
 * The daemon talks to the AirPods (covalenced/headphones.py, protocol from
 * LibrePods). The AirPods do not report every setting back, so a change shows
 * at once here and the view catches up on the next HeadphonesChanged.
 *
 * COVALENCE_HEADPHONES_DEMO=1 shows a made-up pair (for screenshots); nothing is
 * sent to the daemon then.
 */

namespace Covalence {
    public class HeadphonesView : Gtk.Box {
        public Daemon daemon { get; construct; }

        private const int[] MODE_VALUES = { 1, 2, 3, 4 };
        private const string[] MODE_LABELS = { N_("Désactivé"), N_("Réduction du bruit"), N_("Transparence"), N_("Adaptatif") };
        private const string[] MODE_FEATURES = { "anc", "anc", "anc", "adaptive" };
        private const int[] CYCLE_BITS = { 1, 2, 4, 8 };

        private bool demo;
        private Variant[] pairs = {};
        private string current = "";
        private bool updating = false;

        private Gtk.Stack stack;
        private Granite.Placeholder waiting;
        private Gtk.DropDown picker;
        private Gtk.Label name_label;
        private Gtk.Label model_label;
        private Gtk.Label state_label;
        private BudGauge left;
        private BudGauge right;
        private BudGauge case_gauge;
        private Gtk.Box noise_box;
        private Gtk.ToggleButton[] mode_buttons = {};
        private Gtk.Box adaptive_box;
        private Gtk.Scale adaptive_scale;
        private Gtk.ListBox options;
        private Gtk.Switch conversation;
        private Gtk.ListBoxRow conversation_row;
        private Gtk.Switch one_bud;
        private Gtk.ListBoxRow one_bud_row;
        private Gtk.Switch auto_pause;
        private Gtk.Box cycle_box;
        private Gtk.CheckButton[] cycle_checks = {};
        private Gtk.Label cycle_hint;
        private uint adaptive_timer = 0;

        public HeadphonesView (Daemon daemon) {
            Object (daemon: daemon, orientation: Gtk.Orientation.VERTICAL, spacing: 0);
        }

        construct {
            demo = Environment.get_variable ("COVALENCE_HEADPHONES_DEMO") == "1";

            var none = new Granite.Placeholder (_("Aucun écouteur appairé")) {
                description = _("Pour appairer vos AirPods : ouvrez le boîtier près du PC, écouteurs "
                              + "dedans, puis maintenez le bouton du boîtier jusqu'à ce que le voyant "
                              + "clignote en blanc. Choisissez-les ensuite dans les paramètres Bluetooth."),
                icon = new ThemedIcon ("audio-headphones")
            };
            var open_bluetooth = none.append_button (new ThemedIcon ("bluetooth"),
                                                     _("Ouvrir les paramètres Bluetooth"),
                                                     _("Pour appairer de nouveaux écouteurs"));
            open_bluetooth.clicked.connect (() => {
                new Gtk.UriLauncher ("settings://network/bluetooth").launch.begin (get_root () as Gtk.Window, null);
            });

            waiting = new Granite.Placeholder ("") {
                icon = new ThemedIcon ("audio-headphones")
            };

            stack = new Gtk.Stack () { vexpand = true };
            stack.add_named (none, "none");
            stack.add_named (waiting, "waiting");
            stack.add_named (build_details (), "details");

            var scroll = new Gtk.ScrolledWindow () {
                child = stack,
                hscrollbar_policy = Gtk.PolicyType.NEVER,
                vexpand = true
            };
            append (scroll);

            if (demo) {
                pairs = { demo_pair () };
                refresh ();
                return;
            }
            daemon.headphones_changed.connect (() => reload.begin ());
            daemon.changed.connect (() => {
                if (pairs.length == 0 && daemon.running && get_mapped ()) {
                    reload.begin ();
                }
            });
            map.connect (() => reload.begin ());
        }

        // --- building --------------------------------------------------------------------

        private Gtk.Widget build_details () {
            picker = new Gtk.DropDown.from_strings ({ "" }) { halign = Gtk.Align.CENTER, visible = false };
            picker.notify["selected"].connect (() => {
                if (!updating && picker.selected < pairs.length) {
                    current = str (pairs[picker.selected], "address");
                    refresh ();
                }
            });

            var icon = new Gtk.Image.from_icon_name ("audio-headphones") { pixel_size = 96 };
            name_label = new Gtk.Label ("") { ellipsize = Pango.EllipsizeMode.END };
            name_label.add_css_class (Granite.HeaderLabel.Size.H2.to_string ());
            var rename = new Gtk.Button.from_icon_name ("document-edit-symbolic") {
                tooltip_text = _("Renommer"),
                valign = Gtk.Align.CENTER
            };
            rename.add_css_class ("flat");
            rename.clicked.connect (ask_name);
            var name_box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 3) { halign = Gtk.Align.CENTER };
            name_box.append (name_label);
            name_box.append (rename);
            model_label = new Gtk.Label ("");
            model_label.add_css_class (Granite.CssClass.DIM);
            state_label = new Gtk.Label ("") { wrap = true, justify = Gtk.Justification.CENTER };
            state_label.add_css_class (Granite.CssClass.DIM);
            state_label.add_css_class (Granite.CssClass.SMALL);

            left = new BudGauge (_("Gauche"));
            right = new BudGauge (_("Droite"));
            case_gauge = new BudGauge (_("Boîtier"));
            var gauges = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
                halign = Gtk.Align.CENTER,
                homogeneous = true,
                margin_top = 12
            };
            gauges.append (left);
            gauges.append (right);
            gauges.append (case_gauge);

            // Noise control
            var modes = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 0) { homogeneous = true };
            modes.add_css_class ("linked");
            Gtk.ToggleButton? first = null;
            for (int i = 0; i < MODE_VALUES.length; i++) {
                var button = new Gtk.ToggleButton.with_label (_(MODE_LABELS[i]));
                if (first == null) {
                    first = button;
                } else {
                    button.group = first;
                }
                var value = MODE_VALUES[i];
                button.toggled.connect (() => {
                    if (!updating && button.active) {
                        send ("mode", new Variant.int32 (value));
                    }
                });
                mode_buttons += button;
                modes.append (button);
            }
            adaptive_scale = new Gtk.Scale.with_range (Gtk.Orientation.HORIZONTAL, 0, 100, 5) {
                hexpand = true,
                draw_value = false
            };
            adaptive_scale.value_changed.connect (() => {
                if (updating) {
                    return;
                }
                // Send once the slider rests, not on every step.
                if (adaptive_timer != 0) {
                    Source.remove (adaptive_timer);
                }
                adaptive_timer = Timeout.add (300, () => {
                    adaptive_timer = 0;
                    send ("adaptive", new Variant.int32 ((int) adaptive_scale.get_value ()));
                    return Source.REMOVE;
                });
            });
            var more = small (_("Plus de bruit"));
            var less = small (_("Moins de bruit"));
            var scale_row = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6);
            scale_row.append (more);
            scale_row.append (adaptive_scale);
            scale_row.append (less);
            adaptive_box = new Gtk.Box (Gtk.Orientation.VERTICAL, 3) { margin_top = 6 };
            adaptive_box.append (new Gtk.Label (_("Niveau de l'audio adaptatif")) { xalign = 0 });
            adaptive_box.append (scale_row);
            noise_box = new Gtk.Box (Gtk.Orientation.VERTICAL, 6);
            noise_box.append (new Granite.HeaderLabel (_("Contrôle du bruit")));
            noise_box.append (modes);
            noise_box.append (adaptive_box);

            // Switches
            options = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
            options.add_css_class (Granite.CssClass.CARD);
            conversation = new Gtk.Switch () { valign = Gtk.Align.CENTER };
            conversation.notify["active"].connect (() => {
                if (!updating) {
                    send ("conversation", new Variant.boolean (conversation.active));
                }
            });
            conversation_row = switch_row (_("Détection de conversation"),
                _("Baisse le son et laisse passer les voix quand vous parlez."), conversation);
            one_bud = new Gtk.Switch () { valign = Gtk.Align.CENTER };
            one_bud.notify["active"].connect (() => {
                if (!updating) {
                    send ("one_bud", new Variant.boolean (one_bud.active));
                }
            });
            one_bud_row = switch_row (_("Réduction du bruit avec un seul écouteur"),
                _("Garde la réduction du bruit quand vous ne portez qu'un écouteur."), one_bud);
            auto_pause = new Gtk.Switch () { valign = Gtk.Align.CENTER };
            auto_pause.notify["active"].connect (() => {
                if (!updating) {
                    send ("auto_pause", new Variant.boolean (auto_pause.active));
                }
            });
            options.append (conversation_row);
            options.append (one_bud_row);
            options.append (switch_row (_("Pause quand vous retirez un écouteur"),
                _("La lecture reprend quand vous le remettez."), auto_pause));

            // Long press cycle
            var checks = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) { halign = Gtk.Align.START };
            for (int i = 0; i < CYCLE_BITS.length; i++) {
                var check = new Gtk.CheckButton.with_label (_(MODE_LABELS[i]));
                check.toggled.connect (on_cycle);
                cycle_checks += check;
                checks.append (check);
            }
            cycle_hint = small (_("Un appui long sur la tige passe d'un mode coché à l'autre (au moins deux)."));
            cycle_hint.xalign = 0;
            cycle_box = new Gtk.Box (Gtk.Orientation.VERTICAL, 6);
            cycle_box.append (new Granite.HeaderLabel (_("Appui long")));
            cycle_box.append (checks);
            cycle_box.append (cycle_hint);

            var notice = small (_("Compatible avec les AirPods. Covalence n'est pas affiliée à Apple. "
                                + "Protocole documenté par le projet LibrePods, merci à ses contributeurs."));
            notice.justify = Gtk.Justification.CENTER;
            notice.max_width_chars = 60;
            notice.margin_top = 12;

            var content = new Gtk.Box (Gtk.Orientation.VERTICAL, 6) {
                margin_top = 18,
                margin_bottom = 24,
                margin_start = 24,
                margin_end = 24,
                width_request = 520,
                halign = Gtk.Align.CENTER
            };
            content.append (picker);
            content.append (icon);
            content.append (name_box);
            content.append (model_label);
            content.append (state_label);
            content.append (gauges);
            content.append (noise_box);
            content.append (new Granite.HeaderLabel (_("Réglages")));
            content.append (options);
            content.append (cycle_box);
            content.append (notice);
            return content;
        }

        private static Gtk.Label small (string text) {
            var label = new Gtk.Label (text) { wrap = true };
            label.add_css_class (Granite.CssClass.DIM);
            label.add_css_class (Granite.CssClass.SMALL);
            return label;
        }

        private static Gtk.ListBoxRow switch_row (string title, string subtitle, Gtk.Switch toggle) {
            var title_label = new Gtk.Label (title) { xalign = 0 };
            var sub = small (subtitle);
            sub.xalign = 0;
            var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
            text.append (title_label);
            text.append (sub);
            var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
                margin_top = 9,
                margin_bottom = 9,
                margin_start = 12,
                margin_end = 12
            };
            box.append (text);
            box.append (toggle);
            return new Gtk.ListBoxRow () { child = box, activatable = false };
        }

        // --- data ------------------------------------------------------------------------

        private static string str (Variant pair, string key) {
            var v = pair.lookup_value (key, VariantType.STRING);
            return v != null ? v.get_string () : "";
        }

        private static int num (Variant pair, string key, int fallback = -1) {
            var v = pair.lookup_value (key, VariantType.INT32);
            return v != null ? v.get_int32 () : fallback;
        }

        private static bool flag (Variant pair, string key) {
            var v = pair.lookup_value (key, VariantType.BOOLEAN);
            return v != null && v.get_boolean ();
        }

        private static bool has_feature (Variant pair, string feature) {
            var v = pair.lookup_value ("features", new VariantType ("as"));
            if (v == null) {
                return false;
            }
            foreach (var f in v.get_strv ()) {
                if (f == feature) {
                    return true;
                }
            }
            return false;
        }

        private async void reload () {
            if (!daemon.running) {
                return;
            }
            pairs = yield daemon.call_list ("ListHeadphones");
            refresh ();
        }

        private Variant? pair () {
            foreach (var p in pairs) {
                if (str (p, "address") == current) {
                    return p;
                }
            }
            // Prefer a connected pair.
            foreach (var p in pairs) {
                if (flag (p, "connected")) {
                    current = str (p, "address");
                    return p;
                }
            }
            if (pairs.length > 0) {
                current = str (pairs[0], "address");
                return pairs[0];
            }
            return null;
        }

        private void refresh () {
            var p = pair ();
            if (p == null) {
                stack.visible_child_name = "none";
                return;
            }
            updating = true;

            // Several pairs: a picker at the top.
            string[] names = {};
            uint selected = 0;
            for (int i = 0; i < pairs.length; i++) {
                names += str (pairs[i], "name");
                if (str (pairs[i], "address") == current) {
                    selected = i;
                }
            }
            picker.model = new Gtk.StringList (names);
            picker.selected = selected;
            picker.visible = pairs.length > 1;

            if (!flag (p, "connected")) {
                waiting.title = str (p, "name");
                waiting.description = _("Hors de portée ou dans le boîtier fermé. Sortez-les du boîtier "
                                      + "pour les connecter à ce PC.");
                stack.visible_child_name = "waiting";
                updating = false;
                return;
            }
            if (!flag (p, "linked")) {
                waiting.title = str (p, "name");
                waiting.description = _("Connectés. Lecture de l'état des écouteurs…");
                stack.visible_child_name = "waiting";
                updating = false;
                return;
            }
            stack.visible_child_name = "details";

            name_label.label = str (p, "name");
            var model = str (p, "model");
            model_label.label = model != "" ? _(model) : "AirPods";
            model_label.tooltip_text = str (p, "firmware") != "" ? _("Micrologiciel %s").printf (str (p, "firmware")) : null;
            state_label.label = wearing (str (p, "ear_left"), str (p, "ear_right"));

            left.update (num (p, "left"), flag (p, "left_charging"), str (p, "ear_left"));
            right.update (num (p, "right"), flag (p, "right_charging"), str (p, "ear_right"));
            case_gauge.update (num (p, "case"), flag (p, "case_charging"), "");

            var mode = num (p, "mode", 0);
            noise_box.visible = has_feature (p, "anc");
            for (int i = 0; i < mode_buttons.length; i++) {
                mode_buttons[i].visible = has_feature (p, MODE_FEATURES[i]);
                mode_buttons[i].active = MODE_VALUES[i] == mode;
            }
            adaptive_box.visible = mode == 4 && has_feature (p, "adaptive");
            var level = num (p, "adaptive");
            if (level >= 0) {
                adaptive_scale.set_value (level);
            }

            conversation_row.visible = has_feature (p, "conversation");
            conversation.active = num (p, "conversation", 0) == 1;
            one_bud_row.visible = has_feature (p, "one_bud");
            one_bud.active = num (p, "one_bud", 0) == 1;
            auto_pause.active = flag (p, "auto_pause");

            cycle_box.visible = has_feature (p, "anc");
            var cycle = num (p, "cycle", 0);
            for (int i = 0; i < cycle_checks.length; i++) {
                cycle_checks[i].visible = has_feature (p, MODE_FEATURES[i]);
                // Never set from Covalence: show the usual default (noise cancellation and transparency).
                cycle_checks[i].active = cycle != 0 ? (cycle & CYCLE_BITS[i]) != 0 : (i == 1 || i == 2);
            }
            updating = false;
        }

        private static string wearing (string left, string right) {
            var in_ear = (left == "in" ? 1 : 0) + (right == "in" ? 1 : 0);
            if (in_ear == 2) {
                return _("Dans vos oreilles");
            }
            if (in_ear == 1) {
                return _("Un écouteur porté");
            }
            if (left == "case" && right == "case") {
                return _("Dans le boîtier");
            }
            return _("Pas dans vos oreilles");
        }

        // --- changes ---------------------------------------------------------------------

        private void send (string key, Variant value) {
            if (demo || current == "") {
                return;
            }
            daemon.call.begin ("SetHeadphones", new Variant ("(ssv)", current, key, value));
        }

        private void on_cycle () {
            if (updating) {
                return;
            }
            int mask = 0;
            for (int i = 0; i < cycle_checks.length; i++) {
                if (cycle_checks[i].active && cycle_checks[i].visible) {
                    mask |= CYCLE_BITS[i];
                }
            }
            if (bin_count (mask) < 2) {
                cycle_hint.add_css_class (Granite.CssClass.ERROR);
                return;
            }
            cycle_hint.remove_css_class (Granite.CssClass.ERROR);
            send ("cycle", new Variant.int32 (mask));
        }

        private static int bin_count (int mask) {
            int n = 0;
            for (; mask != 0; mask >>= 1) {
                n += mask & 1;
            }
            return n;
        }

        private void ask_name () {
            var entry = new Gtk.Entry () { text = name_label.label, max_length = 32, activates_default = true };
            var dialog = new Granite.MessageDialog.with_image_from_icon_name (
                _("Renommer les écouteurs"),
                _("Le nouveau nom est enregistré dans les écouteurs et s'affiche sur vos autres appareils."),
                "audio-headphones", Gtk.ButtonsType.CANCEL) {
                transient_for = get_root () as Gtk.Window,
                modal = true
            };
            dialog.custom_bin.append (entry);
            var ok = dialog.add_button (_("Renommer"), Gtk.ResponseType.ACCEPT);
            ok.add_css_class (Granite.CssClass.SUGGESTED);
            dialog.default_widget = ok;
            dialog.response.connect ((response) => {
                var name = entry.text.strip ();
                if (response == Gtk.ResponseType.ACCEPT && name != "") {
                    name_label.label = name;
                    send ("name", new Variant.string (name));
                }
                dialog.destroy ();
            });
            dialog.present ();
        }

        private static Variant demo_pair () {
            var b = new VariantBuilder (new VariantType ("a{sv}"));
            b.add ("{sv}", "address", new Variant.string ("00:00:00:00:00:00"));
            b.add ("{sv}", "name", new Variant.string ("AirPods Pro de démonstration"));
            b.add ("{sv}", "model", new Variant.string ("AirPods Pro 2 (USB-C)"));
            b.add ("{sv}", "firmware", new Variant.string ("0.0"));
            b.add ("{sv}", "connected", new Variant.boolean (true));
            b.add ("{sv}", "linked", new Variant.boolean (true));
            b.add ("{sv}", "left", new Variant.int32 (80));
            b.add ("{sv}", "right", new Variant.int32 (75));
            b.add ("{sv}", "case", new Variant.int32 (40));
            b.add ("{sv}", "left_charging", new Variant.boolean (false));
            b.add ("{sv}", "right_charging", new Variant.boolean (false));
            b.add ("{sv}", "case_charging", new Variant.boolean (true));
            b.add ("{sv}", "ear_left", new Variant.string ("in"));
            b.add ("{sv}", "ear_right", new Variant.string ("in"));
            b.add ("{sv}", "mode", new Variant.int32 (4));
            b.add ("{sv}", "cycle", new Variant.int32 (0));
            b.add ("{sv}", "conversation", new Variant.int32 (1));
            b.add ("{sv}", "adaptive", new Variant.int32 (50));
            b.add ("{sv}", "one_bud", new Variant.int32 (2));
            b.add ("{sv}", "features", new Variant.strv ({ "anc", "adaptive", "conversation", "ear", "one_bud" }));
            b.add ("{sv}", "auto_pause", new Variant.boolean (true));
            return b.end ();
        }
    }

    /* One battery: a ring with the level, charge bolt, label and where it is. */
    public class BudGauge : Gtk.Box {
        private Gtk.DrawingArea ring;
        private Gtk.Label level_label;
        private Gtk.Label place_label;
        private int level = -1;
        private bool charging = false;

        public BudGauge (string title) {
            Object (orientation: Gtk.Orientation.VERTICAL, spacing: 3, width_request: 110);
            ring = new Gtk.DrawingArea () {
                content_width = 64,
                content_height = 64,
                halign = Gtk.Align.CENTER
            };
            ring.set_draw_func (draw);
            level_label = new Gtk.Label ("");
            level_label.add_css_class (Granite.HeaderLabel.Size.H4.to_string ());
            var title_label = new Gtk.Label (title);
            place_label = new Gtk.Label ("");
            place_label.add_css_class (Granite.CssClass.DIM);
            place_label.add_css_class (Granite.CssClass.SMALL);
            append (ring);
            append (level_label);
            append (title_label);
            append (place_label);
        }

        public void update (int level, bool charging, string place) {
            this.level = level;
            this.charging = charging;
            level_label.label = level >= 0 ? "%d %%".printf (level) : "—";
            switch (place) {
                case "in":
                    place_label.label = _("dans l'oreille");
                    break;
                case "out":
                    place_label.label = _("retiré");
                    break;
                case "case":
                    place_label.label = _("dans le boîtier");
                    break;
                default:
                    place_label.label = charging ? _("en charge") : "";
                    break;
            }
            ring.queue_draw ();
        }

        private void draw (Gtk.DrawingArea area, Cairo.Context cr, int width, int height) {
            var fg = area.get_color ();
            double cx = width / 2.0, cy = height / 2.0, r = double.min (width, height) / 2.0 - 4;
            cr.set_line_width (6);
            cr.set_line_cap (Cairo.LineCap.ROUND);
            cr.set_source_rgba (fg.red, fg.green, fg.blue, 0.15);
            cr.arc (cx, cy, r, 0, 2 * Math.PI);
            cr.stroke ();
            if (level < 0) {
                return;
            }
            // elementary palette: lime when charging or high, banana at 20 %, strawberry at 10 %.
            if (charging || level > 20) {
                cr.set_source_rgb (0x68 / 255.0, 0xb7 / 255.0, 0x23 / 255.0);
            } else if (level > 10) {
                cr.set_source_rgb (0xf9 / 255.0, 0xc4 / 255.0, 0x40 / 255.0);
            } else {
                cr.set_source_rgb (0xed / 255.0, 0x53 / 255.0, 0x53 / 255.0);
            }
            var start = -Math.PI / 2;
            cr.arc (cx, cy, r, start, start + 2 * Math.PI * level.clamp (1, 100) / 100.0);
            cr.stroke ();
            if (charging) {
                // Small bolt in the middle.
                cr.set_source_rgba (fg.red, fg.green, fg.blue, 0.8);
                cr.move_to (cx + 2, cy - 11);
                cr.line_to (cx - 6, cy + 2);
                cr.line_to (cx - 0.5, cy + 2);
                cr.line_to (cx - 2, cy + 11);
                cr.line_to (cx + 6, cy - 2);
                cr.line_to (cx + 0.5, cy - 2);
                cr.close_path ();
                cr.fill ();
            }
        }
    }
}
