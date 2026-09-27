// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * Navigation of the main window: sections grouped by where they come from
 * (the iPhone over Bluetooth, accessories, the Apple account over the
 * Internet), with the app's own colour icons and unread / missed badges.
 */

public class Covalence.Sidebar : Gtk.Box {
    public Gtk.Stack pages { get; construct; }

    private Gtk.ListBox list;
    private Gtk.ListBox footer;
    private HashTable<string, Gtk.Label> badges = new HashTable<string, Gtk.Label> (str_hash, str_equal);
    private HashTable<string, string> sections = new HashTable<string, string> (str_hash, str_equal);
    private bool syncing = false;
    private Gtk.Box player_slot;

    public Sidebar (Gtk.Stack pages) {
        Object (pages: pages, orientation: Gtk.Orientation.VERTICAL, spacing: 0);
    }

    construct {
        list = new Gtk.ListBox () { vexpand = true };
        list.add_css_class ("navigation-sidebar");
        list.set_header_func ((row, before) => {
            var name = row.get_data<string> ("page");
            var section = sections[name];
            var previous = before != null ? sections[before.get_data<string> ("page")] : null;
            if (section != previous) {
                var label = new Gtk.Label (section) { xalign = 0, margin_start = 9, margin_top = 12 };
                label.add_css_class (Granite.CssClass.DIM);
                label.add_css_class (Granite.CssClass.SMALL);
                label.add_css_class ("sidebar-section");
                row.set_header (label);
            } else {
                row.set_header (null);
            }
        });
        list.row_selected.connect ((row) => {
            if (row != null && !syncing) {
                pages.visible_child_name = row.get_data<string> ("page");
            }
        });
        // Réglages stay at the bottom, apart from the sections.
        footer = new Gtk.ListBox ();
        footer.add_css_class ("navigation-sidebar");
        footer.row_selected.connect ((row) => {
            if (row != null && !syncing) {
                pages.visible_child_name = row.get_data<string> ("page");
            }
        });
        pages.notify["visible-child-name"].connect (sync);

        var scroll = new Gtk.ScrolledWindow () {
            child = list,
            hscrollbar_policy = Gtk.PolicyType.NEVER,
            vexpand = true
        };
        append (scroll);
        player_slot = new Gtk.Box (Gtk.Orientation.VERTICAL, 0);
        append (player_slot);
        append (new Gtk.Separator (Gtk.Orientation.HORIZONTAL));
        append (footer);
    }

    /* A widget shown just above Réglages (the Now Playing mini player). */
    public void set_player (Gtk.Widget player) {
        player_slot.append (player);
    }

    public void add (string page, string section, string icon, string title) {
        sections[page] = section;
        list.append (make_row (page, icon, title));
        sync ();
    }

    public void add_footer (string page, string icon, string title) {
        footer.append (make_row (page, icon, title));
        sync ();
    }

    private Gtk.ListBoxRow make_row (string page, string icon, string title) {
        var image = new Gtk.Image.from_icon_name (icon) { pixel_size = 24 };
        var label = new Gtk.Label (title) { xalign = 0, hexpand = true, ellipsize = Pango.EllipsizeMode.END };
        var badge = new Gtk.Label ("") { visible = false, valign = Gtk.Align.CENTER };
        badge.add_css_class (Granite.STYLE_CLASS_BADGE);
        badges[page] = badge;
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 9) {
            margin_top = 3,
            margin_bottom = 3,
            margin_start = 3,
            margin_end = 3
        };
        box.append (image);
        box.append (label);
        box.append (badge);
        var row = new Gtk.ListBoxRow () { child = box };
        row.set_data<string> ("page", page);
        row.update_property (Gtk.AccessibleProperty.LABEL, title, -1);
        return row;
    }

    /* Page shown by Ctrl+1…9: the n-th entry of the list. */
    public void select_index (int index) {
        var row = list.get_row_at_index (index);
        if (row != null) {
            pages.visible_child_name = row.get_data<string> ("page");
        }
    }

    /* A number next to the page name (0 hides it). */
    public void set_badge (string page, uint count) {
        var badge = badges[page];
        if (badge == null) {
            return;
        }
        badge.label = count > 99 ? "99+" : count.to_string ();
        badge.visible = count > 0;
    }

    private void sync () {
        var name = pages.visible_child_name;
        syncing = true;
        foreach (var box in new Gtk.ListBox[] { list, footer }) {
            Gtk.ListBoxRow? match = null;
            for (int i = 0; box.get_row_at_index (i) != null; i++) {
                var row = box.get_row_at_index (i);
                if (row.get_data<string> ("page") == name) {
                    match = row;
                }
            }
            if (match == null) {
                box.unselect_all ();
            } else if (box.get_selected_row () != match) {
                box.select_row (match);
            }
        }
        syncing = false;
    }
}
