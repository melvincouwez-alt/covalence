// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * "Mises à jour" at the top of Réglages, like Software Update on the iPhone.
 *
 * covalenced/updates.py checks the GitHub releases and publishes the Update property.
 * With a new version: a card first on the page (icon, version, size, the start of the
 * notes, "Mettre à jour maintenant", progress while downloading and installing). Without:
 * one quiet line "Covalence est à jour" with "Rechercher maintenant" and the automatic
 * check switch.
 */

public class Covalence.UpdatesCard : Gtk.Box {
    private const int NOTES_LENGTH = 280;

    private Daemon daemon;
    private Gtk.Box feature;
    private Gtk.Label version_label;
    private Gtk.Label size_label;
    private Gtk.Label notes_label;
    private Gtk.LinkButton more;
    private Gtk.ProgressBar progress;
    private Gtk.Label feature_status;
    private Gtk.Button update_button;
    private Gtk.Label status_label;
    private Gtk.Button check_button;
    private Gtk.Spinner spinner;
    private Gtk.Switch auto_switch;
    private bool updating = false;
    private string url = "";

    public UpdatesCard (Daemon daemon) {
        Object (orientation: Gtk.Orientation.VERTICAL, spacing: 12);
        this.daemon = daemon;

        // The new version, first on the page.
        var icon = new Gtk.Image.from_icon_name (Config.APP_ID) { pixel_size = 64, valign = Gtk.Align.START };
        version_label = new Gtk.Label ("") { xalign = 0 };
        version_label.add_css_class (Granite.HeaderLabel.Size.H3.to_string ());
        size_label = new Gtk.Label ("") { xalign = 0 };
        size_label.add_css_class (Granite.CssClass.DIM);
        size_label.add_css_class (Granite.CssClass.SMALL);
        var heading = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { valign = Gtk.Align.CENTER };
        heading.append (version_label);
        heading.append (size_label);
        var top = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12);
        top.append (icon);
        top.append (heading);

        notes_label = new Gtk.Label ("") { xalign = 0, wrap = true, wrap_mode = Pango.WrapMode.WORD_CHAR };
        more = new Gtk.LinkButton.with_label ("", _("En savoir plus")) { halign = Gtk.Align.START };
        progress = new Gtk.ProgressBar () { visible = false };
        feature_status = new Gtk.Label ("") { xalign = 0, wrap = true, visible = false };
        feature_status.add_css_class (Granite.CssClass.SMALL);
        update_button = new Gtk.Button.with_label (_("Mettre à jour maintenant")) { hexpand = true };
        update_button.add_css_class (Granite.CssClass.SUGGESTED);
        update_button.clicked.connect (on_update_clicked);

        feature = new Gtk.Box (Gtk.Orientation.VERTICAL, 9) {
            margin_top = 15,
            margin_bottom = 15,
            margin_start = 15,
            margin_end = 15
        };
        feature.append (top);
        feature.append (notes_label);
        feature.append (more);
        feature.append (progress);
        feature.append (feature_status);
        feature.append (update_button);
        var feature_card = new Gtk.Box (Gtk.Orientation.VERTICAL, 0);
        feature_card.add_css_class (Granite.CssClass.CARD);
        feature_card.append (feature);
        feature.set_data<Gtk.Widget> ("card", feature_card);

