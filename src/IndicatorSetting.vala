/*
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2026 Melvin Couwez
 *
 * « Afficher dans la barre du haut »: the Covalence indicator in Wingpanel reads
 * apps.conf [general] indicator (true unless turned off) and follows changes live.
 */

namespace Covalence.IndicatorSetting {

    private static string prefs_path () {
        return Path.build_filename (Environment.get_user_config_dir (), "covalence", "apps.conf");
    }

    public bool enabled () {
        var prefs = new KeyFile ();
        try {
            prefs.load_from_file (prefs_path (), KeyFileFlags.NONE);
            return prefs.get_boolean ("general", "indicator");
        } catch (Error e) {
            return true;
        }
    }

    public void set_enabled (bool enabled) {
        var prefs = new KeyFile ();
        try {
            prefs.load_from_file (prefs_path (), KeyFileFlags.KEEP_COMMENTS);
        } catch (Error e) {
            // first choice
        }
        prefs.set_boolean ("general", "indicator", enabled);
        try {
            DirUtils.create_with_parents (Path.get_dirname (prefs_path ()), 0700);
            prefs.save_to_file (prefs_path ());
        } catch (Error e) {
            warning ("cannot save the top bar choice: %s", e.message);
        }
    }

    /* Is the indicator installed? (Built only when the Wingpanel development files were there.) */
    public bool installed () {
        foreach (var dir in new string[] { "/usr/lib/x86_64-linux-gnu/wingpanel-9", "/usr/lib/wingpanel-9",
                                           "/usr/lib64/wingpanel-9" }) {
            if (FileUtils.test (Path.build_filename (dir, "libcovalence-indicator.so"), FileTest.EXISTS)) {
                return true;
            }
        }
        return false;
    }

    /* A card row for Réglages: title, explanation and a switch. */
    public Gtk.Widget row () {
        var title_label = new Gtk.Label (_("Afficher dans la barre du haut")) { xalign = 0 };
        var subtitle_label = new Gtk.Label (
            installed ()
            ? _("Batterie de l'iPhone, lecture en cours, appel et messages non lus, à côté de l'horloge.")
            : _("L'indicateur n'est pas installé avec cette version de Covalence.")
        ) { xalign = 0, wrap = true };
        subtitle_label.add_css_class (Granite.CssClass.DIM);
        subtitle_label.add_css_class (Granite.CssClass.SMALL);
        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        text.append (title_label);
        text.append (subtitle_label);
        var sw = new Gtk.Switch () {
            valign = Gtk.Align.CENTER,
            active = enabled (),
            sensitive = installed ()
        };
        sw.update_property (Gtk.AccessibleProperty.LABEL, title_label.label, -1);
        sw.notify["active"].connect (() => set_enabled (sw.active));
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9,
            margin_bottom = 9,
            margin_start = 12,
            margin_end = 12
        };
        box.append (text);
        box.append (sw);
        return new Gtk.ListBoxRow () { child = box, activatable = false };
    }
}
