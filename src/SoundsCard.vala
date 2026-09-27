/*
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2026 Melvin Couwez
 */

/* Réglages › Sons: one sound for messages, one for iPhone notifications, one ringtone.
   The daemon plays them (Sounds on the bus: none, default, a theme sound name or a file). */
public class Covalence.SoundsCard : Gtk.Box {
    private Daemon daemon;
    private SoundRow[] rows = {};

    public SoundsCard (Daemon daemon) {
        Object (orientation: Gtk.Orientation.VERTICAL, spacing: 6);
        this.daemon = daemon;

        var list = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
        list.add_css_class (Granite.CssClass.CARD);
        rows += new SoundRow (daemon, "messages", Config.APP_ID + ".Messages", _("Messages"),
                              _("SMS reçus"));
        rows += new SoundRow (daemon, "notifications", "preferences-system-notifications",
                              _("Notifications de l'iPhone"), _("Autres apps de l'iPhone"));
        rows += new SoundRow (daemon, "calls", Config.APP_ID + ".Phone", _("Appels"),
                              _("Sonnerie, répétée tant que l'appel sonne"));
        foreach (var row in rows) {
            list.append (row);
        }
        append (list);

        var hint = new Gtk.Label (
            _("Aucun son en mode Ne pas déranger. Si l'iPhone fait déjà sonner l'appel sur ce PC, "
              + "la sonnerie de Covalence se tait.")
        ) { xalign = 0, wrap = true };
        hint.add_css_class (Granite.CssClass.DIM);
        hint.add_css_class (Granite.CssClass.SMALL);
        append (hint);

        load.begin ();
        daemon.changed.connect (() => {
            foreach (var row in rows) {
                row.update ();
            }
        });
    }

    private async void load () {
        string[] values = {};
        string[] labels = {};
        try {
            var reply = yield daemon.call_checked ("ListSounds");
            var array = reply.get_child_value (0);
            for (size_t i = 0; i < array.n_children (); i++) {
                string value, label;
                array.get_child (i, "(ss)", out value, out label);
                values += value;
                labels += label;
            }
        } catch (Error e) {
            warning ("ListSounds failed: %s", e.message);
        }
        foreach (var row in rows) {
            row.set_sounds (values, labels);
        }
    }
}

private class Covalence.SoundRow : Gtk.ListBoxRow {
    private Daemon daemon;
    private string kind;
    private Gtk.DropDown choice;
    private Gtk.StringList model;
    private string[] values = {};
    private string[] theme_values = {};
    private string[] theme_labels = {};
    private bool updating = false;
    private Gtk.Button play;
    private bool playing = false;

