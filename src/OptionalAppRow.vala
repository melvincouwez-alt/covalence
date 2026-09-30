// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * A row for an app Covalence can install for you (covalenced/apps.py): Agenda
 * and Cassette. Installed, it opens the app; not yet, it downloads the package
 * published with Covalence's releases, checked by its SHA-256, and installs it
 * after the password (polkit), with the progress shown in the row.
 */

public class Covalence.OptionalAppRow : Gtk.ListBoxRow {
    public Daemon daemon { get; construct; }
    public string package { get; construct; }
    public string desktop_id { get; construct; }
    public string title { get; construct; }
    public string subtitle { get; construct; }

    private Gtk.Image image;
    private Gtk.Label state_label;
    private Gtk.Button action;
    private Gtk.ProgressBar bar;

    public OptionalAppRow (Daemon daemon, string package, string desktop_id, string title, string subtitle) {
        Object (daemon: daemon, package: package, desktop_id: desktop_id, title: title, subtitle: subtitle,
                activatable: false);
    }

    construct {
        image = new Gtk.Image.from_icon_name (desktop_id) { pixel_size = 32 };
        var title_label = new Gtk.Label (title) { xalign = 0 };
        state_label = new Gtk.Label (subtitle) { xalign = 0, wrap = true };
        state_label.add_css_class (Granite.CssClass.DIM);
        state_label.add_css_class (Granite.CssClass.SMALL);
        bar = new Gtk.ProgressBar () { visible = false, margin_top = 3 };
        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        text.append (title_label);
        text.append (state_label);
        text.append (bar);
        action = new Gtk.Button.with_label (_("Installer…")) { valign = Gtk.Align.CENTER };
        action.clicked.connect (on_action);
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9, margin_bottom = 9, margin_start = 12, margin_end = 12
        };
        box.append (image);
        box.append (text);
        box.append (action);
        child = box;

        daemon.changed.connect (update);
        // Covalence only looks for the package once the row is on screen.
        map.connect (() => {
            daemon.call.begin ("CheckApps");
            update ();
        });
        update ();
    }

    private AppInfo? installed_app () {
        return new DesktopAppInfo (desktop_id + ".desktop");
    }

    private Variant? entry () {
        var all = daemon.get_value ("Apps");
        return all != null ? all.lookup_value (package, VariantType.VARDICT) : null;
    }

    private void update () {
        var app = installed_app ();
        var e = entry ();
        var state = Props.str (e, "state");
        bool busy = state == "downloading" || state == "installing";
        bar.visible = busy;
        bar.fraction = Props.number (e, "progress");
        if (app != null && !busy) {
            action.label = _("Ouvrir");
            action.sensitive = true;
            action.tooltip_text = null;
            state_label.label = subtitle;
            var icon = app.get_icon ();
            if (icon != null) {
                image.gicon = icon;
            }
            return;
        }
        var version = Props.str (e, "version");
        action.label = _("Installer…");
        action.sensitive = !busy && version != "";
        if (state == "downloading") {
            state_label.label = _("Téléchargement…");
        } else if (state == "installing") {
            state_label.label = _("Installation…");
        } else if (state == "error") {
            state_label.label = Props.str (e, "error");
        } else if (version != "") {
            var size = e != null ? e.lookup_value ("size", VariantType.INT64) : null;
            state_label.label = size != null && size.get_int64 () > 0
                ? _("%s · version %s, %s").printf (subtitle, version, format_size ((uint64) size.get_int64 ()))
                : _("%s · version %s").printf (subtitle, version);
        } else {
            state_label.label = _("%s · pas encore disponible au téléchargement").printf (subtitle);
        }
    }

    private void on_action () {
        var app = installed_app ();
        if (app != null) {
            try {
                app.launch (null, get_display ().get_app_launch_context ());
            } catch (Error e) {
                warning ("cannot open %s: %s", desktop_id, e.message);
            }
            return;
        }
        action.sensitive = false;
        daemon.call_checked.begin ("InstallApp", new Variant ("(s)", package), (obj, res) => {
            try {
                daemon.call_checked.end (res);
            } catch (Error e) {
                state_label.label = e.message;
                action.sensitive = true;
            }
        });
    }
}
