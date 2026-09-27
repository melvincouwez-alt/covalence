// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * Default apps for the calendar and the contacts: the app made for Covalence, or
 * elementary's own (Flatpak from AppCenter). Both read the same iCloud account
 * through Evolution Data Server.
 *
 * The choice is kept in apps.conf [default-apps]. For the calendar it also
 * makes the chosen app the handler of text/calendar. For the contacts it
 * decides which launcher shows in the Applications menu (Covalence's Contacts
 * is hidden when elementary's is chosen).
 */

namespace Covalence {
    public class AppChoice : Object {
        public string key { get; construct; }
        public string title { get; construct; }
        public string icon_name { get; construct; }
        public string[] ids { get; construct; }
        public string[] labels { get; construct; }
        public string? content_type { get; construct; }

        public static AppChoice calendar () {
            return new AppChoice ("calendar", _("Agenda"), "io.github.melvincouwez.Agenda",
                                  { "io.github.melvincouwez.Agenda", "io.elementary.calendar" },
                                  { _("Agenda (Covalence)"), _("Calendrier (elementary)") }, "text/calendar");
        }

        public static AppChoice contacts () {
            return new AppChoice ("contacts", _("Contacts"), Config.APP_ID + ".Contacts",
                                  { Config.APP_ID + ".Contacts", "io.elementary.contacts" },
                                  { _("Contacts (Covalence)"), _("Contacts (elementary)") }, null);
        }

        private AppChoice (string key, string title, string icon_name, string[] ids, string[] labels,
                           string? content_type) {
            Object (key: key, title: title, icon_name: icon_name, ids: ids, labels: labels,
                    content_type: content_type);
        }

        private static string prefs_path () {
            return Path.build_filename (Environment.get_user_config_dir (), "covalence", "apps.conf");
        }

        public static bool installed (string id) {
            return new DesktopAppInfo (id + ".desktop") != null;
        }

        /* Index of the chosen app (0 = Covalence's, the default). */
        public int chosen () {
            var prefs = new KeyFile ();
            try {
                prefs.load_from_file (prefs_path (), KeyFileFlags.NONE);
                var id = prefs.get_string ("default-apps", key);
                for (int i = 0; i < ids.length; i++) {
                    if (ids[i] == id) {
                        return i;
                    }
                }
            } catch (Error e) {
                // no choice yet
            }
            return 0;
        }

        public void choose (int index) {
            var prefs = new KeyFile ();
            try {
                prefs.load_from_file (prefs_path (), KeyFileFlags.KEEP_COMMENTS);
            } catch (Error e) {
                // first choice
            }
            prefs.set_string ("default-apps", key, ids[index]);
            try {
                DirUtils.create_with_parents (Path.get_dirname (prefs_path ()), 0700);
                prefs.save_to_file (prefs_path ());
            } catch (Error e) {
                warning ("cannot save default app: %s", e.message);
            }
            apply ();
        }

        /* Make the choice effective; safe to call again once the app got installed. */
        public void apply () {
            var id = ids[chosen ()];
            if (!installed (id)) {
                return;  // waiting for AppCenter: the current handler stays
            }
            if (content_type != null) {
                try {
                    new DesktopAppInfo (id + ".desktop").set_as_default_for_type (content_type);
                } catch (Error e) {
                    warning ("cannot set %s as default for %s: %s", id, content_type, e.message);
                }
            }
            if (key == "contacts") {
                Launchers.set_visible (Mode.CONTACTS, chosen () == 0);
            }
        }

        public void open (Gtk.Window? parent) {
            var id = ids[chosen ()];
            var info = new DesktopAppInfo (id + ".desktop");
            if (info == null) {
                new Gtk.UriLauncher ("appstream://" + id).launch.begin (parent, null);
                return;
            }
            try {
                info.launch (null, parent != null ? parent.get_display ().get_app_launch_context () : null);
            } catch (Error e) {
                warning ("cannot open %s: %s", id, e.message);
            }
        }
    }

    /* One row: icon, title, state, a drop-down to choose, and Ouvrir / Installer… */
    public class AppChoiceRow : Gtk.ListBoxRow {
        public AppChoice choice { get; construct; }

        private Gtk.DropDown dropdown;
        private Gtk.Label state;
        private Gtk.Button action;
        private bool updating = false;

        public AppChoiceRow (AppChoice choice) {
            Object (choice: choice, activatable: false);
        }

        construct {
            var image = new Gtk.Image.from_icon_name (choice.icon_name) { pixel_size = 32 };
            var title = new Gtk.Label (choice.title) { xalign = 0 };
            state = new Gtk.Label ("") { xalign = 0, wrap = true };
            state.add_css_class (Granite.CssClass.DIM);
            state.add_css_class (Granite.CssClass.SMALL);
            var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
            text.append (title);
            text.append (state);
            dropdown = new Gtk.DropDown.from_strings (choice.labels) { valign = Gtk.Align.CENTER };
            dropdown.notify["selected"].connect (() => {
                if (!updating) {
                    choice.choose ((int) dropdown.selected);
                    refresh ();
                }
            });
            action = new Gtk.Button () { valign = Gtk.Align.CENTER };
            action.clicked.connect (() => {
                choice.open (get_root () as Gtk.Window);
            });
            var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
                margin_top = 9,
                margin_bottom = 9,
                margin_start = 12,
                margin_end = 12
            };
            box.append (image);
            box.append (text);
            box.append (dropdown);
            box.append (action);
            child = box;
            // An app installed from AppCenter meanwhile: apply the choice when the row shows again.
            map.connect (() => {
                choice.apply ();
                refresh ();
            });
            refresh ();
        }

        private void refresh () {
            updating = true;
            dropdown.selected = choice.chosen ();
            updating = false;
            var id = choice.ids[choice.chosen ()];
            if (AppChoice.installed (id)) {
                action.label = _("Ouvrir");
                action.tooltip_text = null;
                state.label = choice.content_type != null
                    ? _("App par défaut pour vos calendriers iCloud")
                    : _("App affichée dans le menu Applications");
            } else {
                action.label = _("Installer…");
                action.tooltip_text = _("Ouvrir la fiche dans AppCenter");
                state.label = _("Pas encore installée : elle deviendra l'app par défaut une fois installée");
            }
        }
    }
}
