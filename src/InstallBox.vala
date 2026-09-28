// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * Shared bits of the Fichiers, Recopie d'écran and Photos pages: reading their
 * dictionary properties, and a card offering to install the tools they need
 * (PackageKit, like Components.vala).
 */

namespace Covalence.Props {
    public string str (Variant? dict, string key) {
        var v = dict != null ? dict.lookup_value (key, VariantType.STRING) : null;
        return v != null ? v.get_string () : "";
    }

    public bool flag (Variant? dict, string key) {
        var v = dict != null ? dict.lookup_value (key, VariantType.BOOLEAN) : null;
        return v != null && v.get_boolean ();
    }

    public uint count (Variant? dict, string key) {
        var v = dict != null ? dict.lookup_value (key, VariantType.UINT32) : null;
        return v != null ? v.get_uint32 () : 0;
    }

    public int integer (Variant? dict, string key) {
        var v = dict != null ? dict.lookup_value (key, VariantType.INT32) : null;
        return v != null ? v.get_int32 () : 0;
    }

    public double number (Variant? dict, string key) {
        var v = dict != null ? dict.lookup_value (key, VariantType.DOUBLE) : null;
        return v != null ? v.get_double () : 0;
    }

    public string[] strings (Variant? dict, string key) {
        var v = dict != null ? dict.lookup_value (key, VariantType.STRING_ARRAY) : null;
        return v != null ? v.dup_strv () : new string[0];
    }
}

/* What a page is missing, with an Install button. Hidden when nothing is missing. */
public class Covalence.InstallBox : Gtk.Box {
    public signal void installed ();

    private Gtk.Label text;
    private Gtk.Button button;
    private Gtk.ProgressBar bar;
    private string[] packages = {};

    public InstallBox () {
        Object (orientation: Gtk.Orientation.VERTICAL, spacing: 0);
    }

    construct {
        add_css_class (Granite.CssClass.CARD);
        text = new Gtk.Label ("") { xalign = 0, wrap = true, hexpand = true };
        button = new Gtk.Button.with_label (_("Installer…")) { valign = Gtk.Align.CENTER };
        button.add_css_class (Granite.CssClass.SUGGESTED);
        button.clicked.connect (() => run.begin ());
        var line = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 12,
            margin_bottom = 12,
            margin_start = 12,
            margin_end = 12
        };
        line.append (text);
        line.append (button);
        bar = new Gtk.ProgressBar () {
            visible = false,
            margin_start = 12,
            margin_end = 12,
            margin_bottom = 12
        };
        append (line);
        append (bar);
        visible = false;
    }

    public void set_missing (string[] missing, string what) {
        packages = missing;
        visible = missing.length > 0;
        text.label = _("%s a besoin d'outils absents : %s.").printf (what, string.joinv (", ", missing));
    }

    private async void run () {
        button.sensitive = false;
        bar.visible = true;
        uint pulse = Timeout.add (150, () => {
            bar.pulse ();
            return Source.CONTINUE;
        });
        var installer = new PackageInstaller ();
        installer.progress.connect ((percent) => {
            if (percent >= 0) {
                if (pulse != 0) {
                    Source.remove (pulse);
                    pulse = 0;
                }
                bar.fraction = percent / 100.0;
            }
        });
        string? failure = null;
        try {
            yield installer.install (packages);
        } catch (Error e) {
            failure = e.message;
        }
        if (pulse != 0) {
            Source.remove (pulse);
        }
        bar.visible = false;
        button.sensitive = true;
        if (failure != null) {
            text.label = _("L'installation n'a pas abouti : %s").printf (failure);
        } else {
            installed ();
        }
    }
}

/* Title, subtitle and an optional pill at the top of a page, like the other pages. */
namespace Covalence.PageHeader {
    public Gtk.Widget build (string title, string subtitle, string? pill = null) {
        var name = new Gtk.Label (title) { xalign = 0 };
        name.add_css_class (Granite.HeaderLabel.Size.H2.to_string ());
        var line = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 9);
        line.append (name);
        if (pill != null) {
            var tag = new Gtk.Label (pill) { valign = Gtk.Align.CENTER };
            tag.add_css_class ("alpha-pill");
            line.append (tag);
        }
        var text = new Gtk.Label (subtitle) { xalign = 0, wrap = true };
        text.add_css_class (Granite.CssClass.DIM);
        var box = new Gtk.Box (Gtk.Orientation.VERTICAL, 3);
        box.append (line);
        box.append (text);
        return box;
    }

    /* The scrolled, centred column every page of this kind uses. */
    public Gtk.Box column (out Gtk.ScrolledWindow scroll) {
        var content = new Gtk.Box (Gtk.Orientation.VERTICAL, 12) {
            margin_top = 18,
            margin_bottom = 24,
            margin_start = 24,
            margin_end = 24,
            width_request = 520,
            halign = Gtk.Align.CENTER
        };
        scroll = new Gtk.ScrolledWindow () {
            child = content,
            hscrollbar_policy = Gtk.PolicyType.NEVER,
            vexpand = true
        };
        return content;
    }
}
