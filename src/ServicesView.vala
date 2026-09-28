// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * "Services Apple" tab: what goes through the Internet with the Apple account,
 * kept apart from the iPhone (Bluetooth). iCloud account (mail, calendars,
 * reminders, contacts), iCloud Drive, iCloud Photos, and the apps that show them.
 */

public class Covalence.ServicesView : Gtk.Box {
    public Daemon daemon { get; construct; }

    private Gtk.Label account_state;
    private Gtk.Switch account_switch;
    private Gtk.Button account_button;
    private Gtk.Label drive_state;
    private Gtk.Button drive_open;
    private Gtk.Button drive_connect;
    private Gtk.Button drive_remove;
    private Gtk.Button drive_options;
    private Gtk.Label photos_state;
    private Gtk.Button photos_open;
    private Gtk.Button photos_connect;
    private Gtk.Button photos_remove;
    private Gtk.Button photos_options;
    private Gtk.ListBox apps;
    private bool updating = false;

    public ServicesView (Daemon daemon) {
        Object (daemon: daemon, orientation: Gtk.Orientation.VERTICAL, spacing: 0);
    }

    construct {
        var head = page_header ("preferences-desktop-online-accounts", _("Services Apple"),
            _("Votre compte Apple par Internet : courriel, agendas, rappels, contacts, fichiers "
            + "iCloud et Apple Music dans les apps d'elementary. Indépendant de l'iPhone."));

        // iCloud account (app-specific password, Evolution Data Server)
        account_state = dim_label ();
        account_switch = new Gtk.Switch () { valign = Gtk.Align.CENTER };
        account_switch.notify["active"].connect (() => {
            if (!updating) {
                daemon.set_module_enabled ("icloud", account_switch.active);
            }
        });
        account_button = new Gtk.Button.with_label (_("Se connecter…")) { valign = Gtk.Align.CENTER };
        account_button.clicked.connect (() => Setup.run_helper ("covalence-icloud-signin"));
        var account = card_row ("preferences-desktop-online-accounts", _("Compte iCloud"), account_state,
                                { Guide.help_button ("apple", _("Mot de passe pour app : comment faire")),
                                  account_button, account_switch });

        // iCloud Drive (rclone)
        drive_state = dim_label ();
        drive_open = new Gtk.Button.with_label (_("Ouvrir")) { valign = Gtk.Align.CENTER };
        drive_open.clicked.connect (() => Setup.open_drive_folder (get_root () as Gtk.Window));
        drive_connect = new Gtk.Button.with_label (_("Connecter…")) { valign = Gtk.Align.CENTER };
        drive_connect.clicked.connect (() => Setup.run_helper ("covalence-icloud-drive"));
        drive_remove = new Gtk.Button.from_icon_name ("edit-delete-symbolic") {
            valign = Gtk.Align.CENTER,
            tooltip_text = _("Déconnecter iCloud Drive")
        };
        drive_remove.add_css_class ("flat");
        drive_remove.clicked.connect (() => confirm_removal (false));
        drive_options = new Gtk.Button.from_icon_name ("preferences-system-symbolic") {
            valign = Gtk.Align.CENTER,
            tooltip_text = _("Options d'iCloud Drive : emplacement, hors ligne, réseau")
        };
        drive_options.add_css_class ("flat");
        drive_options.clicked.connect (() => new DriveOptions (get_root () as Gtk.Window).present ());
        var drive = card_row ("folder-remote", _("iCloud Drive"), drive_state,
                              { Guide.help_button ("apple", _("iCloud Drive et Photos : à lire avant de vous connecter")),
                                drive_open, drive_connect, drive_options, drive_remove });

        // iCloud Photos (rclone, read-only)
        photos_state = dim_label ();
        photos_open = new Gtk.Button.with_label (_("Ouvrir")) { valign = Gtk.Align.CENTER };
        photos_open.clicked.connect (() => Setup.open_drive_folder (get_root () as Gtk.Window, true));
        photos_connect = new Gtk.Button.with_label (_("Connecter…")) { valign = Gtk.Align.CENTER };
        photos_connect.clicked.connect (() => Setup.run_helper ("covalence-icloud-drive", { "--photos" }));
        photos_remove = new Gtk.Button.from_icon_name ("edit-delete-symbolic") {
            valign = Gtk.Align.CENTER,
            tooltip_text = _("Déconnecter iCloud Photos")
        };
        photos_remove.add_css_class ("flat");
        photos_remove.clicked.connect (() => confirm_removal (true));
        photos_options = new Gtk.Button.from_icon_name ("preferences-system-symbolic") {
            valign = Gtk.Align.CENTER,
            tooltip_text = _("Options d'iCloud Photos : emplacement, hors ligne, réseau")
        };
        photos_options.add_css_class ("flat");
        photos_options.clicked.connect (() => new DriveOptions (get_root () as Gtk.Window, true).present ());
        var photos = card_row ("folder-pictures", _("iCloud Photos"), photos_state,
                               { photos_open, photos_connect, photos_options, photos_remove });

        var services = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
        services.add_css_class (Granite.CssClass.CARD);
        services.append (account);
        services.append (drive);
        services.append (photos);

        // Apps that show the account: open them, or install them from AppCenter
        apps = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
        apps.add_css_class (Granite.CssClass.CARD);
        fill_apps ();

        var guide = new AppleGuide (daemon);
        var expander = new Gtk.Expander (_("Guide de connexion")) { child = guide };
        guide.margin_top = 12;

        var content = new Gtk.Box (Gtk.Orientation.VERTICAL, 12) {
            margin_top = 18,
            margin_bottom = 24,
            margin_start = 24,
            margin_end = 24,
            width_request = 560,
            halign = Gtk.Align.CENTER
        };
        content.append (head);
        content.append (new Granite.HeaderLabel (_("Connexions")));
        content.append (services);
        // Calendar and contacts: Covalence's app or elementary's
        var defaults = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
        defaults.add_css_class (Granite.CssClass.CARD);
        defaults.append (new AppChoiceRow (AppChoice.calendar ()));
        defaults.append (new AppChoiceRow (AppChoice.contacts ()));
        content.append (new Granite.HeaderLabel (_("Apps par défaut")));
        content.append (defaults);
        content.append (new Granite.HeaderLabel (_("Apps")));
        content.append (apps);
        content.append (new Granite.HeaderLabel (_("Sur iCloud.com")));
        content.append (WebShortcuts.card ());
        content.append (expander);
        append (new Gtk.ScrolledWindow () {
            child = content,
            hscrollbar_policy = Gtk.PolicyType.NEVER,
            vexpand = true
        });

        daemon.changed.connect (update);
        map.connect (update);
        map.connect (fill_apps);
        Timeout.add_seconds (5, () => {
            if (get_mapped ()) {
                update ();
            }
            return Source.CONTINUE;
        });
    }

