/*
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: 2026 Melvin Couwez
 */

/* Réglages › Sons › Sons de Covalence: the free sounds shipped in data/sounds, one row each,
   with a preview and « Utiliser pour… ». Credits in docs/credits-sons.md and in À propos. */
public class Covalence.FreeSoundsCard : Gtk.Box {
    private struct FreeSound {
        string id;
        string name;
        bool ringtone;
        string credit;
    }

    private static FreeSound[] sounds () {
        return {
            { "rosee", _("Rosée"), false, "AOSP (Tethys) · Apache-2.0" },
            { "envol", _("Envol"), false, "AOSP (Ariel) · Apache-2.0" },
            { "vague", _("Vague"), false, "AOSP (Salacia) · Apache-2.0" },
            { "carillon", _("Carillon"), false, "Kenney · CC0" },
            { "cristal", _("Cristal"), false, "Kenney · CC0" },
            { "echo", _("Écho"), false, "AOSP (Titan) · Apache-2.0" },
            { "duo", _("Duo"), false, "AOSP (Carme) · Apache-2.0" },
            { "clochette", _("Clochette"), false, "AOSP (Rhea) · Apache-2.0" },
            { "pop", _("Pop"), false, "Kenney · CC0" },
            { "bulle", _("Bulle"), false, "Kenney · CC0" },
            { "givre", _("Givre"), false, "Kenney · CC0" },
            { "aurore", _("Aurore"), true, "AOSP (Atria) · Apache-2.0" },
            { "orbite", _("Orbite"), true, "AOSP (Ganymede) · Apache-2.0" },
            { "horizon", _("Horizon"), true, "AOSP (Sedna) · Apache-2.0" },
            { "telephone", _("Téléphone"), true, "Covalence · CC0" },
            { "ecume", _("Écume"), true, "AOSP (Luna) · Apache-2.0" },
            { "brise", _("Brise"), true, "AOSP (Umbriel) · Apache-2.0" },
            { "cascade", _("Cascade"), true, "AOSP (Dione) · Apache-2.0" },
            { "carrousel", _("Carrousel"), true, "AOSP (Callisto) · Apache-2.0" }
        };
    }

    private Daemon daemon;
    private FreeSoundRow[] rows = {};

    public FreeSoundsCard (Daemon daemon, Gtk.Window parent) {
        Object (orientation: Gtk.Orientation.VERTICAL, spacing: 6);
        this.daemon = daemon;

        var intro = new Gtk.Label (
            _("Sons libres fournis avec Covalence : écoutez-les, puis choisissez où les utiliser.")
        ) { xalign = 0, wrap = true };
        intro.add_css_class (Granite.CssClass.DIM);
        append (intro);

        var list = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
        list.add_css_class (Granite.CssClass.CARD);
        foreach (var sound in sounds ()) {
            var row = new FreeSoundRow (daemon, sound.id, sound.name, sound.ringtone, sound.credit);
            rows += row;
            list.append (row);
        }
        append (list);

        var credits = new Gtk.Button.with_label (_("Crédits des sons")) {
            halign = Gtk.Align.START,
            tooltip_text = _("Auteurs, sources et licences (fenêtre À propos, onglet Crédits)")
        };
        credits.add_css_class ("flat");
        credits.add_css_class (Granite.CssClass.SMALL);
        credits.clicked.connect (() => show_about (parent));
        append (credits);

        daemon.changed.connect (() => {
            foreach (var row in rows) {
                row.update ();
            }
        });
    }
}

private class Covalence.FreeSoundRow : Gtk.ListBoxRow {
    private const string[] KINDS = { "messages", "notifications", "calls" };

    private Daemon daemon;
    private string value;
    private string credit;
    private bool ringtone;
    private Gtk.Label detail;
    private Gtk.Button play;
    private bool playing = false;

    public FreeSoundRow (Daemon daemon, string id, string name, bool ringtone, string credit) {
        this.daemon = daemon;
        this.value = "covalence:" + id;
        this.credit = credit;
        this.ringtone = ringtone;
        activatable = false;

        var icon = new Gtk.Image.from_icon_name (ringtone ? Config.APP_ID + ".Phone"
                                                          : "preferences-system-notifications") {
            pixel_size = 32,
            valign = Gtk.Align.CENTER
        };
        var title = new Gtk.Label (name) { xalign = 0 };
        detail = new Gtk.Label ("") { xalign = 0, wrap = true };
        detail.add_css_class (Granite.CssClass.DIM);
        detail.add_css_class (Granite.CssClass.SMALL);
        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        text.append (title);
        text.append (detail);

        play = new Gtk.Button.from_icon_name ("media-playback-start-symbolic") {
            valign = Gtk.Align.CENTER,
            tooltip_text = _("Écouter")
        };
        play.add_css_class ("flat");
        play.update_property (Gtk.AccessibleProperty.LABEL, _("Écouter %s").printf (name), -1);
        play.clicked.connect (() => toggle_preview.begin ());

        var menu = new GLib.Menu ();
        menu.append (_("Messages"), "sound.use('messages')");
        menu.append (_("Notifications de l'iPhone"), "sound.use('notifications')");
        menu.append (_("Appels"), "sound.use('calls')");
        var actions = new SimpleActionGroup ();
        var use = new SimpleAction ("use", VariantType.STRING);
        use.activate.connect ((param) => {
            daemon.call.begin ("SetSound", new Variant ("(ss)", param.get_string (), value));
        });
        actions.add_action (use);
        insert_action_group ("sound", actions);
        var use_button = new Gtk.MenuButton () {
            label = _("Utiliser pour…"),
            always_show_arrow = true,
            menu_model = menu,
            valign = Gtk.Align.CENTER
        };

        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9,
            margin_bottom = 9,
            margin_start = 12,
            margin_end = 12
        };
        box.append (icon);
        box.append (text);
        box.append (play);
        box.append (use_button);
        child = box;
        update ();
    }

    /* « Notification · Kenney · CC0 », plus where the sound is in use. */
    public void update () {
        string[] used = {};
        var chosen = daemon.get_value ("Sounds");
        if (chosen != null) {
            foreach (var kind in KINDS) {
                var v = chosen.lookup_value (kind, VariantType.STRING);
                if (v != null && v.get_string () == value) {
                    used += kind_label (kind);
                }
            }
        }
        var text = "%s · %s".printf (ringtone ? _("Sonnerie") : _("Notification"), credit);
        if (used.length > 0) {
            text += "\n" + _("Utilisé pour : %s").printf (string.joinv (", ", used));
        }
        detail.label = text;
        play.sensitive = daemon.running;
    }

    private static string kind_label (string kind) {
        switch (kind) {
            case "messages": return _("Messages");
            case "notifications": return _("Notifications de l'iPhone");
            default: return _("Appels");
        }
    }

    private async void toggle_preview () {
        if (playing) {
            yield daemon.call ("StopSound");
            set_playing (false);
            return;
        }
        set_playing (true);
        var ok = yield daemon.call ("PlaySound",
                                    new Variant ("(ss)", ringtone ? "calls" : "messages", value));
        if (!ok) {
            set_playing (false);
            return;
        }
        // No end signal from the daemon: the button goes back after a short while.
        Timeout.add_seconds (ringtone ? 8 : 3, () => {
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
