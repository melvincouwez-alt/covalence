// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * iCloud Drive (or iCloud Photos) options. They are written to
 * ~/.config/covalence/drive.env (photos.env), which the covalence-icloud-drive
 * (covalence-icloud-photos) user unit reads (rclone takes its flags from
 * RCLONE_* variables), then the mount is restarted.
 *
 * iCloud Photos is always read-only: the unit passes --read-only itself.
 *
 * Covalence does not offer a two-way full sync (rclone bisync): a conflict or a
 * mass deletion could lose files. "Hors ligne" keeps the files you open, for
 * as long as you choose, within the size you choose.
 */

public class Covalence.DriveOptions : Gtk.Window {
    public bool photos { get; construct; }
    private string unit;
    private string service_name;

    private Gtk.Label folder_label;
    private string folder;
    private Gtk.DropDown cache_size;
    private Gtk.DropDown cache_age;
    private Gtk.DropDown refresh;
    private Gtk.DropDown bandwidth;
    private Gtk.Switch read_only;
    private Gtk.Switch at_login;
    private Gtk.Label usage;

    private const string[] SIZE_VALUES = { "1G", "5G", "10G", "20G", "50G" };
    private const string[] SIZE_LABELS = { N_("1 Go"), N_("5 Go"), N_("10 Go"), N_("20 Go"), N_("50 Go") };
    private const string[] AGE_VALUES = { "1h", "24h", "168h", "720h", "8760h" };
    private const string[] AGE_LABELS = { N_("1 heure"), N_("1 jour"), N_("1 semaine"), N_("1 mois"), N_("1 an") };
    private const string[] REFRESH_VALUES = { "1m", "5m", "15m", "1h" };
    private const string[] REFRESH_LABELS = { N_("Chaque minute"), N_("Toutes les 5 minutes"),
                                              N_("Toutes les 15 minutes"), N_("Toutes les heures") };
    private const string[] BW_VALUES = { "off", "10M", "2M", "512k" };
    private const string[] BW_LABELS = { N_("Sans limite"), N_("10 Mo/s"), N_("2 Mo/s"), N_("512 Ko/s") };

    public DriveOptions (Gtk.Window? parent, bool photos = false) {
        Object (transient_for: parent, modal: true, photos: photos,
                title: photos ? _("Options d'iCloud Photos") : _("Options d'iCloud Drive"),
                default_width: 520, resizable: false);
    }

    private string env_path () {
        return Setup.drive_env (photos);
    }