    private void update () {
        updating = true;
        account_switch.active = daemon.module_enabled ("icloud");
        updating = false;
        var state = daemon.get_string ("ICloudState");
        string text;
        switch (state) {
            case "connected":
                text = _("Connecté : courriel, agendas, rappels et contacts");
                break;
            case "attention":
                text = _("Connecté, mais une source n'a pas pu s'authentifier");
                break;
            case "rejected":
                text = _("Mot de passe pour app refusé : créez-en un nouveau");
                break;
            case "disabled":
                text = _("Désactivé");
                break;
            case "unavailable":
                text = _("Evolution Data Server indisponible");
                break;
            default:
                text = _("Non connecté");
                break;
        }
        account_state.label = text;
        account_button.label = state == "absent" ? _("Se connecter…") : _("Se reconnecter…");

        var drive = Setup.drive_state ();
        drive_state.label = drive == "mounted"
                          ? _("Dans Fichiers : dossier « %s »").printf (Path.get_basename (Setup.drive_folder ()))
                          : drive == "configured" ? _("Connecté, dossier non monté pour l'instant")
                          : _("Non connecté");
        drive_open.visible = drive == "mounted";
        drive_connect.visible = drive != "mounted";
        drive_connect.label = drive == "absent" ? _("Connecter…") : _("Reconnecter…");
        drive_remove.visible = drive != "absent";
        drive_options.visible = drive != "absent";

        var photos = Setup.drive_state (true);
        photos_state.label = photos == "mounted"
                           ? _("Dans Fichiers : dossier « %s », en lecture seule").printf (
                                 Path.get_basename (Setup.drive_folder (true)))
                           : photos == "configured" ? _("Connecté, dossier non monté pour l'instant")
                           : _("Non connecté : vos albums en lecture seule dans Fichiers");
        photos_open.visible = photos == "mounted";
        photos_connect.visible = photos != "mounted";
        photos_connect.label = photos == "absent" ? _("Connecter…") : _("Reconnecter…");
        photos_remove.visible = photos != "absent";
        photos_options.visible = photos != "absent";
    }

