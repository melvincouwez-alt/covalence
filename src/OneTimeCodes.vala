// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * One-time codes received by SMS (covalenced/otp.py finds them).
 *
 * `covalence --copy-code` puts the latest code on the clipboard and clears it after two
 * minutes if it is still there. covalenced starts it from the notification with
 * GDK_BACKEND=x11: under Wayland only the focused window may set the clipboard, and a
 * click on a notification leaves no window focused; XWayland shares the clipboard with
 * every app without that rule.
 *
 * CodesCard is the "Codes SMS" part of Réglages: off, notification with copy, or
 * notification and browser (alpha), plus the browser integration install.
 */

namespace Covalence.CodeCopy {
    private const uint KEEP_SECONDS = 120;

    public static int run () {
        if (!Gtk.init_check ()) {
            return 1;
        }
        string code = "";
        try {
            var bus = Bus.get_sync (BusType.SESSION);
            var name = Environment.get_variable ("COVALENCE_DAEMON_NAME") ?? Daemon.NAME;
            var reply = bus.call_sync (name, Daemon.PATH, Daemon.IFACE, "LatestCode",
                                       new Variant ("(s)", "copy"), new VariantType ("(su)"),
                                       DBusCallFlags.NO_AUTO_START, 5000);
            uint age;
            reply.get ("(su)", out code, out age);
        } catch (Error e) {
            warning ("no code: %s", e.message);
            return 1;
        }
        var display = Gdk.Display.get_default ();
        if (code == "" || display == null) {
            return 1;
        }
        var clipboard = display.get_clipboard ();
        clipboard.set_text (code);
        var loop = new MainLoop ();
        Timeout.add_seconds (KEEP_SECONDS, () => {
            loop.quit ();
            return Source.REMOVE;
        });
        // Something else was copied since: nothing of ours left to clear.
        clipboard.changed.connect (() => {
            if (!clipboard.local) {
                loop.quit ();
            }
        });
        loop.run ();
        if (clipboard.local) {
            clipboard.set_content (null);
        }
        return 0;
    }
}

public class Covalence.CodesCard : Gtk.Box {
    private const string[] MODES = { "off", "copy", "browser" };

    private Daemon daemon;
    private Gtk.DropDown mode;
    private Gtk.ListBoxRow browser_row;
    private Gtk.Label browser_status;
    private bool updating = false;

    public CodesCard (Daemon daemon) {
        Object (orientation: Gtk.Orientation.VERTICAL, spacing: 6);
        this.daemon = daemon;

        mode = new Gtk.DropDown.from_strings ({
            _("Désactivé"), _("Notification avec copie"), _("Notification et navigateur (alpha)")
        }) { valign = Gtk.Align.CENTER, selected = 1 };
        mode.notify["selected"].connect (() => {
            if (!updating && mode.selected < MODES.length) {
                daemon.call.begin ("SetOneTimeCodes", new Variant ("(s)", MODES[mode.selected]));
            }
            browser_row.visible = mode.selected == 2;
        });

        var list = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
        list.add_css_class (Granite.CssClass.CARD);
        list.append (row ("dialog-password", _("Codes de vérification"),
                          _("Quand un SMS contient un code, la notification propose « Copier le code ». "
                            + "Le presse-papiers est vidé au bout de 2 minutes."), mode));

        var install = new Gtk.Button.with_label (_("Installer l'intégration navigateur")) {
            valign = Gtk.Align.CENTER
        };
        install.clicked.connect (() => install_browser_host.begin ());
        var folder = new Gtk.Button.from_icon_name ("folder-open") {
            valign = Gtk.Align.CENTER,
            tooltip_text = _("Ouvrir le dossier de l'extension")
        };
        folder.clicked.connect (open_extension_folder);
        var buttons = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6) { valign = Gtk.Align.CENTER };
        buttons.append (folder);
        buttons.append (install);
        browser_status = new Gtk.Label (
            _("Chrome, Chromium, Edge et Firefox. Installez l'intégration, puis chargez l'extension "
              + "(mode d'emploi dans le dossier). Le code n'est mis dans la page que si vous cliquez dessus.")
        ) { xalign = 0, wrap = true };
        browser_row = (Gtk.ListBoxRow) row ("web-browser", _("Remplissage dans le navigateur (alpha)"), "",
                                            buttons, browser_status);
        browser_row.visible = false;
        list.append (browser_row);
        append (list);

        daemon.changed.connect (update);
        update ();
    }

    private void update () {
        var current = daemon.get_string ("OneTimeCodes");
        for (uint i = 0; i < MODES.length; i++) {
            if (MODES[i] == current && mode.selected != i) {
                updating = true;
                mode.selected = i;
                updating = false;
            }
        }
        mode.sensitive = daemon.running;
        browser_row.visible = mode.selected == 2;
    }

    private async void install_browser_host () {
        try {
            var reply = yield daemon.call_checked ("InstallBrowserHost");
            var browsers = reply.get_child_value (0).get_strv ();
            if (browsers.length == 0) {
                browser_status.label = _("Aucun navigateur pris en charge trouvé (Chrome, Chromium, Edge, Firefox).");
            } else {
                browser_status.label = _("Installée pour : %s. Chargez maintenant l'extension, "
                                         + "le mode d'emploi est dans le dossier.").printf (string.joinv (", ", browsers));
            }
        } catch (Error e) {
            browser_status.label = _("Installation impossible : %s").printf (e.message);
        }
    }

    private void open_extension_folder () {
        var folder = File.new_for_path (Path.build_filename (Config.PKGDATADIR, "extension"));
        new Gtk.FileLauncher (folder).launch.begin ((Gtk.Window) get_root (), null);
    }

    private static Gtk.Widget row (string icon, string title, string subtitle, Gtk.Widget end,
                                   Gtk.Label? subtitle_label = null) {
        var image = new Gtk.Image.from_icon_name (icon) { pixel_size = 32, valign = Gtk.Align.START };
        var title_label = new Gtk.Label (title) { xalign = 0 };
        var detail = subtitle_label ?? new Gtk.Label (subtitle) { xalign = 0, wrap = true };
        detail.add_css_class (Granite.CssClass.DIM);
        detail.add_css_class (Granite.CssClass.SMALL);
        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        text.append (title_label);
        text.append (detail);
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9,
            margin_bottom = 9,
            margin_start = 12,
            margin_end = 12
        };
        box.append (image);
        box.append (text);
        box.append (end);
        return new Gtk.ListBoxRow () { child = box, activatable = false };
    }
}