    construct {
        unit = Setup.drive_unit (photos);
        service_name = photos ? _("iCloud Photos") : _("iCloud Drive");
        var header = new Gtk.HeaderBar ();
        header.add_css_class ("flat");
        titlebar = header;
        var values = read_env ();
        folder = values[Setup.drive_env_key (photos)] ?? Setup.drive_folder (photos);

        // Folder
        folder_label = new Gtk.Label (display_path (folder)) {
            xalign = 0,
            ellipsize = Pango.EllipsizeMode.MIDDLE
        };
        folder_label.add_css_class (Granite.CssClass.DIM);
        folder_label.add_css_class (Granite.CssClass.SMALL);
        var choose = new Gtk.Button.with_label (_("Changer…")) { valign = Gtk.Align.CENTER };
        choose.clicked.connect (choose_folder);
        var list = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
        list.add_css_class (Granite.CssClass.CARD);
        list.append (row (_("Emplacement"), folder_label, choose));

        at_login = new Gtk.Switch () { valign = Gtk.Align.CENTER, active = Setup.drive_state (photos) != "absent" };
        list.append (row (_("Monter à l'ouverture de session"), sub (_("Le dossier apparaît dès la connexion.")), at_login));
        read_only = new Gtk.Switch () {
            valign = Gtk.Align.CENTER,
            active = values["RCLONE_READ_ONLY"] == "true"
        };
        if (!photos) {
            list.append (row (_("Lecture seule"), sub (_("Consulter sans risquer de modifier ou supprimer dans iCloud.")),
                              read_only));
        }

        // Offline copies
        var offline = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
        offline.add_css_class (Granite.CssClass.CARD);
        cache_age = drop (AGE_LABELS, AGE_VALUES, values["RCLONE_VFS_CACHE_MAX_AGE"] ?? "168h");
        offline.append (row (_("Garder hors ligne"),
                             sub (photos ? _("Les photos ouvertes restent visibles sans Internet.")
                                         : _("Les fichiers ouverts restent disponibles sans Internet.")),
                             cache_age));
        cache_size = drop (SIZE_LABELS, SIZE_VALUES, values["RCLONE_VFS_CACHE_MAX_SIZE"] ?? "5G");
        usage = sub ("");
        offline.append (row (_("Espace maximal sur ce PC"), usage, cache_size));

        // Network
        var network = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
        network.add_css_class (Granite.CssClass.CARD);
        refresh = drop (REFRESH_LABELS, REFRESH_VALUES, values["RCLONE_DIR_CACHE_TIME"] ?? (photos ? "15m" : "5m"));
        if (photos) {
            network.append (row (_("Voir les nouvelles photos"),
                                 sub (_("Délai avant qu'une photo prise sur l'iPhone apparaisse dans les albums.")),
                                 refresh));
        } else {
            network.append (row (_("Voir les changements d'iCloud"),
                                 sub (_("Délai avant qu'un ajout fait ailleurs apparaisse.")), refresh));
        }
        bandwidth = drop (BW_LABELS, BW_VALUES, values["RCLONE_BWLIMIT"] ?? "off");
        network.append (row (_("Débit maximal"), sub (_("Utile en partage de connexion avec l'iPhone.")), bandwidth));

        var note = new Gtk.Label (photos
            ? _("iCloud Photos est en lecture seule : rien ne peut être modifié ni supprimé depuis ce PC. "
              + "Chaque album est un dossier ; « All Photos » contient toute la photothèque. Les photos "
              + "que vous ouvrez sont gardées hors ligne ; pour en garder une copie, copiez-la ailleurs.")
            : _("Covalence ne propose pas de synchronisation complète dans les deux sens : un conflit ou "
              + "une suppression massive pourrait faire perdre des fichiers. Les fichiers que vous "
              + "ouvrez sont gardés hors ligne, et vos modifications sont envoyées à iCloud en quelques "
              + "secondes.")
        ) { wrap = true, xalign = 0 };
        note.add_css_class (Granite.CssClass.DIM);
        note.add_css_class (Granite.CssClass.SMALL);

        var cancel = new Gtk.Button.with_label (_("Annuler"));
        cancel.clicked.connect (() => close ());
        var apply_button = new Gtk.Button.with_label (_("Appliquer"));
        apply_button.add_css_class (Granite.CssClass.SUGGESTED);
        apply_button.clicked.connect (apply);
        var actions = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6) { halign = Gtk.Align.END, margin_top = 6 };
        actions.append (cancel);
        actions.append (apply_button);