    private struct CatalogEntry {
        string name;
        string text;
        string desktop_id;
        string? appstream_id;
        string? content_type;
    }

    /* Rebuilt whenever the tab shows, so an app installed meanwhile turns into "Ouvrir". */
    private void fill_apps () {
        CatalogEntry[] entries = {
            { _("Courriel"), _("Votre boîte iCloud"), "io.elementary.mail", "io.elementary.mail", null },
            { _("Tâches"), _("Vos rappels iCloud"), "io.elementary.tasks", "io.elementary.tasks", null },
            { _("Fichiers"), _("iCloud Drive dans la barre latérale"), "io.elementary.files", null, null },
            { _("Photos"), _("Vos images, y compris celles d'iCloud Drive"), "io.elementary.photos",
              "io.elementary.photos", null },
            { _("Apple Music"), _("Écouter avec Aria, votre compte Apple Music"), "io.github.melvincouwez.Aria",
              null, null },
        };
        Gtk.Widget? child;
        while ((child = apps.get_first_child ()) != null) {
            apps.remove (child);
        }
        foreach (var e in entries) {
            var row = catalog_row (e);
            if (row != null) {
                apps.append (row);
            }
        }
    }

    private Gtk.Widget? catalog_row (CatalogEntry e) {
        AppInfo? info = e.content_type != null ? AppInfo.get_default_for_type (e.content_type, false) : null;
        if (info == null) {
            info = new DesktopAppInfo (e.desktop_id + ".desktop");
        }
        if (info == null && e.appstream_id == null) {
            return null;  // neither installed nor installable: not offered
        }
        var state = dim_label ();
        state.label = e.text;
        Gtk.Button action;
        if (info != null) {
            action = new Gtk.Button.with_label (_("Ouvrir"));
            var app = info;
            action.clicked.connect (() => {
                try {
                    app.launch (null, get_display ().get_app_launch_context ());
                } catch (Error err) {
                    warning ("cannot open %s: %s", e.desktop_id, err.message);
                }
            });
        } else {
            action = new Gtk.Button.with_label (_("Installer…"));
            action.tooltip_text = _("Ouvrir la fiche dans AppCenter");
            var id = e.appstream_id;
            action.clicked.connect (() => {
                new Gtk.UriLauncher ("appstream://" + id).launch.begin (get_root () as Gtk.Window, null);
            });
        }
        action.valign = Gtk.Align.CENTER;
        var icon = info != null ? info.get_icon () : null;
        var image = icon != null ? new Gtk.Image.from_gicon (icon)
                                 : new Gtk.Image.from_icon_name ("system-software-install");
        image.pixel_size = 32;
        var title_label = new Gtk.Label (e.name) { xalign = 0 };
        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        text.append (title_label);
        text.append (state);
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9,
            margin_bottom = 9,
            margin_start = 12,
            margin_end = 12
        };
        box.append (image);
        box.append (text);
        box.append (action);
        return new Gtk.ListBoxRow () { child = box, activatable = false };
    }

    private void confirm_removal (bool photos) {
        var dialog = new Granite.MessageDialog.with_image_from_icon_name (
            photos ? _("Déconnecter iCloud Photos ?") : _("Déconnecter iCloud Drive ?"),
            photos ? _("Le dossier disparaît de Fichiers et la connexion est oubliée sur ce PC. "
                       + "Vos photos restent dans iCloud.")
                   : _("Le dossier disparaît de Fichiers et la connexion est oubliée sur ce PC. "
                       + "Vos fichiers restent dans iCloud."),
            photos ? "folder-pictures" : "folder-remote", Gtk.ButtonsType.CANCEL) {
            transient_for = get_root () as Gtk.Window,
            modal = true
        };
        var remove = dialog.add_button (_("Déconnecter"), Gtk.ResponseType.ACCEPT);
        remove.add_css_class (Granite.CssClass.DESTRUCTIVE);
        dialog.response.connect ((response) => {
            if (response == Gtk.ResponseType.ACCEPT) {
                Setup.run_helper ("covalence-icloud-drive",
                                  photos ? new string[] { "--photos", "--remove" } : new string[] { "--remove" });
                Timeout.add_seconds (3, () => {
                    update ();
                    return Source.REMOVE;
                });
            }
            dialog.destroy ();
        });
        dialog.present ();
    }

    // --- building blocks ---------------------------------------------------------------

    private static Gtk.Label dim_label () {
        var label = new Gtk.Label ("") { xalign = 0, wrap = true };
        label.add_css_class (Granite.CssClass.DIM);
        label.add_css_class (Granite.CssClass.SMALL);
        return label;
    }

    private static Gtk.Widget card_row (string icon, string title, Gtk.Label state, Gtk.Widget[] suffix) {
        var image = new Gtk.Image.from_icon_name (icon) { pixel_size = 32 };
        var title_label = new Gtk.Label (title) { xalign = 0 };
        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        text.append (title_label);
        text.append (state);
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9,
            margin_bottom = 9,
            margin_start = 12,
            margin_end = 12
        };
        box.append (image);
        box.append (text);
        foreach (var widget in suffix) {
            box.append (widget);
        }
        return new Gtk.ListBoxRow () { child = box, activatable = false };
    }

    private Gtk.Widget app_row (string title, string subtitle, string app_id, string? content_type) {
        AppInfo? info = content_type != null ? AppInfo.get_default_for_type (content_type, false) : null;
        if (info == null) {
            info = new DesktopAppInfo (app_id + ".desktop");
        }
        var state = dim_label ();
        state.label = info != null ? subtitle : _("Non installée");
        var open = new Gtk.Button.with_label (_("Ouvrir")) { sensitive = info != null, valign = Gtk.Align.CENTER };
        open.clicked.connect (() => {
            try {
                info.launch (null, get_display ().get_app_launch_context ());
            } catch (Error e) {
                warning ("cannot open %s: %s", app_id, e.message);
            }
        });
        var icon = info != null ? info.get_icon () : null;
        var image = icon != null ? new Gtk.Image.from_gicon (icon) : new Gtk.Image.from_icon_name ("application-x-executable");
        image.pixel_size = 32;
        var title_label = new Gtk.Label (title) { xalign = 0 };
        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        text.append (title_label);
        text.append (state);
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9,
            margin_bottom = 9,
            margin_start = 12,
            margin_end = 12
        };
        box.append (image);
        box.append (text);
        box.append (open);
        return new Gtk.ListBoxRow () { child = box, activatable = false };
    }
}

namespace Covalence {
    /* Big icon, title and one line of explanation at the top of a tab. */
    public Gtk.Widget page_header (string icon, string title, string text) {
        var image = new Gtk.Image.from_icon_name (icon) { pixel_size = 64 };
        var title_label = new Gtk.Label (title) { xalign = 0 };
        title_label.add_css_class (Granite.HeaderLabel.Size.H1.to_string ());
        var text_label = new Gtk.Label (text) { xalign = 0, wrap = true };
        text_label.add_css_class (Granite.CssClass.DIM);
        var titles = new Gtk.Box (Gtk.Orientation.VERTICAL, 4) { valign = Gtk.Align.CENTER, hexpand = true };
        titles.append (title_label);
        titles.append (text_label);
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 16) { margin_bottom = 6 };
        box.append (image);
        box.append (titles);
        return box;
    }
}
