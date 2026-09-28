// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * Fichiers: send and receive files with the free LocalSend app of the iPhone
 * (covalenced/files.py, covalenced/localsend.py). Off until turned on here: it
 * listens on the local network. Incoming files are always asked for in a
 * notification; files are sent by dropping them on a device or with a button.
 */

public class Covalence.FilesView : Gtk.Box {
    public Daemon daemon { get; construct; }

    private Gtk.Switch toggle;
    private Gtk.Label state_label;
    private Gtk.Box on_box;
    private Gtk.ListBox peers;
    private Granite.Placeholder no_peer;
    private Gtk.Box activity_box;
    private Gtk.Label activity_label;
    private Gtk.ProgressBar activity_bar;
    private bool updating = false;
    private uint peer_count = uint.MAX;
    private uint timer = 0;

    public FilesView (Daemon daemon) {
        Object (daemon: daemon, orientation: Gtk.Orientation.VERTICAL, spacing: 0);
    }

    construct {
        Gtk.ScrolledWindow scroll;
        var content = PageHeader.column (out scroll);
        content.append (PageHeader.build (
            _("Fichiers"),
            _("Échangez des fichiers avec l'app gratuite LocalSend de l'iPhone, sur le même Wi-Fi.")));

        var title = new Gtk.Label (_("Recevoir et envoyer avec LocalSend")) { xalign = 0 };
        state_label = new Gtk.Label ("") { xalign = 0, wrap = true };
        state_label.add_css_class (Granite.CssClass.DIM);
        state_label.add_css_class (Granite.CssClass.SMALL);
        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        text.append (title);
        text.append (state_label);
        toggle = new Gtk.Switch () { valign = Gtk.Align.CENTER };
        toggle.update_property (Gtk.AccessibleProperty.LABEL, title.label, -1);
        toggle.notify["active"].connect (() => {
            if (!updating) {
                daemon.call.begin ("SetLocalSend", new Variant ("(b)", toggle.active));
            }
        });
        var switch_line = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9,
            margin_bottom = 9,
            margin_start = 12,
            margin_end = 12
        };
        switch_line.append (text);
        switch_line.append (toggle);
        var switch_card = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE };
        switch_card.add_css_class (Granite.CssClass.CARD);
        switch_card.append (new Gtk.ListBoxRow () { child = switch_line, activatable = false });
        content.append (switch_card);

        var privacy = new Gtk.Label (
            _("Tant que c'est activé, Covalence écoute le réseau local (port 53317). Chaque envoi vers "
              + "ce PC vous est demandé, sauf depuis un appareil que vous avez choisi de toujours accepter.")
        ) { xalign = 0, wrap = true };
        privacy.add_css_class (Granite.CssClass.DIM);
        privacy.add_css_class (Granite.CssClass.SMALL);
        content.append (privacy);

        on_box = new Gtk.Box (Gtk.Orientation.VERTICAL, 12);
        activity_label = new Gtk.Label ("") { xalign = 0, hexpand = true, ellipsize = Pango.EllipsizeMode.END };
        activity_bar = new Gtk.ProgressBar ();
        var cancel = new Gtk.Button.with_label (_("Annuler")) { valign = Gtk.Align.CENTER };
        cancel.clicked.connect (() => daemon.call.begin ("CancelFiles"));
        var activity_line = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12);
        activity_line.append (activity_label);
        activity_line.append (cancel);
        activity_box = new Gtk.Box (Gtk.Orientation.VERTICAL, 6) { visible = false };
        activity_box.append (activity_line);
        activity_box.append (activity_bar);
        on_box.append (activity_box);

        var refresh = new Gtk.Button.from_icon_name ("view-refresh-symbolic") {
            tooltip_text = _("Rechercher les appareils")
        };
        refresh.add_css_class ("flat");
        refresh.clicked.connect (() => {
            daemon.call.begin ("RefreshFilePeers");
            Timeout.add_seconds (2, () => {
                load_peers.begin ();
                return Source.REMOVE;
            });
        });
        var peers_header = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 6);
        peers_header.append (new Granite.HeaderLabel (_("Appareils LocalSend")) { hexpand = true });
        peers_header.append (refresh);
        on_box.append (peers_header);

        peers = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
        peers.add_css_class (Granite.CssClass.CARD);
        no_peer = new Granite.Placeholder (_("Aucun appareil trouvé")) {
            description = _("Ouvrez LocalSend sur l'iPhone, connecté au même Wi-Fi que ce PC. "
                            + "LocalSend est gratuit sur l'App Store (localsend.org)."),
            icon = new ThemedIcon ("document-send")
        };
        peers.set_placeholder (no_peer);
        on_box.append (peers);

        var folder = new Gtk.Button.with_label (_("Ouvrir le dossier de réception")) { halign = Gtk.Align.START };
        folder.clicked.connect (() => {
            var path = Props.str (daemon.get_value ("Files"), "folder");
            DirUtils.create_with_parents (path, 0755);
            new Gtk.FileLauncher (File.new_for_path (path)).launch.begin (get_root () as Gtk.Window, null);
        });
        on_box.append (folder);
        content.append (on_box);
        append (scroll);

        daemon.changed.connect (update);
        map.connect (() => {
            load_peers.begin ();
            timer = Timeout.add_seconds (10, () => {
                load_peers.begin ();
                return Source.CONTINUE;
            });
        });
        unmap.connect (() => {
            if (timer != 0) {
                Source.remove (timer);
                timer = 0;
            }
        });
        update ();
    }

    private void update () {
        var files = daemon.get_value ("Files");
        var enabled = Props.flag (files, "enabled");
        updating = true;
        toggle.active = enabled;
        updating = false;
        var error = Props.str (files, "error");
        if (!enabled) {
            state_label.label = _("Désactivé");
        } else if (error != "") {
            state_label.label = error;
        } else {
            state_label.label = _("Visible sous le nom « %s »").printf (Props.str (files, "alias"));
        }
        on_box.visible = enabled && error == "";
        var activity = Props.str (files, "activity");
        activity_box.visible = activity != "";
        activity_label.label = activity;
        activity_bar.fraction = Props.number (files, "progress");
        var count = Props.count (files, "peers");
        if (count != peer_count) {
            peer_count = count;
            load_peers.begin ();
        }
    }

    private async void load_peers () {
        var list = yield daemon.call_list ("ListFilePeers");
        Gtk.Widget? child;
        while ((child = peers.get_first_child ()) != null) {
            if (child is Gtk.ListBoxRow) {
                peers.remove (child);
            } else {
                break;
            }
        }
        foreach (var item in list) {
            var peer = new VariantDict (item);
            peers.append (peer_row (peer));
        }
    }

    private Gtk.Widget peer_row (VariantDict peer) {
        string id = "", alias = "", model = "", kind = "";
        peer.lookup ("id", "s", out id);
        peer.lookup ("alias", "s", out alias);
        peer.lookup ("model", "s", out model);
        peer.lookup ("type", "s", out kind);
        var icon = new Gtk.Image.from_icon_name (kind == "mobile" ? "phone" : "computer") { pixel_size = 32 };
        var name = new Gtk.Label (alias) { xalign = 0, ellipsize = Pango.EllipsizeMode.END };
        var detail = new Gtk.Label (model != "" ? model : _("Déposez des fichiers ici pour les envoyer")) {
            xalign = 0
        };
        detail.add_css_class (Granite.CssClass.DIM);
        detail.add_css_class (Granite.CssClass.SMALL);
        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        text.append (name);
        text.append (detail);
        var send = new Gtk.Button.with_label (_("Envoyer des fichiers…")) { valign = Gtk.Align.CENTER };
        send.clicked.connect (() => choose_files.begin (id));
        var line = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9,
            margin_bottom = 9,
            margin_start = 12,
            margin_end = 12
        };
        line.append (icon);
        line.append (text);
        line.append (send);
        var row = new Gtk.ListBoxRow () { child = line, activatable = false };
        var drop = new Gtk.DropTarget (typeof (Gdk.FileList), Gdk.DragAction.COPY);
        drop.drop.connect ((value) => {
            string[] paths = {};
            foreach (var file in ((Gdk.FileList) value).get_files ()) {
                if (file.get_path () != null) {
                    paths += file.get_path ();
                }
            }
            send_paths.begin (id, paths);
            return true;
        });
        row.add_controller (drop);
        return row;
    }

    private async void choose_files (string peer) {
        var dialog = new Gtk.FileDialog () { title = _("Fichiers à envoyer"), modal = true };
        try {
            var chosen = yield dialog.open_multiple (get_root () as Gtk.Window, null);
            string[] paths = {};
            for (uint i = 0; i < chosen.get_n_items (); i++) {
                var file = (File) chosen.get_item (i);
                if (file.get_path () != null) {
                    paths += file.get_path ();
                }
            }
            yield send_paths (peer, paths);
        } catch (Error e) {
            // dismissed
        }
    }

    private async void send_paths (string peer, string[] paths) {
        if (paths.length == 0) {
            return;
        }
        try {
            yield daemon.call_checked ("SendFiles", new Variant ("(s^as)", peer, paths));
        } catch (Error e) {
            var message = e.message;
            if (e is DBusError) {
                DBusError.strip_remote_error (e);
                message = e.message;
            }
            var dialog = new Granite.MessageDialog.with_image_from_icon_name (
                _("Envoi impossible"), message, "dialog-warning", Gtk.ButtonsType.CLOSE) {
                transient_for = get_root () as Gtk.Window,
                modal = true
            };
            dialog.response.connect (() => dialog.destroy ());
            dialog.present ();
        }
    }
}