        var content = new Gtk.Box (Gtk.Orientation.VERTICAL, 12) {
            margin_start = 24,
            margin_end = 24,
            margin_bottom = 24
        };
        content.append (new Granite.HeaderLabel (_("Dossier")));
        content.append (list);
        content.append (new Granite.HeaderLabel (_("Hors ligne")));
        content.append (offline);
        content.append (new Granite.HeaderLabel (_("Réseau")));
        content.append (network);
        content.append (note);
        content.append (actions);
        child = content;
        update_usage ();
    }

    // --- helpers ---------------------------------------------------------------------

    private static Gtk.Label sub (string text) {
        var label = new Gtk.Label (text) { xalign = 0, wrap = true };
        label.add_css_class (Granite.CssClass.DIM);
        label.add_css_class (Granite.CssClass.SMALL);
        return label;
    }

    private static Gtk.Widget row (string title, Gtk.Widget subtitle, Gtk.Widget suffix) {
        var title_label = new Gtk.Label (title) { xalign = 0 };
        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        text.append (title_label);
        text.append (subtitle);
        suffix.valign = Gtk.Align.CENTER;
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 8,
            margin_bottom = 8,
            margin_start = 12,
            margin_end = 12
        };
        box.append (text);
        box.append (suffix);
        return new Gtk.ListBoxRow () { child = box, activatable = false };
    }

    private static Gtk.DropDown drop (string[] labels, string[] values, string current) {
        string[] shown = {};
        foreach (var label in labels) {
            shown += _(label);
        }
        var dropdown = new Gtk.DropDown.from_strings (shown);
        for (int i = 0; i < values.length; i++) {
            if (values[i] == current) {
                dropdown.selected = i;
            }
        }
        return dropdown;
    }

    private static string display_path (string path) {
        var home = Environment.get_home_dir ();
        return path.has_prefix (home + "/") ? "~" + path.substring (home.length) : path;
    }

    private HashTable<string, string> read_env () {
        var values = new HashTable<string, string> (str_hash, str_equal);
        string text;
        try {
            FileUtils.get_contents (env_path (), out text);
        } catch (Error e) {
            return values;
        }
        foreach (var line in text.split ("\n")) {
            var eq = line.index_of ("=");
            if (line.has_prefix ("#") || eq < 1) {
                continue;
            }
            var value = line.substring (eq + 1).strip ();
            if (value.has_prefix ("\"") && value.has_suffix ("\"") && value.length >= 2) {
                value = value.substring (1, value.length - 2);
            }
            values[line.substring (0, eq).strip ()] = value;
        }
        return values;
    }

    private void update_usage () {
        var cache = Path.build_filename (Environment.get_user_cache_dir (), "rclone", "vfs",
                                         photos ? "icloud-photos" : "icloud");
        var bytes = directory_size (File.new_for_path (cache));
        usage.label = _("Actuellement %s de fichiers gardés sur ce PC.").printf (format_size (bytes));
    }

    private static uint64 directory_size (File dir) {
        uint64 total = 0;
        try {
            var children = dir.enumerate_children ("standard::name,standard::type,standard::size",
                                                   FileQueryInfoFlags.NOFOLLOW_SYMLINKS);
            FileInfo? info;
            while ((info = children.next_file ()) != null) {
                if (info.get_file_type () == FileType.DIRECTORY) {
                    total += directory_size (dir.get_child (info.get_name ()));
                } else {
                    total += info.get_size ();
                }
            }
        } catch (Error e) {
            // missing cache: nothing kept yet
        }
        return total;
    }

    private void choose_folder () {
        var dialog = new Gtk.FileDialog () {
            title = _("Emplacement d'%s").printf (service_name),
            initial_folder = File.new_for_path (Environment.get_home_dir ())
        };
        dialog.select_folder.begin (this, null, (obj, res) => {
            try {
                var chosen = dialog.select_folder.end (res);
                var path = chosen.get_path ();
                if (path == null) {
                    return;
                }
                if (path != folder && !is_empty (chosen)) {
                    // rclone would hide what is already there: ask for an empty folder.
                    path = Path.build_filename (path, service_name);
                }
                folder = path;
                folder_label.label = display_path (folder);
            } catch (Error e) {
                // cancelled
            }
        });
    }

    private static bool is_empty (File dir) {
        try {
            var children = dir.enumerate_children ("standard::name", FileQueryInfoFlags.NONE);
            return children.next_file () == null;
        } catch (Error e) {
            return true;
        }
    }

    private void apply () {
        var text = new StringBuilder ("# Written by Covalence (%s options).\n".printf (service_name));
        text.append_printf ("%s=\"%s\"\n", Setup.drive_env_key (photos), folder.replace ("\"", ""));
        text.append_printf ("RCLONE_VFS_CACHE_MAX_SIZE=%s\n", SIZE_VALUES[cache_size.selected]);
        text.append_printf ("RCLONE_VFS_CACHE_MAX_AGE=%s\n", AGE_VALUES[cache_age.selected]);
        text.append_printf ("RCLONE_DIR_CACHE_TIME=%s\n", REFRESH_VALUES[refresh.selected]);
        text.append_printf ("RCLONE_BWLIMIT=%s\n", BW_VALUES[bandwidth.selected]);
        if (!photos) {
            text.append_printf ("RCLONE_READ_ONLY=%s\n", read_only.active ? "true" : "false");
        }
        var old_folder = read_env ()[Setup.drive_env_key (photos)] ?? Setup.drive_folder (photos);
        try {
            DirUtils.create_with_parents (Path.get_dirname (env_path ()), 0700);
            FileUtils.set_contents_full (env_path (), text.str, -1, FileSetContentsFlags.CONSISTENT, 0600);
        } catch (Error e) {
            warning ("cannot save %s options: %s", service_name, e.message);
            return;
        }
        var bookmark_changed = old_folder != folder;
        string[] enable = { at_login.active ? "enable" : "disable", unit };
        string[] apply_now = { at_login.active ? "restart" : "stop", unit };
        run_systemctl (enable);
        // Restart to apply the options (the unit stops first, so a moved folder is unmounted).
        run_systemctl (apply_now, () => {
            if (bookmark_changed) {
                // The old mount point is empty once unmounted (rmdir leaves it otherwise).
                DirUtils.remove (old_folder);
                Setup.run_helper ("covalence-icloud-drive",
                                  photos ? new string[] { "--photos", "--bookmark" } : new string[] { "--bookmark" });
            }
        });
        close ();
    }

    private delegate void Done ();

    private static void run_systemctl (string[] args, owned Done? done = null) {
        string[] argv = { "systemctl", "--user" };
        foreach (var a in args) {
            argv += a;
        }
        try {
            var process = new Subprocess.newv (argv, SubprocessFlags.STDERR_SILENCE);
            process.wait_async.begin (null, () => {
                if (done != null) {
                    done ();
                }
            });
        } catch (Error e) {
            warning ("systemctl failed: %s", e.message);
        }
    }
}
