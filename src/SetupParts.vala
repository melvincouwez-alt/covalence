// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * Setup assistant: two columns, "Connexion aux services Apple pour iCloud" on
 * the left and "Connexion avec votre iPhone" on the right. Each lists the steps
 * on elementary OS and on the iPhone with a live check mark, the switches to
 * turn features on or off, and the detached apps to show or not. Every option
 * stays available in the other tabs.
 */

namespace Covalence {
    private const string APPLE_ACCOUNT_URL = "https://account.apple.com/account/manage/section/security";

    /* Launchers of the detached apps: shown in the Applications menu or not. */
    public class Launchers : Object {
        private static string desktop_path (Mode mode) {
            return Path.build_filename (Environment.get_user_data_dir (), "applications",
                                        Config.APP_ID + mode.suffix () + ".desktop");
        }

        private static string prefs_path () {
            return Path.build_filename (Environment.get_user_config_dir (), "covalence", "apps.conf");
        }

        public static bool is_visible (Mode mode) {
            var prefs = new KeyFile ();
            try {
                prefs.load_from_file (prefs_path (), KeyFileFlags.NONE);
                return prefs.get_boolean ("launchers", mode.to_string ());
            } catch (Error e) {
                return true;
            }
        }

        public static void set_visible (Mode mode, bool visible) {
            var prefs = new KeyFile ();
            try {
                prefs.load_from_file (prefs_path (), KeyFileFlags.NONE);
            } catch (Error e) {
                // first choice
            }
            prefs.set_boolean ("launchers", mode.to_string (), visible);
            try {
                DirUtils.create_with_parents (Path.get_dirname (prefs_path ()), 0700);
                prefs.save_to_file (prefs_path ());
            } catch (Error e) {
                warning ("cannot save launcher choice: %s", e.message);
            }
            apply (mode);
        }

        /* Write the choice into the installed launcher (a reinstall resets it: re-applied at start). */
        public static void apply (Mode mode) {
            var path = desktop_path (mode);
            string? source = path;
            var hidden = !is_visible (mode);
            if (!FileUtils.test (path, FileTest.EXISTS)) {
                // Installed in /usr (the .deb): hiding needs a copy in the user's data dir.
                source = null;
                foreach (var dir in Environment.get_system_data_dirs ()) {
                    var candidate = Path.build_filename (dir, "applications", Path.get_basename (path));
                    if (FileUtils.test (candidate, FileTest.EXISTS)) {
                        source = candidate;
                        break;
                    }
                }
                if (source == null || !hidden) {
                    return;
                }
                DirUtils.create_with_parents (Path.get_dirname (path), 0755);
            }
            var desktop = new KeyFile ();
            try {
                desktop.load_from_file (source, KeyFileFlags.KEEP_COMMENTS | KeyFileFlags.KEEP_TRANSLATIONS);
                bool current = false;
                try {
                    current = desktop.get_boolean ("Desktop Entry", "NoDisplay");
                } catch (Error e) {
                    current = false;
                }
                if (current != hidden) {
                    desktop.set_boolean ("Desktop Entry", "NoDisplay", hidden);
                    desktop.save_to_file (path);
                }
            } catch (Error e) {
                warning ("cannot update %s: %s", path, e.message);
            }
        }
    }

    /* One step: a number that becomes a check mark, a title, a hint and an optional button. */
    public class SetupStep : Gtk.Box {
        private Gtk.Stack mark;
        private Gtk.Label hint;
        private Gtk.Box extra;

        public SetupStep (int number, string title, string text) {
            Object (orientation: Gtk.Orientation.HORIZONTAL, spacing: 12);
            var badge = new Gtk.Label (number.to_string ()) { valign = Gtk.Align.CENTER };
            badge.add_css_class ("setup-number");
            var done = new Gtk.Image.from_icon_name ("process-completed") { pixel_size = 24 };
            mark = new Gtk.Stack () { valign = Gtk.Align.START, width_request = 26 };
            mark.add_named (badge, "todo");
            mark.add_named (done, "done");
            var title_label = new Gtk.Label (title) { xalign = 0, wrap = true };
            title_label.add_css_class ("setup-step-title");
            hint = new Gtk.Label (text) {
                xalign = 0,
                wrap = true,
                use_markup = true,
                max_width_chars = 44
            };
            hint.add_css_class (Granite.CssClass.DIM);
            hint.add_css_class (Granite.CssClass.SMALL);
            extra = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6) { margin_top = 4 };
            var text_box = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true };
            text_box.append (title_label);
            text_box.append (hint);
            text_box.append (extra);
            append (mark);
            append (text_box);
        }

        public void set_done (bool done) {
            mark.visible_child_name = done ? "done" : "todo";
        }

        public void set_hint (string markup) {
            hint.label = markup;
        }

        public Gtk.Button add_button (string label, bool suggested = false) {
            var button = new Gtk.Button.with_label (label);
            if (suggested) {
                button.add_css_class (Granite.CssClass.SUGGESTED);
            }
            extra.append (button);
            return button;
        }
    }

}
