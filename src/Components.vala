// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Melvin Couwez
/*
 * System components Covalence needs (BlueZ, obexd, EDS typelibs, PipeWire…).
 *
 * Detection runs `covalenced --check-components` (covalenced/components.py), which
 * works even when the daemon cannot start. Installing goes through PackageKit
 * on the system bus (Resolve, then InstallPackages): the system asks for the
 * administrator password itself, and nothing is installed without a click.
 * rclone (iCloud Drive and Photos) is not packaged recently enough everywhere: on a
 * click, `covalenced --fetch-rclone` downloads the official build (rclone_fetch.py).
 * COVALENCE_COMPONENTS_DEMO=1 shows two made-up missing components (screenshots).
 */

public class Covalence.Component : Object {
    public string package { get; construct; }
    public string label { get; construct; }
    public bool installable { get; construct; }
    /* Covalence downloads it itself, on request (rclone). */
    public bool downloadable { get; construct; }

    public Component (string package, string label, bool installable, bool downloadable = false) {
        Object (package: package, label: label, installable: installable, downloadable: downloadable);
    }

    public static async Component[] detect () {
        Component[] found = {};
        if (Environment.get_variable ("COVALENCE_COMPONENTS_DEMO") == "1") {
            found += new Component ("bluez-obexd", _("Messages et contacts par Bluetooth (obexd)"), true);
            found += new Component ("gir1.2-ebook-1.2", _("Contacts iCloud"), true);
            found += new Component ("rclone", _("iCloud Drive et iCloud Photos (rclone 1.69 ou plus récent)"),
                                    false, true);
            return found;
        }
        try {
            var process = new Subprocess (SubprocessFlags.STDOUT_PIPE | SubprocessFlags.STDERR_SILENCE,
                                          Path.build_filename (Config.BINDIR, "covalenced"), "--check-components");
            string output;
            yield process.communicate_utf8_async (null, null, out output, null);
            foreach (var line in (output ?? "").split ("\n")) {
                var fields = line.split ("\t");
                if (fields.length == 3) {
                    found += new Component (fields[0], fields[1], fields[2] == "1", fields[2] == "2");
                }
            }
        } catch (Error e) {
            warning ("component check failed: %s", e.message);
        }
        return found;
    }
}

/* Minimal PackageKit client: one transaction per call, waits for Finished. */
public class Covalence.PackageInstaller : Object {
    private const string PK = "org.freedesktop.PackageKit";
    private const string TRANSACTION = "org.freedesktop.PackageKit.Transaction";
    // PkFilterEnum bits: NOT_INSTALLED (3), NEWEST (16), ARCH (18).
    private const uint64 FILTER = (1 << 3) | (1 << 16) | (1 << 18);
    private const uint64 ONLY_TRUSTED = 1 << 1;
    private const uint EXIT_SUCCESS = 1;
    private const uint EXIT_CANCELLED = 3;

    /* 0 to 100, or -1 when PackageKit does not know yet. */
    public signal void progress (int percent);

    /* Package ids for names that are not installed yet. */
    public async string[] resolve (string[] names) throws Error {
        return yield transact ("Resolve", new Variant ("(t^as)", FILTER, names));
    }

    public async void install (string[] names) throws Error {
        var ids = yield resolve (names);
        if (ids.length == 0) {
            throw new IOError.NOT_FOUND (_("Aucun de ces paquets n'est disponible dans les sources de logiciels."));
        }
        yield transact ("InstallPackages", new Variant ("(t^as)", ONLY_TRUSTED, ids));
    }

