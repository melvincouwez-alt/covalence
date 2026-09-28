/*
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2026 Melvin Couwez
 *
 * iCloud.com shortcuts (Services Apple): Find My, Notes, Hide My Email, Reminders and
 * Photos have no protocol open to Linux, but work in a browser. Each row opens the page,
 * and a switch adds a launcher to the Applications menu: a .desktop file in
 * ~/.local/share/applications that opens the page in an app window of a Chromium-based
 * browser when one is installed (--app=), else in the default browser.
 */

namespace Covalence.WebShortcuts {

    private struct Shortcut {
        string id;
        string title;
        string subtitle;
        string url;
        string[] icons;
    }

    private static Shortcut[] shortcuts () {
        return {
            { "find", _("Localiser"), _("Appareils, AirTag et partage de position"),
              "https://www.icloud.com/find", { "find-location", "applications-internet" } },
            { "notes", _("Notes"), _("Notes iCloud"),
              "https://www.icloud.com/notes", { "accessories-text-editor", "text-x-generic" } },
            { "hide-my-email", _("Masquer mon adresse e-mail"), _("Adresses iCloud+ jetables"),
              "https://www.icloud.com/icloudplus/", { "io.elementary.mail", "mail-send", "applications-internet" } },
            { "reminders", _("Rappels"), _("Rappels iCloud, aussi visibles dans Tâches"),
              "https://www.icloud.com/reminders", { "io.elementary.tasks", "x-office-calendar" } },
            { "photos", _("Photos"), _("Photothèque iCloud dans le navigateur"),
              "https://www.icloud.com/photos", { "io.elementary.photos", "multimedia-photo-viewer" } }
        };
    }

    /* Chromium-based browsers open a page as an app window with --app=URL. */
    private const string[] APP_BROWSERS = {
        "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "brave-browser"
    };

    public static string desktop_path (string id) {
        return Path.build_filename (Environment.get_user_data_dir (), "applications",
                                    "%s.Web.%s.desktop".printf (Config.APP_ID, id));
    }

    public static string exec_line (string url) {
        foreach (var browser in APP_BROWSERS) {
            if (Environment.find_program_in_path (browser) != null) {
                return "%s --app=%s".printf (browser, url);
            }
        }
        return "xdg-open %s".printf (url);
    }

    private static string icon_name (string[] names) {
        var display = Gdk.Display.get_default ();
        if (display != null) {
            var theme = Gtk.IconTheme.get_for_display (display);
            foreach (var name in names) {
                if (theme.has_icon (name)) {
                    return name;
                }
            }
        }
        return names[names.length - 1];
    }

    public static string desktop_entry (string title, string comment, string url, string icon) {
        return "[Desktop Entry]\n"
            + "Type=Application\n"
            + "Name=%s\n".printf (title)
            + "Comment=%s\n".printf (comment)
            + "Exec=%s\n".printf (exec_line (url))
            + "Icon=%s\n".printf (icon)
            + "Categories=Network;\n"
            + "Keywords=iCloud;Apple;\n"
            + "X-Covalence-Url=%s\n".printf (url);
    }

    private static bool installed (string id) {
        return FileUtils.test (desktop_path (id), FileTest.EXISTS);
    }

    private static bool set_installed (Shortcut s, bool wanted) {
        var path = desktop_path (s.id);
        try {
            if (wanted) {
                DirUtils.create_with_parents (Path.get_dirname (path), 0755);
                FileUtils.set_contents (path, desktop_entry (_("%s (iCloud)").printf (s.title), s.subtitle,
                                                             s.url, icon_name (s.icons)));
            } else if (FileUtils.test (path, FileTest.EXISTS)) {
                FileUtils.remove (path);
            }
            return true;
        } catch (Error e) {
            warning ("iCloud.com shortcut %s: %s", s.id, e.message);
            return false;
        }
    }

    private static void open (string url) {
        AppInfo.launch_default_for_uri_async.begin (url, null, null);
    }

    public Gtk.Widget card () {
        var list = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
        list.add_css_class (Granite.CssClass.CARD);
        foreach (var s in shortcuts ()) {
            list.append (row (s));
        }
        var hint = new Gtk.Label (
            _("Ces services n'ont pas d'accès ouvert à Linux : ils s'ouvrent sur iCloud.com. "
              + "L'interrupteur ajoute un raccourci au menu Applications.")
        ) { xalign = 0, wrap = true };
        hint.add_css_class (Granite.CssClass.DIM);
        hint.add_css_class (Granite.CssClass.SMALL);
        var box = new Gtk.Box (Gtk.Orientation.VERTICAL, 6);
        box.append (list);
        box.append (hint);
        return box;
    }

    private Gtk.Widget row (Shortcut s) {
        var image = new Gtk.Image.from_gicon (new ThemedIcon.from_names (s.icons)) { pixel_size = 32 };
        var title_label = new Gtk.Label (s.title) { xalign = 0 };
        var subtitle_label = new Gtk.Label (s.subtitle) { xalign = 0, wrap = true };
        subtitle_label.add_css_class (Granite.CssClass.DIM);
        subtitle_label.add_css_class (Granite.CssClass.SMALL);
        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        text.append (title_label);
        text.append (subtitle_label);

        var url = s.url;
        var open_button = new Gtk.Button.with_label (_("Ouvrir")) {
            valign = Gtk.Align.CENTER,
            tooltip_text = url
        };
        open_button.clicked.connect (() => open (url));

        var shortcut = s;
        var in_menu = new Gtk.Switch () {
            valign = Gtk.Align.CENTER,
            active = installed (s.id),
            tooltip_text = _("Afficher dans le menu Applications")
        };
        in_menu.update_property (Gtk.AccessibleProperty.LABEL,
                                 _("%s dans le menu Applications").printf (s.title), -1);
        bool reverting = false;
        in_menu.notify["active"].connect (() => {
            if (reverting) {
                return;
            }
            if (!set_installed (shortcut, in_menu.active)) {
                reverting = true;
                in_menu.active = !in_menu.active;
                reverting = false;
            }
        });

        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9,
            margin_bottom = 9,
            margin_start = 12,
            margin_end = 12
        };
        box.append (image);
        box.append (text);
        box.append (open_button);
        box.append (in_menu);
        return new Gtk.ListBoxRow () { child = box, activatable = false };
    }
}
