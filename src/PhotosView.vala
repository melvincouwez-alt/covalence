// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * Photos: import the iPhone's photos and videos over a USB cable
 * (covalenced/photos_usb.py, libimobiledevice). The page looks for the iPhone
 * every few seconds while it is on screen; nothing is written to the iPhone.
 */

public class Covalence.PhotosView : Gtk.Box {
    public Daemon daemon { get; construct; }

    private InstallBox install;
    private Gtk.Stack stack;
    private Gtk.Label device_label;
    private Gtk.Label pair_hint;
    private Gtk.Button pair_button;
    private Gtk.Button import_button;
    private Gtk.Switch heic;
    private Gtk.Label heic_hint;
    private Gtk.Box progress_box;
    private Gtk.ProgressBar bar;
    private Gtk.Label progress_label;
    private Gtk.Label result_label;
    private bool updating = false;
    private uint timer = 0;

    public PhotosView (Daemon daemon) {
        Object (daemon: daemon, orientation: Gtk.Orientation.VERTICAL, spacing: 0);
    }

    construct {
        Gtk.ScrolledWindow scroll;
        var content = PageHeader.column (out scroll);
        content.append (PageHeader.build (
            _("Photos"),
            _("Importez les photos et vidéos de l'iPhone par câble USB, plus vite qu'avec iCloud.")));

        install = new InstallBox ();
        install.installed.connect (() => daemon.call.begin ("RefreshPhotosUsb"));
        content.append (install);

        stack = new Gtk.Stack ();
        var unplugged = new Granite.Placeholder (_("Branchez l'iPhone")) {
            description = _("Reliez l'iPhone à ce PC avec un câble USB, puis déverrouillez-le."),
            icon = new ThemedIcon ("phone")
        };
        stack.add_named (unplugged, "unplugged");

        var device_box = new Gtk.Box (Gtk.Orientation.VERTICAL, 12);
        device_label = new Gtk.Label ("") { xalign = 0 };
        device_label.add_css_class (Granite.HeaderLabel.Size.H3.to_string ());
        device_box.append (device_label);

        pair_hint = new Gtk.Label (
            _("Cet iPhone ne fait pas encore confiance à ce PC. Touchez « Faire confiance », puis "
              + "« Se fier » sur l'iPhone et saisissez son code.")
        ) { xalign = 0, wrap = true };
        pair_button = new Gtk.Button.with_label (_("Faire confiance")) { halign = Gtk.Align.START };
        pair_button.add_css_class (Granite.CssClass.SUGGESTED);
        pair_button.clicked.connect (() => daemon.call.begin ("PairPhotosUsb"));
        device_box.append (pair_hint);
        device_box.append (pair_button);

        import_button = new Gtk.Button.with_label (_("Importer les photos")) { halign = Gtk.Align.START };
        import_button.add_css_class (Granite.CssClass.SUGGESTED);
        import_button.clicked.connect (() => daemon.call.begin ("ImportPhotosUsb"));
        device_box.append (import_button);

        var heic_title = new Gtk.Label (_("Convertir les photos HEIC en JPEG")) { xalign = 0 };
        heic_hint = new Gtk.Label ("") { xalign = 0, wrap = true };
        heic_hint.add_css_class (Granite.CssClass.DIM);
        heic_hint.add_css_class (Granite.CssClass.SMALL);
        var heic_text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        heic_text.append (heic_title);
        heic_text.append (heic_hint);
        heic = new Gtk.Switch () { valign = Gtk.Align.CENTER };
        heic.update_property (Gtk.AccessibleProperty.LABEL, heic_title.label, -1);
        heic.notify["active"].connect (() => {
            if (!updating) {
                daemon.call.begin ("SetConvertHeic", new Variant ("(b)", heic.active));
            }
        });
        var heic_line = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9,
            margin_bottom = 9,
            margin_start = 12,
            margin_end = 12
        };
        heic_line.append (heic_text);
        heic_line.append (heic);
        var options = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE };
        options.add_css_class (Granite.CssClass.CARD);
        options.append (new Gtk.ListBoxRow () { child = heic_line, activatable = false });
        device_box.append (options);

        progress_box = new Gtk.Box (Gtk.Orientation.VERTICAL, 6);
        bar = new Gtk.ProgressBar ();
        progress_label = new Gtk.Label ("") { xalign = 0, hexpand = true };
        var cancel = new Gtk.Button.with_label (_("Arrêter")) { valign = Gtk.Align.CENTER };
        cancel.clicked.connect (() => daemon.call.begin ("CancelPhotosUsb"));
        var line = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12);
        line.append (progress_label);
        line.append (cancel);
        progress_box.append (line);
        progress_box.append (bar);
        device_box.append (progress_box);

        result_label = new Gtk.Label ("") { xalign = 0, wrap = true };
        device_box.append (result_label);

        var folder = new Gtk.Button.with_label (_("Ouvrir le dossier des photos")) { halign = Gtk.Align.START };
        folder.clicked.connect (() => {
            var path = Props.str (daemon.get_value ("PhotosUsb"), "folder");
            DirUtils.create_with_parents (path, 0755);
            new Gtk.FileLauncher (File.new_for_path (path)).launch.begin (get_root () as Gtk.Window, null);
        });
        device_box.append (folder);
        stack.add_named (device_box, "device");
        content.append (stack);
        append (scroll);

        daemon.changed.connect (update);
        map.connect (() => {
            daemon.call.begin ("RefreshPhotosUsb");
            timer = Timeout.add_seconds (5, () => {
                var state = Props.str (daemon.get_value ("PhotosUsb"), "state");
                if (state != "importing" && state != "pairing") {
                    daemon.call.begin ("RefreshPhotosUsb");
                }
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
        var photos = daemon.get_value ("PhotosUsb");
        var missing = Props.strings (photos, "missing");
        install.set_missing (missing, _("L'import par câble"));
        stack.visible = missing.length == 0;
        var udid = Props.str (photos, "udid");
        stack.visible_child_name = udid != "" ? "device" : "unplugged";
        var state = Props.str (photos, "state");
        var paired = Props.flag (photos, "paired");
        device_label.label = Props.str (photos, "device");
        pair_hint.visible = !paired;
        pair_button.visible = !paired;
        pair_button.sensitive = state != "pairing";
        pair_button.label = state == "pairing" ? _("En attente de l'iPhone…") : _("Faire confiance");
        import_button.visible = paired;
        import_button.sensitive = state != "importing";
        var tool = Props.flag (photos, "heic_tool");
        updating = true;
        heic.active = Props.flag (photos, "convert_heic");
        updating = false;
        heic.sensitive = tool;
        heic_hint.label = tool ? _("Plus compatible, un peu moins léger. Sinon les HEIC sont gardées telles quelles.")
                               : _("Demande l'outil heif-convert (paquet libheif-examples).");
        var total = Props.count (photos, "total");
        var done = Props.count (photos, "done");
        progress_box.visible = state == "importing";
        bar.fraction = total > 0 ? (double) done / total : 0;
        progress_label.label = total > 0 ? _("%u sur %u").printf (done, total) : _("Préparation…");
        var error = Props.str (photos, "error");
        var imported = Props.count (photos, "imported");
        var skipped = Props.count (photos, "skipped");
        if (state == "done") {
            result_label.label = _("%u importées, %u déjà présentes.").printf (imported, skipped);
        } else if (state == "error" && error == "pairing") {
            result_label.label = _("L'iPhone n'a pas confirmé. Déverrouillez-le et réessayez.");
        } else if (state == "error") {
            result_label.label = _("Import impossible. Déverrouillez l'iPhone et réessayez.");
        } else {
            result_label.label = "";
        }
        result_label.visible = result_label.label != "";
    }
}
