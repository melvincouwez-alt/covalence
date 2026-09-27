// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * Interface language: French (source) or English (beta, po/en.po).
 *
 * The choice lives in [general] language of ~/.config/covalence/apps.conf:
 * "fr", "en" or "system" (default). "system" means French when the session
 * language is French, English otherwise. The daemon (covalenced/i18n.py) and
 * the guide read the same key.
 */

namespace Covalence.Language {
    private string prefs_path () {
        return Path.build_filename (Environment.get_user_config_dir (), "covalence", "apps.conf");
    }

    /* "fr", "en" or "system". */
    public string chosen () {
        var prefs = new KeyFile ();
        try {
            prefs.load_from_file (prefs_path (), KeyFileFlags.NONE);
            var value = prefs.get_string ("general", "language").strip ();
            if (value == "fr" || value == "en") {
                return value;
            }
        } catch (Error e) {
            // no choice yet
        }
        return "system";
    }

    /* The language in use: "fr" or "en". */
    public string resolved () {
        var value = chosen ();
        if (value != "system") {
            return value;
        }
        // Read before apply () sets LANGUAGE, and again later: same answer.
        var session = Environment.get_variable ("COVALENCE_SESSION_LANGUAGE");
        if (session != null) {
            return session;
        }
        foreach (var name in Intl.get_language_names ()) {
            if (name == "C" || name == "POSIX") {
                continue;
            }
            return name.has_prefix ("fr") ? "fr" : "en";
        }
        return "en";
    }

    public void save (string value) {
        var prefs = new KeyFile ();
        try {
            prefs.load_from_file (prefs_path (), KeyFileFlags.KEEP_COMMENTS);
        } catch (Error e) {
            // first choice
        }
        prefs.set_string ("general", "language", value);
        try {
            DirUtils.create_with_parents (Path.get_dirname (prefs_path ()), 0700);
            prefs.save_to_file (prefs_path ());
        } catch (Error e) {
            warning ("cannot save the language: %s", e.message);
        }
    }

    /* At start-up, before any window: pick the catalog. */
    public void apply () {
        Intl.setlocale (LocaleCategory.ALL, "");
        if (Environment.get_variable ("COVALENCE_SESSION_LANGUAGE") == null) {
            string session = "en";
            foreach (var name in Intl.get_language_names ()) {
                if (name != "C" && name != "POSIX") {
                    session = name.has_prefix ("fr") ? "fr" : "en";
                    break;
                }
            }
            Environment.set_variable ("COVALENCE_SESSION_LANGUAGE", session, true);
        }
        var lang = resolved ();
        // French is the source language: no catalog needed, GTK's own strings follow too.
        Environment.set_variable ("LANGUAGE", lang == "fr" ? "fr_FR:fr" : "en_US:en", true);
        Intl.setlocale (LocaleCategory.ALL, "");
        // Day names ("Friday") come from LC_TIME, not LANGUAGE: follow the chosen language.
        var time = Intl.setlocale (LocaleCategory.TIME, null) ?? "";
        if (!time.has_prefix (lang)) {
            string[] candidates = lang == "fr" ? new string[] { "fr_FR.UTF-8", "fr_FR.utf8" }
                                               : new string[] { "en_US.UTF-8", "en_GB.UTF-8", "C.UTF-8" };
            foreach (var candidate in candidates) {
                if (Intl.setlocale (LocaleCategory.TIME, candidate) != null) {
                    // GTK calls setlocale () again at start-up: keep it in the environment.
                    Environment.set_variable ("LC_TIME", candidate, true);
                    break;
                }
            }
        }
        Intl.bindtextdomain (Config.GETTEXT_PACKAGE, Config.LOCALEDIR);
        Intl.bind_textdomain_codeset (Config.GETTEXT_PACKAGE, "UTF-8");
        Intl.textdomain (Config.GETTEXT_PACKAGE);
    }