    public SoundRow (Daemon daemon, string kind, string icon, string title, string subtitle) {
        this.daemon = daemon;
        this.kind = kind;
        activatable = false;

        var image = new Gtk.Image.from_icon_name (icon) { pixel_size = 32, valign = Gtk.Align.CENTER };
        var title_label = new Gtk.Label (title) { xalign = 0 };
        var detail = new Gtk.Label (subtitle) { xalign = 0, wrap = true };
        detail.add_css_class (Granite.CssClass.DIM);
        detail.add_css_class (Granite.CssClass.SMALL);
        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        text.append (title_label);
        text.append (detail);

        model = new Gtk.StringList (null);
        choice = new Gtk.DropDown (model, null) { valign = Gtk.Align.CENTER };
        choice.update_property (Gtk.AccessibleProperty.LABEL, title, -1);
        choice.notify["selected"].connect (on_selected);

        play = new Gtk.Button.from_icon_name ("media-playback-start-symbolic") {
            valign = Gtk.Align.CENTER,
            tooltip_text = _("Écouter")
        };
        play.add_css_class ("flat");
        play.clicked.connect (() => toggle_preview.begin ());

        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9,
            margin_bottom = 9,
            margin_start = 12,
            margin_end = 12
        };
        box.append (image);
        box.append (text);
        box.append (choice);
        box.append (play);
        child = box;
        rebuild ();
    }

    public void set_sounds (string[] values, string[] labels) {
        theme_values = values;
        theme_labels = labels;
        rebuild ();
    }

    private string current () {
        var sounds = daemon.get_value ("Sounds");
        if (sounds != null) {
            var v = sounds.lookup_value (kind, VariantType.STRING);
            if (v != null && v.get_string () != "") {
                return v.get_string ();
            }
        }
        return "default";
    }

    /* Aucun, Par défaut, the theme sounds, the chosen file if any, then Choisir un fichier… */
    private void rebuild () {
        updating = true;
        var value = current ();
        string[] items = { _("Aucun"), _("Par défaut") };
        values = { "none", "default" };
        for (int i = 0; i < theme_values.length; i++) {
            items += theme_labels[i];
            values += theme_values[i];
        }
        if (Path.is_absolute (value)) {
            var name = Path.get_basename (value);
            var dot = name.last_index_of_char ('.');
            items += dot > 0 ? name.substring (0, dot) : name;
            values += value;
        }
        items += _("Choisir un fichier…");
        values += "";
        model.splice (0, model.get_n_items (), items);
        choice.selected = index_of (value);
        choice.sensitive = daemon.running;
        play.sensitive = daemon.running && value != "none";
        updating = false;
    }

    public void update () {
        var value = current ();
        if (index_of (value) == Gtk.INVALID_LIST_POSITION
            || (Path.is_absolute (value) && values[choice.selected] != value)) {
            rebuild ();
            return;
        }
        if (values[choice.selected] != value) {
            updating = true;
            choice.selected = index_of (value);
            updating = false;
        }
        choice.sensitive = daemon.running;
        play.sensitive = daemon.running && value != "none";
    }

    private uint index_of (string value) {
        for (uint i = 0; i < values.length; i++) {
            if (values[i] == value && value != "") {
                return i;
            }
        }
        // a theme sound not installed any more: show « Par défaut »
        return values.length > 1 ? 1 : Gtk.INVALID_LIST_POSITION;
    }

    private void on_selected () {
        if (updating || choice.selected >= values.length) {
            return;
        }
        var value = values[choice.selected];
        if (value == "") {
            choose_file.begin ();
            return;
        }
        daemon.call.begin ("SetSound", new Variant ("(ss)", kind, value));
        play.sensitive = value != "none";
    }

    private async void choose_file () {
        var filter = new Gtk.FileFilter () { name = _("Sons") };
        filter.add_mime_type ("audio/*");
        var filters = new ListStore (typeof (Gtk.FileFilter));
        filters.append (filter);
        var dialog = new Gtk.FileDialog () {
            title = _("Choisir un son"),
            modal = true,
            filters = filters,
            default_filter = filter
        };
        try {
            var file = yield dialog.open ((Gtk.Window) get_root (), null);
            var path = file.get_path ();
            if (path != null) {
                try {
                    yield daemon.call_checked ("SetSound", new Variant ("(ss)", kind, path));
                } catch (Error e) {
                    warning ("SetSound failed: %s", e.message);
                }
            }
        } catch (Error e) {
            // cancelled
        }
        rebuild ();
    }

    private async void toggle_preview () {
        if (playing) {
            yield daemon.call ("StopSound");
            set_playing (false);
            return;
        }
        var value = choice.selected < values.length ? values[choice.selected] : "default";
        if (value == "" || value == "none") {
            return;
        }
        set_playing (true);
        var ok = yield daemon.call ("PlaySound", new Variant ("(ss)", kind, value));
        if (!ok) {
            set_playing (false);
            return;
        }
        // No end signal from the daemon: the button goes back after a short while.
        Timeout.add_seconds (kind == "calls" ? 8 : 3, () => {
            set_playing (false);
            return Source.REMOVE;
        });
    }

    private void set_playing (bool now) {
        playing = now;
        play.icon_name = now ? "media-playback-stop-symbolic" : "media-playback-start-symbolic";
        play.tooltip_text = now ? _("Arrêter") : _("Écouter");
    }
}
