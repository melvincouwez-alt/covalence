// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * One feature of Covalence: icon, name, live status and an on/off switch.
 */

public class Covalence.ModuleRow : Gtk.ListBoxRow {
    public string module { get; construct; }
    public signal void toggled (bool active);

    private Gtk.Label status_label;
    private Gtk.Switch toggle;
    private Gtk.Box suffix_box;
    private bool updating = false;

    public ModuleRow (string module, string icon_name, string title) {
        Object (module: module, activatable: false, selectable: false);

        var icon = new Gtk.Image.from_icon_name (icon_name) {
            pixel_size = 32,
            valign = Gtk.Align.CENTER
        };

        var title_label = new Gtk.Label (title) {
            xalign = 0,
            hexpand = true
        };

        status_label = new Gtk.Label ("") {
            xalign = 0,
            wrap = true,
            hexpand = true
        };
        status_label.add_css_class (Granite.CssClass.DIM);
        status_label.add_css_class (Granite.CssClass.SMALL);

        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) {
            valign = Gtk.Align.CENTER,
            hexpand = true
        };
        text.append (title_label);
        text.append (status_label);

        suffix_box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6) {
            valign = Gtk.Align.CENTER
        };

        toggle = new Gtk.Switch () {
            valign = Gtk.Align.CENTER
        };
        toggle.update_property (Gtk.AccessibleProperty.LABEL, title, -1);
        toggle.notify["active"].connect (() => {
            if (!updating) {
                toggled (toggle.active);
            }
        });

        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9,
            margin_bottom = 9,
            margin_start = 12,
            margin_end = 12
        };
        box.append (icon);
        box.append (text);
        box.append (suffix_box);
        box.append (toggle);
        child = box;
    }

    public void add_suffix (Gtk.Widget widget) {
        suffix_box.append (widget);
    }

    public void update (bool enabled, string status, bool available = true) {
        updating = true;
        toggle.active = enabled && available;
        updating = false;
        toggle.sensitive = available;
        status_label.label = status;
    }
}