    /* Restart the app (same program and arguments) and the daemon in the new language. */
    public void restart (Gtk.Application app) {
        try {
            Process.spawn_command_line_async ("systemctl --user restart covalenced.service");
        } catch (SpawnError e) {
            warning ("cannot restart covalenced: %s", e.message);
        }
        var program = Environment.get_prgname () ?? Config.APP_ID;
        var path = Path.build_filename (Config.BINDIR, Path.get_basename (program));
        if (!FileUtils.test (path, FileTest.IS_EXECUTABLE)) {
            path = Path.build_filename (Config.BINDIR, Config.APP_ID);
        }
        try {
            // Started after this instance has quit, or it would just hand over to it.
            string[] argv = { "sh", "-c", "sleep 1; exec \"$0\"", path };
            Process.spawn_async (null, argv, null, SpawnFlags.SEARCH_PATH, null, null);
        } catch (SpawnError e) {
            warning ("cannot restart: %s", e.message);
        }
        app.quit ();
    }

    /* A drop-down "Français / English (beta)" that saves the choice and offers a restart. */
    public Gtk.DropDown selector (Gtk.Widget owner) {
        // Shown in both languages on purpose: whoever reads the other one finds it.
        var dropdown = new Gtk.DropDown.from_strings ({ "Français", "English (beta)" }) {
            valign = Gtk.Align.CENTER,
            selected = resolved () == "en" ? 1 : 0,
            tooltip_text = "Langue / Language"
        };
        dropdown.notify["selected"].connect (() => {
            var value = dropdown.selected == 1 ? "en" : "fr";
            if (value == resolved ()) {
                return;
            }
            save (value);
            ask_restart (owner, value);
        });
        return dropdown;
    }

    /* Réglages row: icon, title with a "beta" badge while English is shown, selector. */
    public Gtk.Widget settings_row (Gtk.Widget owner) {
        var image = new Gtk.Image.from_icon_name ("preferences-desktop-locale") { pixel_size = 32 };
        var title = new Gtk.Label (_("Langue")) { xalign = 0 };
        var beta = new Gtk.Label (_("bêta")) { valign = Gtk.Align.CENTER };
        beta.add_css_class ("beta-badge");
        var heading = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6);
        heading.append (title);
        heading.append (beta);
        var subtitle = new Gtk.Label (_("L'anglais est en bêta : quelques textes peuvent rester en français. "
                                        + "Le guide a son propre bouton FR / EN.")) {
            xalign = 0,
            wrap = true
        };
        subtitle.add_css_class (Granite.CssClass.DIM);
        subtitle.add_css_class (Granite.CssClass.SMALL);
        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        text.append (heading);
        text.append (subtitle);
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9,
            margin_bottom = 9,
            margin_start = 12,
            margin_end = 12
        };
        box.append (image);
        box.append (text);
        box.append (selector (owner));
        return new Gtk.ListBoxRow () { child = box, activatable = false };
    }

    /* Onboarding: "Langue / Language" and the selector, centred. */
    public Gtk.Widget welcome_row (Gtk.Widget owner) {
        var label = new Gtk.Label ("Langue / Language");
        label.add_css_class (Granite.CssClass.DIM);
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) { halign = Gtk.Align.CENTER };
        box.append (new Gtk.Image.from_icon_name ("preferences-desktop-locale-symbolic"));
        box.append (label);
        box.append (selector (owner));
        return box;
    }

    private void ask_restart (Gtk.Widget owner, string value) {
        var english = value == "en";
        var dialog = new Granite.MessageDialog.with_image_from_icon_name (
            english ? "Restart Covalence in English?" : "Relancer Covalence en français ?",
            english ? "The new language applies once Covalence restarts. English is a beta: "
                      + "a few texts may still be in French."
                    : "La nouvelle langue s'applique au redémarrage de Covalence.",
            "preferences-desktop-locale", Gtk.ButtonsType.NONE) {
            transient_for = owner.get_root () as Gtk.Window,
            modal = true
        };
        dialog.add_button (english ? "Later" : "Plus tard", Gtk.ResponseType.CANCEL);
        var now = dialog.add_button (english ? "Restart now" : "Relancer maintenant", Gtk.ResponseType.ACCEPT);
        now.add_css_class (Granite.CssClass.SUGGESTED);
        dialog.response.connect ((response) => {
            dialog.destroy ();
            var app = GLib.Application.get_default () as Gtk.Application;
            if (response == Gtk.ResponseType.ACCEPT && app != null) {
                restart (app);
            }
        });
        dialog.present ();
    }
}