    private async string[] transact (string method, Variant parameters) throws Error {
        var bus = yield Bus.get (BusType.SYSTEM);
        var reply = yield bus.call (PK, "/org/freedesktop/PackageKit", PK, "CreateTransaction", null,
                                    new VariantType ("(o)"), DBusCallFlags.NONE, -1, null);
        string path;
        reply.get ("(o)", out path);

        var ids = new GenericArray<string> ();
        string? failure = null;
        uint exit = 0;
        bool finished = false;
        var subscription = bus.signal_subscribe (PK, null, null, path, null, DBusSignalFlags.NONE,
            (conn, sender, object, iface, name, args) => {
                if (name == "Package") {
                    uint info;
                    string id;
                    string summary;
                    args.get ("(uss)", out info, out id, out summary);
                    ids.add (id);
                } else if (name == "ErrorCode") {
                    uint code;
                    string details;
                    args.get ("(us)", out code, out details);
                    failure = details;
                } else if (name == "PropertiesChanged") {
                    string changed_iface;
                    VariantIter changed;
                    VariantIter invalidated;
                    args.get ("(sa{sv}as)", out changed_iface, out changed, out invalidated);
                    string key;
                    Variant value;
                    while (changed.next ("{sv}", out key, out value)) {
                        if (key == "Percentage") {
                            var percent = (int) value.get_uint32 ();
                            progress (percent > 100 ? -1 : percent);
                        }
                    }
                } else if (name == "Finished") {
                    uint runtime;
                    args.get ("(uu)", out exit, out runtime);
                    if (!finished) {
                        finished = true;
                        Idle.add (transact.callback);
                    }
                }
            });
        try {
            string[] hints = { "interactive=true", "locale=" + (Environment.get_variable ("LANG") ?? "C") };
            yield bus.call (PK, path, TRANSACTION, "SetHints", new Variant ("(^as)", hints),
                            null, DBusCallFlags.NONE, -1, null);
            // Interactive: the polkit password prompt may take the user a while.
            yield bus.call (PK, path, TRANSACTION, method, parameters, null,
                            DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION, int.MAX, null);
            if (!finished) {
                yield;
            }
        } finally {
            bus.signal_unsubscribe (subscription);
        }
        if (exit == EXIT_CANCELLED) {
            throw new IOError.CANCELLED (_("Installation annulée."));
        }
        if (exit != EXIT_SUCCESS) {
            throw new IOError.FAILED (failure ?? _("PackageKit a signalé un échec."));
        }
        return ids.data;
    }
}

/* "Composants manquants": hidden when everything is there. */
public class Covalence.ComponentsCard : Gtk.Box {
    private Gtk.ListBox list;
    private Gtk.Label status;
    private Gtk.ProgressBar bar;
    private Gtk.Button install;
    private string[] installable = {};

