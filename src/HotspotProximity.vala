/*
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2026 Melvin Couwez
 *
 * Two cards, each usable on its own page:
 * HotspotCard: Internet through the iPhone (Bluetooth tethering: Tethering, TetheringState,
 * TetheringError and SetTethering on the daemon).
 * ProximityCard: lock the PC when the iPhone moves away (daemon property Proximity).
 */

namespace Covalence {

    private static string dict_str (Variant? dict, string key) {
        var v = dict != null ? dict.lookup_value (key, VariantType.STRING) : null;
        return v != null ? v.get_string () : "";
    }

    public class HotspotCard : Gtk.Box {
        private Daemon daemon;
        private Gtk.Label status;
        private Gtk.Label error;
        private Gtk.Button button;
        private Gtk.Spinner spinner;
        private string state = "";

        public HotspotCard (Daemon daemon) {
            this.daemon = daemon;
            var list = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, hexpand = true };
            list.add_css_class (Granite.CssClass.CARD);
            append (list);

            var icon = new Gtk.Image.from_icon_name ("network-wireless") { pixel_size = 32 };
            var title = new Gtk.Label (_("Internet via l'iPhone")) { xalign = 0 };
            status = new Gtk.Label ("") { xalign = 0, wrap = true };
            status.add_css_class (Granite.CssClass.DIM);
            status.add_css_class (Granite.CssClass.SMALL);
            error = new Gtk.Label ("") { xalign = 0, wrap = true, visible = false };
            error.add_css_class (Granite.CssClass.ERROR);
            error.add_css_class (Granite.CssClass.SMALL);
            var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
            text.append (title);
            text.append (status);
            text.append (error);
            spinner = new Gtk.Spinner () { valign = Gtk.Align.CENTER, visible = false };
            button = new Gtk.Button.with_label (_("Se connecter via l'iPhone")) { valign = Gtk.Align.CENTER };
            button.clicked.connect (() => {
                button.sensitive = false;
                daemon.call.begin ("SetTethering", new Variant ("(b)", state != "on"), (obj, res) => {
                    daemon.call.end (res);
                    button.sensitive = true;
                });
            });
            var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
                margin_top = 9,
                margin_bottom = 9,
                margin_start = 12,
                margin_end = 12
            };
            box.append (icon);
            box.append (text);
            box.append (spinner);
            box.append (button);
            list.append (new Gtk.ListBoxRow () { child = box, activatable = false });

            daemon.changed.connect (refresh);
            refresh ();
        }

        private void refresh () {
            state = daemon.get_string ("TetheringState");
            var message = daemon.get_string ("TetheringError");
            spinner.visible = spinner.spinning = state == "connecting";
            button.visible = state != "unavailable" && state != "";
            button.label = state == "on" ? _("Se déconnecter") : _("Se connecter via l'iPhone");
            button.sensitive = state != "connecting";
            switch (state) {
                case "on":
                    status.label = _("Connecté : ce PC utilise la connexion de l'iPhone.");
                    break;
                case "connecting":
                    status.label = _("Connexion en cours…");
                    break;
                case "unavailable":
                    status.label = _("Indisponible : iPhone non connecté, ou partage de connexion "
                                     + "Bluetooth non proposé par l'iPhone.");
                    break;
                default:
                    status.label = _("Partage de connexion de l'iPhone, en Bluetooth. Sur l'iPhone : "
                                     + "Réglages › Partage de connexion › « Autoriser d'autres "
                                     + "utilisateurs ».");
                    break;
            }
            error.label = message;
            error.visible = state == "failed" && message != "";
        }
    }

    public class ProximityCard : Gtk.Box {
        private const string[] DISTANCES = { "near", "medium", "far" };
        private const uint[] DELAYS = { 10, 30, 60, 120 };

        private Daemon daemon;
        private Gtk.Switch toggle;
        private Gtk.DropDown distance;
        private Gtk.DropDown delay;
        private bool updating = false;

        public ProximityCard (Daemon daemon) {
            this.daemon = daemon;
            var list = new Gtk.ListBox () {
                selection_mode = Gtk.SelectionMode.NONE,
                show_separators = true,
                hexpand = true
            };
            list.add_css_class (Granite.CssClass.CARD);
            append (list);

            toggle = new Gtk.Switch () { valign = Gtk.Align.CENTER };
            list.append (row (_("Verrouiller le PC quand l'iPhone s'éloigne"),
                         _("Verrouille seulement, ne déverrouille jamais. Rien pendant un appel, ni tant "
                           + "que l'iPhone n'a pas été vu depuis l'ouverture de session."), toggle));
            distance = new Gtk.DropDown.from_strings ({ _("Proche (même bureau)"), _("Moyenne (même pièce)"),
                                                        _("Loin (portée Bluetooth)") }) {
                valign = Gtk.Align.CENTER
            };
            list.append (row (_("Distance"),
                         _("Selon la force du signal, quand le Bluetooth la donne ; sinon, perte de la "
                           + "liaison (une dizaine de mètres)."), distance));
            delay = new Gtk.DropDown.from_strings ({ _("10 secondes"), _("30 secondes"), _("1 minute"),
                                                     _("2 minutes") }) {
                valign = Gtk.Align.CENTER
            };
            list.append (row (_("Délai"), _("Durée d'éloignement avant de verrouiller"), delay));

            toggle.notify["active"].connect (send);
            distance.notify["selected"].connect (send);
            delay.notify["selected"].connect (send);
            daemon.changed.connect (refresh);
            refresh ();
        }

        private static Gtk.ListBoxRow row (string title, string subtitle, Gtk.Widget control) {
            var title_label = new Gtk.Label (title) { xalign = 0 };
            var subtitle_label = new Gtk.Label (subtitle) { xalign = 0, wrap = true };
            subtitle_label.add_css_class (Granite.CssClass.DIM);
            subtitle_label.add_css_class (Granite.CssClass.SMALL);
            var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
            text.append (title_label);
            text.append (subtitle_label);
            control.update_property (Gtk.AccessibleProperty.LABEL, title, -1);
            var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
                margin_top = 9,
                margin_bottom = 9,
                margin_start = 12,
                margin_end = 12
            };
            box.append (text);
            box.append (control);
            return new Gtk.ListBoxRow () { child = box, activatable = false };
        }

        private void send () {
            if (updating) {
                return;
            }
            distance.sensitive = delay.sensitive = toggle.active;
            daemon.call.begin ("SetProximity", new Variant ("(bsu)", toggle.active,
                DISTANCES[distance.selected.clamp (0, DISTANCES.length - 1)],
                DELAYS[delay.selected.clamp (0, DELAYS.length - 1)]));
        }

        private void refresh () {
            var dict = daemon.get_value ("Proximity");
            if (dict == null) {
                return;
            }
            updating = true;
            var enabled = dict.lookup_value ("enabled", VariantType.BOOLEAN);
            toggle.active = enabled != null && enabled.get_boolean ();
            var wanted = dict_str (dict, "distance");
            for (uint i = 0; i < DISTANCES.length; i++) {
                if (DISTANCES[i] == wanted) {
                    distance.selected = i;
                }
            }
            var seconds = dict.lookup_value ("delay", VariantType.UINT32);
            for (uint i = 0; i < DELAYS.length; i++) {
                if (seconds != null && DELAYS[i] == seconds.get_uint32 ()) {
                    delay.selected = i;
                }
            }
            distance.sensitive = delay.sensitive = toggle.active;
            updating = false;
        }
    }
}