        // The quiet part: state, "Rechercher maintenant", automatic checks.
        status_label = new Gtk.Label ("") { xalign = 0, hexpand = true, wrap = true };
        spinner = new Gtk.Spinner () { visible = false };
        check_button = new Gtk.Button.with_label (_("Rechercher maintenant")) { valign = Gtk.Align.CENTER };
        check_button.clicked.connect (() => check_now.begin ());
        var status_row = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 9) {
            margin_top = 9,
            margin_bottom = 9,
            margin_start = 12,
            margin_end = 12
        };
        status_row.append (status_label);
        status_row.append (spinner);
        status_row.append (check_button);

        var auto_label = new Gtk.Label (_("Mises à jour automatiques : rechercher")) { xalign = 0, hexpand = true };
        auto_switch = new Gtk.Switch () { valign = Gtk.Align.CENTER };
        auto_switch.update_property (Gtk.AccessibleProperty.LABEL, auto_label.label, -1);
        auto_switch.notify["active"].connect (() => {
            if (!updating) {
                daemon.call.begin ("SetUpdateChecks", new Variant ("(b)", auto_switch.active));
            }
        });
        var auto_row = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9,
            margin_bottom = 9,
            margin_start = 12,
            margin_end = 12
        };
        auto_row.append (auto_label);
        auto_row.append (auto_switch);

        var list = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
        list.add_css_class (Granite.CssClass.CARD);
        list.append (new Gtk.ListBoxRow () { child = status_row, activatable = false });
        list.append (new Gtk.ListBoxRow () { child = auto_row, activatable = false });

        append (feature_card);
        append (list);

        daemon.changed.connect (update);
        // "vérifié il y a N min" keeps up with the clock.
        Timeout.add_seconds (60, () => {
            update ();
            return Source.CONTINUE;
        });
        update ();
    }

    /* 1 when a new version waits (the badge on Réglages in the sidebar). */
    public static uint pending (Daemon daemon) {
        var v = daemon.get_value ("Update");
        if (v == null) {
            return 0;
        }
        var state = lookup_string (v, "state");
        return lookup_string (v, "latest") != "" && state != "ready" ? 1 : 0;
    }

    private static string lookup_string (Variant dict, string key) {
        var v = dict.lookup_value (key, VariantType.STRING);
        return v != null ? v.get_string () : "";
    }

    private static int64 lookup_int64 (Variant dict, string key) {
        var v = dict.lookup_value (key, VariantType.INT64);
        return v != null ? v.get_int64 () : 0;
    }

    private static bool lookup_bool (Variant dict, string key, bool fallback) {
        var v = dict.lookup_value (key, VariantType.BOOLEAN);
        return v != null ? v.get_boolean () : fallback;
    }

    private static double lookup_double (Variant dict, string key) {
        var v = dict.lookup_value (key, VariantType.DOUBLE);
        return v != null ? v.get_double () : 0;
    }

    private void update () {
        var v = daemon.get_value ("Update");
        var card = feature.get_data<Gtk.Widget> ("card");
        if (v == null) {
            card.visible = false;
            status_label.label = _("Version installée : %s").printf (Config.VERSION);
            check_button.sensitive = false;
            auto_switch.sensitive = false;
            return;
        }
        var state = lookup_string (v, "state");
        var current = lookup_string (v, "current");
        var latest = lookup_string (v, "latest");
        var checked = lookup_int64 (v, "checked");
        var error = lookup_string (v, "error");
        url = lookup_string (v, "url");

        updating = true;
        auto_switch.active = lookup_bool (v, "auto", true);
        updating = false;
        auto_switch.sensitive = true;

        var busy = state == "checking" || state == "downloading" || state == "installing";
        spinner.visible = state == "checking";
        spinner.spinning = state == "checking";
        check_button.sensitive = !busy;

        var when = checked > 0 ? _("vérifié %s").printf (relative (checked)) : _("jamais vérifié");
        if (state == "ready") {
            status_label.label = _("Mise à jour installée : relancez Covalence pour l'utiliser");
        } else if (state == "checking") {
            status_label.label = _("Recherche de mises à jour…");
        } else if (latest != "") {
            status_label.label = _("Version installée : %s, %s").printf (current, when);
        } else if (state == "error") {
            status_label.label = error;
        } else {
            status_label.label = _("Covalence est à jour : %s, %s").printf (current, when);
        }

        card.visible = latest != "" || state == "ready";
        if (!card.visible) {
            return;
        }
        if (state == "ready") {
            version_label.label = _("Mise à jour installée");
            size_label.label = _("Relancez Covalence pour passer à la nouvelle version.");
            notes_label.visible = false;
            more.visible = false;
            progress.visible = false;
            feature_status.visible = false;
            update_button.label = _("Relancer Covalence");
            update_button.sensitive = true;
            return;
        }
        version_label.label = "Covalence %s".printf (latest);
        var size = lookup_int64 (v, "size");
        var prerelease = latest.contains ("-") || current.contains ("-");
        size_label.label = size > 0 ? format_size (size) : "";
        if (prerelease && latest.contains ("-")) {
            size_label.label += (size > 0 ? " · " : "") + _("préversion");
        }
        notes_label.label = short_notes (lookup_string (v, "notes"));
        notes_label.visible = notes_label.label != "";
        more.uri = url;
        more.visible = url != "";

        var can_install = lookup_bool (v, "can_install", false);
        progress.visible = state == "downloading" || state == "installing";
        progress.fraction = lookup_double (v, "progress");
        feature_status.visible = true;
        feature_status.remove_css_class (Granite.CssClass.ERROR);
        feature_status.add_css_class (Granite.CssClass.DIM);
        if (state == "downloading") {
            feature_status.label = _("Téléchargement…");
        } else if (state == "installing") {
            feature_status.label = _("Installation… Votre mot de passe peut être demandé.");
        } else if (state == "error" && error != "") {
            feature_status.label = error;
            feature_status.remove_css_class (Granite.CssClass.DIM);
            feature_status.add_css_class (Granite.CssClass.ERROR);
        } else if (!can_install) {
            feature_status.label = _("Pas de paquet vérifiable pour cette version : installez-la depuis GitHub.");
        } else {
            feature_status.visible = false;
        }
        update_button.label = can_install ? _("Mettre à jour maintenant") : _("Voir sur GitHub");
        update_button.sensitive = !busy;
    }

    private void on_update_clicked () {
        var v = daemon.get_value ("Update");
        if (v != null && lookup_string (v, "state") == "ready") {
            restart ();
        } else if (v != null && lookup_bool (v, "can_install", false)) {
            install.begin ();
        } else if (url != "") {
            new Gtk.UriLauncher (url).launch.begin (get_root () as Gtk.Window, null);
        }
    }

    private async void install () {
        update_button.sensitive = false;
        try {
            yield daemon.call_checked ("InstallUpdate");
        } catch (Error e) {
            DBusError.strip_remote_error (e);
            feature_status.label = e.message;
            feature_status.visible = true;
            update_button.sensitive = true;
        }
    }

    private async void check_now () {
        check_button.sensitive = false;
        try {
            yield daemon.call_checked ("CheckUpdates");
        } catch (Error e) {
            DBusError.strip_remote_error (e);
            status_label.label = e.message;
        }
        check_button.sensitive = true;
    }

    /* New daemon from the service manager, then this app started again once it has quit. */
    private void restart () {
        daemon.call.begin ("RestartDaemon");
        var path = Environment.find_program_in_path (Config.APP_ID)
            ?? Path.build_filename (Config.BINDIR, Config.APP_ID);
        try {
            Process.spawn_async (null, { "sh", "-c", "sleep 2; exec \"$0\"", path }, null,
                                 SpawnFlags.SEARCH_PATH, null, null);
        } catch (SpawnError e) {
            warning ("cannot start Covalence again: %s", e.message);
            return;
        }
        GLib.Application.get_default ().quit ();
    }

    /* The release notes are Markdown: a few plain lines are enough here. */
    private static string short_notes (string markdown) {
        var text = new StringBuilder ();
        foreach (var raw in markdown.split ("\n")) {
            var line = raw.strip ();
            if (line == "" || line.has_prefix ("#") || line.has_prefix ("```") || line.has_prefix ("---")) {
                continue;
            }
            if (line.has_prefix ("- ") || line.has_prefix ("* ")) {
                line = "• " + line.substring (2);
            }
            line = line.replace ("**", "").replace ("`", "");
            if (text.len > 0) {
                text.append ("\n");
            }
            text.append (line);
            if (text.len >= NOTES_LENGTH) {
                break;
            }
        }
        var result = text.str;
        if (result.char_count () > NOTES_LENGTH) {
            result = result.substring (0, result.index_of_nth_char (NOTES_LENGTH)).strip () + "…";
        }
        return result;
    }

    private static string relative (int64 when) {
        var seconds = get_real_time () / 1000000 - when;
        if (seconds < 60) {
            return _("à l'instant");
        }
        if (seconds < 3600) {
            return _("il y a %d min").printf ((int) (seconds / 60));
        }
        if (seconds < 86400) {
            return _("il y a %d h").printf ((int) (seconds / 3600));
        }
        var date = new DateTime.from_unix_local (when);
        return _("le %s").printf (date.format ("%x"));
    }
}