    construct {
        orientation = Gtk.Orientation.VERTICAL;
        spacing = 6;
        visible = false;

        list = new Gtk.ListBox () { selection_mode = Gtk.SelectionMode.NONE, show_separators = true };
        list.add_css_class (Granite.CssClass.CARD);

        status = new Gtk.Label ("") { xalign = 0, wrap = true, hexpand = true };
        status.add_css_class (Granite.CssClass.DIM);
        status.add_css_class (Granite.CssClass.SMALL);
        bar = new Gtk.ProgressBar () { visible = false, valign = Gtk.Align.CENTER, hexpand = true };
        install = new Gtk.Button.with_label (_("Installer")) { valign = Gtk.Align.CENTER };
        install.add_css_class (Granite.CssClass.SUGGESTED);
        install.clicked.connect (() => run_install.begin ());
        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 6) { hexpand = true, valign = Gtk.Align.CENTER };
        text.append (status);
        text.append (bar);
        var footer = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) { margin_top = 3 };
        footer.append (text);
        footer.append (install);

        append (new Granite.HeaderLabel (_("Composants manquants")));
        append (list);
        append (footer);
        refresh.begin ();
    }

    public async void refresh () {
        var found = yield Component.detect ();
        Gtk.Widget? child;
        while ((child = list.get_first_child ()) != null) {
            list.remove (child);
        }
        string[] names = {};
        bool others = false;
        foreach (var component in found) {
            list.append (row (component));
            others = others || !component.downloadable;
            if (component.installable) {
                names += component.package;
            }
        }
        installable = names;
        install.visible = names.length > 0;
        status.label = names.length > 0
            ? _("Covalence a besoin de ces paquets pour fonctionner entièrement. Le système demandera "
              + "le mot de passe administrateur.")
            : others ? _("Ces éléments demandent une version plus récente du système.")
            : _("Covalence peut télécharger cet outil pour vous.");
        visible = found.length > 0;
    }

    private Gtk.Widget row (Component component) {
        var image = new Gtk.Image.from_icon_name (component.installable || component.downloadable
                                                  ? "dialog-warning" : "dialog-error") {
            pixel_size = 32
        };
        var title = new Gtk.Label (component.label) { xalign = 0, wrap = true };
        var detail = new Gtk.Label (component.downloadable
                                    ? _("Téléchargé depuis rclone.org (licence MIT), vérifié par empreinte SHA-256")
                                    : component.installable
                                    ? _("Paquet %s").printf (component.package)
                                    : _("Mise à jour du système nécessaire (%s)").printf (component.package)) {
            xalign = 0,
            wrap = true
        };
        detail.add_css_class (Granite.CssClass.DIM);
        detail.add_css_class (Granite.CssClass.SMALL);
        var text = new Gtk.Box (Gtk.Orientation.VERTICAL, 2) { hexpand = true, valign = Gtk.Align.CENTER };
        text.append (title);
        text.append (detail);
        var box = new Gtk.Box (Gtk.Orientation.HORIZONTAL, 12) {
            margin_top = 9,
            margin_bottom = 9,
            margin_start = 12,
            margin_end = 12
        };
        box.append (image);
        box.append (text);
        if (component.downloadable) {
            var fetch = new Gtk.Button.with_label (_("Télécharger rclone")) { valign = Gtk.Align.CENTER };
            fetch.clicked.connect (() => run_fetch.begin (fetch, detail));
            box.append (fetch);
        }
        return new Gtk.ListBoxRow () { child = box, activatable = false };
    }

    private async void run_install () {
        install.sensitive = false;
        bar.visible = true;
        bar.fraction = 0;
        status.label = _("Installation…");
        uint pulse = Timeout.add (150, () => {
            bar.pulse ();
            return Source.CONTINUE;
        });
        var installer = new PackageInstaller ();
        installer.progress.connect ((percent) => {
            if (percent >= 0 && pulse != 0) {
                Source.remove (pulse);
                pulse = 0;
            }
            if (percent >= 0) {
                bar.fraction = percent / 100.0;
            }
        });
        string? failure = null;
        try {
            yield installer.install (installable);
        } catch (Error e) {
            failure = e.message;
        }
        if (pulse != 0) {
            Source.remove (pulse);
        }
        bar.visible = false;
        install.sensitive = true;
        if (failure == null) {
            restart_daemon ();
        }
        yield refresh ();
        if (failure != null) {
            status.label = _("L'installation n'a pas abouti : %s").printf (failure);
        }
    }

    /* covalenced --fetch-rclone: "progress N" lines, then "ok VERSION"; errors on stderr. */
    private async void run_fetch (Gtk.Button button, Gtk.Label detail) {
        button.sensitive = false;
        detail.label = _("Téléchargement…");
        string? failure = null;
        try {
            var process = new Subprocess (SubprocessFlags.STDOUT_PIPE | SubprocessFlags.STDERR_PIPE,
                                          Path.build_filename (Config.BINDIR, "covalenced"), "--fetch-rclone");
            var lines = new DataInputStream (process.get_stdout_pipe ());
            string? line;
            while ((line = yield lines.read_line_utf8_async ()) != null) {
                if (line.has_prefix ("progress ")) {
                    detail.label = _("Téléchargement… %s %%").printf (line.substring (9));
                }
            }
            var errors = new DataInputStream (process.get_stderr_pipe ());
            var message = yield errors.read_line_utf8_async ();
            yield process.wait_async ();
            if (!process.get_successful ()) {
                failure = message ?? _("échec du téléchargement");
            }
        } catch (Error e) {
            failure = e.message;
        }
        button.sensitive = true;
        if (failure != null) {
            detail.label = _("Le téléchargement n'a pas abouti : %s").printf (failure);
            return;
        }
        yield refresh ();
    }

    /* The daemon loads obexd, typelibs and PipeWire at start: restart it on the new components. */
    private static void restart_daemon () {
        try {
            new Subprocess (SubprocessFlags.NONE, "systemctl", "--user", "restart", "covalenced.service");
        } catch (Error e) {
            warning ("cannot restart covalenced: %s", e.message);
        }
    }
}
