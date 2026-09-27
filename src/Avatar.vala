// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * Round contact picture: the iPhone contact's photo when PBAP provided one,
 * otherwise initials. The CSS node is "avatar" so that the elementary
 * stylesheet draws it like every other avatar of the desktop (colours
 * color1 to color14 picked from the name, "image" when a photo is shown).
 */

public class Covalence.Avatar : Gtk.Widget {
    private const int COLORS = 14;

    public int size { get; construct; }

    private Gtk.Label initials;
    private Gtk.Picture picture;
    private string current_path = "";

    public Avatar (int size) {
        Object (size: size, valign: Gtk.Align.CENTER, halign: Gtk.Align.CENTER);
    }

    static construct {
        set_css_name ("avatar");
        set_accessible_role (Gtk.AccessibleRole.IMG);
    }

    construct {
        width_request = size;
        height_request = size;
        overflow = Gtk.Overflow.HIDDEN;
        initials = new Gtk.Label ("") { halign = Gtk.Align.CENTER, valign = Gtk.Align.CENTER };
        initials.set_parent (this);
        picture = new Gtk.Picture () {
            content_fit = Gtk.ContentFit.COVER,
            can_shrink = true,
            visible = false
        };
        picture.set_parent (this);
        var attrs = new Pango.AttrList ();
        attrs.insert (new Pango.AttrSize.with_absolute ((int) (size * 0.4 * Pango.SCALE)));
        attrs.insert (Pango.attr_weight_new (Pango.Weight.SEMIBOLD));
        initials.attributes = attrs;
    }

    /* Always exactly size x size, whatever the photo's own dimensions. */
    public override void measure (Gtk.Orientation orientation, int for_size, out int minimum,
                                  out int natural, out int minimum_baseline,
                                  out int natural_baseline) {
        minimum = natural = size;
        minimum_baseline = natural_baseline = -1;
    }

    public override void size_allocate (int width, int height, int baseline) {
        foreach (var child in new Gtk.Widget[] { initials, picture }) {
            if (child.visible) {
                int min, nat, min_b, nat_b;
                child.measure (Gtk.Orientation.HORIZONTAL, -1, out min, out nat, out min_b, out nat_b);
                child.allocate (width, height, baseline, null);
            }
        }
    }

    public override void dispose () {
        initials.unparent ();
        picture.unparent ();
        base.dispose ();
    }

    public void show_person (string name, string photo_path, bool group = false) {
        update_property (Gtk.AccessibleProperty.LABEL, name, -1);
        for (int i = 1; i <= COLORS; i++) {
            remove_css_class ("color%d".printf (i));
        }
        add_css_class ("color%u".printf (name.hash () % COLORS + 1));

        if (photo_path != "" && FileUtils.test (photo_path, FileTest.EXISTS)) {
            if (photo_path != current_path) {
                picture.set_filename (photo_path);
                current_path = photo_path;
            }
            picture.visible = true;
            initials.visible = false;
            add_css_class ("image");
            return;
        }
        remove_css_class ("image");
        current_path = "";
        picture.visible = false;
        initials.visible = true;
        initials.label = group ? group_initials (name) : person_initials (name);
    }

    private static string first_letter (string word) {
        var w = word.strip ();
        if (w == "") {
            return "";
        }
        unichar c = w.get_char (0);
        if (!c.isalpha ()) {
            return "";
        }
        return c.toupper ().to_string ();
    }

    private static string person_initials (string name) {
        var parts = name.strip ().split (" ");
        var result = first_letter (parts.length > 0 ? parts[0] : "");
        if (parts.length > 1) {
            result += first_letter (parts[parts.length - 1]);
        }
        return result != "" ? result : "#";
    }

    private static string group_initials (string names) {
        var parts = names.split (",");
        var result = "";
        for (int i = 0; i < parts.length && i < 2; i++) {
            result += first_letter (parts[i]);
        }
        return result != "" ? result : "#";
    }
}
