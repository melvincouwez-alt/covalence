/*
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2026 Melvin Couwez
 *
 * « Nouveautés »: what changed in this version, shown once after an update and from Réglages.
 * The version last shown is kept in apps.conf [general] whats-new.
 */

namespace Covalence.WhatsNew {

    private struct Item {
        string icon;
        string title;
        string text;
    }

    private static Item[] items () {
        return {
            { "object-select-symbolic", _("Messages envoyés"),
              _("Une petite coche apparaît sous un message dès que l'iPhone confirme son envoi.") },
            { "emoji-body-symbolic", _("Réactions"),
              _("Les réactions reçues s'affichent sur le bon message, sans doublon, et se cumulent. "
                + "Au survol d'un message : réagir, copier ou supprimer.") },
            { "dialog-password-symbolic", _("Codes SMS"),
              _("Un code reçu par SMS se copie depuis la notification. En alpha : remplissage "
                + "dans Chrome, Chromium, Edge et Firefox (Réglages › Codes SMS).") },
            { "format-justify-fill-symbolic", _("Messages en entier"),
              _("« Tout lire » récupère la suite d'un message long non lu, ou toujours, "
                + "au choix dans Réglages. Le message passe alors en lu sur l'iPhone.") },
            { "view-refresh-symbolic", _("Synchroniser"),
              _("Un bouton dans Messages relit les messages, les contacts et le journal d'appels.") },
            { "audio-volume-high-symbolic", _("Sons"),
              _("Choisissez le son des messages, des notifications de l'iPhone et la sonnerie "
                + "des appels, dont 8 sons libres fournis avec Covalence (Réglages › Sons).") },
            { "system-software-update-symbolic", _("Mises à jour"),
              _("Covalence recherche les nouvelles versions et s'installe depuis Réglages.") },
            { "applications-science-symbolic", _("Fonctions alpha"),
              _("À essayer dans Réglages : historique étendu, marquer comme lu sur l'iPhone, "
                + "actions des notifications, favoris des contacts.") }
        };
    }

    private static string prefs_path () {
        return Path.build_filename (Environment.get_user_config_dir (), "covalence", "apps.conf");
    }

    private static string last_shown () {
        var prefs = new KeyFile ();
        try {
            prefs.load_from_file (prefs_path (), KeyFileFlags.NONE);
            return prefs.get_string ("general", "whats-new");
        } catch (Error e) {
            return "";
        }
    }

    private static void remember () {
        var prefs = new KeyFile ();
        try {
            prefs.load_from_file (prefs_path (), KeyFileFlags.KEEP_COMMENTS);
        } catch (Error e) {
            // first choice
        }
        prefs.set_string ("general", "whats-new", Config.VERSION);
        try {
            DirUtils.create_with_parents (Path.get_dirname (prefs_path ()), 0700);
            prefs.save_to_file (prefs_path ());
        } catch (Error e) {
            warning ("cannot save the version shown: %s", e.message);
        }
    }

    /* Once per version, after an update (not on a first install: the setup assistant runs then). */
    public void maybe_show (Gtk.Window parent, bool first_run) {
        if (last_shown () == Config.VERSION) {
            return;
        }
        remember ();
        if (!first_run) {
            Idle.add (() => {
                show (parent);
                return Source.REMOVE;
            });
        }
    }

    public void show (Gtk.Window? parent) {
        var list = new Gtk.Box (Gtk.Orientation.VERTICAL, 14) {
            margin_top = 6,
            margin_bottom = 6
        };
        foreach (var item in items ()) {
            var icon = new Gtk.Image.from_icon_name (item.icon) {
                pixel_size = 24,
                valign = Gtk.Align.START
            };
            icon.add_css_class (Granite.CssClass.ACCENT);
            var title = new Gtk.Label (item.title) { xalign = 0 };
            title.add_css_class ("heading");
            var text = new Gtk.Label (item.text) {
                xalign = 0,
                wrap = true,
                max_width_chars = 48
            };
            text.add_css_class (Granite.CssClass.DIM);
            var words = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true };
            words.append (title);
            words.append (text);
            var row = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12);
            row.append (icon);
            row.append (words);
            list.append (row);
        }
        var scrolled = new Gtk.ScrolledWindow () {
            child = list,
            hscrollbar_policy = Gtk.PolicyType.NEVER,
            propagate_natural_height = true,
            max_content_height = 420
        };
        var dialog = new Granite.MessageDialog.with_image_from_icon_name (
            _("Nouveautés de Covalence %s").printf (Config.VERSION),
            _("Ce qui change dans cette version."),
            Config.APP_ID, Gtk.ButtonsType.NONE) {
            transient_for = parent,
            modal = true
        };
        dialog.custom_bin.append (scrolled);
        var ok = dialog.add_button (_("Continuer"), Gtk.ResponseType.CLOSE);
        ok.add_css_class (Granite.CssClass.SUGGESTED);
        dialog.response.connect (() => dialog.destroy ());
        dialog.present ();
    }
}
